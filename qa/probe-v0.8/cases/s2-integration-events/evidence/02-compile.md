# 02-compile — orders-lite 최종 컴파일

## 명령

```
$ git rev-parse HEAD
264e3442d653e5534d827687ebac5ede956e801a
$ .venv/bin/lnpl compile qa/probe-v0.8/cases/s2-integration-events/src/orders-lite/orders.lnpl --strict=warning
rc=0
```

### stdout (Semantic IR, 288줄 — 요약: 노드 kind 카운트만 발췌)

```
$ grep -o '"kind": "[A-Za-z]*"' .claude/tmp/compile-stdout.txt | sort | uniq -c
```
(전문은 `src/orders-lite/orders.lnpl`이 소스이므로 별도 보관 안 함 — IR은
재생성 가능. `lnpl compile ... -o`로 언제든 재산출)

### stderr

```
(empty — 진단 0건, --strict=warning과 --strict(info) 둘 다 rc=0, stderr 빈 문자열)
```

## 소스 (최종본, round 5)

`src/orders-lite/orders.lnpl` 전문은 evidence/01-authoring.md의 round 5가
가리키는 상태 그대로 — Decimal→Integer 우회 적용됨.

## 회귀 확인

`--strict`(=info, 가장 엄격) 로도 rc=0 — `declared-not-enforced` 등 info급
진단조차 없다. `policy timeout 1s` 선언 자체는 §Reference-level 상
enforced이므로 `declared-not-enforced`가 뜨지 않는 것이 맞다.
