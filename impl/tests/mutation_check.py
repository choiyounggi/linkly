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
    ("Guard: ignore `when` and always run the guarded item",
     "lnpl/interp.py",
     'if not _condition_holds(node.get("condition"), payload):',
     "if False:"),
    ("Guard: run `repeat` once instead of `count` times",
     "lnpl/interp.py",
     'for _ in range(int(node["count"])):',
     "for _ in range(1):"),
    ("Guard: accept any condition instead of refusing unknown ones",
     "lnpl/interp.py",
     'raise RunError("Phase 1 evaluates only `<field> missing|exists` conditions, "',
     'return True\n    raise RunError("unreachable, "'),
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
    ("mode B: drop the effect calls",
     "lnpl/backend.py",
     '            for cn, child_id in enumerate(step.get("children", [])):\n                ksym = strings[nodes[child_id]["kind"]]\n                lines.append("    %%k%d_%d = llvm.mlir.addressof @%s : !llvm.ptr"',
     '            for cn, child_id in enumerate([]):\n                ksym = strings[nodes[child_id]["kind"]]\n                lines.append("    %%k%d_%d = llvm.mlir.addressof @%s : !llvm.ptr"'),
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
    ("Reviewer: stop checking ownership (let orphans through)",
     "lnpl/agents.py",
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
    ("Reviewer: stop checking dangling references",
     "lnpl/agents.py",
     "    if dangling:\n        return (",
     "    if False:\n        return ("),
    ("Reviewer: check `children` only, ignoring named references (rule 6)",
     "lnpl/protocol.py",
     'NAMED_REF_FIELDS = ("requires", "constraints", "entity", "event")',
     "NAMED_REF_FIELDS = ()"),
    ("Reviewer: check ownership of new nodes only (allows removal-by-edit)",
     "lnpl/agents.py",
     '    orphans = sorted(n["id"] for n in merged.values()\n                     if n["kind"] not in ENTRY_KINDS and n["id"] not in owners)',
     '    orphans = sorted(n["id"] for n in [] if n["kind"] not in ENTRY_KINDS)'),
    ("Reviewer: let a node have two owners (rule 2)",
     "lnpl/agents.py",
     "    if contested:\n        return (",
     "    if False:\n        return ("),
    ("Reviewer: check self-loops only, not longer ownership cycles (rule 4)",
     "lnpl/agents.py",
     "                if colour[kid] == grey:\n                    return path[path.index(kid):] + [kid]",
     "                if colour[kid] == grey and kid == node_id:\n                    return path[path.index(kid):] + [kid]"),
    ("Reviewer: allow a replacement to drop references (removal by edit)",
     "lnpl/agents.py",
     "            if dropped:\n                return False,",
     "            if False:\n                return False,"),
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
TREE_CONTENTS = ("impl", "examples", "schemas", "scripts", "kb", "rfcs", "docs",
                 "plans", ".venv")


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


def apply_and_run(label, relpath, original, mutated):
    """Returns (verdict, note). verdict is GREEN|RED|HANG|STALE."""
    with tempfile.TemporaryDirectory() as tmp:
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
    with tempfile.TemporaryDirectory() as tmp:
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
