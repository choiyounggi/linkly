# shellcheck shell=sh
# lnpl 실행기 해석 — 이 플러그인의 훅 둘이 공유하는 단일 정본.
#
# 훅은 **Claude Code의 프로세스 환경**에서 돈다: 사용자가 activate한 venv도,
# 셸 rc가 얹은 PATH도 거기에는 없다. `command -v lnpl` 하나에 기대면, CLI를
# 프로젝트 로컬(`.venv/bin/lnpl`)에 설치하는 레포에서는 훅이 통째로 죽는다.
# linkly 자신이 그런 레포였다 — 플러그인은 설치돼 있고 훅은 등록돼 있는데
# 보호는 0인 상태가 조용히 성립했다.
#
# 두 훅이 각자 구현하면 반드시 갈라진다. 그래서 여기 하나뿐이다.
#
# 사용법:
#     . "<...>/lib/resolve-lnpl.sh"
#     resolve_lnpl_bin "<시작 경로: 파일이든 디렉터리든>"
#     # -> LNPL_MODE  ("bin" | "module" | "" 못 찾음)
#     #    LNPL_EXE   (bin: lnpl 실행 파일 / module: python3)
#     #    LNPL_PYPATH(module 모드의 PYTHONPATH)
#     #    LNPL_ORIGIN(어느 후보가 이겼는지 — 사람에게 말할 때 쓴다)
#
# 순서와 그 이유:
#   1. $LNPL_BIN                       명시적 오버라이드 (겸 테스트 시딩 지점)
#   2. 시작 경로에서 위로: .venv/bin/lnpl
#   3. $CLAUDE_PROJECT_DIR/.venv/bin/lnpl
#   4. PATH의 lnpl
#   5. python3 -m lnpl  (위로 올라가며 찾은 impl/ 을 PYTHONPATH로)
#
# 2가 3보다 앞인 것은 결정이다: 워크트리는 각자 자기 venv를 갖는데
# CLAUDE_PROJECT_DIR는 메인 체크아웃을 가리킬 수 있고, 그러면 워크트리 안의
# `.lnpl`을 다른 체크아웃의 컴파일러로 검사하게 된다.

LNPL_MODE=""
LNPL_EXE=""
LNPL_PYPATH=""
LNPL_ORIGIN=""

# $1 에서 위로 올라가며 $2(상대 경로)가 실행 가능한 첫 자리를 출력한다.
find_up_exec() {
  _dir=$1
  while :; do
    if [ -x "$_dir/$2" ]; then printf '%s\n' "$_dir/$2"; return 0; fi
    _parent=$(dirname "$_dir")
    [ "$_parent" = "$_dir" ] && return 1
    _dir=$_parent
  done
}

# $1 에서 위로 올라가며 $2(상대 경로)가 존재하는 첫 **디렉터리**를 출력한다.
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
  LNPL_MODE=""; LNPL_EXE=""; LNPL_PYPATH=""; LNPL_ORIGIN=""
  _start=${1:-$PWD}
  if [ -d "$_start" ]; then
    _from=$(cd "$_start" 2>/dev/null && pwd -P) || _from=""
  else
    _from=$(cd "$(dirname "$_start")" 2>/dev/null && pwd -P) || _from=""
  fi

  # 1. 설정돼 있으면 이것만 쓴다. 실행 불가여도 폴백하지 않는다 —
  #    조용히 다른 걸 쓰면 그건 오버라이드가 아니다. unset 과 empty 를
  #    구분해야 하므로 ${VAR+set} 이다.
  if [ -n "${LNPL_BIN+set}" ]; then
    if [ -x "${LNPL_BIN-}" ]; then
      LNPL_MODE=bin; LNPL_EXE=${LNPL_BIN-}; LNPL_ORIGIN='$LNPL_BIN'
    fi
    return
  fi

  if [ -n "$_from" ]; then
    _hit=$(find_up_exec "$_from" ".venv/bin/lnpl") && {
      LNPL_MODE=bin; LNPL_EXE=$_hit; LNPL_ORIGIN="상위 .venv/bin/lnpl"; return; }
  fi

  if [ -n "${CLAUDE_PROJECT_DIR-}" ] && [ -x "${CLAUDE_PROJECT_DIR}/.venv/bin/lnpl" ]; then
    LNPL_MODE=bin; LNPL_EXE="${CLAUDE_PROJECT_DIR}/.venv/bin/lnpl"
    LNPL_ORIGIN='$CLAUDE_PROJECT_DIR/.venv/bin/lnpl'; return
  fi

  _path_hit=$(command -v lnpl 2>/dev/null) && [ -n "$_path_hit" ] && {
    LNPL_MODE=bin; LNPL_EXE=$_path_hit; LNPL_ORIGIN="PATH"; return; }

  if [ -n "$_from" ] && command -v python3 >/dev/null 2>&1; then
    _repo=$(find_up_dir "$_from" "impl/lnpl/__init__.py") && {
      LNPL_MODE=module
      LNPL_EXE=$(command -v python3)
      LNPL_PYPATH="$_repo/impl"
      LNPL_ORIGIN="python3 -m lnpl ($LNPL_PYPATH)"
      return; }
  fi
}

# 해석된 실행기로 lnpl 을 부른다. 인자는 그대로 전달된다.
run_lnpl() {
  case "$LNPL_MODE" in
    bin)    "$LNPL_EXE" "$@" ;;
    module) PYTHONPATH="$LNPL_PYPATH" "$LNPL_EXE" -m lnpl "$@" ;;
    *)      return 127 ;;
  esac
}

# 어느 후보들을 시도했는지 — 못 찾았을 때 사람에게 말할 한 줄.
lnpl_resolution_trace() {
  printf '%s' 'LNPL_BIN / 상위 .venv/bin/lnpl / $CLAUDE_PROJECT_DIR/.venv/bin/lnpl / PATH / python3 -m lnpl'
}
