#!/usr/bin/env python3
"""Coverage totals and diff coverage as markdown, for the advisory CI job (issue #247).

    python3 scripts/diff_coverage.py --coverage-json coverage.json [--diff pr.diff]

`--coverage-json` is the output of `coverage json`. `--diff` is a
`git diff --unified=0` of the change; its changed executable lines are the
added lines of each `.py` file that coverage.py counts as statements
(executed_lines + missing_lines). Prints markdown to stdout and exits 0
whatever the percentages are — the job is advisory. Exits 2 with a
`diff_coverage: error:` line on stderr when an input cannot be read.
A diff that adds no `.py` lines prints an explicit line instead of a table
(wiki/infrastructure/ci-cd/changed-files-only-gates.md: an empty change set
must never read like a measured one).
"""
import argparse
import json
import re
import sys

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class InputError(Exception):
    pass


def parse_added_lines(diff_text):
    """{path: sorted added line numbers} for `.py` files, from hunk headers."""
    added = {}
    current = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
                path = path[1:-1]
            if path == "/dev/null":
                current = None
                continue
            if path.startswith("b/"):
                path = path[2:]
            current = path if path.endswith(".py") else None
            continue
        match = HUNK_RE.match(line)
        if match and current is not None:
            start = int(match.group(1))
            count = 1 if match.group(2) is None else int(match.group(2))
            if count:
                added.setdefault(current, set()).update(range(start, start + count))
    return {path: sorted(lines) for path, lines in added.items() if lines}


def diff_rows(added, files):
    rows = []
    for path in sorted(added):
        if path not in files:
            rows.append({"path": path, "status": "unmeasured", "changed": 0,
                         "covered": 0, "missed": []})
            continue
        entry = files[path]
        if not isinstance(entry, dict) or not isinstance(entry.get("executed_lines"), list) \
                or not isinstance(entry.get("missing_lines"), list):
            raise InputError("coverage json files[%s] lacks executed_lines/missing_lines" % path)
        executed = set(entry["executed_lines"])
        executable = executed | set(entry["missing_lines"])
        changed = [n for n in added[path] if n in executable]
        covered = [n for n in changed if n in executed]
        rows.append({"path": path, "status": "measured", "changed": len(changed),
                     "covered": len(covered),
                     "missed": sorted(set(changed) - set(covered))})
    return rows


def ranges(numbers):
    if not numbers:
        return "-"
    parts = []
    start = prev = numbers[0]
    for n in numbers[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else "%d-%d" % (start, prev))
        start = prev = n
    parts.append(str(start) if start == prev else "%d-%d" % (start, prev))
    return ", ".join(parts)


def _pct(num, den):
    return "%.2f%%" % (100.0 * num / den)


def totals_lines(totals):
    statements = totals["num_statements"]
    covered = totals["covered_lines"]
    if statements:
        line = "- Line coverage: %s (%d/%d statements)" % (_pct(covered, statements), covered, statements)
    else:
        line = "- Line coverage: n/a (0 statements measured)"
    if "num_branches" not in totals or "covered_branches" not in totals:
        branch = "- Branch coverage: n/a (not measured; run coverage with --branch)"
    elif totals["num_branches"] == 0:
        branch = "- Branch coverage: n/a (0 branches measured)"
    else:
        branch = "- Branch coverage: %s (%d/%d branches)" % (
            _pct(totals["covered_branches"], totals["num_branches"]),
            totals["covered_branches"], totals["num_branches"])
    return [line, branch]


def render(totals, rows, diff_given):
    out = ["## Coverage (advisory)", ""] + totals_lines(totals)
    if diff_given:
        out += ["", "### Diff coverage (changed executable lines)", ""]
        if not rows:
            out.append("No measured files changed: the diff adds 0 lines to .py files.")
        else:
            out += ["| File | Changed executable lines | Covered | Missed lines |",
                    "|---|---|---|---|"]
            for row in rows:
                if row["status"] == "unmeasured":
                    out.append("| %s | unmeasured | - | not in coverage.json |" % row["path"])
                else:
                    out.append("| %s | %d | %d | %s |" % (row["path"], row["changed"],
                                                       row["covered"], ranges(row["missed"])))
            changed = sum(r["changed"] for r in rows)
            covered = sum(r["covered"] for r in rows)
            out.append("")
            if changed:
                out.append("Diff coverage: %s (%d/%d changed executable lines)"
                           % (_pct(covered, changed), covered, changed))
            else:
                out.append("Diff coverage: n/a (0 changed executable lines)")
    return "\n".join(out) + "\n"


def _read(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise InputError("cannot read %s %s: %s" % (what, path, exc))


def load_coverage(path):
    try:
        data = json.loads(_read(path, "coverage json"))
    except ValueError as exc:
        raise InputError("coverage json %s is not valid JSON: %s" % (path, exc))
    totals = data.get("totals") if isinstance(data, dict) else None
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(totals, dict) or not isinstance(files, dict):
        raise InputError("coverage json %s lacks totals/files" % path)
    for key in ("covered_lines", "num_statements"):
        if not isinstance(totals.get(key), int):
            raise InputError("coverage json %s lacks totals.%s" % (path, key))
    return totals, files


def main(argv):
    parser = argparse.ArgumentParser(prog="diff_coverage.py")
    parser.add_argument("--coverage-json", required=True)
    parser.add_argument("--diff")
    args = parser.parse_args(argv)
    try:
        totals, files = load_coverage(args.coverage_json)
        rows = []
        if args.diff is not None:
            rows = diff_rows(parse_added_lines(_read(args.diff, "diff")), files)
    except InputError as exc:
        print("diff_coverage: error: %s" % exc, file=sys.stderr)
        return 2
    sys.stdout.write(render(totals, rows, args.diff is not None))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
