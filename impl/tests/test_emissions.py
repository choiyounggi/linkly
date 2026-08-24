"""Issue #102 — `run_workflow`'s `result["emissions"]` clause.

`spec.py`'s `emitted` assertion already reads `interp.outbox` directly,
unconditional of the run's final `status` (RFC-0003: the synchronous part of
`emit` ends at *registering* the publish, not at the workflow finishing). This
clause surfaces that same list on the JSON result, so a caller without spec
access sees what spec already sees — "fake 백엔드에서도 이벤트 관측 가능"
(D5). A workflow that never emits gets no `emissions` key at all — not an
empty list — so it is byte-identical to before this feature existed, the same
`respond`/`response` precedent issue #96 set (D4/D5 there).
"""

import contextlib
import io
import json
import os
import unittest

from lnpl import cli
from lnpl.interp import Interpreter
from lnpl.lower import lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUARDED_LNPL = os.path.join(REPO, "examples", "guarded.lnpl")

EMIT_SRC = """entity Order
    field
        id UUID
        status Text

event OrderPlaced on Order create

workflow PlaceOrder
    create order
    emit orderPlaced
"""

NO_EMIT_SRC = """entity Order
    field
        id UUID
        status Text

workflow PlaceOrder
    create order
"""

# A later step failing must not un-register an emit that already ran —
# RFC-0003's "registering the publish" happens synchronously at the `emit`
# step, before whatever runs after it. `cache order` with no `performance
# cache` TTL budget raises at run time (the same fixture shape
# test_respond_verb.py's own later-step-failure case uses).
EMIT_THEN_FAIL_SRC = """capability redis

entity Order
    field
        id UUID
        status Text

event OrderPlaced on Order create

workflow PlaceOrder
    create order
    emit orderPlaced
    cache order
"""


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


class TestEmissionsRuns(unittest.TestCase):

    def test_run_workflow_result_carries_an_emissions_clause(self):
        doc = compile_doc(EMIT_SRC)
        payload = {"id": "o-1", "status": "new"}

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.place.order", payload)

        self.assertEqual("completed", result["status"])
        self.assertEqual(1, len(result["emissions"]))
        emission = result["emissions"][0]
        self.assertEqual("event.order.placed", emission["event"])
        self.assertEqual(payload, emission["payload"])
        self.assertIn("emission_id", emission)

    def test_emissions_is_the_same_list_spec_emitted_already_reads(self):
        """No second bookkeeping mechanism — `result["emissions"]` and
        `spec.py`'s `emitted` assertion must agree because they read the
        same object, not two derivations that could drift."""
        doc = compile_doc(EMIT_SRC)
        payload = {"id": "o-1", "status": "new"}
        interp = Interpreter(doc, repo_rows={})

        result = interp.run_workflow("wf.place.order", payload)

        self.assertEqual(interp.outbox, result["emissions"])

    def test_a_workflow_that_never_emits_carries_no_emissions_key(self):
        doc = compile_doc(NO_EMIT_SRC)
        payload = {"id": "o-1", "status": "new"}

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.place.order", payload)

        self.assertEqual("completed", result["status"])
        self.assertNotIn("emissions", result)

    def test_existing_trace_keys_are_unchanged_alongside_emissions(self):
        doc = compile_doc(EMIT_SRC)
        payload = {"id": "o-1", "status": "new"}

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.place.order", payload)

        for key in ("status", "steps", "skipped", "failed_step",
                   "failure_reason", "bindings", "duration_ms",
                   "correlation_id"):
            self.assertIn(key, result)

    def test_an_emit_survives_a_later_steps_failure(self):
        doc = compile_doc(EMIT_THEN_FAIL_SRC)
        payload = {"id": "o-1", "status": "new"}

        result = Interpreter(doc, repo_rows={}).run_workflow(
            "wf.place.order", payload)

        self.assertEqual("failed", result["status"])
        self.assertEqual(1, len(result["emissions"]))


class TestEmissionsByteIdenticalWhenAbsent(unittest.TestCase):
    """D4/D5's non-destructive guarantee, over a real shipped file rather
    than a synthetic fixture: `examples/guarded.lnpl` declares no `emit` at
    all, so its `run --json` output must gain nothing new."""

    def run_cli_json(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(argv)
        return rc, json.loads(out.getvalue())

    def test_guarded_example_gets_no_emissions_key(self):
        rc, doc = self.run_cli_json(["run", GUARDED_LNPL, "--json"])

        self.assertEqual(0, rc)
        self.assertEqual("completed", doc["result"]["status"])
        self.assertNotIn("emissions", doc["result"])


class TestEmissionsCliJson(unittest.TestCase):
    """`lnpl run --json` carries the same `emissions` clause — sent
    verbatim, with zero change needed in cli.py (the same non-change
    `respond`'s own CLI test confirms for `response`, issue #96)."""

    def setUp(self):
        import tempfile
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-emissions-cli-", dir=os.path.join(REPO, ".claude", "tmp"))
        self.src_path = os.path.join(self.workdir, "emit.lnpl")
        with open(self.src_path, "w", encoding="utf-8") as fh:
            fh.write(EMIT_SRC)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_run_json_carries_the_emissions_clause(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli.main(["run", self.src_path, "--json"])
        self.assertEqual(0, rc)
        doc = json.loads(out.getvalue())
        self.assertEqual(1, len(doc["result"]["emissions"]))
        self.assertEqual("event.order.placed",
                         doc["result"]["emissions"][0]["event"])


if __name__ == "__main__":
    unittest.main()
