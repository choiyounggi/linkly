# Task 02: carry `intent` through `ir.propose` and relax its rights gate

## Objective

`ir.propose` accepts an optional `intent`, stores it on the proposal, and permits
a node outside the caller's rights when — and only when — it is a reference-only
edit that the intent declares.

## Wiki pages (read these first, only these)

- `wiki/testing/quality/tests-that-cannot-fail.md` — governs the negative
  controls. A permissive branch that never refuses is indistinguishable from an
  absent gate.
- `wiki/testing/quality/minimum-case-set.md` — the case set for the new
  validation: normal, error, boundary per behaviour, asserting the error contract
  rather than just "it raised".

## Inputs

- From task 01: `rfcs/0010-proposal-intent.md`, whose §Reference-level
  Specification defines `intent` and the four reference-only conditions.
- `impl/lnpl/protocol.py`, measured:
  - `DECLARATION`/`BEHAVIOR`/`EFFECT`/`CONSTRAINT` at `:50`-`:55`, `ROLES` at
    `:57`, `RefactoringAgent: {"propose": BEHAVIOR | EFFECT, "approve": False}`
    at `:65`.
  - `node_references(node)` at `:100` — returns `children` plus every named
    reference field. **Use this**; do not write a second reference extractor. Its
    docstring records that when two gates asked different questions, a dropped
    `constraints` reference slipped past both.
  - `_m_ir_propose(self, params)` at `:340` — validates role, then `ir_fragment`
    shape, then `module` match, then
    `allowed = ROLES[role]["propose"]` and rejects any node whose `kind` is not in
    it with `RpcError("ir_invalid", "role %s may not propose %s nodes")`. Then
    builds `pid`, dispatches the review task, and stores
    `self.proposals[pid] = {"id", "role", "state", "nodes", "review_task_id"}`.
- Decisions that bind you: **D5** (shape; absent `intent` behaves exactly as
  before), **D6** (the four conditions), **D7** (`child` must be authored in this
  proposal), **D9** (add no invariant checker).

## Steps

1. Add a module-level helper next to `node_references`:

   ```python
   def reference_only_edit(proposed, existing, declared_children):
       """Is `proposed` a replacement of `existing` that only adds `declared_children`?

       RFC-0010 lets a role edit a node outside its rights for one purpose:
       attaching something it just authored. That is safe only when the edit does
       nothing else, so all four conditions hold or none of it does.
       """
   ```

   Return `True` only when all four hold. **Per field and order-preserving — not
   set-based.** A set comparison passes for two attacks an audit demonstrated
   against exactly that draft: reversing `children` while adding one (and
   `children` order **is** execution order, RFC-0001 rule 3), and migrating an id
   from `constraints` into `children` (set-identical, but `interp.py` reads
   `constraints` for retry/timeout/rollback — measured to silently drop retry).

   - (a) `existing` is not `None`;
   - (b) `proposed["kind"] == existing["kind"]`;
   - (c) every key present in either dict **other than** the reference-bearing
     ones is equal in both — compare
     `{k: v for k, v in node.items() if k not in _REFERENCE_KEYS}` on each side.
     Define once, module-level:

     ```python
     _REFERENCE_KEYS = {"children"} | set(NAMED_REF_FIELDS)
     ```

     `set(...)` is required — `NAMED_REF_FIELDS` is a **tuple**
     (`protocol.py:97`), and `{"children"} | NAMED_REF_FIELDS` raises
     `TypeError: unsupported operand type(s) for |: 'set' and 'tuple'` at import;
   - (d) for **each** field in `_REFERENCE_KEYS`, taken independently: strip the
     declared additions from the proposed field, in order, and require what
     remains to be **identical** — same values, same order — to the existing
     node's value for that field. Concretely:

     ```python
     for field in _REFERENCE_KEYS:
         before = existing.get(field)
         after = proposed.get(field)
         if isinstance(after, list):
             remaining = [ref for ref in after if ref not in declared_children]
             if remaining != list(before or []):
                 return False
         elif after != before:
             return False
     ```

     A scalar reference field (`entity`, `event`, `source`, …) must be untouched;
     a list field may only gain the declared children, anywhere in it, with every
     pre-existing entry keeping its position relative to the others. This one
     condition subsumes "adds exactly the declared refs" and "drops none", and
     closes both attacks.

2. Add a helper that reads the intent safely, so a malformed intent is a clean
   `ir_invalid` rather than a `TypeError`:

   ```python
   def attachments(intent):
       """`{parent id: {child ids}}` from an intent's `attach` list."""
   ```

   Raise `RpcError("ir_invalid", ...)` when `intent` is not a dict, when `attach`
   is not a list, or when an entry lacks a string `parent` or `child`. The message
   must name `intent` so a caller can tell this apart from a node problem.

3. In `_m_ir_propose`, read `intent = params.get("intent") or {}` before the
   rights loop, and build `attach_map = attachments(intent)`.

4. Replace the rights loop's rejection with the following. Build the id map
   **once, before** the loop — the name `by_id` is used by step 5 too:

   ```python
   by_id = {n["id"]: n for n in self.doc["nodes"]}
   for node in fragment["nodes"]:
       kind = node.get("kind")
       if kind in allowed:
           continue
       # RFC-0010: a node outside this role's rights is permitted for attachment
       # only, and only when the edit does nothing but add the declared children.
       declared = attach_map.get(node.get("id"), set())
       if declared and reference_only_edit(node, by_id.get(node.get("id")),
                                           declared):
           continue
       raise RpcError("ir_invalid",
                      "role %s may not propose %s nodes" % (role, kind))
   ```

   **Keep the rejection message byte-identical** — an existing test asserts on it.

5. Validate D7's containment and D9's kind-compatibility, after the rights loop.
   `authored = {n["id"] for n in fragment["nodes"]} - set(by_id)`.

   For every `attach` entry:
   - the `child` must be in `authored`; otherwise `RpcError("ir_invalid", …)`
     naming the child and saying a proposal may attach only a node it authored in
     the same proposal. Without this a role could re-parent anything.
   - the `parent`'s kind must be allowed to own the `child`'s kind. **Nothing in
     the codebase checks this today** — RFC-0004 §S2's invariant V5 (`kind별
     children 허용 종별 준수`) is unimplemented, and the schema types `children` as
     an unrestricted id array, so an audit attached a `WorkflowStep` to an
     `Entity` and it was approved. Add the table to `protocol.py`, transcribed
     from RFC-0001 §노드 카탈로그's *children 허용* column:

     ```python
     CHILDREN_ALLOWED = {
         "Entity": {"Validation"},
         "Service": {"Workflow", "Pipeline", "BusinessRule"},
         "Workflow": {"WorkflowStep", "Guard", "Concurrency", "Pipeline"},
         "Event": set(), "Capability": set(),
         "BusinessRule": set(), "Validation": set(),
         "WorkflowStep": {"Validation", "BusinessRule", "NetworkCall",
                          "RepositoryCall", "CacheAccess", "Transaction",
                          "Authorization", "EventEmit", "Concurrency", "Pipeline"},
         "Guard": {"WorkflowStep", "Concurrency", "Pipeline"},
         "Pipeline": {"WorkflowStep"},
         "Concurrency": {"WorkflowStep"},
         "NetworkCall": set(), "RepositoryCall": set(), "CacheAccess": set(),
         "Transaction": {"RepositoryCall", "NetworkCall", "CacheAccess",
                         "EventEmit", "BusinessRule", "Validation"},
         "Authorization": set(), "EventEmit": set(),
         "Policy": set(), "Security": set(), "Performance": set(),
     }
     ```

     Reject with `RpcError("ir_invalid", …)` naming both kinds. Scope note: this
     gates `attach` only; enforcing V5 across a whole document is filed separately
     (plan §out of scope).

6. Require `meta.origin` on the reference-only edit (D9b): a node accepted through
   the attachment exception must carry `meta.origin` matching `^agent:` — otherwise
   the merged document keeps no record that a role reached outside its rights.
   Reject with `ir_invalid` naming the node.

7. Store the intent on the proposal so the Reviewer sees the same thing the
   server validated: add `"intent": intent` to the `self.proposals[pid]` dict.

8. Add tests to `impl/tests/test_protocol.py`, following its existing style. Nine,
   grouped in one class `TestProposalIntent`:
   - **normal** a `RefactoringAgent` proposal containing a reference-only
     `Workflow` edit plus the authored step is accepted (no raise), where the
     `Workflow`'s only delta is the declared child.
   - **normal** the stored proposal carries the intent (`server.proposals[pid]
     ["intent"]`).
   - **error** the same `Workflow` edit **without** an `attach` entry still
     raises, message containing `may not propose Workflow`.
   - **error** a `Workflow` edit that also changes `name` while attaching raises —
     this is condition (b), and it is what stops the mechanism becoming a
     general-purpose escape hatch.
   - **error** an `attach` whose `child` already exists in the document raises,
     message naming the child (D7).
   - **error** `test_reordering_children_while_attaching_is_rejected` — the
     `Workflow` edit adds the declared child **and** reverses the two existing
     ones. Assert it raises. `children` order is execution order (RFC-0001 rule
     3), and a set-based condition approved this in audit.
   - **error** `test_migrating_a_reference_between_fields_is_rejected` — a
     `Service` edit that moves a `Policy` id out of `constraints` into `children`
     while attaching. Set-identical, so only per-field equality catches it; the
     interpreter reads `constraints` for retry, and audit measured this silently
     dropping retry.
   - **error** `test_attaching_a_child_the_parent_may_not_own_is_rejected` —
     attach a `WorkflowStep` to an `Entity` (RFC-0001: `Entity` children =
     `Validation` only). Assert the message names both kinds.
   - **boundary** `intent` absent entirely → behaves exactly as before (a
     within-rights proposal succeeds, an out-of-rights one raises). This is the
     compatibility assertion.

## Deliverables

- `impl/lnpl/protocol.py` (modified)
- `impl/tests/test_protocol.py` (modified — one new class)

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK` with **345 + your new tests**, and no failures. The 345 must pass
untouched — that is D5's compatibility claim, and any edit to an existing test to
make it pass means the change was not backward compatible.

Then prove the new gate can refuse. Make each mutation, require red, revert:

| Mutation | Must turn red |
|---|---|
| Drop condition (c) — stop comparing non-reference fields | the "also changes `name`" test |
| Make (d) set-based: compare `set(remaining) == set(before or [])` | the reordering test **and** the field-migration test. If it reddens only one, the other condition is not doing what this task claims |
| Drop the D7 containment check | the "child already exists" test |
| Drop the `CHILDREN_ALLOWED` check | the `WorkflowStep`-on-`Entity` test |
| Drop the `meta.origin` requirement | its own test |
| Make `reference_only_edit` return `True` unconditionally | several of the above |

```bash
PYTHONPATH=impl .venv/bin/python -m unittest -v tests.test_protocol.TestProposalIntent
```

If a mutation stays green, that branch is decoration.

## Out of scope

- `Reviewer._assess` — task 03. This task's gate is the propose-time one; the
  review-time gate is a second, independent check and a test in `test_agents.py`
  relies on that independence.
- `RefactoringAgent` itself — task 04.
- The `removal:`/`move` relaxation — task 03 owns it, because that check lives in
  the Reviewer.
