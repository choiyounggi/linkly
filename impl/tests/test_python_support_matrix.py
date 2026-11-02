"""Python 지원 집합의 세 사본이 같은 집합을 말하는가 (issue #246).

지원 버전은 세 곳에 따로 적힌다: `ci.yml` `gate` 잡의 매트릭스, `pyproject.toml`의
`classifiers`, `docs/compatibility.md`의 `## 지원 Python 버전` 표. 한 곳만 고치는
드리프트를 이 파일이 잡는다 — 각 사본은 자기 파일에서 따로 읽는다.
"""
import json
import os
import re
import tomllib
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CI_YML_PATH = os.path.join(REPO, ".github", "workflows", "ci.yml")
PYPROJECT_PATH = os.path.join(REPO, "pyproject.toml")
COMPAT_PATH = os.path.join(REPO, "docs", "compatibility.md")
EXPECTED = ["3.11", "3.12", "3.13", "3.14"]
CLASSIFIER_PREFIX = "Programming Language :: Python :: "


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _gate_job(ci_text):
    start = ci_text.index("\n  gate:\n")
    end = ci_text.index("\n  modeb-linux:\n", start)
    return ci_text[start:end]


def matrix_versions(ci_text):
    match = re.search(r"^\s*python-version: (\[.*\])\s*$", _gate_job(ci_text), re.M)
    if match is None:
        raise ValueError("gate job has no python-version matrix list")
    return json.loads(match.group(1))


def classifier_versions(project):
    versions = []
    for classifier in project.get("classifiers", []):
        if classifier.startswith(CLASSIFIER_PREFIX):
            version = classifier[len(CLASSIFIER_PREFIX):]
            if re.fullmatch(r"3\.\d+", version):
                versions.append(version)
    return versions


def doc_table_versions(md_text):
    start = md_text.index("\n## 지원 Python 버전\n")
    end = md_text.find("\n## ", start + 1)
    section = md_text[start:end if end >= 0 else len(md_text)]
    return re.findall(r"^\| (3\.\d+) \|", section, re.M)


def _key(version):
    return tuple(int(part) for part in version.split("."))


class SupportSetTest(unittest.TestCase):
    """정상 케이스: 세 사본이 같은 네 버전을 말한다."""

    def test_gate_matrix_is_the_four_versions(self):
        self.assertEqual(matrix_versions(_read(CI_YML_PATH)), EXPECTED)

    def test_classifiers_match_the_matrix(self):
        project = tomllib.loads(_read(PYPROJECT_PATH))["project"]
        self.assertEqual(classifier_versions(project), matrix_versions(_read(CI_YML_PATH)))

    def test_doc_table_matches_the_matrix(self):
        self.assertEqual(doc_table_versions(_read(COMPAT_PATH)), matrix_versions(_read(CI_YML_PATH)))

    def test_requires_python_is_the_matrix_floor(self):
        project = tomllib.loads(_read(PYPROJECT_PATH))["project"]
        floor = min(matrix_versions(_read(CI_YML_PATH)), key=_key)
        self.assertEqual(project["requires-python"], ">=" + floor)

    def test_gate_job_has_no_continue_on_error(self):
        self.assertNotIn("continue-on-error", _gate_job(_read(CI_YML_PATH)))


class MissingAnchorTest(unittest.TestCase):
    """에러 케이스: 읽을 자리가 없으면 빈 결과가 아니라 예외다."""

    def test_matrix_versions_without_a_gate_job_raises(self):
        with self.assertRaises(ValueError):
            matrix_versions("jobs:\n  lint:\n    runs-on: ubuntu-latest\n")

    def test_matrix_versions_without_a_matrix_line_raises(self):
        with self.assertRaises(ValueError):
            matrix_versions("jobs:\n  gate:\n    steps: []\n  modeb-linux:\n")

    def test_doc_table_versions_without_the_section_raises(self):
        with self.assertRaises(ValueError):
            doc_table_versions("# 호환성 정책\n\n## 계약 목록\n")


class ClassifierBoundaryTest(unittest.TestCase):
    """경계값: classifiers가 없거나 X.Y가 아닌 항목만 있으면 빈 목록."""

    def test_project_without_classifiers_gives_empty_list(self):
        self.assertEqual(classifier_versions({}), [])

    def test_non_minor_version_classifiers_are_ignored(self):
        project = {"classifiers": [CLASSIFIER_PREFIX + "3", CLASSIFIER_PREFIX + "3 :: Only"]}
        self.assertEqual(classifier_versions(project), [])


if __name__ == "__main__":
    unittest.main()
