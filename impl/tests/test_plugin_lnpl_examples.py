"""`lnpl` 플러그인이 vendor한 예제와 참조 링크의 계약 테스트.

감사 follow-up: `lnpl-authoring` 스킬이 `plugins/lnpl` 밖의
`examples/linkhub.lnpl`을 가리켰다 — 설치된 플러그인에는 그 파일이 없으니
참조가 깨진다. 고침은 `plugins/lnpl/examples/`에 같은 파일을 vendor하고
참조를 그쪽으로 돌리는 것이다. 이 파일은 두 가지를 고정한다:

  1. vendor된 사본이 레포 정본(`examples/`)과 바이트 동일하다 — 둘이
     갈라지면 스킬이 가르치는 예제와 레포가 테스트하는 예제가 달라진다.
  2. `plugins/lnpl/**/*.md`의 상대 링크(와 `${CLAUDE_PLUGIN_ROOT}/...`)가
     전부 플러그인 **안에서** resolve된다 — 밖을 가리키는 링크는 설치된
     플러그인에서 깨진다.
"""
import glob
import os
import re
import shutil
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN_ROOT = os.path.join(REPO, "plugins", "lnpl")
VENDORED_EXAMPLES = os.path.join(PLUGIN_ROOT, "examples")
SOURCE_EXAMPLES = os.path.join(REPO, "examples")

LINK_RE = re.compile(r"\]\(([^)]+)\)")


def _iter_md_links(root):
    for path in glob.glob(os.path.join(root, "**", "*.md"), recursive=True):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for m in LINK_RE.finditer(text):
            yield path, m.group(1)


def _check_links_resolve_inside(root):
    """`root` 아래 `*.md`의 상대/`${CLAUDE_PLUGIN_ROOT}/...` 링크가 전부
    `root` **안의** 실재하는 파일로 resolve되는지 검사한다.

    `http(s)://`, `mailto:` 절대 링크와 순수 인페이지 앵커(`#foo`)는
    건너뛴다 — 그건 이미 플러그인 밖(또는 같은 페이지 안)을 가리키도록
    정해진 참조다. 위반 목록을 `(md_path, link, 이유)` 튜플로 돌려준다.
    """
    violations = []
    root_abs = os.path.normpath(root)
    for md_path, link in _iter_md_links(root):
        if link.startswith(("http://", "https://", "mailto:")):
            continue
        link_path = link.split("#", 1)[0]
        if not link_path:
            continue
        if link_path.startswith("${CLAUDE_PLUGIN_ROOT}/"):
            target = os.path.join(root_abs, link_path[len("${CLAUDE_PLUGIN_ROOT}/"):])
        else:
            target = os.path.join(os.path.dirname(md_path), link_path)
        target = os.path.normpath(target)
        if target != root_abs and not target.startswith(root_abs + os.sep):
            violations.append((md_path, link, "resolves outside the plugin"))
            continue
        if not os.path.isfile(target):
            violations.append((md_path, link, "target does not exist"))
    return violations


class VendoredExamplesStaySyncedTest(unittest.TestCase):

    def test_vendored_examples_are_byte_identical_to_their_source(self):
        vendored = sorted(glob.glob(os.path.join(VENDORED_EXAMPLES, "*.lnpl")))
        self.assertTrue(vendored, "plugins/lnpl/examples/ 에 vendor된 .lnpl이 없다")
        for path in vendored:
            name = os.path.basename(path)
            source = os.path.join(SOURCE_EXAMPLES, name)
            self.assertTrue(os.path.isfile(source),
                            "%s의 원본이 레포 examples/ 에 없다" % name)
            with open(path, "rb") as fh:
                vendored_bytes = fh.read()
            with open(source, "rb") as fh:
                source_bytes = fh.read()
            self.assertEqual(
                vendored_bytes, source_bytes,
                "%s가 원본(examples/%s)과 달라졌다 — vendor된 사본은 손으로 고치지 "
                "말고 원본에서 다시 복사해야 한다" % (name, name))


class PluginLinkContainmentTest(unittest.TestCase):

    def test_every_markdown_link_in_the_plugin_resolves_inside_it(self):
        violations = _check_links_resolve_inside(PLUGIN_ROOT)
        self.assertEqual(
            violations, [],
            "plugins/lnpl 밖을 가리키거나 존재하지 않는 링크: %r" % (violations,))

    def test_a_dangling_or_escaping_link_is_reported(self):
        # error case: a reference to a file that does not exist, and one
        # that escapes the checked root entirely, must both surface.
        tmp = tempfile.mkdtemp(dir=os.path.join(REPO, ".claude", "tmp"))
        self.addCleanup(shutil.rmtree, tmp, True)
        escape_target = os.path.join(REPO, "examples", "linkhub.lnpl")
        escape_rel = os.path.relpath(escape_target, tmp)
        with open(os.path.join(tmp, "broken.md"), "w", encoding="utf-8") as fh:
            fh.write("See [missing](./nope-does-not-exist.md) "
                    "and [escape](%s).\n" % escape_rel)
        violations = _check_links_resolve_inside(tmp)
        self.assertEqual(len(violations), 2, violations)
        reasons = {reason for _, _, reason in violations}
        self.assertIn("target does not exist", reasons)
        self.assertIn("resolves outside the plugin", reasons)

    def test_a_markdown_file_with_no_links_passes(self):
        # boundary: no references at all is not a violation.
        tmp = tempfile.mkdtemp(dir=os.path.join(REPO, ".claude", "tmp"))
        self.addCleanup(shutil.rmtree, tmp, True)
        with open(os.path.join(tmp, "plain.md"), "w", encoding="utf-8") as fh:
            fh.write("그냥 글이다 — 링크가 없다.\n")
        self.assertEqual(_check_links_resolve_inside(tmp), [])


if __name__ == "__main__":
    unittest.main()
