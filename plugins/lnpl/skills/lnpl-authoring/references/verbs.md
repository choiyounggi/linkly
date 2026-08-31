<!-- 생성물 — 손으로 고치지 마라. 정본은 impl/lnpl/의 모듈 상수이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# 동사 어휘 (VERB_LEXICON)

> lnpl 0.7.0 기준.

워크플로 스텝의 **첫 낱말**이 동사다. 아래 표에 없는 동사는 에러가 아니라 **효과 없는 no-op**으로 실행된다 — 파일은 컴파일되고, 런타임은 아무것도 하지 않는다(issue #36). 진단 코드 `unknown-verb`가 그때 발생한다.

| 동사 | 파생되는 Effect | 속성 |
|------|-----------------|------|
| `set` | `Assignment` | — |
| `validate` | `Validation` | — |
| `authenticate` | `RepositoryCall` | operation=read |
| `load` | `RepositoryCall` | operation=read |
| `find` | `RepositoryCall` | operation=read |
| `read` | `RepositoryCall` | operation=read |
| `list` | `RepositoryCall` | operation=query |
| `create` | `RepositoryCall` | operation=create |
| `insert` | `RepositoryCall` | operation=create |
| `update` | `RepositoryCall` | operation=update |
| `delete` | `RepositoryCall` | operation=delete |
| `cache` | `CacheAccess` | operation=set |
| `invalidate` | `CacheAccess` | operation=invalidate |
| `call` | `NetworkCall` | — |
| `request` | `NetworkCall` | — |
| `emit` | `EventEmit` | — |
| `publish` | `EventEmit` | — |
| `authorize` | `Authorization` | — |
| `format` | `Assignment` | — |
| `respond` | `Response` | — |
| `note` | `Annotation` | — |

`return`, `log`, `send`, `notify`, `verify` 같은 낱말은 이 표에 **없다**. 자연스러워 보여도 아무 효과가 없다.

`create`가 언제 충돌하고 그 충돌을 spec으로 어디까지 계약할 수 있는지는 [spec.md](spec.md)의 "저장소 시드와 `create` 충돌"에 있다. `set`의 대상이 될 수 있는 바인딩을 어떤 동사가 만드는지는 [grammar.md](grammar.md)의 "할당(`set`)의 대상"에 있다.
