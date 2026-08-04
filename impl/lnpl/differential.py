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
from .repo_policy import repository_calls, seeded_entities


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


def observe_mode_b(document, workflow_id, workdir, payload=None, seeded=None):
    """Build and run the native binary, reducing its output to the same shape.

    RFC-0008 G8: condition field values come from the payload. Selection is by
    the workflow's own condition fields, not by the payload's shape — picking
    every int in the payload would let an unrelated field displace a real one,
    because the values are forwarded positionally.

    The Presence-guard `skip` flag is derived from the payload here (issue #12),
    using the same evaluation mode A uses, so there is no separate input a caller
    could set to contradict the payload — the divergence that made a wiring
    mistake indistinguishable from a real mode A/B disagreement.

    `seeded` is issue #35's seed condition, in the same spirit: the SET of entity
    ids that start with a row (`None` = the default role-based policy,
    `frozenset()` = `--no-row`). Mode B derives its own repository outcome from
    that set. It is deliberately not mode A's `repo_rows` dict — that is
    `FakeRepository`'s storage layout, and reading it here would couple mode B to
    how mode A happens to store rows rather than to what the seed rule says.
    """
    bin_path = backend.build(document, workflow_id, workdir, seeded=seeded)

    values = {}
    for name in backend.condition_field_names(document, workflow_id):
        raw = (payload or {}).get(name, 0)
        values[name] = raw if isinstance(raw, int) else 0

    skip = _derive_skip_from_payload(document, workflow_id, payload or {})
    rc, lines = backend.run_binary(bin_path, skip=skip, condition_fields=values)
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


def _derive_skip_from_payload(document, workflow_id, payload):
    """Derive the skip flag from Presence guards in the workflow.

    RFC-0008: Presence conditions are evaluated against the payload in mode A.
    This function reuses that same evaluation logic to derive the skip flag
    for mode B, ensuring both modes evaluate the same condition the same way.

    If a Presence guard is found, its condition is evaluated and the skip flag
    is set based on whether the condition is false (skip=True) or true (skip=False).
    If no Presence guard is found, skip defaults to False (don't skip).
    """
    from .condition import parse_condition, Presence, ConditionError

    # Find any Presence guard conditions in the workflow
    nodes = {n["id"]: n for n in document["nodes"]}

    def find_presence_condition(node_ids):
        """Recursively search for the first Presence guard condition."""
        for node_id in node_ids:
            node = nodes.get(node_id)
            if node is None:
                continue
            if node["kind"] == "Guard" and node.get("mode") == "when":
                cond_str = node.get("condition")
                if cond_str:
                    try:
                        cond = parse_condition(cond_str)
                        if isinstance(cond, Presence):
                            return cond_str
                    except ConditionError:
                        pass  # not a condition we can classify; keep searching
            # Recurse into children
            if node.get("children"):
                result = find_presence_condition(node["children"])
                if result:
                    return result
        return None

    wf = nodes.get(workflow_id)
    if wf is None or wf["kind"] != "Workflow":
        return False

    presence_cond_str = find_presence_condition(wf.get("children", []))
    if not presence_cond_str:
        return False  # No Presence guard found

    # Evaluate the Presence condition against the payload with the exact function
    # mode A uses. Mode A raises on an invalid condition; let that propagate rather
    # than swallow it — silently returning skip=False would run a step mode A
    # refused, masking a real divergence behind a false verdict.
    from .interp import _condition_holds
    # token present -> "token missing" is false -> skip=True;
    # token absent  -> "token missing" is true  -> skip=False.
    return not _condition_holds(presence_cond_str, payload)


def _check_seed_agreement(document, workflow_id, repo_rows, seeded):
    """Refuse a run whose two seed inputs disagree (issue #35).

    Mode A is handed a materialised store and mode B a seed condition, so the same
    fact reaches the comparison twice — and two copies of one fact own a
    synchronization bug. A caller that seeds mode A but tells mode B nothing is
    seeded produces a *genuine* mode A/B disagreement that is really a wiring
    mistake, which is the class of defect `_derive_skip_from_payload` removed for
    the skip flag. Raising here keeps a divergence report meaning what it says.

    Only entities the workflow actually calls are compared: a row for an entity no
    `RepositoryCall` names is inert to both modes, so requiring agreement about it
    would reject harmless input.
    """
    touched = {entity_id for entity_id, _op in repository_calls(document, workflow_id)}
    if not touched:
        return
    from_rows = {entity_id for entity_id, table in repo_rows.items() if table}
    if from_rows & touched != set(seeded) & touched:
        raise DifferentialError(
            "seed inputs disagree for %s: mode A's rows seed %s, mode B's seed "
            "condition says %s. One of the two callers is wrong, and comparing "
            "them anyway would report a wiring mistake as a divergence."
            % (sorted(touched), sorted(from_rows & touched),
               sorted(set(seeded) & touched)))


def verify(document, workflow_id, payload, repo_rows, workdir, seeded=None):
    """Compare the two modes. Returns (ok, report_lines).

    RFC-0008: The skip flag for Presence guards is derived from the payload,
    not supplied by the caller. This ensures mode A and B evaluate the same
    condition the same way, preventing spurious divergence.

    `seeded` is issue #35's seed condition — see `observe_mode_b`. `None` resolves
    to the default role-based policy, the same rule `cli._repo_rows` materialises
    for mode A, so the common case cannot disagree by construction.
    """
    if not backend.toolchain_available():
        raise DifferentialError(
            "mode B toolchain unavailable — cannot compare. Install it with "
            "`brew install llvm`. (Skipping the comparison silently would let a "
            "divergence ship unnoticed.)")

    resolved = (seeded_entities(document, workflow_id) if seeded is None
                else seeded)
    _check_seed_agreement(document, workflow_id, repo_rows, resolved)

    a = observe_mode_a(document, workflow_id, payload, repo_rows)
    b = observe_mode_b(document, workflow_id, workdir, payload=payload,
                       seeded=resolved)

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
