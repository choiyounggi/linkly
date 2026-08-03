# Task 03: teach the Reviewer the same contract, and let a declared move through

## Objective

`Reviewer._assess` accepts a reference-only edit outside the proposer's rights,
treats a declared move as a move rather than a removal, and still refuses
everything else — with `_structure_fault` deciding whether the result is sound.

## Wiki pages (read these first, only these)

- `wiki/testing/quality/tests-that-cannot-fail.md` — the whole task. The Reviewer
  is the second independent gate; a relaxation here that cannot refuse removes
  the only check standing between a proposal and the document.
- `wiki/testing/quality/minimum-case-set.md` — case set and error-contract
  assertions for the two relaxed branches.

## Inputs

- From task 01: `rfcs/0010-proposal-intent.md`.
- From task 02: `protocol.reference_only_edit(proposed, existing, declared_children)`
  and `protocol.attachments(intent)`, plus `proposals[pid]["intent"]`.
- `impl/lnpl/agents.py`, measured. `Reviewer._assess(proposal_id)` at `:275`
  checks in this order — **preserve the order**, since each stage assumes the
  previous one passed:
  1. rights — `{n["kind"] for n in nodes} - allowed`, message
     `"rights: %s may not propose %s"`.
  2. provenance — new nodes need `meta.source` matching
     `_SOURCE_FORM` (`:31`, `^(kb:[a-z0-9-]+@\d+\.\d+\.\d+|ir:[a-z][a-z0-9.]*)$`)
     **and resolving** via `_source_resolves` (`:268`).
  3. kind change on a replacement → `"kind: …"`.
  4. dropped references → `"removal: replacing %s would drop reference(s) %s — 
     \`ir.propose\` cannot express a removal (RFC-0006 §Methods)"`.
  5. `_structure_fault(merged)` — dangling (rule 6), one-owner (rule 2), orphan
     (rules 2·5), acyclicity (rule 4), over the **whole merged document**.
  6. schema validation of the merged candidate.
- **D9/D12 matter here.** Stage 5 already enforces every invariant a move could
  break, so this task *narrows* stage 4 rather than adding a checker. And stage
  4's citation is wrong — RFC-0006 contains no removal rule (grepped); it becomes
  RFC-0010.
- Decisions that bind you: **D6**, **D7**, **D8**, **D9**, **D12**.

## Steps

1. At the top of `_assess`, read the intent the server stored:
   `intent = proposal.get("intent") or {}` and
   `attach_map = protocol.attachments(intent)`. Import what you need from
   `protocol` the way this module already imports `ROLES` and `node_references`.

2. Relax stage 1 (rights) to match task 02's gate exactly. Same four conditions,
   same helper — call `reference_only_edit`, do not re-derive it:

   ```python
   outside = []
   for node in nodes:
       if node.get("kind") in allowed:
           continue
       declared = attach_map.get(node.get("id"), set())
       if declared and reference_only_edit(node, existing.get(node.get("id")),
                                           declared):
           continue
       outside.append(node.get("kind"))
   if outside:
       return False, ("rights: %s may not propose %s"
                      % (proposal["role"], ", ".join(sorted(set(outside)))))
   ```

   Keep the message shape — `test_agents.py` asserts the substring `rights`.

3. Enforce D7 here too. For each `attach` entry, the `child` must be authored in
   this proposal (present in `nodes`, absent from `existing`). Reject with a new
   code `attach:` naming the child and stating that a proposal may attach only what
   it authored. Both gates check this because the test suite treats the Reviewer as
   an independent gate — a proposal planted directly into `server.proposals`
   bypasses task 02 entirely, and `test_agents.py` already does exactly that in
   `test_it_rejects_a_kind_outside_the_proposers_rights`.

4. Narrow stage 4. A dropped reference is sanctioned when a declared `move`
   accounts for it:

   ```python
   moves = protocol.moves(intent)      # {(from_id, node_id): to_id}
   ...
   dropped = sorted(set(node_references(old)) - set(node_references(node)))
   unexplained = [ref for ref in dropped
                  if (node["id"], ref) not in moves]
   if unexplained:
       return False, ("removal: replacing %s would drop reference(s) %s without a "
                      "declared move — `ir.propose` expresses a move by declaring "
                      "it in `intent`, and refuses an undeclared removal "
                      "(RFC-0010 §Methods)"
                      % (node["id"], ", ".join(unexplained)))
   ```

   Add `moves(intent)` to `protocol.py` beside `attachments`, validating shape the
   same way (a non-dict intent, a non-list `move`, or an entry missing a string
   `node`/`from`/`to` is `ir_invalid`).

   **Note the citation change** — `RFC-0010 §Methods`, because RFC-0006 never
   stated this (D12).

5. Verify the declared destination actually took the node, **in the same field it
   left**. After the `merged` dict is built (stage 5's input) and **before**
   `_structure_fault`, for each move:

   - find which reference field of the `from` node held `node` in the original
     document;
   - require the `to` node in `merged` to reference `node` **in that same field**;
   - and if `node`'s kind is `Policy`/`Security`/`Performance`, require that field
     to be `constraints` — RFC-0001 rule 5 forbids owning a Constraint through
     `children`.

   Reject with `move:` naming the entry and the field otherwise.

   **"References it somewhere" is not enough.** `node_references` unions `children`
   with the named fields, so an audit against that weaker check laundered a
   Constraint removal: a `Policy` was declared as "moved" out of a step's
   `constraints` and landed in another node's `children`, emptying `constraints`
   while the check passed. The interpreter reads `constraints` for retry, timeout
   and rollback, so that is a silent policy removal — the exact hazard
   `test_it_rejects_a_constraint_removal_expressed_as_an_edit` exists to prevent.

6. Leave stage 5 and 6 **untouched**. They are the invariant gate this design
   relies on (D9).

7. Add tests to `impl/tests/test_agents.py` in one class
   `TestReviewerHonoursDeclaredIntent`, following the file's existing setup
   (`Server(golden(), KnowledgeBase())`, `Reviewer(server)`, propose via
   `server.call("ir.propose", …)`).

   Use a **local** IR document (D17) — a workflow whose one step owns two
   `RepositoryCall`s, since `golden()` has none:

   ```python
   TWO_ACCESS = {"lir_version": "0.1", "module": "t", "nodes": [
       {"kind": "Entity", "id": "entity.user", "name": "User",
        "fields": [{"name": "id", "type": "UUID"}]},
       {"kind": "Service", "id": "svc.s", "name": "S", "children": ["wf.w"]},
       {"kind": "Workflow", "id": "wf.w", "name": "W", "children": ["wf.w.step.1"]},
       {"kind": "WorkflowStep", "id": "wf.w.step.1", "name": "load and audit",
        "children": ["wf.w.step.1.a", "wf.w.step.1.b"]},
       {"kind": "RepositoryCall", "id": "wf.w.step.1.a",
        "entity": "entity.user", "operation": "read"},
       {"kind": "RepositoryCall", "id": "wf.w.step.1.b",
        "entity": "entity.user", "operation": "update"}]}
   ```

   New nodes need `meta` with `origin: "agent:RefactoringAgent"` and
   `source: "kb:patterns-repository-call@0.1.0"` (D16) or provenance rejects them
   at stage 2 before your branches run.

   - **normal** `test_a_declared_split_is_approved` — the full split (parent
     reference-only edit + replaced step + new step, with `attach` and `move`) is
     approved. Assert the reason mentions the clear invariants.
   - **error** `test_an_undeclared_drop_is_still_a_removal` — same nodes, empty
     `intent`; assert rejection and that the reason starts `removal:` **and**
     cites `RFC-0010`.
   - **error** `test_a_move_to_a_destination_that_does_not_take_it_is_rejected` —
     declare a `move` whose `to` is a node that does not reference the child;
     assert `move:`.
   - **error** `test_attaching_a_node_it_did_not_author_is_rejected` — declare an
     `attach` whose `child` is `wf.w.step.1` (already in the document); assert
     `attach:`.
   - **error** `test_a_non_reference_change_on_an_out_of_rights_node_is_rejected` —
     the `Workflow` edit also renames; assert `rights:`.
   - **boundary** `test_a_move_that_creates_two_owners_is_rejected` — declare the
     move but have **both** steps keep the child; assert the reason is
     `ownership:` (from `_structure_fault`, not from your branch) — this is what
     shows the invariant gate is still doing the work.
   - **error** `test_a_move_into_a_different_field_is_rejected` — declare a move of
     a `Policy` out of a step's `constraints` whose destination takes it in
     `children`. Assert `move:`. This is the laundered-removal attack.
   - **boundary** `test_the_existing_removal_refusal_is_unchanged_without_intent` —
     a plain replacement dropping a reference, no intent at all, still rejected.

8. **Do not let this task make an existing mutation STALE.** `mutation_check.py`
   carries `Reviewer: allow a replacement to drop references (removal by edit)`
   anchored on `            if dropped:\n                return False,` in
   `lnpl/agents.py`. Step 4 renames that condition to `if unexplained:`, which
   turns the anchor STALE — and `mutation_check.py` reports STALE as a
   *non-failure*, so it would pass silently. Re-anchor it in this task, on the new
   condition, keeping its label. Task 05 verifies `0 STALE`; do not leave it to
   discover this.

## Deliverables

- `impl/lnpl/protocol.py` (modified — add `moves`)
- `impl/lnpl/agents.py` (modified — `_assess`)
- `impl/tests/test_agents.py` (modified — one new class)

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK`, the 345 plus tasks 02's and this task's new tests, no failures.
No existing test may be edited.

Then prove each relaxed branch can refuse:

| Mutation | Must turn red |
|---|---|
| Skip the `unexplained` filter — sanction every dropped reference | `test_an_undeclared_drop_is_still_a_removal` |
| Drop the step-5 destination check | `test_a_move_to_a_destination_that_does_not_take_it_is_rejected` |
| Drop the step-3 containment check | `test_attaching_a_node_it_did_not_author_is_rejected` |
| Make `_structure_fault` return `None` always | `test_a_move_that_creates_two_owners_is_rejected` — this one proves the invariant gate, not your branch, is what catches structural damage |

```bash
PYTHONPATH=impl .venv/bin/python -m unittest -v \
  tests.test_agents.TestReviewerHonoursDeclaredIntent
```

And confirm the citation was corrected:

```bash
git grep -n "cannot express a removal" -- impl
```

Success = the message cites `RFC-0010`, not `RFC-0006` — RFC-0006 has no such
rule (D12).

## Out of scope

- `RefactoringAgent` — task 04. This task makes the gate accept a correct split;
  nothing yet produces one.
- Changing `_structure_fault`, the provenance check, or the schema stage.
