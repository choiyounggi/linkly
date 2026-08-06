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

## 기대 결과 — 77개 전부 CAUGHT

`MUTATION CHECK: PASS`가 정상이다. 어떤 실패든 새 회귀로 취급하라.

**HANG이 보이면 그것은 RED가 아니다.** 하네스는 `run_suite(timeout=300)`으로
GREEN/RED/HANG을 가른다. 뮤테이션이 무한 루프를 만들면 "잡혔다"가 아니라 "판정
불가"다 — 스위트가 반환하지 않으므로 어떤 테스트도 그것을 관찰하지 못한다.
`RFC-0003: drop the retry attempt cap`이 정확히 그랬고(2026-08-05 실측),
**테스트를 더 써서 닫을 수 없는** 종류의 구멍이었다. 관찰하려는 테스트 자신이
돌아오지 않기 때문이다.

닫은 방법은 런타임에 경계를 하나 더 두는 것이었다 — `MAX_STEP_ATTEMPTS`(RFC-0013,
RFC-0003 §Policy Enforcement 갱신). 상한이 하나뿐인 재시도 루프는 그 하나를 잃는
순간 실패가 아니라 무한 루프가 된다. 데드라인은 대신하지 못했다: `timeout`을
선언하지 않은 워크플로에는 데드라인이 아예 없었다.

**이 패턴을 일반화해서 읽어라.** 뮤테이션이 HANG으로 끝나면 테스트 부족이 아니라
**런타임에 경계가 하나뿐이라는 신호**다. 그때 필요한 것은 테스트가 아니라 계약
개정이다.
