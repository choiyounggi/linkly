<!-- 생성물 — 손으로 고치지 마라. 정본은 impl/lnpl/의 모듈 상수이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# 타입과 Refinement

> lnpl 0.7.0 기준.

## 의미 타입

필드 타입은 아래 집합에서 고른다.

| 타입 | 예시 값 |
|------|---------|
| `UUID` | `3f2504e0-4f89-41d3-9a0c-0305e82c3301` |
| `Email` | `user@example.com` |
| `Password` | `s3cret-value` |
| `DateTime` | `2026-07-31T09:00:00Z` |
| `Phone` | `+14155550100` |
| `Money` | `{'amount': '0', 'currency': 'USD'}` |
| `Currency` | `USD` |
| `GeoLocation` | `{'lat': 0, 'lng': 0}` |
| `Address` | `{'line1': '1 Main St', 'city': 'Springfield', 'country': 'US'}` |
| `Image` | `{'uri': 'https://example.com/i.png', 'mediaType': 'image/png'}` |
| `File` | `{'uri': 'https://example.com/f.pdf', 'mediaType': 'application/pdf'}` |
| `Json` | `{}` |
| `Html` | `<p>x</p>` |
| `Markdown` | `# x` |
| `Text` | `text` |
| `Integer` | `1` |
| `Decimal` | `0` |
| `Boolean` | `True` |

## Refinement 프리셋

선언 없이 바로 쓰면 emit-on-use로 문서에 실린다.

| 프리셋 | base | facet |
|--------|------|-------|
| `URL` | `Text` | maxLength=2048, pattern=^https?://[^\s]+$ |
| `Slug` | `Text` | maxLength=64, pattern=^[a-z0-9-]{1,64}$ |
| `PositiveInteger` | `Integer` | min=1 |

## 직접 선언하는 refinement

`refine <PascalName> of <base>` 뒤에 facet을 둔다. base별로 허용되는 facet이 다르다.

| base | 허용 facet |
|------|------------|
| `UUID` | `enum` `maxLength` `minLength` `pattern` |
| `Email` | `enum` `maxLength` `minLength` `pattern` |
| `Password` | `enum` `maxLength` `minLength` `pattern` |
| `DateTime` | `enum` `maxLength` `minLength` `pattern` |
| `Phone` | `enum` `maxLength` `minLength` `pattern` |
| `Currency` | `enum` `maxLength` `minLength` `pattern` |
| `Html` | `enum` `maxLength` `minLength` `pattern` |
| `Markdown` | `enum` `maxLength` `minLength` `pattern` |
| `Text` | `enum` `maxLength` `minLength` `pattern` |
| `Integer` | `enum` `max` `min` |
| `Decimal` | `enum` `max` `min` |
| `Boolean` | — |
| `Money` | — |
| `GeoLocation` | — |
| `Address` | — |
| `Image` | — |
| `File` | — |
| `Json` | — |
