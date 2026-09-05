# 02 — lint (import-linter, R1 boundary proof)

D2: `.importlinter`는 `orderhub.catalog` / `orderhub.payments` / `orderhub.app`가
`orderhub.orders.inventory`(Stock 선언 + reserve/release)를 import하지 못하게 막는
`forbidden` contract 1개다. `allow_indirect_imports = True`로 설정한다(아래 이유 참고).

## 위반 코드 삽입 후 실행 (rc≠0이어야 함)

`src/orderhub/payments/__init__.py`에 임시로 추가:
```python
from orderhub.orders.inventory import reserve  # noqa: F401  # TEMP violation for D2 proof
```

명령: `PYTHONPATH=src .venv-s5/bin/lint-imports --config .importlinter`

```
orders.inventory is internal to the orders team BROKEN

Contracts: 0 kept, 1 broken.


----------------
Broken contracts
----------------

orders.inventory is internal to the orders team
-----------------------------------------------

orderhub.payments is not allowed to import orderhub.orders.inventory:

-   orderhub.payments -> orderhub.orders.inventory (l.2)


rc=1
```

## 위반 제거 후 재실행 (rc=0)

임시 import 라인 제거, 재실행:

```
Analyzed 12 files, 7 dependencies.
----------------------------------

orders.inventory is internal to the orders team KEPT

Contracts: 1 kept, 0 broken.
rc=0
```

## Frictions 발견 (기록만, F-항목으로도 카운트)

1. **`lint-imports`는 cwd 기준으로 설정을 찾는다.** `src/`에서 실행하면
   "Could not read any configuration"(rc=1, 설정 파싱 실패이지 계약 위반이 아님) —
   케이스 루트에서 `--config .importlinter`로 명시 실행해야 한다.
2. **default `forbidden` contract는 간접(transitive) import도 검사한다.** 처음
   구현 시 `orderhub.db`가 `orderhub.orders.inventory`의 `STOCK_DDL` 상수를 import해서
   스키마를 초기화했는데, `orderhub.app`이 `orders.router` → `orders.service` →
   `orders.inventory`로 이어지는 정당한(같은 팀 내부) 경로를 통해 간접적으로
   `orderhub.orders.inventory`에 닿는 것도 위반으로 잡혔다(`app -> ... -> orders.inventory`).
   이것은 실제 아키텍처 버그였다 — `db.py`(공유 인프라)가 굳이 `orders.inventory`의
   DDL을 import할 필요가 없었으므로, `stock`/`stock_reservation` DDL을 `db.py`
   자체 스키마 스크립트로 되돌려 근본 원인을 없앴다. 그런데도 `app.py`가 정당하게
   `orders` 라우터를 조립하는 한 `app -> orders.router -> orders.service ->
   orders.inventory` 경로 자체는 남는다 — R1의 의도("Stock을 orders 팀 밖에서
   **직접** 참조하면 안 된다")는 직접 import 금지이지 "app이 orders 기능을
   조립하는 것 자체를 금지"가 아니므로, `allow_indirect_imports = True`로 계약을
   직접-import만 검사하도록 좁혔다. 이 결정이 없으면 R1을 만족하는 정상적인
   FastAPI 라우터 조립 자체가 불가능해진다(고의로 깨야만 통과하는 계약이 됨).
