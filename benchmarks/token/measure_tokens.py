#!/usr/bin/env python3
"""measure_tokens.py — issues #142 and #251 token benchmark, deterministic output.

Prints one JSON object to stdout: source token counts for six scenarios
(checkout, consume, schedule, parallel, cached, linkhub), each as LNPL vs its
FastAPI port in equiv/, plus edit-token counts for five edit kinds in edits/
(m1_note_field, m2_duplicate_guard, m3_add_workflow, m4_cached_read,
m5_timeout_policy). Two runs on an unchanged tree produce byte-identical stdout
(REPORT.md's numbers are this output, pasted verbatim — see the BEGIN/END
markers there; hand edits inside them are forbidden).

Run from the project's own venv, never the repo's: this needs tiktoken,
which is not (and must not become) a project dependency — see PROTOCOL.md.
"""

import difflib
import json
import sys
from pathlib import Path

import tiktoken

TOKENIZERS = ("o200k_base", "cl100k_base")

BASE_DIR = Path(__file__).resolve().parent          # benchmarks/token
REPO_ROOT = BASE_DIR.parent.parent                   # repo root

SCENARIOS = {
    "checkout": {"lnpl": REPO_ROOT / "examples" / "checkout.lnpl", "fastapi": BASE_DIR / "equiv" / "checkout_fastapi.py"},
    "consume": {"lnpl": BASE_DIR / "scenarios" / "consume.lnpl", "fastapi": BASE_DIR / "equiv" / "consume_fastapi.py"},
    "schedule": {"lnpl": BASE_DIR / "scenarios" / "schedule.lnpl", "fastapi": BASE_DIR / "equiv" / "schedule_fastapi.py"},
    "parallel": {"lnpl": BASE_DIR / "scenarios" / "parallel.lnpl", "fastapi": BASE_DIR / "equiv" / "parallel_fastapi.py"},
    "cached": {"lnpl": BASE_DIR / "scenarios" / "cached.lnpl", "fastapi": BASE_DIR / "equiv" / "cached_fastapi.py"},
    "linkhub": {"lnpl": BASE_DIR / "scenarios" / "linkhub.lnpl", "fastapi": BASE_DIR / "equiv" / "linkhub_fastapi.py"},
}
EDIT_KINDS = ("m1_note_field", "m2_duplicate_guard", "m3_add_workflow", "m4_cached_read", "m5_timeout_policy")
EDIT_BASELINES = {"m1_note_field": "linkhub", "m2_duplicate_guard": "linkhub", "m3_add_workflow": "cached",
                  "m4_cached_read": "consume", "m5_timeout_policy": "schedule"}


def _edit_paths(kind):
    d = BASE_DIR / "edits" / kind
    return {
        "lnpl": (d / "lnpl_before.lnpl", d / "lnpl_after.lnpl"),
        "fastapi": (d / "fastapi_before.py", d / "fastapi_after.py"),
    }


EDIT_TASKS = {kind: _edit_paths(kind) for kind in EDIT_KINDS}


def _encodings():
    return {name: tiktoken.get_encoding(name) for name in TOKENIZERS}


def count_tokens(text, encoding):
    return len(encoding.encode(text))


def char_stats(text):
    return {
        "chars": len(text),
        "chars_no_whitespace": len("".join(text.split())),
    }


def measure_text(text, encodings):
    result = dict(char_stats(text))
    for name, enc in encodings.items():
        result[f"tokens_{name}"] = count_tokens(text, enc)
    return result


def measure_file(path, encodings):
    text = path.read_text(encoding="utf-8")
    result = measure_text(text, encodings)
    result["path"] = str(path.relative_to(REPO_ROOT))
    return result


def diff_lines(before_text, after_text):
    """Added/removed content lines (no diff markers), stdlib difflib."""
    before_lines = before_text.splitlines()
    after_lines = after_text.splitlines()
    added, removed = [], []
    for line in difflib.unified_diff(before_lines, after_lines, lineterm=""):
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added.append(line[1:])
        elif line.startswith("-"):
            removed.append(line[1:])
    return added, removed


def measure_edit_pair(before_path, after_path, encodings):
    before_text = before_path.read_text(encoding="utf-8")
    after_text = after_path.read_text(encoding="utf-8")
    added, removed = diff_lines(before_text, after_text)
    added_text = "\n".join(added)
    removed_text = "\n".join(removed)

    result = {
        "before_path": str(before_path.relative_to(REPO_ROOT)),
        "after_path": str(after_path.relative_to(REPO_ROOT)),
        "added_lines": len(added),
        "removed_lines": len(removed),
    }
    for name, enc in encodings.items():
        added_tokens = count_tokens(added_text, enc) if added else 0
        removed_tokens = count_tokens(removed_text, enc) if removed else 0
        result[f"added_tokens_{name}"] = added_tokens
        result[f"removed_tokens_{name}"] = removed_tokens
        result[f"edit_tokens_{name}"] = added_tokens + removed_tokens
    return result


def build_report():
    encodings = _encodings()

    source_tokens = {
        sid: {side: measure_file(path, encodings) for side, path in sides.items()}
        for sid, sides in SCENARIOS.items()
    }

    edit_tokens = {}
    for task_name, sides in EDIT_TASKS.items():
        edit_tokens[task_name] = {
            side: measure_edit_pair(before, after, encodings)
            for side, (before, after) in sides.items()
        }

    return {
        "tiktoken_version": tiktoken.__version__,
        "tokenizers": list(TOKENIZERS),
        "source_tokens": source_tokens,
        "edit_tokens": edit_tokens,
    }


def render_json(report):
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def extract_report_block(text):
    """The fenced JSON between REPORT.md's BEGIN marker and its closing fence."""
    lines = text.splitlines(keepends=True)
    i = next((n for n, line in enumerate(lines) if "<!-- BEGIN measure_tokens.py output" in line), None)
    j = None if i is None else next(
        (n for n in range(i + 1, len(lines)) if lines[n].rstrip("\n") == "```json"), None)
    k = None if j is None else next(
        (n for n in range(j + 1, len(lines)) if lines[n].rstrip("\n") == "```"), None)
    if k is None:
        raise ValueError("REPORT.md has no measure_tokens.py output block")
    return "".join(lines[j + 1:k])


def main():
    sys.stdout.write(render_json(build_report()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
