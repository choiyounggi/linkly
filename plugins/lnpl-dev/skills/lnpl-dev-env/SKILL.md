---
name: lnpl-dev-env
description: Use before running linkly's test suite, when tests fail for reasons that look unrelated to the change, when setting up a fresh clone or worktree, or when writing a task spec another session will execute. This repo has four preconditions and every one of them fails silently.
---

# 스위트를 돌리기 전에

이 레포의 전제조건은 넷이고 **전부 조용히 실패한다.** 빠뜨리면 테스트가 실패하는데
그 실패가 원인을 가리키지 않아서 코드 회귀로 오독하기 쉽다.

```
bash scripts/dev_doctor.sh
```

exit 0이면 준비된 것이다. exit 1이면 출력에 적힌 조치를 그대로 따른다.

## 무엇이 조용히 실패하는가

| 전제 | 빠뜨렸을 때 보이는 것 |
|------|------------------------|
| `python3.13` (system `python3`는 3.14) | `venv`가 `ensurepip`에서 죽어 **pip 없는 venv**가 생긴다. 이후 모든 `pip install`이 불가능한데 에러는 처음 한 번뿐이다 |
| `.venv`에 `jsonschema` | `scripts/validate_ir.py --self-test`만 실패 — 무관해 보인다 |
| `.venv`에 `lnpl` 콘솔 스크립트 (`pip install .`) | 훅이 "CLI 없음" 분기로 **우아하게** 빠져 3건이 엉뚱한 이유로 실패한다 |
| LLVM 툴체인 + `CPATH`/`LIBRARY_PATH` | mode B 테스트가 대량으로 깨진다(실측 7 failures / 62 errors). `main`에서도 똑같이 재현되므로 **회귀가 아니다** |

## 스위트 실행

```bash
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
SDK="$(xcrun --show-sdk-path)"
export CPATH="$SDK/usr/include"      # homebrew clang은 SDKROOT를 무시한다
export LIBRARY_PATH="$SDK/usr/lib"

PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl \
  2>&1 | grep -E "^(OK|FAILED|Ran )"
```

`grep`은 장식이 아니다. 테스트가 런타임 트레이스를 stdout에 찍어서 `tail`만 쓰면
요약 줄이 묻힌다 — 붉은 스위트를 초록으로 오독하는 경로다.

`impl/lnpl/`을 고친 뒤에는 콘솔 스크립트를 다시 설치한다:

```
.venv/bin/pip install --force-reinstall --no-deps .
```

## 워크트리와 병렬 세션

- 워크트리마다 **자기 `.venv`**를 만들고 **상대경로** `.venv/bin/python`으로 부른다.
  메인 체크아웃의 venv를 절대경로로 공유하면 가드레일에 막히고, 막힌 명령은 출력이
  없어서 "돌지 않은 스위트"를 통과로 오독하게 된다.
- **다른 세션이 이 레포에서 동시에 작업한다.** 계획을 세우기 전에 `git rev-parse HEAD`와
  `git worktree list`를 다시 재고, 세션 초반에 읽은 상태를 믿지 마라.

## 다른 세션에 넘길 태스크를 쓸 때

명령과 기대 출력을 스펙에 박아 넣기 전에 **실행자가 갖게 될 환경에서** 먼저 돌려라 —
당신의 셸이 아니라. 당신 셸엔 위 넷이 이미 설정돼 있어서 전부 보이지 않는다.
새 워크트리를 하나 만들어 스펙의 첫 명령을 거기서 실행해 보는 것이 가장 싸다.
