# evidence/07 — R10 change request (gift_wrap)

Snapshot before change: `cp -R src .claude/tmp/src-pre-r10` (D17).

## Rounds

- round 1: added `OrderLine.giftWrap Integer` (client input, 0/1 — no
  Boolean-as-guard-operand restriction risk, consistent with this case's
  Integer-flag convention throughout) and `giftWrapRejected Integer derived`
  (observability only), plus a `when input.giftWrap == 1 / pipeline
  giftWrapCheck` block right after `line.lineTotalCents` is first computed —
  compiled clean.
- round 2: ran the no-gift-wrap and with-gift-wrap cases. **Self-inflicted
  bug, not a platform one:** the `pipeline giftWrapCheck` block, having no
  following control keyword, silently absorbed **every remaining step of
  the workflow** (`create stockreservation`, all of `discount`/`tax`/`total`,
  `respond`) into its own guard scope (grammar.md's "암묵 종결" rule — a
  `pipeline` extends to the *next control keyword*, not "a few lines"). The
  no-gift-wrap regression run silently produced **no response at all**
  (guard-skip swallowed the whole rest of the order). **F-15** (minor, `llm`
  axis — an easy, silent authoring mistake with no diagnostic pointing at
  it; `guard-skipped-steps` does list the swallowed step names, but only if
  the author reads that warning under `--strict=warning` and recognizes the
  list is too long).
- round 3: fixed by opening a second, unguarded `pipeline reserve` right
  after `giftWrapCheck` — an unguarded pipeline is a no-op scope boundary
  that only serves to *close* the guarded one early. Re-ran both cases:
  no-gift-wrap regression now matches A1 exactly (`subtotalCents 3998`,
  unchanged); gift-wrap case gives `subtotalCents 4198` (3998 + 200, one
  physical line ×1 gift-wrapped — matches the P1+gift_wrap scenario
  s1.md's R10 names).
- round 4: digital + gift_wrap (`P2`, `kind=1`): `list catalogproduct where
  id == input.product and kind == 0` (a second, narrower re-list of the
  same entity, inside the guarded block) matches zero rows, and the
  following `max product.priceCents` fails the run — the whole order is
  rejected (`policy rollback` discards everything), not just the surcharge.
  Confirms "digital 상품엔 불가(거부)" at the data level (same 500-not-4xx
  caveat as every other rejection path in this case, F-4).

Rounds this task: 4.

## Spec impact

No spec blocks exist yet for this case (R9 — 시간 상한, FINDINGS.md 커버리지
표). There is therefore nothing to re-run/break here; this is recorded as a
**gap**, not a "0 broken" pass — a real spec suite would very likely need a
new scenario for R10 and would need `A1`-equivalent scenarios re-asserted
unchanged (exactly the round-2 regression this task caught by hand instead).

## Diff size

```
$ diff -ru .claude/tmp/src-pre-r10 qa/probe-v0.8/cases/s1-order-platform/src | grep -c '^[+-]'
12
```

12 changed lines (`orders/orders.lnpl` only: 1 new field, 1 new derived
field, 6-line guarded block, 1-line pipeline-close fix, respond line
unchanged) across 4 rounds — one of which (round 2→3) was pure self-inflicted
debugging, not the requirement itself.
