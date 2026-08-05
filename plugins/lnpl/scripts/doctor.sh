#!/usr/bin/env bash
# linkly / lnpl — 설치 상태 진단.
#
# 플러그인 자체는 레포에 묶여 커밋 단위로 정합하지만, 사용자가 설치한 lnpl CLI는
# 다른 버전일 수 있다. drift가 배포 경계에서 다시 나타나는 지점이 여기다.
#
# exit 0 = 정상, exit 1 = 조치가 필요하다.
set -uo pipefail

PROBLEMS=0

echo "lnpl 플러그인 진단"
echo "-------------------"

if command -v lnpl >/dev/null 2>&1; then
  echo "CLI 경로   : $(command -v lnpl)"
else
  echo "CLI 경로   : 없음"
  echo ""
  echo "lnpl CLI가 PATH에 없다. linkly 체크아웃에서 설치하라:"
  echo "    pip install /path/to/linkly"
  echo ""
  echo "설치 없이 쓰려면 레포 안에서:"
  echo "    PYTHONPATH=impl python -m lnpl compile <파일>"
  exit 1
fi

CLI_VERSION=$(lnpl --version 2>/dev/null | awk '{print $2}')
if [ -z "$CLI_VERSION" ]; then
  echo "CLI 버전   : 읽을 수 없음 (--version 미지원 — 구버전이다)"
  echo ""
  echo "설치된 lnpl이 --version을 모른다. 최신 체크아웃으로 재설치하라:"
  echo "    pip install --force-reinstall /path/to/linkly"
  exit 1
fi
echo "CLI 버전   : ${CLI_VERSION}"

PLUGIN_JSON="${CLAUDE_PLUGIN_ROOT:-}/.claude-plugin/plugin.json"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -f "$PLUGIN_JSON" ]; then
  PLUGIN_VERSION=$(jq -r '.version // empty' "$PLUGIN_JSON" 2>/dev/null)
  echo "플러그인   : ${PLUGIN_VERSION:-알 수 없음}"
  if [ -n "$PLUGIN_VERSION" ] && [ "$PLUGIN_VERSION" != "$CLI_VERSION" ]; then
    echo ""
    echo "버전 불일치: 플러그인 ${PLUGIN_VERSION} vs CLI ${CLI_VERSION}."
    echo "플러그인의 어휘 문서는 ${PLUGIN_VERSION} 시점의 소스에서 생성됐다."
    echo "둘을 맞춰라 — 같은 체크아웃에서 재설치하거나 플러그인을 갱신하라."
    PROBLEMS=1
  fi
else
  echo "플러그인   : plugin.json 없음 (버전 비교 건너뜀)"
fi

# CLI가 실제로 컴파일까지 가는지 본다 — PATH에 있다는 것만으로는 부족하다.
# 프로브는 플러그인 설치 경로가 아니라 사용자 상태 디렉터리에 쓴다(훅의 마커와 같은 곳).
# 경로는 호출마다 유일해야 한다: 고정 경로를 쓰면 동시에 돌던 두 doctor 중 한쪽의
# 정리가 다른 쪽 프로브를 지워, 멀쩡한 설치를 "컴파일 실패"로 보고한다(실측 플래키).
PROBE_BASE="${HOME}/.claude/lnpl-plugin"
mkdir -p "$PROBE_BASE" 2>/dev/null
PROBE_DIR="$(mktemp -d "${PROBE_BASE}/probe.XXXXXX" 2>/dev/null)" || PROBE_DIR="${PROBE_BASE}/probe.$$"
mkdir -p "$PROBE_DIR" 2>/dev/null
PROBE="${PROBE_DIR}/probe.lnpl"
printf 'entity Note\n    field\n        id UUID\n\nworkflow Save\n    validate input\n    create note\n' > "$PROBE" 2>/dev/null
if lnpl compile "$PROBE" >/dev/null 2>&1; then
  echo "컴파일     : 정상"
else
  echo "컴파일     : 실패"
  echo ""
  echo "lnpl이 최소 예제조차 컴파일하지 못한다. 설치가 손상됐다."
  PROBLEMS=1
fi
rm -rf "$PROBE_DIR" 2>/dev/null

echo ""
if [ "$PROBLEMS" -eq 0 ]; then
  echo "이상 없음."
else
  echo "위 항목을 조치하라."
fi
exit "$PROBLEMS"
