# v0.8.0 엔터프라이즈 실사용 감사 (11차) — 공통 측정 프로토콜

이 디렉터리의 문서는 **계약**이다. 워커(각 시나리오를 실제로 개발하는 세션)는 이
문서를 읽고 따르되 **고치지 않는다**. 요구사항이 애매하거나 플랫폼으로 표현 불가능해
보이면 그것 자체가 측정 결과다 — FINDINGS에 기록하고, 가장 가까운 해석으로 진행한다.

## 1. 질문

"linkly(lnpl 0.8.0)만 가지고 실제 엔터프라이즈급 개발을 진행할 수 있는가. 성능·유지보수·
LLM 특화 측면에서 충분한가. 상품성에 대한 테스트·QA는 되어 있는가."

이전 10차 판정(`qa/rerun/REPORT.md`): "조건부 Go — 요청-응답 CRUD·값 규칙·가드+spec은
Ship-with-known-issues, 배치·집계는 Block". 그 판정은 lnpl 0.2.0 기준이었다. 이번은
v0.8.0에서 새로 열린 표면(RowSet group by·Money·NetworkDriver 실패 분기·outbox/relay·
네임스페이스·다중 파일·트랜잭션·드라이버 SPI 3종·serve 경화·migrate)을 실제 요구사항으로
밟는다.

## 2. 워커 조건 — 블랙박스

워커는 **외부 엔터프라이즈 개발자**를 흉내낸다. 허용되는 지식원:

- `AGENTS.md`·`CLAUDE.md`(레포 루트 — 모든 세션에 자동 로드되는 스킬 라우팅 표; 외부 개발자도 첫 화면으로 보는 문서)
- `plugins/lnpl/skills/**` (lnpl-authoring · lnpl-kb · lnpl-spec · lnpl-verify · lnpl-doctor)
  와 그 `references/`
- `docs/**`, `README.md`, `examples/**`, `rfcs/**`(공개 명세이므로 허용)
- `lnpl` CLI (`--help` 포함), `lnpl-mcp` MCP 툴(붙어 있으면)
- 외부 드라이버 레포의 README (lnpl-postgres · lnpl-redis · lnpl-otel)

**금지**: `impl/` 소스 열람·수정, `scripts/` 열람. 예외 하나 — 어떤 마찰의 **근인을
확정**하기 위해서만 `impl/`을 읽을 수 있고, 그 경우 해당 F-항목에 `근인(impl 열람)`
필드를 채워 표기한다. `impl/` **수정은 어떤 이유로도 금지**(측정 중 수리 금지).

플랫폼 버그를 발견해도 고치지 않는다. 우회했으면 우회를 기록한다. 우회도 못 했으면
그 요구사항을 "불가"로 기록하고 다음으로 간다.

## 3. 환경

- 워크트리마다 자기 `.venv`(python3.13, `.venv/bin/python` 상대경로). `bash scripts/dev_doctor.sh`
  는 실행해도 된다(읽기 전용 진단). 모드 B(`lnpl build`)를 쓰려면 세션에서
  `SDK="$(xcrun --show-sdk-path)"; export CPATH="$SDK/usr/include" LIBRARY_PATH="$SDK/usr/lib"`.
- 설치: `.venv/bin/pip install -e .` 후 `.venv/bin/lnpl --version`이 `0.8.0`인지 확인해
  `evidence/00-env.md`에 기록.
- Docker 27 사용 가능. 외부 드라이버는 `pip install git+https://github.com/choiyounggi/<repo>@main`.
- 임시 파일은 자기 워크트리의 `.claude/tmp/` 아래. `/tmp` 금지.
- `git stash` 금지. 커밋은 코디네이터 지시가 있을 때만.

## 4. 기록 — 무엇을 남기는가

케이스 디렉터리 `qa/probe-v0.8/cases/<case>/`:

```
<case>/
  src/            .lnpl 소스(다중 파일이면 디렉터리 구조 그대로), lnpl.toml, 페이로드 JSON
  evidence/       NN-<단계>.md — 실행한 명령·rc·출력 발췌(절단 시 절단 표기)
  FINDINGS.md     마찰 기록 + Scorecard + 요구사항 커버리지 + 케이스 판정 (스키마: FINDINGS-SCHEMA.md)
  METRICS.md      정량 지표 (스키마: FINDINGS-SCHEMA.md §3)
```

원칙:

- **모든 재시도를 센다.** `.lnpl`을 고치고 다시 돌린 횟수가 authoring 라운드다. "왜 다시
  돌렸는가"를 한 줄씩 evidence에 남긴다.
- **초록 ≠충족.** 파이프라인이 통과해도 요구사항이 실제로 구현됐는지(값이 실제로
  계산되는지, 거부가 실제로 일어나는지) 실행 출력으로 증명한다. no-op 스텝이 spec을
  통과시키는지 의심하라 — `--strict=warning`, `effects complete`, `rows <Entity> <N>`을 쓴다.
- **문서가 틀리면 문서 마찰이다.** 스킬 문서대로 썼는데 파서가 거부하거나 런타임이
  무시하면 그것이 가장 중요한 LLM 특화 마찰이다. 어느 문서 어느 줄을 따랐는지 인용한다.
- **우회는 의미 손실을 명시한다.** 우회로 요구사항의 일부를 포기했으면 어떤 부분인지 쓴다.
- 판정 어휘는 셋뿐: **Ship / Ship-with-known-issues / Block.** 네 번째는 없다.

## 5. 시간 예산

한 시나리오는 실개발 기준 **집중 작업 4시간 상당**을 상한으로 본다. 상한에 닿으면
그 시점의 상태를 기록하고 마무리한다 — 미완도 데이터다. 한 마찰에 3회 이상 우회를
시도해도 안 되면 "불가"로 기록하고 넘어간다.

## 6. 시나리오 색인

| 케이스 | 문서 | 시험하는 것 |
|--------|------|-------------|
| s1-order-platform | s1.md | 엔터프라이즈 코드베이스 구조·도메인 규칙·상태 전이·Money·트랜잭션·변경 요청 |
| s2-integration-events | s2.md | 실 HTTP 연동·실패 분기·재시도·보상·outbox/relay 이벤트·멱등 소비 |
| s3-batch-report | s3.md | 스케줄·집계(group by/avg/min/max)·10k 행 성능·멱등 재실행 (이전 Block 도메인) |
| s4-ops-deploy | s4.md | postgres/redis/otel 실드라이버·serve 경화·마이그레이션·Docker·부하·드레인 |
| s5-baseline-fastapi | s5.md | s1과 동일 요구사항을 FastAPI+SQLite로 — LLM 특화 주장의 대조군 |
