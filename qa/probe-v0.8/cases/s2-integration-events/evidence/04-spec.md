# 04-spec — R2/R3/R4/R7 spec 표현

## 시도 1 — 엔티티 저장값(fx_status)을 직접 단언 (D15 요구대로)

```
spec ... expect result o.fxStatus == live
```
→ **컴파일 거부**: "unsupported result expectation 'result o.fxStatus == live':
Cannot compare non-numeric o.fxStatus='live' in condition ...". `result <ref>
<op> <value>`도 `set`/가드와 **같은 비수치 비교 거부 평가기**를 공유한다 —
Text/refine(enum) 필드는 `result`로 값 단언이 **전혀 안 됨**(존재 여부
`exists`/`missing`만 가능, 값 비교 불가). task 01/03에서 이미 세 번(산술
`set`, 가드 조건, 이제 spec `result`) 교차 확인된 같은 제약의 네 번째
발현 — 이 언어의 비교/산술 평가기는 전체 표면에서 Integer/DateTime만
받는다.

## 시도 2 — 우회: NetworkCall 결과 바인딩(fxResult.status, Integer)으로 대체

```
$ lnpl spec src/orders-lite/orders.lnpl --run --strict=warning
```
```
PASS CreateOrder spec 1 — completed
PASS CreateOrder spec 1 — effects complete
PASS CreateOrder spec 1 — result fxResult.status == 200
PASS CreateOrder spec 2 — completed
PASS CreateOrder spec 2 — effects complete
PASS CreateOrder spec 2 — result fxResult.status != 200
PASS CreateOrder spec 3 — completed
PASS CreateOrder spec 3 — effects complete
FAIL CreateOrder spec 3 — result fxResult.status != 200 (-> False)
spec: 8 passed, 1 failed
```

spec 3(`given call Fx returns 200 body.rate abc`, R4)은 **의도적으로 레드**
— fxResult.status는 200이므로(스텁이 200을 낸다, 본문만 깨짐)
`!= 200` 단언이 실패한다. 이건 버그가 아니라 **spec이 R4의 실제 결함을
정확히 잡아낸 것**: 이 플랫폼은 본문 검증 없이 상태코드만으로 live/fallback을
가르므로, "본문이 깨졌으면 fallback"이라는 요구를 충족하지 못한다는 사실이
spec 레드로 기계 검증됐다(사람이 실행 출력을 읽고 판단한 게 아니라).

## 표

| 분기 | spec 표현 가능(yes/no) | 사용한 네트워크 응답 스텁 형태 | 단언한 판별값 | 결과 |
|------|------------------------|----------------------------------|----------------|------|
| R2(live, fx 200) | yes | `given call Fx returns 200 body.rate 1350.5` | `fxResult.status == 200`(엔티티 저장값 `o.fxStatus`는 Text라 `result`로 단언 불가 — 우회) | 부분(간접 판별값) |
| R3(재시도 2회 후 200) | no | 없음 — `given call <target> returns <status>`는 단일 상태 하나만 스텁한다(문서화된 형태에 시퀀스가 없음, spec.md 전문 재확인). task 03에서 이미 재시도 자체가 런타임에서 발동하지 않는 것도 확인됨(불가) | — | 불가 |
| R4(fx 200, 본문 깨짐) | yes(신호는 fxResult.status뿐) | `given call Fx returns 200 body.rate abc` | `fxResult.status != 200`(의도적으로 레드 — 실제 판별값 `o.fxStatus`는 여전히 단언 불가) | **레드로 결함 포착**(부분 — 판별값은 대리 신호) |
| R7(멱등 소비, 관계 relay 2회) | no | `given`/`when`/`expect`는 한 번의 실행만 모델링한다 — "같은 CloudEvents id로 두 번 호출"이라는 시나리오 자체를 표현할 문법이 spec.md 어휘(§`given`이 알아듣는 형식) 전체에 없다(재확인: `stored`/`call ... returns`/`no`/`empty repository` 중 반복 호출을 표현하는 것 없음) | — | 불가 |

## 요약

- R2/R4는 **상태코드 프록시로만** 부분 표현 가능 — 요구사항이 실제로
  요구하는 "저장된 fx_status 값"은 spec의 `result` 어휘로 절대 단언 못 함
  (Text 비교 불가라는 플랫폼 전역 제약 때문).
- R3/R7은 spec 어휘 자체에 필요한 원시 기능(다중 응답 시퀀스, 반복 호출)이
  없어 **불가**.
- spec이 실제로 결함을 잡아낸 사례 1건(R4 레드) — METRICS의 "spec이 잡은
  것" 카운트에 반영.
