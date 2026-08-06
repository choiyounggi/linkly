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


class DocumentCoverageTest(unittest.TestCase):
    def test_the_document_exists(self):
        self.assertTrue(os.path.isfile(DOC), "cli-surface.md가 없다")

    def test_every_subcommand_is_documented(self):
        subcommands, _ = parse_cli_surface()
        text = read_doc()
        missing = sorted(name for name in subcommands if name not in text)
        self.assertEqual(missing, [], "문서에 없는 서브커맨드: %s" % missing)

    def test_every_long_option_is_documented(self):
        _, options = parse_cli_surface()
        text = read_doc()
        missing = sorted(opt for opt in options if opt not in text)
        self.assertEqual(missing, [], "문서에 없는 플래그: %s" % missing)

    def test_the_diagnostic_location_limit_is_stated(self):
        """t4 F-11: diagnostics point at node ids, not file:line."""
        text = read_doc()
        self.assertIn("노드 id", text)
        self.assertIn("line", text)

    def test_the_skill_routes_to_it(self):
        skill = os.path.join(os.path.dirname(DOC), "SKILL.md")
        with open(skill, encoding="utf-8") as fh:
            self.assertIn("cli-surface.md", fh.read())


if __name__ == "__main__":
    unittest.main()
