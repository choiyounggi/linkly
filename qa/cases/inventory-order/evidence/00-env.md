# evidence/00-env — 환경 구성과 베이스라인 (Task 01)

날짜: 2026-08-05 / 워크트리: `.worktrees/qa-t1-inventory-order` / 반복 횟수: 1 (첫 시도에 rc=0)

## 베이스라인 고정

```
$ git rev-parse HEAD
713a4cba14a5ace278801c193abbc809ab09894e
$ git status --porcelain | wc -l
0        # clean
```

## venv 생성·설치 (상대경로, 워크트리 자체 소유 — D2)

```
$ python3.13 -m venv .venv
# rc=0
$ .venv/bin/pip install -e .
# rc=0 (pip 24.3.1 notice만 출력)
```

## 셸 export (매 셸마다 재적용 — D2)

```sh
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
SDK="$(xcrun --show-sdk-path)"
export CPATH="$SDK/usr/include" LIBRARY_PATH="$SDK/usr/lib"
```

## 게이트: dev_doctor

```
$ bash scripts/dev_doctor.sh
# rc=0
linkly 기여자 환경 진단
------------------------
python3.13  : Python 3.13.1
venv        : Python 3.13.1
jsonschema  : 설치됨
lnpl 스크립트: lnpl 0.2.0
MLIR/LLVM   : /opt/homebrew/opt/llvm/bin/clang
SDK 경로    : CPATH/LIBRARY_PATH 설정됨
준비됨.
```

## CLI 확인

```
$ .venv/bin/lnpl --version
lnpl 0.2.0
```

판정: 환경 준비 완료. 전제조건 4종(python3.13 / jsonschema / lnpl 콘솔 스크립트 /
LLVM+SDK 경로) 전부 충족, 침묵 실패 없음.
