# linkhub.lnpl ↔ linkhub_fastapi.py — equivalence mapping

Defines what "behaviorally equivalent" means for the token benchmark
(issue #142). This is the source of truth for the mapping; REPORT.md quotes
it rather than re-deriving it. Both implementations run against an in-memory
fake store — `capability postgres`/`capability redis` are descriptive in the
`.lnpl` source (see examples/linkhub.lnpl header) and are not exercised by
either side, so no real database/cache is required to compare them.

| LNPL (examples/linkhub.lnpl) | FastAPI (equiv/linkhub_fastapi.py) | Equivalent? |
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

## Known non-equivalence (documented, not hidden)

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
