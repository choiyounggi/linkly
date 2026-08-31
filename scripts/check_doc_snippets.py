#!/usr/bin/env python3
"""Verify that ```lnpl code blocks embedded in repo prose actually compile.

`.lnpl` has a closed vocabulary, so a plausible-looking but wrong verb parses
fine and does nothing at runtime — RFC/README/docs prose is exempt from any
compiler today. This gate extracts every ```lnpl fenced block under
rfcs/**/*.md, docs/**/*.md, plugins/**/*.md, README.md and README.ko.md, and
compiles each one standalone with the existing `lnpl compile` CLI.

A block that is intentionally partial (a fragment, a `...` placeholder, or an
example demonstrating a rejected form) is marked with an HTML comment
directly above its fence:

    <!-- lnpl-check: skip — <reason> -->
    <!-- lnpl-check: prelude <repo-relative .lnpl path> -->

`skip` requires a non-empty reason and is rejected (as a violation, not a
pass) once the block actually compiles — a marker is not a permanent
exemption. `prelude` compiles the named file's contents ahead of the block's
own body, for fragments that need earlier context from a real file. A block
with no marker must compile standalone.

Exit codes: 0 pass, 1 violation(s) found, 2 usage/environment error.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IMPL_DIR = REPO_ROOT / "impl"

TARGET_DIR_GLOBS = ["rfcs/**/*.md", "docs/**/*.md", "plugins/**/*.md"]
TARGET_ROOT_FILES = ["README.md", "README.ko.md"]

FENCE_START_RE = re.compile(r"^```lnpl\s*$")
FENCE_END_RE = re.compile(r"^```\s*$")
MARKER_RE = re.compile(r"^<!--\s*lnpl-check:\s*(.+?)\s*-->\s*$")
LEADING_DASH_RE = re.compile(r"^[-—]+\s*")


class Violation:
    def __init__(self, path, line, message):
        self.path = path
        self.line = line
        self.message = message

    def format(self, repo_root):
        try:
            rel = self.path.relative_to(repo_root)
        except ValueError:
            rel = self.path
        return f"{rel}:{self.line} — {self.message}"


def find_target_files(repo_root):
    files = set()
    for pattern in TARGET_DIR_GLOBS:
        files.update(p for p in repo_root.glob(pattern) if p.is_file())
    for name in TARGET_ROOT_FILES:
        p = repo_root / name
        if p.is_file():
            files.add(p)
    return sorted(files)


def extract_blocks(path):
    """Return every ```lnpl block in `path` as {path, line, body, marker}.

    `line` is the fence's own 1-indexed line number. `marker` is the parsed
    directive text (everything between `lnpl-check:` and `-->`) of the
    nearest non-blank line above the fence, or None.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks = []
    i, n = 0, len(lines)
    while i < n:
        if FENCE_START_RE.match(lines[i]):
            start_line = i + 1
            j = i + 1
            body = []
            while j < n and not FENCE_END_RE.match(lines[j]):
                body.append(lines[j])
                j += 1
            marker = None
            k = i - 1
            while k >= 0 and lines[k].strip() == "":
                k -= 1
            if k >= 0:
                m = MARKER_RE.match(lines[k].strip())
                if m:
                    marker = m.group(1).strip()
            blocks.append({"path": path, "line": start_line, "body": body, "marker": marker})
            i = j + 1
        else:
            i += 1
    return blocks


def _compile_env():
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([str(IMPL_DIR)] + ([existing] if existing else []))
    return env


def compile_source(source_text):
    """Compile `source_text` as a standalone .lnpl file. Returns (ok, first error line or None).

    Uses `--strict=warning` so an unknown verb (parses, runs as a silent no-op
    — the platform's dominant failure mode per AGENTS.md) fails the compile
    instead of passing with a warning. The compiler's own exit code (0/2) is
    never surfaced as this script's exit code — callers only see this (ok,
    message) pair, and check_doc_snippets.py's own exit codes (0/1/2) mean
    something else entirely (pass/violation/usage-error).
    """
    with tempfile.TemporaryDirectory() as td:
        snippet_path = Path(td) / "snippet.lnpl"
        snippet_path.write_text(source_text, encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "lnpl", "compile", "--strict=warning", str(snippet_path)],
            capture_output=True,
            text=True,
            env=_compile_env(),
        )
    if proc.returncode == 0:
        return True, None
    output = (proc.stderr or proc.stdout or "").strip()
    first_line = output.splitlines()[0] if output else "(no compiler output)"
    return False, first_line


def check_block(block, repo_root):
    body_text = "\n".join(block["body"]) + "\n"
    marker = block["marker"]
    path, line = block["path"], block["line"]

    if marker is None:
        ok, msg = compile_source(body_text)
        if ok:
            return []
        return [Violation(path, line, msg)]

    directive, _, rest = marker.partition(" ")
    rest = rest.strip()

    if directive == "skip":
        reason = LEADING_DASH_RE.sub("", rest).strip()
        if not reason:
            return [Violation(path, line, "lnpl-check: skip requires a reason (`skip — <reason>`)")]
        ok, _msg = compile_source(body_text)
        if ok:
            return [Violation(
                path, line,
                f"lnpl-check: stale skip — block now compiles cleanly (reason was: {reason})",
            )]
        return []

    if directive == "prelude":
        if not rest:
            return [Violation(path, line, "lnpl-check: prelude requires a repo-relative .lnpl path")]
        prelude_path = repo_root / rest
        if not prelude_path.is_file():
            return [Violation(path, line, f"lnpl-check: prelude path does not exist: {rest}")]
        prelude_text = prelude_path.read_text(encoding="utf-8")
        full_text = prelude_text.rstrip("\n") + "\n" + body_text
        ok, msg = compile_source(full_text)
        if ok:
            return []
        return [Violation(path, line, msg)]

    return [Violation(path, line, f"lnpl-check: unknown lnpl-check directive '{directive}'")]


def check_files(files, repo_root):
    violations = []
    total_blocks = 0
    for f in files:
        for block in extract_blocks(f):
            total_blocks += 1
            violations.extend(check_block(block, repo_root))
    return total_blocks, violations


def _run_git(args, repo_root):
    return subprocess.run(["git"] + args, cwd=str(repo_root), capture_output=True, text=True)


def is_shallow_repo(repo_root):
    proc = _run_git(["rev-parse", "--is-shallow-repository"], repo_root)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def changed_target_files(base_ref, repo_root):
    """Return (sorted changed target-scope files relative to repo_root, error)."""
    mb = _run_git(["merge-base", base_ref, "HEAD"], repo_root)
    if mb.returncode != 0:
        return None, f"git merge-base against '{base_ref}' failed: {mb.stderr.strip()}"
    merge_base = mb.stdout.strip()
    diff = _run_git(["diff", "--name-only", "--diff-filter=d", merge_base, "HEAD"], repo_root)
    if diff.returncode != 0:
        return None, f"git diff failed: {diff.stderr.strip()}"
    changed = [line.strip() for line in diff.stdout.splitlines() if line.strip()]
    allowed = {str(p.relative_to(repo_root)) for p in find_target_files(repo_root)}
    return sorted(f for f in changed if f in allowed), None


def main(argv=None, repo_root=None):
    parser = argparse.ArgumentParser(prog="check_doc_snippets.py")
    parser.add_argument("--changed-only", action="store_true")
    parser.add_argument("--base")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if exc.code is not None else 2

    if repo_root is None:
        repo_root = REPO_ROOT
    repo_root = Path(repo_root)

    if args.changed_only and not args.base:
        print("error: --changed-only requires --base <ref>", file=sys.stderr)
        return 2
    if args.base and not args.changed_only:
        print("error: --base requires --changed-only", file=sys.stderr)
        return 2

    if args.changed_only:
        if is_shallow_repo(repo_root):
            print(
                "skip: shallow repository (git rev-parse --is-shallow-repository) — "
                "cannot resolve merge-base for --changed-only"
            )
            return 0
        changed, err = changed_target_files(args.base, repo_root)
        if err is not None:
            print(f"error: {err}", file=sys.stderr)
            return 2
        if not changed:
            print("no .md files changed — skipped")
            return 0
        print(f"checking {len(changed)} changed file(s):")
        for f in changed:
            print(f"  {f}")
        files = [repo_root / f for f in changed]
    else:
        files = find_target_files(repo_root)
        print(f"checking {len(files)} target file(s)")

    total_blocks, violations = check_files(files, repo_root)
    print(f"{total_blocks} lnpl block(s) examined")

    if violations:
        print(f"{len(violations)} violation(s):")
        for v in violations:
            print(f"  {v.format(repo_root)}")
        return 1

    print("all lnpl blocks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
