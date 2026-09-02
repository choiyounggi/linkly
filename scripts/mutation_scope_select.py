#!/usr/bin/env python3
"""PR-scoped mutation selection (issue #166). Filters
`mutation_check.MUTATIONS` to entries whose anchor file the caller's changed-
file list touches, then runs the harness's own unmodified `main()` — this
script never edits mutation_check.py or reimplements its verdict logic.

    python scripts/mutation_scope_select.py <changed-file-path>...

With zero changed-file arguments, prints an explicit skip line and exits 0
without importing/running the harness at all (see
wiki/infrastructure/ci-cd/changed-files-only-gates.md — an empty operand
list must never fall through into a state that reads the same as "ran and
genuinely selected zero relevant mutations").
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def select(changed_files, mutations):
    changed = set(changed_files)
    selected = []
    for m in mutations:
        relpath = m[1]
        anchor_path = os.path.join("impl", relpath).replace(os.sep, "/")
        if anchor_path in changed:
            selected.append(m)
    return selected


def main(argv):
    changed_files = argv
    if not changed_files:
        print("mutation_scope_select: 0 changed files passed — skipping "
              "(no mutation anchors can be in scope); nothing was run")
        return 0
    sys.path.insert(0, os.path.join(REPO, "impl"))
    import tests.mutation_check as mc
    selected = select(changed_files, mc.MUTATIONS)
    print("mutation_scope_select: %d/%d mutation(s) selected for %d changed "
          "file(s)" % (len(selected), len(mc.MUTATIONS), len(changed_files)))
    mc.MUTATIONS = selected
    return mc.main()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
