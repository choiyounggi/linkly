#!/usr/bin/env bash
# Idempotent main-branch-protection preparer (issues #166, #244). NEVER auto-run
# by CI or any orchestration task — apply only after an explicit human/coordinator
# decision. `--check` is read-only: it prints the desired payload, then reads the
# live protection with ONE GET (never PUT/PATCH) and prints an ok:/drift: line
# per required check and per setting. `--include-modeb` is kept so old runbooks
# keep working; it changes nothing, because modeb-linux is in the default list
# since #244.
set -euo pipefail
OWNER="choiyounggi"
REPO="linkly"
BRANCH="main"
CHECK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --include-modeb) ;;
    --check) CHECK_ONLY=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

CHECKS='{"context":"gate (py3.11)"},{"context":"gate (py3.12)"},{"context":"gate (py3.13)"},{"context":"lint (ruff)"},{"context":"modeb-linux (test_repo_state under real mode B)"},{"context":"test-quality / gate"}'

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
  "allow_deletions": false,
  "required_conversation_resolution": true,
  "required_linear_history": false,
  "block_creations": false,
  "lock_branch": false,
  "allow_fork_syncing": false
}
JSON
)

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "would PUT to /repos/$OWNER/$REPO/branches/$BRANCH/protection:"
  echo "$PAYLOAD"
  if ! command -v python3 >/dev/null 2>&1; then
    echo "live: unavailable (python3 not found)" >&2
    exit 0
  fi
  if ! command -v gh >/dev/null 2>&1; then
    echo "live: unavailable (gh not found)" >&2
    exit 0
  fi
  rc=0
  LIVE=$(gh api --method GET -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "/repos/$OWNER/$REPO/branches/$BRANCH/protection" 2>/dev/null) || rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "live: unavailable (gh api exited $rc)" >&2
    exit 0
  fi
  echo "--- live vs desired (GET /repos/$OWNER/$REPO/branches/$BRANCH/protection) ---"
  crc=0
  DESIRED_JSON="$PAYLOAD" LIVE_JSON="$LIVE" python3 - <<'PY' || crc=$?
import json
import os
import sys

desired = json.loads(os.environ["DESIRED_JSON"])
try:
    live = json.loads(os.environ["LIVE_JSON"])
except ValueError:
    live = None
if not isinstance(live, dict):
    print("live: unavailable (unparseable response)", file=sys.stderr)
    sys.exit(0)


def render(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return "set"


def live_bool(key):
    if key not in live:
        return "absent"
    value = live[key]
    if isinstance(value, dict) and "enabled" in value:
        return render(value["enabled"])
    return render(value)


lines = []
want = [c["context"] for c in desired["required_status_checks"]["checks"]]
rsc = live.get("required_status_checks") or {}
have = [c.get("context") for c in rsc.get("checks", [])]
for ctx in want:
    if ctx in have:
        lines.append(("ok", 'check "%s"' % ctx))
    else:
        lines.append(("drift", 'check "%s" missing live' % ctx))
for ctx in have:
    if ctx not in want:
        lines.append(("drift", 'check "%s" live only (PUT would remove it)' % ctx))
settings = [("strict", desired["required_status_checks"]["strict"],
             render(rsc["strict"]) if "strict" in rsc else "absent")]
for key in ("enforce_admins", "required_conversation_resolution"):
    settings.append((key, desired[key], live_bool(key)))
for key in ("required_pull_request_reviews", "restrictions"):
    settings.append((key, desired[key], render(live.get(key))))
for key in ("allow_force_pushes", "allow_deletions", "required_linear_history",
            "block_creations", "lock_branch", "allow_fork_syncing"):
    settings.append((key, desired[key], live_bool(key)))
for name, want_value, live_value in settings:
    shown = render(want_value)
    if shown == live_value:
        lines.append(("ok", "%s=%s" % (name, shown)))
    else:
        lines.append(("drift", "%s desired=%s live=%s" % (name, shown, live_value)))
for kind, text in lines:
    print("%s: %s" % (kind, text))
drift = sum(1 for kind, _ in lines if kind == "drift")
print("summary: %d drift, %d ok" % (drift, len(lines) - drift))
PY
  if [ "$crc" -ne 0 ]; then
    echo "live: unavailable (comparator exited $crc)" >&2
  fi
  exit 0
fi

echo "$PAYLOAD" | gh api --method PUT \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "/repos/$OWNER/$REPO/branches/$BRANCH/protection" \
  --input -
echo "setup_branch_protection: applied"
