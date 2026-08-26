# evidence/00-env — 환경 구축과 베이스라인 (T01)

> 2026-08-26: 이 기록은 `security encrypt` 어휘 제거(#127) 이전의 실행이다.

- 시각: 2026-08-05T21:20+0900
- 워크트리: `.worktrees/qa-t2-payment-refund`
- 베이스라인 commit: `713a4cba14a5ace278801c193abbc809ab09894e`
- 시작 시 `git status --porcelain` 행 수: **0** (clean)

## venv (워크트리 자체, 상대경로)

```
$ python3.13 -m venv .venv && .venv/bin/pip install -e .
rc=0
```

시도 1회. `.venv/`와 `.claude/tmp/`는 `.gitignore` 3·4·8행에 의해 무시됨(무변경 증명에 영향 없음).

## 셸 export (매 셸마다 — lnpl-dev-env SKILL.md)

```
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
SDK="$(xcrun --show-sdk-path)"
export CPATH="$SDK/usr/include" LIBRARY_PATH="$SDK/usr/lib"
```

## dev_doctor 게이트

```
$ bash scripts/dev_doctor.sh
doctor-rc=0
```

출력(원문):

```
linkly 기여자 환경 진단
------------------------
python3.13  : Python 3.13.1
venv        : Python 3.13.1
jsonschema  : 설치됨
lnpl 스크립트: lnpl 0.2.0
MLIR/LLVM   : /opt/homebrew/opt/llvm/bin/clang
SDK 경로    : CPATH/LIBRARY_PATH 설정됨
```

주의: 최초 1회 doctor 실행은 `.claude/tmp/` 부재로 rc=1(캡처 파일 생성 실패 — 진단 스크립트 자체 문제 아님, 내 캡처 경로 문제). 디렉터리 생성 후 rc=0. 시도 2회로 계수.

## CLI 확인

```
$ .venv/bin/lnpl --help ; rc=0   (lnpl 0.2.0)
```
