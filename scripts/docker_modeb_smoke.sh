#!/usr/bin/env bash
# Mode-B Linux toolchain smoke test (issue #161). Proves the apt.llvm.org
# pinned-version install path works before ci.yml's modeb-linux job ships.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
LLVM_MAJOR="$(awk '{print $2}' "$REPO/mlir/llvm.pin" | cut -d. -f1)"
[ -n "$LLVM_MAJOR" ] || { echo "docker_modeb_smoke: could not parse mlir/llvm.pin" >&2; exit 1; }
docker run --rm -v "$REPO":/repo:ro ubuntu:24.04 bash -c '
  set -euo pipefail
  WORK=/root/lnpl-smoke
  mkdir -p "$WORK"
  apt-get update -qq
  apt-get install -y -qq wget gnupg lsb-release ca-certificates python3 python3-venv >/dev/null
  CODENAME="$(lsb_release -cs)"
  wget -qO "$WORK/llvm.gpg.key" https://apt.llvm.org/llvm-snapshot.gpg.key
  gpg --dearmor -o /usr/share/keyrings/llvm.gpg < "$WORK/llvm.gpg.key"
  echo "deb [signed-by=/usr/share/keyrings/llvm.gpg] http://apt.llvm.org/$CODENAME/ llvm-toolchain-$CODENAME-'"$LLVM_MAJOR"' main" > /etc/apt/sources.list.d/llvm.list
  apt-get update -qq
  apt-get install -y -qq "clang-'"$LLVM_MAJOR"'" "mlir-'"$LLVM_MAJOR"'-tools" "libmlir-'"$LLVM_MAJOR"'-dev" >/dev/null
  BIN="/usr/lib/llvm-'"$LLVM_MAJOR"'/bin"
  if [ ! -x "$BIN/mlir-opt" ]; then
    echo "expected bin dir $BIN missing mlir-opt; discovering real path:" >&2
    dpkg -L "mlir-'"$LLVM_MAJOR"'-tools" | grep "/bin/mlir-opt" >&2 || true
    exit 1
  fi
  test -x "$BIN/mlir-translate"
  test -x "$BIN/clang-'"$LLVM_MAJOR"'" || test -x "$BIN/clang"
  export LNPL_LLVM_BIN="$BIN"
  cp -a /repo "$WORK/src"
  python3 -m venv "$WORK/venv"
  "$WORK/venv/bin/pip" install -q -e "$WORK/src"
  cd "$WORK/src"
  LNPL_LLVM_BIN="$LNPL_LLVM_BIN" PYTHONPATH=impl "$WORK/venv/bin/python" -m unittest tests.test_repo_state -v
'
echo "docker_modeb_smoke: OK (LLVM major $LLVM_MAJOR)"
