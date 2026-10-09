# evidence/00 — Environment

## Commands & output

```
$ python3.13 -m venv .venv && .venv/bin/pip install -e .
Successfully installed attrs-26.1.0 jsonschema-4.26.0 jsonschema-specifications-2025.9.1 lnpl-0.8.0 referencing-0.37.0 rpds-py-2026.6.3

$ .venv/bin/lnpl --version
lnpl 0.8.0

$ .venv/bin/python --version
Python 3.13.1

$ git rev-parse --short HEAD
264e344

$ bash scripts/dev_doctor.sh
rc=1
linkly 기여자 환경 진단
------------------------
python3.13  : Python 3.13.1
venv        : Python 3.13.1
jsonschema  : 설치됨
lnpl 스크립트: lnpl 0.8.0
MLIR/LLVM   : 없음 — mlir-opt mlir-translate
  → brew install llvm
  → export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
  → 없으면 mode B 테스트가 대량으로 깨진다 — 코드 회귀가 아니라 환경이다.
sysroot 정합: /Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX26.2.sdk
SDK 경로    : CPATH/LIBRARY_PATH 미설정
  → 이 세션에서 export 하라 (homebrew clang은 SDKROOT를 무시한다)
```

rc=1은 MLIR/LLVM 미설치(모드 B) 때문 — AGENTS.md가 명시한 환경 문제이며 코드 회귀가
아니다. read-only 진단이므로 조치하지 않고 그대로 기록한다. 이 케이스는 모드 A(인터프리터)
+ serve만 쓰므로 모드 B 불필요.

## Routing (AGENTS.md)

AGENTS.md 라우팅 표에 따라:
- `.lnpl` 작성·수정·리뷰 → `lnpl-authoring` (어휘 정본; `.lnpl`은 한 줄이라도 쓰기 전에 먼저 간다)
- `spec` 블록 작성·리뷰 → `lnpl-spec`
- 변경을 "됐다"고 말하기 직전 → `lnpl-verify` (게이트)
- 플러그인 미설치 세션이면 `plugins/lnpl/skills/{lnpl-authoring,lnpl-spec,lnpl-verify}/SKILL.md`를 직접 읽는다.

`impl/`, `scripts/`는 열람하지 않는다(§2 예외: `scripts/dev_doctor.sh` 실행만 허용).

## Docs read

(다음 태스크가 이 절에 계속 추가한다 — 파일 경로 + `wc -l`)

- AGENTS.md — 66 lines (routing table; read for §2 exception + skill routing)

## Rounds

D4 규칙: `.lnpl`을 고치고 다시 컴파일/실행한 횟수가 1라운드다. evidence/01-authoring.md와
evidence/04-spec.md에 `- round N: <why>` 한 줄씩 남긴다(왜 다시 돌렸는지).
