#!/usr/bin/env bash
# linkly / lnpl — PostToolUse 진단 훅.
#
# `.lnpl`을 Write/Edit한 직후 `lnpl compile`을 돌리고 진단을 모델에게 되돌린다.
#
# 왜 필요한가: `lnpl compile`은 진단을 stderr로 내보내고 **종료 코드 0**으로
# 끝난다. 즉 아무도 보지 않으면 사라진다. 사전에 없는 동사는 에러가 아니라
# 효과 없는 no-op이고(issue #36), 선언 중 상당수는 집행되지 않는다(issue #38).
# 그 사실이 작성 시점에 보이지 않으면 리뷰 때까지 아무도 모른다.
#
# 계약:
#   exit 0 — 조용. exit 2 — stderr가 모델에게 전달된다.
#   PostToolUse는 도구 실행 뒤에 돌기 때문에 exit 2가 쓰기를 되돌리지 않는다.
set -uo pipefail

INPUT=$(cat)

FILE=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -n "$FILE" ] || exit 0
case "$FILE" in
  *.lnpl) ;;
  *) exit 0 ;;
esac
[ -f "$FILE" ] || exit 0

# `lnpl`이 없으면 사용자 워크플로를 깨지 않는다. 다만 세션당 한 번은 알린다 —
# 훅이 조용히 죽어 있으면 플러그인이 설치된 줄 알면서 아무 보호도 못 받는다.
if ! command -v lnpl >/dev/null 2>&1; then
  SESSION=$(printf '%s' "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null)
  MARK_DIR="${HOME}/.claude/lnpl-plugin"
  MARK="${MARK_DIR}/notified-${SESSION}"
  [ -e "$MARK" ] && exit 0
  mkdir -p "$MARK_DIR" 2>/dev/null && : > "$MARK" 2>/dev/null
  echo "lnpl CLI가 PATH에 없어 .lnpl 진단을 건너뛰었다. \`lnpl-doctor\` 스킬로 진단하라." >&2
  exit 2
fi

# stdout(IR)은 버리고 stderr(진단)만 잡는다. 리디렉션 순서가 중요하다.
OUT=$(lnpl compile "$FILE" 2>&1 >/dev/null)
RC=$?

if [ "$RC" -ne 0 ]; then
  {
    echo "\`$FILE\`이 컴파일되지 않는다:"
    echo "$OUT"
  } >&2
  exit 2
fi

if [ -n "$OUT" ]; then
  {
    echo "\`$FILE\` 진단:"
    echo "$OUT"
    echo ""
    echo "각 항목이 의도한 것인지 확인하라. unknown-verb는 그 스텝이 아무 효과도"
    echo "내지 않는다는 뜻이고, declared-not-enforced는 선언이 실행을 바꾸지"
    echo "않는다는 뜻이다. 어휘는 \`lnpl-authoring\` 스킬의 references/를 본다."
  } >&2
  exit 2
fi

exit 0
