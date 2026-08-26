# Graph Report - /Users/choeyeong-gi/Desktop/workspace/linkly/impl  (2026-08-24)

## Corpus Check
- 104 files · ~174,684 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 4705 nodes · 14123 edges · 42 communities detected
- Extraction: 53% EXTRACTED · 47% INFERRED · 0% AMBIGUOUS · INFERRED: 6615 edges (avg confidence: 0.63)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Runtime & Drivers|Runtime & Drivers]]
- [[_COMMUNITY_Conditions & Time Semantics|Conditions & Time Semantics]]
- [[_COMMUNITY_CLI & Serve Backend|CLI & Serve Backend]]
- [[_COMMUNITY_Agent Protocol|Agent Protocol]]
- [[_COMMUNITY_Mode Equivalence & Repo State|Mode Equivalence & Repo State]]
- [[_COMMUNITY_CLI Diagnostics & Plugins|CLI Diagnostics & Plugins]]
- [[_COMMUNITY_Parser & Syntax|Parser & Syntax]]
- [[_COMMUNITY_IR Lowering & Network Binding|IR Lowering & Network Binding]]
- [[_COMMUNITY_MLIR Dialect & Backend|MLIR Dialect & Backend]]
- [[_COMMUNITY_OpenAPI & Types|OpenAPI & Types]]
- [[_COMMUNITY_Lowering Tests|Lowering Tests]]
- [[_COMMUNITY_Refinement & Golden Fixtures|Refinement & Golden Fixtures]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]

## God Nodes (most connected - your core abstractions)
1. `Interpreter` - 498 edges
2. `RunError` - 271 edges
3. `ConditionError` - 244 edges
4. `parse()` - 238 edges
5. `LowerError` - 226 edges
6. `ParseError` - 193 edges
7. `lower()` - 171 edges
8. `DriverError` - 158 edges
9. `Diagnostics` - 147 edges
10. `Server` - 142 edges

## Surprising Connections (you probably didn't know these)
- `Lowering rules: R2 (id derivation) and R1 (closed verb lexicon).` --uses--> `LowerError`  [INFERRED]
  /Users/choeyeong-gi/Desktop/workspace/linkly/impl/tests/test_lower.py → /Users/choeyeong-gi/Desktop/workspace/linkly/impl/lnpl/lower.py
- `R2 — one uniform rule, including the redundant-kind-word strip.` --uses--> `LowerError`  [INFERRED]
  /Users/choeyeong-gi/Desktop/workspace/linkly/impl/tests/test_lower.py → /Users/choeyeong-gi/Desktop/workspace/linkly/impl/lnpl/lower.py
- `R1 — a step's verb selects an Effect by lookup, never by inference.` --uses--> `LowerError`  [INFERRED]
  /Users/choeyeong-gi/Desktop/workspace/linkly/impl/tests/test_lower.py → /Users/choeyeong-gi/Desktop/workspace/linkly/impl/lnpl/lower.py
- `Guards and blocks: one Guard kind with a mode, not three kinds.` --uses--> `LowerError`  [INFERRED]
  /Users/choeyeong-gi/Desktop/workspace/linkly/impl/tests/test_lower.py → /Users/choeyeong-gi/Desktop/workspace/linkly/impl/lnpl/lower.py
- `A module may declare several entities; the step object selects one.` --uses--> `LowerError`  [INFERRED]
  /Users/choeyeong-gi/Desktop/workspace/linkly/impl/tests/test_lower.py → /Users/choeyeong-gi/Desktop/workspace/linkly/impl/lnpl/lower.py

## Communities

### Community 0 - "Runtime & Drivers"
Cohesion: 0.01
Nodes (222): Clock, DriverError, _encode(), open_repository(), A file-backed repository. One connection, owned by the creating thread.      Con, `affected` is the true row count here, where the Fake answers 1         uncondit, `--backend`'s value -> a RepositoryDriver, or None for the default.      `None`, A capability adapter could not carry out the operation.      `interp` wraps this (+214 more)

### Community 1 - "Conditions & Time Semantics"
Cohesion: 0.02
Nodes (328): BackendError, _backoff_ms(), _comparisons(), condition_field_names(), _constraints_of_kind(), _duration_ms(), _emit_condition(), _emit_operand() (+320 more)

### Community 2 - "CLI & Serve Backend"
Cohesion: 0.01
Nodes (220): cmd_agents(), cmd_build(), cmd_compile(), cmd_diff(), cmd_openapi(), cmd_run(), cmd_serve(), cmd_spec() (+212 more)

### Community 3 - "Agent Protocol"
Cohesion: 0.03
Nodes (136): _AgentBase, Architect, Coder, PerformanceAnalyzer, Planner, Two agents doing the RFC-0006 Examples round trip (ROADMAP Phase 3).  The cycle, Approves or rejects — on its own criteria, not the caller's.      `ir.propose` b, Does this provenance string name something that actually exists? (+128 more)

### Community 4 - "Mode Equivalence & Repo State"
Cohesion: 0.01
Nodes (156): _lnpl_ops(), runtime_c(), _repo_rows(), _check_rows_are_reproducible(), _check_seed_agreement(), compare_observations(), _normalise_skips(), observe_mode_a() (+148 more)

### Community 5 - "CLI Diagnostics & Plugins"
Cohesion: 0.01
Nodes (116): AssertionError, validation_effect_steps(), `text`(그대로) 또는 `path`(읽어서). 정확히 하나여야 한다., _read_source(), apply_and_run(), main(), make_tree(), Mutation check — proves the suite can fail.  Each mutation removes one rule the (+108 more)

### Community 6 - "Parser & Syntax"
Cohesion: 0.02
Nodes (116): is_duration(), Line, LNPL lexer — line-oriented tokenizer.  RFC-0002 §Lexical / §Block structure:   -, Split source into significant Lines.      Blank lines and comment-only lines are, One significant source line, indentation stripped from `tokens`.      `indent` i, _strip_comment(), tokenize(), _append_workflow_item() (+108 more)

### Community 7 - "IR Lowering & Network Binding"
Cohesion: 0.02
Nodes (85): emit_mlir(), restore_skips(), step_plan(), resolve_reference(), _check_aggregate(), _check_dimensions(), _check_enum_member(), _check_event_refs() (+77 more)

### Community 8 - "MLIR Dialect & Backend"
Cohesion: 0.02
Nodes (83): build(), emit_lnpl_mlir(), _fields_path(), pinned_llvm_version(), run_binary(), tool(), toolchain_available(), verify_lnpl_module() (+75 more)

### Community 9 - "OpenAPI & Types"
Cohesion: 0.02
Nodes (50): _constraints(), _entity_schema(), generate(), _operation(), IR -> OpenAPI 3.1 (RFC-0004 Architecture Optimizer, auto-generation).  CHARTER l, Refuse a composition no instance can satisfy.      RFC-0001 A.6.2: a refinement, Semantic IR document -> an OpenAPI 3.1 dict., The declared schedule triggers, in node order, as OpenAPI metadata. (+42 more)

### Community 10 - "Lowering Tests"
Cohesion: 0.03
Nodes (33): by_id(), ir(), Lowering rules: R2 (id derivation) and R1 (closed verb lexicon)., What this pass emits must satisfy schemas/lir.schema.json (Wave 1, frozen)., RFC-0012 §G12.5: a qualified reference is resolved where the document is     in, R1 — a step's verb selects an Effect by lookup, never by inference., 이슈 #56 [2] / r3 N-2: 진단이 `set` 스텝을 "guard condition"이라 부르던 것.      가드 검사와 할당 검사가, 대상은 `input.`으로 고칠 수 없다 — 안내가 그리로 보내면 안 된다. (+25 more)

### Community 11 - "Refinement & Golden Fixtures"
Cohesion: 0.03
Nodes (45): check_semantic_type(), refinement_index(), sample_for_type(), sample_payload(), entities(), Default-fixture derivation (issue #23).  `run`/`diff` used to assume the golden, `sample_payload(entities)` with no index omits every refined field.          `re, shorten_doc() (+37 more)

### Community 12 - "Community 12"
Cohesion: 0.02
Nodes (55): ran_step_indices(), facets_for_base(), preset(), The refinement registry — facet vocabulary, base categories, built-in presets (R, The facet names A.6.3 allows on `base`; empty for boolean and composite.      Ra, The built-in preset `name` as {"base": ..., "facets": ...}, or None.      The re, HelperBoundaryTest, PathReferenceIntegrityTest (+47 more)

### Community 13 - "Community 13"
Cohesion: 0.03
Nodes (43): run_manifest(), build(), build(), payload_for(), Issue #46 [2][3]: `given <field> <value>` must produce a payload `run` runs.  QA, TestIntegerGivenCoercion, TestNonIntegerGivenIsUnchanged, TestStoredAcceptsTheDeclaredName (+35 more)

### Community 14 - "Community 14"
Cohesion: 0.03
Nodes (43): Diagnostic, format_lines(), Compiler and runtime diagnostics — the single channel (issues #36, #38).  Two sy, One thing the platform is not doing, and where.      `code` is what callers bran, Record one diagnostic and return it.          Keyword-only: `severity` used to s, Append every diagnostic from another accumulator or any iterable., Every diagnostic, in the order it was added (a copy)., Accept either a `Diagnostics` or a plain iterable of `Diagnostic`. (+35 more)

### Community 15 - "Community 15"
Cohesion: 0.03
Nodes (46): DiagnosticsHookTest, HookWiringTest, make_shim(), MissingCliTest, ModuleFallbackTest, outside_repo_dir(), outside_repo_root(), ProductionEnvironmentTest (+38 more)

### Community 16 - "Community 16"
Cohesion: 0.03
Nodes (46): AnchorMissing, diagnostic_severity_errors(), document_coverage_errors(), document_validity_errors(), first_table_rows(), matrix_completeness_errors(), parse_table(), `docs/ENFORCEMENT-MATRIX.md` may not drift away from the code (issue #38).  The (+38 more)

### Community 17 - "Community 17"
Cohesion: 0.03
Nodes (35): main(), CLI arg-wiring smoke tests (issue #27).  The `lnpl diff` crash fixed in PR #22 (, The typo is operator error whether or not the binary is executed., `--version`은 서브커맨드 없이도 통해야 한다 (`required=True`인데도).      lnpl-doctor가 설치된 CLI와 플, `--workflow` takes a node id, and a wrong one lists the valid ones.      Issue #, Guards against an implementation that always picks `workflows[0]`., t3 F-7 verbatim: the declaration name is not the node id., Drive `cli.main(argv)` with stdout/stderr muted; return its exit code. (+27 more)

### Community 18 - "Community 18"
Cohesion: 0.04
Nodes (32): Only the diagnostics carrying `code`, in order., BlockDidNotLower, lnpl_blocks(), README의 `.lnpl` 예제가 어휘 안에 머무는지 — 컴파일러 자신이 판정한다.  README는 LLM과 사람 모두의 첫 접촉면이고, 첫, 판정 함수가 위반을 실제로 잡는가 — 이게 없으면 위 초록은 증거가 아니다., ```lnpl 로 태그된 코드펜스의 본문들., 블록이 파싱은 되는데 lowering에서 거부됐다.      `lower()`가 raise하면 unittest는 ERROR와 원시 트레이스백을, `source`가 내는 `unknown-verb` 진단의 subject들 — 컴파일러가 판정한다. (+24 more)

### Community 19 - "Community 19"
Cohesion: 0.05
Nodes (34): Diagnostics -> plain dicts, for a caller that reads JSON not prose (#52).      N, to_records(), _error(), handle(), _lnpl(), _ok(), LNPL을 MCP 툴로 노출하는 stdio 서버.  왜 있는가: `lnpl compile`은 진단을 **stderr로 내보내고 종료 코드 0**, `spec` 블록을 추출해 가짜 백엔드 위에서 실행하고, 케이스별 결과를 돌려준다.      spec.py는 수정하지 않는다 — 공개 API(` (+26 more)

### Community 20 - "Community 20"
Cohesion: 0.05
Nodes (22): cmd_kb(), Knowledge Base access — RFC-0005 §Consumption Interface.  Three operations, exac, kb.route(task_description) -> [doc_id], ranked, possibly empty.          Decided, kb.load(doc_id) -> {frontmatter fields..., body}., Return a list of problems; empty means the KB satisfies RFC-0005., Load the routing index only — never a document body., _repo_root(), _split_frontmatter() (+14 more)

### Community 21 - "Community 21"
Cohesion: 0.07
Nodes (24): BaseHTTPRequestHandler, HttpNetworkDriver, NetworkDriver, open_network(), The `NetworkCall` effect's adapter contract (RFC-0027 §1, issue #64).      Refer, Call `target` once.          -> (status: int, body: dict). A response was receiv, Release resources. Safe to call more than once., `http.client` only — standard library, zero dependencies (RFC-0027     §1). `tar (+16 more)

### Community 22 - "Community 22"
Cohesion: 0.11
Nodes (6): compile_doc(), nodes_of(), TestIrSchemaGate, TestModeAEvaluation, TestRedRepro, TestStaticRejections

### Community 23 - "Community 23"
Cohesion: 0.08
Nodes (8): clauses(), FilenameAndNumberTest, good_body(), NumberingTest, `scripts/rfc_lint.py`의 검사 로직 — 합성 입력으로만 검증한다.  이 파일은 **레포의 RFC가 깨끗한지 묻지 않는다.** 린, SectionScanBoundaryTest, StatusTest, TemplateSectionTest

### Community 24 - "Community 24"
Cohesion: 0.1
Nodes (14): frontmatter(), KbSkillTest, parse_frontmatter(), P1 스킬 3종의 구조·정합 검사.  `lnpl-authoring`(P0)이 쓰는 순간을 다뤘다면 이 셋은 그 다음을 다룬다: 완료 게이트(`l, 스킬이 백틱으로 가르치는 기대 키가 전부 EXPECTATIONS에 있는가.          이것이 이 파일의 핵심이다. 구현에 없는 규칙(계획, KB 조회 경로가 실제 CLI와 맞는가., `---`로 감싼 머리말을 key: value로 읽는다. fence가 없으면 거부한다., 정상 경로 — 세 스킬 모두 로드 가능한 형태인가. (+6 more)

### Community 25 - "Community 25"
Cohesion: 0.12
Nodes (16): _b_double(), _doc(), _observe_a(), Issue #43: masking must hold on EVERY output channel, not just the trace.  QA ca, F-7: the result channel must mask exactly what the trace channel masks., A mode B observation stub (what-to-mock: stub the query side).      Copies the c, F-9: masking PASS must mean every output channel was scanned., Every property name whose schema says `writeOnly: true`, recursively. (+8 more)

### Community 26 - "Community 26"
Cohesion: 0.1
Nodes (15): diagnose(), EveryOrphanIsNamed, ItStaysQuietWhereThereIsNoConsequence, `guard-orphaned-steps` — 가드가 지키려던 상태를 가드 밖에서 만지는 스텝 (RFC-0023).  가드는 **바로 다음 항목, `source`가 내는 이 코드의 진단들 — 컴파일러가 판정한다., 커밋된 통제쌍. 골든에 이 형태가 없어서 골든 변형으로는 검증되지 않는다., 권하는 고침이 실제로 진단을 없애지 못하면 그 문면은 거짓이다., 가드 아래 있는 것은 이미 조건부다 — 그게 **다른** 가드여도 그렇다.      이 클래스가 `_steps_outside_guards`의 G (+7 more)

### Community 27 - "Community 27"
Cohesion: 0.12
Nodes (14): _calls_named(), GuardBoundaryTest, GuardDetectsLeaksTest, leaking_scopes(), _mkdtemp_calls(), mkdtemp_without_dir(), 임시 디렉터리 위생 — 테스트가 만든 것은 테스트가 지운다.  이 파일이 존재하는 이유(실측): `.claude/tmp`에 998개 / 43MB, 가드 자체가 작동하는지 — 통과만으로는 잠자는 테스트와 구별되지 않는다. (+6 more)

### Community 28 - "Community 28"
Cohesion: 0.13
Nodes (8): extract_with(), Issue #54 [3]: a `given` the runner cannot build is refused at manifest time.  B, The boundary: nothing is declared, so every field name is undeclared., TestFormErrors, TestNoEntityModule, TestStoredNameChecks, TestUndeclaredNamesAreRefusedEarly, TestValidGivensSurvive

### Community 29 - "Community 29"
Cohesion: 0.14
Nodes (13): _doc(), _payment_doc(), Issue #83: a guard skip record carries the values it actually measured.  RFC-001, RFC-0014 example 1 (`stock = 0`): the skip's `evaluations` names what     was ac, D3: a `ref` naming a sensitive entity field gets its `value` masked the     same, RFC-0015 `and`: `_condition_holds` threads `collector` through its own     per-t, Task 02 / plan D2: `evaluations` must never reach the mode A/B     comparison —, _run() (+5 more)

### Community 30 - "Community 30"
Cohesion: 0.13
Nodes (8): DevPluginStructureTest, DevSkillContentTest, frontmatter_name(), `lnpl-dev` 플러그인(기여자용)의 구조 검사.  `lnpl` 플러그인이 `.lnpl` 작성자를 향한다면 이쪽은 linkly 자체를 고치는, 스킬이 가리키는 도구가 실재하는가 — 깨지면 조용히 쓸모없어진다., 가르치는 내용이 실측과 어긋나지 않는가., read(), ToolReferenceIntegrityTest

### Community 31 - "Community 31"
Cohesion: 0.17
Nodes (7): Carry out one RepositoryCall.          read / query    -> the stored row as a di, Every row for `entity_id`, ordered by row_key ascending.          Empty list whe, Write back a row mutated through an execution-scope binding.          RFC-0015's, Release resources. Safe to call more than once., The `postgres` capability's adapter contract.      Reference implementation: `in, Populate `{entity_id: {row_key: row}}`, INSERTING ONLY WHERE ABSENT.          In, RepositoryDriver

### Community 32 - "Community 32"
Cohesion: 1.0
Nodes (1): A payload whose entity fields differ from the default must be read from

### Community 33 - "Community 33"
Cohesion: 1.0
Nodes (0): 

### Community 34 - "Community 34"
Cohesion: 1.0
Nodes (1): RFC-0025 §10: the boundary case — an unseeded `list`-only entity         must NO

### Community 35 - "Community 35"
Cohesion: 1.0
Nodes (1): A `list` under a `when` — mode B's scf.if branching must agree with         mode

### Community 36 - "Community 36"
Cohesion: 1.0
Nodes (1): `--no-row`'s seed condition (`seeded=frozenset()`) — the entity the         work

### Community 37 - "Community 37"
Cohesion: 1.0
Nodes (1): A minimal observation whose only interesting field is `effects`.

### Community 38 - "Community 38"
Cohesion: 1.0
Nodes (1): Absolute, `~`-expanded, and resolved once so every later component         agree

### Community 39 - "Community 39"
Cohesion: 1.0
Nodes (1): One of SEVERITIES, decided by the code alone (#52).

### Community 40 - "Community 40"
Cohesion: 1.0
Nodes (1): `product` for `product.stock`; None for a bare name.

### Community 41 - "Community 41"
Cohesion: 1.0
Nodes (1): The last segment: `stock` for both `stock` and `product.stock`.

## Knowledge Gaps
- **419 isolated node(s):** `Mode B (native) and the mode A/B differential check.  RFC-0004 requires the equi`, `Emission needs no toolchain — it is text generation.`, `RFC-0008: Presence guard 'when field missing' with absent field.          When t`, `RFC-0008: Presence guard 'when field missing' with present field.          When`, `RFC-0004's deliberate-mismatch requirement: the check must be able to fail.` (+414 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 32`** (1 nodes): `A payload whose entity fields differ from the default must be read from`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 33`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 34`** (1 nodes): `RFC-0025 §10: the boundary case — an unseeded `list`-only entity         must NO`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 35`** (1 nodes): `A `list` under a `when` — mode B's scf.if branching must agree with         mode`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 36`** (1 nodes): ``--no-row`'s seed condition (`seeded=frozenset()`) — the entity the         work`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 37`** (1 nodes): `A minimal observation whose only interesting field is `effects`.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 38`** (1 nodes): `Absolute, `~`-expanded, and resolved once so every later component         agree`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 39`** (1 nodes): `One of SEVERITIES, decided by the code alone (#52).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (1 nodes): ``product` for `product.stock`; None for a bare name.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (1 nodes): `The last segment: `stock` for both `stock` and `product.stock`.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Interpreter` connect `Runtime & Drivers` to `Conditions & Time Semantics`, `CLI & Serve Backend`, `Mode Equivalence & Repo State`, `CLI Diagnostics & Plugins`, `Parser & Syntax`, `IR Lowering & Network Binding`, `OpenAPI & Types`, `Refinement & Golden Fixtures`, `Community 13`, `Community 14`, `Community 22`, `Community 25`, `Community 29`?**
  _High betweenness centrality (0.166) - this node is a cross-community bridge._
- **Why does `parse()` connect `Parser & Syntax` to `Runtime & Drivers`, `CLI & Serve Backend`, `Agent Protocol`, `Mode Equivalence & Repo State`, `CLI Diagnostics & Plugins`, `IR Lowering & Network Binding`, `MLIR Dialect & Backend`, `OpenAPI & Types`, `Lowering Tests`, `Refinement & Golden Fixtures`, `Community 12`, `Community 13`, `Community 14`, `Community 15`, `Community 18`, `Community 19`, `Community 22`, `Community 25`, `Community 26`, `Community 27`, `Community 28`, `Community 29`?**
  _High betweenness centrality (0.102) - this node is a cross-community bridge._
- **Why does `SpecError` connect `CLI & Serve Backend` to `Runtime & Drivers`, `Conditions & Time Semantics`, `Parser & Syntax`, `IR Lowering & Network Binding`, `Community 13`, `Community 15`, `Community 28`?**
  _High betweenness centrality (0.079) - this node is a cross-community bridge._
- **Are the 485 inferred relationships involving `Interpreter` (e.g. with `MockClock` and `TestUntilBoundaries`) actually correct?**
  _`Interpreter` has 485 INFERRED edges - model-reasoned connections that need verification._
- **Are the 251 inferred relationships involving `RunError` (e.g. with `TestUnenforcedDeclarationsAreReported` and `TestGoldenScenario`) actually correct?**
  _`RunError` has 251 INFERRED edges - model-reasoned connections that need verification._
- **Are the 233 inferred relationships involving `ConditionError` (e.g. with `TestConditionParsing` and `TestScopedReference`) actually correct?**
  _`ConditionError` has 233 INFERRED edges - model-reasoned connections that need verification._
- **Are the 232 inferred relationships involving `parse()` (e.g. with `ir()` and `.test_login_example_lowers_unchanged()`) actually correct?**
  _`parse()` has 232 INFERRED edges - model-reasoned connections that need verification._