# Token benchmark — LNPL ↔ FastAPI equivalence mapping (issues #142, #251)

Defines what "behaviorally equivalent" means for the six scenarios
measured by measure_tokens.py (issues #142, #251). This is the source of
truth for the mapping; REPORT.md quotes it rather than re-deriving it. Both
implementations run against an in-memory fake store — `capability postgres`/`capability redis` are descriptive in the
`.lnpl` source (see examples/linkhub.lnpl header) and are not exercised by
either side, so no real database/cache is required to compare them.

## Conventions (issue #251 ports)

- Reference behaviour: the LNPL interpreter with one `interp.FakeRepository`
  kept across requests (rows persist; a read of an absent row fails
  `not-found`; a create on an existing id conflicts). Each port holds one
  in-memory `Store` dataclass per app. No SQLAlchemy on either side (issue
  #251's "FastAPI+SQLAlchemy" is a REPORT limit).
- Surface: exactly the paths `lnpl openapi <file>` prints, plus
  `POST /-/events/<event-slug>` for `consume by` and
  `POST /-/schedules/<event-slug>` for `on schedule`. Each derived
  `GET /<svc>/<entity>/{id}` returns the stored row or 404 `not-found`.
- Status codes (docs/serving.md M-table): 200 completed (guard skip
  included), 400 `validation-failed`, 401 `auth-missing`, 404 `not-found`,
  409 `conflict`, 504 `deadline-exceeded`; error body `{"code", "detail"}`
  only. Consume route: 400 `cloudevents-invalid` / `cloudevents-id-too-long`,
  200, 422 `event-rejected`.
- Validation: `validate(payload, fields)` copies `interp.check_semantic_type`:
  missing -> `missing required field`, null -> `is null`, UUID =
  case-insensitive canonical 8-4-4-4-12 hex pattern of `lnpl/types.py`,
  Text = JSON string, Integer = JSON integer and not boolean, Money = any
  non-null value. pydantic was not used: its `uuid.UUID` accepts hyphenless,
  braced and `urn:uuid:` forms LNPL rejects, and strict unions reject Money
  values LNPL accepts.
- Retry: `policy retry N` = 1 + N attempts on the repository read, retried
  only on `not-found`. Timeout: one deadline per run, checked before every
  step and retry attempt. Cache: `"<entity>:<id>"` keys, TTL from
  `performance cache`.
- Comments: new LNPL sources carry only a 2-line header, new ports only a
  2-line module docstring.
- Not modelled on either side: durability, transactions/rollback (in every
  scenario the only repository write is the last step that can fail), the
  idempotency claim store, the full RFC 9457 body, 200-body trace fields,
  framework-level M1/M2/M4/M5 (FastAPI answers malformed JSON with 422, not
  400 `body-unreadable`), `/-/healthz` `/-/readyz` `/-/metrics`.

## linkhub

LNPL: benchmarks/token/scenarios/linkhub.lnpl — byte copy of
examples/linkhub.lnpl at 43d8bbd (before RFC-0048 added
`workflow CountPopularBookmarks`). FastAPI: equiv/linkhub_fastapi.py
(issue #142).

| LNPL (scenarios/linkhub.lnpl) | FastAPI (equiv/linkhub_fastapi.py) | Equivalent? |
|---|---|---|
| `entity Bookmark` fields `id UUID`, `url URL`, `title Text`, `owner UUID`, `savedAt DateTime`, `visits VisitCount` | `BookmarkCreate` (input) + `Bookmark` dataclass (stored row), same 6 fields | Yes — field-for-field |
| `refine VisitCount of Integer / min 0` | `visits: int = 0`, never set below 0 (no decrement path in either scenario) | Yes |
| `refine URL` preset (`Text`, maxLength 2048, pattern `^https?://[^\s]+$`) | `URL_PATTERN` regex + `URL_MAX_LENGTH` in `BookmarkCreate.url_matches_pattern` (same pattern, same limit) | Yes — same regex literal |
| `workflow SaveBookmark`: `validate input` → `pipeline persist`(`create bookmark`, `cache bookmark`, `emit bookmarkSaved`) | `POST /bookmarks` → pydantic validation, then `save_bookmark()` runs `create_bookmark` → `cache_bookmark` → `emit_bookmark_saved` in the same order | Yes — same 3-step order, no partial-failure branching in either (LNPL `pipeline` has no `merge`/rollback here) |
| `workflow GetBookmark`: `validate input` → `find bookmark` | `GET /bookmarks/{id}` → `get_bookmark()` → `find_bookmark()` | Yes |
| `service LinkHubService` / `policy retry 3` | `with_retry(RETRY_ATTEMPTS=3, ...)` wraps `find_bookmark` in `get_bookmark()` (mirrors "enforced" retry on the read side per `plugins/lnpl/skills/lnpl-authoring/references/declarations.md`'s enforcement matrix — `run_workflow re-runs a failed step while its effects are idempotent`, and `find` is idempotent) | Yes — same attempt count, same target step |
| `service LinkHubService` / `performance cache 5m` | `CACHE_TTL_SECONDS = 5 * 60`, stored as `expires_at` on cache write | Yes — same TTL budget; enforcement doc marks `performance cache` **enforced** ("owns the TTL budget every CacheAccess set is written with") |
| `create` conflicts when the same `(entity, id)` key already exists (spec.md "저장소 시드와 `create` 충돌") | `create_bookmark` raises `RepositoryConflictError` when `payload.id in store.bookmarks` | Yes — same key (id), same failure semantics |
| `find` fails hard when the row is absent (`repository read found no row for entity.bookmark`) | `find_bookmark` raises `RepositoryNotFoundError` with the matching message | Yes — same message, used to keep the ported spec's `error reason` assertions meaningful |
| spec 1 (SaveBookmark, normal): `empty repository` → `saveBookmark` → `completed`, `rows Bookmark 1`, `cache written` | `test_save_bookmark_success` — POST with a valid payload against an empty store → 201, `len(store.bookmarks) == 1`, cache has 1 entry | Yes — ported 1:1, see tests/test_equiv_spec.py |
| spec 2 (SaveBookmark, error): `input.url not-a-url` → `saveBookmark` → `failed`, `error reason does not match URL's pattern` | `test_save_bookmark_rejects_invalid_url` — POST with `url="not-a-url"` → 422, error body contains `"does not match URL's pattern"` | Yes — same substring |
| spec (GetBookmark, boundary): `empty repository` → `getBookmark` → `failed`, `rows Bookmark 0` | `test_get_bookmark_empty_repository_fails` — GET a random id against an empty store → 404, `len(store.bookmarks) == 0` | Yes |
| `event BookmarkSaved on Bookmark create` | `store.events.append({"name": "BookmarkSaved", ...})` in `emit_bookmark_saved` | Yes — LNPL's own enforcement doc does not list `event ... on <Entity> create` in the enforcement matrix (only `event schedule` is), so both sides treat it as a plain recorded emission, no assertions beyond spec's own `cache written`/`effects complete` keys carry over |

### Known non-equivalence (documented, not hidden)

- LNPL's `spec` `effects complete` key (no no-op step) has no FastAPI
  analogue — Python has no closed verb lexicon to be "complete" against, so
  the ported tests assert observable outcomes (status code, store contents,
  cache contents) instead. This is a methodology limitation, not a behavior
  difference; see REPORT.md's limitations footnotes.
- `policy retry 3` is **enforced** by LNPL's interpreter at the workflow-step
  level for idempotent effects (declarations.md enforcement matrix). The
  FastAPI port reimplements the same attempt count by hand (`with_retry`) —
  equivalent behavior, not equivalent enforcement mechanism (LNPL's is a
  language-level guarantee; the port's is a one-off helper an author must
  remember to call).
- The port uses REST paths `POST /bookmarks`, `GET /bookmarks/{bookmark_id}`
  and answers 201/422/404, where LNPL serves
  `POST /link-hub-service/save-bookmark`, `POST /link-hub-service/get-bookmark`,
  `GET /link-hub-service/bookmark/{id}` with 200/400/404.
- `with_retry(3, ...)` makes 3 attempts, LNPL `retry 3` makes 4
  (unobservable on the in-memory store).
- Both files are frozen so the m1/m2 edit baselines stay byte-identical.

## checkout

LNPL: examples/checkout.lnpl (live, read only). FastAPI:
equiv/checkout_fastapi.py. Tests: tests/test_checkout_equiv_spec.py.

| LNPL (examples/checkout.lnpl) | FastAPI (equiv/checkout_fastapi.py) | Equivalent? |
|---|---|---|
| `entity Product` fields `id UUID`, `name Text`, `stock Integer`, `price Money` | `PRODUCT_FIELDS` + `Store.products` rows | Yes — field-for-field |
| `entity Order` fields `id UUID`, `quantity Integer`, `total Money`, `placedAt DateTime` | `ORDER_FIELDS` + `Store.orders` rows (fields copied from the payload when present) | Yes |
| `validate product` | `validate(payload, PRODUCT_FIELDS)` -> 400 `validation-failed` | Yes — same checks as `interp.check_semantic_type` (Conventions) |
| `find product` + `policy retry 3` | `with_retry(lambda: get_row(store.products, ...), deadline)`, 1 + `RETRY` attempts, retried only on `not-found` | Yes — attempt count unobservable (see below) |
| `cache product` + `performance cache 5m` | `cache_product`, key `product:<id>`, `expires_at` = now + `CACHE_TTL_SECONDS` (300) | Yes |
| `when product.stock > 0` | `if row["stock"] > 0` else `skipped.append("product.stock > 0")`, still 200 | Yes |
| `create order` | `create_order` -> 409 `conflict` on an existing id | Yes |
| `policy timeout 3s` | `TIMEOUT_SECONDS = 3`, `check_deadline` before every step and attempt -> 504 `deadline-exceeded` | Yes — untested (see below) |
| `performance response < 50ms` | `slo_met = elapsed_ms <= SLO_MS` in the 200 body | Yes — same `<=` comparison |
| `security jwt` | `require_auth`: `Authorization` header presence on all 3 routes, else 401 `auth-missing` | Partial — token verification not ported (see below) |
| `POST /checkout-service/checkout` | `checkout_route` | Yes |
| `GET /checkout-service/product/{id}` | `get_product` -> row or 404 `not-found` | Yes |
| `GET /checkout-service/order/{id}` | `get_order` -> row or 404 `not-found` | Yes |
| spec: `valid product` -> `checkout` -> `completed`, `slo met`, `cache written`, `result product.stock > 0`, `rows Order 1` | `test_checkout_valid_product` | Yes |
| forcing input: no `Authorization` header | `test_checkout_without_authorization_is_401` | Yes |
| forcing input: empty repository | `test_checkout_empty_repository_is_404` | Yes |
| forcing input: `stock 0` (guard false) | `test_checkout_out_of_stock_guard_skips_create` | Yes |
| forcing input: `stock "3"` (Integer as string) | `test_checkout_invalid_stock_is_400` | Yes |
| forcing input: hyphenless UUID | `test_checkout_hyphenless_uuid_is_400` | Yes |
| forcing input: `price {"a": 1}` (Money unchecked) | `test_checkout_money_accepts_any_non_null` | Yes |
| derived GETs, 200 row / 401 / 404 | `test_get_product_by_id`, `test_get_order_by_id` | Yes |

### Known non-equivalence

- Spec keys `steps 4`, `effects 4` and `effects complete` have no FastAPI
  counterpart; the tests assert status and store state instead.
- M3a token verification (signature, issuer, audience, expiry) is not ported;
  the port checks header presence only.
- `capability jwt`, `capability postgres`, `capability redis` and
  `event OrderPlaced on Order create` are descriptive; no counterpart.
- examples/checkout.lnpl is measured live, not frozen: drift turns the REPORT
  agreement test red.
- The deadline is untested on both sides (no clock seam).
- The retry attempt count is unobservable on the in-memory store.
- An Integer beyond the signed 64-bit range (`stock = 2**70`) passes
  `validate` on both sides; LNPL then stops at the guard comparison with a
  64-bit range runtime error (rc 3), while the port answers 200.

## consume

LNPL: benchmarks/token/scenarios/consume.lnpl. FastAPI:
equiv/consume_fastapi.py. Tests: tests/test_consume_equiv_spec.py.

| LNPL (scenarios/consume.lnpl) | FastAPI (equiv/consume_fastapi.py) | Equivalent? |
|---|---|---|
| `entity Order` fields `id UUID`, `status Text` | `ORDER_FIELDS` + `Store.orders` rows | Yes — field-for-field |
| `entity Shipment` fields `id UUID`, `status Text` | `SHIPMENT_FIELDS` + `Store.shipments` rows | Yes |
| `event OrderPlaced` / `consume by FulfillOrder` | `POST /-/events/order-placed` -> `check_envelope`, then `fulfill_order` on `data` | Yes |
| `validate order` | `validate(payload, ORDER_FIELDS)` -> 400 `validation-failed` | Yes |
| `find order` + `policy retry 3` | `with_retry(lambda: get_row(store.orders, ...))`, 1 + `RETRY` attempts on `not-found` | Yes — attempt count unobservable |
| `create shipment` | `create_shipment`, row seeded from the same-named payload fields, 409 `conflict` on an existing id | Yes |
| `POST /fulfillment-service/fulfill-order` | `fulfill_order_route` | Yes |
| `GET /fulfillment-service/order/{id}` | `get_order` -> row or 404 `not-found` | Yes |
| `GET /fulfillment-service/shipment/{id}` | `get_shipment` -> row or 404 `not-found` | Yes |
| `POST /-/events/order-placed` | `order_placed` | Yes |
| E1 required attribute missing or empty -> 400 `cloudevents-invalid` | `check_envelope` over `ENVELOPE_REQUIRED` | Yes |
| E2 `data_base64` present -> 400 `cloudevents-invalid` | `check_envelope` | Yes |
| E3 `data` not an object -> 400 `cloudevents-invalid` | `check_envelope` | Yes |
| E9 `id` over 255 UTF-8 bytes -> 400 `cloudevents-id-too-long` | `MAX_EVENT_ID_BYTES = 255` in `check_envelope` | Yes |
| E5 workflow completed -> 200 | `fulfill_order` returns `{"status": "completed"}` | Yes |
| E7 permanent failure (validation, not-found, conflict) -> 422 `event-rejected` | any `WorkflowFailed` from `fulfill_order` re-raised as 422 `event-rejected` | Yes |
| spec 1: `valid order` -> `fulfillOrder` -> `completed`, `rows Shipment 1` | `test_event_valid_order`, `test_workflow_route_valid_order` | Yes |
| spec 2: `empty repository` -> `fulfillOrder` -> `failed`, `rows Shipment 0` | `test_event_empty_repository_rejected` | Yes |
| forcing input: order without `status` (event, workflow route) | `test_event_invalid_order_rejected`, `test_workflow_route_invalid_order_is_400` | Yes |
| forcing input: E1, E2, E3, E9 envelopes | `test_envelope_missing_source_is_invalid`, `test_envelope_data_base64_is_invalid`, `test_envelope_data_not_object_is_invalid`, `test_envelope_id_256_bytes_too_long` | Yes |
| boundary: `id` of exactly 255 bytes | `test_envelope_id_255_bytes_accepted` | Yes |
| derived GETs, 200 row / 404 | `test_get_order_by_id`, `test_get_shipment_by_id` | Yes |

### Known non-equivalence

- E4/E8 (idempotency in progress, replay) need the idempotency claim store,
  which neither the reference `FakeRepository` nor the port has.
- E6 (503 `event-retry-later`) is unreachable: no driver error or deadline
  can occur on either side.
- No dedupe by CloudEvents `id` on either side; a production consumer adds it
  on both sides (handlers must be idempotent under redelivery).
- Redelivery of one `id` is untested: LNPL replays on a claiming backend,
  while the port re-runs and the shipment create conflicts (422).
- The envelope `type` is not cross-checked against `OrderPlaced` on either
  side.
- `effects complete` is not portable.
- The retry attempt count is unobservable on the in-memory store.

## schedule

LNPL: benchmarks/token/scenarios/schedule.lnpl. FastAPI:
equiv/schedule_fastapi.py. Tests: tests/test_schedule_equiv_spec.py.

| LNPL (scenarios/schedule.lnpl) | FastAPI (equiv/schedule_fastapi.py) | Equivalent? |
|---|---|---|
| `entity Report` fields `id UUID`, `total Integer` | `Store.reports` rows | Yes — field-for-field |
| `event DailyRollup on schedule daily at 00:00 UTC` | `SCHEDULE = "daily at 00:00 UTC"` constant | Yes — a declaration on both sides; neither runs a scheduler |
| schedule trigger `POST /-/schedules/daily-rollup` | `daily_rollup` -> `build_report` | Yes |
| `find report` + `policy retry 3` | `with_retry(lambda: get_row(store.reports, ...))`, 1 + `RETRY` attempts on `not-found` | Yes — attempt count unobservable |
| `list report where total > 0` | `[r for r in store.reports.values() if r["total"] > 0]` | Yes |
| `set report.total to count report` | `report["total"] = len(rows)` | Yes |
| `update report` | `store.reports[report["id"]] = report` | Yes |
| `POST /rollup-service/build-report` | `build_report_route` | Yes |
| `GET /rollup-service/report/{id}` | `get_report` -> row or 404 `not-found` | Yes |
| spec 1: `valid report` -> `buildReport` -> `completed`, `rows Report 1` | `test_trigger_valid_report` | Yes |
| spec 2: `empty repository` -> `buildReport` -> `failed`, `rows Report 0` | `test_trigger_empty_repository_is_404` | Yes |
| boundary: a row with `total 0` is not counted | `test_count_ignores_zero_totals` (LNPL interpreter on the same seed: total 1, other row unchanged) | Yes |
| forcing input: both POST routes | `test_workflow_route_matches_trigger` | Yes |
| derived GET, 200 row / 404 | `test_get_report_by_id` | Yes |

### Known non-equivalence

- No scheduler on either side: `on schedule` is a declaration only.
- `lnpl schedules` crontab/systemd generation and the `x-lnpl-schedules`
  OpenAPI metadata are not ported.
- `update` of a 0-row key (RFC-0064 `not-found`) is unreachable after a
  successful `find` on the in-memory store.
- `total = 2**70` completes on both sides on the reference store (LNPL total
  1, rc 0): `FakeRepository` evaluates `where total > 0` in
  `repo_policy.apply_predicate`, which has no 64-bit range check. Other
  backends were not measured.
- The retry attempt count is unobservable on the in-memory store.
- `effects complete` is not portable.

## parallel

LNPL: benchmarks/token/scenarios/parallel.lnpl. FastAPI:
equiv/parallel_fastapi.py. Tests: tests/test_parallel_equiv_spec.py.

| LNPL (scenarios/parallel.lnpl) | FastAPI (equiv/parallel_fastapi.py) | Equivalent? |
|---|---|---|
| `entity Product` fields `id UUID`, `stock Integer` | `Store.products` rows | Yes — field-for-field |
| `entity Order` fields `id UUID`, `quantity Integer` | `ORDER_FIELDS` + `Store.orders` rows | Yes |
| `policy parallel 2` | `ThreadPoolExecutor(max_workers=PARALLEL)`, `PARALLEL = 2` | Yes |
| `parallel` ... `merge` | submit both steps, `wait(..., return_when=FIRST_EXCEPTION)`, cancel pending, re-raise the first failure in submit order | Yes |
| `find product` | `get_row(store.products, ...)` -> 404 `not-found` | Yes |
| `cache product` + `performance cache 5m` | `cache_product`, key `product:<id>`, TTL `CACHE_TTL_SECONDS` (300) | Yes |
| `create order` | `create_order` -> 409 `conflict` on an existing id | Yes |
| `POST /fan-out-service/restock` | `restock_route` | Yes |
| `GET /fan-out-service/product/{id}` | `get_product` -> row or 404 `not-found` | Yes |
| `GET /fan-out-service/order/{id}` | `get_order` -> row or 404 `not-found` | Yes |
| spec 1: `valid product` -> `restock` -> `completed`, `rows Order 1`, `cache written` | `test_restock_valid_product` | Yes |
| spec 2: `empty repository` -> `restock` -> `failed`, `rows Order 0` | `test_restock_empty_repository_is_404` | Yes |
| forcing input: an order with the same id already exists | `test_restock_existing_order_conflicts` (LNPL interpreter on the same seed: `failed`/`conflict`, 1 order, cache written) | Yes |
| derived GETs, 200 row / 404 | `test_get_product_by_id`, `test_get_order_by_id` | Yes |

### Known non-equivalence

- LNPL stops the next retry of a sibling after a failure; no retry is
  declared here, so this is unobservable.
- Neither side can cancel a sibling that is already running: with 2 workers
  both steps start at once.
- `effects complete` is not portable.

## cached

LNPL: benchmarks/token/scenarios/cached.lnpl. FastAPI:
equiv/cached_fastapi.py. Tests: tests/test_cached_equiv_spec.py.

| LNPL (scenarios/cached.lnpl) | FastAPI (equiv/cached_fastapi.py) | Equivalent? |
|---|---|---|
| `entity Product` fields `id UUID`, `stock Integer` | `PRODUCT_FIELDS` + `Store.products` rows | Yes — field-for-field |
| `validate input` | `validate(payload, PRODUCT_FIELDS)` -> 400 `validation-failed` | Yes |
| `find product cached` — hit | unexpired `store.cache["product:<id>"]` -> 200 without reading the store | Yes |
| `find product cached` — miss | `get_row(store.products, ...)` -> 404 `not-found` | Yes |
| `find product cached` — fill | miss writes `{"value": row, "expires_at": now + CACHE_TTL_SECONDS}` | Yes |
| `performance cache 5m` | `CACHE_TTL_SECONDS = 5 * 60` | Yes |
| `POST /catalog-service/get-product` | `get_product_route` | Yes |
| `GET /catalog-service/product/{id}` | `get_product_by_id` -> row or 404 `not-found` | Yes |
| spec 1: `valid product` -> `getProduct` -> `completed`, `cache written` | `test_get_product_valid_product` | Yes |
| spec 2: `empty repository` -> `getProduct` -> `failed`, `rows Product 0` | `test_get_product_empty_repository_is_404` | Yes |
| forcing input: cold read, store row deleted, warm read | `test_warm_cache_hit_skips_store` (LNPL interpreter on the same sequence: both runs `completed`) | Yes |
| forcing input: `stock` missing | `test_get_product_missing_stock_is_400` | Yes |
| forcing input: hyphenless UUID | `test_get_product_hyphenless_uuid_is_400` | Yes |
| derived GET, 200 row / 404 | `test_get_product_by_id` | Yes |

### Known non-equivalence

- TTL expiry is untested on both sides (no clock seam).
- LNPL treats a cache outage as a miss; a dict cannot fail, so this is
  unreachable in the port.
- The derived GET reads the store directly on both sides, not the cache.
- LNPL keys the `find product cached` entry `entity.product#<id>`; the port
  keys it `product:<id>` (Conventions). Unobservable over HTTP.
- `effects complete` is not portable.
