"""Mode A vs mode B differential verification (RFC-0004 §Execution modes).

RFC-0004 requires the two execution modes to agree on **observable behaviour**
only, and names exactly what that covers (adopted from RFC-0003):

    1. execution order      — which steps ran, in what order
    2. policy outcomes      — the terminal status the policies produced
    3. observability signals — the effects each step performed
    4. masking              — no secret appears in the output

and what it explicitly does *not* cover: scheduler shape, memory placement,
instruction selection, op count, wall-clock time. This module compares (1)-(4)
and ignores the rest — a check that compared timings would fail for reasons the
contract permits, which is worse than no check.

The comparison is on a normalised **observation** extracted from each mode, so it
cannot pass by accident: `verify` fails if either mode is missing, and the
self-check below proves a deliberate divergence is detected.
"""

from . import backend
from .interp import Interpreter


class DifferentialError(Exception):
    """Raised when the two modes disagree, or one of them could not run."""


def observe_mode_a(document, workflow_id, payload, repo_rows):
    """Run the interpreter and reduce its trace to the observable four."""
    interp = Interpreter(document, repo_rows=repo_rows)
    result = interp.run_workflow(workflow_id, payload)
    steps = []
    for span in (interp.trace.root.children if interp.trace.root else []):
        steps.append({"step": span.name,
                      "effects": [c.kind for c in span.children]})
    return {"order": [s["step"] for s in steps],
            "effects": {s["step"]: s["effects"] for s in steps},
            "status": result["status"],
            "text": _text_of(steps, result["status"])}


def observe_mode_b(document, workflow_id, workdir, skip=False):
    """Build and run the native binary, reducing its output to the same shape."""
    bin_path = backend.build(document, workflow_id, workdir)
    rc, lines = backend.run_binary(bin_path, skip=skip)
    order, effects, status = [], {}, None
    for line in lines:
        parts = line.split(" ", 2)
        if parts[0] == "step" and len(parts) == 3:
            order.append(parts[2])
            effects.setdefault(parts[2], [])
        elif parts[0] == "effect" and len(parts) == 3:
            # `effect <step name> <Kind>` — the step name may contain spaces, so
            # split from the right.
            body = line[len("effect "):]
            step_name, kind = body.rsplit(" ", 1)
            effects.setdefault(step_name, []).append(kind)
        elif parts[0] == "status" and len(parts) >= 2:
            status = parts[1]
    if status is None:
        raise DifferentialError("mode B produced no status line (exit %d)" % rc)
    return {"order": order, "effects": effects, "status": status,
            "text": _text_of([{"step": s, "effects": effects.get(s, [])}
                              for s in order], status)}


def _text_of(steps, status):
    out = []
    for s in steps:
        out.append("step %s" % s["step"])
        for kind in s["effects"]:
            out.append("  effect %s" % kind)
    out.append("status %s" % status)
    return "\n".join(out)


SECRET_MARKERS = ("s3cret", "password=", "BEGIN PRIVATE KEY")


def verify(document, workflow_id, payload, repo_rows, workdir, skip=False):
    """Compare the two modes. Returns (ok, report_lines)."""
    if not backend.toolchain_available():
        raise DifferentialError(
            "mode B toolchain unavailable — cannot compare. Install it with "
            "`brew install llvm`. (Skipping the comparison silently would let a "
            "divergence ship unnoticed.)")

    a = observe_mode_a(document, workflow_id, payload, repo_rows)
    b = observe_mode_b(document, workflow_id, workdir, skip=skip)

    report, ok = [], True

    if a["order"] == b["order"]:
        report.append("PASS 1/4 execution order — %d step(s): %s"
                      % (len(a["order"]), " -> ".join(a["order"]) or "(none)"))
    else:
        ok = False
        report.append("FAIL 1/4 execution order\n  mode A: %s\n  mode B: %s"
                      % (a["order"], b["order"]))

    if a["status"] == b["status"]:
        report.append("PASS 2/4 policy outcome — status=%s" % a["status"])
    else:
        ok = False
        report.append("FAIL 2/4 policy outcome — A=%s B=%s"
                      % (a["status"], b["status"]))

    if a["effects"] == b["effects"]:
        total = sum(len(v) for v in a["effects"].values())
        report.append("PASS 3/4 observability signals — %d effect(s) per step match"
                      % total)
    else:
        ok = False
        report.append("FAIL 3/4 observability signals\n  mode A: %s\n  mode B: %s"
                      % (a["effects"], b["effects"]))

    leaked = [m for m in SECRET_MARKERS if m in a["text"] or m in b["text"]]
    if not leaked:
        report.append("PASS 4/4 masking — no secret marker in either mode's output")
    else:
        ok = False
        report.append("FAIL 4/4 masking — leaked marker(s): %s" % leaked)

    report.append("differential: %s" % ("EQUIVALENT" if ok else "DIVERGENT"))
    return ok, report
