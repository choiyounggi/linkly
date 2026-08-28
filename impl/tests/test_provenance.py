"""`.lir.json` provenance — issue #136.

`to_document()` used to say only what schema generation it emitted
(`lir_version`), never what vocabulary/enforcement generation it was compiled
against. SLSA build provenance's minimal lesson applies: the artifact should
say what made it. These tests pin the four keys `to_document()` now attaches,
their determinism (no timestamps, no environment-only reason to differ across
two compiles of the same source), and `lnpl.provenance.check()`'s report-only
contract for both current and provenance-less (legacy) documents.
"""

import copy
import hashlib
import json
import os
import unittest
from unittest import mock

from lnpl import capabilities, provenance, vocab
from lnpl.diagnostics import ENFORCEMENT
from lnpl.lower import lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGIN_SRC = os.path.join(REPO, "examples", "login.lnpl")

SLOT_NAMES = tuple(slot for slot, _group, _builtin, _fn in capabilities.SLOTS)


def compile_login():
    with open(LOGIN_SRC, encoding="utf-8") as fh:
        return lower(parse(fh.read()), "login").to_document()


class ProvenanceBlockTests(unittest.TestCase):
    """Normal path: a real compile carries a well-formed, deterministic block."""

    def test_document_carries_all_four_provenance_keys(self):
        block = compile_login()["provenance"]
        self.assertEqual(set(block), {"compiler", "vocabulary_digest",
                                       "enforcement_digest", "extensions"})

    def test_digests_use_the_sha256_prefix_format(self):
        block = compile_login()["provenance"]
        for key in ("vocabulary_digest", "enforcement_digest"):
            digest = block[key]
            self.assertTrue(digest.startswith("sha256:"), (key, digest))
            hex_part = digest[len("sha256:"):]
            self.assertEqual(len(hex_part), 64, (key, digest))
            int(hex_part, 16)  # raises ValueError if not hex

    def test_compiler_field_is_the_lnpl_version_string(self):
        from lnpl import __version__
        self.assertEqual(compile_login()["provenance"]["compiler"], __version__)

    def test_no_timestamp_anywhere_in_the_block(self):
        block = compile_login()["provenance"]
        encoded = json.dumps(block)
        # A cheap but effective net: ISO-ish date/time substrings would show up
        # verbatim in the serialized block if anyone slipped one in.
        self.assertNotIn("T00:", encoded)
        self.assertNotRegex(encoded, r"\d{4}-\d{2}-\d{2}")

    def test_two_compiles_of_the_same_source_are_byte_identical(self):
        first = json.dumps(compile_login(), sort_keys=True)
        second = json.dumps(compile_login(), sort_keys=True)
        self.assertEqual(first, second)

    def test_extensions_has_every_contract_slot_present(self):
        extensions = compile_login()["provenance"]["extensions"]
        self.assertEqual(set(extensions), set(SLOT_NAMES))

    def test_vocabulary_digest_matches_an_independently_computed_canonical_hash(self):
        # Pins D2's exact serialization contract (sort_keys, compact
        # separators) from outside `provenance.py`'s own helper — a
        # non-canonical-but-internally-consistent implementation would pass
        # every other digest test here but fail this one.
        expected = "sha256:" + hashlib.sha256(
            json.dumps(vocab.vocabulary_document(), sort_keys=True,
                       separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(compile_login()["provenance"]["vocabulary_digest"], expected)

    def test_enforcement_digest_matches_an_independently_computed_canonical_hash(self):
        expected_payload = {
            "%s.%s" % (clause, name): {"status": status, "note": note}
            for (clause, name), (status, note) in ENFORCEMENT.items()
        }
        expected = "sha256:" + hashlib.sha256(
            json.dumps(expected_payload, sort_keys=True,
                       separators=(",", ":")).encode("utf-8")).hexdigest()
        self.assertEqual(compile_login()["provenance"]["enforcement_digest"], expected)

    def test_extensions_slot_is_an_empty_list_when_nothing_is_registered(self):
        # No third-party entry points are installed in the test environment,
        # so every slot's registered-name list is empty (never omitted, never
        # null — same "empty collection, not None" rule as t-cap/t-vocab).
        extensions = compile_login()["provenance"]["extensions"]
        for slot in SLOT_NAMES:
            self.assertEqual(extensions[slot], [], slot)


class VocabularyDigestDriftTests(unittest.TestCase):
    """Boundary: the digest must move when the thing it digests moves."""

    def test_vocabulary_digest_changes_when_the_vocabulary_document_changes(self):
        baseline = provenance._current_vocabulary_digest()
        mutated = dict(vocab.vocabulary_document())
        mutated["verbs"] = dict(mutated["verbs"])
        mutated["verbs"]["__simulated_new_verb__"] = {"effect": "read", "attrs": {}}
        with mock.patch.object(vocab, "vocabulary_document", return_value=mutated):
            drifted = provenance._current_vocabulary_digest()
        self.assertNotEqual(baseline, drifted)

    def test_vocabulary_digest_is_stable_across_repeated_calls(self):
        self.assertEqual(provenance._current_vocabulary_digest(),
                          provenance._current_vocabulary_digest())

    def test_enforcement_digest_changes_when_enforcement_changes(self):
        baseline = provenance._current_enforcement_digest()
        mutated = copy.deepcopy(ENFORCEMENT)
        mutated[("policy", "__simulated__")] = ("enforced", "test-only")
        with mock.patch.object(provenance, "ENFORCEMENT", mutated):
            drifted = provenance._current_enforcement_digest()
        self.assertNotEqual(baseline, drifted)


class CheckHelperTests(unittest.TestCase):
    """`lnpl.provenance.check()` — report-only, never raises."""

    def test_matching_document_reports_both_digests_matching(self):
        report = provenance.check(compile_login())
        self.assertTrue(report["vocabulary_match"])
        self.assertTrue(report["enforcement_match"])
        self.assertEqual(report["missing_extensions"], {})

    def test_stale_vocabulary_digest_reports_a_mismatch_not_an_error(self):
        doc = compile_login()
        doc["provenance"] = dict(doc["provenance"])
        doc["provenance"]["vocabulary_digest"] = "sha256:" + "0" * 64
        report = provenance.check(doc)
        self.assertFalse(report["vocabulary_match"])
        self.assertTrue(report["enforcement_match"])

    def test_extension_registered_in_document_but_absent_now_is_reported_missing(self):
        doc = compile_login()
        doc["provenance"] = dict(doc["provenance"])
        doc["provenance"]["extensions"] = dict(doc["provenance"]["extensions"])
        doc["provenance"]["extensions"]["repository"] = ["__phantom_driver__"]
        report = provenance.check(doc)
        self.assertEqual(report["missing_extensions"], {"repository": ["__phantom_driver__"]})

    def test_document_without_a_provenance_block_reports_none_not_an_error(self):
        legacy = {"lir_version": "0.1", "module": "login", "nodes": []}
        report = provenance.check(legacy)  # must not raise
        self.assertIsNone(report["vocabulary_match"])
        self.assertIsNone(report["enforcement_match"])
        self.assertEqual(report["missing_extensions"], {})

    def test_check_never_raises_on_a_malformed_provenance_block(self):
        doc = {"lir_version": "0.1", "module": "login", "nodes": [],
               "provenance": {}}
        report = provenance.check(doc)  # missing keys inside the block
        self.assertFalse(report["vocabulary_match"])
        self.assertFalse(report["enforcement_match"])
        self.assertEqual(report["missing_extensions"], {})


class GoldenGateIgnoresProvenanceTests(unittest.TestCase):
    """D5: the golden-pair comparison must not see `provenance` at all."""

    def test_golden_pair_comparison_excludes_provenance_from_both_sides(self):
        from tests.test_golden import GOLDEN_IR as LOGIN_GOLDEN_IR
        with open(LOGIN_GOLDEN_IR, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertNotIn("provenance", committed,
                         "golden files stay provenance-free (D5) — a digest "
                         "must never be baked into a committed fixture")
        compiled = compile_login()
        self.assertIn("provenance", compiled)
        compiled_without_provenance = dict(compiled)
        compiled_without_provenance.pop("provenance")
        self.assertEqual(compiled_without_provenance, committed)


if __name__ == "__main__":
    unittest.main()
