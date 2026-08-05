"""`lnpl-dev` 플러그인(기여자용)의 구조 검사.

`lnpl` 플러그인이 `.lnpl` 작성자를 향한다면 이쪽은 linkly 자체를 고치는 사람을
향한다. 도구는 레포 `scripts/`에 두고 스킬은 "언제 쓰는가"만 담는다 — 기여자는
언제나 체크아웃을 갖고 있으므로 플러그인이 스크립트를 중복 배포할 이유가 없다.

여기서 검사하는 것은 구조와 **참조 무결성**이다. 스킬이 가리키는 스크립트가
실재하지 않으면 조용히 쓸모없어진다.
"""
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN_DIR = os.path.join(REPO, "plugins", "lnpl-dev")
SKILLS = os.path.join(PLUGIN_DIR, "skills")

DEV_SKILLS = ("lnpl-dev-env", "lnpl-dev-rfc", "lnpl-dev-mutation")
TOOLS = (os.path.join("scripts", "dev_doctor.sh"),
         os.path.join("scripts", "rfc_lint.py"))


def read(name):
    with open(os.path.join(SKILLS, name, "SKILL.md"), encoding="utf-8") as fh:
        return fh.read()


def frontmatter_name(text):
    m = re.search(r"^name:\s*(\S+)\s*$", text, re.M)
    return m.group(1) if m else None


class DevPluginStructureTest(unittest.TestCase):
    def test_every_dev_skill_exists(self):
        for name in DEV_SKILLS:
            self.assertTrue(os.path.isfile(os.path.join(SKILLS, name, "SKILL.md")),
                            "%s가 없다" % name)

    def test_frontmatter_name_matches_directory(self):
        for name in DEV_SKILLS:
            self.assertEqual(frontmatter_name(read(name)), name)

    def test_description_is_long_enough_to_trigger(self):
        for name in DEV_SKILLS:
            text = read(name)
            m = re.search(r"^description:\s*(.+)$", text, re.M)
            self.assertIsNotNone(m, "%s에 description이 없다" % name)
            self.assertGreater(len(m.group(1)), 60)

    def test_plugin_readme_lists_every_dev_skill(self):
        with open(os.path.join(PLUGIN_DIR, "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        for name in DEV_SKILLS:
            self.assertIn(name, text)

    def test_readme_points_at_the_author_facing_plugin(self):
        # 두 플러그인의 대상이 다르다는 사실이 사라지면 사용자가 잘못 설치한다.
        with open(os.path.join(PLUGIN_DIR, "README.md"), encoding="utf-8") as fh:
            self.assertIn("../lnpl/README.md", fh.read())


class ToolReferenceIntegrityTest(unittest.TestCase):
    """스킬이 가리키는 도구가 실재하는가 — 깨지면 조용히 쓸모없어진다."""

    def test_the_tools_exist(self):
        for rel in TOOLS:
            self.assertTrue(os.path.isfile(os.path.join(REPO, rel)),
                            "%s가 없다" % rel)

    def test_dev_doctor_is_executable(self):
        self.assertTrue(os.access(os.path.join(REPO, "scripts", "dev_doctor.sh"),
                                  os.X_OK))

    def test_every_scripts_path_named_in_a_skill_exists(self):
        pattern = re.compile(r"scripts/[A-Za-z0-9_.-]+")
        for name in DEV_SKILLS:
            for rel in set(pattern.findall(read(name))):
                self.assertTrue(os.path.isfile(os.path.join(REPO, rel)),
                                "%s가 없는 %s를 가리킨다" % (name, rel))

    def test_env_skill_names_the_doctor(self):
        self.assertIn("scripts/dev_doctor.sh", read("lnpl-dev-env"))

    def test_rfc_skill_names_the_lint(self):
        self.assertIn("scripts/rfc_lint.py", read("lnpl-dev-rfc"))

    def test_mutation_skill_names_the_harness_and_its_tree_guard(self):
        text = read("lnpl-dev-mutation")
        self.assertIn("mutation_check.py", text)
        self.assertIn("TREE_CONTENTS", text)


class DevSkillContentTest(unittest.TestCase):
    """가르치는 내용이 실측과 어긋나지 않는가."""

    def test_env_skill_lists_all_four_preconditions(self):
        text = read("lnpl-dev-env")
        for token in ("python3.13", "jsonschema", "pip install .", "CPATH"):
            self.assertIn(token, text, "전제조건 %s가 빠졌다" % token)

    def test_rfc_skill_carries_the_seven_template_sections(self):
        text = read("lnpl-dev-rfc")
        for section in ("Status", "Motivation", "Guide-level Explanation",
                        "Reference-level Specification", "Examples",
                        "Alternatives", "Open Questions"):
            self.assertIn(section, text)

    def test_rfc_skill_records_the_process_rfc_exemption(self):
        # 이것을 빠뜨리면 RFC-0000/0007을 위반으로 오독한다.
        text = read("lnpl-dev-rfc")
        self.assertIn("RFC-0000", text)
        self.assertIn("RFC-0007", text)

    def test_mutation_skill_warns_about_masked_exit_codes(self):
        text = read("lnpl-dev-mutation")
        self.assertTrue(any(w in text for w in ("종료 코드", "rc=")),
                        "파이프가 종료 코드를 가리는 함정이 없다")


if __name__ == "__main__":
    unittest.main()
