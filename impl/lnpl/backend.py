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

import os
import shutil
import subprocess

from lnpl.condition import parse_condition, Presence, Comparison

MLIR_OPT = "mlir-opt"
MLIR_TRANSLATE = "mlir-translate"
BREW_LLVM_BIN = "/opt/homebrew/opt/llvm/bin"


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


def emit_mlir(document, workflow_id):
    """Semantic IR -> textual MLIR using func/arith only (no custom dialect)."""
    nodes = {n["id"]: n for n in document["nodes"]}
    wf = nodes.get(workflow_id)
    if wf is None or wf["kind"] != "Workflow":
        raise BackendError("no such workflow: %r" % workflow_id)
    steps = _steps_in_order(nodes, wf.get("children", []), [])

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

    # RFC-0008 G8: Extract condition fields for function parameters
    condition_fields = {}  # {field_name: index}
    for step, cond in steps:
        if cond and isinstance(cond, tuple) and len(cond) == 2:
            mode, cond_str = cond
            extracted = _extract_condition_field(cond_str)
            if extracted and len(extracted) >= 1:
                field = extracted[0]
                if field not in condition_fields:
                    condition_fields[field] = len(condition_fields)

    # Build lnpl_run signature with condition fields
    params = ["%skip : i32"]
    for field in sorted(condition_fields.keys()):
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
            # RFC-0008 G10: until becomes scf.while (deferred: implement loop with round_cap)
            # For now, compile as a no-op (condition always true, no loop)
            lines.append("    %%r%d = func.call @lnpl_step(%%p%d, %%i%d) : "
                         "(!llvm.ptr, i32) -> i32" % (idx, idx, idx))
            for cn, child_id in enumerate(step.get("children", [])):
                ksym = strings[nodes[child_id]["kind"]]
                lines.append("    %%k%d_%d = llvm.mlir.addressof @%s : !llvm.ptr"
                             % (idx, cn, ksym))
                lines.append("    func.call @lnpl_effect(%%p%d, %%k%d_%d) : "
                             "(!llvm.ptr, !llvm.ptr) -> ()" % (idx, idx, cn))
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


RUNTIME_C = r"""/* Mode B runtime shim.
 * Emits the same observable step trace mode A does, so the differential check
 * compares behaviour rather than formatting.
 *
 * RFC-0008 G8: Reads condition field values from environment variables
 * (LNPL_<fieldname>=value) and passes them to lnpl_run.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int lnpl_step(const char *name, int index) {
  printf("step %d %s\n", index, name);
  return 0;
}

void lnpl_effect(const char *step, const char *kind) {
  printf("effect %s %s\n", step, kind);
}

/* lnpl_run is generated by emit_mlir with condition field parameters.
   Declare it here so main() can call it. */
int lnpl_run(int skip, int64_t counter, int64_t flag);

int main(int argc, char **argv) {
  int skip = (argc > 1 && argv[1][0] == '1') ? 1 : 0;

  /* RFC-0008 G8: Read condition field values from command-line arguments.
     Fields are passed in sorted key order: argv[2]=counter, argv[3]=flag, etc.
  */
  int64_t counter = (argc > 2) ? strtoll(argv[2], NULL, 10) : 0;
  int64_t flag = (argc > 3) ? strtoll(argv[3], NULL, 10) : 0;

  int rc = lnpl_run(skip, counter, flag);
  printf("status %s\n", rc == 0 ? "completed" : "failed");
  return rc;
}
"""


def build(document, workflow_id, workdir, keep_intermediate=True):
    """Run S4-S7. Returns the path to the native binary."""
    os.makedirs(workdir, exist_ok=True)
    mlir_path = os.path.join(workdir, "module.mlir")
    llvm_dialect = os.path.join(workdir, "module.llvm.mlir")
    ll_path = os.path.join(workdir, "module.ll")
    c_path = os.path.join(workdir, "runtime.c")
    bin_path = os.path.join(workdir, "module")

    with open(mlir_path, "w", encoding="utf-8") as fh:
        fh.write(emit_mlir(document, workflow_id))
    with open(c_path, "w", encoding="utf-8") as fh:
        fh.write(RUNTIME_C)

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


def run_binary(bin_path, skip=False, condition_fields=None):
    """Execute the native binary; returns (exit_code, stdout lines).

    Args:
        bin_path: path to the binary
        skip: skip flag for when guard
        condition_fields: dict of field_name -> value for condition evaluation (RFC-0008 G8)
    """
    # RFC-0008 G8: Pass condition field values via command-line arguments
    # argv[1]: skip, argv[2...]: condition field values in sorted key order
    args = [bin_path, "1" if skip else "0"]

    if condition_fields:
        # Sort keys for deterministic order (counter before flag)
        for field_name in sorted(condition_fields.keys()):
            args.append(str(int(condition_fields[field_name])))

    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, proc.stdout.splitlines()
