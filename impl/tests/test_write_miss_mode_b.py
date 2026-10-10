"""Issue #215 / RFC-0064: mode A/B parity for an `update`/`delete` that affects 0 rows.

This module never skips, on purpose. The divergence (mode A failing a write miss
`not-found`, mode B still completing it) is catchable only by the mode A/B
comparison, so a missing toolchain fails loudly in
`TestWriteMissModeBToolchainIsRequired` instead of skipping -- the same stance as
`test_repo_state.py`.
"""

import os
import shutil
import tempfile
import unittest

from lnpl import backend, cli
from lnpl.differential import observe_mode_a, observe_mode_b, verify
from lnpl.interp import sample_payload
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BARE = """
capability postgres
entity Stock
    field
        id UUID
        quantity Integer
service StockService
workflow Restock
    update stock
workflow Remove
    delete stock
workflow Audit
    find stock
    update stock
"""
BARE_RETRY = BARE.replace("service StockService\n",
                          "service StockService\n    policy\n        retry 2\n")
WRITE_RETRY_TMPL = """
capability postgres
entity Product
    field
        id UUID
        stock Integer
service CheckoutService
%(policy)s
workflow Checkout
%(lead)s    %(op)s product
"""
# Same cell test_backend excludes: the deadline is spent before the call.
DEADLINE_STARVED = {("100ms", 20)}


def compile_doc(src):
    return lower(parse(src), "stock").to_document()


def payload_for(doc):
    return sample_payload(cli._entities(doc))


def write_retry_doc(op, retry, timeout, lead):
    rules = []
    if retry is not None:
        rules.append("        retry %d" % retry)
    if timeout is not None:
        rules.append("        timeout %s" % timeout)
    policy = "    policy\n" + "\n".join(rules) + "\n" if rules else ""
    src = WRITE_RETRY_TMPL % {
        "policy": policy, "op": op,
        "lead": "".join("    validate product\n" for _ in range(lead))}
    return lower(parse(src), "checkout").to_document()


def tmp_workdir(test):
    base = os.path.join(REPO, ".claude", "tmp")
    os.makedirs(base, exist_ok=True)
    path = tempfile.mkdtemp(prefix="lnpl-t215-", dir=base)
    test.addCleanup(shutil.rmtree, path, True)
    return path


class TestWriteMissModeBToolchainIsRequired(unittest.TestCase):
    def test_the_mode_b_toolchain_is_present_because_issue_215_needs_it(self):
        self.assertTrue(
            backend.toolchain_available(),
            "issue #215 regression cannot run: the MLIR/LLVM toolchain is "
            "missing, so mode B cannot be built and `lnpl diff` cannot be "
            "compared. This module deliberately does NOT skip -- the write-miss "
            "divergence is catchable ONLY by the mode A/B comparison.\n"
            "Fix:\n"
            "  brew install llvm\n"
            "  export PATH=\"/opt/homebrew/opt/llvm/bin:$PATH\"\n"
            "  SDK=\"$(xcrun --show-sdk-path)\"\n"
            "  export CPATH=\"$SDK/usr/include\" LIBRARY_PATH=\"$SDK/usr/lib\"")


class TestPredictorMatchesModeAOnWriteMisses(unittest.TestCase):
    """Pure Python, no toolchain."""

    def test_derived_attempts_match_mode_a_for_a_failing_update_and_delete(self):
        compared = 0
        for op in ("update", "delete"):
            for retry in (None, 0, 1, 3, 5):
                for timeout in (None, "3s", "1s", "500ms", "100ms"):
                    for lead in (0, 2, 20):
                        if (timeout, lead) in DEADLINE_STARVED:
                            continue
                        with self.subTest(op=op, retry=retry, timeout=timeout,
                                          lead=lead):
                            d = write_retry_doc(op, retry, timeout, lead)
                            derived = len(backend._lnpl_ops(
                                d, "wf.checkout", seeded=frozenset())[1][-1]["effects"])
                            payload = sample_payload(
                                [n for n in d["nodes"] if n["kind"] == "Entity"])
                            observed = len(observe_mode_a(
                                d, "wf.checkout", payload, {})["effects"]["%s product" % op])
                            self.assertEqual(derived, observed)
                        compared += 1
        self.assertEqual(compared, 2 * (5 * 5 * 3 - len(DEADLINE_STARVED) * 5))

    def test_a_seeded_entity_is_not_predicted_to_miss(self):
        doc = compile_doc(BARE)
        attrs, _ops = backend._lnpl_ops(doc, "wf.restock",
                                        seeded=frozenset({"entity.stock"}))
        self.assertNotIn("lnpl.terminal_status", attrs)
        attrs, _ops = backend._lnpl_ops(doc, "wf.restock", seeded=frozenset())
        self.assertEqual(attrs["lnpl.terminal_status"], "failed")


class TestWriteMissDiffIsEquivalent(unittest.TestCase):
    """Needs the toolchain; a missing one fails the class above, never skips."""

    def setUp(self):
        self.doc = compile_doc(BARE)
        self.payload = payload_for(self.doc)
        self.workdir = tmp_workdir(self)

    def test_no_row_update_and_delete_fail_the_same_way_in_both_modes(self):
        for wf in ("wf.restock", "wf.remove"):
            with self.subTest(workflow=wf):
                ok, report = verify(self.doc, wf, self.payload, {},
                                    self.workdir, seeded=frozenset())
                self.assertTrue(ok, "\n".join(report))
                a = observe_mode_a(self.doc, wf, self.payload, {})
                b = observe_mode_b(self.doc, wf, self.workdir,
                                   payload=self.payload, seeded=frozenset())
                self.assertEqual(a["status"], "failed")
                self.assertEqual(b["status"], "failed")
                self.assertEqual(a["order"], b["order"])

    def test_default_seed_update_first_fails_the_same_way(self):
        rows = default_rows(self.doc, "wf.restock", self.payload)
        self.assertEqual(rows, {})
        ok, report = verify(self.doc, "wf.restock", self.payload, rows,
                            self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertEqual(
            observe_mode_a(self.doc, "wf.restock", self.payload, rows)["status"],
            "failed")

    def test_a_read_backed_update_still_completes_in_both_modes(self):
        rows = default_rows(self.doc, "wf.audit", self.payload)
        ok, report = verify(self.doc, "wf.audit", self.payload, rows,
                            self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertEqual(
            observe_mode_a(self.doc, "wf.audit", self.payload, rows)["status"],
            "completed")

    def test_a_retried_write_miss_repeats_its_span_in_both_modes(self):
        doc = compile_doc(BARE_RETRY)
        payload = payload_for(doc)
        ok, report = verify(doc, "wf.restock", payload, {}, self.workdir,
                            seeded=frozenset())
        self.assertTrue(ok, "\n".join(report))
        b = observe_mode_b(doc, "wf.restock", self.workdir, payload=payload,
                           seeded=frozenset())
        self.assertEqual(b["effects"]["update stock"], ["RepositoryCall"] * 3)

    def test_mode_b_without_the_write_miss_rule_is_caught(self):
        saved = backend._WRITE_MISS_OPS
        backend._WRITE_MISS_OPS = ()
        self.addCleanup(setattr, backend, "_WRITE_MISS_OPS", saved)
        ok, _report = verify(self.doc, "wf.restock", self.payload, {},
                             self.workdir, seeded=frozenset())
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
