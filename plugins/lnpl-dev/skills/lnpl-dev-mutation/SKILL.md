---
name: lnpl-dev-mutation
description: Use before running or interpreting linkly's mutation harness (`impl/tests/mutation_check.py`), or after adding tests that read new repository paths. The sweep is slow, anchor-fragile, and its exit code is easy to mask — and a stale copy list makes every mutant fail identically.
---

# 뮤테이션 스윕

`impl/tests/mutation_check.py`는 77개 뮤테이션을 심고 각각이 스위트에 잡히는지 본다.
평범한 테스트와 성질이 다르므로 돌리기 전에 알아야 할 것이 넷 있다.

```bash
PYTHONPATH=impl .venv/bin/python impl/tests/mutation_check.py
```

## 1. 느리다 — 13~25분

뮤턴트마다 레포 사본을 만들고(`.venv` 포함) 전체 스위트를 돌린다. LLVM 바이너리
컴파일이 뮤턴트마다 일어난다. 백그라운드로 돌리고 다른 일을 하되, **워킹 트리는
건드리지 마라**(아래 2번).

한 앵커만 확인하고 싶으면 전체를 돌리지 말고 `mutation_check`를 import해서 해당
뮤테이션 하나만 구동하라 — 1분이면 된다.

## 2. 앵커가 리터럴 텍스트 치환이다

각 뮤테이션은 `(이름, 파일, 찾을 문자열, 바꿀 문자열)`이다. **정규식이 아니라
정확한 문자열 일치**다. 그래서:

- 앵커로 쓰인 코드 줄을 리팩터링하면 그 뮤테이션이 조용히 아무것도 안 바꾸고,
  "잡히지 않은 뮤테이션"으로 보고된다
- 실행 중에 워킹 트리를 고치면 뮤턴트 사본이 서로 다른 상태에서 만들어진다

## 3. 종료 코드를 파이프로 가리지 마라

```bash
# 나쁨 — tail의 코드를 읽는다
python impl/tests/mutation_check.py | tail -20

# 좋음
python impl/tests/mutation_check.py > out.txt 2>&1; rc=$?; echo "rc=$rc"; tail -20 out.txt
```

마지막 줄 `MUTATION CHECK: PASS/FAIL`을 직접 읽는 것이 가장 확실하다.

## 4. 테스트가 읽는 경로는 복사 목록에 있어야 한다

`make_tree`는 `TREE_CONTENTS`에 열거된 최상위 항목만 복사한다. 테스트가 읽는
경로가 빠지면 **77개 뮤턴트가 전부 같은 실패를 내고**, 잡힌 뮤테이션과 그냥 깨진
트리를 구별할 수 없게 된다.

이 함정은 이미 두 번 밟혔다 — `mlir`/`CHARTER.md`(RFC-0004 S4), 그리고
`plugins`/`.claude-plugin`(플러그인 작업, 뮤턴트 트리에서 81건 중 60건 실패).
**전체 스위트는 두 번 다 초록이었다.** 평범한 회귀 검사로는 보이지 않는다.

지금은 `impl/tests/test_mutation_tree.py`가 이 결합을 고정한다 —
`os.path.join(REPO, "<name>", ...)`로 읽는 이름은 `TREE_CONTENTS`에 있어야 한다.
새 최상위 디렉터리를 읽는 테스트를 추가했다면 그 가드가 먼저 알려줄 것이다.

## 알려진 선행 결함

뮤테이션 `RFC-0003: drop the retry attempt cap`은 실패하지 않고 **행(hang)** 한다 —
`interp.py`의 무한 재시도를 경계 짓는 테스트가 없기 때문이다. `main`에서도 그러므로
최근 변경 탓이 아니다.
