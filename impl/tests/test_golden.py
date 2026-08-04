"""The golden scenario is machine-generated, not hand-maintained.

`examples/login.lir.json` must be exactly what the compiler emits from
`examples/login.lnpl`. This is what keeps the grammar, the IR, and the runtime
timeline from drifting apart as the RFCs change.

`examples/checkout.lir.json` is the second such pair (issue #35). Login is a
single-entity workflow, so it cannot exercise the case the issue reports: a
workflow that READS one entity and CREATES another. Checkout does, and it runs
green only under Wave 1's role-based seed rule — Product is read so it is
seeded, Order is only created so its table starts empty and `create order`
inserts instead of conflicting. `TestCheckoutExecution` asserts that *reason*,
not just the green, so a silent widening of the seed rule fails loudly here.

Both pairs run the same five assertions through `GoldenPairContract`. Neither
`.lir.json` is ever hand-edited: when one goes stale the fix is to regenerate it
with the command in the failure message.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from lnpl.interp import Interpreter, sample_payload
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows, row_key, seeded_entities
from tests.fixtures import CHECKOUT_LIR, CHECKOUT_LNPL

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "examples", "login.lnpl")
GOLDEN_IR = os.path.join(REPO, "examples", "login.lir.json")
VALIDATOR = os.path.join(REPO, "scripts", "validate_ir.py")

PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
           "email": "user@example.com",
           "password": "s3cret-value",
           "createdAt": "2026-07-31T09:00:00Z"}

CHECKOUT_WORKFLOW = "wf.checkout"


def compile_module(path):
    """Compile a committed source exactly as `lnpl compile` does.

    The module name comes from the file name, which is what `cli._compile`
    does — deriving it here keeps the compiled document identical to the one
    the CLI writes into the golden.
    """
    with open(path, encoding="utf-8") as fh:
        return lower(parse(fh.read()),
                     os.path.splitext(os.path.basename(path))[0]).to_document()


def compile_golden():
    return compile_module(SRC)


def compile_checkout():
    return compile_module(CHECKOUT_LNPL)


def checkout_payload(document):
    """The default fixture the CLI runs with: every field of every entity."""
    return sample_payload([n for n in document["nodes"] if n["kind"] == "Entity"])


class GoldenPairContract:
    """The assertions every committed <source, IR> pair must satisfy.

    A plain mixin, not a `TestCase`: unittest collects only `TestCase`
    subclasses, so these run once per concrete pair below and never on their
    own. Each concrete class supplies the pair's paths and the two id facts that
    are genuinely per-module.
    """

    SRC = None
    GOLDEN_IR = None
    FIRST_NODE_ID = None
    LAST_NODE_IDS = None
    REGEN_CMD = None

    @classmethod
    def compile_source(cls):
        return compile_module(cls.SRC)

    def test_source_compiles_to_the_committed_ir(self):
        with open(self.GOLDEN_IR, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(self.compile_source(), committed,
                         "%s is stale — regenerate it with `%s`"
                         % (os.path.relpath(self.GOLDEN_IR, REPO), self.REGEN_CMD))

    def test_node_ids_and_order_are_stable(self):
        ids = [n["id"] for n in self.compile_source()["nodes"]]
        self.assertEqual(ids[0], self.FIRST_NODE_ID)
        self.assertEqual(ids[-len(self.LAST_NODE_IDS):], self.LAST_NODE_IDS)
        self.assertEqual(len(ids), len(set(ids)))       # ids are unique

    def test_committed_ir_passes_the_schema_validator(self):
        proc = subprocess.run([sys.executable, VALIDATOR, self.GOLDEN_IR],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_every_reference_resolves(self):
        doc = self.compile_source()
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
        doc = self.compile_source()
        owners = {}
        for node in doc["nodes"]:
            for child in node.get("children", []):
                self.assertNotIn(child, owners,
                                 "%s is owned by both %s and %s"
                                 % (child, owners.get(child), node["id"]))
                owners[child] = node["id"]


class TestGoldenPair(GoldenPairContract, unittest.TestCase):
    SRC = SRC
    GOLDEN_IR = GOLDEN_IR
    FIRST_NODE_ID = "svc.login"
    LAST_NODE_IDS = ["cap.postgres", "cap.redis", "cap.jwt"]
    REGEN_CMD = "python3 -m lnpl compile examples/login.lnpl -o examples/login.lir.json"


class TestCheckoutGoldenPair(GoldenPairContract, unittest.TestCase):
    SRC = CHECKOUT_LNPL
    GOLDEN_IR = CHECKOUT_LIR
    FIRST_NODE_ID = "svc.checkout"
    LAST_NODE_IDS = ["cap.postgres", "cap.redis", "cap.jwt"]
    REGEN_CMD = ("python3 -m lnpl compile examples/checkout.lnpl "
                 "-o examples/checkout.lir.json")


class TestCheckoutShape(unittest.TestCase):
    """The structure the equivalence regression and mode B both quote."""

    def test_the_workflow_reads_product_and_creates_order(self):
        doc = compile_checkout()
        nodes = {n["id"]: n for n in doc["nodes"]}
        self.assertEqual(nodes["wf.checkout.step.2.repo"]["entity"], "entity.product")
        self.assertEqual(nodes["wf.checkout.step.2.repo"]["operation"], "read")
        self.assertEqual(nodes["wf.checkout.step.4.repo"]["entity"], "entity.order")
        self.assertEqual(nodes["wf.checkout.step.4.repo"]["operation"], "create")

    def test_the_guard_owns_only_the_create(self):
        # `when stock > 0` guards exactly one item, so nothing downstream of the
        # create can run when the guard is false.
        guard = {n["id"]: n for n in compile_checkout()["nodes"]}["wf.checkout.guard.1"]
        self.assertEqual(guard["mode"], "when")
        self.assertEqual(guard["condition"], "stock > 0")
        self.assertEqual(guard["children"], ["wf.checkout.step.4"])


class TestCheckoutExecution(unittest.TestCase):
    """Issue #35 completion criterion 1: read-then-create completes under the
    default seed — and completes *because of* the role-based rule, not by luck.
    """

    def test_the_default_seed_runs_read_then_create_to_completion(self):
        doc = compile_checkout()
        payload = checkout_payload(doc)
        interp = Interpreter(doc, repo_rows=default_rows(doc, CHECKOUT_WORKFLOW, payload))
        result = interp.run_workflow(CHECKOUT_WORKFLOW, payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["validate product", "find product",
                          "cache product", "create order"])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(interp.repo.calls,
                         [("entity.product", "read"), ("entity.order", "create")])

    def test_it_completes_because_only_the_entity_it_reads_is_seeded(self):
        # The reason, asserted. Seeding Order too would make `create order`
        # conflict on every run, which is the defect issue #35 reports; this
        # fails loudly if the seed rule ever widens back.
        doc = compile_checkout()
        payload = checkout_payload(doc)
        self.assertEqual(seeded_entities(doc, CHECKOUT_WORKFLOW), {"entity.product"})
        rows = default_rows(doc, CHECKOUT_WORKFLOW, payload)
        self.assertEqual(set(rows), {"entity.product"})
        self.assertEqual(list(rows["entity.product"]),
                         [row_key("entity.product", payload)])

    def test_stock_zero_skips_the_guarded_create(self):
        # Boundary of `when stock > 0`: 0 is the limit, and the Integer sample
        # 1 is one past it — the case above runs the true side.
        doc = compile_checkout()
        payload = dict(checkout_payload(doc))
        self.assertEqual(payload["stock"], 1, "the default payload must take the guard")
        payload["stock"] = 0
        interp = Interpreter(doc, repo_rows=default_rows(doc, CHECKOUT_WORKFLOW, payload))
        result = interp.run_workflow(CHECKOUT_WORKFLOW, payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["validate product", "find product", "cache product"])
        self.assertEqual(result["skipped"], ["wf.checkout.guard.1"])
        # the create never reached the repository
        self.assertEqual(interp.repo.calls, [("entity.product", "read")])

    def test_an_empty_repository_fails_the_read_after_retrying_it(self):
        # The error contract, not just "it failed": which step, which message,
        # and how many attempts the `retry 3` policy spent on it. The effects
        # map below is the mode A observation mode B has to reproduce — a read
        # is idempotent, so the retry emits one RepositoryCall span per attempt.
        doc = compile_checkout()
        payload = checkout_payload(doc)
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow(CHECKOUT_WORKFLOW, payload)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "find product")
        reasons = [e.get("reason") for e in interp.trace.logs
                   if e["message"] == "step failed"]
        self.assertEqual(reasons, ["repository read found no row for entity.product"])
        attempts = {s["step"]: s["attempts"] for s in result["steps"]}
        self.assertEqual(attempts, {"validate product": 1, "find product": 4})
        effects = {span.name: [child.kind for child in span.children]
                   for span in interp.trace.root.children}
        self.assertEqual(effects, {"validate product": ["Validation"],
                                   "find product": ["RepositoryCall"] * 4})
        self.assertEqual(interp.repo.calls, [("entity.product", "read")] * 4)


class TestCheckoutGoldenControls(unittest.TestCase):
    """A negative control per golden check, each mutating only what its own
    check owns — so a green run above states what it proved rather than only
    that it ran. This mirrors `scripts/validate_ir.py --self-test`, which pairs
    its one positive with three seeded faults.
    """

    def _tmpdir(self):
        # `.claude/tmp`, never /tmp: the repo writes temp dirs inside the
        # worktree, and the CLI already defaults its workdirs there.
        base = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(base, exist_ok=True)
        path = tempfile.mkdtemp(dir=base)
        self.addCleanup(shutil.rmtree, path, True)
        return path

    def _committed_ir(self):
        with open(CHECKOUT_LIR, encoding="utf-8") as fh:
            return json.load(fh)

    def test_a_drifted_golden_is_rejected_by_the_equality_check(self):
        # Control for test_source_compiles_to_the_committed_ir: rename one node
        # and the comparison must reject it. Without this, an equality between
        # two things that are equal by construction would look just as green.
        drifted = self._committed_ir()
        workflow = next(n for n in drifted["nodes"] if n["id"] == CHECKOUT_WORKFLOW)
        self.assertEqual(workflow["name"], "Checkout")
        workflow["name"] = "CheckoutDrifted"
        self.assertNotEqual(compile_checkout(), drifted)

    def test_an_ir_missing_a_required_field_is_rejected_by_the_validator(self):
        # Control for test_committed_ir_passes_the_schema_validator, dropping
        # the same required field the validator's own self-test drops.
        broken = self._committed_ir()
        workflow = next(n for n in broken["nodes"] if n["id"] == CHECKOUT_WORKFLOW)
        del workflow["name"]
        path = os.path.join(self._tmpdir(), "broken.lir.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(broken, fh)
        proc = subprocess.run([sys.executable, VALIDATOR, path],
                              capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0,
                            "the validator accepted a workflow with no name")
        report = proc.stdout + proc.stderr
        self.assertIn("INVALID", report)
        self.assertIn(CHECKOUT_WORKFLOW, report,
                      "the report must name the node it rejected")


class TestGoldenExecution(unittest.TestCase):
    def test_golden_runs_to_completion(self):
        doc = compile_golden()
        interp = Interpreter(doc, repo_rows={"entity.user": {row_key("entity.user", PAYLOAD): dict(PAYLOAD)}})
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["steps"]), 6)

    def test_timeline_matches_the_declared_six_steps(self):
        doc = compile_golden()
        interp = Interpreter(doc, repo_rows={"entity.user": {row_key("entity.user", PAYLOAD): dict(PAYLOAD)}})
        interp.run_workflow("wf.login", PAYLOAD)
        self.assertEqual([s.name for s in interp.trace.root.children],
                         ["validate input", "authenticate", "cache user",
                          "generate token", "audit login", "return token"])

    def test_golden_meets_its_own_response_slo(self):
        doc = compile_golden()
        interp = Interpreter(doc, repo_rows={"entity.user": {row_key("entity.user", PAYLOAD): dict(PAYLOAD)}})
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
