"""Default-fixture derivation (issue #23).

`run`/`diff` used to assume the golden login payload (`cli.DEFAULT_PAYLOAD`), so
any entity whose fields differ failed at the first `validate <field>` step. The
fixture must instead be synthesized from the target module's own entity fields.
"""

import os
import shutil
import unittest
from argparse import Namespace

from lnpl import backend, cli
from lnpl.interp import Interpreter, sample_payload, check_semantic_type
from lnpl.lower import lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HAS_TOOLS = backend.toolchain_available()

# A module that is NOT the login scenario — different entity, different fields.
SHORTEN = """
capability postgres
capability redis
entity Link
    field
        id UUID
        slug Text
        target Text
        createdAt DateTime
event LinkCreated on Link create
service ShortenService
    policy
        retry 3
        timeout 2s
    security
        jwt
    performance
        response < 40ms
        cache 10m
workflow Shorten
    validate target
    create link
    cache link
"""

# Every RFC-0001 semantic type, so a field of any declared type gets a value.
RFC0001_TYPES = ["UUID", "Money", "Email", "Phone", "Password", "Address",
                 "Image", "File", "Currency", "GeoLocation", "Json", "Html",
                 "Markdown", "Text", "Integer", "Decimal", "Boolean", "DateTime"]


def shorten_doc():
    return lower(parse(SHORTEN), "shorten").to_document()


def entities(doc):
    return [n for n in doc["nodes"] if n["kind"] == "Entity"]


class TestSamplePayload(unittest.TestCase):
    def test_covers_every_field_of_the_entity(self):
        payload = sample_payload(entities(shorten_doc()))
        self.assertEqual(set(payload), {"id", "slug", "target", "createdAt"})

    def test_samples_pass_their_own_semantic_type_validation(self):
        # A derived value must be a *valid* instance of its field's type, or the
        # fixture would fail the very validation it exists to satisfy.
        payload = sample_payload(entities(shorten_doc()))
        entity = entities(shorten_doc())[0]
        for field in entity["fields"]:
            check_semantic_type(field["type"], payload[field["name"]], field["name"])

    def test_every_rfc0001_type_has_a_sample(self):
        # No declared field of a valid type can be left out of the fixture.
        one_of_each = [{"kind": "Entity", "id": "entity.e", "name": "E",
                        "fields": [{"name": "f%d" % i, "type": t}
                                   for i, t in enumerate(RFC0001_TYPES)]}]
        payload = sample_payload(one_of_each)
        self.assertEqual(len(payload), len(RFC0001_TYPES))

    def test_no_entities_yields_empty_fixture(self):
        self.assertEqual(sample_payload([]), {})


class TestDerivedFixtureRunsNonLoginApi(unittest.TestCase):
    def test_shorten_workflow_completes_on_derived_fixture(self):
        doc = shorten_doc()
        payload = sample_payload(entities(doc))
        interp = Interpreter(doc, repo_rows={})   # empty repo: it is a create
        result = interp.run_workflow("wf.shorten", payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["validate target", "create link", "cache link"])


class TestCliDerivesFixture(unittest.TestCase):
    """`run`/`diff` with no --payload must derive the fixture from the module's
    entities, not fall back to the hardcoded login payload."""

    def setUp(self):
        self.dir = os.path.join(REPO, ".claude", "tmp", "fixture-cli-test")
        os.makedirs(self.dir, exist_ok=True)
        self.src = os.path.join(self.dir, "shorten.lnpl")
        with open(self.src, "w", encoding="utf-8") as fh:
            fh.write(SHORTEN)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _run_args(self, **over):
        base = dict(source=self.src, payload=None, workflow=None,
                    no_row=True, json=False)
        base.update(over)
        return Namespace(**base)

    def test_run_without_payload_completes_for_non_login_entity(self):
        self.assertEqual(cli.cmd_run(self._run_args()), 0)

    @unittest.skipUnless(HAS_TOOLS, "MLIR/LLVM toolchain not installed")
    def test_diff_without_payload_is_equivalent_for_non_login_entity(self):
        args = Namespace(source=self.src, workflow=None,
                         workdir=os.path.join(self.dir, "wd"),
                         payload=None, no_row=True)
        self.assertEqual(cli.cmd_diff(args), 0)


if __name__ == "__main__":
    unittest.main()
