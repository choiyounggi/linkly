<!-- 생성물 — 손으로 고치지 마라. 정본은 impl/lnpl/의 모듈 상수이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# 이름과 참조 — 선언명·노드 id·스텝 객체

> lnpl 0.6.0 기준.

선언에 붙인 이름은 곧 **노드 id**가 되고, 스텝이 엔티티를 가리킬 때 쓰는 철자도 그 규칙에서 나온다. 둘 다 기계적이고, 둘 다 틀리면 조용히 실패하지 않고 **컴파일이 거부한다** — 다만 에러가 이유를 말해주지 않아서 규칙을 모르면 빠져나올 수 없다(이슈 #50).

## 선언명 → 노드 id

| kind | 접두사 | 예 |
|------|--------|-----|
| `Entity` | `entity` | `DailyReport` → `entity.daily.report` |
| `Service` | `svc` | `LoginService` → `svc.login` |
| `Workflow` | `wf` | `GetReport` → `wf.get.report` |
| `Event` | `event` | `UserCreated` → `event.user.created` |
| `Capability` | `cap` | `Postgres` → `cap.postgres` |
| `Refinement` | `refine` | `ClickCount` → `refine.click.count` |
| `Policy` | `policy` | `Retry` → `policy.retry` |
| `Security` | `security` | `Jwt` → `security.jwt` |
| `Performance` | `perf` | `Response` → `perf.response` |

PascalCase는 낱말마다 점으로 끊긴다. 대문자 연속은 한 낱말이고(`APIKey` → `api.key`), 숫자는 앞 낱말에 붙는다.

## 후행 kind 낱말은 지워진다

이름의 **마지막** 낱말이 kind와 같으면 중복이므로 제거된다. 해당 kind는 `Entity` `Service` `Workflow` `Event` `Capability`다.

- `ProbeWorkflow` → `wf.probe` (후행 `Workflow`가 지워진다)
- `WorkflowProbe` → `wf.workflow.probe` (선행은 지워지지 않는다)

## 스텝 객체로 엔티티를 가리키는 법

스텝의 두 번째 낱말(객체)은 **선언명이 아니라 그 소문자 연결형**이다 — PascalCase의 낱말 경계를 지우고 전부 소문자로 내린 형태다. `entity DailyReport`를 가리키려면 `dailyreport`라고 쓴다.

| 스텝에 쓴 것 | 결과 |
|--------------|------|
| `validate dailyreport` | **해석된다** — 소문자 연결형 |
| `validate dailyReport` | 거부 — camelCase는 이 규칙이 아니다 |
| `validate DailyReport` | 거부 (엔티티를 둘 이상 선언했을 때) — 선언과 같은 표기여도 안 된다; 하나뿐이면 대신 `unknown-entity` 경고로 컴파일된다 (아래 참조) |
| `validate dailyreports` | 거부 — 복수형을 단수로 되돌리지 않는다 |
| `validate order` | 해석된다 — `entity Order`의 소문자 연결형 |

두 가지 예외가 있다:

- 모듈이 엔티티를 **정확히 하나** 선언하면 객체를 생략할 수 있다.
- 객체가 어떤 엔티티의 **필드명**과 같으면 그 엔티티로 해석된다.

## 선언되지 않은 명사를 쓰면 — `unknown-entity`

스텝 객체가 위 표의 어느 형태로도 매칭되지 않을 때, 모듈이 엔티티를 **정확히 하나** 선언했으면 컴파일은 계속된다 — `_resolve_entity`가 그 하나를 그대로 쓴다(런타임 동작은 바뀌지 않는다, 이슈 #91 §4). 대신 `unknown-verb`(#36→#82)와 대칭인 `unknown-entity` **warning** 진단이 하나 실린다:

```
warning: unknown-entity [line 8] find user — 'user' names no declared entity; declared: customer — did you mean 'customer'?
```

형식은 `unknown-verb`가 확정한 구조 그대로다 — 구조화 `line`, did-you-mean 제안(RFC-0026). 엔티티가 **하나뿐이면** 제안은 늘 그 하나다. `--strict=warning`으로 게이트할 수 있다(RFC-0021). 엔티티를 둘 이상 선언한 모듈에서 객체가 매칭에 실패하면 이 진단이 아니라 바로 아래의 모호성 에러가 난다 — 그 경로는 이미 조용하지 않으므로 이슈 #91의 범위가 아니다. `<명사>.<필드>` Reference의 명사부(가드·`set` 대상)는 이 진단의 범위가 아니다 — 선언되지 않은 바인딩을 쓰면 이미 컴파일 에러이므로(#45), 무진단으로 통과하는 구멍이 없다.

## 이 에러가 나면

```
`validate DailyReport` does not say which entity it means, and this module declares 2 (...).
Name the entity as the step's object.
```

지시를 그대로 따라 **정확한 선언명**을 써도 같은 에러가 반복된다. 이 에러가 말하는 "the entity as the step's object"는 이 언어에서 `dailyreport`를 뜻한다 — 위 표의 소문자 연결형이다. 다단어 엔티티를 쓸 거면 그 연결형이 읽히는지 먼저 확인하라.

## `--workflow`가 요구하는 것

CLI의 `--workflow`는 **선언명이 아니라 노드 id**를 받는다. `workflow GetReport`를 지정하려면 `--workflow wf.get.report`라고 쓴다. 잘못된 id를 주면 유효한 id 전부가 에러에 나열된다.
