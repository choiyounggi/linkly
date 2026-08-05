"""레포 루트 라우팅 파일(`AGENTS.md`)의 참조 무결성.

이 파일은 모든 에이전트 세션이 시작할 때 읽는 진입점이다. 여기서 이름이
어긋나면 **모든 세션이 같은 방향으로 잘못 간다** — 스킬을 이름으로 부르지
못하거나, 없는 경로를 읽으려 하거나, 존재하지 않는 도구로 보내진다.
그런데 스킬 디렉터리 이름을 바꿔도 이 파일은 조용히 낡을 뿐이다.

`CLAUDE.md`는 `@AGENTS.md` 임포트 한 줄만 담는 포인터다 — 정본을 둘로
늘리지 않으면서 Claude Code(문서화된 CLAUDE.md 경로)와 다른 도구(AGENTS.md
관례)가 같은 내용을 읽게 한다.
"""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AGENTS = os.path.join(REPO, "AGENTS.md")
CLAUDE = os.path.join(REPO, "CLAUDE.md")

SKILL_ROOTS = (os.path.join("plugins", "lnpl", "skills"),
               os.path.join("plugins", "lnpl-dev", "skills"))


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def real_skills():
    names = set()
    for root in SKILL_ROOTS:
        names |= set(os.listdir(os.path.join(REPO, root)))
    return names


def skills_named_in(text):
    """백틱으로 감싼 `lnpl-…` 중 실제 스킬 이름 후보."""
    return set(re.findall(r"`(lnpl-[a-z][a-z-]*)`", text))


def paths_named_in(text):
    """`scripts/…` · `rfcs/…` 형태로 언급된 파일 경로."""
    return set(re.findall(r"\b(?:scripts|rfcs)/[\w.\-]+", text))


class RoutingFileExistsTest(unittest.TestCase):
    def test_agents_md_is_the_source_of_truth(self):
        self.assertTrue(os.path.isfile(AGENTS))
        self.assertGreater(len(read(AGENTS)), 500, "라우팅 내용이 거의 없다")

    def test_claude_md_is_only_a_pointer(self):
        text = read(CLAUDE)
        self.assertIn("@AGENTS.md", text, "CLAUDE.md가 AGENTS.md를 임포트하지 않는다")
        self.assertLess(len(text), 500,
                        "CLAUDE.md에 내용이 생겼다 — 정본이 둘로 갈라진다")

    def test_claude_md_does_not_duplicate_the_routing_table(self):
        # 표를 복사해 두면 한쪽만 갱신되어 조용히 갈라진다.
        self.assertNotIn("| 지금 하려는 일", read(CLAUDE))


class SkillReferenceIntegrityTest(unittest.TestCase):
    def test_every_skill_it_names_exists(self):
        named = skills_named_in(read(AGENTS))
        # `lnpl-dev`는 플러그인 이름이지 스킬이 아니다.
        named.discard("lnpl-dev")
        missing = sorted(named - real_skills())
        self.assertEqual(missing, [],
                         "AGENTS.md가 없는 스킬을 부른다: %s" % missing)

    def test_every_skill_is_routed_to(self):
        named = skills_named_in(read(AGENTS))
        unrouted = sorted(real_skills() - named)
        self.assertEqual(unrouted, [],
                         "라우팅 표에 없는 스킬이 있다 — 아무도 못 찾는다: %s"
                         % unrouted)

    def test_it_names_a_nonzero_number_of_skills(self):
        # 대상 0건이라 통과하는 잠자는 테스트가 되지 않게 고정한다.
        self.assertGreaterEqual(len(skills_named_in(read(AGENTS))), 8)


class PathReferenceIntegrityTest(unittest.TestCase):
    def test_every_scripts_and_rfcs_path_exists(self):
        missing = sorted(p for p in paths_named_in(read(AGENTS))
                         if not os.path.exists(os.path.join(REPO, p)))
        self.assertEqual(missing, [],
                         "AGENTS.md가 없는 경로를 가리킨다: %s" % missing)

    def test_skill_file_paths_resolve(self):
        text = read(AGENTS)
        checked = 0
        for m in re.finditer(r"(plugins/[\w-]+/skills)/\{([^}]+)\}/SKILL\.md", text):
            for name in m.group(2).split(","):
                path = os.path.join(REPO, m.group(1), name.strip(), "SKILL.md")
                self.assertTrue(os.path.isfile(path), "%s가 없다" % path)
                checked += 1
        self.assertGreaterEqual(checked, 8,
                                "SKILL.md 폴백 경로가 문서에 없다 — 플러그인 "
                                "미설치 세션이 갈 곳을 잃는다")


class HelperBoundaryTest(unittest.TestCase):
    def test_skill_scan_ignores_prose_without_backticks(self):
        self.assertEqual(skills_named_in("lnpl-authoring 을 쓴다"), set())

    def test_skill_scan_finds_a_backticked_name(self):
        self.assertEqual(skills_named_in("`lnpl-verify`"), {"lnpl-verify"})

    def test_path_scan_ignores_other_directories(self):
        self.assertEqual(paths_named_in("impl/lnpl/lower.py"), set())

    def test_path_scan_finds_scripts_and_rfcs(self):
        self.assertEqual(paths_named_in("scripts/a.py 와 rfcs/0007-x.md"),
                         {"scripts/a.py", "rfcs/0007-x.md"})

    def test_empty_text_yields_nothing(self):
        self.assertEqual(skills_named_in(""), set())
        self.assertEqual(paths_named_in(""), set())


if __name__ == "__main__":
    unittest.main()
