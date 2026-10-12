# RFC-0064: 0행에 영향을 준 update·delete는 not-found로 실패한다

## Status

- Status: Draft
- Updates: 없음 — 기존 RFC의 어느 문장도 바꾸지 않는다. RFC-0012 §G12.2, RFC-0025, RFC-0030, RFC-0052 §3은 쓰기가 영향 행 수를 돌려주고 바인딩하지 않는다고만 말하며, 그 문장은 그대로 참이다.
- References: issue #197(읽기 미스 `not-found`), issue #215, RFC-0032(트랜잭션 롤백), RFC-0040 §7 (E7, 소비 경로 거부), RFC-0052 §3(`by` 쓰기)

## Motivation

issue #215: 같은 키에 대해 `find`는 이슈 #197부터 404인데, `update`/`delete`는 행이
없어도 `completed`로 끝났고 `lnpl serve`는 200을 냈다. 아무것도 바꾸지 않은 쓰기가
성공으로 보고되는 비대칭이다.

- RFC 9110 §15.5.5: "The 404 (Not Found) status code indicates that the origin
  server did not find a current representation for the target resource." 대상이
  없는 쓰기는 성공이 아니라 404다.
- Amazon DynamoDB 조건 표현식(이슈가 인용): 조건부 update/delete는 "The condition
  expression must evaluate to true in order for the operation to succeed;
  otherwise, the operation fails". 존재를 전제로 한 쓰기는 그 전제가 어긋나면
  실패를 돌려준다.

## Guide-level Explanation

```lnpl
entity Stock
    field
        id UUID
        productId UUID
        quantity Integer

service StockService

workflow Restock
    update stock by input.productId

workflow Remove
    delete stock by input.productId
```

빈 저장소에서 두 워크플로는 모두 `not-found`로 실패한다. `lnpl serve`는 404를,
`consume by`로 받은 이벤트는 422를 낸다. 행이 있으면 이전과 같이 `completed`다.

`delete`도 기본은 실패다. **멱등 delete 표기는 이번 변경에 없다** — 이미 지워진 행의
delete를 성공으로 두는 선택은 §Open Questions에 미래 작업으로 적는다.

`fake` 백엔드에서 기본 시드는 처음 `read`하는 엔티티만 채운다. 그래서 어떤 엔티티를
`update`/`delete`로 처음 건드리는 워크플로는 기본 시드로 돌려도 `not-found`로
실패한다.

## Reference-level Specification

### 1. 런타임 규칙

`RepositoryDriver.execute`가 `update`/`delete`(bare 또는 `by <ref>`)에 `{"affected": 0}`을
돌려주면 그 스텝은 `failure_kind` `not-found`로 실패한다. 이유 문구는
`repository <op> found no row for <entity>`다. 트레이스 스팬의 `found`는 거짓이고,
실패한 시도마다 읽기 미스와 같은 1 ms를 쓴다. 재시도 분류는 RFC-0003의 연산별
멱등성 그대로 바뀌지 않는다.

### 2. 트랜잭션

실패한 스텝은 RFC-0032의 롤백을 그대로 탄다: 그 실행의 앞선 쓰기는 버려진다.

### 3. serve와 소비 경로

`docs/serving.md` M8b(404 `not-found`)와 E7(422 `event-rejected`)은 `failure_kind`로
매핑하므로 코드 변경이 없다. 설명만 0행 쓰기를 포함하도록 넓힌다.

### 4. 드라이버 계약

`FakeRepository.execute(..., "update", key)`는 실제 개수를 돌려준다(없으면 0, 삽입하지
않는다). `RepositoryDriverTCK`에 `test_updating_an_absent_row_reports_affected_zero`가
새로 생긴다. 외부 드라이버 lnpl-postgres와 lnpl-redis는 이 케이스를 통과해야 한다
(후속 이슈). 부재 행에 1을 돌려주는 드라이버는 이 규칙을 그 백엔드에서 조용하게
만든다.

### 5. 모드 B

`backend._lnpl_ops`는 시드도 앞선 create도 없는 엔티티의 bare `update`/`delete`를
실패로 예측하고, `_failure_attempts`는 같은 1 ms를 매긴다. `by` 워크플로는 RFC-0052의
거부 그대로다.

## Examples

```lnpl
entity Stock
    field
        id UUID
        productId UUID
        quantity Integer

service StockService

workflow Restock
    update stock by input.productId

workflow Remove
    delete stock by input.productId
```

```
Restock  status=failed  failed_step="update stock by input.productId"  failure_kind=not-found
Remove   status=failed  failed_step="delete stock by input.productId"  failure_kind=not-found
serve    HTTP 404 not-found
```

## Alternatives

| 대안 | 기각 사유 |
|------|----------|
| 멱등 delete를 기본으로(0행이어도 성공) | 사용자 결정은 기본 실패다. RFC 9110 §9.2.2의 멱등은 반복해도 같은 의도된 효과를 뜻하지, 부재한 대상에 성공을 돌려준다는 뜻이 아니다. 같은 키의 `find`는 이미 #197로 404다 |
| 멱등 delete 표기를 이번에 추가 | 이번 변경에서 제공하지 않는다 |
| 드라이버가 not-found 오류를 던진다 | `{"affected": n}` SPI를 깬다 |
| update/delete로 시작하는 엔티티를 기본 fake 시드에 채운다 | 미룬다 — `lookup_key_source`와 RFC-0052 §4의 변경이 필요하다 |

## Open Questions

1. 명시적 멱등 delete 표기 — 미래 작업이며 이번 변경에서는 제공하지 않는다.
2. update/delete로 시작하는 엔티티의 기본 시드.
3. `not-found`(읽기·쓰기 모두)를 `retry`에서 제외할지 — 404는 재시도할 가치가 없다는 지침이 있다.
4. lnpl-postgres와 lnpl-redis가 새 TCK 케이스 `test_updating_an_absent_row_reports_affected_zero`를 통과하도록 하는 후속 이슈.
