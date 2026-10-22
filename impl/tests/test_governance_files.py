"""Repository governance files (issue #242).

OpenSSF Scorecard and corporate open-source reviews look for SECURITY.md,
CONTRIBUTING.md, CODE_OF_CONDUCT.md and a CODEOWNERS file first. Once branch
protection requires code-owner review (#244), a CODEOWNERS rule with a bad
owner, a pattern for a path that no longer exists, or a catch-all placed after
the specific rules silently changes who is asked to review.

Each root file is joined with a literal name so test_mutation_tree.py sees the
read and keeps it in mutation_check.TREE_CONTENTS.
"""
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CODEOWNERS = os.path.join(REPO, ".github", "CODEOWNERS")
GOVERNANCE_FILES = {
    "SECURITY.md": os.path.join(REPO, "SECURITY.md"),
    "CONTRIBUTING.md": os.path.join(REPO, "CONTRIBUTING.md"),
    "CODE_OF_CONDUCT.md": os.path.join(REPO, "CODE_OF_CONDUCT.md"),
    ".github/CODEOWNERS": CODEOWNERS,
}
REQUIRED_PATTERNS = ("impl/lnpl/", "rfcs/", ".github/")
OWNER = "@choiyounggi"


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def parse_codeowners(text):
    """Return [(pattern, [owners])] for every rule line of a CODEOWNERS text.

    Blank lines and lines whose first non-space character is '#' are skipped.
    An inline comment (the first token starting with '#' and everything after
    it) is dropped, as GitHub allows. A rule with no owner left, or with an
    owner that is not an @handle, raises ValueError.
    """
    rules = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        for i, token in enumerate(tokens):
            if token.startswith("#"):
                tokens = tokens[:i]
                break
        pattern, owners = tokens[0], tokens[1:]
        if not owners:
            raise ValueError(f"line {lineno}: pattern {pattern!r} has no owner")
        for owner in owners:
            if not owner.startswith("@") or len(owner) == 1:
                raise ValueError(f"line {lineno}: owner {owner!r} is not an @handle")
        rules.append((pattern, owners))
    return rules


def missing_patterns(rules):
    present = {pattern for pattern, _ in rules}
    return [p for p in REQUIRED_PATTERNS if p not in present]


def foreign_owners(rules):
    return [(pattern, owners) for pattern, owners in rules if owners != [OWNER]]


def unresolved_paths(rules, root):
    return [pattern for pattern, _ in rules
            if pattern != "*" and not os.path.exists(os.path.join(root, pattern))]


def catch_all_misplaced(rules):
    """GitHub applies the last matching rule, so a `*` rule must come first."""
    return any(pattern == "*" for pattern, _ in rules[1:])


class GovernanceFilesExistTest(unittest.TestCase):
    def test_each_governance_file_exists(self):
        for name, path in GOVERNANCE_FILES.items():
            with self.subTest(file=name):
                self.assertTrue(os.path.isfile(path), f"missing: {name}")


class CodeownersFileTest(unittest.TestCase):
    def rules(self):
        # A missing file must fail as an assertion, not error as FileNotFoundError.
        self.assertTrue(os.path.isfile(CODEOWNERS), "missing: .github/CODEOWNERS")
        return parse_codeowners(read(CODEOWNERS))

    def test_required_patterns_are_covered(self):
        self.assertEqual(missing_patterns(self.rules()), [])

    def test_every_rule_names_only_the_maintainer(self):
        self.assertEqual(foreign_owners(self.rules()), [])

    def test_every_path_pattern_exists(self):
        self.assertEqual(unresolved_paths(self.rules(), REPO), [])

    def test_catch_all_comes_first(self):
        self.assertFalse(catch_all_misplaced(self.rules()))


class ParseCodeownersTest(unittest.TestCase):
    def test_rule_lines_are_parsed(self):
        self.assertEqual(parse_codeowners("* @a\nrfcs/ @a @b\n"),
                         [("*", ["@a"]), ("rfcs/", ["@a", "@b"])])

    def test_pattern_without_owner_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "has no owner"):
            parse_codeowners("rfcs/\n")
        with self.assertRaisesRegex(ValueError, "has no owner"):
            parse_codeowners("rfcs/ # owner forgotten\n")

    def test_owner_without_at_sign_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "is not an @handle"):
            parse_codeowners("rfcs/ choiyounggi\n")

    def test_inline_comment_is_dropped(self):
        self.assertEqual(parse_codeowners("rfcs/ @a # spec owners\n"),
                         [("rfcs/", ["@a"])])

    def test_comments_and_blank_lines_are_skipped(self):
        text = "# header\n\n   \n  # indented comment\n* @a\n"
        self.assertEqual(parse_codeowners(text), [("*", ["@a"])])

    def test_empty_text_has_no_rules(self):
        self.assertEqual(parse_codeowners(""), [])

    def test_missing_required_pattern_is_reported(self):
        rules = parse_codeowners("* @choiyounggi\nimpl/lnpl/ @choiyounggi\n.github/ @choiyounggi\n")
        self.assertEqual(missing_patterns(rules), ["rfcs/"])

    def test_foreign_owner_is_reported(self):
        rules = parse_codeowners("rfcs/ @example-user\n")
        self.assertEqual(foreign_owners(rules), [("rfcs/", ["@example-user"])])

    def test_pattern_for_absent_path_is_reported(self):
        rules = parse_codeowners("* @choiyounggi\nno-such-dir-t242/ @choiyounggi\n")
        self.assertEqual(unresolved_paths(rules, REPO), ["no-such-dir-t242/"])

    def test_misplaced_catch_all_is_reported(self):
        self.assertTrue(catch_all_misplaced(parse_codeowners("rfcs/ @a\n* @a\n")))
        self.assertFalse(catch_all_misplaced(parse_codeowners("* @a\nrfcs/ @a\n")))


if __name__ == "__main__":
    unittest.main()
