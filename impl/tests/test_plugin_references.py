"""플러그인 어휘 문서가 소스에서 생성된 그대로인지 검사한다.

정본은 `impl/lnpl/`의 모듈 상수다. `references/*.md`는 산출물이고, 사람이
고치면 안 된다. 고치면 플러그인이 틀린 어휘를 권위 있게 가르치게 된다 —
`docs/ENFORCEMENT-MATRIX.md`가 `test_enforcement_matrix.py`로 고정된 것과
같은 이유, 같은 장치다.
"""
import os
import re
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GEN = os.path.join(REPO, "scripts", "gen_plugin_references.py")
REFS = os.path.join(REPO, "plugins", "lnpl", "skills", "lnpl-authoring", "references")
EXPECTED = ("grammar.md", "verbs.md", "declarations.md", "types.md", "spec.md",
            "naming.md")


def run_gen(*args):
    env = dict(os.environ, PYTHONPATH=os.path.join(REPO, "impl"))
    return subprocess.run([sys.executable, GEN, *args], cwd=REPO, env=env,
                          capture_output=True, text=True)


class GeneratorTest(unittest.TestCase):
    def test_generator_exists(self):
        self.assertTrue(os.path.isfile(GEN))

    def test_all_reference_files_present(self):
        for name in EXPECTED:
            self.assertTrue(os.path.isfile(os.path.join(REFS, name)),
                            "%s가 없다 — 생성기를 돌려라" % name)

    def test_no_drift_between_source_and_committed_files(self):
        proc = run_gen("--check")
        self.assertEqual(proc.returncode, 0,
                         "어휘 문서가 소스와 어긋났다. `python scripts/"
                         "gen_plugin_references.py`로 재생성하라.\n%s" % proc.stderr)

    def test_check_mode_detects_a_hand_edit(self):
        # 게이트가 실제로 잡는지 증명한다 — 통과만으로는 잠자는 테스트와 구별되지 않는다.
        target = os.path.join(REFS, "verbs.md")
        with open(target, encoding="utf-8") as fh:
            original = fh.read()
        try:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(original + "\n손으로 덧붙인 줄\n")
            proc = run_gen("--check")
            self.assertEqual(proc.returncode, 1)
            self.assertIn("verbs.md", proc.stderr)
        finally:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(original)

    def test_check_mode_reports_a_missing_file(self):
        target = os.path.join(REFS, "spec.md")
        with open(target, encoding="utf-8") as fh:
            original = fh.read()
        try:
            os.remove(target)
            proc = run_gen("--check")
            self.assertEqual(proc.returncode, 1)
            self.assertIn("spec.md", proc.stderr)
        finally:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(original)

    def test_generated_files_carry_the_do_not_edit_banner(self):
        for name in EXPECTED:
            with open(os.path.join(REFS, name), encoding="utf-8") as fh:
                head = fh.readline()
            self.assertIn("생성물", head, "%s에 경고 배너가 없다" % name)

    def test_every_verb_in_the_lexicon_reaches_the_document(self):
        from lnpl.lower import VERB_LEXICON
        with open(os.path.join(REFS, "verbs.md"), encoding="utf-8") as fh:
            text = fh.read()
        for verb in VERB_LEXICON:
            self.assertIn("`%s`" % verb, text)

    def test_every_enforcement_row_reaches_the_document(self):
        from lnpl.diagnostics import ENFORCEMENT
        with open(os.path.join(REFS, "declarations.md"), encoding="utf-8") as fh:
            text = fh.read()
        for clause, name in ENFORCEMENT:
            self.assertIn("`%s %s`" % (clause, name), text)

    def test_every_diagnostic_code_reaches_the_document_with_its_grade(self):
        """The grade column must be *derived*, not typed in (#52, RFC-0021).

        `--check` alone cannot see this: it compares the committed file against
        the generator's own output, so a generator that hardcoded every grade to
        `warning` would regenerate happily and stay green. This asserts the
        document against `SEVERITY_OF` itself, which is the only comparison that
        can tell "derived from the table" from "agrees with the generator".
        """
        from lnpl.diagnostics import CODES, SEVERITY_OF
        with open(os.path.join(REFS, "declarations.md"), encoding="utf-8") as fh:
            text = fh.read()
        for code in CODES:
            self.assertIn("| `%s` | **%s** |" % (code, SEVERITY_OF[code]), text,
                          "declarations.md disagrees with SEVERITY_OF for %r" % code)

    def test_the_grade_column_is_not_a_single_repeated_value(self):
        """Negative control: a column of one value carries no information.

        That is precisely the #52 defect one level up — the `severity` field
        existed but every code read `warning`, so nothing could select on it.
        """
        from lnpl.diagnostics import CODES, SEVERITY_OF
        self.assertGreater(len({SEVERITY_OF[c] for c in CODES}), 1)


SKILL_DIR = os.path.join(REPO, "plugins", "lnpl", "skills", "lnpl-authoring")
SKILL_MD = os.path.join(SKILL_DIR, "SKILL.md")


def read_frontmatter(path):
    """`---`로 감싼 YAML 머리말을 아주 단순하게 읽는다 (key: value만)."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    if lines[0].strip() != "---":
        raise AssertionError("%s가 `---`로 시작하지 않는다" % path)
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


class ComparatorCanonTest(unittest.TestCase):
    """`==`/`!=` must say the same thing in the lexer, the RFC and the reference.

    Issue #50 t4 F-7: RFC-0008 §1 promised `==`/`!=` while the generated
    grammar.md listed only `<= >= < >`, and an author could not tell which one
    the implementation actually was — so they designed around it without ever
    testing the real behaviour. RFC-0015 closed the gap by updating RFC-0008 §1
    and adding both to `COMPARATORS`. This pins all three surfaces together so
    the next comparator cannot land in two of them.
    """

    RFC = os.path.join(REPO, "rfcs", "0015-value-semantics.md")

    def _rfc_comparators(self):
        with open(self.RFC, encoding="utf-8") as fh:
            for line in fh:
                if line.strip().startswith("Comparator"):
                    return set(re.findall(r"'([^']+)'", line))
        self.fail("RFC-0015에서 `Comparator ::=` 생산규칙을 못 찾았다 — "
                  "절이 사라졌거나 이름이 바뀌었다")

    def _reference_comparators(self):
        with open(os.path.join(REFS, "grammar.md"), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("비교 연산자:"):
                    return set(re.findall(r"`([^`]+)`", line))
        self.fail("grammar.md에서 '비교 연산자:' 줄을 못 찾았다")

    def test_the_extractors_find_a_full_set(self):
        """Negative control: an empty match must not pass as agreement."""
        from lnpl.lexer import COMPARATORS
        self.assertEqual(len(COMPARATORS), 6)
        self.assertEqual(len(self._rfc_comparators()), 6)
        self.assertEqual(len(self._reference_comparators()), 6)

    def test_equality_comparators_are_present_everywhere(self):
        from lnpl.lexer import COMPARATORS
        for op in ("==", "!="):
            self.assertIn(op, COMPARATORS)
            self.assertIn(op, self._rfc_comparators())
            self.assertIn(op, self._reference_comparators())

    def test_all_three_surfaces_agree(self):
        from lnpl.lexer import COMPARATORS
        self.assertEqual(set(COMPARATORS), self._rfc_comparators())
        self.assertEqual(set(COMPARATORS), self._reference_comparators())


class UndocumentedRuleTest(unittest.TestCase):
    """이슈 #50: `--check`만으로는 부족한 부분.

    `--check`는 파일이 생성기와 같은지만 본다. 생성기에서 절을 통째로 지워도
    재생성하면 다시 초록이다 — QA가 4/4 케이스에서 관측한 미문서 규칙 셋이
    바로 그렇게 사라질 수 있다. 그래서 규칙의 **존재**를 따로 단언한다.
    """

    def _read(self, name):
        with open(os.path.join(REFS, name), encoding="utf-8") as fh:
            return fh.read()

    def test_guard_scope_rule_is_documented(self):
        """t1 F-4: 가드가 뒤따르는 블록 전체를 감싼다는 오해."""
        text = self._read("grammar.md")
        self.assertIn("가드의 스코프", text)
        self.assertIn("바로 다음 항목 하나", text)
        # 회피책이 없으면 규칙만 알고 빠져나오지 못한다.
        self.assertIn("parallel", text)

    def test_guard_condition_type_restriction_is_documented(self):
        """가드 참조는 Integer/DateTime만 받는다 — Presence도 마찬가지."""
        text = self._read("grammar.md")
        self.assertIn("Integer 또는 DateTime", text)

    def test_step_object_spelling_rule_is_documented(self):
        """t3 F-4/F-6: 다단어 엔티티 참조 불가 + 복수형 불인식."""
        from lnpl.lower import split_pascal
        text = self._read("naming.md")
        self.assertIn("".join(split_pascal("DailyReport")), text)   # dailyreport
        self.assertIn("DailyReport", text)                          # 거부되는 표기
        self.assertIn("복수형", text)

    def test_node_id_derivation_is_documented(self):
        """t3 F-7: `--workflow`가 요구하는 id가 어디에서 오는지."""
        from lnpl.lower import derive_id
        text = self._read("naming.md")
        self.assertIn(derive_id("GetReport", "Workflow"), text)      # wf.get.report
        self.assertIn("--workflow", text)


class AuthoringSkillTest(unittest.TestCase):
    def test_skill_file_exists(self):
        self.assertTrue(os.path.isfile(SKILL_MD))

    def test_frontmatter_name_matches_directory(self):
        meta = read_frontmatter(SKILL_MD)
        self.assertEqual(meta.get("name"), "lnpl-authoring")

    def test_frontmatter_has_a_triggering_description(self):
        meta = read_frontmatter(SKILL_MD)
        desc = meta.get("description", "")
        self.assertGreater(len(desc), 40, "description이 너무 짧아 트리거되지 않는다")
        self.assertIn(".lnpl", desc)

    def test_every_reference_file_is_linked(self):
        with open(SKILL_MD, encoding="utf-8") as fh:
            text = fh.read()
        for name in EXPECTED:
            self.assertIn("references/%s" % name, text,
                          "%s로 가는 경로가 SKILL.md에 없다" % name)

    def test_skill_body_stays_a_routing_layer(self):
        # A4: 어휘를 SKILL.md에 인라인하면 .lnpl을 안 쓰는 세션까지 비용을 낸다.
        with open(SKILL_MD, encoding="utf-8") as fh:
            text = fh.read()
        self.assertLess(len(text), 4000,
                        "SKILL.md가 라우팅 계층을 넘어섰다 — 본문은 references/로")

    def test_skill_does_not_inline_the_verb_table(self):
        from lnpl.lower import VERB_LEXICON
        with open(SKILL_MD, encoding="utf-8") as fh:
            text = fh.read()
        hits = sum(1 for verb in VERB_LEXICON if "`%s`" % verb in text)
        self.assertLessEqual(hits, 4,
                             "동사 표가 SKILL.md에 복사됐다 — verbs.md로 라우팅만 하라")

    def test_reserved_keywords_are_called_out_at_the_routing_layer(self):
        # if/for/while/switch는 LLM의 기본 반사라 라우팅 단계에서 막아야 한다.
        with open(SKILL_MD, encoding="utf-8") as fh:
            text = fh.read()
        for word in ("if", "for", "while", "switch"):
            self.assertIn("`%s`" % word, text)


if __name__ == "__main__":
    unittest.main()
