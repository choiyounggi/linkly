"""Every external action in .github/workflows is pinned to a commit SHA (issue #243)."""
import glob
import os
import re
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOWS_DIR = os.path.join(REPO, ".github", "workflows")
DEPENDABOT_PATH = os.path.join(REPO, ".github", "dependabot.yml")

USES_LINE = re.compile(r"\s*(?:-\s+)?uses:\s*(?P<value>.*?)\s*")
PINNED = re.compile(
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*@[0-9a-f]{40} # v\d+\.\d+\.\d+")

SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"


def scan_uses(text, filename):
    """`(problems, pinned_count)`: one `file:line: value` problem per external
    `uses:` that is not `owner/repo@<40-hex> # vX.Y.Z`; local `./` refs and
    comment lines are exempt."""
    problems = []
    pinned_count = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        m = USES_LINE.fullmatch(line)
        if m is None:
            continue
        value = m.group("value")
        if value.startswith("./"):
            continue
        if PINNED.fullmatch(value):
            pinned_count += 1
        else:
            problems.append("%s:%d: %s" % (filename, lineno, value))
    return problems, pinned_count


def dependabot_problems(text):
    """Every way `text` falls short of weekly `pip` + `github-actions`
    updates at `/` (issue #243). Plain text, not YAML: CI installs only the
    lockfile, which has no YAML parser. Each entry runs from its
    `  - package-ecosystem:` line to the next one.
    """
    problems = []
    if not re.search(r"(?m)^version: 2$", text):
        problems.append("version is not 2")
    entries = {}
    for block in re.split(r"(?m)^(?=  - package-ecosystem: )", text)[1:]:
        m = re.match(r'  - package-ecosystem: "([^"]+)"\n', block)
        if m:
            entries[m.group(1)] = block
    for ecosystem in ("pip", "github-actions"):
        block = entries.get(ecosystem)
        if block is None:
            problems.append("missing ecosystem %s" % ecosystem)
            continue
        if '\n    directory: "/"\n' not in block:
            problems.append("%s: directory is not /" % ecosystem)
        if '\n      interval: "weekly"' not in block:
            problems.append("%s: interval is not weekly" % ecosystem)
    return problems


def _workflow_paths():
    return sorted(glob.glob(os.path.join(WORKFLOWS_DIR, "*.yml"))
                  + glob.glob(os.path.join(WORKFLOWS_DIR, "*.yaml")))


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class WorkflowActionPinTest(unittest.TestCase):
    def test_every_external_uses_in_the_real_workflows_is_pinned(self):
        paths = _workflow_paths()
        self.assertTrue(paths)
        problems = []
        total_pinned = 0
        for path in paths:
            found, pinned = scan_uses(_read(path), os.path.basename(path))
            problems += found
            total_pinned += pinned
        self.assertEqual(problems, [])
        self.assertGreaterEqual(total_pinned, 32)

    def test_floating_tag_is_reported_with_file_and_line(self):
        self.assertEqual(
            scan_uses("steps:\n      - uses: actions/checkout@v7\n", "ci.yml"),
            (["ci.yml:2: actions/checkout@v7"], 0),
        )

    def test_valid_pin_counts_and_reports_nothing(self):
        for text in ("      - uses: actions/checkout@%s # v7.0.1\n" % SHA,
                     "        uses: actions/checkout@%s # v7.0.1\n" % SHA):
            with self.subTest(text=text):
                self.assertEqual(scan_uses(text, "x.yml"), ([], 1))

    def test_comments_and_local_refs_are_exempt(self):
        text = ("# t4 uses: ./.github/workflows/_ai-gate.yml\n"
                "    uses: ./.github/workflows/_ai-gate.yml\n"
                "      # - uses: actions/checkout@v7\n")
        self.assertEqual(scan_uses(text, "x.yml"), ([], 0))

    def test_near_miss_pins_are_reported(self):
        values = [
            "actions/checkout@%s # v7.0.1" % SHA[:39],
            "actions/checkout@%s # v7.0.1" % (SHA + "0"),
            "actions/checkout@%s # v7.0.1" % SHA.upper(),
            "actions/checkout@" + SHA,
            "actions/checkout@%s # v7" % SHA,
            "actions/checkout@main # v7.0.1",
            '"actions/checkout@%s # v7.0.1' % SHA,
            "actions/checkout@%s # v7.0.1 # v6" % SHA,
        ]
        for value in values:
            with self.subTest(value=value):
                problems, pinned = scan_uses("      - uses: " + value + "\n", "x.yml")
                self.assertEqual(problems, ["x.yml:1: " + value])
                self.assertEqual(pinned, 0)

    def test_empty_text_has_nothing(self):
        self.assertEqual(scan_uses("", "x.yml"), ([], 0))


class DependabotConfigTest(unittest.TestCase):
    def test_real_config_updates_pip_and_actions_weekly(self):
        self.assertEqual(dependabot_problems(_read(DEPENDABOT_PATH)), [])

    def test_dropped_ecosystem_is_reported(self):
        text = _read(DEPENDABOT_PATH)
        start = text.index('  - package-ecosystem: "github-actions"')
        self.assertEqual(dependabot_problems(text[:start]),
                         ["missing ecosystem github-actions"])

    def test_wrong_interval_and_directory_are_reported(self):
        text = _read(DEPENDABOT_PATH).replace('interval: "weekly"', 'interval: "daily"', 1)
        text = text.replace('directory: "/"', 'directory: "/impl"', 1)
        self.assertEqual(dependabot_problems(text),
                         ["pip: directory is not /", "pip: interval is not weekly"])

    def test_empty_text_reports_everything(self):
        self.assertEqual(dependabot_problems(""),
                         ["version is not 2", "missing ecosystem pip",
                          "missing ecosystem github-actions"])


if __name__ == "__main__":
    unittest.main()
