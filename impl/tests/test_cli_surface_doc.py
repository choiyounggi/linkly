"""The CLI surface doc must not drift from the parser (issue #50, t1 F-12).

QA case t1 simulated "develop from the public documents only" and had to open
`impl/lnpl/cli.py` to learn that `-o`, `run --payload/--no-row`,
`build --field/--workdir` and the `openapi` subcommand exist at all. The skill
documents route to the vocabulary references, and those are generated from the
compiler tables — but the CLI had no such surface anywhere.

`cli-surface.md` is hand-written (argparse help text is not a stable generator
input across Python versions), so it needs a gate instead: this module reads the
parser out of `cli.py` with `ast` and asserts every subcommand and every long
option reaches the document. Nothing here imports argparse or builds a parser —
the source is the truth, so a flag added and never documented fails here.
"""

import ast
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLI = os.path.join(REPO, "impl", "lnpl", "cli.py")
DOC = os.path.join(REPO, "plugins", "lnpl", "skills", "lnpl-authoring",
                   "cli-surface.md")

# Below these the extractor is not measuring the parser any more, it is measuring
# nothing. Kept just under the real counts so adding a flag does not force a bump
# here, but far enough above zero that a broken walk cannot pass (issue #50).
MIN_SUBCOMMANDS = 8
MIN_OPTIONS = 12


def _first_string_arg(node):
    if node.args and isinstance(node.args[0], ast.Constant) \
       and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def parse_cli_surface(path=CLI):
    """(subcommand names, long option strings) as written in the source."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    subcommands, options = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "add_parser":
            name = _first_string_arg(node)
            if name:
                subcommands.add(name)
        elif node.func.attr == "add_argument":
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                   and arg.value.startswith("--"):
                    options.add(arg.value)
    return subcommands, options


def read_doc():
    with open(DOC, encoding="utf-8") as fh:
        return fh.read()


def heading_lines(text):
    """Only the `#`-prefixed lines — a name in body prose does not count.

    Without this, a subcommand mentioned in passing inside an unrelated
    section's paragraph (e.g. "이 references/의 grammar·verbs·... 넷을
    생성한다") satisfies a plain substring check by coincidence, with no
    dedicated section actually documenting it (t162 r1 F1)."""
    return "\n".join(line for line in text.split("\n")
                     if line.lstrip().startswith("#"))


class ExtractorTest(unittest.TestCase):
    """The negative controls: an extractor that finds nothing must not pass."""

    def test_the_walk_finds_the_real_parser(self):
        subcommands, options = parse_cli_surface()
        self.assertGreaterEqual(len(subcommands), MIN_SUBCOMMANDS,
                                "서브커맨드를 못 찾았다 — 추출기가 고장났다")
        self.assertGreaterEqual(len(options), MIN_OPTIONS,
                                "옵션을 못 찾았다 — 추출기가 고장났다")

    def test_known_members_are_actually_extracted(self):
        subcommands, options = parse_cli_surface()
        self.assertIn("compile", subcommands)
        self.assertIn("openapi", subcommands)
        self.assertIn("--no-row", options)
        self.assertIn("--workflow", options)

    def test_positional_arguments_are_not_collected(self):
        """`source` is not an option; collecting it would make the doc wrong."""
        _, options = parse_cli_surface()
        self.assertNotIn("source", options)
        for opt in options:
            self.assertTrue(opt.startswith("--"), opt)

    def test_a_source_without_a_parser_yields_nothing(self):
        """Distinguishes "found none" from "walked nothing" (empty != broken)."""
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write("x = 1\n")
            path = fh.name
        try:
            subcommands, options = parse_cli_surface(path)
            self.assertEqual((subcommands, options), (set(), set()))
        finally:
            os.unlink(path)

    def test_a_missing_document_is_an_error_not_a_pass(self):
        with self.assertRaises(OSError):
            with open(DOC + ".nope", encoding="utf-8") as fh:
                fh.read()


class HeadingScopeTest(unittest.TestCase):
    """반증 컨트롤: 부분 문자열 우연 통과가 실제로 막히는지 증명한다.

    t162 r1 F1 — `grammar`는 자기 절이 없이도 `vocab` 절 본문의 무관한
    문장("이 references/의 grammar·verbs·... 넷을 생성한다") 속 부분 문자열
    우연으로 `test_every_subcommand_is_documented`를 통과하고 있었다."""

    def test_a_name_mentioned_only_in_body_prose_is_not_a_match(self):
        prose_only = ("### `vocab` — 벤더 중립 어휘 매니페스트\n\n"
                      "이 references/의 grammar·verbs 넷을 생성한다.\n")
        headings = heading_lines(prose_only)
        self.assertIsNone(re.search(r"\bgrammar\b", headings))

    def test_a_name_with_its_own_heading_is_a_match(self):
        with_heading = "### `grammar` — 닫힌 어휘를 GBNF/JSON으로\n\n본문.\n"
        headings = heading_lines(with_heading)
        self.assertIsNotNone(re.search(r"\bgrammar\b", headings))


class DocumentCoverageTest(unittest.TestCase):
    def test_the_document_exists(self):
        self.assertTrue(os.path.isfile(DOC), "cli-surface.md가 없다")

    def test_every_subcommand_is_documented(self):
        # Scoped to heading lines only (not "anywhere in the file") — a name
        # that only coincides with unrelated body prose must not pass.
        subcommands, _ = parse_cli_surface()
        headings = heading_lines(read_doc())
        missing = sorted(name for name in subcommands
                         if not re.search(r"\b%s\b" % re.escape(name), headings))
        self.assertEqual(missing, [],
                         "문서에 헤딩(### ...)으로 없는 서브커맨드: %s" % missing)

    def test_every_long_option_is_documented(self):
        _, options = parse_cli_surface()
        text = read_doc()
        missing = sorted(opt for opt in options if opt not in text)
        self.assertEqual(missing, [], "문서에 없는 플래그: %s" % missing)

    def test_the_diagnostic_location_limit_is_stated(self):
        """t4 F-11: most diagnostics point at node ids, not file:line — and
        RFC-0024's exception (enforcement diagnostics carry both) is
        documented too, not silently left as the old node-id-only claim."""
        text = read_doc()
        self.assertIn("노드 id", text)
        self.assertIn("line", text)
        self.assertIn("RFC-0024", text)
        self.assertIn("(line N)", text)

    def test_the_skill_routes_to_it(self):
        skill = os.path.join(os.path.dirname(DOC), "SKILL.md")
        with open(skill, encoding="utf-8") as fh:
            self.assertIn("cli-surface.md", fh.read())


if __name__ == "__main__":
    unittest.main()
