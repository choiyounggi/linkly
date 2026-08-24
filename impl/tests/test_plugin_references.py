"""플러그인 어휘 문서가 소스에서 생성된 그대로인지 검사한다.

정본은 `impl/lnpl/`의 모듈 상수다. `references/*.md`는 산출물이고, 사람이
고치면 안 된다. 고치면 플러그인이 틀린 어휘를 권위 있게 가르치게 된다 —
`docs/ENFORCEMENT-MATRIX.md`가 `test_enforcement_matrix.py`로 고정된 것과
같은 이유, 같은 장치다.
"""
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLAUDE_TMP = os.path.join(REPO, ".claude", "tmp")
GEN = os.path.join(REPO, "scripts", "gen_plugin_references.py")
REFS = os.path.join(REPO, "plugins", "lnpl", "skills", "lnpl-authoring", "references")
EXPECTED = ("grammar.md", "verbs.md", "declarations.md", "types.md", "spec.md",
            "naming.md", "rfcs.md")


def run_gen(*args):
    env = dict(os.environ, PYTHONPATH=os.path.join(REPO, "impl"))
    return subprocess.run([sys.executable, GEN, *args], cwd=REPO, env=env,
                          capture_output=True, text=True)


def load_gen():
    """생성기를 모듈로 들여온다 — 렌더러의 fail-closed 거부를 직접 부르기 위해.

    `run_gen`은 서브프로세스라 예외의 종류를 볼 수 없다. 반증 컨트롤은
    "무엇이 붉어졌는가"를 검사마다 구별해야 하므로(각 검사가 자기 소유
    mutation만 붉힌다) 여기서는 모듈을 직접 부른다. 매번 새로 로드해서
    한 테스트의 몽키패치가 다음 테스트로 새지 않게 한다.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_plugin_references", GEN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def table_rows(text, header_cell):
    """`header_cell`을 첫 칸으로 갖는 표의 **본문** 행들을 칸 단위로 돌려준다.

    GFM은 칸 안의 리터럴 파이프를 `\\|`로 적게 하므로, 이스케이프되지 않은
    파이프로만 쪼갠 뒤 각 칸의 이스케이프를 되돌린다. 순진한 `split("|")`은
    그런 칸을 가진 행에서 칸 수를 부풀려 멀쩡한 표를 "깨진 표"로 신고한다.
    """
    rows, inside = [], False
    for line in text.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            inside = False
            continue
        cells = _split_row(line)
        if not inside:
            if cells and cells[0] == header_cell:
                inside = True
            continue
        if set("".join(cells)) <= set("-: "):
            continue                      # 구분선
        rows.append(cells)
    return rows


def _split_row(row):
    row = re.sub(r"(?<!\\)\|$", "", re.sub(r"^\|", "", row.strip()))
    return [c.replace(r"\|", "|").strip() for c in re.split(r"(?<!\\)\|", row)]


def section(text, heading):
    """`heading` 줄부터 같은 수준 이상의 다음 제목 직전까지. 없으면 None.

    규칙 검사를 절 범위로 좁히는 데 쓴다. 문서 전체에 대고 낱말을 세면 예시
    블록이나 옆 절의 산문이 규칙 대신 통과해 버린다 — 절이 통째로 지워져도
    초록인 검사가 그렇게 만들어진다. 못 찾으면 None을 주고, 호출자는 그것을
    **실패**로 다룬다(건너뛰기가 아니라).
    """
    lines = text.split("\n")
    if heading not in lines:
        return None
    start = lines.index(heading)
    level = len(heading) - len(heading.lstrip("#"))
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.startswith("#") and len(line) - len(line.lstrip("#")) <= level:
            return "\n".join(lines[start:index])
    return "\n".join(lines[start:])


def backticked(line):
    return set(re.findall(r"`([^`]+)`", line))


def line_starting(text, prefix):
    for line in text.split("\n"):
        if line.startswith(prefix):
            return line
    return None


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

    def test_every_given_form_reaches_the_document(self):
        # Issue #54: the reference used to keep its OWN hand-written list of
        # `given` forms, and that copy is what left the first-entity limit
        # undocumented while the diagnostics were equally silent (r1 N-4).
        from lnpl.spec import GIVEN_FORMS
        with open(os.path.join(REFS, "spec.md"), encoding="utf-8") as fh:
            text = fh.read()
        for _key, form, doc in GIVEN_FORMS:
            self.assertIn("`%s`" % form, text)
            self.assertIn(doc, text)

    def test_every_expect_format_reaches_the_document(self):
        # Issue #61: the section used to be a bare key list — `rows`,
        # `effects`, and `emitted` gave no hint of the formats or comparators
        # they take, so a reader had to go read spec.py to find out.
        with open(os.path.join(REFS, "spec.md"), encoding="utf-8") as fh:
            text = fh.read()
        for signature in ("rows <Entity> <N>", "effects <N>", "effects complete",
                          "emitted <Name>", "error reason"):
            self.assertIn(signature, text, "%r missing from expect section" % signature)

    def test_render_refuses_an_expect_handler_with_no_docstring(self):
        # A new expect key added without a docstring must fail the build, not
        # render a blank cell — a silent gap is what issue #61 exists to close.
        gen = load_gen()
        def _fake(_phrase, _result, _interp):
            return True, "ok"
        gen.EXPECTATIONS = dict(gen.EXPECTATIONS)
        gen.EXPECTATIONS["fake"] = _fake
        with self.assertRaises(RuntimeError) as caught:
            gen.render_spec()
        self.assertIn("fake", str(caught.exception))

    def test_render_refuses_an_expect_handler_whose_docstring_has_no_format(self):
        # A docstring can exist but still say nothing quotable — e.g. prose
        # with no backticked signature. That must fail closed too.
        gen = load_gen()
        def _fake(_phrase, _result, _interp):
            return True, "ok"
        _fake.__doc__ = "does the fake thing, no format quoted here"
        gen.EXPECTATIONS = dict(gen.EXPECTATIONS)
        gen.EXPECTATIONS["fake"] = _fake
        with self.assertRaises(RuntimeError) as caught:
            gen.render_spec()
        self.assertIn("fake", str(caught.exception))

    def test_a_multi_line_docstring_paragraph_joins_into_one_table_cell(self):
        # Boundary: `_expect_emitted`'s first paragraph spans two physical
        # lines in the source and contains a literal `|` (`exists|missing`).
        # The generated cell must join the lines and escape the pipe, or the
        # markdown table row breaks — either into a ragged cell or extra columns.
        with open(os.path.join(REFS, "spec.md"), encoding="utf-8") as fh:
            text = fh.read()
        rows = {cells[0]: cells[1] for cells in table_rows(text, "키")}
        self.assertIn("`emitted`", rows)
        self.assertIn("`emitted <Name> payload <field> exists|missing`", rows["`emitted`"])
        self.assertNotIn("\n", rows["`emitted`"])

    def test_the_effects_complete_opt_in_rationale_is_quoted(self):
        # D2: the "why is this opt-in" paragraph is what motivated issue #61 —
        # without it, a reader sees `effects complete` exists but not why it
        # doesn't fire automatically on every unknown-verb diagnostic.
        with open(os.path.join(REFS, "spec.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("opt-in rather than", text)
        self.assertIn("login.lnpl", text)

    def test_the_scope_of_given_no_is_documented(self):
        # r4 F-6: `no <field>`'s scope was undocumented, so an author could not
        # tell what it removes from — the input payload, the seeded row, or both.
        # Asserted as four distinct BULLETS under the scope heading, not as
        # keywords loose in the file: a keyword-presence gate passes on a
        # document that mentions the words while answering none of the four
        # questions an author actually has.
        with open(os.path.join(REFS, "spec.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("## `given no`의 스코프", text)
        section = text.split("## `given no`의 스코프", 1)[1].split("\n## ", 1)[0]
        bullets = [l for l in section.splitlines() if l.startswith("- ")]
        self.assertEqual(len(bullets), 4, section)
        # Each question gets its own bullet, in order: what is removed, what
        # happens to the seeded row, how `stored` interacts, and whether
        # removing an absent field is an error.
        for index, claim in enumerate(("입력 payload", "시드", "stored", "no-op")):
            self.assertIn(claim, bullets[index], bullets)


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

    # -- 이슈 #56 [2]: `set` 대상 바인딩 규칙 -----------------------------
    #
    # r3 N-2: `create report` 뒤의 `set report.orderCount to …`가 거부되는데,
    # "set 대상은 read 계열로 바인딩된 행이어야 한다"는 규칙이 references
    # 어디에도 없었다. 저자는 거부만 보고 규칙을 역추정해야 했다.

    SET_TARGET_HEADING = "## 할당(`set`)의 대상"
    READ_VERBS_PREFIX = "읽기 동사:"
    CREATE_VERBS_PREFIX = "결과를 바인딩하는 동사:"
    NO_BINDING_PREFIX = "바인딩을 만들지 않는 동사:"
    ROWSET_VERBS_PREFIX = "행 집합(RowSet) 동사:"

    def _set_target_section(self):
        body = section(self._read("grammar.md"), self.SET_TARGET_HEADING)
        self.assertIsNotNone(
            body, "grammar.md에 %r 절이 없다 — 앵커가 사라지면 아래 검사는 "
                  "'볼 것이 없다'가 아니라 실패여야 한다" % self.SET_TARGET_HEADING)
        return body

    def _repo_verbs(self):
        """(단일 행 바인딩을 만드는 동사, `as`로 결과를 바인딩할 수 있는
        동사, 아무 바인딩도 만들지 않는 동사, RowSet을 바인딩하는 동사).

        `lower.READ_VERBS`를 그대로 쓴다 — `_check_scoped_conditions`가
        `read_entities`를 세우는 것과 같은 소스(RFC-0025 §5/§6.1:
        `operation == "read"`만, `repo_policy.READ_OPS`의 `query`는 빠진다 —
        `list`는 단일 행이 아니라 RowSet을 별개 이름공간에 바인딩하므로). 이
        전에는 `repo_policy.READ_OPS`를 다시 계산해 이분법(읽기/쓰기)으로
        썼는데, `lower.py`가 `read_entities`를 그 테이블에서 떼어 놓은 뒤로
        그 재계산이 바로 이 검사가 막으려던 조용한 어긋남이 되었다 — 소스를
        한 곳으로 합치고, RowSet을 세 번째 갈래로 분리한다(둘 다 아니므로).
        issue #97 / RFC-0012 Updates(RFC-0030): `create` 연산은 더 이상
        "아무 바인딩도 만들지 않는" 갈래가 아니다 — `as <이름>`을 붙이면
        결과를 바인딩한다(`update`/`delete`는 여전히 바인딩하지 않는다) —
        그래서 네 번째 갈래로 분리한다.
        """
        from lnpl.lower import READ_VERBS, VERB_LEXICON
        reads, create, writes, rowset = set(), set(), set(), set()
        for verb, (kind, attrs) in VERB_LEXICON.items():
            if kind != "RepositoryCall":
                continue
            if verb in READ_VERBS:
                reads.add(verb)
            elif attrs.get("operation") == "query":
                rowset.add(verb)
            elif attrs.get("operation") == "create":
                create.add(verb)
            else:
                writes.add(verb)
        return reads, create, writes, rowset

    def test_set_target_binding_rule_is_documented(self):
        body = self._set_target_section()
        # issue #97 / RFC-0012 Updates: `set`의 바인딩은 이제 "읽은" 행뿐
        # 아니라 `create ... as`로 "만든" 행도 포함한다.
        self.assertIn("읽었거나 만든", body)
        # 규칙만 알고 빠져나오지 못하면 소용없다 — 수리 경로가 같은 절에 있어야 한다.
        self.assertRegex(body, r"`read`|`load`|`find`")
        self.assertIn("`create <명사> as <이름>`", body)

    def test_the_read_verbs_in_the_document_match_the_lexicon(self):
        """전사 드리프트 차단: 어휘가 바뀌면 문서가 따라오거나 붉어진다."""
        reads, _create, _writes, _rowset = self._repo_verbs()
        line = line_starting(self._set_target_section(), self.READ_VERBS_PREFIX)
        self.assertIsNotNone(line, "%r 줄이 없다" % self.READ_VERBS_PREFIX)
        self.assertEqual(backticked(line), reads)

    def test_the_create_verbs_in_the_document_match_the_lexicon(self):
        """issue #97 / RFC-0012 Updates: `as`로 결과를 바인딩할 수 있는
        동사(`create`/`insert`)가 문서에 자기 갈래를 갖는다."""
        _reads, create, _writes, _rowset = self._repo_verbs()
        line = line_starting(self._set_target_section(), self.CREATE_VERBS_PREFIX)
        self.assertIsNotNone(line, "%r 줄이 없다" % self.CREATE_VERBS_PREFIX)
        self.assertEqual(backticked(line), create)
        self.assertIn("create", create)

    def test_the_non_binding_verbs_in_the_document_match_the_lexicon(self):
        _reads, _create, writes, _rowset = self._repo_verbs()
        line = line_starting(self._set_target_section(), self.NO_BINDING_PREFIX)
        self.assertIsNotNone(line, "%r 줄이 없다" % self.NO_BINDING_PREFIX)
        self.assertEqual(backticked(line), writes)

    def test_the_rowset_verbs_in_the_document_match_the_lexicon(self):
        """RFC-0025 §5: `list`는 단일 행도, "바인딩 없음"도 아닌 세 번째
        갈래다 — 그 갈래가 문서에도 따로 있어야 한다."""
        _reads, _create, _writes, rowset = self._repo_verbs()
        line = line_starting(self._set_target_section(), self.ROWSET_VERBS_PREFIX)
        self.assertIsNotNone(line, "%r 줄이 없다" % self.ROWSET_VERBS_PREFIX)
        self.assertEqual(backticked(line), rowset)
        self.assertIn("list", rowset)

    def test_the_four_verb_lines_do_not_overlap(self):
        """경계: 네 줄이 서로 겹치면 위 검사들은 통과해도 갈래가 무의미하다."""
        reads, create, writes, rowset = self._repo_verbs()
        groups = (reads, create, writes, rowset)
        for i, a in enumerate(groups):
            for b in groups[i + 1:]:
                self.assertEqual(a & b, set())
        for group in groups:
            self.assertGreater(len(group), 0)

    def test_input_is_documented_as_an_illegal_assignment_target(self):
        """에러 케이스: `set input.x to …`가 왜 거부되는지."""
        body = self._set_target_section()
        self.assertIn("input.", body)
        self.assertRegex(body, r"대상이 될 수 없다|대상이 아니다")

    def test_the_section_helper_fails_closed_on_a_missing_heading(self):
        """반증 컨트롤: 위 검사들이 '절이 없으면 조용히 통과'가 아님을 보인다."""
        self.assertIsNone(section(self._read("grammar.md"), "## 없는 절"))

    # -- 이슈 #56 [3]: 블록의 시작과 종결 --------------------------------
    #
    # r1 N-5: grammar.md의 블록 예시는 `parallel … merge`뿐이라, `pipeline`
    # 뒤에 `merge`를 둔 저자는 진단으로만 "merge는 parallel 전용"을 알았고
    # pipeline이 어디서 끝나는지는 끝내 역추정해야 했다.

    BLOCK_HEADING = "## 블록의 시작과 종결"

    BLOCK_SOURCE = """
capability postgres
entity Order
    field
        id UUID
        total Integer
service ShopService
    policy
        retry 0
workflow Checkout
%s
"""

    def _block_section(self):
        body = section(self._read("grammar.md"), self.BLOCK_HEADING)
        self.assertIsNotNone(body, "grammar.md에 %r 절이 없다" % self.BLOCK_HEADING)
        return body

    def _parse_failure(self, steps):
        from lnpl.parser import ParseError, parse
        with self.assertRaises(ParseError) as caught:
            parse(self.BLOCK_SOURCE % steps)
        return str(caught.exception)

    def test_the_block_termination_rule_is_documented(self):
        body = self._block_section()
        self.assertIn("merge", body)
        self.assertIn("pipeline", body)

    def test_the_document_quotes_the_refusal_the_parser_actually_emits(self):
        """교차 참조: 전사한 문면이 아니라 파서가 지금 내는 문면이어야 한다."""
        message = self._parse_failure("    pipeline\n    create order\n    merge")
        quoted = "`merge` closes a `parallel` block, but none is open"
        self.assertIn(quoted, message,
                      "파서 문면이 바뀌었다 — 문서도 같이 고쳐야 한다")
        self.assertIn(quoted, self._block_section())

    def test_the_document_quotes_the_unclosed_parallel_refusal(self):
        message = self._parse_failure("    parallel\n    create order")
        quoted = "ends with an unclosed `parallel` block (missing `merge`)"
        self.assertIn(quoted, message)
        self.assertIn(quoted, self._block_section())

    def test_the_pipeline_is_documented_as_not_taking_merge(self):
        """양태: 부정문이 살아 있어야 한다 — 긍정으로 뒤집히면 규칙이 사라진다."""
        body = self._block_section()
        self.assertRegex(body, r"`merge`(로|가)[^\n]*(닫지 않는다|아니다)")

    def test_the_keywords_that_close_a_pipeline_match_the_lexer(self):
        """전사 드리프트 차단: 암묵 종결을 일으키는 키워드 집합."""
        from lnpl.lexer import KEYWORDS_CONTROL
        expected = set(KEYWORDS_CONTROL) - {"merge"}
        line = line_starting(self._block_section(), "암묵 종결:")
        self.assertIsNotNone(line, "`암묵 종결:` 줄이 없다")
        self.assertEqual(backticked(line), expected)

    def test_a_pipeline_really_is_closed_by_the_next_control_keyword(self):
        """정상 대조군: 문서가 말하는 암묵 종결이 실제로 일어난다."""
        from lnpl.parser import parse
        decls = parse(self.BLOCK_SOURCE
                      % "    pipeline\n    find order\n    when order.total > 0"
                        "\n    create order")
        self.assertTrue(decls)

    def test_the_nesting_depth_and_naming_rules_are_documented(self):
        """경계: 이름·중첩 제약도 진단으로만 발견되던 것들."""
        body = self._block_section()
        self.assertIn("`pipeline` takes at most one name",
                      self._parse_failure(
                          "    pipeline a b\n    create order"))
        self.assertRegex(body, r"이름")
        self.assertRegex(body, r"중첩|깊이")

    # -- 이슈 #56 [4]: create 충돌의 현재 계약 ---------------------------
    #
    # r2 N-3: `given stored Payment id <같은 uuid>` 뒤의 `create payment`가
    # 조용히 completed로 끝났다. 저장소는 충돌을 구현하고 있으나 시드 규칙이
    # create만 하는 엔티티를 비워 두므로, "사전 행이 있어 충돌한다"는 시나리오는
    # 애초에 세워지지 않는다. 문서는 그 사실을 **표현 불가로** 적어야 한다.

    CONFLICT_HEADING = "## 저장소 시드와 `create` 충돌"

    def _conflict_section(self):
        body = section(self._read("spec.md"), self.CONFLICT_HEADING)
        self.assertIsNotNone(body,
                             "spec.md에 %r 절이 없다" % self.CONFLICT_HEADING)
        return body

    def test_the_create_conflict_contract_is_documented(self):
        body = self._conflict_section()
        self.assertIn("stored", body)
        self.assertIn("create", body)

    def test_the_document_says_the_scenario_cannot_be_expressed(self):
        """양태: 이 절의 요점은 '없다'이다 — 긍정으로 뒤집히면 거짓이 된다."""
        body = self._conflict_section()
        self.assertRegex(body, r"표현할 수 없다|세울 수 없다")

    def test_the_document_names_the_seed_rule_as_the_cause(self):
        """'표현 수단이 없다'가 아니라 '시드가 비어 있다'가 원인이다."""
        body = self._conflict_section()
        self.assertRegex(body, r"읽는 엔티티|읽는 것만|읽지 않")

    def test_the_documented_failure_reason_is_the_one_the_runtime_emits(self):
        """교차 참조: 전사한 문면이 아니라 지금 실행이 내는 문면이어야 한다."""
        from lnpl import repo_policy
        from lnpl.interp import Interpreter
        from lnpl.lower import lower
        from lnpl.parser import parse
        source = """
capability postgres
entity Order
    field
        id UUID
        total Integer
service ShopService
    policy
        retry 0
workflow Checkout
    create order
    create order
"""
        doc = lower(parse(source), "shop").to_document()
        payload = {"id": "abc", "total": 1}
        result = Interpreter(
            doc, repo_rows=repo_policy.default_rows(doc, "wf.checkout", payload)
        ).run_workflow("wf.checkout", payload)
        self.assertEqual(result["status"], "failed")
        reason = result["failure_reason"]
        self.assertIn("repository create conflicts", reason)
        self.assertIn("repository create conflicts", self._conflict_section())

    def test_the_document_names_both_ways_a_row_can_already_exist(self):
        """규칙만 적고 빠져나갈 길을 안 적으면 저자는 여전히 막힌다.

        경계이자 반증: 처음 쓴 문면은 "관측 가능한 형태는 **하나**"라고 배타를
        주장했는데, `find order` 다음의 `create order`가 그 주장을 깬다(읽는
        엔티티는 시드되므로 충돌한다). 그래서 여기서 고정하는 것은 형태의
        개수가 아니라 **행이 생기는 두 경로**가 둘 다 적혀 있다는 것이다.
        """
        body = self._conflict_section()
        self.assertIn("시드", body)
        self.assertRegex(body, r"두 번")
        self.assertIn("empty repository", body)

    def test_the_document_does_not_claim_a_single_reachable_form(self):
        body = self._conflict_section()
        self.assertNotRegex(
            body, r"관측 가능한 형태는 하나",
            "배타 주장은 거짓이다 — 시드 경로와 앞선 create 경로 둘 다 있다")

    def test_the_row_key_rule_is_documented(self):
        """경계: 충돌이 엔티티 단위가 아니라 (엔티티, 키) 단위임을 말해야 한다."""
        self.assertIn("#", self._conflict_section())
        self.assertRegex(self._conflict_section(), r"키|key")

    def test_the_verb_reference_points_at_the_conflict_section(self):
        """`create`를 찾아온 저자가 그 절에 닿을 수 있어야 한다."""
        self.assertIn("spec.md", self._read("verbs.md"))

    def test_node_id_derivation_is_documented(self):
        """t3 F-7: `--workflow`가 요구하는 id가 어디에서 오는지."""
        from lnpl.lower import derive_id
        text = self._read("naming.md")
        self.assertIn(derive_id("GetReport", "Workflow"), text)      # wf.get.report
        self.assertIn("--workflow", text)


class RfcPointerTest(unittest.TestCase):
    """이슈 #56 [1]: authoring 라우팅에서 RFC(로드맵 포함)로 가는 포인터.

    재측정 r2 N-4는 시간 문법 발견이 RFC 번호 인지에 의존했고, r3 §D12는
    집계 로드맵(RFC-0015 §Alternatives)으로 가는 포인터가 **0건**임을
    측정했다. 그래서 여기서 보는 것은 "표가 있는가"가 아니라 네 축이다:
    구조(칸 수), 집합 완전성(rfcs/ 전부), 교차 참조(경로·절이 실재),
    양태(sentinel의 철자).

    토큰 존재 검사만으로는 부족하다 — 표를 통째로 지워도 근처 산문에 낱말이
    남아 있으면 초록이기 때문이다.
    """

    RFC_DIR = os.path.join(REPO, "rfcs")
    HEADER = "RFC"

    def _rows(self):
        with open(os.path.join(REFS, "rfcs.md"), encoding="utf-8") as fh:
            return table_rows(fh.read(), self.HEADER)

    def _rfc_numbers_on_disk(self):
        names = glob.glob(os.path.join(self.RFC_DIR, "[0-9][0-9][0-9][0-9]-*.md"))
        return {os.path.basename(p)[:4] for p in names}

    # -- 구조 -------------------------------------------------------------
    def test_the_table_parses_into_three_column_rows(self):
        rows = self._rows()
        self.assertGreater(len(rows), 0, "rfcs.md에서 RFC 표를 못 찾았다")
        for cells in rows:
            self.assertEqual(len(cells), 3,
                             "행의 칸 수가 3이 아니다: %r" % (cells,))
            for cell in cells:
                self.assertNotEqual(cell, "", "빈 칸이 있다: %r" % (cells,))

    def test_the_file_carries_the_generated_banner(self):
        with open(os.path.join(REFS, "rfcs.md"), encoding="utf-8") as fh:
            self.assertIn("손으로 고치지 마라", fh.read())

    # -- 집합 완전성 -------------------------------------------------------
    def test_every_rfc_on_disk_has_a_row(self):
        on_disk = self._rfc_numbers_on_disk()
        # 먼저 소스 목록이 비어 있지 않음을 단언한다: 0건으로 파싱되면
        # 집합 비교가 무엇과도 성립해서 커버리지가 헛되이 통과한다.
        self.assertGreaterEqual(len(on_disk), 20,
                                "rfcs/에서 파싱한 RFC가 %d건뿐이다 — 패턴을 의심하라"
                                % len(on_disk))
        in_table = {re.search(r"RFC-(\d{4})", cells[0]).group(1)
                    for cells in self._rows()}
        self.assertEqual(in_table, on_disk)

    # -- 교차 참조 ---------------------------------------------------------
    def test_every_path_cell_resolves_to_a_file(self):
        for cells in self._rows():
            path = cells[2].strip("`")
            self.assertTrue(os.path.isfile(os.path.join(REPO, path)),
                            "경로가 실재하지 않는다: %s" % path)

    def test_the_aggregation_roadmap_row_points_at_the_section_that_holds_it(self):
        """r3 §D12: sum/count가 왜 없고 어디에 로드맵이 있는지로 가는 유일한 길."""
        row = [c for c in self._rows() if c[0].startswith("RFC-0015")]
        self.assertEqual(len(row), 1)
        question = row[0][1]
        self.assertIn("집계", question)
        self.assertIn("Alternatives", question)
        with open(os.path.join(REPO, "rfcs", "0015-value-semantics.md"),
                  encoding="utf-8") as fh:
            rfc = fh.read()
        self.assertIn("### 집계(`sum`/`count`)를 이번 개정에 넣지 않는 이유", rfc)

    def test_the_time_grammar_row_names_the_rfc_that_owns_it(self):
        """r2 N-4: 기간·스케줄 질문이 RFC 번호를 몰라도 0016에 닿아야 한다."""
        row = [c for c in self._rows() if c[0].startswith("RFC-0016")]
        self.assertEqual(len(row), 1)
        self.assertNotEqual(row[0][1], "—")
        self.assertRegex(row[0][1], r"기간|시각|스케줄")

    # -- 양태 (sentinel의 철자) -------------------------------------------
    def test_process_only_rfcs_carry_the_explicit_sentinel(self):
        rows = {c[0][:8]: c[1] for c in self._rows()}
        for number in ("RFC-0000", "RFC-0007"):
            self.assertEqual(rows[number], "—",
                             "%s의 질문 칸은 명시적 sentinel이어야 한다 — "
                             "빈 칸은 '아직 안 썼다'와 구별되지 않는다" % number)

    def test_authoring_rfcs_do_not_carry_the_sentinel(self):
        """경계: sentinel이 번져 표 전체가 '—'가 되면 커버리지는 여전히 초록이다."""
        answered = [c for c in self._rows() if c[1] != "—"]
        self.assertGreaterEqual(len(answered), 15)

    # -- 반증 컨트롤 (검사마다 자기 것만 붉힌다) ---------------------------
    def test_render_refuses_when_a_route_is_missing(self):
        gen = load_gen()
        gen.RFC_ROUTES.pop("0016")
        with self.assertRaises(RuntimeError) as caught:
            gen.render_rfcs()
        self.assertIn("0016", str(caught.exception))

    def test_render_refuses_an_route_with_no_rfc_behind_it(self):
        gen = load_gen()
        gen.RFC_ROUTES["9999"] = ("있지도 않은 RFC", ())
        with self.assertRaises(RuntimeError) as caught:
            gen.render_rfcs()
        self.assertIn("9999", str(caught.exception))

    def test_render_refuses_a_section_anchor_that_does_not_exist(self):
        gen = load_gen()
        question, _anchors = gen.RFC_ROUTES["0015"]
        gen.RFC_ROUTES["0015"] = (question, ("### 이런 절은 없다",))
        with self.assertRaises(RuntimeError) as caught:
            gen.render_rfcs()
        self.assertIn("이런 절은 없다", str(caught.exception))

    def test_render_refuses_when_the_rfc_directory_parses_empty(self):
        """경계: 소스 목록이 0건이면 집합 비교는 무엇과도 성립한다."""
        gen = load_gen()
        gen.RFC_DIR = os.path.join(REPO, "schemas")
        with self.assertRaises(RuntimeError) as caught:
            gen.render_rfcs()
        self.assertIn("rfcs", str(caught.exception))

    def _stub_rfc_world(self, count=23):
        """제목 분기를 실제로 태우기 위한 최소 RFC 세계.

        `rfcs/`의 Accepted 문서는 편집 대상이 아니므로(RFC-0007), 제목이
        깨졌을 때를 관측하려면 렌더러에게 다른 디렉터리를 주는 수밖에 없다.
        번호는 실물과 같은 폭(4자리)을 쓴다 — 렌더러가 파일명 앞 4자를
        번호로 읽기 때문이다.
        """
        os.makedirs(CLAUDE_TMP, exist_ok=True)
        root = tempfile.mkdtemp(prefix="lnpl-i56-rfcs-", dir=CLAUDE_TMP)
        self.addCleanup(shutil.rmtree, root, True)
        routes = {}
        for index in range(count):
            number = "%04d" % index
            with open(os.path.join(root, "%s-stub.md" % number), "w",
                      encoding="utf-8") as fh:
                fh.write("# RFC-%s: 스텁\n\n## Status\n\n- Status: Accepted\n"
                         % number)
            routes[number] = ("스텁 질문", ())
        return root, routes

    def test_the_stub_world_renders_so_the_title_control_means_something(self):
        """양성 대조군: 아래 제목 컨트롤이 '늘 붉음'이 아님을 먼저 보인다."""
        gen = load_gen()
        gen.RFC_DIR, gen.RFC_ROUTES = self._stub_rfc_world()
        self.assertIn("RFC-0000 스텁", gen.render_rfcs())

    def test_render_refuses_a_title_line_it_cannot_parse(self):
        gen = load_gen()
        root, gen.RFC_ROUTES = self._stub_rfc_world()
        gen.RFC_DIR = root
        target = os.path.join(root, "0003-stub.md")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("RFC 0003 — 제목 형식이 아니다\n")
        with self.assertRaises(RuntimeError) as caught:
            gen.render_rfcs()
        self.assertIn("0003", str(caught.exception))

    def test_render_refuses_a_title_whose_number_contradicts_the_filename(self):
        """경계: 형식은 맞지만 번호가 파일명과 어긋나는 경우 — 행이 엉뚱한
        문서를 가리키게 되는데, 형식 검사만으로는 통과한다."""
        gen = load_gen()
        root, gen.RFC_ROUTES = self._stub_rfc_world()
        gen.RFC_DIR = root
        target = os.path.join(root, "0005-stub.md")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("# RFC-0009: 남의 번호를 단 제목\n")
        with self.assertRaises(RuntimeError) as caught:
            gen.render_rfcs()
        self.assertIn("0005", str(caught.exception))

    def test_a_healthy_render_produces_the_committed_file(self):
        """정상 대조군: 위 네 개가 붉어진 이유가 '늘 붉음'이 아님을 보인다."""
        gen = load_gen()
        with open(os.path.join(REFS, "rfcs.md"), encoding="utf-8") as fh:
            self.assertEqual(gen.render_rfcs(), fh.read())


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

    def test_the_routing_table_has_exactly_one_row_to_the_rfc_pointer(self):
        """이슈 #56 [1]: 라우팅 표에서 rfcs.md로 가는 행이 정확히 하나."""
        with open(SKILL_MD, encoding="utf-8") as fh:
            text = fh.read()
        rows = [cells for cells in table_rows(text, "지금 하려는 일")
                if "references/rfcs.md" in cells[1]]
        self.assertEqual(len(rows), 1,
                         "라우팅 표에 rfcs.md 행이 %d개다" % len(rows))
        # 라우팅 문구가 로드맵 질문을 잡아야 한다 — 번호를 아는 사람만
        # 찾을 수 있으면 r2 N-4가 그대로다.
        self.assertRegex(rows[0][0], r"로드맵|왜")

    def test_reserved_keywords_are_called_out_at_the_routing_layer(self):
        # if/for/while/switch는 LLM의 기본 반사라 라우팅 단계에서 막아야 한다.
        with open(SKILL_MD, encoding="utf-8") as fh:
            text = fh.read()
        for word in ("if", "for", "while", "switch"):
            self.assertIn("`%s`" % word, text)


if __name__ == "__main__":
    unittest.main()
