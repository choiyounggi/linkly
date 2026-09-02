#!/usr/bin/env bash
# Idempotent main-branch-protection preparer (issue #166). NEVER auto-run by
# CI or any orchestration task — apply only after an explicit human/coordinator
# decision, post-merge-gate. `--check` is read-only (prints current vs desired,
# changes nothing). `--include-modeb` adds the unproven modeb-linux job to the
# required-checks list (default: excluded — see design.md D2; enable after the
# first observed green run on GitHub-hosted runners).
set -euo pipefail
OWNER="choiyounggi"
REPO="linkly"
BRANCH="main"
INCLUDE_MODEB=0
CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --include-modeb) INCLUDE_MODEB=1 ;;
    --check) CHECK_ONLY=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

CHECKS='{"context":"gate (py3.11)"},{"context":"gate (py3.12)"},{"context":"gate (py3.13)"},{"context":"lint (ruff)"}'
if [ "$INCLUDE_MODEB" -eq 1 ]; then
  CHECKS="$CHECKS,{\"context\":\"modeb-linux (test_repo_state under real mode B)\"}"
fi

PAYLOAD=$(cat <<JSON
{
  "required_status_checks": {
    "strict": true,
    "checks": [$CHECKS]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
)

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "would PUT to /repos/$OWNER/$REPO/branches/$BRANCH/protection:"
  echo "$PAYLOAD"
  exit 0
fi

echo "$PAYLOAD" | gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "/repos/$OWNER/$REPO/branches/$BRANCH/protection" \
  --input -
echo "setup_branch_protection: applied (include_modeb=$INCLUDE_MODEB)"
