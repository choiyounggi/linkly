<!-- 생성물 — 손으로 고치지 마라. 정본은 impl/lnpl/의 모듈 상수이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# 동사 어휘 (VERB_LEXICON)

> lnpl 0.3.0 기준.

워크플로 스텝의 **첫 낱말**이 동사다. 아래 표에 없는 동사는 에러가 아니라 **효과 없는 no-op**으로 실행된다 — 파일은 컴파일되고, 런타임은 아무것도 하지 않는다(issue #36). 진단 코드 `unknown-verb`가 그때 발생한다.

| 동사 | 파생되는 Effect | 속성 |
|------|-----------------|------|
| `set` | `Assignment` | — |
| `validate` | `Validation` | — |
| `authenticate` | `RepositoryCall` | operation=read |
| `load` | `RepositoryCall` | operation=read |
| `find` | `RepositoryCall` | operation=read |
| `read` | `RepositoryCall` | operation=read |
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

`return`, `log`, `send`, `notify`, `verify` 같은 낱말은 이 표에 **없다**. 자연스러워 보여도 아무 효과가 없다.
