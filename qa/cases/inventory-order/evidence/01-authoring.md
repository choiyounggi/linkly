# evidence/01-authoring — 저작 세션 로그 (Task 03)

**차터**(D6): Explore `.lnpl` 저작(inventory-order)을 생성 레퍼런스 5종
(verbs/declarations/types/grammar/spec)과 examples/checkout.lnpl만으로 수행하여
어휘·문법 한계를 발견한다.

**시도 카운터: 5** (.lnpl 수정→재실행 1회 = 1시도; 시도 1~3은 아래 표,
시도 4~5는 spec 단계에서 발생 — evidence/08 타임라인 참조)

## 레퍼런스 통독 소요 관찰

- 5종 합계 198줄 — 통독 부담 낮음. verbs 표 16행, 문법 키워드 폐쇄 집합 명시.
- 파이프라인 명령 자체는 authoring 레퍼런스에 없고 `impl/lnpl/cli.py`를 직접
  읽어야 전모(–o, --payload, --field, --workdir 등)가 나온다 → F-후보(라우팅 갭).

## 시도 로그

| # | 변경 | 결과 | 진단 원문 |
|---|------|------|-----------|
| 1 | 초안: 가드 `when product.stock >= order.quantity`, refine OrderStatus enum, spec 3블록 | **rc=2 컴파일 에러** | `compile error: line 44: invalid condition: invalid value 'order.quantity': 'product.stock >= order.quantity'` |
| 2 | 가드를 `when product.stock > 0` 리터럴 비교로 후퇴 | rc=0, 경고 1건 | `warning: declared-measured-only [perf.order] performance response — declared but measured: …` |
| 3 | IR 검사에서 가드가 다음 1스텝만 감싸는 것을 발견 → `update product` 앞에 가드 중복 | rc=0, 경고 1건(동일), Guard 노드 2개 각각 create/update를 감쌈 | 동일 |

진단 품질 판정(D7): 시도 1의 에러는 행 번호(44)와 문제 토큰(`order.quantity`)을
정확히 지목 — **원인을 가리킴(양호)**. 단, "우변은 리터럴만 가능"이라는 규칙
자체는 에러에도 레퍼런스에도 없어서 반증 실험으로만 알 수 있었다.

## 프로브 판정 (P1~P6)

- **P1 재고 가드**: 성공 — `when product.stock > 0` (checkout.lnpl 동형, Guard 노드 생성 확인).
- **P2 엔티티 간 비교(stock ≥ quantity)**: **표현 불가** — 가드 우변에 필드 참조 불가(시도 1 에러 원문). 우회: 리터럴 비교(`> 0`)로 후퇴 → "수량 인지 재고 검사"는 표현되지 않음. F-확정.
- **P3 재고 차감(산술)**: **표현 불가** — `update` 동사는 있으나(verbs.md) 산술·할당 문법이 grammar.md에 없음. 우회: `update product` 스텝만 두어 op=update RepositoryCall이 발생함을 관측. "5→3 차감" 값 의미론은 표현되지 않음. F-확정.
- **P4 상태 전이(created→confirmed)**: **부분 성공** — 타입 수준은 `refine OrderStatus of Text` + `enum created confirmed`로 표현됨(IR facets.enum 확인; 단 facet 문법 예시가 레퍼런스에 없어 추측 성공). 전이 규칙("created에서만 confirmed로")은 어휘 없음 → F-확정(부분).
- **P5 부족 시 거부**: **우회 성공** — 가드는 바로 다음 1스텝만 감싼다(IR: guard.1 children=[step.3]). `update product`가 가드 밖에서 무조건 실행되는 문제를 가드 중복(시도 3)으로 우회. "거부(실패 응답)" 의미론은 없고 "스텝 스킵"만 있음 → F-확정(부분).
- **P6 경계 3종 spec**: given `stored Product stock 0`(S3)·`empty repository`(retry) 표현됨(컴파일 통과). qty=0(S4)은 `quantity PositiveInteger`(min=1 프리셋)로 타입 거부에 위임. 정확 한계(S5, qty=stock)는 P2 불가의 귀결로 spec 표현 불가 — 실행 단계에서 관측 시도. 러너 평가는 Task 06에서 실측.

## 남은 진단 판정 (lnpl-verify §1)

- `declared-measured-only [perf.order]`: **의도됨** — response 예산은 측정·보고
  전용임을 알고 선언(파일 헤더 주석에 기계/서술 구분 명시). 유지.
