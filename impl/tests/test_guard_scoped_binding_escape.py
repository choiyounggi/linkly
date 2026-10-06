"""`guard-scoped-binding-escape` — a binding made under a guard, read outside it
(issue #198).

`create ... as <name>` / `call ... as <name>` / `request ... as <name>` binds
`<name>` only on a run where the guard that owns the step held. RFC-0002 gives
a guard exactly one item, so the step right after it is unguarded:

    when product.stock >= input.quantity
    create order as o
    respond o.id

On a run where the guard is false `o` was never bound, and `respond o.id` (or
a `set`, a `format`, an `emit ... with`) reads a name that does not exist.
The runtime no longer crashes on it (see `test_respond_verb.py`), but the
program is still wrong, and the compiler can see that from the tree alone —
the same guard-scope judgement RFC-0023 makes for state and issue #98 makes
for event sources, applied to RFC-0027 result bindings.

The two remedies are the ones `references/grammar.md` already prescribes:
repeat the guard line before the reader, or put creator and reader in one
block under the guard. A binding that is also created with no guard at all is
always bound, so it is never reported.
"""
import contextlib
import glob
import io
import os
import shutil
import tempfile
import unittest

from lnpl import cli
from lnpl.diagnostics import CODES, SEVERITY_OF
from lnpl.lower import ORPHAN_HINT, lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP_ROOT = os.path.join(REPO, ".claude", "tmp")

CODE = "guard-scoped-binding-escape"

# Everything above the workflow's own steps: `find product` is HEAD's last
# line, so the first step passed to `source()` sits on the line after it.
HEAD = """capability http PaymentGateway
    method get

entity Product
    field
        id UUID
        stock Integer
        label Text

entity Order
    field
        id UUID
        quantity Integer

event OrderCreated

service ShopService

workflow PlaceOrder
    find product
"""
FIRST_BODY_LINE = len(HEAD.splitlines()) + 1

GUARD = "when product.stock >= input.quantity"
OTHER_GUARD = "when input.quantity > 0"


def source(*steps):
    return HEAD + "".join("    %s\n" % step for step in steps)


# The issue's own reproduction, verbatim.
ISSUE_REPRO = """entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

service ShopService

workflow PlaceOrder
    find product
    when product.stock >= input.quantity
    create order as o
    respond o.id
"""
ISSUE_RESPOND_LINE = 17


def diagnose(text, name="probe"):
    """`text`'s diagnostics for CODE — the compiler decides, not the test."""
    module = lower(parse(text), name)
    return list(module.diagnostics.by_code(CODE))


def run_cli_split(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class TheCodeIsRegistered(unittest.TestCase):

    def test_the_code_exists_and_is_a_warning(self):
        self.assertIn(CODE, CODES)
        self.assertEqual("warning", SEVERITY_OF[CODE])


class TestTheIssueReproduction(unittest.TestCase):

    def setUp(self):
        self.found = diagnose(ISSUE_REPRO)

    def test_it_fires_exactly_once(self):
        self.assertEqual(1, len(self.found))

    def test_it_points_at_the_respond_line(self):
        d = self.found[0]
        self.assertEqual(ISSUE_RESPOND_LINE, d.line)
        self.assertEqual("line %d" % ISSUE_RESPOND_LINE, d.where)
        self.assertEqual("o", d.subject)

    def test_the_message_names_the_reader_and_both_remedies(self):
        message = self.found[0].message
        self.assertIn("`respond o.id`", message)
        self.assertIn(ORPHAN_HINT, message)
        self.assertIn("Repeat the guard line", message)
        self.assertIn("`parallel`", message)

    def test_the_record_carries_the_registered_hint(self):
        self.assertEqual(ORPHAN_HINT, self.found[0].hint)


class TestEveryReaderKindFires(unittest.TestCase):
    """One assertion per emitting path: each reader is named by its OWN
    construct, never by another reader's verb."""

    def _one(self, *steps):
        found = diagnose(source(GUARD, *steps))
        self.assertEqual(1, len(found), [d.message for d in found])
        self.assertEqual(FIRST_BODY_LINE + 2, found[0].line)
        return found[0]

    def test_set_reading_a_create_binding(self):
        d = self._one("create order as o",
                      "set product.stock to o.quantity")
        self.assertEqual("o", d.subject)
        self.assertIn("the assignment to `product.stock`", d.message)
        self.assertNotIn("respond", d.message)

    def test_format_reading_a_create_binding(self):
        d = self._one("create order as o",
                      'format product.label from "{}" with o.id')
        self.assertEqual("o", d.subject)
        self.assertIn("the assignment to `product.label`", d.message)
        self.assertNotIn("respond", d.message)

    def test_emit_with_reading_a_create_binding(self):
        d = self._one("create order as o", "emit orderCreated with o.id")
        self.assertEqual("o", d.subject)
        self.assertIn("`emit orderCreated ... with`", d.message)
        self.assertNotIn("respond", d.message)

    def test_call_send_reading_a_create_binding(self):
        d = self._one("create order as o", "call PaymentGateway send o.id")
        self.assertEqual("o", d.subject)
        self.assertIn("`call PaymentGateway ... send`", d.message)
        self.assertNotIn("respond", d.message)

    def test_request_send_is_named_by_its_own_verb(self):
        d = self._one("create order as o", "request PaymentGateway send o.id")
        self.assertIn("`request PaymentGateway ... send`", d.message)

    def test_publish_with_is_named_by_its_own_verb(self):
        d = self._one("create order as o", "publish orderCreated with o.id")
        self.assertIn("`publish orderCreated ... with`", d.message)
        self.assertNotIn("emit", d.message)

    def test_set_reading_a_call_binding(self):
        d = self._one("call PaymentGateway as p",
                      "set product.stock to p.amount")
        self.assertEqual("p", d.subject)
        self.assertIn("the assignment to `product.stock`", d.message)

    def test_emit_with_reading_a_request_binding(self):
        d = self._one("request PaymentGateway as p",
                      "emit orderCreated with p.amount")
        self.assertEqual("p", d.subject)
        self.assertIn("`emit orderCreated ... with`", d.message)


class TestScopeComparison(unittest.TestCase):

    def test_a_reader_under_an_unrelated_guard_still_fires(self):
        # "Is guarded" is not "is guarded by the creator's guard".
        found = diagnose(source(GUARD, "create order as o",
                                OTHER_GUARD, "respond o.id"))
        self.assertEqual(["o"], [d.subject for d in found])
        self.assertEqual(FIRST_BODY_LINE + 3, found[0].line)

    def test_two_refs_to_one_binding_are_reported_once(self):
        found = diagnose(source(GUARD, "create order as o",
                                "respond o.id o.quantity"))
        self.assertEqual(1, len(found))
        self.assertIn("`respond o.id o.quantity`", found[0].message)

    def test_each_escaping_binding_is_reported(self):
        found = diagnose(source(GUARD, "create order as o",
                                OTHER_GUARD, "call PaymentGateway as p",
                                "emit orderCreated with o.id p.amount"))
        self.assertEqual(["o", "p"], [d.subject for d in found])

    def test_each_escaping_reader_is_reported(self):
        found = diagnose(source(GUARD, "create order as o",
                                "emit orderCreated with o.id",
                                "respond o.id"))
        self.assertEqual([FIRST_BODY_LINE + 2, FIRST_BODY_LINE + 3],
                         [d.line for d in found])


class TestReadersInsideTheScopeStaySilent(unittest.TestCase):

    def test_repeating_the_guard_line_silences_it(self):
        self.assertEqual([], diagnose(source(
            GUARD, "create order as o", GUARD, "respond o.id")))

    def test_the_repeated_guard_fix_applied_to_the_issue_repro(self):
        fixed = ISSUE_REPRO.replace(
            "    respond o.id\n",
            "    when product.stock >= input.quantity\n    respond o.id\n")
        self.assertNotEqual(ISSUE_REPRO, fixed)
        self.assertEqual([], diagnose(fixed))

    def test_one_parallel_block_under_the_guard_silences_it(self):
        self.assertEqual([], diagnose(source(
            GUARD, "parallel", "create order as o", "respond o.id", "merge")))

    def test_one_pipeline_block_under_the_guard_silences_it(self):
        self.assertEqual([], diagnose(source(
            GUARD, "pipeline", "create order as o", "respond o.id")))

    def test_every_reader_kind_is_silent_under_the_repeated_guard(self):
        for creator, reader in (
                ("create order as o", "set product.stock to o.quantity"),
                ("create order as o",
                 'format product.label from "{}" with o.id'),
                ("create order as o", "emit orderCreated with o.id"),
                ("call PaymentGateway as p", "set product.stock to p.amount"),
                ("create order as o", "call PaymentGateway send o.id")):
            with self.subTest(reader=reader):
                self.assertEqual([], diagnose(source(
                    GUARD, creator, GUARD, reader)))


class TestUnconditionalBindingsStaySilent(unittest.TestCase):

    def test_no_guard_anywhere(self):
        self.assertEqual([], diagnose(source(
            "create order as o", "respond o.id")))

    def test_an_unguarded_binding_read_under_a_guard(self):
        self.assertEqual([], diagnose(source(
            "create order as o", GUARD, "respond o.id")))

    def test_a_workflow_with_a_guard_but_no_result_binding(self):
        self.assertEqual([], diagnose(source(
            GUARD, "create order", "emit orderCreated")))

    def test_a_reader_that_names_no_guard_scoped_binding(self):
        self.assertEqual([], diagnose(source(
            GUARD, "create order as o",
            "set product.stock to product.stock - input.quantity")))


class TestStrictWarningGate(unittest.TestCase):

    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        self.tmpdir = tempfile.mkdtemp(dir=TMP_ROOT)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)
        self.repro = os.path.join(self.tmpdir, "t198_repro.lnpl")
        with open(self.repro, "w", encoding="utf-8") as fh:
            fh.write(ISSUE_REPRO)

    def test_the_repro_compiles_rc_0_and_prints_the_warning_and_hint(self):
        rc, _, err = run_cli_split(["compile", self.repro])
        self.assertEqual(0, rc, err)
        self.assertIn(CODE, err)
        self.assertIn("line %d" % ISSUE_RESPOND_LINE, err)
        self.assertIn("Repeat the guard line", err)

    def test_strict_warning_turns_it_into_rc_2(self):
        rc, _, err = run_cli_split(["compile", self.repro, "--strict=warning"])
        self.assertEqual(2, rc)
        self.assertIn(CODE, err)

    def test_strict_error_does_not_gate_a_warning(self):
        rc, _, err = run_cli_split(["compile", self.repro, "--strict=error"])
        self.assertEqual(0, rc, err)


class ShippedExamplesStaySilent(unittest.TestCase):

    def test_no_shipped_example_reports_the_code(self):
        paths = sorted(glob.glob(os.path.join(REPO, "examples", "*.lnpl")))
        self.assertGreaterEqual(len(paths), 4, "예제를 하나도 못 찾으면 공허하다")
        for path in paths:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            with self.subTest(path=path):
                self.assertEqual([], diagnose(text, os.path.basename(path)))


if __name__ == "__main__":
    unittest.main()
