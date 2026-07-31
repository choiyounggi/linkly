"""The golden scenario is machine-generated, not hand-maintained.

`examples/login.lir.json` must be exactly what the compiler emits from
`examples/login.lnpl`. This is what keeps the grammar, the IR, and the runtime
timeline from drifting apart as the RFCs change.
"""

import json
import os
import subprocess
import sys
import unittest

from lnpl.interp import Interpreter
from lnpl.lower import lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "examples", "login.lnpl")
GOLDEN_IR = os.path.join(REPO, "examples", "login.lir.json")
VALIDATOR = os.path.join(REPO, "scripts", "validate_ir.py")

PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
           "email": "user@example.com",
           "password": "s3cret-value",
           "createdAt": "2026-07-31T09:00:00Z"}


def compile_golden():
    with open(SRC, encoding="utf-8") as fh:
        return lower(parse(fh.read()), "login").to_document()


class TestGoldenPair(unittest.TestCase):
    def test_source_compiles_to_the_committed_ir(self):
        with open(GOLDEN_IR, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(compile_golden(), committed,
                         "examples/login.lir.json is stale — regenerate it with "
                         "`python3 -m lnpl compile examples/login.lnpl -o examples/login.lir.json`")

    def test_node_ids_and_order_are_stable(self):
        ids = [n["id"] for n in compile_golden()["nodes"]]
        self.assertEqual(ids[0], "svc.login")
        self.assertEqual(ids[-3:], ["cap.postgres", "cap.redis", "cap.jwt"])
        self.assertEqual(len(ids), len(set(ids)))       # ids are unique

    def test_committed_ir_passes_the_schema_validator(self):
        proc = subprocess.run([sys.executable, VALIDATOR, GOLDEN_IR],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_every_reference_resolves(self):
        doc = compile_golden()
        ids = {n["id"] for n in doc["nodes"]}
        for node in doc["nodes"]:
            for key in ("children", "requires", "constraints"):
                for ref in node.get(key, []):
                    self.assertIn(ref, ids, "dangling %s in %s" % (key, node["id"]))
            for key in ("entity", "event"):
                if key in node:
                    self.assertIn(node[key], ids)
            if "source" in node:
                self.assertIn(node["source"]["ref"], ids)

    def test_each_node_has_at_most_one_owner(self):
        doc = compile_golden()
        owners = {}
        for node in doc["nodes"]:
            for child in node.get("children", []):
                self.assertNotIn(child, owners,
                                 "%s is owned by both %s and %s"
                                 % (child, owners.get(child), node["id"]))
                owners[child] = node["id"]


class TestGoldenExecution(unittest.TestCase):
    def test_golden_runs_to_completion(self):
        doc = compile_golden()
        interp = Interpreter(doc, repo_rows={"entity.user": dict(PAYLOAD)})
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["steps"]), 6)

    def test_timeline_matches_the_declared_six_steps(self):
        doc = compile_golden()
        interp = Interpreter(doc, repo_rows={"entity.user": dict(PAYLOAD)})
        interp.run_workflow("wf.login", PAYLOAD)
        self.assertEqual([s.name for s in interp.trace.root.children],
                         ["validate input", "authenticate", "cache user",
                          "generate token", "audit login", "return token"])

    def test_golden_meets_its_own_response_slo(self):
        doc = compile_golden()
        interp = Interpreter(doc, repo_rows={"entity.user": dict(PAYLOAD)})
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertTrue(result["slo_met"], "golden run exceeded response < 50ms")

    def test_empty_repository_exercises_retry_then_fails(self):
        doc = compile_golden()
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "authenticate")


if __name__ == "__main__":
    unittest.main()
