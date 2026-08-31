#!/usr/bin/env python3
"""measure_tokens.py — issue #142 token benchmark, deterministic output.

Prints one JSON object to stdout: source token counts for
examples/linkhub.lnpl vs equiv/linkhub_fastapi.py, plus edit-token counts
for the two edit tasks in edits/ (M1: add a field, M2: duplicate-url guard
attempt). Two runs on an unchanged tree produce byte-identical stdout
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

SOURCE_FILES = {
    "lnpl": REPO_ROOT / "examples" / "linkhub.lnpl",
    "fastapi": BASE_DIR / "equiv" / "linkhub_fastapi.py",
}

EDIT_TASKS = {
    "m1_note_field": {
        "lnpl": (
            BASE_DIR / "edits" / "m1_note_field" / "lnpl_before.lnpl",
            BASE_DIR / "edits" / "m1_note_field" / "lnpl_after.lnpl",
        ),
        "fastapi": (
            BASE_DIR / "edits" / "m1_note_field" / "fastapi_before.py",
            BASE_DIR / "edits" / "m1_note_field" / "fastapi_after.py",
        ),
    },
    "m2_duplicate_guard": {
        "lnpl": (
            BASE_DIR / "edits" / "m2_duplicate_guard" / "lnpl_before.lnpl",
            BASE_DIR / "edits" / "m2_duplicate_guard" / "lnpl_after.lnpl",
        ),
        "fastapi": (
            BASE_DIR / "edits" / "m2_duplicate_guard" / "fastapi_before.py",
            BASE_DIR / "edits" / "m2_duplicate_guard" / "fastapi_after.py",
        ),
    },
}


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
        key: measure_file(path, encodings) for key, path in SOURCE_FILES.items()
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


def main():
    report = build_report()
    json.dump(report, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
