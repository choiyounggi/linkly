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

# ---------------------------------------------------------------------------
# lnpl 실행기 해석
#
# 훅은 **Claude Code의 프로세스 환경**에서 돈다 — 사용자가 activate한 venv도,
# 셸 rc가 얹은 PATH도 거기에는 없다. `command -v lnpl` 하나에 기대면, CLI를
# 프로젝트 로컬(`.venv/bin/lnpl`)에 설치하는 레포에서는 훅이 통째로 죽는다.
# linkly 자신이 바로 그런 레포였다: 플러그인은 설치돼 있고 훅은 등록돼 있는데
# 보호는 0인 상태가 조용히 성립했다.
#
# 그래서 자동화가 하는 일을 한다 — 바이너리를 고정한다. 아래 순서로 시도하고
# 첫 성공에서 멈춘다:
#
#   1. $LNPL_BIN            명시적 오버라이드 (겸 테스트 시딩 지점)
#   2. 편집된 파일에서 위로 올라가며 만나는 첫 .venv/bin/lnpl
#   3. $CLAUDE_PROJECT_DIR/.venv/bin/lnpl
#   4. PATH의 lnpl
#   5. python3 -m lnpl  (위로 올라가며 찾은 레포의 impl/ 을 PYTHONPATH로)
#
# 2가 3보다 앞인 이유: 워크트리는 각자 자기 venv를 갖는다. CLAUDE_PROJECT_DIR는
# 메인 체크아웃을 가리킬 수 있고, 그러면 워크트리 안의 .lnpl을 다른 체크아웃의
# 컴파일러로 검사하게 된다.
# ---------------------------------------------------------------------------

LNPL_MODE=""     # "bin" | "module" | "" (못 찾음)
LNPL_EXE=""      # bin 모드: lnpl 실행 파일 / module 모드: python3
LNPL_PYPATH=""   # module 모드의 PYTHONPATH

# $1 에서 시작해 위로 올라가며 $2 (상대 경로)가 실행 가능한 첫 자리를 출력한다.
find_up_exec() {
  _dir=$1
  while :; do
    if [ -x "$_dir/$2" ]; then printf '%s\n' "$_dir/$2"; return 0; fi
    _parent=$(dirname "$_dir")
    [ "$_parent" = "$_dir" ] && return 1
    _dir=$_parent
  done
}

# $1 에서 시작해 위로 올라가며 $2 (상대 경로)가 존재하는 첫 **디렉터리**를 출력한다.
find_up_dir() {
  _dir=$1
  while :; do
    if [ -e "$_dir/$2" ]; then printf '%s\n' "$_dir"; return 0; fi
    _parent=$(dirname "$_dir")
    [ "$_parent" = "$_dir" ] && return 1
    _dir=$_parent
  done
}

resolve_lnpl_bin() {
  _from=$(cd "$(dirname "$FILE")" 2>/dev/null && pwd -P) || _from=""

  # 1. 명시적 오버라이드. 설정돼 있으면 **이것만** 쓴다 — 실행 불가여도
  #    폴백하지 않는다. 조용히 다른 걸 쓰면 그건 오버라이드가 아니다.
  #    unset 과 empty 를 구분해야 하므로 ${VAR+set} 을 쓴다.
  if [ -n "${LNPL_BIN+set}" ]; then
    if [ -x "${LNPL_BIN-}" ]; then LNPL_MODE=bin; LNPL_EXE=${LNPL_BIN-}; fi
    return
  fi

  # 2. 편집된 파일 기준 walk-up — 워크트리 로컬 venv가 여기서 잡힌다.
  if [ -n "$_from" ]; then
    _hit=$(find_up_exec "$_from" ".venv/bin/lnpl") && {
      LNPL_MODE=bin; LNPL_EXE=$_hit; return; }
  fi

  # 3. 프로젝트 루트의 venv.
  if [ -n "${CLAUDE_PROJECT_DIR-}" ] && [ -x "${CLAUDE_PROJECT_DIR}/.venv/bin/lnpl" ]; then
    LNPL_MODE=bin; LNPL_EXE="${CLAUDE_PROJECT_DIR}/.venv/bin/lnpl"; return
  fi

  # 4. 전역 설치.
  _path_hit=$(command -v lnpl 2>/dev/null) && [ -n "$_path_hit" ] && {
    LNPL_MODE=bin; LNPL_EXE=$_path_hit; return; }

  # 5. 콘솔 스크립트가 없어도 소스가 있으면 모듈로 돈다.
  if [ -n "$_from" ] && command -v python3 >/dev/null 2>&1; then
    _repo=$(find_up_dir "$_from" "impl/lnpl/__init__.py") && {
      LNPL_MODE=module
      LNPL_EXE=$(command -v python3)
      LNPL_PYPATH="$_repo/impl"
      return; }
  fi
}

# stdout(IR)은 버리고 stderr(진단)만 잡는다. 리디렉션 순서가 중요하다 —
# 뒤집으면 stderr를 버리고 IR을 잡는다.
compile_capture() {
  case "$LNPL_MODE" in
    bin)    "$LNPL_EXE" compile "$1" 2>&1 >/dev/null ;;
    module) PYTHONPATH="$LNPL_PYPATH" "$LNPL_EXE" -m lnpl compile "$1" 2>&1 >/dev/null ;;
    *)      return 127 ;;
  esac
}

resolve_lnpl_bin

# 해석은 **매번** 시도한다. 마커는 아래에서 안내의 반복만 억제한다 — 마커를
# 이유로 해석을 건너뛰면, 한 번 CLI를 못 찾은 세션은 남은 내내 무방비가 된다.
if [ -z "$LNPL_MODE" ]; then
  SESSION=$(printf '%s' "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null)
  MARK_DIR="${HOME}/.claude/lnpl-plugin"
  MARK="${MARK_DIR}/notified-${SESSION}"
  [ -e "$MARK" ] && exit 0
  mkdir -p "$MARK_DIR" 2>/dev/null && : > "$MARK" 2>/dev/null
  echo "lnpl CLI를 찾지 못해 .lnpl 진단을 건너뛰었다 (LNPL_BIN / 상위 .venv/bin/lnpl / CLAUDE_PROJECT_DIR / PATH / python3 -m lnpl 순으로 시도). \`lnpl-doctor\` 스킬로 진단하라." >&2
  exit 2
fi

OUT=$(compile_capture "$FILE")
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
