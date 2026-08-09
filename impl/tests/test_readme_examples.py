"""README의 `.lnpl` 예제가 어휘 안에 머무는지 — 컴파일러 자신이 판정한다.

README는 LLM과 사람 모두의 첫 접촉면이고, 첫 행동은 예제 복사다. 그런데 이
언어의 어휘는 닫혀 있고 학습 데이터에 없어서, 사전 밖 동사는 에러가 아니라
**효과 없는 no-op**으로 컴파일된다(이슈 #36). 그래서 README 예제가 낡으면
읽는 쪽은 틀린 어휘를 자신 있게 배우고, 컴파일은 성공한다 — 아무도 모른다.

판정을 여기서 다시 구현하지 않는다. 정규식으로 동사 목록을 흉내 내면 그
목록이 `VERB_LEXICON`에서 갈라지는 순간 가드가 거짓을 말한다. 대신 실제
lowering(`parse` -> `lower`)에 먹이고 그것이 내는 `unknown-verb` 진단을 읽는다
— 실행이 쓰는 바로 그 판정이다.

스코프는 **README 두 개뿐이다.** `examples/`는 보지 않는다: `login.lnpl`은
#36의 회귀 픽스처이고 `shorten.lnpl`도 의도적으로 경고를 낸다. 둘을 예외
목록으로 빼는 순간 가드는 아무것도 측정하지 않게 되므로, 이름이 아니라
**위치**로 스코프를 정한다.
"""
import os
import re
import unittest

from lnpl.lower import lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
READMES = ("README.md", "README.ko.md")

# 어휘 밖 동사 하나를 담은 최소 문서. 이 파일의 판정 함수가 실제로 위반을
# 잡는다는 것을 보이는 통제(negative control)이고, 그 외의 쓸모는 없다.
KNOWN_VIOLATION = """entity Note
    field
        id UUID

workflow Save
    validate note
    return note
"""

FENCE = re.compile(r"^```lnpl[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)


def read(path):
    with open(os.path.join(REPO, path), encoding="utf-8") as fh:
        return fh.read()


def lnpl_blocks(markdown):
    """```lnpl 로 태그된 코드펜스의 본문들."""
    return FENCE.findall(markdown)


class BlockDidNotLower(Exception):
    """블록이 파싱은 되는데 lowering에서 거부됐다.

    `lower()`가 raise하면 unittest는 ERROR와 원시 트레이스백을 낸다 — 가드가
    통과한 것은 아니지만, 어느 README의 몇 번째 블록인지가 그 트레이스백에
    없다. 실패 신호를 사람이 고칠 수 있는 형태로 바꾸기 위해 감싼다.
    """


def unknown_verbs(source, name):
    """`source`가 내는 `unknown-verb` 진단의 subject들 — 컴파일러가 판정한다."""
    try:
        module = lower(parse(source), name)
    except Exception as exc:                     # LowerError 및 파싱 거부
        raise BlockDidNotLower("%s: %s" % (type(exc).__name__, exc)) from exc
    return [d.subject for d in module.diagnostics.by_code("unknown-verb")]


class ReadmeBlocksAreExtractable(unittest.TestCase):
    """블록을 못 뽑으면 이후 단언은 전부 공허하게 통과한다."""

    def test_each_readme_has_at_least_one_lnpl_block(self):
        for name in READMES:
            with self.subTest(readme=name):
                blocks = lnpl_blocks(read(name))
                self.assertGreaterEqual(
                    len(blocks), 1,
                    "%s 에서 ```lnpl 블록을 하나도 뽑지 못했다. 펜스에 언어 태그가 "
                    "빠졌다면 이 가드는 아무것도 검사하지 않는다." % name)

    def test_the_two_readmes_carry_the_same_blocks(self):
        en, ko = (lnpl_blocks(read(name)) for name in READMES)
        self.assertEqual(
            en, ko,
            "README.md 와 README.ko.md 의 `.lnpl` 블록이 갈라졌다 — 한쪽만 "
            "고친 것이다.")


class ReadmeExamplesStayInsideTheLexicon(unittest.TestCase):

    def test_no_readme_block_uses_a_verb_outside_the_lexicon(self):
        for name in READMES:
            for i, block in enumerate(lnpl_blocks(read(name))):
                with self.subTest(readme=name, block=i):
                    try:
                        found = unknown_verbs(block, "readme")
                    except BlockDidNotLower as exc:
                        self.fail("%s 의 %d번째 ```lnpl 블록이 컴파일되지 "
                                  "않는다: %s" % (name, i, exc))
                    self.assertEqual(
                        found, [],
                        "%s 의 %d번째 ```lnpl 블록이 어휘 밖 동사 %r 를 쓴다. "
                        "그 스텝은 컴파일에 성공하고 아무 효과도 내지 않는다. "
                        "동사 정본: plugins/lnpl/skills/lnpl-authoring/"
                        "references/verbs.md" % (name, i, found))


class TheGuardCanFail(unittest.TestCase):
    """판정 함수가 위반을 실제로 잡는가 — 이게 없으면 위 초록은 증거가 아니다."""

    def test_the_same_check_reports_a_known_violation(self):
        self.assertEqual(unknown_verbs(KNOWN_VIOLATION, "control"), ["return"])

    def test_a_clean_document_reports_nothing(self):
        clean = KNOWN_VIOLATION.replace("    return note\n", "    create note\n")
        self.assertEqual(unknown_verbs(clean, "control"), [])


if __name__ == "__main__":
    unittest.main()
