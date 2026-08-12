#!/usr/bin/env bash
# linkly / lnpl — SessionStart 환경 진단.
#
# 왜 세션 시작인가: 이 플러그인의 보호는 전부 `lnpl` 컴파일러를 부를 수 있다는
# 전제 위에 서 있다. 그 전제가 깨져 있으면 지금까지는 **처음 `.lnpl`을 쓸 때**
# 한 번 알려지고, 그때는 이미 모델이 어휘를 추측한 뒤다. 전제는 앞에서 말해야
# 값이 있다.
#
# 조용함의 규칙: 컴파일러가 해석되고 버전이 플러그인과 맞으면 **아무 말도 하지
# 않는다.** 세션 시작 출력은 모든 세션의 컨텍스트를 먹기 때문에, 행동을 바꾸지
# 않는 사실은 소음이다. 말하는 경우는 둘뿐이다 — 못 찾았을 때, 그리고 버전이
# 어긋났을 때.
#
# 계약: 항상 exit 0. 세션 시작을 막지 않는다. 할 말이 있으면 stdout에
# hookSpecificOutput.additionalContext 로 싣는다.
set -uo pipefail

HOOK_DIR=$(cd "$(dirname "$0")" 2>/dev/null && pwd -P) || HOOK_DIR="."
# shellcheck source=lib/resolve-lnpl.sh
. "$HOOK_DIR/lib/resolve-lnpl.sh"

emit() {
  # jq 로 JSON 을 만든다 — 메시지에 따옴표나 개행이 들어가도 깨지지 않게.
  if command -v jq >/dev/null 2>&1; then
    jq -n --arg ctx "$1" \
      '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
  else
    printf '%s\n' "$1"
  fi
  exit 0
}

resolve_lnpl_bin "${CLAUDE_PROJECT_DIR-$PWD}"

if [ -z "$LNPL_MODE" ]; then
  emit "lnpl 플러그인: 컴파일러를 찾지 못했다 ($(lnpl_resolution_trace) 순으로 시도).
이 세션에서 \`.lnpl\` 쓰기 진단은 동작하지 않는다 — 사전에 없는 동사가 조용한
no-op으로 통과한다는 뜻이다. \`lnpl-doctor\` 스킬로 진단하거나, 레포 체크아웃에서
\`.venv/bin/pip install .\` 를 하거나, LNPL_IMPL/LNPL_BIN 을 설정하라."
fi

CLI_VERSION=$(run_lnpl --version 2>/dev/null | awk '{print $NF}')
if [ -z "$CLI_VERSION" ]; then
  emit "lnpl 플러그인: 컴파일러는 찾았지만($LNPL_ORIGIN) \`--version\` 이 답하지
않는다. 설치가 깨졌을 수 있다 — \`lnpl-doctor\` 스킬을 쓰라."
fi

MANIFEST="$HOOK_DIR/../.claude-plugin/plugin.json"
PLUGIN_VERSION=""
if [ -f "$MANIFEST" ] && command -v jq >/dev/null 2>&1; then
  PLUGIN_VERSION=$(jq -r '.version // empty' "$MANIFEST" 2>/dev/null)
fi

if [ -n "$PLUGIN_VERSION" ] && [ "$PLUGIN_VERSION" != "$CLI_VERSION" ]; then
  emit "lnpl 플러그인: 버전이 어긋난다 — 플러그인 $PLUGIN_VERSION,
컴파일러 $CLI_VERSION ($LNPL_ORIGIN). 이 플러그인의 어휘 참조는 컴파일러
테이블에서 생성된 것이라, 버전이 다르면 references/ 가 실제 어휘와 다를 수 있다.
레포에서 \`python scripts/gen_plugin_references.py --check\` 로 확인하라."
fi

# 준비됐다 — 아무 말도 하지 않는다.
exit 0
