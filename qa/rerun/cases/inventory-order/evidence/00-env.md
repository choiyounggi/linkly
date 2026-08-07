# evidence/00-env — 환경 구성과 베이스라인 (재측정 Task 01)

날짜: 2026-08-07 / 워크트리: `.worktrees/qa-r1-inventory-order` / 반복 횟수: 1 (첫 시도에 rc=0)

## 베이스라인 고정 (D17·D13)

```
$ git rev-parse HEAD
6d84bd6f9f41e4978f916ee191ab4216cf591da9   # main 머지 커밋(이슈 #43~#50 구현 포함)
$ git status --porcelain -uall
# (출력 없음 = clean)
```

원 실측 baseline은 `713a4cb`(수정 전). 이번 재측정은 `6d84bd6`(RFC-0014~0017
구현 후) — 이 커밋 차이가 측정 대상이다.

## venv 생성·설치 (상대경로, 워크트리 자체 소유 — D17)

```
$ python3.13 -m venv .venv
# rc=0
$ .venv/bin/pip install -e .
# rc=0 (pip 24.3.1 notice만 출력)
```

## 셸 export (매 셸마다 재적용 — D17)

```sh
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
SDK="$(xcrun --show-sdk-path)"
export CPATH="$SDK/usr/include" LIBRARY_PATH="$SDK/usr/lib"
```

## 게이트: dev_doctor

```
$ bash scripts/dev_doctor.sh
# rc=0
… (말미)
SDK 경로    : CPATH/LIBRARY_PATH 설정됨
준비됨.
```

## CLI·플랫폼 확인

```
$ .venv/bin/lnpl --version
lnpl 0.2.0
$ .venv/bin/python --version
Python 3.13.1
$ uname -sr
Darwin 25.1.0        # macOS 26.1
```

판정: 환경 준비 완료. 전제조건 4종(python3.13 / jsonschema / lnpl 콘솔 스크립트 /
LLVM+SDK 경로) 전부 충족, 침묵 실패 없음. 임시 산출물 루트 `.claude/tmp/qa-r1/`
생성(태스크 08에서 일괄 회수 예정).
