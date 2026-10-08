"""Issue #216: a bare `expect result <name>` reads the input field (RFC-0012
§G12.1/G12.3), and `spec` fills every input a case did not give with a type
sample, so a name shared with a `respond` field compares against the sample.
`spec-result-reads-input` (warning) reports that collision at compile time.
"""
import contextlib
import io
import os
import shutil
import tempfile
import unittest

from lnpl import cli
from lnpl.diagnostics import SEVERITY_OF
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.spec import extract, run_manifest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP_ROOT = os.path.join(REPO, ".claude", "tmp")
CODE = "spec-result-reads-input"
READ = ("read item", "respond item.quantity")
TERM = ("list item where quantity > 0 limit 10", "read item",
        "respond item.quantity quantity as sum item.quantity")


def source(steps=READ, given=("stored item quantity 7",),
           expects=("result quantity == 1",), extra_blocks=()):
    lines = ["entity Item", "    field", "        id UUID",
             "        quantity Integer", "", "service ItemService", "",
             "workflow CheckItem"]
    lines += ["    " + s for s in steps]
    for g, e in ((given, expects),) + tuple(extra_blocks):
        lines += ["    spec", "        given"]
        lines += ["            " + x for x in g]
        lines += ["        when", "            checkitem", "        expect",
                  "            completed"]
        lines += ["            " + x for x in e]
    return "\n".join(lines) + "\n"


def records(src):
    return lower(parse(src), "m").diagnostics.by_code(CODE)


def run_spec(src):
    decls = parse(src)
    return run_manifest(extract(decls, "m"), lower(decls, "m").to_document())


class CliCase(unittest.TestCase):
    def cli(self, src, argv):
        os.makedirs(TMP_ROOT, exist_ok=True)
        d = tempfile.mkdtemp(dir=TMP_ROOT)
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        path = os.path.join(d, "check.lnpl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(src)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main([argv[0], path] + argv[1:])
        return rc, out.getvalue(), err.getvalue()


class TestRecord(unittest.TestCase):
    def test_issue_module_reports_one_warning(self):
        recs = records(source())
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r.code, CODE)
        self.assertEqual(r.severity, "warning")
        self.assertEqual(r.where, "line 18")
        self.assertEqual(r.line, 18)
        self.assertEqual(r.subject, "quantity")
        self.assertEqual(
            r.message,
            "result quantity reads the input field, not the response — "
            "write result item.quantity")

    def test_code_is_graded_warning(self):
        self.assertEqual(SEVERITY_OF[CODE], "warning")


class TestStrict(CliCase):
    def test_spec_run_strict_warning_exits_2(self):
        rc, _out, err = self.cli(source(), ["spec", "--run", "--strict=warning"])
        self.assertEqual(rc, 2)
        self.assertIn(CODE, err)

    def test_spec_run_without_strict_exits_0_and_still_passes(self):
        rc, out, err = self.cli(source(), ["spec", "--run"])
        self.assertEqual(rc, 0)
        self.assertIn(CODE, err)
        self.assertIn("spec: 2 passed, 0 failed", out)

    def test_failing_spec_keeps_rc_1_under_strict(self):
        rc, _out, _err = self.cli(source(expects=("result quantity == 7",)),
                                  ["spec", "--run", "--strict=warning"])
        self.assertEqual(rc, 1)

    def test_compile_strict_warning_exits_2(self):
        rc, _out, _err = self.cli(source(), ["compile", "--strict=warning"])
        self.assertEqual(rc, 2)


class TestSilent(unittest.TestCase):
    def test_given_bare_field_sets_the_input(self):
        src = source(given=("quantity 7", "stored item quantity 7"),
                     expects=("result quantity == 7",))
        self.assertEqual(len(records(src)), 0)

    def test_given_input_field_sets_the_input(self):
        src = source(given=("input.quantity 7", "stored item quantity 7"),
                     expects=("result quantity == 7",))
        self.assertEqual(len(records(src)), 0)

    def test_qualified_name_is_the_repair(self):
        src = source(expects=("result item.quantity == 7",))
        self.assertEqual(len(records(src)), 0)
        passed, failed, _lines = run_spec(src)
        self.assertEqual((passed, failed), (2, 0))

    def test_input_namespace_is_qualified(self):
        src = source(expects=("result input.quantity == 1",))
        self.assertEqual(len(records(src)), 0)

    def test_same_name_term_wins(self):
        src = source(steps=TERM, expects=("result quantity == 7",))
        self.assertEqual(len(records(src)), 0)
        passed, failed, _lines = run_spec(src)
        self.assertEqual((passed, failed), (2, 0))

    def test_respond_of_another_field(self):
        src = source(steps=("read item", "respond item.id"))
        self.assertEqual(len(records(src)), 0)

    def test_no_respond_step(self):
        self.assertEqual(len(records(source(steps=("read item",)))), 0)

    def test_no_result_expectation(self):
        self.assertEqual(len(records(source(expects=()))), 0)


class TestBlocks(unittest.TestCase):
    def test_no_input_given_still_warns(self):
        src = source(given=("no quantity", "stored item quantity 7"),
                     expects=("result quantity missing",))
        self.assertEqual(len(records(src)), 1)

    def test_each_block_judged_by_its_own_given(self):
        src = source(given=("quantity 7", "stored item quantity 7"),
                     expects=("result quantity == 7",),
                     extra_blocks=((("stored item quantity 7",),
                                    ("result quantity == 1",)),))
        recs = records(src)
        self.assertEqual(len(recs), 1)
        last = [i for i, l in enumerate(src.splitlines(), 1)
                if l.strip() == "result quantity == 1"][-1]
        self.assertEqual(recs[0].line, last)


if __name__ == "__main__":
    unittest.main()
