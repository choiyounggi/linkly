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

import json

from . import backend
from .condition import looks_like_instant
from .interp import Interpreter, resolve_reference
from .repo_policy import (default_rows, repository_calls, seed_bindings,
                          seeded_entities)


class DifferentialError(Exception):
    """Raised when the two modes disagree, or one of them could not run."""


def observe_mode_a(document, workflow_id, payload, repo_rows, network=None):
    """Run the interpreter and reduce its trace to the observable four.

    Issue #43: the masking class scans `text`, so `text` must carry every
    channel mode A actually outputs. `result["bindings"]` is the channel t2's
    QA probe caught leaking (F-9 — the scan was green while `--json` returned
    the raw secret), so the (already masked) bindings are serialised into the
    scanned surface. Classes 1-3 are structural and unaffected.

    `network` (RFC-0027 §8) lets a caller vary a `NetworkCall`'s stubbed
    response/failure across comparisons — mode B never reads it (it computes
    no network values at all), which is exactly what the equivalence proof
    demonstrates: the response value is not one of RFC-0004's four classes.
    """
    interp = Interpreter(document, repo_rows=repo_rows, network=network)
    result = interp.run_workflow(workflow_id, payload)
    steps = []
    for span in (interp.trace.root.children if interp.trace.root else []):
        steps.append({"step": span.name,
                      "effects": [c.kind for c in span.children]})
    text = _text_of(steps, result["status"])
    for name in sorted(result["bindings"]):
        text += "\nbinding %s %s" % (
            name, json.dumps(result["bindings"][name], sort_keys=True,
                             ensure_ascii=False, default=repr))
    # RFC-0018: accumulate per step NAME, the fold `observe_mode_b` already
    # uses. A name repeats when `until` or `repeat` unrolls its body, and this
    # used to be a dict comprehension — last occurrence wins — so a 16-round
    # loop reported one `RepositoryCall` against mode B's sixteen and class 3/4
    # went red although both modes ran the same 17 steps (issue #51; the
    # asymmetry RFC-0017 §Open Questions 1 left undecided).
    #
    # Unified toward accumulation, not toward overwriting: folding sixteen
    # performed effects into one is a normalisation no contract clause permits,
    # and it would let mode B skip fifteen repository calls and still pass.
    effects = {}
    for s in steps:
        effects.setdefault(s["step"], []).extend(s["effects"])
    return {"order": [s["step"] for s in steps],
            "effects": effects,
            "status": result["status"],
            "skips": _normalise_skips(result["skipped"]),
            "bindings": result["bindings"],
            "text": text}


def _normalise_skips(records):
    """Project `result["skipped"]` onto the fields both modes can observe.

    Two changes, each forced by what mode B can produce (issue #44):

    * `guard` (an IR node id) is dropped. The native binary prints
      `step <index> <name>` and nothing else, so a comparison keyed on node ids
      could never pass — it would report the absence of a channel as a
      disagreement about behaviour.
    * one entry per STEP, not per guard. Mode A knows which guard owns which
      steps; mode B can only see that a planned step never printed. Flattening
      mode A to the finer grain lets the two be compared directly instead of
      making mode B guess how mode A grouped its records.

    `rounds` rides along because RFC-0008 §5 names the `until` round count as
    its own comparison item.

    This is an ALLOW-list, not a deny-list: it names exactly the four keys the
    projection carries, so `evaluations` (issue #83's per-term measured values,
    RFC-0014 D3-D4 addendum) is excluded the same way `guard` already is — mode
    B cannot produce it either — with no change needed here when that key was
    added.
    """
    return [{"mode": r["mode"], "condition": r["condition"],
             "step": name, "rounds": r["rounds"]}
            for r in records for name in r["steps"]]


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
    bin_path = backend.build(document, workflow_id, workdir, seeded=seeded,
                             payload=payload)

    # RFC-0012 §G12.6: values are resolved through the SAME scope rule mode A
    # evaluates, so a qualified reference (`product.stock`) reaches the compiled
    # guard as the row's value rather than as a missing payload key. The scope is
    # projected from the seed rule because mode B's module models no repository
    # state — see `repo_policy.seed_bindings`.
    bindings = seed_bindings(document, workflow_id, payload or {}, seeded)
    values = {}
    for name in backend.condition_field_names(document, workflow_id):
        raw = resolve_reference(name, payload or {}, bindings)
        # Values that name a QUANTITY go through `backend.encode_condition_value`,
        # the same coercion the compiled path uses. This used to read `raw if
        # isinstance(raw, int) else 0`, which silently turned any non-integer —
        # a DateTime among them — into 0, so both sides of a time comparison
        # became the epoch and every window guard evaluated true in mode B while
        # mode A read the real instants (RFC-0016).
        #
        # Anything else stays 0, and that is not a fallback for a failed
        # encoding: a Presence guard's field reaches mode B through the run-level
        # `skip` boolean, never through this channel, so its i64 slot is a
        # placeholder no comparison reads. A malformed date-time still raises,
        # because `looks_like_instant` sends it to the encoder.
        if isinstance(raw, (int, bool)) or looks_like_instant(raw):
            values[name] = backend.encode_condition_value(raw)
        else:
            values[name] = 0

    skip = _derive_skip_from_payload(document, workflow_id, payload or {}, seeded)
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
    # Issue #44: a guard mode B did not take prints nothing at all, so the skip is
    # observable only as an absence from the plan the module was built from.
    # `backend.restore_skips` owns that reading — issue #55 gave `cli.cmd_build` a
    # second reader, and two copies of it could disagree about what mode B
    # observed. `seeded`/`payload` are the values `backend.build` was called with
    # above, so the plan describes the module that actually ran.
    skips = backend.restore_skips(document, workflow_id,
                                 backend.ran_step_indices(lines),
                                 seeded=seeded, payload=payload)

    # Issue #43: the masking surface is the binary's WHOLE stdout, not the
    # normalised reduction of the lines the parser above recognised — an
    # unrecognised line would otherwise drop out of the scan, which is the
    # same silent-surface gap F-9 found on the mode A side.
    return {"order": order, "effects": effects, "status": status,
            "skips": skips, "text": "\n".join(lines)}


def _text_of(steps, status):
    out = []
    for s in steps:
        out.append("step %s" % s["step"])
        for kind in s["effects"]:
            out.append("  effect %s" % kind)
    out.append("status %s" % status)
    return "\n".join(out)


SECRET_MARKERS = ("s3cret", "password=", "BEGIN PRIVATE KEY")


def _derive_skip_from_payload(document, workflow_id, payload, seeded=None):
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
    from .repo_policy import seed_bindings
    # RFC-0012: a Presence guard may name a bound row (`product.name exists`), so
    # the skip flag is derived against the same execution scope mode A will build.
    # Mode B's module models no repository state, so the scope is projected
    # statically from the seed rule — the one input both modes already share.
    bindings = seed_bindings(document, workflow_id, payload, seeded)
    # token present -> "token missing" is false -> skip=True;
    # token absent  -> "token missing" is true  -> skip=False.
    return not _condition_holds(presence_cond_str, payload, bindings)


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

    A `query` call (RFC-0025's `list`) is excluded from `touched` — `seeded` is
    mode B's boolean "does this entity start with A row" condition, which only
    matters to mode B's static prediction for `read` (does it find nothing?) and
    `create` (does it conflict?). A RowSet has no analogous prediction: `list`
    never fails on an empty result (RFC-0025 §5), and mode B does not model row
    VALUES at all (RFC-0015 §5's "할당이 만든 값" is an allowed difference), so
    it has no opinion on whether a `query`-only entity is seeded. Requiring
    agreement there would refuse the ordinary case — mode A's `repo_rows` seeded
    with RowSet rows (indexed `given stored` seeds, RFC-0025 §8) while mode B's
    `seeded` (`repo_policy.seeded_entities`) rightly never mentions it.
    """
    touched = {entity_id for entity_id, op in repository_calls(document, workflow_id)
              if op != "query"}
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


def _check_rows_are_reproducible(document, workflow_id, payload, repo_rows, seeded):
    """Refuse a comparison whose mode A rows the seed rule cannot reproduce (RFC-0012 §G12.6).

    Mode B is handed a scope PROJECTED from the seed rule, because its module
    models no repository state. That projection can only say what the rule says: a
    seeded row is a copy of the payload. If the caller seeded mode A with a row
    carrying a different value, the two modes are evaluating the guard against
    different inputs, and any disagreement they produce describes the caller's
    wiring rather than a backend defect.

    So the comparison is refused, not run — the same stance `_check_seed_agreement`
    takes for the seed SET. Mode A alone is unaffected: `observe_mode_a` and the
    interpreter accept any rows, which is what lets issue #37's proof use a row
    that deliberately differs from the payload.

    Only fields a guard actually reads are compared. Requiring every column to
    match would reject rows that differ in ways no guard can observe.
    """
    watched = set()
    for name in backend.condition_field_names(document, workflow_id):
        if "." in name:
            watched.add(name)
    if not watched:
        return

    expected = default_rows(document, workflow_id, payload)
    resolved = (seeded_entities(document, workflow_id) if seeded is None
                else set(seeded))
    nodes = {n["id"]: n for n in document["nodes"]}
    from .repo_policy import binding_name

    for entity_id in sorted(resolved):
        node = nodes.get(entity_id)
        if node is None:
            continue
        prefix = binding_name(node) + "."
        fields = sorted(n.split(".", 1)[1] for n in watched
                        if n.startswith(prefix))
        if not fields:
            continue
        for key, row in sorted((repo_rows.get(entity_id) or {}).items()):
            reference = (expected.get(entity_id) or {}).get(key)
            if reference is None:
                continue
            for field in fields:
                if row.get(field) != reference.get(field):
                    raise DifferentialError(
                        "mode A's row for %s carries %s=%r, but the seed rule "
                        "would produce %r. Mode B derives that value from the "
                        "seed rule, so it cannot reproduce this row, and "
                        "comparing the two modes anyway would report the "
                        "difference as a divergence. Run mode A on its own for "
                        "this input, or seed a row the rule produces."
                        % (entity_id, field, row.get(field),
                           reference.get(field)))


def verify(document, workflow_id, payload, repo_rows, workdir, seeded=None,
           network=None):
    """Compare the two modes. Returns (ok, report_lines).

    RFC-0008: The skip flag for Presence guards is derived from the payload,
    not supplied by the caller. This ensures mode A and B evaluate the same
    condition the same way, preventing spurious divergence.

    `seeded` is issue #35's seed condition — see `observe_mode_b`. `None` resolves
    to the default role-based policy, the same rule `cli._repo_rows` materialises
    for mode A, so the common case cannot disagree by construction.

    `network` (RFC-0027 §8) is mode A's `NetworkDriver` only — see
    `observe_mode_a`.
    """
    if not backend.toolchain_available():
        raise DifferentialError(
            "mode B toolchain unavailable — cannot compare. Install it with "
            "`brew install llvm`. (Skipping the comparison silently would let a "
            "divergence ship unnoticed.)")

    resolved = (seeded_entities(document, workflow_id) if seeded is None
                else seeded)
    _check_seed_agreement(document, workflow_id, repo_rows, resolved)
    _check_rows_are_reproducible(document, workflow_id, payload, repo_rows,
                                 resolved)

    a = observe_mode_a(document, workflow_id, payload, repo_rows, network=network)
    b = observe_mode_b(document, workflow_id, workdir, payload=payload,
                       seeded=resolved)
    return compare_observations(a, b, document, workflow_id)


def _list_where_step_count(document, workflow_id):
    """How many `list where` steps (issue #116, D9) `workflow_id` reaches.

    A predicate filters the RowSet by stored row VALUES, which RFC-0025 §10
    already put outside mode B's four observation classes (mode B never
    computes a value at all — `_render_std` emits only the effect-kind
    pointer). `EQUIVALENT` from the four classes below is still an honest
    claim (nothing that differs IS compared), but it says nothing about
    which rows the predicate kept — that has to be spelled out, or a
    reader takes "EQUIVALENT" as "the filtered content agrees too," which
    it was never checked to say (docs/backends.md §6's sqlite-storage
    caveat, extended to this dimension).
    """
    nodes = {n["id"]: n for n in document["nodes"]}
    workflow = nodes.get(workflow_id)
    if workflow is None or workflow["kind"] != "Workflow":
        return 0

    count = 0

    def walk(ids):
        nonlocal count
        for node_id in ids:
            node = nodes.get(node_id)
            if node is None:
                continue
            if node["kind"] == "WorkflowStep":
                for child_id in node.get("children", []):
                    child = nodes.get(child_id)
                    if (child is not None and child["kind"] == "RepositoryCall"
                            and child.get("operation") == "query"
                            and child.get("predicate")):
                        count += 1
            else:
                walk(node.get("children", []))

    walk(workflow.get("children", []))
    return count


def _parallel_block_count(document, workflow_id):
    """How many `parallel` blocks (issue #108) `workflow_id` reaches.

    Mode A now actually runs a `parallel` block's steps concurrently
    (RFC-0041); mode B still runs everything sequentially — RFC-0004
    §5(#7)'s open question, still open, this issue only changed mode A.
    The four observation classes' "execution order" reads the block's
    steps in DECLARED order (D6), not completion order, so a run with no
    failure reports the same order either mode used — but that says
    nothing about whether mode A's steps actually overlapped in real time,
    which is not a thing any of the four classes observes at all (same
    shape as `_list_where_step_count`'s filtered-content caveat above).
    """
    nodes = {n["id"]: n for n in document["nodes"]}
    workflow = nodes.get(workflow_id)
    if workflow is None or workflow["kind"] != "Workflow":
        return 0

    count = 0

    def walk(ids):
        nonlocal count
        for node_id in ids:
            node = nodes.get(node_id)
            if node is None:
                continue
            if node["kind"] == "Concurrency":
                count += 1
            elif node["kind"] != "WorkflowStep":
                walk(node.get("children", []))

    walk(workflow.get("children", []))
    return count


def compare_observations(a, b, document=None, workflow_id=None):
    """RFC-0004's four-class comparison on two observations. (ok, report).

    Split out of `verify` (issue #43) so a doctored observation can prove the
    masking class GOES RED when a channel leaks — a detection check that needs
    no toolchain. `verify`'s signature and behaviour are unchanged.

    `document`/`workflow_id` (issue #116, D9) are optional and additive: when
    given, and the workflow reaches a `list where` step, one extra report
    line names it as an unverified dimension — the `ok` verdict itself is
    untouched, since nothing the four classes check actually diverges.
    Every existing caller (this module's own doctored-observation tests
    included) passes neither and sees no behaviour change.
    """
    report, ok = [], True

    # RFC-0008 §5 puts the skip set and the `until` round count INSIDE the
    # execution-order class rather than adding a fifth: "기존 4분류는 유지하고,
    # 새 항목을 실행 순서 내에 포함시킨다". A step that was skipped and a step
    # that never existed both show up as a shorter `order`, so without the skip
    # set the class cannot tell a guard disagreement from a lowering one.
    a_skips, b_skips = a.get("skips") or [], b.get("skips") or []
    if a["order"] == b["order"] and a_skips == b_skips:
        report.append("PASS 1/4 execution order — %d step(s): %s | %d skip(s)"
                      % (len(a["order"]), " -> ".join(a["order"]) or "(none)",
                         len(a_skips)))
    else:
        ok = False
        report.append("FAIL 1/4 execution order\n  mode A: %s skips=%s"
                      "\n  mode B: %s skips=%s"
                      % (a["order"], a_skips, b["order"], b_skips))

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
    if document is not None and workflow_id is not None:
        n = _list_where_step_count(document, workflow_id)
        if n:
            report.append(
                "note: %d `list where` step(s) — filtered RowSet content is "
                "not compared (unverified dimension, docs/backends.md §6)" % n)
        p = _parallel_block_count(document, workflow_id)
        if p:
            report.append(
                "note: %d `parallel` block(s) — mode B runs them "
                "sequentially (unverified dimension, docs/backends.md §6)" % p)
    return ok, report
