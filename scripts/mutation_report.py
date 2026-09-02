#!/usr/bin/env python3
"""Parses mutation_check.py's stdout into SURVIVED vs STALE/HANG buckets
(issue #166). SURVIVED mutations are reported as an "미검증 규칙" issue body,
never as a job failure. STALE/HANG mean the harness itself could not judge —
those make the caller's job fail (mutation_check.py's own verdict vocabulary,
preserved unmodified).
"""
import re
import sys

_SURVIVED_RE = re.compile(r"^\s*- (.+) \[SURVIVED — no test asserts this rule\]$")
_STALE_RE = re.compile(r"^\s*- (.+) \[stale anchor\]$")
_HANG_RE = re.compile(r"^\s*- (.+) \[hangs instead of failing\]$")


def parse(stdout_text):
    """Returns {"survived": [...], "stale": [...], "hang": [...], "harness_ok": bool}."""
    survived, stale, hang = [], [], []
    for line in stdout_text.splitlines():
        m = _SURVIVED_RE.match(line)
        if m:
            survived.append(m.group(1))
            continue
        m = _STALE_RE.match(line)
        if m:
            stale.append(m.group(1))
            continue
        m = _HANG_RE.match(line)
        if m:
            hang.append(m.group(1))
    return {"survived": survived, "stale": stale, "hang": hang,
            "harness_ok": not stale and not hang}


def format_issue_body(result):
    if not result["survived"]:
        return ("No mutations survived this week's full run — every rule "
                "the harness covers is still asserted somewhere.")
    lines = ["The following rules have no failing test (SURVIVED this "
             "week's mutation run) — 미검증 규칙, not a CI failure:", ""]
    lines += ["- %s" % label for label in result["survived"]]
    return "\n".join(lines)


def main(argv):
    # --rc N: mutation_check.py's own exit code, captured by the workflow.
    # Fail CLOSED (D14): a nonzero rc that no SURVIVED line explains means
    # the harness itself died before judging (baseline not green, no-op
    # control caught, crash) - that must fail this gate, not read as
    # "nothing survived".
    rc = None
    args = list(argv)
    if "--rc" in args:
        i = args.index("--rc")
        rc = int(args[i + 1])
    text = sys.stdin.read()
    result = parse(text)
    unexplained_rc = (rc is not None and rc != 0 and not result["survived"]
                      and not result["stale"] and not result["hang"])
    healthy = result["harness_ok"] and not unexplained_rc
    if healthy:
        print(format_issue_body(result))
    else:
        print("HARNESS-INTEGRITY FAULT - stale=%d hang=%d rc=%s "
              "(no issue update; see job log)" %
              (len(result["stale"]), len(result["hang"]), rc))
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
