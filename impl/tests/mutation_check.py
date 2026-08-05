"""Mutation check — proves the suite can fail.

Each mutation removes one rule the specification requires. The suite must go
RED for every one of them; a mutation that survives means the rule is asserted
nowhere, and the suite is decoration for that rule.

    .venv/bin/python impl/tests/mutation_check.py     # from the repo root

Exit 0 only when the no-op control SURVIVES *and* every mutation is caught.

**The control is not optional.** An earlier version of this harness copied only
`impl/` into the mutant tree, but the tests resolve the repo from `__file__` and
read `examples/login.lir.json`, so every mutant died on a missing file before any
rule ran — "all caught" while proving nothing. The no-op control (a mutation that
provably cannot change behaviour) is what detects that class of failure: if the
control goes RED, the harness is broken and no other result means anything.
"""

import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMPL = os.path.join(REPO, "impl")

# (label, file, original fragment, mutated fragment)
MUTATIONS = [
    ("R2: drop the redundant-kind-word strip",
     "lnpl/lower.py",
     "if word and len(parts) > 1 and parts[-1] == word:",
     "if False:"),
    ("R1: remove `cache` from the verb lexicon",
     "lnpl/lower.py",
     '"cache": ("CacheAccess", {"operation": "set"}),',
     ""),
    ("R1: let an unknown verb fall back to a RepositoryCall",
     "lnpl/lower.py",
     "    entry = VERB_LEXICON.get(verb)\n    if entry is None:\n        return None",
     '    entry = VERB_LEXICON.get(verb)\n    if entry is None:\n        entry = ("RepositoryCall", {"operation": "read"})'),
    ("RFC-0003: drop the retry attempt cap",
     "lnpl/interp.py",
     'if attempts > con["retry"]:\n            return False',
     "if False:\n            return False"),
    ("RFC-0003: allow retrying non-idempotent effects",
     "lnpl/interp.py",
     'if eff["kind"] in ("RepositoryCall", "CacheAccess") and key not in IDEMPOTENT_OPS:\n                return False',
     'if False:\n                return False'),
    ("RFC-0003: retry an at-least-once emit / network call",
     "lnpl/interp.py",
     'if eff["kind"] in ("NetworkCall", "EventEmit"):\n                return False',
     "if False:\n                return False"),
    ("RFC-0003: stop masking Password",
     "lnpl/interp.py",
     'MASKED_TYPES = ("Password",)',
     "MASKED_TYPES = ()"),
    ("RFC-0003: drop the metric label allowlist",
     "lnpl/interp.py",
     "        if extra:\n            raise RunError",
     "        if False:\n            raise RunError"),
    ("RFC-0003: allow a cache write without a TTL",
     "lnpl/interp.py",
     "        if ttl_ms is None:\n            raise RunError",
     "        if False:\n            raise RunError"),
    # Re-anchored 2026-08-05: RFC-0012 added the execution scope, so
    # `_condition_holds` takes the bindings as a third argument and the old
    # anchor's text no longer exists in the file.
    ("Guard: ignore `when` and always run the guarded item",
     "lnpl/interp.py",
     'if not _condition_holds(node.get("condition"), payload, bindings):',
     "if False:"),
    # RFC-0012 / issue #37. The guard must read the row a completed read bound,
    # not the input payload. Reverting the qualified branch to a payload lookup
    # restores exactly the defect the issue reports, so the suite must kill it.
    ("Guard: resolve a qualified reference against the payload instead of the bound row",
     "lnpl/interp.py",
     '    binding, _, field = name.partition(".")\n'
     '    row = bindings.get(binding)\n'
     '    if not isinstance(row, dict):\n'
     '        return None\n'
     '    return row.get(field)',
     '    binding, _, field = name.partition(".")\n'
     '    _unused = bindings.get(binding)\n'
     '    return payload.get(field)'),
    # RFC-0012: guards and `spec … expect` must share ONE scope. Cutting the
    # bindings out of the expectation path forks it into two, which is the
    # failure this task exists to prevent — so a test must notice.
    ("spec: evaluate `result` against an empty scope instead of the run's bindings",
     "lnpl/spec.py",
     '        ok = _condition_holds(text, result.get("payload", {}),\n'
     '                              result.get("bindings", {}))',
     '        ok = _condition_holds(text, result.get("payload", {}), {})'),
    ("Guard: run `repeat` once instead of `count` times",
     "lnpl/interp.py",
     'for _ in range(int(node["count"])):',
     "for _ in range(1):"),
    # Re-anchored 2026-08-02: RFC-0008 replaced the hand-rolled
    # `<field> missing|exists` check with parse_condition, so the old anchor's
    # error string no longer exists. This is issue #3's acceptance bullet
    # "평가 불가 조건 수용" — mode A must refuse a condition it cannot evaluate
    # rather than treating it as true.
    ("Guard: accept an unevaluable condition instead of refusing it",
     "lnpl/interp.py",
     '    except ConditionError as e:\n        raise RunError(f"Invalid condition: {e}")',
     '    except ConditionError:\n        return True'),
    ("Capability attribution: guess instead of failing on a multi-service module",
     "lnpl/lower.py",
     'raise LowerError(\n                "service %s declares no `database` clause',
     'requires = list(cap_ids)\n            _unused = (\n                "service %s declares no `database` clause'),
    ("spec: treat an unsupported expectation as a pass",
     "lnpl/spec.py",
     '            if check is None:\n                failed += 1',
     '            if check is None:\n                passed += 1'),
    ("mode B: emit steps in the wrong order",
     "lnpl/backend.py",
     '        if kind == "WorkflowStep":\n            out.append((node, None))',
     '        if kind == "WorkflowStep":\n            out.insert(0, (node, None))'),
    # Re-anchored 2026-08-01: the S4 work moved this loop from reading the IR
    # (step["children"] + nodes[...]["kind"]) to reading the lnpl op stream.
    ("mode B: drop the effect calls",
     "lnpl/backend.py",
     '            for cn, effect in enumerate(entry["effects"]):\n                ksym = strings[effect["kind"]]\n                lines.append("    %%k%d_%d = llvm.mlir.addressof @%s : !llvm.ptr"',
     '            for cn, effect in enumerate([]):\n                ksym = strings[effect["kind"]]\n                lines.append("    %%k%d_%d = llvm.mlir.addressof @%s : !llvm.ptr"'),
    ("S4: emit an lnpl module that loses its node ids",
     "lnpl/backend.py",
     '                ("lnpl.node_id", op["node_id"]),\n                ("lnpl.name", op["name"]),',
     '                ("lnpl.node_id", "x"),\n                ("lnpl.name", op["name"]),'),
    ("S4: stop gating the build on the dialect verifier",
     "lnpl/backend.py",
     "    verify_lnpl_module(lnpl_text, path=lnpl_path)",
     "    pass  # verify_lnpl_module(lnpl_text, path=lnpl_path)"),
    ("S4: drop the MLIR location, keeping only the discardable attribute",
     "lnpl/backend.py",
     '        lines.append(\'  "lnpl.step"() {%s} : () -> () loc(%s)\' % (',
     '        lines.append(\'  "lnpl.step"() {%s} : () -> () // loc(%s)\' % ('),
    ("differential: skip the comparison when the toolchain is missing",
     "lnpl/differential.py",
     "    if not backend.toolchain_available():\n        raise DifferentialError(",
     "    if False:\n        raise DifferentialError("),
    ("OpenAPI: emit an empty schema for an unmapped semantic type",
     "lnpl/openapi.py",
     '        if tname not in TYPE_SCHEMA:\n            raise OpenApiError(',
     '        if False:\n            raise OpenApiError('),
    ("KB: let route() read document bodies (breaks the routing tier)",
     "lnpl/kb.py",
     'haystack = _tokens(meta["triggers"] + " " + doc_id.replace("-", " "))',
     'haystack = _tokens(meta["triggers"] + " " + doc_id.replace("-", " ") + " " + open(meta["path"], encoding="utf-8").read())'),
    ("KB: return a guess instead of an empty route result",
     "lnpl/kb.py",
     "        return [doc_id for _score, doc_id in scored]",
     "        return [doc_id for _score, doc_id in scored] or sorted(self.index())[:1]"),
    ("protocol: let ir.propose mutate the document directly",
     "lnpl/protocol.py",
     '        pid = "prop-%04d" % (len(self.proposals) + 1)',
     '        self.doc["nodes"].extend(fragment["nodes"])\n        pid = "prop-%04d" % (len(self.proposals) + 1)'),
    ("protocol: drop the idempotency key requirement",
     "lnpl/protocol.py",
     '        if not key:\n            raise RpcError("ir_invalid",',
     '        if False:\n            raise RpcError("ir_invalid",'),
    ("protocol: let any role approve a proposal",
     "lnpl/protocol.py",
     '        if not ROLES[task.role]["approve"]:',
     "        if False:"),
    ("protocol: leak internal exception detail to the caller",
     "lnpl/protocol.py",
     '            return self._err(rid, RpcError("internal", "internal error"))',
     '            import traceback\n            return self._err(rid, RpcError("internal", traceback.format_exc()))'),
    ("agents: propose an Effect without attaching it to its step",
     "lnpl/agents.py",
     '        return {"module": self.server.doc["module"],\n                "nodes": [parent,',
     '        return {"module": self.server.doc["module"],\n                "nodes": [' ),
    ("agents: let the Coder prescribe for any routed step",
     "lnpl/agents.py",
     '        if step.split()[0] != "generate":\n            return None',
     "        if False:\n            return None"),
    ("lowering: drop the goal clause (a declaration that does nothing)",
     "lnpl/lower.py",
     '        for n, line in enumerate(d.clauses.get("goal", []), start=1):',
     '        for n, line in enumerate([], start=1):'),
    ("lowering: pick an entity instead of reporting ambiguity",
     "lnpl/lower.py",
     "    if len(registry) == 1:\n        return next(iter(registry.values()))",
     "    if len(registry) >= 1:\n        return next(iter(registry.values()))"),
    ("EventEmit: emit without a unique id (breaks consumer dedupe)",
     "lnpl/interp.py",
     '"emission_id": "%s#%d" % (effect["id"], len(self.outbox) + 1)',
     '"emission_id": "fixed"'),
    ("EventEmit: publish the payload unmasked",
     "lnpl/interp.py",
     '"payload": mask_payload(payload, self._entity_node())',
     '"payload": dict(payload)'),
    ("Reviewer: rubber-stamp instead of assessing",
     "lnpl/agents.py",
     "        if approve is None:\n            ok, why = self._assess(proposal_id)",
     "        if approve is None:\n            ok, why = (True, 'ok')\n            _unused = self._assess"),
    ("Reviewer: stop checking provenance on new nodes",
     "lnpl/agents.py",
     '        if bad_source:\n            return False, ("provenance:',
     '        if False:\n            return False, ("provenance:'),
    ("Structure gate: stop checking ownership (let orphans through)",
     "lnpl/protocol.py",
     '    if orphans:\n        return ("orphan:',
     '    if False:\n        return ("orphan:'),
    ("Architect: propose from an incomplete spec",
     "lnpl/agents.py",
     '            if key not in (spec or {}):\n                return self._refuse(',
     '            if False:\n                return self._refuse('),
    ("PerformanceAnalyzer: propose a budget with no measurements",
     "lnpl/agents.py",
     '        if not measurements:\n            return self._refuse(',
     '        if not measurements:\n            measurements = [{"duration_ms": 1}]\n        if False:\n            return self._refuse('),
    ("Tester: emit an expectation the runner cannot evaluate",
     "lnpl/agents.py",
     '        happy = {"name": "%s happy path" % wf["name"], "workflow": workflow_id,\n                 "given": ["valid account"], "when": ["run"],\n                 "expect": ["completed", "steps %d" % step_count]}',
     '        happy = {"name": "%s happy path" % wf["name"], "workflow": workflow_id,\n                 "given": ["valid account"], "when": ["run"],\n                 "expect": ["vibes good", "steps %d" % step_count]}'),
    ("Structure gate: stop checking dangling references (runs on apply + review)",
     "lnpl/protocol.py",
     "    if dangling:\n        return (",
     "    if False:\n        return ("),
    ("Reviewer: check `children` only, ignoring named references (rule 6)",
     "lnpl/protocol.py",
     'NAMED_REF_FIELDS = ("requires", "constraints", "entity", "event")',
     "NAMED_REF_FIELDS = ()"),
    ("Structure gate: check ownership of new nodes only (allows removal-by-edit)",
     "lnpl/protocol.py",
     '    orphans = sorted(n["id"] for n in merged.values()\n                     if n["kind"] not in ENTRY_KINDS and n["id"] not in owners)',
     '    orphans = sorted(n["id"] for n in [] if n["kind"] not in ENTRY_KINDS)'),
    ("Structure gate: let a node have two owners (rule 2)",
     "lnpl/protocol.py",
     "    if contested:\n        return (",
     "    if False:\n        return ("),
    ("Structure gate: check self-loops only, not longer ownership cycles (rule 4)",
     "lnpl/protocol.py",
     "                if colour[kid] == grey:\n                    return path[path.index(kid):] + [kid]",
     "                if colour[kid] == grey and kid == node_id:\n                    return path[path.index(kid):] + [kid]"),
    # issue #15: the document-wide invariants #15 added, now that _structure_fault
    # runs on the apply path too. (V1 id-uniqueness is enforced earlier, at
    # propose time, so a duplicate never reaches this gate — it is covered there.)
    ("Structure gate: stop enforcing V5 children allowance document-wide",
     "lnpl/protocol.py",
     "            if child_kind and child_kind not in CHILDREN_ALLOWED.get(parent_kind, set()):\n                return (\"v5_children:",
     "            if False:\n                return (\"v5_children:"),
    ("Structure gate: stop enforcing Guard cardinality (exactly one child)",
     "lnpl/protocol.py",
     "            if children_count != 1:\n                return (\"guard_cardinality:",
     "            if False:\n                return (\"guard_cardinality:"),
    # Re-anchored 2026-08-03: RFC-0010 narrowed this condition from "any dropped
    # reference" to "a dropped reference no declared move accounts for", so the
    # old `if dropped:` anchor no longer exists.
    ("Reviewer: allow a replacement to drop references (removal by edit)",
     "lnpl/agents.py",
     '                    if (node["id"], ref) not in move_map:',
     "                    if False:"),

    # RFC-0010 (2026-08-03). Every branch the attachment exception introduced.
    # Its whole content is "write a reference into a node whose kind you do not
    # own", so a gate here that only ever says yes is indistinguishable from a
    # deleted one. The union-set entry is the important one: comparing references
    # as one set across all fields is what let an audit reverse a workflow's
    # execution order and migrate a Policy out of `constraints`.
    ("Intent: compare references as one set instead of per field, in order",
     "lnpl/protocol.py",
     """    for field in REFERENCE_KEYS:
        before, after = existing.get(field), proposed.get(field)""",
     """    added = set(node_references(proposed)) - set(node_references(existing))
    if added != set(declared_children):
        return False
    return True
    for field in REFERENCE_KEYS:
        before, after = existing.get(field), proposed.get(field)"""),
    ("Intent: accept any out-of-rights edit, ignoring the other fields",
     "lnpl/protocol.py",
     "    if _comparable(proposed) != _comparable(existing):\n        return False",
     "    if False:\n        return False"),
    ("Intent: let a proposal attach a node it did not author (propose time)",
     "lnpl/protocol.py",
     "                if child not in authored:",
     "                if False:"),
    ("Intent: attach a child its parent may not own (V5, propose time)",
     "lnpl/protocol.py",
     "                if child_kind not in CHILDREN_ALLOWED.get(parent_kind, set()):",
     "                if False:"),
    ("Intent: accept an out-of-rights edit with no agent origin",
     "lnpl/protocol.py",
     '                if not origin.startswith("agent:"):',
     "                if False:"),
    ("Intent: let a proposal attach a node it did not author (review time)",
     "lnpl/agents.py",
     "                if child not in authored:",
     "                if False:"),
    ("Intent: attach a child its parent may not own (V5, review time)",
     "lnpl/agents.py",
     "                if child_kind not in CHILDREN_ALLOWED.get(parent_kind, set()):",
     "                if False:"),
    ("Intent: accept a move whose destination takes it in another field",
     "lnpl/agents.py",
     "            if node_id not in _refs_in(merged.get(to_id), field):",
     "            if False:"),
    # The agent rather than a gate: this proves the split is a *move*, not a
    # duplication. Leaving the access on both steps is contested ownership, which
    # `_structure_fault` catches — so this also exercises that the invariant gate
    # is still what does the structural work.
    ("Refactoring: duplicate the access instead of moving it",
     "lnpl/agents.py",
     """        original["children"] = [c for c in step.get("children", [])
                                if c not in extra_call_ids]""",
     '        original["children"] = list(step.get("children", []))'),
    ("Refactoring: split a step under any owner, not just Workflow/Pipeline",
     "lnpl/agents.py",
     '            if owner is None or owner.get("kind") not in self.SPLITTABLE_OWNERS:',
     "            if False:"),
    # Added after an adversarial review of the branch found both of these live.
    ("Intent: compare dropped references across fields instead of per field",
     "lnpl/agents.py",
     """            for field in sorted(REFERENCE_KEYS):
                gone = sorted(_refs_in(old, field) - _refs_in(node, field))""",
     """            for field in ["children"]:
                gone = sorted(set(node_references(old)) - set(node_references(node)))"""),
    ("Intent: accept a move whose destination already referenced the node",
     "lnpl/agents.py",
     "            if node_id in _refs_in(existing.get(to_id), field):",
     "            if False:"),
    # Re-anchored 2026-08-03 (#16): the attachment widening replaced the single
    # `allowed_new = declared_children if field == "children" else ()` expression
    # with an if/elif/else, so the mutation now targets the else branch — letting a
    # field that is neither `children` nor a Constraint's `constraints` take the
    # declared additions is the same "write into any reference field" fault.
    ("Intent: let an attachment be written into any reference field",
     "lnpl/protocol.py",
     "        else:\n            allowed_new = ()",
     "        else:\n            allowed_new = declared_children"),
    ("Intent: accept a fragment that names one id twice",
     "lnpl/protocol.py",
     "        if repeated:",
     "        if False:"),
    ("Refactoring: invent a name when the entity has none",
     "lnpl/agents.py",
     '        if not entity or not isinstance(entity.get("name"), str):\n            return None',
     "        if False:\n            return None"),
    ("Refactoring: propose even when no step owns two accesses",
     "lnpl/agents.py",
     "        if not violations:\n            return self._refuse(",
     "        if False:\n            return self._refuse("),
    ("Refactoring: append the new step instead of running it next",
     "lnpl/agents.py",
     """        owner["children"] = (children[:at] + [s["id"] for s in new_steps]
                             + children[at:])""",
     '        owner["children"] = children + [s["id"] for s in new_steps]'),
    ("Reviewer: allow a kind swap under the same id",
     "lnpl/agents.py",
     '            if node.get("kind") != old.get("kind"):',
     "            if False:"),
    ("Reviewer: accept any non-empty provenance string",
     "lnpl/agents.py",
     "            if not source or not _SOURCE_FORM.match(source):",
     "            if not source:"),
    ("Reviewer: accept provenance that only matches the shape",
     "lnpl/agents.py",
     "            if not self._source_resolves(source, existing):",
     "            if False:"),
    ("Reviewer: stop checking the schema",
     "lnpl/agents.py",
     "        if self.server.validate is not None:",
     "        if False:"),
    ("SecurityAuditor: report a finding unconditionally",
     "lnpl/agents.py",
     '        if not findings:\n            return self._clean(task, "every affected service already declares Security")',
     '        findings = findings or [next(n for n in nodes.values() if n["kind"] == "Service")]\n        if False:\n            return self._clean(task, "every affected service already declares Security")'),
    ("SecurityAuditor: ignore the Password precondition",
     "lnpl/agents.py",
     '        if not secret_entities:\n            return self._clean(task, "no entity carries a Password field")',
     '        secret_entities = secret_entities or {n["id"] for n in nodes.values() if n["kind"] == "Entity"}\n        if False:\n            return self._clean(task, "no entity carries a Password field")'),
    ("ReleaseAgent: treat an empty verification map as evidence",
     "lnpl/agents.py",
     "        if not verification:",
     "        if verification is None:"),
    ("ReleaseAgent: accept a verification result that is not a map",
     "lnpl/agents.py",
     "        elif not isinstance(verification, dict):",
     "        elif False:"),
    ("ReleaseAgent: accept any truthy verification marker as a pass",
     "lnpl/agents.py",
     "                if ok is not True:",
     "                if not ok:"),
    ("PerformanceAnalyzer: accept non-positive durations",
     "lnpl/agents.py",
     "        if any(not isinstance(d, int) or isinstance(d, bool) or d <= 0\n               for d in durations):",
     "        if False:"),
    ("RFC-0003: enforce the response SLO instead of measuring it",
     "lnpl/interp.py",
     'result["slo_met"] = total <= con["response_slo_ms"]',
     'result["slo_met"] = total <= con["response_slo_ms"]\n            result["status"] = "failed" if not result["slo_met"] else result["status"]'),
]


VENV_PY = os.path.join(REPO, ".venv", "bin", "python")
PYTHON = VENV_PY if os.access(VENV_PY, os.X_OK) else sys.executable

# A mutation that provably cannot change behaviour. If the harness reports this as
# caught, the harness itself is broken (see the module docstring).
NOOP_CONTROL = ("CONTROL (must survive): reword a docstring",
                "lnpl/agents.py",
                '"""Two agents doing the RFC-0006 Examples round trip',
                '"""TWO AGENTS DOING the RFC-0006 Examples round trip')

# Copied into each mutant tree. The tests resolve the repo from __file__, so they
# need the data they read, not just the package.
#
# `plugins` and `.claude-plugin` arrived with the Claude Code plugin: the plugin
# tests read SKILL.md files, hooks.json, doctor.sh and the two manifests through
# REPO-relative paths, and the hook tests execute `plugins/lnpl/hooks/*.sh`.
# Omitting them cost 60 failures in every mutant tree (measured) — the same
# "cannot tell a caught mutation from a broken tree" failure described below.
#
# `mlir` and `CHARTER.md` arrived with the RFC-0004 S4 work: `build()` loads the
# dialect from `mlir/lnpl.irdl.mlir`, and a test asserts `CHARTER.md` to pin that
# `backend.REPO_ROOT` resolves to this repository. Omitting them made every
# mutant tree fail at the baseline — 41 errors reading a missing .irdl.mlir — so
# the harness could not tell a caught mutation from a broken tree.
TREE_CONTENTS = ("impl", "examples", "schemas", "scripts", "kb", "rfcs", "docs",
                 "plans", "mlir", "CHARTER.md", ".venv",
                 "plugins", ".claude-plugin", "AGENTS.md", "CLAUDE.md")


def make_tree(dest):
    """Build a runnable copy of the repo at `dest`. Returns the impl/ path."""
    os.makedirs(dest, exist_ok=True)
    for name in TREE_CONTENTS:
        src = os.path.join(REPO, name)
        if not os.path.exists(src):
            continue
        if name == ".venv":
            # The venv holds absolute paths; symlink instead of copying so the
            # interpreter and its packages resolve.
            os.symlink(src, os.path.join(dest, name))
        elif os.path.isfile(src):
            shutil.copy2(src, os.path.join(dest, name))
        else:
            shutil.copytree(src, os.path.join(dest, name), symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
    # Tests that build native binaries use `<repo>/.claude/tmp` as their scratch
    # directory, so the mutant tree needs it to exist.
    os.makedirs(os.path.join(dest, ".claude", "tmp"), exist_ok=True)
    return os.path.join(dest, "impl")


def run_suite(tree_root, timeout=300):
    """Run the suite inside a mutant tree root. Returns 'GREEN' | 'RED' | 'HANG'."""
    impl = os.path.join(tree_root, "impl")
    env = dict(os.environ, PYTHONPATH=impl)
    try:
        proc = subprocess.run(
            [PYTHON, "-m", "unittest", "discover",
             "-s", os.path.join(impl, "tests"), "-t", impl],
            capture_output=True, text=True, timeout=timeout, env=env,
            cwd=tree_root)
    except subprocess.TimeoutExpired:
        return "HANG"
    return "GREEN" if proc.returncode == 0 else "RED"


def _scratch():
    """Mutant trees live under the repo, never the system temp directory.

    This repo keeps generated trees and the native binaries their tests build
    out of the system scratch area; a harness that ignores that cannot be run
    here at all.
    """
    path = os.path.join(REPO, ".claude", "tmp")
    os.makedirs(path, exist_ok=True)
    return path


def apply_and_run(label, relpath, original, mutated):
    """Returns (verdict, note). verdict is GREEN|RED|HANG|STALE."""
    with tempfile.TemporaryDirectory(dir=_scratch()) as tmp:
        root = os.path.join(tmp, "repo")
        make_tree(root)
        target = os.path.join(root, "impl", relpath)
        with open(target, encoding="utf-8") as fh:
            text = fh.read()
        if original not in text:
            return "STALE", "anchor not found"
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(text.replace(original, mutated, 1))
        return run_suite(root), ""


def main():
    baseline_root = None
    with tempfile.TemporaryDirectory(dir=_scratch()) as tmp:
        baseline_root = os.path.join(tmp, "repo")
        make_tree(baseline_root)
        baseline = run_suite(baseline_root)
    if baseline != "GREEN":
        print("baseline (unmutated copy) is not green (%s) — the harness cannot "
              "distinguish a caught mutation from a broken tree. Fix that first."
              % baseline)
        return 1
    print("baseline (unmutated copy): GREEN")

    label, relpath, original, mutated = NOOP_CONTROL
    verdict, note = apply_and_run(label, relpath, original, mutated)
    print("  %-8s %-58s %s" % ("SURVIVED" if verdict == "GREEN" else "CAUGHT",
                               label, verdict + (" — " + note if note else "")))
    if verdict != "GREEN":
        print("\nMUTATION CHECK: FAIL — the no-op control did not survive. The "
              "harness is reporting RED for something other than the mutation, so "
              "every other result below would be meaningless. Nothing else was run.")
        return 1

    failures = []
    for label, relpath, original, mutated in MUTATIONS:
        verdict, note = apply_and_run(label, relpath, original, mutated)
        caught = verdict in ("RED", "HANG")
        print("  %-8s %-58s %s" % ("CAUGHT" if caught else "SURVIVED", label,
                                   verdict + (" — " + note if note else "")))
        if verdict == "STALE":
            failures.append(label + " [stale anchor]")
        elif verdict == "HANG":
            failures.append(label + " [hangs instead of failing]")
        elif verdict == "GREEN":
            failures.append(label + " [SURVIVED — no test asserts this rule]")

    print()
    if failures:
        print("MUTATION CHECK: FAIL — %d of %d mutation(s) not cleanly caught:"
              % (len(failures), len(MUTATIONS)))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("MUTATION CHECK: PASS — no-op control survived, and all %d mutations "
          "caught by a failing test" % len(MUTATIONS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
