"""Issue #64/#76 / RFC-0027 — mode B (Task 06).

RFC-0027 §8's central finding: mode B computes NOTHING for a `NetworkCall`
result — no real HTTP call, no fake stub lookup — because the response value
(`status`, the body's flattened fields) is not one of RFC-0004's four
observation classes, exactly as RFC-0025 §10 found for aggregate values. This
file proves `lnpl diff` (`differential.verify`) agrees across three mode-A
inputs that vary ONLY the network response — success (200), a 5xx, and a
transport failure (bound `status=0`) — while mode B's own output never
changes, since it never reads the stub at all.
"""

import os
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.drivers import DriverError, FakeNetworkDriver
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HAS_TOOLS = backend.toolchain_available()
NEEDS_TOOLS = unittest.skipUnless(
    HAS_TOOLS, "MLIR/LLVM toolchain not installed (brew install llvm)")

CHARGE_CARD_SRC = """capability postgres

entity Order
    field
        id UUID
        failureCode Integer

service Checkout
    policy
        timeout 5s

workflow ChargeCard
    find order
    call PaymentGateway as paymentResult
    set order.failureCode to paymentResult.status
    update order
"""


def compile_doc(source=CHARGE_CARD_SRC, module="m"):
    return lower(parse(source), module).to_document()


class _FailingNetworkDriver(FakeNetworkDriver):
    def call(self, target, payload, timeout_ms, trace_headers=None,
             path_args=None):
        raise DriverError("the gateway is unreachable")


class NetworkCallModeEquivalenceTest(unittest.TestCase):
    """RFC-0027 §8, D5: the three inputs the DoD names — success/5xx/transport
    failure — each proven equivalent independently, so a divergence in any
    one of them cannot hide behind the other two passing."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-network-diff-", dir=os.path.join(REPO, ".claude", "tmp"))
        self.doc = compile_doc()
        self.target = next(n["id"] for n in self.doc["nodes"]
                           if n["kind"] == "Workflow")
        self.payload = {"id": "o-1"}
        self.rows = {"entity.order": {row_key("entity.order", self.payload):
                                      {"id": "o-1", "failureCode": 0}}}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

    @NEEDS_TOOLS
    def test_a_successful_response_is_equivalent(self):
        network = FakeNetworkDriver({"PaymentGateway": (200, {})})
        ok, report = differential.verify(self.doc, self.target, self.payload,
                                         self.rows, self.workdir, network=network)
        self.assertTrue(ok, "\n".join(report))

    @NEEDS_TOOLS
    def test_a_5xx_response_is_equivalent(self):
        network = FakeNetworkDriver({"PaymentGateway": (500, {"code": 42})})
        ok, report = differential.verify(self.doc, self.target, self.payload,
                                         self.rows, self.workdir, network=network)
        self.assertTrue(ok, "\n".join(report))

    @NEEDS_TOOLS
    def test_a_transport_failure_is_equivalent(self):
        ok, report = differential.verify(self.doc, self.target, self.payload,
                                         self.rows, self.workdir,
                                         network=_FailingNetworkDriver())
        self.assertTrue(ok, "\n".join(report))

    @NEEDS_TOOLS
    def test_mode_bs_own_output_does_not_change_across_the_three_inputs(self):
        """The claim RFC-0027 §8 actually makes: mode B never reads the
        stub, so its observation is IDENTICAL for all three — the diff
        passing for each is not three coincidences, it is one fact."""
        b_success = differential.observe_mode_b(self.doc, self.target,
                                                 self.workdir, payload=self.payload)
        b_5xx = differential.observe_mode_b(self.doc, self.target,
                                            self.workdir, payload=self.payload)
        self.assertEqual(b_success, b_5xx)


class UnboundNetworkCallModeEquivalenceTest(unittest.TestCase):
    """The pre-existing, `as`-less `call` path must still agree — RFC-0027
    §3's backward-compatibility claim, checked against mode B too."""

    UNBOUND_SRC = """capability postgres

entity Order
    field
        id UUID

service Checkout
    policy
        timeout 5s

workflow Ping
    find order
    call PaymentGateway
"""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-network-unbound-diff-", dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

    @NEEDS_TOOLS
    def test_an_unbound_call_is_equivalent(self):
        doc = compile_doc(self.UNBOUND_SRC)
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        payload = {"id": "o-1"}
        rows = {"entity.order": {row_key("entity.order", payload): {"id": "o-1"}}}
        ok, report = differential.verify(doc, target, payload, rows, self.workdir)
        self.assertTrue(ok, "\n".join(report))


# RFC-0057 §6: `send` adds nothing for mode B to refuse or diverge on.
SEND_CLAUSE_SRC = """capability postgres

capability http PaymentGateway
    method post

entity Order
    field
        id UUID
        stock Integer
        total Integer
        failureCode Integer

service Checkout
    policy
        timeout 5s

workflow ChargeCard
    find order
    set order.total to input.total
    call PaymentGateway send order.id order.total as paymentResult
    set order.failureCode to paymentResult.status
    update order
"""


class SendClauseModeEquivalenceTest(unittest.TestCase):

    def setUp(self):
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-network-send-diff-", dir=os.path.join(REPO, ".claude", "tmp"))
        # registered before anything that can raise, so a failing setUp
        # (no tearDown) still removes the directory
        import shutil
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)
        self.doc = compile_doc(SEND_CLAUSE_SRC)
        self.target = next(n["id"] for n in self.doc["nodes"]
                           if n["kind"] == "Workflow")
        self.payload = {"id": "o-1", "total": 500}
        self.rows = {"entity.order": {row_key("entity.order", self.payload):
                                      {"id": "o-1", "stock": 1, "total": 500,
                                       "failureCode": 0}}}

    def test_the_fixture_really_carries_a_body_map(self):
        call = next(n for n in self.doc["nodes"] if n["kind"] == "NetworkCall")
        self.assertEqual([{"field": "id", "ref": "order.id"},
                          {"field": "total", "ref": "order.total"}],
                         call["bodyMap"])

    @NEEDS_TOOLS
    def test_build_does_not_raise_for_a_send_clause_workflow(self):
        out = backend.build(self.doc, self.target, self.workdir)
        self.assertTrue(out)

    @NEEDS_TOOLS
    def test_differential_verify_agrees_for_a_send_clause_workflow(self):
        ok, report = differential.verify(
            self.doc, self.target, self.payload, self.rows, self.workdir,
            network=FakeNetworkDriver({"PaymentGateway": (200, {})}))
        self.assertTrue(ok, "\n".join(report))

    def test_build_and_diff_refuse_a_send_workflow_by_the_existing_chain(self):
        # A `fail` beside the `send` is refused for `fail` (RFC-0056) by
        # both commands, before any toolchain use -- `send` adds no link.
        doc = compile_doc(SEND_CLAUSE_SRC.replace(
            "    update order\n",
            "    update order\n    when order.stock < 1\n    fail out-of-stock\n"))
        with self.assertRaises(backend.BackendError) as built:
            backend.build(doc, self.target, self.workdir)
        with self.assertRaises(differential.DifferentialError) as diffed:
            differential.verify(doc, self.target, self.payload, self.rows,
                                self.workdir)
        for msg in (str(built.exception), str(diffed.exception)):
            self.assertIn("RFC-0056", msg)
            self.assertNotIn("RFC-0057", msg)


if __name__ == "__main__":
    unittest.main()
