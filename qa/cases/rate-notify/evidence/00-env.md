# 00 — 환경 구축과 기준선 (Task 01)

기록 시각: 2026-08-05 21:15 GMT+9

## 기준선 고정

```
$ git rev-parse HEAD
713a4cba14a5ace278801c193abbc809ab09894e

$ git status --porcelain
(출력 없음 — clean)          # rc=0
```

## venv 구축 (워크트리 자체, 상대경로)

```
$ python3.13 -m venv .venv && .venv/bin/pip install -e . -q
install-rc=0
$ .venv/bin/pip install -q jsonschema
jsonschema-rc=0
```

시도 1회. 마찰 없음. (pip 자체 업그레이드 notice는 무해 — 무시.)

## 셸 export + dev_doctor

```
$ export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
$ SDK="$(xcrun --show-sdk-path)"; export CPATH="$SDK/usr/include" LIBRARY_PATH="$SDK/usr/lib"
$ bash scripts/dev_doctor.sh
linkly 기여자 환경 진단
------------------------
python3.13  : Python 3.13.1
venv        : Python 3.13.1
jsonschema  : 설치됨
lnpl 스크립트: lnpl 0.2.0
MLIR/LLVM   : /opt/homebrew/opt/llvm/bin/clang
SDK 경로    : CPATH/LIBRARY_PATH 설정됨
준비됨. …
doctor-rc=0

$ .venv/bin/lnpl --help >/dev/null; echo rc=$?
lnpl-help-rc=0
```

시도 1회, rc=0.

## 패리티 인벤토리 (wiki: qa-environments-test-environment-parity — 이후 실패 귀속의 기준)

| 차원(전제) | 상태 | 확인 방법 |
|-----------|------|-----------|
| python3.13 (system 3.14 아님) | 일치 — 3.13.1 | dev_doctor 출력 |
| .venv jsonschema | 설치됨 | dev_doctor 출력 |
| .venv lnpl 콘솔 스크립트 | lnpl 0.2.0 | dev_doctor 출력 + `--help` rc=0 |
| LLVM 툴체인 + CPATH/LIBRARY_PATH | 설정됨 (homebrew clang) | dev_doctor 출력 |

4개 전제 전부 일치 상태에서 시작 → 이후 mode B 실패가 나오면 이 인벤토리가
기준(환경 문제 가능성을 낮추는 증거)이 된다. export는 셸마다 재설정 필요
(mode B 단계에서 재확인 예정).
