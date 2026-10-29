"""`scripts/rfc_lint.py`의 검사 로직 — 대부분 합성 입력으로 검증한다.

이 파일은 대부분 **레포의 RFC가 깨끗한지 묻지 않는다** — 그것은 CI가
`python scripts/rfc_lint.py`를 blocking 단계로 돌려 게이트한다.

실제 파일을 읽는 테스트도 있다: `BackLinkRealTreeTest`가 실제 rfcs/에 §2.2 역링크
검사를 돌려 0건을 요구하고(issue #263 — 승격 때 손으로 다는 역링크가 표류했다),
`Rule7RealTreeTest`가 규칙 7(한 절을 읽으려고 여는 문서 수)을 실제 rfcs/에 돌려
0건을 요구하고(issue #268), `RosterPinTest`가 docs/CI-GATES.md의 rfc_lint 행이
main()이 부르는 검사마다 표기를 지니는지 대조한다(issue #268 §3).

검사하는 것은 린터가 **옳게 판정하는가**다. 도구가 틀리면 그것을 믿고 내린
판단이 전부 틀어지므로, 규칙마다 통과 케이스와 위반 케이스를 함께 둔다.
"""
import contextlib
import importlib.util
import inspect
import io
import os
import re
import tempfile
import types
import unicodedata
import unittest
from unittest import mock

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


class ChangelogCitationTest(unittest.TestCase):
    """CHANGELOG.md가 인용한 RFC는 Accepted 또는 Superseded여야 한다(issue #249)."""

    def test_an_accepted_citation_is_clean(self):
        self.assertEqual(rfc_lint.check_changelog_citations(
            "- Fixed (issue #215, RFC-0064).\n", {"0064": "Accepted"}), [])

    def test_a_superseded_citation_is_clean(self):
        self.assertEqual(rfc_lint.check_changelog_citations(
            "RFC-0000", {"0000": "Superseded"}), [])

    def test_flags_a_draft_citation(self):
        problems = rfc_lint.check_changelog_citations(
            "(issue #215, RFC-0064)", {"0064": "Draft"})
        self.assertEqual(clauses(problems), ["§2.1"])
        self.assertIn("RFC-0064", problems[0][1])
        self.assertIn("Draft", problems[0][1])

    def test_flags_a_review_citation(self):
        problems = rfc_lint.check_changelog_citations(
            "RFC-0064", {"0064": "Review"})
        self.assertEqual(clauses(problems), ["§2.1"])
        self.assertIn("Review", problems[0][1])

    def test_flags_a_citation_whose_document_has_no_status(self):
        problems = rfc_lint.check_changelog_citations("RFC-0064", {"0064": None})
        self.assertEqual(clauses(problems), ["§2.1"])
        self.assertIn("(없음)", problems[0][1])

    def test_text_without_a_citation_is_clean(self):
        self.assertEqual(rfc_lint.check_changelog_citations(
            "- Fixed a typo.\n", {"0008": "Accepted"}), [])

    def test_empty_text_is_clean(self):
        self.assertEqual(rfc_lint.check_changelog_citations("", {}), [])

    def test_flags_a_dangling_citation(self):
        problems = rfc_lint.check_changelog_citations(
            "see RFC-0099", {"0008": "Accepted"})
        self.assertEqual(clauses(problems), ["§3"])
        self.assertIn("0099", problems[0][1])

    def test_a_repeated_citation_is_reported_once(self):
        problems = rfc_lint.check_changelog_citations(
            "RFC-0049 ... RFC-0049", {"0049": "Draft"})
        self.assertEqual(len(problems), 1)

    def test_findings_follow_number_order(self):
        problems = rfc_lint.check_changelog_citations(
            "RFC-0050 then RFC-0049", {"0049": "Draft", "0050": "Draft"})
        self.assertEqual(len(problems), 2)
        self.assertIn("RFC-0049", problems[0][1])
        self.assertIn("RFC-0050", problems[1][1])

    def test_a_five_digit_token_is_not_a_citation(self):
        self.assertEqual(rfc_lint.check_changelog_citations("RFC-00490", {}), [])

    def test_the_second_number_of_a_slash_pair_is_checked(self):
        # CHANGELOG.md의 `The RFC-0044/0045 designs` 꼴 — 둘째 번호가 숨으면 안 된다.
        problems = rfc_lint.check_changelog_citations(
            "The RFC-0044/0045 designs", {"0044": "Accepted", "0045": "Draft"})
        self.assertEqual(clauses(problems), ["§2.1"])
        self.assertIn("RFC-0045", problems[0][1])

    def test_a_missing_changelog_file_is_its_own_finding(self):
        missing = os.path.join(REPO, "rfcs", "NO-SUCH-CHANGELOG.md")
        problems = rfc_lint.check_changelog_file(missing, {"0008": "Accepted"})
        self.assertEqual(clauses(problems), ["§2.1"])
        self.assertIn("없다", problems[0][1])


class StatusCollectionTest(unittest.TestCase):
    def test_maps_a_well_formed_name_to_its_status(self):
        self.assertEqual(
            rfc_lint.collect_statuses(
                [("0008-guard-conditions.md", good_body(status="Draft"))]),
            {"0008": "Draft"})

    def test_skips_a_malformed_name(self):
        # 형식 밖 파일명은 check_document가 §3으로 보고한다 — 여기서는 건너뛸 뿐이다.
        self.assertEqual(
            rfc_lint.collect_statuses(
                [("notes.md", good_body()), ("0008-guard-conditions.md", good_body())]),
            {"0008": "Accepted"})


def doc(number, status="Accepted", header=""):
    """good_body 문서의 Status 줄 바로 뒤에 머리 줄(`header`)을 끼운다."""
    body = good_body(number=number, title="RFC-%s: 제목" % number, status=status)
    return body.replace("(2026-08-05)\n", "(2026-08-05)\n" + header, 1)


class BackLinkTest(unittest.TestCase):
    """§2.2: Accepted RFC의 `Updates:` 대상마다 `Updated-by: RFC-<갱신>`이 있어야 한다."""

    def test_flags_a_target_without_the_back_link(self):
        problems = rfc_lint.check_back_links([
            ("0002-syntax.md", doc("0002")),
            ("0008-guard-conditions.md",
             doc("0008", header="- Updates: RFC-0002 §Full grammar\n"))])
        self.assertEqual(len(problems), 1)
        where, clause, msg = problems[0]
        self.assertEqual((where, clause), ("0002-syntax.md", "§2.2"))
        self.assertIn("RFC-0008", msg)
        self.assertIn("RFC-0002", msg)

    def test_accepts_a_present_back_link(self):
        self.assertEqual(rfc_lint.check_back_links([
            ("0002-syntax.md",
             doc("0002", header="- Updated-by: RFC-0008 (§Full grammar)\n")),
            ("0008-guard-conditions.md",
             doc("0008", header="- Updates: RFC-0002 §Full grammar\n"))]), [])

    def test_skips_a_draft_updater(self):
        self.assertEqual(rfc_lint.check_back_links([
            ("0002-syntax.md", doc("0002")),
            ("0008-guard-conditions.md",
             doc("0008", status="Draft", header="- Updates: RFC-0002 §Full grammar\n"))]), [])

    def test_skips_a_review_updater(self):
        self.assertEqual(rfc_lint.check_back_links([
            ("0002-syntax.md", doc("0002")),
            ("0008-guard-conditions.md",
             doc("0008", status="Review", header="- Updates: RFC-0002 §Full grammar\n"))]), [])

    def test_skips_a_superseded_updater(self):
        self.assertEqual(rfc_lint.check_back_links([
            ("0002-syntax.md", doc("0002")),
            ("0008-guard-conditions.md",
             doc("0008", status="Superseded", header="- Updates: RFC-0002 §Full grammar\n"))]), [])

    def test_a_parenthesised_predecessor_is_not_a_target(self):
        self.assertEqual(rfc_lint.check_back_links([
            ("0002-syntax.md",
             doc("0002", header="- Updated-by: RFC-0060 (§Full grammar)\n")),
            ("0049-emit-payload-mapping.md", doc("0049")),
            ("0060-assigned-field-guard.md",
             doc("0060", header="- Updates: RFC-0002 §Full grammar (+RFC-0049)\n"))]), [])

    def test_the_target_outside_the_parentheses_is_still_checked(self):
        problems = rfc_lint.check_back_links([
            ("0002-syntax.md", doc("0002")),
            ("0049-emit-payload-mapping.md", doc("0049")),
            ("0060-assigned-field-guard.md",
             doc("0060", header="- Updates: RFC-0002 §Full grammar (+RFC-0049)\n"))])
        self.assertEqual([p[0] for p in problems], ["0002-syntax.md"])

    def test_reads_targets_on_continuation_lines(self):
        problems = rfc_lint.check_back_links([
            ("0002-syntax.md",
             doc("0002", header="- Updated-by: RFC-0028 (§Full grammar)\n")),
            ("0014-guard-skip-observability.md", doc("0014")),
            ("0028-arith.md", doc("0028", header=(
                "- Updates: RFC-0002 §Full grammar,\n"
                "  RFC-0014 §Reference-level Specification/2\n")))])
        self.assertEqual([p[0] for p in problems], ["0014-guard-skip-observability.md"])

    def test_reads_a_back_link_on_a_continuation_line(self):
        self.assertEqual(rfc_lint.check_back_links([
            ("0024-line.md", doc("0024", header=(
                "- Updated-by: RFC-0001 (§집행 진단의\n"
                "  `line`), RFC-0026 (§Examples)\n"))),
            ("0026-enforce.md",
             doc("0026", header="- Updates: RFC-0024 §Reference-level Specification/5\n"))]), [])

    def test_a_blank_line_ends_the_entry(self):
        self.assertEqual(rfc_lint.update_targets("0008", doc("0008", header=(
            "- Updates: RFC-0002 §Full grammar\n\nRFC-0014는 본문 산문이다.\n"))), {"0002"})

    def test_a_list_item_or_pointer_line_ends_the_entry(self):
        self.assertEqual(rfc_lint.update_targets("0008", doc("0008", header=(
            "- Updates: RFC-0002 §Full grammar\n- Note: RFC-0014는 목록 항목이다\n"))), {"0002"})
        self.assertEqual(rfc_lint.update_targets("0008", doc("0008", header=(
            "- Updates: RFC-0002 §Full grammar\n> 갱신됨: RFC-0014\n"))), {"0002"})

    def test_a_five_digit_number_is_not_an_rfc_reference(self):
        self.assertEqual(rfc_lint.update_targets("0008", doc("0008", header=(
            "- Updates: RFC-00149 §x, RFC-0002 §Full grammar\n"))), {"0002"})

    def test_an_entry_starting_with_none_has_no_targets(self):
        self.assertEqual(rfc_lint.update_targets("0064", doc("0064", header=(
            "- Updates: 없음 — RFC-0012 §G12.2와 RFC-0025를 참조만 한다\n"))), set())

    def test_an_entry_inside_a_code_fence_is_ignored(self):
        self.assertEqual(rfc_lint.update_targets("0007", doc("0007", header=(
            "```markdown\n- Updates: RFC-0002 §Full grammar\n```\n"))), set())

    def test_the_rfcs_own_number_is_not_a_target(self):
        self.assertEqual(rfc_lint.update_targets("0031", doc("0031", header=(
            "- Updates: RFC-0004 §파이프라인 — RFC-0031 자신의 범위는 이 행뿐이다\n"))), {"0004"})

    def test_a_prose_mention_is_not_a_back_link(self):
        problems = rfc_lint.check_back_links([
            ("0002-syntax.md", doc("0002", header=(
                "  `Updated-by: RFC-0008`는 아직 달지 않았다.\n"))),
            ("0008-guard-conditions.md",
             doc("0008", header="- Updates: RFC-0002 §Full grammar\n"))])
        self.assertEqual([p[0] for p in problems], ["0002-syntax.md"])

    def test_flags_a_target_without_a_document(self):
        problems = rfc_lint.check_back_links([
            ("0008-guard-conditions.md",
             doc("0008", header="- Updates: RFC-0099 §Full grammar\n"))])
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0][0], "0008-guard-conditions.md")
        self.assertIn("RFC-0099", problems[0][2])

    def test_empty_input_has_no_findings(self):
        self.assertEqual(rfc_lint.check_back_links([]), [])

    def test_findings_follow_target_then_updater_order(self):
        problems = rfc_lint.check_back_links([
            ("0001-semantic-ir.md", doc("0001")),
            ("0002-syntax.md", doc("0002")),
            ("0015-value.md", doc("0015", header="- Updates: RFC-0002 §a, RFC-0001 §b\n")),
            ("0016-time.md", doc("0016", header="- Updates: RFC-0001 §b\n"))])
        self.assertEqual([(p[0], p[2][:8]) for p in problems],
                         [("0001-semantic-ir.md", "RFC-0015"),
                          ("0001-semantic-ir.md", "RFC-0016"),
                          ("0002-syntax.md", "RFC-0015")])


class HeaderStatusScopeTest(unittest.TestCase):
    """`header_entries`는 `## Status` 절만 읽는다(issue #268 §3)."""

    def test_an_entry_inside_status_is_read(self):
        self.assertEqual(rfc_lint.update_targets("0008", doc("0008", header=(
            "- Updates: RFC-0002 §x\n"))), {"0002"})

    def test_an_entry_outside_status_is_ignored(self):
        text = doc("0008").replace(
            "## Motivation\n\n본문\n", "## Motivation\n\n- Updates: RFC-0002 §x\n", 1)
        self.assertIn("- Updates: RFC-0002 §x", text)
        self.assertEqual(rfc_lint.update_targets("0008", text), set())

    def test_a_status_heading_inside_a_fence_opens_nothing(self):
        text = ("# RFC-0008: 제목\n\n```markdown\n## Status\n```\n"
                "- Updates: RFC-0002 §x\n")
        self.assertEqual(rfc_lint.header_entries(text, "Updates"), [])

    def test_a_document_without_a_status_section_has_no_entries(self):
        text = "# RFC-0007: 제목\n\n> Status: Accepted\n\n- Updates: RFC-0002 §x\n"
        self.assertEqual(rfc_lint.header_entries(text, "Updates"), [])

    def test_the_status_section_stops_at_the_next_heading(self):
        section = rfc_lint.status_section(doc("0008", header="- Updates: RFC-0002 §x\n"))
        self.assertIn("- Updates: RFC-0002 §x", section)
        self.assertNotIn("## Motivation", section)
        self.assertNotIn("본문", section)

    def test_empty_text_has_an_empty_status_section(self):
        self.assertEqual(rfc_lint.status_section(""), "")


class UpdateTargetsEmptyValueTest(unittest.TestCase):
    """`Updates:` 빈 값 철자(issue #268 §3) — 철자마다 하나, 그리고 빈 값이 아닌 것들."""

    SPELLINGS = ("없음", "**없음**", "_없음_", "`없음`", "(없음)", "해당 없음",
                 "none", "None", "N/A", "n/a")

    def targets(self, value):
        return rfc_lint.update_targets("0064", doc("0064", header="- Updates: %s\n" % value))

    def test_each_empty_spelling_has_no_targets(self):
        for spelling in self.SPELLINGS:
            with self.subTest(spelling=spelling):
                self.assertEqual(self.targets(spelling + " — RFC-0012 §G12.2를 참조만 한다"), set())

    def test_a_bare_empty_word_has_no_targets(self):
        self.assertEqual(self.targets("없음"), set())

    def test_a_decomposed_empty_word_is_still_empty(self):
        self.assertEqual(self.targets(unicodedata.normalize("NFD", "없음") + " — RFC-0012"), set())

    def test_a_real_target_still_parses(self):
        self.assertEqual(self.targets("RFC-0002 §Full grammar"), {"0002"})

    def test_a_word_that_only_starts_like_an_empty_word_is_not_empty(self):
        for value in ("없음없는 RFC-0012", "Nonexistent RFC-0012", "none-such RFC-0012",
                      "— RFC-0012", "없다 — RFC-0012"):
            with self.subTest(value=value):
                self.assertEqual(self.targets(value), {"0012"})


class Rule7SectionKeyTest(unittest.TestCase):
    """규칙 7의 절 키 — 갱신 RFC마다 다른 철자를 한 절로 모은다."""

    def test_the_long_and_short_spellings_share_a_key(self):
        self.assertEqual(rfc_lint.section_key("§G12.2"), "G12.2")
        self.assertEqual(rfc_lint.section_key("§Reference-level Specification/G12.2"), "G12.2")

    def test_a_numbered_title_reduces_to_its_number(self):
        for name, key in (("§Reference-level Specification/3", "3"),
                          ("§Reference-level Specification/3. 피연산자의 차원 규칙", "3"),
                          ("§2.1 `when` 모드", "2.1"),
                          ("§1 — `NetworkDriver` 계약", "1")):
            with self.subTest(name=name):
                self.assertEqual(rfc_lint.section_key(name), key)

    def test_a_name_without_a_leading_number_is_kept(self):
        self.assertEqual(rfc_lint.section_key("§노드 카탈로그/Guard"), "노드 카탈로그/Guard")
        self.assertEqual(rfc_lint.section_key("§Examples/5.2 Guarded Workflow"),
                         "Examples/5.2 Guarded Workflow")

    def test_a_decomposed_name_equals_the_composed_one(self):
        self.assertEqual(rfc_lint.section_key(unicodedata.normalize("NFD", "§코드 → 등급 (정본)")),
                         "코드 → 등급 (정본)")

    def test_an_empty_name_gives_an_empty_key(self):
        self.assertEqual(rfc_lint.section_key(""), "")
        self.assertEqual(rfc_lint.section_key("§"), "")


class Rule7SectionTest(unittest.TestCase):
    """`updated_sections` — `Updated-by:` 묶음을 (갱신, 절 키)로 나눈다."""

    def sections(self, header):
        return rfc_lint.updated_sections(doc("0003", header=header))

    def test_one_group_can_name_several_sections(self):
        self.assertEqual(self.sections(
            "- Updated-by: RFC-0032 (§Execution Model/§Policy Enforcement/§Examples)\n"),
            [("0032", "Execution Model"), ("0032", "Policy Enforcement"), ("0032", "Examples")])

    def test_a_middle_dot_and_a_comma_separate_sections(self):
        self.assertEqual(self.sections(
            "- Updated-by: RFC-0022 (§2.5·§2.6), RFC-0025 (§G12.2, §G12.4)\n"),
            [("0022", "2.5"), ("0022", "2.6"), ("0025", "G12.2"), ("0025", "G12.4")])

    def test_parentheses_inside_a_name_stay_in_the_name(self):
        self.assertEqual(self.sections(
            "- Updated-by: RFC-0022 (§코드 → 등급 (정본)), "
            "RFC-0042 (§Reference-level Specification/코드 → 등급 (정본))\n"),
            [("0022", "코드 → 등급 (정본)"), ("0042", "코드 → 등급 (정본)")])

    def test_a_slash_path_and_a_plain_comma_do_not_split(self):
        self.assertEqual(self.sections(
            "- Updated-by: RFC-0028 (§노드 카탈로그/Guard), "
            "RFC-0031 (§Reference-level Specification > 파이프라인 표, S1 행)\n"),
            [("0028", "노드 카탈로그/Guard"),
             ("0031", "Reference-level Specification > 파이프라인 표, S1 행")])

    def test_a_continuation_line_is_joined(self):
        self.assertEqual(self.sections(
            "- Updated-by: RFC-0026 (§Reference-level Specification/3. 집행 진단 3종의\n"
            "  `line`), RFC-0026 (§Examples/바뀌지 않는다)\n"),
            [("0026", "3"), ("0026", "Examples/바뀌지 않는다")])

    def test_a_reference_without_a_group_has_no_section(self):
        self.assertEqual(self.sections("- Updated-by: RFC-0049\n"), [("0049", None)])

    def test_no_updated_by_line_gives_nothing(self):
        self.assertEqual(self.sections(""), [])


THREE_UPDATERS = ("- Updated-by: RFC-0008 (§Full grammar)\n"
                  "- Updated-by: RFC-0012 (§Full grammar)\n")


def rule7_tree(header=THREE_UPDATERS, target="Accepted", first="Accepted", second="Accepted"):
    """대상 RFC-0002와 갱신 RFC-0008·RFC-0012의 (파일명, 본문) 목록."""
    return [("0002-syntax.md", doc("0002", status=target, header=header)),
            ("0008-guard-conditions.md", doc("0008", status=first)),
            ("0012-execution-scope.md", doc("0012", status=second))]


class Rule7CheckTest(unittest.TestCase):
    """§2.2 규칙 7: 한 절을 읽으려고 여는 문서가 2개를 넘으면 위반이다(issue #268)."""

    def test_three_documents_are_one_violation(self):
        self.assertEqual(rfc_lint.rule7_violations(rule7_tree()),
                         [("0002", "Full grammar", 3, ("0008", "0012"))])

    def test_two_documents_are_clean(self):
        self.assertEqual(rfc_lint.rule7_check(rule7_tree(
            header="- Updated-by: RFC-0008 (§Full grammar)\n")), [])

    def test_the_finding_names_target_section_count_and_updaters(self):
        problems = rfc_lint.rule7_check(rule7_tree())
        self.assertEqual(len(problems), 1)
        where, clause, msg = problems[0]
        self.assertEqual((where, clause), ("0002-syntax.md", "§2.2"))
        for part in ("RFC-0002", "§Full grammar", "문서 3개", "RFC-0008", "RFC-0012"):
            self.assertIn(part, msg)

    def test_an_updater_that_is_not_accepted_is_not_counted(self):
        for status in ("Draft", "Review", "Superseded"):
            with self.subTest(status=status):
                self.assertEqual(rfc_lint.rule7_check(rule7_tree(second=status)), [])

    def test_a_target_that_is_not_accepted_is_not_checked(self):
        for status in ("Superseded", "Draft"):
            with self.subTest(status=status):
                self.assertEqual(rfc_lint.rule7_check(rule7_tree(target=status)), [])

    def test_an_updater_without_a_document_is_not_counted(self):
        self.assertEqual(rfc_lint.rule7_check(rule7_tree()[:2]), [])

    def test_a_self_reference_is_not_counted(self):
        self.assertEqual(rfc_lint.rule7_check(rule7_tree(
            header=THREE_UPDATERS.replace("RFC-0012", "RFC-0002"))), [])

    def test_a_repeated_updater_counts_once(self):
        self.assertEqual(rfc_lint.rule7_check(rule7_tree(
            header=THREE_UPDATERS.replace("RFC-0012", "RFC-0008"))), [])

    def test_the_target_header_decides_the_section(self):
        # 갱신의 `Updates:`가 같은 절을 지목해도 대상 머리가 다른 절이라 하면 머리를 따른다.
        named = [("0002-syntax.md", doc("0002", header=(
                    "- Updated-by: RFC-0008 (§Full grammar)\n"
                    "- Updated-by: RFC-0012 (§Block structure)\n"))),
                 ("0008-guard-conditions.md",
                  doc("0008", header="- Updates: RFC-0002 §Full grammar\n")),
                 ("0012-execution-scope.md",
                  doc("0012", header="- Updates: RFC-0002 §Full grammar\n"))]
        self.assertEqual(rfc_lint.rule7_violations(named), [])

    def test_a_parent_number_counts_for_its_child(self):
        named = [("0014-guard-skip-observability.md", doc("0014", header=(
                    "- Updated-by: RFC-0028 (§Reference-level Specification/2)\n"
                    "- Updated-by: RFC-0060 (§2.1 `when` 모드)\n"))),
                 ("0028-arith.md", doc("0028")),
                 ("0060-assigned-field-guard.md", doc("0060"))]
        self.assertEqual(rfc_lint.rule7_violations(named),
                         [("0014", "2.1", 3, ("0028", "0060"))])

    def test_a_whole_section_does_not_count_for_a_slash_part(self):
        named = [("0001-semantic-ir.md", doc("0001", header=(
                    "- Updated-by: RFC-0015 (§노드 카탈로그)\n"
                    "- Updated-by: RFC-0028 (§노드 카탈로그/Guard)\n"))),
                 ("0015-value.md", doc("0015")),
                 ("0028-arith.md", doc("0028"))]
        self.assertEqual(rfc_lint.rule7_violations(named), [])

    def test_a_reference_without_a_group_is_its_own_finding(self):
        named = [("0002-syntax.md", doc("0002", header="- Updated-by: RFC-0049\n")),
                 ("0049-emit-payload-mapping.md", doc("0049"))]
        self.assertEqual(rfc_lint.rule7_violations(named), [])
        self.assertEqual(rfc_lint.ungrouped_updaters(named), [("0002", "0049")])
        problems = rfc_lint.rule7_check(named)
        self.assertEqual([(p[0], p[1]) for p in problems], [("0002-syntax.md", "§2.2")])
        self.assertIn("RFC-0049", problems[0][2])
        self.assertIn("(§…)", problems[0][2])

    def test_a_draft_reference_without_a_group_is_skipped(self):
        named = [("0002-syntax.md", doc("0002", header="- Updated-by: RFC-0049\n")),
                 ("0049-emit-payload-mapping.md", doc("0049", status="Draft"))]
        self.assertEqual(rfc_lint.ungrouped_updaters(named), [])

    def test_findings_follow_target_then_section_order(self):
        named = [("0003-runtime.md", doc("0003", header=(
                    "- Updated-by: RFC-0008 (§Guard)\n- Updated-by: RFC-0012 (§Guard)\n"))),
                 ("0002-syntax.md", doc("0002", header=(
                    THREE_UPDATERS + "- Updated-by: RFC-0049\n"
                    "- Updated-by: RFC-0008 (§Block structure)\n"
                    "- Updated-by: RFC-0012 (§Block structure)\n"))),
                 ("0008-guard-conditions.md", doc("0008")),
                 ("0012-execution-scope.md", doc("0012")),
                 ("0049-emit-payload-mapping.md", doc("0049"))]
        self.assertEqual([(p[0], p[2][:p[2].index(":")]) for p in rfc_lint.rule7_check(named)],
                         [("0002-syntax.md", "RFC-0002 §Block structure"),
                          ("0002-syntax.md", "RFC-0002 §Full grammar"),
                          ("0002-syntax.md", "RFC-0002 머리의 `Updated-by"),
                          ("0003-runtime.md", "RFC-0003 §Guard")])

    def test_a_tree_with_at_most_two_documents_per_section_is_clean(self):
        named = [("0002-syntax.md", doc("0002", header=(
                    "- Updated-by: RFC-0008 (§Full grammar)\n"
                    "- Updated-by: RFC-0012 (§Block structure)\n"))),
                 ("0003-runtime.md", doc("0003", header=(
                    "- Updated-by: RFC-0008 (§Guard)\n"
                    "- Updated-by: RFC-0012 (§Policy Enforcement)\n"))),
                 ("0008-guard-conditions.md", doc("0008")),
                 ("0012-execution-scope.md", doc("0012"))]
        self.assertEqual(rfc_lint.rule7_check(named), [])

    def test_empty_input_has_no_findings(self):
        self.assertEqual(rfc_lint.rule7_violations([]), [])
        self.assertEqual(rfc_lint.ungrouped_updaters([]), [])
        self.assertEqual(rfc_lint.rule7_check([]), [])


def real_rfcs():
    """실제 rfcs/의 (파일명, 본문) 목록."""
    names = sorted(n for n in os.listdir(rfc_lint.RFC_DIR) if n.endswith(".md"))
    out = []
    for name in names:
        with open(os.path.join(rfc_lint.RFC_DIR, name), encoding="utf-8") as fh:
            out.append((name, fh.read()))
    return out


class BackLinkRealTreeTest(unittest.TestCase):
    """known-good: 실제 rfcs/는 §2.2 역링크 누락이 0건이어야 한다(issue #263)."""

    def test_the_sweep_selects_real_updates(self):
        texts = dict(real_rfcs())
        self.assertEqual(
            rfc_lint.update_targets("0062", texts["0062-cached-read-through-clause.md"]),
            {"0002", "0003"})

    def test_every_accepted_update_has_its_back_link(self):
        self.assertEqual(rfc_lint.check_back_links(real_rfcs()), [])

    def test_removing_one_real_back_link_reddens_the_check(self):
        named = real_rfcs()
        prefix = "- Updated-by: RFC-0047 ("
        mutated = []
        for name, text in named:
            if name == "0045-rowset-aggregation-extension.md":
                mutant = "".join(line for line in text.splitlines(keepends=True)
                                 if not line.startswith(prefix))
                self.assertNotEqual(mutant, text, "the mutation did not apply")
                text = mutant
            mutated.append((name, text))
        problems = rfc_lint.check_back_links(mutated)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0][0], "0045-rowset-aggregation-extension.md")
        self.assertIn("RFC-0047", problems[0][2])


class Rule7RealTreeTest(unittest.TestCase):
    """known-good: 실제 rfcs/는 규칙 7 위반이 0건이어야 한다(issue #268)."""

    def test_no_accepted_section_needs_more_than_two_documents(self):
        self.assertEqual(rfc_lint.rule7_check(real_rfcs()), [])

    def test_one_more_updater_on_a_real_section_reddens_the_check(self):
        prefix = "- Updated-by: RFC-0047 ("
        added = "- Updated-by: RFC-0066 (§1)\n"
        mutated = []
        for name, text in real_rfcs():
            if name == "0045-rowset-aggregation-extension.md":
                mutant = "".join(line + added if line.startswith(prefix) else line
                                 for line in text.splitlines(keepends=True))
                self.assertNotEqual(mutant, text, "the mutation did not apply")
                text = mutant
            mutated.append((name, text))
        problems = rfc_lint.rule7_check(mutated)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0][:2], ("0045-rowset-aggregation-extension.md", "§2.2"))
        for part in ("RFC-0045 §1", "문서 3개", "RFC-0047", "RFC-0066"):
            self.assertIn(part, problems[0][2])


CI_GATES_PATH = os.path.join(REPO, "docs", "CI-GATES.md")
ROSTER_ROW_NAME = "RFC lint(`rfc_lint.py`)"
# main()이 부르지만 발견을 내지 않는 도우미 — 로스터에 표기가 없다.
MAIN_HELPERS = {"status_of", "collect_statuses"}


def table_cells(line):
    """마크다운 표 한 줄의 칸 목록. 이스케이프된 `\\|`는 칸 안의 글자다."""
    row = re.sub(r"(?<!\\)\|$", "", re.sub(r"^\|", "", line.strip()))
    return [cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", row)]


def roster_cells(path):
    """CI-GATES.md에서 첫 칸이 RFC lint인 행마다 마지막 칸."""
    with open(path, encoding="utf-8") as fh:
        rows = [table_cells(line) for line in fh if line.startswith("|")]
    return [cells[-1] for cells in rows if cells[0] == ROSTER_ROW_NAME]


def missing_roster_tokens(cell):
    """칸에 없는 (검사 함수, 표기) 목록, 함수 이름 순."""
    return [(check, token) for check, tokens in sorted(rfc_lint.ROSTER_TOKENS.items())
            for token in tokens if token not in cell]


def functions_main_calls():
    """main()의 코드(안쪽 컴프리헨션·제너레이터 포함)가 이름으로 부르는 모듈 함수."""
    def names(code):
        found = set(code.co_names)
        for const in code.co_consts:
            if isinstance(const, types.CodeType):
                found |= names(const)
        return found
    return {name for name in names(rfc_lint.main.__code__)
            if inspect.isfunction(getattr(rfc_lint, name, None))}


class RosterPinTest(unittest.TestCase):
    """docs/CI-GATES.md의 rfc_lint 행이 main()이 부르는 검사마다 표기를 지니는가(issue #268 §3)."""

    def test_the_row_appears_exactly_once(self):
        self.assertEqual(len(roster_cells(CI_GATES_PATH)), 1)

    def test_the_row_carries_a_token_for_every_check(self):
        cells = roster_cells(CI_GATES_PATH)
        self.assertEqual(len(cells), 1)
        self.assertEqual(missing_roster_tokens(cells[0]), [])

    def test_main_runs_exactly_the_rostered_checks(self):
        self.assertEqual(functions_main_calls() - MAIN_HELPERS, set(rfc_lint.ROSTER_TOKENS))

    def test_a_dropped_token_is_reported(self):
        cell = roster_cells(CI_GATES_PATH)[0]
        token = "§2.2 `Updated-by:` 역링크"
        mutant = cell.replace(token, "")
        self.assertNotEqual(mutant, cell, "the mutation did not apply")
        self.assertEqual(missing_roster_tokens(mutant), [("check_back_links", token)])

    def test_an_empty_cell_misses_every_token(self):
        self.assertEqual(len(missing_roster_tokens("")),
                         sum(len(tokens) for tokens in rfc_lint.ROSTER_TOKENS.values()))


TMP_PARENT = os.path.join(REPO, ".claude", "tmp")
CATALOGUE_UPDATES = "- Updates: RFC-0001 §노드 카탈로그\n"


class MainWiringTest(unittest.TestCase):
    """main()이 인용 검사를 실제로 부르는가 — 합성 rfcs/와 CHANGELOG.md로 돌린다."""

    def run_main(self, files, changelog):
        os.makedirs(TMP_PARENT, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=TMP_PARENT) as root:
            rfcs = os.path.join(root, "rfcs")
            os.makedirs(rfcs)
            for name, text in files.items():
                with open(os.path.join(rfcs, name), "w", encoding="utf-8") as fh:
                    fh.write(text)
            log = os.path.join(root, "CHANGELOG.md")
            with open(log, "w", encoding="utf-8") as fh:
                fh.write(changelog)
            out = io.StringIO()
            with mock.patch.object(rfc_lint, "RFC_DIR", rfcs), \
                    mock.patch.object(rfc_lint, "CHANGELOG_PATH", log), \
                    contextlib.redirect_stdout(out):
                rc = rfc_lint.main([])
        return rc, out.getvalue()

    def test_main_fails_on_a_draft_citation(self):
        rc, out = self.run_main(
            {"0008-guard-conditions.md": good_body(status="Draft")},
            "- Changed (issue #1, RFC-0008).\n")
        self.assertEqual(rc, 1)
        self.assertIn("RFC-0008", out)
        self.assertIn("Draft", out)

    def test_main_passes_on_an_accepted_citation(self):
        rc, out = self.run_main(
            {"0008-guard-conditions.md": good_body()},
            "- Changed (issue #1, RFC-0008).\n")
        self.assertEqual(rc, 0)
        self.assertIn("문제 없음.", out)

    def test_main_reports_a_malformed_rfc_filename_as_a_finding(self):
        rc, out = self.run_main(
            {"0008-guard-conditions.md": good_body(), "notes.md": "메모\n"},
            "- Changed (issue #1, RFC-0008).\n")
        self.assertEqual(rc, 1)
        self.assertIn("notes.md", out)
        self.assertIn("§3", out)

    def test_main_fails_on_a_missing_back_link(self):
        rc, out = self.run_main(
            {"0001-semantic-ir.md": doc("0001"),
             "0002-syntax.md": doc("0002", header="- Updates: RFC-0001 §노드 카탈로그\n")},
            "- Changed (issue #1, RFC-0001).\n")
        self.assertEqual(rc, 1)
        self.assertIn("§2.2", out)
        self.assertIn("RFC-0002", out)

    def test_main_passes_when_the_back_link_is_present(self):
        rc, out = self.run_main(
            {"0001-semantic-ir.md": doc("0001", header="- Updated-by: RFC-0002 (§노드 카탈로그)\n"),
             "0002-syntax.md": doc("0002", header="- Updates: RFC-0001 §노드 카탈로그\n")},
            "- Changed (issue #1, RFC-0001).\n")
        self.assertEqual(rc, 0)
        self.assertIn("문제 없음.", out)

    def test_main_fails_when_a_section_needs_three_documents(self):
        rc, out = self.run_main(
            {"0001-semantic-ir.md": doc("0001", header=(
                "- Updated-by: RFC-0002 (§노드 카탈로그)\n"
                "- Updated-by: RFC-0003 (§노드 카탈로그)\n")),
             "0002-syntax.md": doc("0002", header=CATALOGUE_UPDATES),
             "0003-runtime.md": doc("0003", header=CATALOGUE_UPDATES)},
            "- Changed (issue #1, RFC-0001).\n")
        self.assertEqual(rc, 1)
        self.assertIn("RFC-0001 §노드 카탈로그", out)
        self.assertIn("문서 3개", out)
        self.assertIn("1 problem(s)", out)

    def test_main_passes_when_a_section_needs_two_documents(self):
        rc, out = self.run_main(
            {"0001-semantic-ir.md": doc("0001", header="- Updated-by: RFC-0002 (§노드 카탈로그)\n"),
             "0002-syntax.md": doc("0002", header=CATALOGUE_UPDATES)},
            "- Changed (issue #1, RFC-0001).\n")
        self.assertEqual(rc, 0)
        self.assertIn("문제 없음.", out)

    def test_main_fails_on_an_updated_by_without_a_section_group(self):
        rc, out = self.run_main(
            {"0001-semantic-ir.md": doc("0001", header="- Updated-by: RFC-0002\n"),
             "0002-syntax.md": doc("0002", header=CATALOGUE_UPDATES)},
            "- Changed (issue #1, RFC-0001).\n")
        self.assertEqual(rc, 1)
        self.assertIn("(§…)", out)
        self.assertIn("RFC-0002", out)
        self.assertIn("1 problem(s)", out)


if __name__ == "__main__":
    unittest.main()
