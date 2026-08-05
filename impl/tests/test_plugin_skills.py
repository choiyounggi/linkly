"""P1 스킬 3종의 구조·정합 검사.

`lnpl-authoring`(P0)이 쓰는 순간을 다뤘다면 이 셋은 그 다음을 다룬다:
완료 게이트(`lnpl-verify`), 검증 도출(`lnpl-spec`), 설계 근거 조회(`lnpl-kb`).

여기서 지키는 규칙은 두 가지다.

1. **스킬은 라우팅 계층이다.** 어휘 본문은 생성물 `references/`에 있고, 스킬이
   그것을 복사하면 `scripts/gen_plugin_references.py`의 drift 게이트를 우회하는
   두 번째 사본이 생긴다.
2. **가르치는 규칙의 정본은 구현이다.** `lnpl-spec`이 말하는 기대 키는 전부
   `lnpl.spec.EXPECTATIONS`에 실재해야 한다 — 계획 문서에만 있고 코드에는 없는
   규칙을 가르치면(예: `timeout` → 데드라인 케이스) 스킬이 조용히 거짓이 된다.
"""
import os
import re
import unittest

from lnpl.spec import EXPECTATIONS

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILLS = os.path.join(REPO, "plugins", "lnpl", "skills")
PLUGIN_README = os.path.join(REPO, "plugins", "lnpl", "README.md")

NEW_SKILLS = ("lnpl-verify", "lnpl-spec", "lnpl-kb")
ALL_SKILLS = ("lnpl-authoring", "lnpl-doctor") + NEW_SKILLS


def skill_path(name):
    return os.path.join(SKILLS, name, "SKILL.md")


def read(name):
    with open(skill_path(name), encoding="utf-8") as fh:
        return fh.read()


def parse_frontmatter(text):
    """`---`로 감싼 머리말을 key: value로 읽는다. fence가 없으면 거부한다."""
    lines = text.split("\n")
    if lines[0].strip() != "---":
        raise ValueError("머리말 fence(`---`)로 시작하지 않는다")
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return out
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    raise ValueError("머리말이 닫히지 않았다")


def frontmatter(name):
    return parse_frontmatter(read(name))


class SkillStructureTest(unittest.TestCase):
    """정상 경로 — 세 스킬 모두 로드 가능한 형태인가."""

    def test_every_new_skill_exists(self):
        for name in NEW_SKILLS:
            self.assertTrue(os.path.isfile(skill_path(name)), "%s가 없다" % name)

    def test_frontmatter_name_matches_directory(self):
        for name in NEW_SKILLS:
            self.assertEqual(frontmatter(name).get("name"), name)

    def test_description_is_long_enough_to_trigger(self):
        for name in NEW_SKILLS:
            desc = frontmatter(name).get("description", "")
            self.assertGreater(len(desc), 40, "%s의 description이 너무 짧다" % name)

    def test_each_skill_stays_a_routing_layer(self):
        for name in NEW_SKILLS:
            self.assertLess(len(read(name)), 4000,
                            "%s가 라우팅 계층을 넘어섰다" % name)

    def test_plugin_readme_lists_every_skill(self):
        with open(PLUGIN_README, encoding="utf-8") as fh:
            text = fh.read()
        for name in ALL_SKILLS:
            self.assertIn(name, text, "README가 %s를 안 적는다" % name)


class VerifySkillTest(unittest.TestCase):
    """완료 게이트가 실제로 게이트인가."""

    def test_names_the_gate_commands_in_order(self):
        text = read("lnpl-verify")
        compile_at = text.find("lnpl compile")
        spec_at = text.find("lnpl spec")
        self.assertGreater(compile_at, -1, "compile 단계가 없다")
        self.assertGreater(spec_at, -1, "spec --run 단계가 없다")
        self.assertLess(compile_at, spec_at, "compile이 spec보다 먼저여야 한다")
        self.assertIn("--run", text)

    def test_treats_mode_b_as_conditional(self):
        # B1: mlir-opt/mlir-translate/clang이 없는 환경이 정상이다.
        text = read("lnpl-verify")
        self.assertIn("lnpl diff", text)
        self.assertTrue(any(w in text for w in ("툴체인", "toolchain")),
                        "diff가 툴체인 조건부라는 사실이 없다")

    def test_says_zero_diagnostics_is_not_the_bar(self):
        # B2: 골든 예제 셋 다 경고를 낸다. 0건을 완료 조건으로 걸면 모델이
        # 게이트를 통과시키려고 정당한 선언을 지운다 — 게이트가 코드를 나쁘게
        # 만드는 것이다. 그래서 "0건이 아니어도 된다"를 명시적으로 요구한다.
        text = read("lnpl-verify")
        self.assertRegex(text, r"0건이\s*완료\s*조건이\s*아니")
        self.assertIn("의도", text, "진단을 어떻게 판정할지가 없다")


class SpecSkillTest(unittest.TestCase):
    """도출 규칙이 구현과 일치하는가."""

    # agents.py:588-650의 Tester가 실제로 도출하는 것.
    REQUIRED_RULES = ("completed", "steps", "slo", "cache", "failed", "attempts")

    def test_carries_the_derivation_rules(self):
        text = read("lnpl-spec")
        for token in self.REQUIRED_RULES:
            self.assertIn(token, text, "도출 규칙에 %s가 없다" % token)

    def test_mentions_the_retry_plus_one_rule(self):
        # 가장 틀리기 쉬운 규칙이라 따로 고정한다: retry N -> attempts N+1.
        text = read("lnpl-spec")
        self.assertRegex(text, r"attempts.{0,40}(N\s*\+\s*1|\+\s*1)")

    def test_every_expectation_key_it_teaches_exists_in_the_implementation(self):
        """스킬이 백틱으로 가르치는 기대 키가 전부 EXPECTATIONS에 있는가.

        이것이 이 파일의 핵심이다. 구현에 없는 규칙(계획 문서에만 있던
        `timeout` -> 데드라인 케이스 같은 것)을 가르치면 여기서 잡힌다.
        """
        text = read("lnpl-spec")
        taught = set()
        for phrase in re.findall(r"`([a-z][a-z ]*?)`", text):
            head = phrase.split()[0]
            # `expect` 절에 쓰이는 형태만 본다 — 산문 단어를 잡지 않도록
            # EXPECTATIONS와 이름이 겹치는 것만 후보로 삼는다.
            if head in EXPECTATIONS:
                taught.add(head)
        self.assertTrue(taught, "가르치는 기대 키를 하나도 못 찾았다")
        self.assertTrue(taught <= set(EXPECTATIONS),
                        "EXPECTATIONS에 없는 키를 가르친다: %s"
                        % sorted(taught - set(EXPECTATIONS)))

    def test_does_not_inline_the_full_expectation_vocabulary(self):
        # 어휘의 정본은 생성물 references/spec.md다. 스킬이 12개를 다 옮기면
        # drift 게이트를 우회하는 두 번째 사본이 된다.
        text = read("lnpl-spec")
        hits = sum(1 for key in EXPECTATIONS if "`%s" % key in text)
        self.assertLess(hits, len(EXPECTATIONS),
                        "EXPECTATIONS 전부를 인라인했다 — references/spec.md로 라우팅하라")

    def test_routes_to_the_generated_reference(self):
        self.assertIn("references/spec.md", read("lnpl-spec"))


class KbSkillTest(unittest.TestCase):
    """KB 조회 경로가 실제 CLI와 맞는가."""

    def test_names_both_kb_subcommands(self):
        text = read("lnpl-kb")
        self.assertIn("kb --route", text)
        self.assertIn("kb --load", text)

    def test_says_when_to_consult_the_kb(self):
        text = read("lnpl-kb")
        self.assertTrue(any(w in text for w in ("결정", "선택")),
                        "언제 KB를 보는지가 없다")


class SkillBoundaryTest(unittest.TestCase):
    """경계값 — 헬퍼 자체가 정직한가."""

    def test_frontmatter_rejects_text_without_a_fence(self):
        with self.assertRaises(ValueError):
            parse_frontmatter("# 제목만 있는 문서\n본문\n")

    def test_frontmatter_rejects_an_unclosed_fence(self):
        with self.assertRaises(ValueError):
            parse_frontmatter("---\nname: x\n본문이 이어진다\n")

    def test_frontmatter_rejects_empty_text(self):
        with self.assertRaises(ValueError):
            parse_frontmatter("")

    def test_frontmatter_reads_a_well_formed_head(self):
        meta = parse_frontmatter("---\nname: x\ndescription: y\n---\n본문\n")
        self.assertEqual(meta, {"name": "x", "description": "y"})

    def test_missing_skill_raises_rather_than_passing_quietly(self):
        with self.assertRaises(FileNotFoundError):
            read("lnpl-does-not-exist")


if __name__ == "__main__":
    unittest.main()
