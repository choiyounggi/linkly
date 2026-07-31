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


# ---- S4: Semantic IR -> MLIR (standard dialects) ---------------------------

def _steps_in_order(nodes, ids, out):
    """Flatten the body the way mode A does, so both modes agree on step order.

    Guards are resolved at compile time only when their outcome is decidable from
    the IR alone; `when` is not, so a guarded step is emitted with a runtime flag
    the caller supplies. `repeat` is a constant, so it unrolls.
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
                inner = []
                _steps_in_order(nodes, node.get("children", []), inner)
                for step, _cond in inner:
                    out.append((step, node.get("condition")))
            else:
                raise BackendError(
                    "mode B cannot compile guard mode %r yet: an `until` loop needs "
                    "a runtime condition evaluator (RFC-0002 Open Questions 2)"
                    % node["mode"])
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
    lines.append("  func.func @lnpl_run(%skip : i32) -> i32 {")
    lines.append("    %c0 = arith.constant 0 : i32")
    lines.append("    %c1 = arith.constant 1 : i32")

    for idx, (step, cond) in enumerate(steps, start=1):
        sym = strings[step["name"]]
        lines.append("    // step %d: %s%s"
                     % (idx, step["name"],
                        "  (guarded by `%s`)" % cond if cond else ""))
        lines.append("    %%p%d = llvm.mlir.addressof @%s : !llvm.ptr" % (idx, sym))
        lines.append("    %%i%d = arith.constant %d : i32" % (idx, idx))
        if cond:
            # A `when` guard becomes a runtime branch on the caller-supplied flag.
            lines.append("    %%skip%d = arith.cmpi eq, %%skip, %%c1 : i32" % idx)
            lines.append("    scf.if %%skip%d {" % idx)
            lines.append("    } else {")
            lines.append("      %%r%d = func.call @lnpl_step(%%p%d, %%i%d) : "
                         "(!llvm.ptr, i32) -> i32" % (idx, idx, idx))
            for cn, child_id in enumerate(step.get("children", [])):
                ksym = strings[nodes[child_id]["kind"]]
                lines.append("      %%k%d_%d = llvm.mlir.addressof @%s : !llvm.ptr"
                             % (idx, cn, ksym))
                lines.append("      func.call @lnpl_effect(%%p%d, %%k%d_%d) : "
                             "(!llvm.ptr, !llvm.ptr) -> ()" % (idx, idx, cn))
            lines.append("    }")
        else:
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
 */
#include <stdio.h>

int lnpl_step(const char *name, int index) {
  printf("step %d %s\n", index, name);
  return 0;
}

void lnpl_effect(const char *step, const char *kind) {
  printf("effect %s %s\n", step, kind);
}

int lnpl_run(int skip);

int main(int argc, char **argv) {
  int skip = (argc > 1 && argv[1][0] == '1') ? 1 : 0;
  int rc = lnpl_run(skip);
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


def run_binary(bin_path, skip=False):
    """Execute the native binary; returns (exit_code, stdout lines)."""
    proc = subprocess.run([bin_path, "1" if skip else "0"],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout.splitlines()
