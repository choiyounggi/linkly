"""issue #188 / RFC-0062 §Mode B: mode B refuses a `cached` read, and
`build`, `emit_mlir` and `diff` report the same first refusal."""

import os
import shutil
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.lower import lower
from lnpl.parser import parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
HEAD = """
capability postgres
capability redis
entity Product
    field
        id Text
        sku Text
        qty Integer
service Catalog
    performance
        cache 5m
workflow G
"""
WORKFLOW = "wf.g"
ROW = {"entity.product": {"entity.product#p1": {"id": "p1", "sku": "S1", "qty": 1}}}


def compile_doc(body):
    return lower(parse(HEAD + body), "m").to_document()


def workdir(test):
    base = os.path.join(REPO_ROOT, ".claude", "tmp")
    os.makedirs(base, exist_ok=True)
    path = tempfile.mkdtemp(prefix="lnpl-t188b-", dir=base)
    test.addCleanup(shutil.rmtree, path, True)
    return path


class TestModeBRefusesCachedReads(unittest.TestCase):

    def first_refusals(self, doc):
        out = {}
        for name, call in (
                ("build", lambda: backend.build(doc, WORKFLOW, workdir(self))),
                ("emit_mlir", lambda: backend.emit_mlir(doc, WORKFLOW)),
                ("diff", lambda: differential.verify(
                    doc, WORKFLOW, {"id": "p1", "sku": "S1"}, ROW,
                    workdir(self)))):
            with self.assertRaises((backend.BackendError,
                                    differential.DifferentialError)) as ctx:
                call()
            out[name] = str(ctx.exception)
        return out

    def test_a_cached_read_is_refused_naming_rfc_0062(self):
        got = self.first_refusals(compile_doc("    find product cached\n"))
        self.assertIn("step find product cached: entity.product is read with "
                      "`cached`, and mode B has no cache state to consult "
                      "(RFC-0062 §Mode B, recorded exemption)", got["build"])
        self.assertIn("RFC-0062 §Mode B", got["emit_mlir"])
        self.assertIn("reads with `cached` — mode B has no cache state to "
                      "consult (RFC-0062 §Mode B, recorded exemption); "
                      "differential comparison is not attempted", got["diff"])

    def test_the_refusal_comes_before_any_toolchain_lookup(self):
        real = backend.toolchain_available
        backend.toolchain_available = lambda: False
        self.addCleanup(setattr, backend, "toolchain_available", real)
        got = self.first_refusals(compile_doc("    find product cached\n"))
        for name, text in got.items():
            with self.subTest(command=name):
                self.assertIn("RFC-0062", text)
                self.assertNotIn("toolchain unavailable", text)

    def test_a_lookup_key_is_reported_before_the_cached_read(self):
        got = self.first_refusals(compile_doc("    find product by input.sku cached\n"))
        for name, text in got.items():
            with self.subTest(command=name):
                self.assertIn("RFC-0052", text)
                self.assertNotIn("RFC-0062", text)

    def test_an_otherwise_branch_is_reported_before_the_cached_read(self):
        got = self.first_refusals(compile_doc(
            "    find product cached\n    when product.qty > 0\n"
            "        note \"in\"\n    otherwise\n        note \"out\"\n"))
        for name, text in got.items():
            with self.subTest(command=name):
                self.assertIn("RFC-0060", text)
                self.assertNotIn("RFC-0062", text)

    def test_the_cached_read_is_reported_before_a_numeric_predicate(self):
        doc = compile_doc(
            "    find product cached\n    when product.qty is-numeric\n"
            "        note \"flagged\"\n")
        self.assertTrue(backend.workflow_uses_numeric_predicate(doc, WORKFLOW))
        got = self.first_refusals(doc)
        for name, text in got.items():
            with self.subTest(command=name):
                self.assertIn("RFC-0062", text)
                self.assertNotIn("RFC-0050", text)

    def test_a_plain_read_is_not_flagged(self):
        doc = compile_doc("    find product\n")
        self.assertFalse(backend.workflow_uses_cached_read(doc, WORKFLOW))
        self.assertTrue(backend.workflow_uses_cached_read(
            compile_doc("    find product cached\n"), WORKFLOW))

    def test_an_unknown_workflow_is_a_backend_error(self):
        doc = compile_doc("    find product cached\n")
        with self.assertRaises(backend.BackendError) as ctx:
            backend.workflow_uses_cached_read(doc, "wf.nope")
        self.assertIn("no such workflow: 'wf.nope'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
