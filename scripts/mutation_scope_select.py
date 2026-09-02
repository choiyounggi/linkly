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
    if not selected:
        # 교차 앵커가 0건이면 판정할 대상 자체가 없다 — 여기서 하네스의
        # baseline(전체 스위트 + no-op 컨트롤)까지 돌리는 것은 순수 낭비이고,
        # 러너 환경에서 baseline이 붉으면 "이 PR과 무관한 red"라는 노이즈만
        # 만든다(2026-09-03 PR #167에서 실측). 빈 CHANGED 목록의 명시적 스킵과
        # 같은 원칙(wiki changed-files-only-gates)을 빈 SELECTION에도 적용한다.
        print("mutation_scope_select: no anchor intersects the changed files "
              "— nothing to judge, skipping the harness entirely")
        return 0
    mc.MUTATIONS = selected
    return mc.main()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
