"""`scripts/rfc_lint.py`의 검사 로직 — 합성 입력으로만 검증한다.

이 파일은 **레포의 RFC가 깨끗한지 묻지 않는다.** 린터는 기여자가 손으로 돌리는
도구이고 스위트에 걸려 있지 않다(현재 RFC-0011이 §7 템플릿 섹션 5개를 빠뜨려
있는데, 그것을 채우는 일은 내용 작업이라 도구가 강제할 사안이 아니다).

검사하는 것은 린터가 **옳게 판정하는가**다. 도구가 틀리면 그것을 믿고 내린
판단이 전부 틀어지므로, 규칙마다 통과 케이스와 위반 케이스를 함께 둔다.
"""
import importlib.util
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LINT_PATH = os.path.join(REPO, "scripts", "rfc_lint.py")

_spec = importlib.util.spec_from_file_location("rfc_lint", LINT_PATH)
rfc_lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rfc_lint)


def good_body(number="0008", title="RFC-0008: 제목", status="Accepted"):
    head = "# %s\n\n## Status\n\n- Status: **%s** (2026-08-05)\n" % (title, status)
    rest = "".join("\n## %s\n\n본문\n" % s
                   for s in rfc_lint.REQUIRED_SECTIONS if s != "Status")
    return head + rest


def clauses(problems):
    return [c for c, _ in problems]


class FilenameAndNumberTest(unittest.TestCase):
    def test_accepts_a_well_formed_document(self):
        self.assertEqual(rfc_lint.check_document("0008-guard-conditions.md",
                                                 good_body()), [])

    def test_rejects_a_filename_without_the_number_prefix(self):
        problems = rfc_lint.check_document("guard-conditions.md", good_body())
        self.assertEqual(clauses(problems), ["§3"])

    def test_rejects_a_non_kebab_slug(self):
        problems = rfc_lint.check_document("0008-Guard_Conditions.md", good_body())
        self.assertEqual(clauses(problems), ["§3"])

    def test_rejects_a_title_number_that_disagrees_with_the_filename(self):
        body = good_body(title="RFC-0009: 제목")
        problems = rfc_lint.check_document("0008-guard-conditions.md", body)
        self.assertIn("§3", clauses(problems))
        self.assertIn("0009", problems[0][1])

    def test_rejects_a_missing_title_line(self):
        body = good_body().replace("# RFC-0008: 제목", "제목만 있고 헤딩이 없다")
        problems = rfc_lint.check_document("0008-guard-conditions.md", body)
        self.assertIn("§3", clauses(problems))


class NumberingTest(unittest.TestCase):
    def test_accepts_a_contiguous_run(self):
        names = ["0000-a.md", "0001-b.md", "0002-c.md"]
        self.assertEqual(rfc_lint.check_numbering(names), [])

    def test_detects_a_duplicate_number(self):
        names = ["0011-a.md", "0011-b.md"]
        problems = rfc_lint.check_numbering(names)
        self.assertEqual(clauses(problems), ["§3"])
        self.assertIn("0011", problems[0][1])

    def test_detects_a_gap(self):
        names = ["0000-a.md", "0002-c.md"]
        problems = rfc_lint.check_numbering(names)
        self.assertIn("0001", problems[0][1])

    def test_ignores_files_that_are_not_rfcs(self):
        self.assertEqual(rfc_lint.check_numbering(["README.md", "notes.md"]), [])

    def test_empty_input_is_not_a_problem(self):
        self.assertEqual(rfc_lint.check_numbering([]), [])


class StatusTest(unittest.TestCase):
    def test_reads_the_list_form(self):
        self.assertEqual(rfc_lint.status_of("- Status: Accepted (2026-07-31)"),
                         "Accepted")

    def test_reads_the_bold_list_form(self):
        self.assertEqual(rfc_lint.status_of("- Status: **Accepted** (RFC-0012)"),
                         "Accepted")

    def test_reads_the_blockquote_form(self):
        # RFC-0000 / RFC-0007이 쓰는 형식.
        self.assertEqual(rfc_lint.status_of("> Status: Superseded (2026-07-31)"),
                         "Superseded")

    def test_skips_a_status_quoted_inside_a_code_fence(self):
        # 프로세스 RFC는 템플릿을 펜스 안에 인용한다. 그것을 자기 상태로 읽으면
        # RFC-0007이 Draft로 오독된다 — 실제로 그렇게 잘못 읽은 적이 있다.
        text = ("> Status: Accepted (2026-08-03)\n"
                "\n```\n# RFC-NNNN: <제목>\n- Status: Draft\n```\n")
        self.assertEqual(rfc_lint.status_of(text), "Accepted")

    def test_returns_none_when_absent(self):
        self.assertIsNone(rfc_lint.status_of("# RFC-0008: 제목\n\n본문\n"))

    def test_flags_a_status_outside_the_vocabulary(self):
        body = good_body(status="Provisional")
        problems = rfc_lint.check_document("0008-guard-conditions.md", body)
        self.assertEqual(clauses(problems), ["§2.1"])

    def test_flags_a_missing_status(self):
        body = good_body().replace("- Status: **Accepted** (2026-08-05)", "")
        problems = rfc_lint.check_document("0008-guard-conditions.md", body)
        self.assertIn("§2.1", clauses(problems))


class TemplateSectionTest(unittest.TestCase):
    def test_flags_missing_sections_by_name(self):
        body = "# RFC-0008: 제목\n\n## Status\n\n- Status: Accepted\n\n## Motivation\n\n본문\n"
        problems = rfc_lint.check_document("0008-guard-conditions.md", body)
        self.assertEqual(clauses(problems), ["§7"])
        self.assertIn("Examples", problems[0][1])
        self.assertIn("Open Questions", problems[0][1])

    def test_extra_sections_are_forbidden(self):
        # §7: "7개 섹션의 이름과 순서는 고정이며 글자 단위로 일치해야 한다
        # (섹션 추가·삭제·개명 금지)". 관측이 아니라 조문이 정본이다 —
        # RFC-0005가 추가 섹션을 가진 것처럼 보이는 것은 그 섹션들이 코드 펜스
        # 안의 예시 문서라서다(issue #11이 RFC-0008의 8번째 섹션을 지적했다).
        body = good_body() + "\n## Implementation Status\n\n본문\n"
        problems = rfc_lint.check_document("0008-guard-conditions.md", body)
        self.assertEqual(clauses(problems), ["§7"])
        self.assertIn("Implementation Status", problems[0][1])

    def test_reports_missing_and_extra_separately(self):
        body = ("# RFC-0008: 제목\n\n## Status\n\n- Status: Accepted\n"
                "\n## Motivation\n\n본문\n\n## 부록 A\n\n본문\n")
        problems = rfc_lint.check_document("0008-guard-conditions.md", body)
        self.assertEqual(len(problems), 2)
        self.assertIn("누락", problems[0][1])
        self.assertIn("템플릿에 없는", problems[1][1])

    def test_flags_sections_that_are_out_of_order(self):
        ordered = list(rfc_lint.REQUIRED_SECTIONS)
        swapped = ordered[:4] + [ordered[5], ordered[4]] + ordered[6:]
        problems = rfc_lint.check_sections(swapped)
        self.assertEqual(clauses(problems), ["§7"])
        self.assertIn("순서", problems[0][1])

    def test_correct_order_is_clean(self):
        self.assertEqual(rfc_lint.check_sections(list(rfc_lint.REQUIRED_SECTIONS)), [])

    def test_order_is_not_reported_while_sections_are_missing(self):
        # 누락이 있는데 순서까지 지적하면 소음이다.
        problems = rfc_lint.check_sections(["Motivation", "Status"])
        self.assertEqual(len(problems), 1)
        self.assertIn("누락", problems[0][1])

    def test_process_rfcs_are_exempt(self):
        # RFC-0007 §1의 프로세스 RFC 면제. 7섹션이 없어도 문제가 아니다.
        body = "# RFC-0007: RFC Process v2\n\n> Status: Accepted\n\n## 1. 목적\n\n본문\n"
        self.assertEqual(rfc_lint.check_document("0007-rfc-process-v2.md", body), [])

    def test_a_non_process_rfc_is_not_exempt(self):
        body = "# RFC-0008: 제목\n\n> Status: Accepted\n\n## 1. 목적\n\n본문\n"
        problems = rfc_lint.check_document("0008-guard-conditions.md", body)
        self.assertIn("§7", clauses(problems))

    def test_sections_inside_a_code_fence_do_not_count(self):
        # 템플릿을 인용했다고 그 섹션을 가진 것으로 치면 안 된다.
        body = ("# RFC-0008: 제목\n\n> Status: Accepted\n\n"
                "```\n## Motivation\n## Examples\n## Alternatives\n```\n")
        problems = rfc_lint.check_document("0008-guard-conditions.md", body)
        self.assertIn("§7", clauses(problems))
        self.assertIn("Motivation", problems[0][1])


class SectionScanBoundaryTest(unittest.TestCase):
    def test_empty_text_has_no_sections(self):
        self.assertEqual(rfc_lint.sections(""), [])

    def test_h1_and_h3_are_not_sections(self):
        self.assertEqual(rfc_lint.sections("# 제목\n### 소절\n"), [])

    def test_strips_the_heading_marker(self):
        self.assertEqual(rfc_lint.sections("## Motivation\n"), ["Motivation"])


if __name__ == "__main__":
    unittest.main()
