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
    ("RFC-0003: enforce the response SLO instead of measuring it",
     "lnpl/interp.py",
     'result["slo_met"] = total <= con["response_slo_ms"]',
     'result["slo_met"] = total <= con["response_slo_ms"]\n            result["status"] = "failed" if not result["slo_met"] else result["status"]'),
]


def run_suite(tree, timeout=60):
    """Run the suite inside `tree`. Returns 'GREEN' | 'RED' | 'HANG'."""
    env = dict(os.environ, PYTHONPATH=tree, LNPL_REPO=REPO)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover",
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
