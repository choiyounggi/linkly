"""Mutation check — proves the suite can fail.

Each mutation removes one rule the specification requires. The suite must go
RED for every one of them; a mutation that survives means the rule is asserted
nowhere, and the suite is decoration for that rule.

    python3 impl/tests/mutation_check.py        # from the repo root

Exit 0 only when every mutation is caught.
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
    ("RFC-0003: enforce the response SLO instead of measuring it",
     "lnpl/interp.py",
     'result["slo_met"] = total <= con["response_slo_ms"]',
     'result["slo_met"] = total <= con["response_slo_ms"]\n            result["status"] = "failed" if not result["slo_met"] else result["status"]'),
]


VENV_PY = os.path.join(REPO, ".venv", "bin", "python")
PYTHON = VENV_PY if os.access(VENV_PY, os.X_OK) else sys.executable


def run_suite(tree, timeout=180):
    """Run the suite inside `tree`. Returns 'GREEN' | 'RED' | 'HANG'."""
    env = dict(os.environ, PYTHONPATH=tree, LNPL_REPO=REPO)
    try:
        proc = subprocess.run(
            [PYTHON, "-m", "unittest", "discover",
             "-s", os.path.join(tree, "tests"), "-t", tree],
            capture_output=True, text=True, timeout=timeout, env=env, cwd=REPO)
    except subprocess.TimeoutExpired:
        return "HANG"
    return "GREEN" if proc.returncode == 0 else "RED"


def main():
    baseline = run_suite(IMPL)
    if baseline != "GREEN":
        print("baseline suite is not green (%s) — fix that first" % baseline)
        return 1
    print("baseline: GREEN")

    failures = []
    for label, relpath, original, mutated in MUTATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            tree = os.path.join(tmp, "impl")
            shutil.copytree(IMPL, tree)
            target = os.path.join(tree, relpath)
            with open(target, encoding="utf-8") as fh:
                text = fh.read()
            if original not in text:
                print("  SKIP  %-58s (anchor not found — mutation is stale)" % label)
                failures.append(label + " [stale anchor]")
                continue
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(text.replace(original, mutated, 1))
            verdict = run_suite(tree)
            caught = verdict in ("RED", "HANG")
            print("  %-5s %-58s %s"
                  % ("CAUGHT" if caught else "SURVIVED", label, verdict))
            if verdict == "HANG":
                failures.append(label + " [hangs instead of failing]")
            elif verdict == "GREEN":
                failures.append(label)

    print()
    if failures:
        print("MUTATION CHECK: FAIL — %d mutation(s) not cleanly caught:" % len(failures))
        for f in failures:
            print("  - %s" % f)
        return 1
    print("MUTATION CHECK: PASS — all %d mutations caught by a failing test"
          % len(MUTATIONS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
