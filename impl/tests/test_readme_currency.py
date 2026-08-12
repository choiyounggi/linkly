"""README가 주장하는 수치가 레포의 실제와 같은가.

이 파일이 생긴 이유: README의 "**1346 tests**"와 "**15 RFCs**"가 **두 릴리스치**
낡아 있었다(실제로는 1964와 24). 아무도 거짓말하지 않았고, 손으로 적은 숫자가
릴리스마다 조용히 밀렸을 뿐이다. 첫 접촉면이 자기 규모를 틀리게 말하면, 읽는
쪽은 그것을 검증할 방법이 없다.

여기서 세는 것은 **손으로 적힌 주장**뿐이다. 생성물(`references/`)은
`gen_plugin_references.py --check`가 이미 소유하고 있으므로 건드리지 않는다.

세 축을 각각 본다 — 하나로 뭉치면 어느 축이 밀렸는지 실패 메시지가 말해주지
못한다:

  1. 스위트 규모     README의 테스트 수 == 실제 발견되는 테스트 수
  2. RFC 규모        README의 RFC 수·Accepted 수 == `rfcs/`의 실제
  3. 표의 완전성     RFC 표와 플러그인 표가 실재하는 것을 빠짐없이 싣는가

두 README(영문·한국어)를 모두 본다. 한쪽만 고치는 것이 이 드리프트의 흔한
형태였다.
"""
import glob
import importlib.util
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOP_LEVEL = os.path.dirname(TESTS_DIR)
EN = os.path.join(REPO, "README.md")
KO = os.path.join(REPO, "README.ko.md")

# RFC 상태는 `scripts/rfc_lint.py` 가 정본으로 읽는다. 여기서 정규식을 다시
# 쓰면 그 파서와 갈라지고, 갈라진 쪽이 조용히 이긴다 — 처음 이 파일을 쓸 때
# 실제로 그랬다(0000의 Status를 못 읽어 Superseded를 0으로 셌다).
_LINT = os.path.join(REPO, "scripts", "rfc_lint.py")
_spec = importlib.util.spec_from_file_location("rfc_lint", _LINT)
rfc_lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rfc_lint)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def discovered_test_count():
    """실제로 발견되는 테스트 수. 스위트를 **실행하지 않고** 센다."""
    loader = unittest.TestLoader()
    suite = loader.discover(TESTS_DIR, top_level_dir=TOP_LEVEL)
    if loader.errors:                      # 임포트에 실패한 모듈이 있으면 수가 준다
        raise AssertionError("테스트 모듈 임포트 실패: %s" % loader.errors[:2])
    return suite.countTestCases()


def rfc_paths():
    return sorted(glob.glob(os.path.join(REPO, "rfcs", "[0-9][0-9][0-9][0-9]-*.md")))


def rfc_numbers():
    return [os.path.basename(p)[:4] for p in rfc_paths()]


def superseded_numbers():
    """`Superseded` 상태인 RFC들 — 판정은 rfc_lint 가 한다."""
    return [os.path.basename(p)[:4] for p in rfc_paths()
            if rfc_lint.status_of(read(p)) == "Superseded"]


def marketplace_plugin_names():
    import json
    with open(os.path.join(REPO, ".claude-plugin", "marketplace.json"),
              encoding="utf-8") as fh:
        return [e["name"] for e in json.load(fh)["plugins"]]


class SuiteSizeClaimTest(unittest.TestCase):

    def test_both_readmes_state_the_real_test_count(self):
        actual = discovered_test_count()
        for path, pattern in ((EN, r"\*\*(\d[\d,]*) tests, all passing\*\*"),
                              (KO, r"\*\*테스트 (\d[\d,]*)개 전부 통과\*\*")):
            with self.subTest(readme=os.path.basename(path)):
                m = re.search(pattern, read(path))
                self.assertIsNotNone(
                    m, "%s 에서 테스트 수 주장을 찾지 못했다 — 문면이 바뀌었으면 "
                       "이 가드의 패턴도 함께 고쳐라" % os.path.basename(path))
                claimed = int(m.group(1).replace(",", ""))
                self.assertEqual(
                    claimed, actual,
                    "%s 가 %d개라고 적었는데 실제로는 %d개다."
                    % (os.path.basename(path), claimed, actual))

    def test_the_verification_block_shows_the_same_number(self):
        # 위의 산문과 아래의 붙여넣은 출력이 서로 어긋나면 어느 쪽을 믿을지
        # 알 수 없다.
        actual = discovered_test_count()
        for path in (EN, KO):
            with self.subTest(readme=os.path.basename(path)):
                m = re.search(r"Ran (\d+) tests in ", read(path))
                self.assertIsNotNone(m)
                self.assertEqual(int(m.group(1)), actual)


class RfcCountClaimTest(unittest.TestCase):

    def test_both_readmes_state_the_real_rfc_counts(self):
        total = len(rfc_numbers())
        accepted = total - len(superseded_numbers())
        self.assertGreater(total, 0, "rfcs/ 를 하나도 찾지 못했다 — 공허한 통과다")
        for path, pattern in (
                (EN, r"\*\*(\d+) RFCs — (\d+) `Accepted`"),
                (KO, r"\*\*RFC (\d+)편 — (\d+)편 `Accepted`")):
            with self.subTest(readme=os.path.basename(path)):
                m = re.search(pattern, read(path))
                self.assertIsNotNone(m, os.path.basename(path))
                self.assertEqual((int(m.group(1)), int(m.group(2))),
                                 (total, accepted),
                                 "%s 의 RFC 수 주장이 rfcs/ 와 다르다"
                                 % os.path.basename(path))


class TableCompletenessTest(unittest.TestCase):

    def test_the_rfc_table_lists_every_rfc(self):
        numbers = rfc_numbers()
        self.assertGreater(len(numbers), 0)
        for path in (EN, KO):
            text = read(path)
            listed = set(re.findall(r"\]\(rfcs/(\d{4})-[^)]+\.md\)", text))
            with self.subTest(readme=os.path.basename(path)):
                missing = sorted(set(numbers) - listed)
                self.assertEqual(
                    missing, [],
                    "%s 의 RFC 표에 빠진 항목: %s"
                    % (os.path.basename(path), missing))

    def test_the_english_plugin_table_lists_every_shipped_plugin(self):
        text = read(EN)
        for name in marketplace_plugin_names():
            with self.subTest(plugin=name):
                self.assertIn(
                    "](plugins/%s/README.md)" % name, text,
                    "README의 플러그인 표에 %s 가 없다 — 마켓플레이스는 그것을 "
                    "배포하고 있다" % name)


if __name__ == "__main__":
    unittest.main()
