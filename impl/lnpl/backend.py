"""Execution mode B — Semantic IR -> MLIR -> LLVM IR -> native binary.

RFC-0004 stages S4-S7. One deviation from the RFC is recorded here and in
docs/ROADMAP.md: **S4 emits standard MLIR dialects directly, not the custom
`lnpl` dialect.** Registering a custom dialect with `mlir-opt` requires a C++
TableGen build against MLIR's development libraries; until that exists, the
`lnpl` dialect's purpose — hosting the high-level passes — is served at the
Semantic IR level by S3, which mode A already performs. Deferring it therefore
does not weaken the equivalence claim, but it is a real gap, not a design choice.

What this module emits is a `func` + `scf` + `arith` module that reproduces the
workflow's **observable** behaviour: the step order, the policy outcomes, and the
exit status. The effects themselves call into a small C runtime shim (printf-based
trace) so the native binary emits the same span/step lines mode A does — that is
what the differential check compares.

Pipeline:

    IR --emit_mlir--> .mlir --mlir-opt--> LLVM dialect --mlir-translate--> .ll
        --clang--> native binary
"""

import json
import os
import shutil
import subprocess
import tempfile

from lnpl.condition import parse_condition, Presence, Comparison

MLIR_OPT = "mlir-opt"
MLIR_TRANSLATE = "mlir-translate"
BREW_LLVM_BIN = "/opt/homebrew/opt/llvm/bin"

# This file is <repo>/impl/lnpl/backend.py, so three dirnames reach the repo.
# The dialect definition is located from here rather than from the cwd, because
# `build()` runs against an arbitrary workdir while the tests run from the root.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
LNPL_IRDL_PATH = os.path.join(REPO_ROOT, "mlir", "lnpl.irdl.mlir")


class BackendError(Exception):
    """Raised when the native pipeline cannot run or produces an error."""


def tool(name):
    """Locate an LLVM/MLIR tool, preferring a keg-only homebrew install."""
    candidate = os.path.join(BREW_LLVM_BIN, name)
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    found = shutil.which(name)
    if found:
        return found
    raise BackendError(
        "%s not found. Mode B needs MLIR/LLVM tools — install them with "
        "`brew install llvm` (they land in %s)." % (name, BREW_LLVM_BIN))


def toolchain_available():
    for name in (MLIR_OPT, MLIR_TRANSLATE, "clang"):
        try:
            tool(name)
        except BackendError:
            return False
    return True


def verify_lnpl_module(text, stage="S4 (lnpl dialect verification)", path=None):
    """Run the `lnpl` dialect's verifier over a module; return the round trip.

    With `path`, the file at that path is verified **in place** — so the artifact
    `build()` wrote is the object that actually gets checked, and a failure names
    the file the caller can go read. Without it, `text` is staged under the repo's
    own tmp directory (never the system temp dir) and removed afterwards.

    `--mlir-print-debuginfo` is not cosmetic: without it `mlir-opt` prints no
    `loc(...)` at all, so the round trip could not show that the Location half of
    RFC-0004's two traceability paths survived. The `lnpl.node_id` attribute is
    discardable by design, which is exactly why the Location must be observable.
    """
    staged = None
    if path is None:
        tmpdir = os.path.join(REPO_ROOT, ".claude", "tmp")
        os.makedirs(tmpdir, exist_ok=True)
        # mkstemp, not a fixed name: builds can run concurrently.
        fd, staged = tempfile.mkstemp(dir=tmpdir, suffix=".lnpl.mlir")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        target = staged
    else:
        target = path

    try:
        return _run([tool(MLIR_OPT), "--irdl-file", LNPL_IRDL_PATH,
                     "--mlir-print-debuginfo", target], stage)
    finally:
        if staged is not None:
            os.remove(staged)


def _extract_condition_field(cond_str):
    """RFC-0008 G8: Extract field name from condition string.

    Returns (field_name, op, value) for Comparison or (field_name, 'exists'|'missing') for Presence.
    Used to populate lnpl_run parameter list and generate arith.cmpi code.
    """
    try:
        cond = parse_condition(cond_str)
    except Exception:
        return None

    if isinstance(cond, Presence):
        return (cond.field, cond.kind)  # (field, 'exists'|'missing')
    elif isinstance(cond, Comparison):
        return (cond.field, cond.op, cond.value)  # (field, op, value_ms)
    return None


def _compile_condition(cond_str, field_var_name):
    """RFC-0008 G8: Compile condition to MLIR i1 predicate using field parameter.

    Args:
        cond_str: condition string (e.g., "counter >= 10")
        field_var_name: MLIR variable name for the field (e.g., "%counter")

    Returns:
        MLIR code that evaluates the condition (e.g., "%cond = arith.cmpi sge, %counter, %c10 : i64")
    """
    extracted = _extract_condition_field(cond_str)
    if not extracted:
        return None

    if len(extracted) == 2:  # Presence
        field, kind = extracted
        # Presence: check if field is not null/zero
        # For now, field existence is assumed true (parameter presence means it exists)
        return "%c1"
    elif len(extracted) == 3:  # Comparison
        field, op, value = extracted
        # Comparison: field op value (value is already in milliseconds if Duration)
        # Convert op to arith.cmpi predicate
        op_map = {
            '<': 'slt',
            '<=': 'sle',
            '>': 'sgt',
            '>=': 'sge',
            '==': 'eq',
            '!=': 'ne',
        }
        pred = op_map.get(op)
        if not pred:
            return "%c1"
        # Generate: %cond = arith.cmpi <pred>, %field, %const : i64
        return f"arith.cmpi {pred}, {field_var_name}, %c{value} : i64"
    return "%c1"


# ---- S4: Semantic IR -> MLIR (standard dialects) ---------------------------

_UNTIL_ROUND_CAP = 16


def _steps_in_order(nodes, ids, out):
    """Flatten the body the way mode A does, so both modes agree on step order.

    Guards are resolved at compile time only when their outcome is decidable from
    the IR alone; `when` is not, so a guarded step is emitted with a runtime flag
    the caller supplies. `repeat` and `until` are constants, so they unroll.

    RFC-0008 G10: until unrolls to _UNTIL_ROUND_CAP iterations (matching Mode A).
    Condition evaluation deferred to runtime (see _compile_condition).
    """
    for nid in ids:
        node = nodes[nid]
        kind = node["kind"]
        if kind == "WorkflowStep":
            out.append((node, None))
        elif kind in ("Concurrency", "Pipeline"):
            _steps_in_order(nodes, node.get("children", []), out)
        elif kind == "Guard":
            if node["mode"] == "repeat":
                for _ in range(int(node["count"])):
                    _steps_in_order(nodes, node.get("children", []), out)
            elif node["mode"] == "when":
                # RFC-0008 G9: when becomes arith.cmpi + scf.if
                inner = []
                _steps_in_order(nodes, node.get("children", []), inner)
                for step, _cond in inner:
                    out.append((step, ("when", node.get("condition"))))
            elif node["mode"] == "until":
                # RFC-0008 G10: until unrolls to round_cap (16) iterations.
                # Condition evaluation deferred; unrolling ensures Mode A ≈ Mode B.
                inner = []
                _steps_in_order(nodes, node.get("children", []), inner)
                for _ in range(_UNTIL_ROUND_CAP):
                    for step, _cond in inner:
                        out.append((step, ("until", node.get("condition"))))
            else:
                raise BackendError("unknown guard mode %r" % node["mode"])
        else:
            raise BackendError("workflow body cannot contain %s" % kind)
    return out


# `until c` repeats while c is false, so each unrolled round is guarded by the
# negation of the condition's comparison.
_NEGATED_CMP = {"<": "sge", "<=": "sgt", ">": "sle", ">=": "slt",
                "==": "ne", "!=": "eq"}


def _workflow_steps(document, workflow_id):
    nodes = {n["id"]: n for n in document["nodes"]}
    wf = nodes.get(workflow_id)
    if wf is None or wf["kind"] != "Workflow":
        raise BackendError("no such workflow: %r" % workflow_id)
    return nodes, _steps_in_order(nodes, wf.get("children", []), [])


def condition_field_names(document, workflow_id):
    """RFC-0008 G8: the ordered condition-field list `lnpl_run` takes as i64 params.

    Single source of truth. `emit_mlir` builds the signature from this, `runtime_c`
    declares and forwards exactly these, and `run_binary` supplies values in this
    order. C linkage matches on symbol name only, so if any of the three derived
    the list independently a disagreement would surface as an uninitialised
    register rather than a link error.
    """
    _, steps = _workflow_steps(document, workflow_id)
    fields = set()
    for _step, cond in steps:
        if cond and isinstance(cond, tuple) and len(cond) == 2:
            _mode, cond_str = cond
            extracted = _extract_condition_field(cond_str)
            if extracted:
                fields.add(extracted[0])
    return sorted(fields)


def encode_condition_value(value):
    """Coerce a condition-field value to the i64 the guard compares against.

    `bool` is accepted because it is an `int` in Python and 0/1 is a meaningful
    i64. Everything else non-integral is rejected rather than truncated, so a
    guard never silently compares against a rounded or coerced value.
    """
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return value
    raise BackendError(
        "condition field value must be an integer, got %r (%s)"
        % (value, type(value).__name__))


def emit_mlir(document, workflow_id):
    """Semantic IR -> textual MLIR using func/arith only (no custom dialect)."""
    nodes, steps = _workflow_steps(document, workflow_id)

    lines = [
        "// Generated from Semantic IR (lir_version %s, module %s) — do not edit."
        % (document["lir_version"], document["module"]),
        "// RFC-0004 S4-S5: standard dialects (func, arith). See backend.py for the",
        "// recorded deviation: the custom `lnpl` dialect is not yet registered.",
        "module {",
        '  func.func private @lnpl_step(!llvm.ptr, i32) -> i32',
        '  func.func private @lnpl_effect(!llvm.ptr, !llvm.ptr) -> ()',
        "",
    ]
    # String globals for the step and effect names.
    strings = {}

    def intern(text):
        if text not in strings:
            strings[text] = "s%d" % len(strings)
        return strings[text]

    for step, _cond in steps:
        intern(step["name"])
        for child_id in step.get("children", []):
            intern(nodes[child_id]["kind"])

    for text, sym in strings.items():
        encoded = text.replace('"', '\\"')
        lines.append('  llvm.mlir.global internal constant @%s("%s\\00")'
                     % (sym, encoded))
    lines.append("")

    # RFC-0008 G8: condition fields become i64 parameters, in the one order
    # condition_field_names defines (see its docstring for why that matters).
    params = ["%skip : i32"]
    for field in condition_field_names(document, workflow_id):
        params.append(f"%{field} : i64")
    params_str = ", ".join(params)

    lines.append(f"  func.func @lnpl_run({params_str}) -> i32 {{")
    lines.append("    %c0 = arith.constant 0 : i32")
    lines.append("    %c1 = arith.constant 1 : i32")

    # Declare i64 constants for condition comparisons
    # Collect all i64 values used in condition comparisons
    cond_i64_values = set()
    for step, cond in steps:
        if cond and isinstance(cond, tuple) and len(cond) == 2:
            mode, cond_str = cond
            extracted = _extract_condition_field(cond_str)
            if extracted and len(extracted) == 3:  # Comparison
                field, op, value = extracted
                cond_i64_values.add(value)

    # Declare all i64 constants upfront
    for value in sorted(cond_i64_values):
        lines.append(f"    %c{value}_i64 = arith.constant {value} : i64")

    for idx, (step, cond) in enumerate(steps, start=1):
        sym = strings[step["name"]]
        guard_mode = None
        guard_str = None

        if cond and isinstance(cond, tuple):
            guard_mode, guard_str = cond

        guard_desc = ""
        if guard_mode and guard_str:
            guard_desc = "  (guarded by `%s` %s)" % (guard_mode, guard_str)

        lines.append("    // step %d: %s%s"
                     % (idx, step["name"], guard_desc))
        lines.append("    %%p%d = llvm.mlir.addressof @%s : !llvm.ptr" % (idx, sym))
        lines.append("    %%i%d = arith.constant %d : i32" % (idx, idx))

        if guard_mode == "when":
            # RFC-0008 G8-G9: when becomes scf.if with condition evaluation
            extracted = _extract_condition_field(guard_str) if guard_str else None

            if extracted and len(extracted) == 3:  # Comparison
                field, op, value = extracted
                op_map = {'<': 'slt', '<=': 'sle', '>': 'sgt', '>=': 'sge', '==': 'eq', '!=': 'ne'}
                pred = op_map.get(op, 'eq')
                # Generate comparison: %cond_idx = arith.cmpi pred, %field, %const : i64
                # Use pre-declared constant %c<value>_i64
                lines.append(f"    %cond{idx} = arith.cmpi {pred}, %{field}, %c{value}_i64 : i64")
                lines.append(f"    scf.if %cond{idx} {{")
            else:
                # Presence or unparseable: use caller-supplied skip flag
                # skip=1 means "skip condition evaluation and execute", so we negate it
                lines.append("    %%skip%d = arith.cmpi eq, %%skip, %%c0 : i32" % idx)
                lines.append("    scf.if %%skip%d {" % idx)

            # RFC-0008: When condition is true, execute the guarded step
            lines.append("      %%r%d = func.call @lnpl_step(%%p%d, %%i%d) : "
                         "(!llvm.ptr, i32) -> i32" % (idx, idx, idx))
            for cn, child_id in enumerate(step.get("children", [])):
                ksym = strings[nodes[child_id]["kind"]]
                lines.append("      %%k%d_%d = llvm.mlir.addressof @%s : !llvm.ptr"
                             % (idx, cn, ksym))
                lines.append("      func.call @lnpl_effect(%%p%d, %%k%d_%d) : "
                             "(!llvm.ptr, !llvm.ptr) -> ()" % (idx, idx, cn))
            lines.append("    }")
        elif guard_mode == "until":
            # RFC-0008 G10 / issue #3. `_steps_in_order` has already unrolled the
            # loop to _UNTIL_ROUND_CAP, so what is left is to make each round obey
            # the condition instead of running unconditionally — which is what made
            # mode B behave as though the condition never became true.
            #
            # `until c` repeats *while `c` is false*, so each round is guarded by the
            # negation of c. Nothing in the IR mutates a condition field mid-run, so
            # c is constant across the workflow and this yields the same two outcomes
            # mode A can produce: zero rounds, or the cap.
            extracted = _extract_condition_field(guard_str) if guard_str else None
            round_guard = None
            if extracted and len(extracted) == 3:
                field, op, value = extracted
                negated = _NEGATED_CMP.get(op)
                if negated:
                    round_guard = ("    %%ucond%d = arith.cmpi %s, %%%s, %%c%s_i64 "
                                   ": i64" % (idx, negated, field, value))

            if round_guard:
                lines.append(round_guard)
                lines.append("    scf.if %%ucond%d {" % idx)
                body, close = "      ", ["    }"]
            else:
                # Presence or unparseable: no evaluator, so keep the previous
                # unconditional emission rather than inventing a decision.
                body, close = "    ", []

            lines.append("%s%%r%d = func.call @lnpl_step(%%p%d, %%i%d) : "
                         "(!llvm.ptr, i32) -> i32" % (body, idx, idx, idx))
            for cn, child_id in enumerate(step.get("children", [])):
                ksym = strings[nodes[child_id]["kind"]]
                lines.append("%s%%k%d_%d = llvm.mlir.addressof @%s : !llvm.ptr"
                             % (body, idx, cn, ksym))
                lines.append("%sfunc.call @lnpl_effect(%%p%d, %%k%d_%d) : "
                             "(!llvm.ptr, !llvm.ptr) -> ()" % (body, idx, idx, cn))
            lines.extend(close)
        else:
            # No guard: unconditional step
            lines.append("    %%r%d = func.call @lnpl_step(%%p%d, %%i%d) : "
                         "(!llvm.ptr, i32) -> i32" % (idx, idx, idx))
            for cn, child_id in enumerate(step.get("children", [])):
                ksym = strings[nodes[child_id]["kind"]]
                lines.append("    %%k%d_%d = llvm.mlir.addressof @%s : !llvm.ptr"
                             % (idx, cn, ksym))
                lines.append("    func.call @lnpl_effect(%%p%d, %%k%d_%d) : "
                             "(!llvm.ptr, !llvm.ptr) -> ()" % (idx, idx, cn))

    lines.append("    return %c0 : i32")
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


RUNTIME_C_HEADER = r"""/* Mode B runtime shim — generated, do not edit.
 * Emits the same observable step trace mode A does, so the differential check
 * compares behaviour rather than formatting.
 *
 * RFC-0008 G8: condition field values arrive as command-line arguments —
 * argv[1] is the skip flag and argv[2..] are the i64 condition fields, in the
 * order condition_field_names() defines. The declaration and the forwarding
 * below are generated from that same list, because C linkage matches on symbol
 * name only: a hand-written declaration that disagreed with the MLIR signature
 * would compile and link, then read an uninitialised register.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

int lnpl_step(const char *name, int index) {
  printf("step %d %s\n", index, name);
  return 0;
}

void lnpl_effect(const char *step, const char *kind) {
  printf("effect %s %s\n", step, kind);
}
"""


def runtime_c(field_names):
    """Generate the mode B shim for exactly `field_names` (ordered).

    Kept in lockstep with `emit_mlir` by taking the same list, so the arity and
    the positional meaning of `lnpl_run`'s parameters cannot drift.
    """
    decl_params = ", ".join(["int skip"] + ["int64_t %s" % f for f in field_names])
    reads = "\n".join(
        "  int64_t %s = (argc > %d) ? strtoll(argv[%d], NULL, 10) : 0;"
        % (f, i, i)
        for i, f in enumerate(field_names, start=2))
    call_args = ", ".join(["skip"] + list(field_names))
    fields_note = ", ".join("argv[%d]=%s" % (i, f)
                            for i, f in enumerate(field_names, start=2)) or "none"
    return (
        RUNTIME_C_HEADER
        + "\n/* Condition fields: %s */\n" % fields_note
        + "int lnpl_run(%s);\n\n" % decl_params
        + "int main(int argc, char **argv) {\n"
        + "  int skip = (argc > 1 && argv[1][0] == '1') ? 1 : 0;\n"
        + (reads + "\n" if reads else "")
        + "\n  int rc = lnpl_run(%s);\n" % call_args
        + '  printf("status %s\\n", rc == 0 ? "completed" : "failed");\n'
        + "  return rc;\n}\n")


def build(document, workflow_id, workdir, keep_intermediate=True):
    """Run S4-S7. Returns the path to the native binary."""
    os.makedirs(workdir, exist_ok=True)
    mlir_path = os.path.join(workdir, "module.mlir")
    llvm_dialect = os.path.join(workdir, "module.llvm.mlir")
    ll_path = os.path.join(workdir, "module.ll")
    c_path = os.path.join(workdir, "runtime.c")
    bin_path = os.path.join(workdir, "module")

    fields = condition_field_names(document, workflow_id)
    with open(mlir_path, "w", encoding="utf-8") as fh:
        fh.write(emit_mlir(document, workflow_id))
    with open(c_path, "w", encoding="utf-8") as fh:
        fh.write(runtime_c(fields))
    # Persist the parameter order next to the binary so run_binary binds values by
    # name instead of re-deriving an order that could disagree with the build.
    with open(_fields_path(bin_path), "w", encoding="utf-8") as fh:
        json.dump(fields, fh)

    # scf -> cf -> llvm: without --convert-cf-to-llvm the branches a `when` guard
    # produces stop at the cf dialect, and mlir-translate cannot read them.
    _run([tool(MLIR_OPT), mlir_path,
          "--convert-scf-to-cf", "--convert-cf-to-llvm",
          "--convert-func-to-llvm", "--convert-arith-to-llvm",
          "--reconcile-unrealized-casts",
          "-o", llvm_dialect], "S5-S6 (mlir-opt: standard dialects -> LLVM dialect)")
    _run([tool(MLIR_TRANSLATE), "--mlir-to-llvmir", llvm_dialect, "-o", ll_path],
         "S6 (mlir-translate: LLVM dialect -> LLVM IR)")
    _run([tool("clang"), ll_path, c_path, "-o", bin_path],
         "S7 (clang: LLVM IR + runtime -> native binary)")

    if not keep_intermediate:
        for path in (mlir_path, llvm_dialect, ll_path, c_path):
            os.remove(path)
    return bin_path


def _run(argv, stage):
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BackendError("%s failed (exit %d)\n$ %s\n%s"
                           % (stage, proc.returncode, " ".join(argv),
                              (proc.stderr or proc.stdout).strip()))
    return proc.stdout


def _fields_path(bin_path):
    return bin_path + ".fields.json"


def run_binary(bin_path, skip=False, condition_fields=None):
    """Execute the native binary; returns (exit_code, stdout lines).

    Args:
        bin_path: path to the binary
        skip: skip flag for Presence `when` guards
        condition_fields: field_name -> value (RFC-0008 G8). Values are bound by
            name to the parameter order recorded at build time, so extra keys are
            ignored and missing condition fields default to 0. Callers therefore
            cannot shift a value into the wrong parameter by passing an unrelated
            field.
    """
    args = [bin_path, "1" if skip else "0"]
    values = condition_fields or {}
    for name in values:
        encode_condition_value(values[name])   # reject non-integers up front

    try:
        with open(_fields_path(bin_path), encoding="utf-8") as fh:
            order = json.load(fh)
    except OSError:
        raise BackendError(
            "missing %s — the binary's condition-field order is recorded at build "
            "time; rebuild with build() rather than invoking a stale binary"
            % os.path.basename(_fields_path(bin_path)))

    for name in order:
        args.append(str(encode_condition_value(values.get(name, 0))))

    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, proc.stdout.splitlines()
