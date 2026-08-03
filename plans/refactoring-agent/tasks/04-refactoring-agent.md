# Task 04: implement RefactoringAgent

## Objective

`agents.RefactoringAgent` exists, splits a `WorkflowStep` that owns more than one
`RepositoryCall` into one step per access, and proposes nothing when it has no
prescription to stand on. All nine `protocol.ROLES` now have an implementation.

## Wiki pages (read these first, only these)

- `wiki/testing/quality/minimum-case-set.md` — the case set: the split, the
  refusal, and the boundaries (exactly one access; three accesses).
- `wiki/testing/quality/tests-that-cannot-fail.md` — an agent that proposes
  nothing always passes a test that only checks "it did not crash"; assert the
  proposal's content.

## Inputs

- From task 03: the Reviewer accepts a split whose intent declares the attach and
  the move. From task 02: `ir.propose` takes `intent`.
- **The prescription this agent implements** —
  `kb/patterns/patterns-repository-call.md`, `id: patterns-repository-call`,
  `version: 0.1.0`: *"**한 step에 한 저장소 접근.** 두 접근이 필요하면 두 step이다.
  step은 재시도·span의 단위이므로 접근을 묶으면 재시도가 둘을 함께 반복한다."*
  This is the only restructuring prescription in the KB (all 11 documents read).
- `impl/lnpl/agents.py` conventions, measured:
  - `_AgentBase.__init__(self, server)`; agents are constructed as
    `Reviewer(server)`.
  - `Coder._fragment_for` returns `None` for anything but `security-jwt-issuance`
    — the established way to refuse rather than invent. Follow it.
  - `SecurityAuditor`/`PerformanceAnalyzer` report `attachment_required` when they
    can author but not attach. **RefactoringAgent does not need that escape** any
    more: task 02/03 gave it a way to attach. Do not copy that pattern.
- Decisions that bind you: **D14** (one job, refuse otherwise), **D15** (ids and
  names), **D16** (provenance), **D5** (intent shape), **D7** (attach only what
  this proposal authored).

## Steps

1. Add `class RefactoringAgent(_AgentBase)` to `impl/lnpl/agents.py`, placed after
   `PerformanceAnalyzer` so the file order matches `protocol.ROLES`' reading order.

   Class docstring must state: the one prescription it implements, that a step is
   the unit of retry and span (which is *why* the KB says one access per step), and
   that it proposes nothing when no step violates the rule.

2. `def _violations(self, doc)` — return the list of steps to split, each as
   `(owner_id, step, [extra_call_ids])`:
   - a node with `kind == "WorkflowStep"` whose `children` include **more than
     one** node of kind `RepositoryCall`;
   - `owner_id` = the id of the node whose `children` contain this step. Find it by
     scanning; if nothing owns the step, skip it — an orphan is a structure fault,
     not a refactoring target, and `_structure_fault` owns that judgment.
   - **the owner's kind must be `Workflow` or `Pipeline`. Skip any other owner.**
     An audit of the first draft showed why: with a `Concurrency` owner the new
     step becomes a **parallel branch** (mode A is single-threaded, so no test
     would have caught it, while RFC-0004 S5 requires structured-concurrency
     preservation); with a `Guard` owner the guard ends up with two guarded items
     where RFC-0001 allows exactly one, and under `repeat 3` both repeat. Refusing
     is the `Coder._fragment_for → None` discipline this task already follows.
   - **Direct children only.** A `RepositoryCall` nested inside a `Transaction`
     child does not count, so a step with one direct and one nested access is not
     reported. That is under-detection, not a wrong answer — note it in the class
     docstring rather than silently differing from the KB rule.
   - `extra_call_ids` = the second and subsequent `RepositoryCall` children, in
     `children` order. The first stays with the original step, so the original
     keeps its id and its primary access (RFC-0004 §노드 id 안정성: no renaming).

3. `def _split(self, doc, workflow_id, step, extra_call_ids)` — return
   `(nodes, intent)`:

   - **new step ids**: `"%s.split.%d" % (workflow_id, n)`, `n` starting at 1 and
     skipping any id already present in `doc`. Follows RFC-0004 §변형의 형태's
     `<workflow id>.par.<n>` precedent for a synthesised sibling step and satisfies
     RFC-0001's id pattern (D15).
   - **new step name**: `"%s %s" % (verb, entity_name.split()[0].lower())` where
     `entity_name` is the `name` of the Entity node whose id is `call["entity"]`,
     and `verb` is `call["operation"]` except that **`query` maps to `find`** —
     `patterns-repository-call`'s dictionary has no `query` verb, and
     `find → RepositoryCall(read)` is the nearest entry it does define, so a name
     built from `query` would not round-trip through the verb dictionary the KB
     document owns. Taking only the first whitespace-delimited token of the entity
     name keeps the result inside `StepLine`'s token bounds. Example:
     `RepositoryCall(entity=entity.user, operation=update)` → `update user`.
     If the entity id does not resolve, skip this step — do not invent a name.
   - **the replaced step**: a copy of `step` whose `children` drop the extra call
     ids. Do not touch anything else about it.
   - **the parent edit**: a copy of the owner node whose `children` insert the new
     step ids **immediately after** the original step, so execution order stays
     `… original, split.1, …` rather than moving the new work to the end.
     `children` order is execution order (RFC-0001 Workflow row), so appending at
     the end would change the order of effects. It must also carry
     `meta.origin = "agent:RefactoringAgent"` — the gate requires it on a
     reference-only edit (D9b), since otherwise nothing records that a role reached
     outside its rights.

     **What the split preserves and what it does not** (D14b) — put this in the
     class docstring, because RFC-0006 says this role *"의미를 보존하며 구조를
     바꾼다"* and only half of that is true here. Preserved: the sequence of
     effects. **Not preserved: retry grouping.** The KB's whole reason for
     one-access-per-step is that a step is the unit of retry and span, so a moved
     access stops being retried together with the one it left. Measured with
     `retry 2` against a failing repository, the moved effect went from executing
     3× to 1×. That is the intended consequence of the prescription, not a defect —
     but calling it behaviour-preserving would be wrong.
   - **`meta` on new nodes**: `{"origin": "agent:RefactoringAgent",
     "source": "kb:patterns-repository-call@0.1.0"}` (D16). The replaced step and
     the parent keep their own `meta` — they are existing nodes, and stage 2 of the
     review only requires provenance on new ones.
   - **intent**: `{"attach": [{"parent": workflow_id, "child": new_id} …],
     "move": [{"node": call_id, "from": step["id"], "to": new_id} …]}`.

4. `def propose(self, deadline_ms=30000)` — find violations in `self.server.doc`;
   if none, return `None` and propose nothing. Otherwise build the fragment for the
   **first** violation and return the result of

   ```python
   self.server.call("ir.propose", role="RefactoringAgent",
                    ir_fragment={"lir_version": ..., "module": ..., "nodes": nodes},
                    intent=intent, deadline_ms=deadline_ms,
                    idempotency_key="refactor-%s" % step["id"])
   ```

   The return value is `ir.propose`'s result — `{proposal_id, state,
   review_task_id}` — passed through unchanged, which is what the Verify one-liner
   below indexes. The idempotency key is derived from the step id so a replay for
   the same violation is idempotent rather than a second proposal. One violation
   per call keeps each proposal reviewable on its own; the caller may call again.

   The `ir_fragment` must be a complete LIR document object —
   `{lir_version, module, nodes}` — per RFC-0006 §IR Fragment Embedding, taking
   `lir_version` and `module` from `self.server.doc`.

5. Add tests to `impl/tests/test_agents.py` in one class
   `TestRefactoringAgent`, reusing the `TWO_ACCESS` document task 03 added to that
   file (do not define a second copy):

   - **normal** `test_it_splits_a_step_with_two_repository_accesses` — propose,
     then approve through `Reviewer`, then assert the merged document has two steps
     each owning exactly one `RepositoryCall`, and that the workflow's `children`
     order is `[wf.w.step.1, wf.w.split.1]`.
   - **normal** `test_the_original_step_keeps_its_id_and_first_access` — assert
     `wf.w.step.1` still exists and still owns `wf.w.step.1.a`.
   - **normal** `test_the_new_step_is_grounded_in_the_kb` — assert the new node's
     `meta.source` is `kb:patterns-repository-call@0.1.0`.
   - **error** `test_it_proposes_nothing_when_no_step_violates_the_rule` — against
     `golden()` (whose steps own at most one access), `propose()` returns `None`
     and `server.proposals` stays empty. Assert **both**, or an agent that raised
     and was swallowed would pass.
   - **boundary** `test_a_step_with_exactly_one_access_is_not_a_violation` — one
     `RepositoryCall` is the boundary of "more than one".
   - **boundary** `test_three_accesses_split_into_three_steps` — two new steps,
     ids `…split.1` and `…split.2`, each owning one call.
   - **error** `test_it_refuses_a_step_owned_by_a_concurrency_node` — the same
     two-access step, but owned by a `Concurrency` node instead of the workflow.
     `propose()` returns `None` and no proposal is stored. Splitting there would
     make the new step a parallel branch, which mode A cannot reveal.
   - **error** `test_it_refuses_a_step_owned_by_a_guard` — same, with a `Guard`
     owner; RFC-0001 allows a guard exactly one guarded item.
   - **normal** `test_all_nine_roles_now_have_an_implementation` — assert
     `set(protocol.ROLES)` equals
     `{name for name, obj in inspect.getmembers(agents, inspect.isclass)
       if obj.__module__ == "lnpl.agents" and not name.startswith("_")}`.
     The `_`-prefix filter excludes `_AgentBase`; without it this fails on a class
     that is not a role. This is the test that makes "8 of 9" impossible to
     regress to.

## Deliverables

- `impl/lnpl/agents.py` (modified — one new class)
- `impl/tests/test_agents.py` (modified — one new class)

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK`, no failures, no existing test edited.

Then confirm the end-to-end job actually works through the real server, since the
tests could all pass with a proposal that never gets approved:

```bash
PYTHONPATH=impl .venv/bin/python -c "
import sys; sys.path.insert(0, 'impl/tests')
from tests.test_agents import TWO_ACCESS
from lnpl.agents import RefactoringAgent, Reviewer
from lnpl.kb import KnowledgeBase
from lnpl.protocol import Server
s = Server(TWO_ACCESS, KnowledgeBase())
out = RefactoringAgent(s).propose()
print('proposed:', out is not None)
print('review  :', Reviewer(s).decide(out['review_task_id'], out['proposal_id']))
steps = [n for n in s.doc['nodes'] if n['kind'] == 'WorkflowStep']
for st in steps:
    calls = [c for c in st.get('children', [])
             if any(n['id'] == c and n['kind'] == 'RepositoryCall' for n in s.doc['nodes'])]
    print('  %-16s owns %d access(es)' % (st['id'], len(calls)))
"
```

Success = the proposal is approved and **each step owns exactly 1 access**. If a
step still owns 2, the merge did not happen and the tests are asserting on
something other than the applied document.

Then the mutation check:

| Mutation | Must turn red |
|---|---|
| `_violations` returns `[]` always | the split tests |
| Append new steps at the end of `children` instead of after the original | the order assertion |
| Drop `meta.source` from new nodes | provenance rejects → the split tests |

## Out of scope

- Wiring `SecurityAuditor`/`PerformanceAnalyzer` to use the new attachment path.
  They still report `attachment_required`; the mechanism now exists for them, but
  changing their behaviour is a separate change (plan §out of scope).
- `mutation_check.py` entries — task 05.
