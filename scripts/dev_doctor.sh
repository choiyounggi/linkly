#!/usr/bin/env bash
# linkly 기여자 환경 진단 — 전체 스위트를 초록으로 돌리기 위한 전제조건.
#
#     bash scripts/dev_doctor.sh
#
# exit 0 = 준비됨, exit 1 = 조치 필요.
#
# 이 스크립트가 존재하는 이유: 이 레포의 전제조건은 넷이고 **전부 조용히 실패한다**.
# 빠뜨리면 테스트가 "실패"하는데 그 실패가 원인을 가리키지 않아서, 코드 회귀로
# 오독하기 쉽다. 실제로 그렇게 낭비된 적이 있다.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$REPO" || exit 1

PROBLEMS=0
note() { echo "  → $*"; }

echo "linkly 기여자 환경 진단"
echo "------------------------"

# 1. 인터프리터 --------------------------------------------------------------
if command -v python3.13 >/dev/null 2>&1; then
  echo "python3.13  : $(python3.13 -V 2>&1)"
else
  echo "python3.13  : 없음"
  note "brew install python@3.13"
  note "system python3는 3.14일 수 있고, 그 venv는 ensurepip에서 죽어 pip 없는"
  note "venv를 만든다 — 그러면 이후 pip install이 전부 조용히 불가능해진다."
  PROBLEMS=1
fi

# 2. venv --------------------------------------------------------------------
if [ -x .venv/bin/python ]; then
  echo "venv        : $(.venv/bin/python -V 2>&1)"
else
  echo "venv        : 없음"
  note "python3.13 -m venv .venv"
  PROBLEMS=1
fi

# 3. 의존과 콘솔 스크립트 ----------------------------------------------------
if [ -x .venv/bin/python ]; then
  if .venv/bin/python -c "import jsonschema" >/dev/null 2>&1; then
    echo "jsonschema  : 설치됨"
  else
    echo "jsonschema  : 없음"
    note ".venv/bin/pip install jsonschema"
    note "없으면 scripts/validate_ir.py --self-test가 실패한다."
    PROBLEMS=1
  fi

  if [ -x .venv/bin/lnpl ]; then
    echo "lnpl 스크립트: $(.venv/bin/lnpl --version 2>&1)"
  else
    echo "lnpl 스크립트: 없음"
    note ".venv/bin/pip install ."
    note "훅·doctor 테스트가 <repo>/.venv/bin을 PATH에 얹고 command -v lnpl로"
    note "CLI를 찾는다. 없으면 훅이 '​CLI 없음' 분기로 **우아하게** 빠져서,"
    note "3건이 원인과 무관해 보이는 이유로 실패한다."
    note "impl/lnpl/을 고친 뒤에는:"
    note "  .venv/bin/pip install --force-reinstall --no-deps ."
    PROBLEMS=1
  fi
fi

# 4. MLIR/LLVM 툴체인 --------------------------------------------------------
MISSING_TOOLS=""
for t in mlir-opt mlir-translate clang; do
  command -v "$t" >/dev/null 2>&1 || MISSING_TOOLS="$MISSING_TOOLS $t"
done
if [ -z "$MISSING_TOOLS" ]; then
  echo "MLIR/LLVM   : $(command -v clang)"
else
  echo "MLIR/LLVM   : 없음 —$MISSING_TOOLS"
  note "brew install llvm"
  note 'export PATH="/opt/homebrew/opt/llvm/bin:$PATH"'
  note "없으면 mode B 테스트가 대량으로 깨진다 — 코드 회귀가 아니라 환경이다."
  PROBLEMS=1
fi

# 5. sysroot 정합 -------------------------------------------------------------
# 이슈 #104: brew LLVM의 clang은 bottle 빌드 시점의 SDK 경로를 기본 sysroot로
# 굽는다. 이 머신의 SDK가 다르면(또는 없으면) S7이 조용히 죽는다. backend.py의
# S7은 이제 이 계산을 직접 하고(-isysroot) 실패를 BackendError로 번역하지만,
# 여기서도 같은 계산을 미리 해서 "모드 B 대량 실패"를 코드 회귀로 오독하기
# 전에 원인을 보여준다.
if command -v xcrun >/dev/null 2>&1; then
  SDK_PATH="$(xcrun --sdk macosx --show-sdk-path 2>/dev/null)"
  if [ -n "$SDK_PATH" ] && [ -d "$SDK_PATH" ]; then
    echo "sysroot 정합: $SDK_PATH"
  else
    echo "sysroot 정합: xcrun이 SDK를 못 찾음 (반환값: '${SDK_PATH:-없음}')"
    note "xcode-select --install (Command Line Tools 재설치)"
    note "xcrun --sdk macosx --show-sdk-path 를 직접 실행해 원인을 확인하라"
    note "LNPL_LLVM_BIN으로 sysroot를 스스로 해석하는 LLVM 설치를 가리킬 수도 있다"
    PROBLEMS=1
  fi
else
  echo "sysroot 정합: xcrun 없음"
  note "xcode-select --install (Command Line Tools 설치)"
  PROBLEMS=1
fi

# 6. SDK 헤더 경로 -----------------------------------------------------------
# homebrew clang은 SDKROOT를 무시한다. CommandLineTools의 SDK는 비어 있을 수
# 있어 CPATH/LIBRARY_PATH로 직접 가리켜야 한다.
if [ -n "${CPATH:-}" ] && [ -n "${LIBRARY_PATH:-}" ]; then
  echo "SDK 경로    : CPATH/LIBRARY_PATH 설정됨"
else
  echo "SDK 경로    : CPATH/LIBRARY_PATH 미설정"
  note "이 세션에서 export 하라 (homebrew clang은 SDKROOT를 무시한다):"
  note '  SDK="$(xcrun --show-sdk-path)"'
  note '  export CPATH="$SDK/usr/include"'
  note '  export LIBRARY_PATH="$SDK/usr/lib"'
  PROBLEMS=1
fi

echo
if [ "$PROBLEMS" -eq 0 ]; then
  echo "준비됨. 전체 스위트:"
  echo '  PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl \'
  echo '    2>&1 | grep -E "^(OK|FAILED|Ran )"'
  echo
  echo "결과 줄은 반드시 grep으로 읽어라 — 테스트가 런타임 트레이스를 stdout에"
  echo "찍어서 tail만 쓰면 요약이 묻힌다."
else
  echo "위 항목을 조치한 뒤 다시 돌려라."
fi
exit "$PROBLEMS"
