"""README가 주장하는 수치가 레포의 실제를 충실히 반영하는가.

이 파일이 생긴 이유: README의 "**1346 tests**"와 "**15 RFCs**"가 **두 릴리스치**
낡아 있었다(실제로는 1964와 24). 아무도 거짓말하지 않았고, 손으로 적은 숫자가
릴리스마다 조용히 밀렸을 뿐이다. 첫 접촉면이 자기 규모를 틀리게 말하면, 읽는
쪽은 그것을 검증할 방법이 없다. (이 1346 vs 1964 수치는 이제
`BandDiscriminationTest`의 역방향 대조군으로도 쓰인다 — 밴드 밖 값이 실제로
걸러지는지를 이 실제 사건으로 증명한다.)

여기서 세는 것은 **손으로 적힌 주장**뿐이다. 생성물(`references/`)은
`gen_plugin_references.py --check`가 이미 소유하고 있으므로 건드리지 않는다.

세 축을 각각 본다 — 하나로 뭉치면 어느 축이 밀렸는지 실패 메시지가 말해주지
못한다:

  1. 스위트 규모     README의 테스트 수(근사치)가 실제 발견되는 테스트 수의
                     ±5% 밴드 안에 있는가 — 정확한 수는 어디에도 커밋되지
                     않으므로, 테스트를 추가하는 브랜치가 이 줄을 고칠 이유가
                     없다 (`within_band` 참고)
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


def accepted_numbers():
    """`Accepted` 상태인 RFC들 — 판정은 rfc_lint 가 한다.

    `total - len(superseded_numbers())`가 아니다: 그 뺄셈은 Superseded가
    아닌 RFC를 전부 Accepted로 셌다. Draft RFC가 하나도 없던 동안은 우연히
    맞았을 뿐이고, RFC-0033(첫 Draft)이 그 우연을 깬다.
    """
    return [os.path.basename(p)[:4] for p in rfc_paths()
            if rfc_lint.status_of(read(p)) == "Accepted"]


def marketplace_plugin_names():
    import json
    with open(os.path.join(REPO, ".claude-plugin", "marketplace.json"),
              encoding="utf-8") as fh:
        return [e["name"] for e in json.load(fh)["plugins"]]


SUITE_CLAIM_BAND = 0.05


def within_band(claimed, actual, ratio=SUITE_CLAIM_BAND):
    """주장한 수가 실측값의 ±ratio 안인가. 판정을 함수로 빼는 이유는
    README를 변조하지 않고도 이 판정이 빨개질 수 있음을 증명하기
    위해서다 (wiki: tests-that-cannot-fail §1)."""
    if actual <= 0:
        raise ValueError("actual must be positive; 0이면 공허한 통과다")
    return abs(claimed - actual) <= actual * ratio


class SuiteSizeClaimTest(unittest.TestCase):

    def test_both_readmes_state_the_real_test_count(self):
        actual = discovered_test_count()
        for path, pattern in ((EN, r"\*\*~([\d,]+) tests, all passing\*\*"),
                              (KO, r"\*\*테스트 ([\d,]+)여 개 전부 통과\*\*")):
            with self.subTest(readme=os.path.basename(path)):
                m = re.search(pattern, read(path))
                self.assertIsNotNone(
                    m, "%s 에서 테스트 수 주장을 찾지 못했다 — 문면이 바뀌었으면 "
                       "이 가드의 패턴도 함께 고쳐라" % os.path.basename(path))
                claimed = int(m.group(1).replace(",", ""))
                self.assertTrue(
                    within_band(claimed, actual),
                    "%s 는 약 %d개라고 적었는데 실측은 %d개다 — 밴드 ±%d%% 밖이다. "
                    "README의 근사치를 갱신하라."
                    % (os.path.basename(path), claimed, actual,
                       int(SUITE_CLAIM_BAND * 100)))

    def test_the_verification_block_is_within_the_band(self):
        # 위의 산문과 아래의 붙여넣은 출력이 서로 크게 어긋나면 어느 쪽을
        # 믿을지 알 수 없다. 붙여넣은 출력은 특정 시점의 증거이므로 등호가
        # 아니라 같은 밴드로 검사한다(wiki: stale-artifact-baselines §1).
        actual = discovered_test_count()
        for path in (EN, KO):
            with self.subTest(readme=os.path.basename(path)):
                m = re.search(r"Ran (\d+) tests in ", read(path))
                self.assertIsNotNone(m)
                pasted = int(m.group(1))
                self.assertTrue(
                    within_band(pasted, actual),
                    "%s 의 붙여넣은 실행 출력(%d개)이 실측(%d개)과 밴드 ±%d%% "
                    "밖으로 어긋났다."
                    % (os.path.basename(path), pasted, actual,
                       int(SUITE_CLAIM_BAND * 100)))


class BandDiscriminationTest(unittest.TestCase):
    """`within_band`가 실제로 빨개질 수 있음을 증명하는 역방향 대조군
    (wiki: harness-reverse-controls §1, minimum-case-set)."""

    def test_within_band_normal(self):
        self.assertTrue(within_band(2800, 2823))

    def test_within_band_error_out_of_band(self):
        # 이 파일이 생긴 실제 사건: 1346 주장 vs 1964 실측(31% 과소) —
        # 밴드 ±5%로는 명백히 걸러져야 한다.
        self.assertFalse(within_band(1346, 1964))

    def test_within_band_boundary(self):
        # actual=2800은 actual*SUITE_CLAIM_BAND가 부동소수점으로 정확히
        # 떨어져(140.0) 경계 비교가 반올림 오차로 흔들리지 않는다.
        actual = 2800
        at_edge = actual - actual * SUITE_CLAIM_BAND
        self.assertTrue(within_band(at_edge, actual))
        just_outside = at_edge - 1
        self.assertFalse(within_band(just_outside, actual))

    def test_within_band_zero_actual_raises(self):
        with self.assertRaises(ValueError):
            within_band(1, 0)


class RfcCountClaimTest(unittest.TestCase):

    def test_both_readmes_state_the_real_rfc_counts(self):
        total = len(rfc_numbers())
        accepted = len(accepted_numbers())
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

    def test_a_draft_rfc_is_excluded_from_the_accepted_count(self):
        """회귀: `accepted = total - superseded`로 되돌아가면, Superseded가
        아닌 Draft RFC가 Accepted로 잘못 세어진다 — Draft가 하나도 없던
        동안은 우연히 맞았을 뿐이다(RFC-0033 전까지)."""
        draft_numbers = [os.path.basename(p)[:4] for p in rfc_paths()
                          if rfc_lint.status_of(read(p)) == "Draft"]
        self.assertGreater(
            len(draft_numbers), 0,
            "이 회귀가 잡으려는 상황(Draft RFC 존재)이 지금 레포에 없다 "
            "— Draft가 0개면 이 테스트는 공허하게 통과한다")
        accepted = accepted_numbers()
        for number in draft_numbers:
            with self.subTest(rfc=number):
                self.assertNotIn(
                    number, accepted,
                    "Draft RFC %s가 Accepted 집계에 들어갔다 — "
                    "`total - superseded` 식으로 되돌아간 회귀다" % number)


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
