# Implementation Plan: Issues #15, #16, #13 — Invariant Enforcement & Agent Attachment

**Date:** 2026-08-03  
**Methodology:** TDD (Test-First Development)  
**Baseline:** 386 tests, baseline failures from LLVM + jsonschema (ignored per spec)

---

## Overview

Three foundational protocol issues affecting document validation and agent integration:

1. **#15** — RFC-0004 invariants V1 (id uniqueness) & V5 (children kind allowance) not enforced document-wide
2. **#16** — SecurityAuditor & PerformanceAnalyzer cannot attach Constraints via RFC-0010 mechanism
3. **#13** — RFC-0006 & RFC-0010 require `kb_pins` parameter; no caller provides or validates it

**Implementation Order:** #15 (foundational) → #16 (builds on #15) → #13 (independent but affects all callers)

---

## Task #15: Enforce RFC-0004 Invariants V1 & V5 Document-Wide

**Context:**
- RFC-0004 §S2 defines 5 document-level invariants; only 3 currently enforced (V2, V3, V4)
- V1 (id uniqueness): only partially enforced at `ir.propose` time (RFC-0006 #14 refusal)
- V5 (kind-specific children): enforced nowhere except `attach` gate in protocol.CHILDREN_ALLOWED
- Gap: Architect, Coder, hand-written .lir.json, approval override all bypass these checks
- RFC-0001 §Guard row: "피가드 항목 1개" (exactly one guarded item) — cardinality not expressible in CHILDREN_ALLOWED

**Adoption Plan:**

1. **Move V5 enforcement into `_structure_fault`** (agents.py)
   - Add kind→allowed-children validation alongside V2/V3/V4
   - Run on merged document (not just proposed nodes)
   - Add Guard cardinality special-case: Guard must have exactly 1 child (RFC-0001)

2. **Add V1 enforcement to `_structure_fault`**
   - Check all node ids are unique in merged document
   - Runs alongside other structural checks

3. **Ensure override path is covered**
   - `_apply` method (protocol.py) calls `_structure_fault` only at proposal time
   - Approval override via `decide(approve=True)` reaches merge without validation
   - Add V1/V5 check to `_apply` if needed (or ensure Reviewer's `_assess` is always consulted first)

4. **Validate existing documents**
   - `examples/login.lir.json` and all fixtures must pass
   - If CHILDREN_ALLOWED is incorrect, mass failure (good) or silent permissiveness (bad)

5. **Document divergence handling**
   - Update `docs/CONSISTENCY-CHECK.md` with V1/V5 enforcement details (RFC-0007 §5)
   - Label section to avoid merge conflicts

**Done Criterion:**
- V1 & V5 checked in `_structure_fault` and apply path
- Guard cardinality (1 child) enforced via special case
- `examples/login.lir.json` passes validation
- Full test suite: no NEW failures vs baseline
- `docs/CONSISTENCY-CHECK.md` updated with new section

**Verify Command:** `PYTHONPATH=impl python3 -m unittest discover -s impl/tests -t impl 2>&1 | tail -5`

---

## Task #16: Wire SecurityAuditor & PerformanceAnalyzer to RFC-0010 Attachment

**Context:**
- RFC-0010 Open Question 1: "두 역할이 실제로 `intent`를 쓰도록 바꾸는 것은 별도 작업이다"
- Currently: both agents report `attachment_required` in their payloads
- Both can author Constraint nodes but cannot attach them to Services
- RFC-0010 recommends: widen `attach` to allow `constraints` field for Constraint kinds
- Condition: declared child's kind is Constraint (narrower than RFC-0010's "per-field order-preserving" rule)

**Adoption Plan:**

1. **Widen `reference_only_edit` (protocol.py)**
   - Line 226: `allowed_new = declared_children if field == "children" else ()`
   - Change to: allow `constraints` field when declared child's kind is in CONSTRAINT_KINDS
   - Keep same per-field order-preserving/additive rule for both `children` and `constraints`

2. **Replace `attachment_required` reports in SecurityAuditor (agents.py)**
   - Instead of reporting `attachment_required` with `{"node": svc["id"], "field": "constraints", "add": sec_id}`
   - Propose via `ir.propose` with `intent.attach` declaring attachment
   - Include additive edit to Service's `constraints` field (reference-only)
   - Test: Constraint is actually referenced afterwards

3. **Replace `attachment_required` reports in PerformanceAnalyzer (agents.py)**
   - Same pattern as SecurityAuditor
   - Propose Performance Constraint + reference-only edit to Service's `constraints`
   - Test: Constraint is actually referenced afterwards

4. **Update RFC-0010 §Methods/ir.propose text**
   - Clarify that `constraints` is allowed for Constraint-kind children
   - Keep RFC-0006 unchanged (RFC-0010 only updates its own sections)

**Done Criterion:**
- SecurityAuditor: proposes Constraint + reference-only Service edit with intent.attach
- PerformanceAnalyzer: proposes Constraint + reference-only Service edit with intent.attach
- New tests: proposal is APPROVED and Constraint is actually referenced in merged doc
- `mutation_check.py`: 2 new entries (one per agent) verified RED
- No existing test breakage

**Verify Command:** `PYTHONPATH=impl python3 -m unittest discover -s impl/tests -t impl 2>&1 | tail -5`

---

## Task #13: Enforce RFC-0006 `kb_pins` & `rationale` Parameters

**Context:**
- RFC-0006 §Methods declares `ir.propose` params: `{module, ir_fragment, rationale, kb_pins, _meta}`
- RFC-0006 & RFC-0010 both state `kb_pins` **필수** (required): `[{doc_id, version}]` or `[]` if not used
- Validation ④ in ### Errors not yet implemented
- No caller (Architect, Coder, SecurityAuditor, PerformanceAnalyzer, RefactoringAgent) passes `kb_pins`
- `rationale` never read; should be stored and threaded through

**Adoption Plan:**

1. **Add `kb_pins` validation to `_m_ir_propose` (protocol.py)**
   - Check `kb_pins` parameter is present
   - Must be a list of `{doc_id, version}` objects
   - Both values must be non-empty strings
   - Empty list `[]` is valid (means no KB documents used)
   - Reject if missing or wrong shape with `ir_invalid` error

2. **Store `rationale` in proposal object**
   - Add `rationale` field to proposal dict in `_m_ir_propose`
   - Thread through to Reviewer's assessment (if needed)
   - Currently not used by Reviewer, but stored for audit trail

3. **Update all 5 callers to pass `kb_pins`:**
   - **Architect** (agents.py:484): has pinned KB doc → pass its pins; or `[]`
   - **Coder** (agents.py:205): pinned KB doc (`routed[0]`) → pass it
   - **SecurityAuditor** (agents.py:557): pinned KB doc → pass it
   - **PerformanceAnalyzer** (agents.py:631): uses `ir:` provenance → pass `[]`
   - **RefactoringAgent** (agents.py:858): uses KB doc `patterns-repository-call` → pass its pins

4. **Update RFC-0006 §Methods/ir.propose**
   - Clarify `kb_pins` validation rules (already in spec, just not implemented)

5. **Add test coverage**
   - Normal: valid kb_pins list passes
   - Error: missing kb_pins → `ir_invalid`
   - Error: wrong shape (not a list, not objects, missing keys) → `ir_invalid`
   - Boundary: empty list `[]` is valid

**Done Criterion:**
- `kb_pins` parameter validated in `_m_ir_propose`
- All 5 agents pass valid `kb_pins` values
- Existing tests still pass
- New test cases: missing key, wrong shape, empty list all work
- Full test suite: no NEW failures vs baseline
- RFC-0006 text verified accurate

**Verify Command:** `PYTHONPATH=impl python3 -m unittest discover -s impl/tests -t impl 2>&1 | tail -5`

---

## Mutation Check Entries (to add in mutation_check.py)

For issues #15, #16, #13:

```python
# #15: Invariant V1 (id uniqueness)
("RFC-0004: drop id uniqueness check from _structure_fault",
 "lnpl/agents.py",
 "    ids = [n[\"id\"] for n in merged.values()]\n    repeated = [i for i in set(ids) if ids.count(i) > 1]\n    if repeated:",
 '    if False:'),

# #15: Invariant V5 (kind-specific children)
("RFC-0004: allow any kind as children (drop V5 check)",
 "lnpl/agents.py",
 "    for node in merged.values():\n        for child_id in node.get(\"children\", []):\n            child_kind = merged.get(child_id, {}).get(\"kind\")\n            if child_kind and child_kind not in CHILDREN_ALLOWED.get(node[\"kind\"], set()):",
 '    if False:  # V5 check'),

# #15: Guard cardinality (exactly 1)
("RFC-0001: allow Guard with multiple children",
 "lnpl/agents.py",
 "    for node in merged.values():\n        if node.get(\"kind\") == \"Guard\" and len(node.get(\"children\", [])) != 1:",
 '    if False:  # Guard cardinality'),

# #16: Allow constraints field for Constraint attachment
("RFC-0010: forbid Constraint attachment via constraints field",
 "lnpl/protocol.py",
 '        allowed_new = declared_children if field == "children" else ()',
 '        allowed_new = declared_children if field == "children" else (declared_children if field == "constraints" and any(...) else ())'),

# #13: kb_pins validation
("RFC-0006: drop kb_pins validation",
 "lnpl/protocol.py",
 "    kb_pins = params.get(\"kb_pins\")\n    if not isinstance(kb_pins, list):\n        raise RpcError(\"ir_invalid\", \"kb_pins must be an array\")",
 '    if False:  # kb_pins check'),
```

Each mutation verified RED before first commit.

---

## Files to Modify

### Core Implementation
- `impl/lnpl/protocol.py` — V1/V5 checks, kb_pins validation, constraints attachment
- `impl/lnpl/agents.py` — V1/V5 in _structure_fault, Guard cardinality, SecurityAuditor/PerformanceAnalyzer attachment
- `rfcs/0006-agent-protocol.md` — clarify kb_pins if needed
- `rfcs/0010-proposal-intent.md` — clarify constraints attachment

### Documentation
- `docs/CONSISTENCY-CHECK.md` — add V1/V5 enforcement section (labeled to avoid merge conflicts)

### Tests
- `impl/tests/test_protocol.py` — kb_pins validation, V1/V5 checks
- `impl/tests/test_agents.py` — SecurityAuditor/PerformanceAnalyzer attachment
- `impl/tests/mutation_check.py` — add 5 new mutation entries

---

## Test Strategy

Each task follows TDD:

1. **Write failing test(s)** — confirm RED
2. **Implement** — make GREEN
3. **Verify no regressions** — full suite clean
4. **Add to mutation_check.py** — verify each mutation is RED

Test coverage requirements:
- Normal path + error path + boundary cases for each feature
- Per RFC-0001 rule 5 & RFC-0006 §Reliability

---

## Commit Strategy

**One commit per issue**, referencing issue number in message:

```
fix(protocol): RFC-0004 invariants V1 & V5 enforced document-wide (#15)

- Move V5 (children kind allowance) check into _structure_fault
- Add V1 (id uniqueness) check to _structure_fault  
- Add Guard cardinality special case (exactly 1 child, RFC-0001)
- Ensure _apply path runs validation
- Update docs/CONSISTENCY-CHECK.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

Similar for #16 (attachment) and #13 (kb_pins).

---

## Success Criteria

### Overall
- ✓ All 3 issues implemented in order (#15 → #16 → #13)
- ✓ Zero NEW test failures vs baseline (386 tests)
- ✓ Mutation check: all new entries verified RED
- ✓ RFCs updated to match implementation
- ✓ Three atomic commits with proper attribution

### #15 Specific
- V1 & V5 enforced in `_structure_fault` and `_apply` path
- Guard cardinality enforced (exactly 1 child)
- `examples/login.lir.json` validates
- docs/CONSISTENCY-CHECK.md has labeled section

### #16 Specific
- SecurityAuditor proposes Constraint + Service reference edit via `intent.attach`
- PerformanceAnalyzer proposes Constraint + Service reference edit via `intent.attach`
- Both proposals APPROVED with Constraint actually referenced in merged doc
- Tests verify attachment actually worked

### #13 Specific
- `kb_pins` parameter required in `ir.propose`, validated
- All 5 agents pass valid kb_pins values
- Error cases: missing, wrong shape all rejected
- Boundary: empty list `[]` accepted
