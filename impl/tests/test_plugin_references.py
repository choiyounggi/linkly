"""플러그인 어휘 문서가 소스에서 생성된 그대로인지 검사한다.

정본은 `impl/lnpl/`의 모듈 상수다. `references/*.md`는 산출물이고, 사람이
고치면 안 된다. 고치면 플러그인이 틀린 어휘를 권위 있게 가르치게 된다 —
`docs/ENFORCEMENT-MATRIX.md`가 `test_enforcement_matrix.py`로 고정된 것과
같은 이유, 같은 장치다.
"""
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GEN = os.path.join(REPO, "scripts", "gen_plugin_references.py")
REFS = os.path.join(REPO, "plugins", "lnpl", "skills", "lnpl-authoring", "references")
EXPECTED = ("grammar.md", "verbs.md", "declarations.md", "types.md", "spec.md")


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


if __name__ == "__main__":
    unittest.main()
