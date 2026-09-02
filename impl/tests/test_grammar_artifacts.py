"""`impl/lnpl/grammar.py`'s GBNF + JSON builders (issue #162).

Source of truth is `vocabulary_document()`; these builders never re-derive
from the compiler tables directly. Membership tests below import the raw
compiler tables independently of `grammar.py` so a hardcoding generator (one
that emits a fixed literal list instead of iterating the table) cannot stay
green.
"""
import re
import unittest

from lnpl.grammar import _gbnf_quote, grammar_json_document, render_gbnf
from lnpl.lexer import (ARITH_OPS, COMPARATORS, KEYWORDS_CLAUSE,
                        KEYWORDS_CONTROL, KEYWORDS_TOP, LOGICAL_OPS)
from lnpl.lower import PERF_METRICS, POLICY_NAMES, SECURITY_MECHANISMS, VERB_LEXICON
from lnpl.spec import EXPECTATIONS, GIVEN_FORMS
from lnpl.types import SEMANTIC_TYPES

# rule name -> the raw compiler-table members it must enumerate, sourced
# independently of grammar.py's own vocab-derived lambdas.
_RULE_MEMBERS = {
    "verb": set(VERB_LEXICON),
    "top_keyword": set(KEYWORDS_TOP),
    "clause_keyword": set(KEYWORDS_CLAUSE),
    "control_keyword": set(KEYWORDS_CONTROL),
    "semantic_type": set(SEMANTIC_TYPES),
    "comparator": set(COMPARATORS),
    "arithmetic_op": set(ARITH_OPS),
    "logical_op": set(LOGICAL_OPS),
    "policy_clause": set(POLICY_NAMES),
    "security_clause": set(SECURITY_MECHANISMS),
    "performance_clause": set(PERF_METRICS),
    "spec_expect": set(EXPECTATIONS),
    "spec_given_form": {pattern for _key, pattern, _doc in GIVEN_FORMS},
}


def _rule_line(gbnf_text, rule_name):
    matches = re.findall(r"^%s ::= .+$" % re.escape(rule_name), gbnf_text,
                         re.MULTILINE)
    return matches


class TestGrammarArtifacts(unittest.TestCase):

    # ---- normal -----------------------------------------------------------

    def test_render_gbnf_has_a_verb_rule_listing_every_verb_lexicon_key(self):
        gbnf = render_gbnf()
        lines = _rule_line(gbnf, "verb")
        self.assertEqual(len(lines), 1)
        for verb in VERB_LEXICON:
            self.assertIn(_gbnf_quote(verb), lines[0])

    # ---- boundary -----------------------------------------------------------

    def test_every_fixed_rule_name_appears_exactly_once(self):
        gbnf = render_gbnf()
        for rule_name in _RULE_MEMBERS:
            lines = _rule_line(gbnf, rule_name)
            self.assertEqual(
                len(lines), 1,
                "expected exactly one %r rule, found %d" % (rule_name,
                                                             len(lines)))

    def test_every_rule_enumerates_every_member_of_its_source_table(self):
        # A count-only check would let a hardcoding generator stay green —
        # this asserts full membership, not just cardinality.
        gbnf = render_gbnf()
        for rule_name, members in _RULE_MEMBERS.items():
            lines = _rule_line(gbnf, rule_name)
            self.assertEqual(len(lines), 1)
            line = lines[0]
            for member in members:
                self.assertIn(
                    _gbnf_quote(member), line,
                    "%r missing from %r rule" % (member, rule_name))

    # ---- error / regression -------------------------------------------------

    def test_json_document_spec_expectations_matches_expectations_table_exactly(self):
        doc = grammar_json_document()
        expects = doc["vocabulary"]["spec_expectations"]["expects"]
        self.assertEqual(expects, sorted(EXPECTATIONS))

    def test_json_document_is_marked_generated_and_never_hand_edit(self):
        doc = grammar_json_document()
        self.assertIs(doc["_generated"]["hand_edit"], False)
        self.assertEqual(doc["_generated"]["source"],
                         "impl/lnpl/grammar.py:grammar_json_document()")


if __name__ == "__main__":
    unittest.main()
