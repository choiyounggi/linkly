# 마이그레이션 — expand / migrate / contract (issue #147)

linkly의 저장소는 엔티티별 테이블이 아니라 `entity_id` 키의 단일 JSON payload
컬럼이다([docs/backends.md](backends.md) §3). 그래서 스키마 변경은 SQL DDL이
아니라 **entity 선언을 고치고, 이미 쓰인 행을 그 선언에 맞춰 뒤늦게 채우는
것**이다. 이 문서는 그 절차의 정본이고, 순서(expand → migrate → contract)는
Pramod Sadalage/Scott Ambler의 [Database Refactoring](https://databaserefactoring.com/)
이 정리한 expand-contract 패턴을 linkly의 문맥으로 옮긴 것이다.

## 1. 왜 세 단계인가

entity에 필드를 추가하거나 타입을 바꾼 순간, 그 전에 쓰인 행은 조용히 옛
모양 그대로 저장소에 남는다 — 이 어긋남을 실시간으로 잡아내는 것이
`stored-row-shape-mismatch` 진단(issue #85)이고, 저장소 전체를 훑어 잡아내는
것이 `lnpl db check`다(`docs/backends.md` §3, `plugins/lnpl/skills/
lnpl-authoring/cli-surface.md`의 `db check` 절). 문제는 이 진단이 **경고일
뿐**이라는 것 — 새 필드를 옛 행이 갖지 못한 채로 워크플로를 계속 돌리면
`validate`/refinement가 그 필드를 참조하는 순간 실패한다. 배포와 백필을 한
순간에 맞추는 것은 무중단 배포에서 불가능하므로, 그 사이를 견디는 절차가
필요하다.

## 2. 세 단계

### expand — 관용하는 새 필드를 먼저 연다

새 필드를 추가할 때는 **아직 없는 행도 읽히도록** 만든다. Phase 1의 필드는
전부 선언되면 필수이므로(옵셔널 필드 문법은 없다), "관용"은 실무에서 두
가지 중 하나를 뜻한다:

- 새 필드를 참조하는 `validate`/`set`을 아직 워크플로에 넣지 않는다 — 필드는
  선언돼 있어도 어떤 스텝도 아직 그 값에 의존하지 않으므로, 옛 행이 그
  필드를 갖지 못해도 실행은 실패하지 않는다(`row_shape_mismatches`는
  `stored-row-shape-mismatch`를 warning으로만 낸다, RFC-0021의 "프로그램을
  고치면 사라지는가" 기준 — 데이터를 고치면 사라지는 경고라 여기서는
  블로킹하지 않는다).
- 배포 순서를 그렇게 굳힐 수 없다면, 배포 **전에** 3절의 `lnpl migrate`로
  기본값을 먼저 채운다.

이 단계는 코드 변경(entity 선언)이지, 저장소를 건드리지 않는다.

### migrate — `lnpl migrate`로 배치 백필

```
lnpl migrate <source...> --entity <E> --set <field>=<value> --backend sqlite:<path> [--dry-run]
```

entity `<E>`의 저장된 행 중 `<field>`가 **없는** 행에만 `<value>`를
채운다 — 이미 값이 있는 행은 절대 덮어쓰지 않는다(expand 의미론: 이 행은
이미 새 스키마를 따르고 있으니 손대지 않는다). `<value>`는 그 필드의
선언 타입으로 파싱해(Integer/Boolean/그 외 문자열류) `check_semantic_type`
으로 검증한다 — 타입이 안 맞거나, `<field>`가 그 entity에 선언돼 있지
않거나, `<E>` 자체가 선언돼 있지 않으면 **아무것도 쓰지 않고** 거부한다
(rc 2) — 이 레포의 "추측하지 않고 거부" 원칙 그대로다. 같은 원칙이
네임스페이스에도 적용된다: RFC-0033 디렉터리 레이아웃은 `billing/`과
`shipping/`이 각각 `Order`를 선언하는 것을 허용하므로, 짧은 이름 `<E>`가
둘 이상과 일치하면 후보를 나열하고 거부한다. 그때는 정규화 철자
(`--entity billing.Order` — 생성된 OpenAPI의 스키마 키와 같은 철자)로
대상을 확정한다. 짧은 이름이 하나만 가리키는 레이아웃은 그대로 쓰면 된다. `--dry-run`은 실제로
쓰지 않고 scanned/updated/skipped 개수만 낸다 — 배포 전에 영향 범위를 먼저
가늠하는 용도다. 실제로 값을 쓴 행마다 4절의 `_schema_gen`을 재스탬프한다.
전체 배치는 단일 트랜잭션이다. `fake` 백엔드는 거부된다(영속 저장소가
아니라 백필할 대상이 없다) — `db check`가 이미 세운 것과 같은 경계다.

한 번에 한 필드다. 여러 필드를 채워야 하면 `lnpl migrate`를 필드마다
반복한다 — 트랜잭션 하나가 여러 필드를 섞으면 부분 실패의 관측 표면이
넓어지기 때문이다.

### contract — 옛 참조가 사라진 뒤에 제거

옛 필드(또는 옛 타입)를 실제로 지우는 것은 컴파일러가 강제하는 일이다: 그
필드를 참조하는 워크플로/refinement가 하나도 안 남았는지는 `lnpl compile`이
바로 알려준다 — 참조가 남아 있으면 컴파일이 실패한다. 그래서 이 저장소
쪽에서 별도로 확인할 것은 없다: entity 선언에서 필드를 지우고 컴파일이
통과하면 contract는 끝난 것이다. `lnpl db check`를 다시 돌려 저장된 행이
전부 새 선언과 정합하는지 확인하는 것으로 마무리한다.

## 3. `_schema_gen` — payload 내부 스키마 세대 스탬프

`lnpl migrate`가 실제로 쓴 행, 그리고 `lnpl run`이 `create`/`set`으로
쓰는 모든 행은 payload 내부에 예약 키 `_schema_gen`을 함께 갖는다 — 그
entity의 선언 필드(derived 제외) 이름·타입 목록을 정렬해 계산한 sha256
12자리 digest다(`impl/lnpl/interp.py`의 `schema_generation`). 같은 선언이면
언제 계산해도 같은 값이고(결정적), 빌드 시각이나 실행 환경은 전혀 섞이지
않는다 — `impl/lnpl/provenance.py`(issue #136)가 이미 세운 "산출물이 자기
유래를 결정적으로 말한다" 원칙을 저장된 행 하나하나로 좁힌 것이다.

**`lnpl_rows`/`lnpl_outbox`의 DDL은 이 이슈로 바뀌지 않는다** —
`_schema_gen`은 새 컬럼이 아니라 기존 `payload` TEXT 컬럼 안의 평범한
JSON 키다(`docs/compatibility.md`가 지키는 sqlite 표면 보존과 같은 이유).
그래서:

- 이 키가 없는 행은 **스탬프 이전에 쓰인 행**으로 식별할 수 있다 — 저장소
  자체를 훑어 어떤 행이 이번 마이그레이션의 대상인지 판단하는 근거다.
- 이 키는 `RepositoryDriver` SPI(§8/§9/§10)가 알지 못하는 애플리케이션
  계층 관례다 — 드라이버는 이 키가 있는 payload를 다른 키와 똑같이
  저장하고 그대로 돌려줄 뿐이다. 저장된 행을 읽는 모든 경로(interp.py의
  `read`/`list`, `lnpl serve`의 GET 단일/목록)가 역직렬화 직후 이 키를
  벗긴다 — 워크플로 바인딩·RowSet·HTTP 응답 어디에도 나타나지 않는다.

## 참고

- 저장 계층·동시성·백업: [docs/backends.md](backends.md)
- sqlite 표면 보존 계약: [docs/compatibility.md](compatibility.md)
- `lnpl migrate`/`lnpl db check` 플래그 전체: [plugins/lnpl/skills/lnpl-authoring/cli-surface.md](../plugins/lnpl/skills/lnpl-authoring/cli-surface.md)
- 자기 유래를 말하는 산출물 선례(issue #136): `impl/lnpl/provenance.py`
