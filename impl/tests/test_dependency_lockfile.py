"""Hash-pinned lockfile invariants (issue #243)."""
import os
import re
import tomllib
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PYPROJECT_PATH = os.path.join(REPO, "pyproject.toml")
REQ_PATH = os.path.join(REPO, "requirements.txt")
SERVE_PATH = os.path.join(REPO, "requirements-serve.txt")
COVERAGE_PATH = os.path.join(REPO, "requirements-coverage.txt")
AUDIT_PATH = os.path.join(REPO, "requirements-audit.txt")
CI_YML_PATH = os.path.join(REPO, ".github", "workflows", "ci.yml")
WORKFLOWS_DIR = os.path.join(REPO, ".github", "workflows")
DOCKERFILE_PATH = os.path.join(REPO, "docker", "Dockerfile")
DEPLOY_DOCKERFILE_PATH = os.path.join(REPO, "examples", "deploy", "Dockerfile")

COMMANDS = {
    REQ_PATH: "uv pip compile pyproject.toml --extra lint --group build --universal --python-version 3.11 --generate-hashes -o requirements.txt",
    SERVE_PATH: "uv pip compile pyproject.toml --group serve -c requirements.txt --universal --python-version 3.11 --generate-hashes -o requirements-serve.txt",
    COVERAGE_PATH: "uv pip compile --group pyproject.toml:coverage --universal --python-version 3.11 --generate-hashes -o requirements-coverage.txt",
    AUDIT_PATH: "uv pip compile --group pyproject.toml:audit --universal --python-version 3.11 --generate-hashes -o requirements-audit.txt",
}

# Every pip line a workflow or shipping Dockerfile may run, after _normalise.
ALLOWED_WORKFLOW = {
    "pip install --require-hashes -r requirements.txt",
    "pip install --require-hashes -r requirements-serve.txt",
    "pip install --require-hashes -r requirements-coverage.txt",
    "pip install --require-hashes -r requirements-audit.txt",
    "pip wheel --no-deps --no-build-isolation --wheel-dir dist/ci-wheel .",
    "pip install --no-deps dist/ci-wheel/*.whl",
    "python -m build --no-isolation",
}
ALLOWED_DOCKERFILE = {
    "pip install --no-cache-dir --require-hashes -r requirements.txt \\",
    "pip wheel --no-deps --no-build-isolation --wheel-dir /wheels .",
    "pip install --no-cache-dir --require-hashes -r /tmp/requirements-serve.txt \\",
    "pip install --no-cache-dir --no-deps /tmp/*.whl \\",
}

_PIN_RE = re.compile(r"([a-z0-9][a-z0-9._-]*)==([^ ;]+)")
# Any spelling of a pip install/wheel or a build: `pip3`, `python3 -m pip`,
# `python3.13 -m build` all count, so a bare install cannot hide behind one.
_PIP_COMMAND_RE = re.compile(
    r"\bpip3?(\.\d+)?\s+(install|wheel)\b|\bpython3?(\.\d+)?\s+-m\s+(pip|build)\b|--upgrade pip")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def lock_entries(text):
    """`(head, block)` per requirement: a non-indented, non-comment line plus
    the indented `--hash`/`# via` lines that follow it."""
    entries = []
    for line in text.splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            head = line[:-2] if line.endswith(" \\") else line
            entries.append([head.strip(), line])
        elif entries and line[:1].isspace():
            entries[-1][1] += "\n" + line
    return [(head, block) for head, block in entries]


def lock_problems(text):
    entries = lock_entries(text)
    if not entries:
        return ["no requirements"]
    problems = []
    for head, block in entries:
        if re.match(r"[a-z0-9][a-z0-9._-]*==[^ ;]+", head) is None:
            problems.append("%s: not an exact == pin" % head)
        if not re.search(r"--hash=sha256:[0-9a-f]{64}", block):
            name = re.split(r"[=<> ;]", head, maxsplit=1)[0]
            problems.append("%s: no --hash" % name)
    return problems


def pins(text):
    out = {}
    for head, _block in lock_entries(text):
        m = _PIN_RE.match(head)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def group_pin_problems(pyproject, locks):
    groups = {}
    lint = pyproject.get("project", {}).get("optional-dependencies", {}).get("lint")
    if lint is not None:
        groups["lint"] = lint
    for key in ("build", "coverage", "serve", "audit"):
        if key in pyproject.get("dependency-groups", {}):
            groups[key] = pyproject["dependency-groups"][key]
    problems = []
    for key, requirements in groups.items():
        if key not in locks:
            continue
        locked = pins(locks[key])
        for requirement in requirements:
            name, sep, version = requirement.partition("==")
            if not sep:
                continue
            if name not in locked:
                problems.append("%s: group pins %s, lock has no entry" % (name, version))
            elif locked[name] != version:
                problems.append("%s: group pins %s, lock pins %s" % (name, version, locked[name]))
    return problems


def pip_audit_job_problems(ci_text):
    start = ci_text.find("\n  pip-audit:\n")
    if start < 0:
        return ["no pip-audit job"]
    nxt = re.search(r"\n  [A-Za-z0-9_-]+:\n", ci_text[start + 1:])
    job = ci_text[start:start + 1 + nxt.start()] if nxt else ci_text[start:]
    problems = []
    if "    name: pip-audit (lockfiles)\n" not in job:
        problems.append("not named pip-audit (lockfiles)")
    if "    permissions:\n      contents: read\n    steps:" not in job:
        problems.append("permissions is not exactly contents: read")
    if 'python-version: "3.11"' not in job:
        problems.append("python is not 3.11")
    if "run: pip install --require-hashes -r requirements-audit.txt\n" not in job:
        problems.append("pip-audit is not installed from requirements-audit.txt")
    if ("run: pip-audit --require-hashes -r requirements.txt -r requirements-serve.txt"
            " -r requirements-coverage.txt -r requirements-audit.txt") not in job:
        problems.append("audit command does not cover the four lockfiles")
    if "continue-on-error" in job:
        problems.append("continue-on-error set")
    return problems


def _normalise(line):
    line = line.strip()
    for prefix in ("run: ", "RUN ", "&& "):
        if line.startswith(prefix):
            line = line[len(prefix):]
    return line


def pip_problems(text, filename, allowed):
    problems = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        if _PIP_COMMAND_RE.search(line):
            if _normalise(line) not in allowed:
                problems.append("%s:%d: %s" % (filename, lineno, line.strip()))
    return problems


def unpinned_base_images(text):
    """`FROM` lines whose image carries no `@sha256:` digest."""
    return [line.strip() for line in text.splitlines()
            if line.startswith("FROM ") and "@sha256:" not in line.split()[1]]


class LockProblemsTest(unittest.TestCase):
    def test_real_lockfiles_have_no_problems(self):
        for path in (REQ_PATH, SERVE_PATH, COVERAGE_PATH, AUDIT_PATH):
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual(lock_problems(_read(path)), [])

    def test_range_requirement_is_reported(self):
        text = "jsonschema>=4.0\n    --hash=sha256:" + "0" * 64 + "\n"
        self.assertEqual(lock_problems(text), ["jsonschema>=4.0: not an exact == pin"])

    def test_entry_without_hash_is_reported(self):
        self.assertEqual(
            lock_problems("attrs==26.1.0\n    # via referencing\n"),
            ["attrs: no --hash"],
        )

    def test_empty_and_comment_only_text_report_no_requirements(self):
        for text in ("", "# header\n#    more\n"):
            with self.subTest(text=text):
                self.assertEqual(lock_problems(text), ["no requirements"])


class LockHeaderTest(unittest.TestCase):
    def test_each_header_records_its_exact_command(self):
        for path, command in COMMANDS.items():
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual(_read(path).splitlines()[1], "#    " + command)


class LockMembershipTest(unittest.TestCase):
    def test_requirements_keeps_the_311_floor(self):
        heads = [h for h, _ in lock_entries(_read(REQ_PATH)) if h.startswith("typing-extensions==")]
        self.assertEqual(len(heads), 1, heads)
        self.assertIn("; python_full_version < '3.13'", heads[0])

    def test_each_tool_lives_only_in_its_lockfile(self):
        locks = {path: pins(_read(path)) for path in (REQ_PATH, SERVE_PATH, COVERAGE_PATH, AUDIT_PATH)}
        homes = {"ruff": REQ_PATH, "build": REQ_PATH, "hatchling": REQ_PATH,
                 "gunicorn": SERVE_PATH, "coverage": COVERAGE_PATH, "pip-audit": AUDIT_PATH}
        for tool, home in homes.items():
            for path, locked in locks.items():
                with self.subTest(tool=tool, lock=os.path.basename(path)):
                    self.assertEqual(tool in locked, path == home)

    def test_serve_repeats_requirements_pins_exactly(self):
        req = pins(_read(REQ_PATH))
        serve = pins(_read(SERVE_PATH))
        self.assertIn("gunicorn", serve)
        for name, version in serve.items():
            if name == "gunicorn":
                continue
            with self.subTest(name=name):
                self.assertEqual(req.get(name), version)


class GroupPinTest(unittest.TestCase):
    def test_real_groups_match_their_lockfiles(self):
        with open(PYPROJECT_PATH, "rb") as fh:
            pyproject = tomllib.load(fh)
        locks = {"lint": _read(REQ_PATH), "build": _read(REQ_PATH), "serve": _read(SERVE_PATH),
                 "coverage": _read(COVERAGE_PATH), "audit": _read(AUDIT_PATH)}
        self.assertEqual(group_pin_problems(pyproject, locks), [])

    def test_stale_group_pin_is_reported(self):
        pyproject = {"dependency-groups": {"coverage": ["coverage==7.16.0"]}, "project": {}}
        self.assertEqual(
            group_pin_problems(pyproject, {"coverage": _read(COVERAGE_PATH)}),
            ["coverage: group pins 7.16.0, lock pins 7.17.0"],
        )

    def test_group_pin_missing_from_lock_is_reported(self):
        pyproject = {"dependency-groups": {"serve": ["waitress==3.0.2"]}, "project": {}}
        self.assertEqual(
            group_pin_problems(pyproject, {"serve": _read(SERVE_PATH)}),
            ["waitress: group pins 3.0.2, lock has no entry"],
        )

    def test_no_groups_is_empty(self):
        self.assertEqual(group_pin_problems({"project": {}}, {"serve": _read(SERVE_PATH)}), [])


class PipAuditJobTest(unittest.TestCase):
    def test_real_job_has_no_problems(self):
        self.assertEqual(pip_audit_job_problems(_read(CI_YML_PATH)), [])

    def test_advisory_mode_is_reported(self):
        name = "    name: pip-audit (lockfiles)\n"
        text = _read(CI_YML_PATH).replace(name, name + "    continue-on-error: true\n", 1)
        self.assertEqual(pip_audit_job_problems(text), ["continue-on-error set"])

    def test_wrong_python_is_reported(self):
        text = _read(CI_YML_PATH)
        start = text.index("\n  pip-audit:\n")
        text = text[:start] + text[start:].replace('"3.11"', '"3.13"')
        self.assertEqual(pip_audit_job_problems(text), ["python is not 3.11"])

    def test_missing_job_is_reported(self):
        self.assertEqual(pip_audit_job_problems("jobs:\n  gate:\n"), ["no pip-audit job"])


class PipCommandTest(unittest.TestCase):
    def _sources(self):
        sources = [(os.path.join(WORKFLOWS_DIR, name), ALLOWED_WORKFLOW)
                   for name in sorted(os.listdir(WORKFLOWS_DIR)) if name.endswith(".yml")]
        sources += [(DOCKERFILE_PATH, ALLOWED_DOCKERFILE), (DEPLOY_DOCKERFILE_PATH, ALLOWED_DOCKERFILE)]
        return sources

    def test_every_pip_command_is_hash_pinned(self):
        for path, allowed in self._sources():
            with self.subTest(path=os.path.relpath(path, REPO)):
                self.assertEqual(pip_problems(_read(path), os.path.basename(path), allowed), [])

    def test_scan_found_install_lines(self):
        scanned = [os.path.join(WORKFLOWS_DIR, name) for name in
                   ("ci.yml", "release.yml", "mutation.yml", "load-weekly.yml", "_ai-gate.yml")]
        scanned += [DOCKERFILE_PATH, DEPLOY_DOCKERFILE_PATH]
        for path in scanned:
            with self.subTest(path=os.path.relpath(path, REPO)):
                lines = [line for line in _read(path).splitlines()
                         if "pip install" in line and not line.lstrip().startswith("#")]
                self.assertGreaterEqual(len(lines), 1)

    def test_bare_installs_are_reported(self):
        cases = [
            ("        run: pip install .", ALLOWED_WORKFLOW),
            ("        run: python -m pip install --upgrade pip && pip install build", ALLOWED_WORKFLOW),
            ("        run: pip3 install .", ALLOWED_WORKFLOW),
            ("        run: python3 -m build", ALLOWED_WORKFLOW),
            ("          python3.13 -m pip install -r requirements.txt", ALLOWED_WORKFLOW),
            ("RUN pip install --no-cache-dir /tmp/*.whl gunicorn && rm -rf /tmp/*.whl", ALLOWED_DOCKERFILE),
        ]
        for line, allowed in cases:
            with self.subTest(line=line):
                self.assertEqual(pip_problems(line + "\n", "x", allowed), ["x:1: " + line.strip()])

    def test_comment_and_empty_text_are_ignored(self):
        self.assertEqual(pip_problems("", "x.yml", ALLOWED_WORKFLOW), [])
        self.assertEqual(pip_problems("        # pip install .\n", "x.yml", ALLOWED_WORKFLOW), [])

    def test_lookalike_commands_are_not_pip_installs(self):
        text = "        run: pipx install foo\n        run: python -m pip_audit --help\n"
        self.assertEqual(pip_problems(text, "x.yml", ALLOWED_WORKFLOW), [])


class BaseImageDigestTest(unittest.TestCase):
    def test_shipping_dockerfiles_pin_every_base_by_digest(self):
        for path in (DOCKERFILE_PATH, DEPLOY_DOCKERFILE_PATH):
            with self.subTest(path=os.path.relpath(path, REPO)):
                text = _read(path)
                self.assertEqual(len([line for line in text.splitlines() if line.startswith("FROM ")]), 2)
                self.assertEqual(unpinned_base_images(text), [])

    def test_tag_only_base_is_reported(self):
        text = "FROM python:3.13-slim-bookworm AS builder\nFROM python:3.13-slim-bookworm@sha256:" + "0" * 64 + "\n"
        self.assertEqual(unpinned_base_images(text), ["FROM python:3.13-slim-bookworm AS builder"])

    def test_no_from_line_is_empty(self):
        self.assertEqual(unpinned_base_images(""), [])
        self.assertEqual(unpinned_base_images("# FROM python:3.13\n"), [])


if __name__ == "__main__":
    unittest.main()
