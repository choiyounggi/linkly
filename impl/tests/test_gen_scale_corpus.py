"""`scripts/gen_scale_corpus.py`의 합성 코퍼스 생성기 (issue #117, t117 Task 01).

"파일이 생성됐다"가 아니라 "생성물이 실제로 컴파일된다"가 성공 기준이므로,
정상 케이스는 `.venv/bin/lnpl compile`을 서브프로세스로 직접 돌려 rc 0을 본다.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GEN_PATH = os.path.join(REPO, "scripts", "gen_scale_corpus.py")
LNPL_BIN = os.path.join(os.path.dirname(sys.executable), "lnpl")
# `.claude/tmp`, never /tmp: repo policy — see impl/tests/test_tmp_hygiene.py.
TMP_ROOT = os.path.join(REPO, ".claude", "tmp")
os.makedirs(TMP_ROOT, exist_ok=True)

_spec = importlib.util.spec_from_file_location("gen_scale_corpus", GEN_PATH)
gen_scale_corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_scale_corpus)


def _lnpl_files(out_dir):
    found = []
    for root, _dirs, files in os.walk(out_dir):
        for name in sorted(files):
            if name.endswith(".lnpl"):
                found.append(os.path.join(root, name))
    return sorted(found)


class GenerateNormalTest(unittest.TestCase):
    """정상: --entities 10 --disambiguate로 생성한 코퍼스가 실제로 컴파일된다."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="gen-scale-corpus-", dir=TMP_ROOT)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def test_disambiguated_corpus_actually_compiles(self):
        out = os.path.join(self.tmpdir, "corpus10")
        written, _pool_report = gen_scale_corpus.generate(10, out, seed=0,
                                                            disambiguate=True)
        self.assertEqual(len(written), 10)

        files = _lnpl_files(out)
        self.assertEqual(len(files), 10)

        ir_path = os.path.join(self.tmpdir, "corpus10.lir.json")
        result = subprocess.run(
            [LNPL_BIN, "compile"] + files + ["-o", ir_path],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                          "compile failed: %s" % (result.stderr or result.stdout))
        self.assertTrue(os.path.isfile(ir_path))

    def test_entities_spread_across_five_domain_dirs(self):
        out = os.path.join(self.tmpdir, "corpus10")
        gen_scale_corpus.generate(10, out, seed=0, disambiguate=True)
        domains_present = sorted(
            name for name in os.listdir(out)
            if os.path.isdir(os.path.join(out, name)))
        self.assertEqual(domains_present, sorted(gen_scale_corpus.DOMAINS))


class DeterminismTest(unittest.TestCase):
    """결정성: 같은 --seed로 두 번 생성하면 파일 내용이 바이트 동일하다."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="gen-scale-corpus-det-", dir=TMP_ROOT)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def test_same_seed_produces_byte_identical_files(self):
        out_a = os.path.join(self.tmpdir, "a")
        out_b = os.path.join(self.tmpdir, "b")
        gen_scale_corpus.generate(15, out_a, seed=7, disambiguate=True)
        gen_scale_corpus.generate(15, out_b, seed=7, disambiguate=True)

        files_a = _lnpl_files(out_a)
        files_b = _lnpl_files(out_b)
        self.assertEqual(len(files_a), len(files_b))

        for path_a, path_b in zip(files_a, files_b):
            rel_a = os.path.relpath(path_a, out_a)
            rel_b = os.path.relpath(path_b, out_b)
            self.assertEqual(rel_a, rel_b)
            with open(path_a, "rb") as fh:
                content_a = fh.read()
            with open(path_b, "rb") as fh:
                content_b = fh.read()
            self.assertEqual(content_a, content_b,
                              "byte mismatch for %s" % rel_a)

    def test_different_seed_can_change_noun_choice(self):
        out_a = os.path.join(self.tmpdir, "seed0")
        out_b = os.path.join(self.tmpdir, "seed1")
        gen_scale_corpus.generate(10, out_a, seed=0, disambiguate=True)
        gen_scale_corpus.generate(10, out_b, seed=1, disambiguate=True)
        names_a = {os.path.basename(p) for p in _lnpl_files(out_a)}
        names_b = {os.path.basename(p) for p in _lnpl_files(out_b)}
        self.assertNotEqual(names_a, names_b)


class ErrorCaseTest(unittest.TestCase):
    """에러: --entities 0 -> rc 2 + 명확한 메시지."""

    def test_cli_rejects_zero_entities(self):
        with tempfile.TemporaryDirectory(dir=TMP_ROOT) as tmpdir:
            out = os.path.join(tmpdir, "corpus0")
            result = subprocess.run(
                [sys.executable, GEN_PATH, "--entities", "0", "--out", out],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("--entities", result.stderr)
            self.assertFalse(os.path.isdir(out))

    def test_generate_raises_on_zero_entities(self):
        with tempfile.TemporaryDirectory(dir=TMP_ROOT) as tmpdir:
            with self.assertRaises(ValueError):
                gen_scale_corpus.generate(0, os.path.join(tmpdir, "x"))


class BoundaryCaseTest(unittest.TestCase):
    """경계값: --entities 1이 동작한다."""

    def test_single_entity_generates_one_file(self):
        with tempfile.TemporaryDirectory(dir=TMP_ROOT) as tmpdir:
            out = os.path.join(tmpdir, "corpus1")
            written, pool_report = gen_scale_corpus.generate(
                1, out, seed=0, disambiguate=True)
            self.assertEqual(len(written), 1)
            files = _lnpl_files(out)
            self.assertEqual(len(files), 1)
            with open(files[0], encoding="utf-8") as fh:
                content = fh.read()
            # 단일 엔티티(billing, size=1)는 shared_count=round(1/3)=0이라
            # domain-unique 첫 낱말(DOMAIN_NOUNS['billing'][0])을 결정적으로 쓴다.
            expected_noun = gen_scale_corpus.DOMAIN_NOUNS["billing"][0]
            self.assertIn("entity Billing0000%s" % expected_noun, content)
            self.assertIn("workflow Wf0000Find", content)
            self.assertEqual(pool_report["billing"]["shared_drawn"], 0)
            self.assertEqual(pool_report["billing"]["unique_drawn"], 1)


class RealisticNamingTest(unittest.TestCase):
    """r1 F1 회귀: 이름 충돌이 명사 풀 고갈이 아니라 공유 어휘 재사용에서만 나온다.

    도메인 전용 명사(DOMAIN_NOUNS)는 도메인마다 겹치지 않게 손으로 골랐고
    N과 함께 자라므로, 관측되는 모든 충돌은 반드시 SHARED_NOUNS(4개짜리
    소집합)에서 나와야 한다 — 그렇지 않으면 F1이 지적한 비둘기집 버그로
    되돌아간 것이다.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="gen-scale-corpus-realism-",
                                        dir=TMP_ROOT)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def _entity_names(self, out_dir):
        names = []
        for path in _lnpl_files(out_dir):
            with open(path, encoding="utf-8") as fh:
                first_line = fh.readline().strip()
            self.assertTrue(first_line.startswith("entity "), first_line)
            names.append(first_line[len("entity "):])
        return names

    def test_every_collision_is_a_shared_noun_not_pool_exhaustion(self):
        out = os.path.join(self.tmpdir, "corpus50")
        gen_scale_corpus.generate(50, out, seed=0, disambiguate=False)
        names = self._entity_names(out)
        counts = {}
        for name in names:
            counts[name] = counts.get(name, 0) + 1
        colliding = [name for name, c in counts.items() if c > 1]
        self.assertGreater(
            len(colliding), 0,
            "이 회귀가 확인하려는 상황(충돌 존재)이 지금 없다 — 공허한 통과")
        for name in colliding:
            with self.subTest(name=name):
                self.assertIn(
                    name, gen_scale_corpus.SHARED_NOUNS,
                    "%r가 충돌했지만 공유 어휘가 아니다 — 도메인 전용 풀이 "
                    "고갈됐거나 도메인 풀끼리 겹친다는 뜻으로, F1의 비둘기집 "
                    "버그가 되돌아온 신호다" % name)

    def test_domain_pools_do_not_overlap_each_other_or_the_shared_pool(self):
        all_domain_words = []
        for words in gen_scale_corpus.DOMAIN_NOUNS.values():
            all_domain_words.extend(words)
        self.assertEqual(
            len(all_domain_words), len(set(all_domain_words)),
            "도메인 전용 명사 목록끼리 겹치는 낱말이 있다")
        overlap = set(all_domain_words) & set(gen_scale_corpus.SHARED_NOUNS)
        self.assertEqual(overlap, set(),
                          "도메인 전용 명사가 공유 풀과도 겹친다: %s" % overlap)

    def test_pool_exhaustion_raises_a_clear_error(self):
        # DOMAIN_NOUNS 각 도메인 20개 -> 5도메인 * 20 = 100개가 상한(unique
        # 몫만 고려하면 더 크다). 극단적으로 큰 --entities는 명확한 에러로
        # 거부돼야 한다("나중에" 조용히 이름을 재사용하지 않는다).
        with tempfile.TemporaryDirectory(dir=TMP_ROOT) as tmpdir:
            with self.assertRaises(ValueError):
                gen_scale_corpus.generate(100000, os.path.join(tmpdir, "x"))


if __name__ == "__main__":
    unittest.main()
