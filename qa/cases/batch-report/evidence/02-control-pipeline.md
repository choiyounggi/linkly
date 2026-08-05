# 양성 대조군: examples/shorten.lnpl 전 파이프라인 실행

목적(D2, wiki: testing-quality-harness-reverse-controls): batch-report 판정 전에
공식 예제가 이 환경에서 어디까지 통과하는지 고정한다. 대조군이 실패하는 단계는
batch-report에서 `N/A(env)`, 대조군이 통과하는 단계의 batch-report 실패만 FAIL.

- 실행 시각: 2026-08-05 21:2x KST, HEAD=713a4cb, venv=.venv (python3.13, 상대경로)
- env: `PATH=/opt/homebrew/opt/llvm/bin:$PATH`, `CPATH=$SDK/usr/include`, `LIBRARY_PATH=$SDK/usr/lib`
- 사전 점검: `bash scripts/dev_doctor.sh` → exit=0 (`01-env-doctor.log`)

## 명령 발견 경로 (D14 — 발견 난이도 측정)

| 단계 | 명령 | 발견 출처 | 발견 난이도 메모 |
|------|------|-----------|------------------|
| parse+lower | `lnpl compile <src> -o <out.lir.json>` | lnpl-authoring SKILL.md "쓴 다음에 반드시 한다" + `lnpl --help` | 쉬움 — SKILL 본문에 명시 |
| validate | `python scripts/validate_ir.py <file.lir.json>` | 브리프 + `validate_ir.py --help`(인자 없이 rc=1로 사용법 출력) | 보통 — 스킬 문서에는 단일 문서 검증 언급 없음, 스크립트 자체 헬프로 확인 |
| mode A | `lnpl run <src> [--payload f.json] [--json]` | `lnpl --help` | 쉬움 |
| mode B | `lnpl build <src> --workdir <dir> --run` | `lnpl --help` + lnpl-verify SKILL(툴체인 조건) | 쉬움 |
| differential | `lnpl diff <src> --workdir <dir>` | lnpl-verify SKILL.md §3 | 쉬움 |
| openapi | `lnpl openapi <src> -o <out>` | `lnpl --help` | 쉬움 |
| spec 검증 | `lnpl spec <src> --run` | lnpl-verify SKILL.md §2 | 쉬움 |
| (게이트) | lnpl-verify SKILL 절차 전체 | AGENTS.md 라우팅 표 | 쉬움 |

핵심 사전 지식(문서에서 확보): 진단은 **stderr + exit 0** — 안 보면 사라진다.
`unknown-verb` 진단이 silent no-op의 1차 판별기.

## 대조군 결과

| 단계 | 명령 | exit | 판정 | 증적 |
|------|------|------|------|------|
| parse+lower | `lnpl compile examples/shorten.lnpl -o …/control/shorten.lir.json` | 0 | PASS (24 nodes; 의도 경고 3건) | 01-control-compile.log |
| validate | `validate_ir.py …/control/shorten.lir.json` | 0 | PASS | 01-control-validate.log |
| mode A | `lnpl run examples/shorten.lnpl --json` | 0 | PASS (status=completed, 6 steps) | 01-control-modeA.log |
| mode B | `lnpl build examples/shorten.lnpl --workdir .claude/tmp/control-build --run` | 0 | PASS | 01-control-modeB.log |
| differential | `lnpl diff examples/shorten.lnpl --workdir .claude/tmp/control-diff` | 0 | PASS (4/4 EQUIVALENT) | 01-control-diff.log |
| openapi | `lnpl openapi examples/shorten.lnpl -o …/control/shorten.openapi.json` | 0 | PASS | 01-control-openapi.log |
| spec | `lnpl spec examples/shorten.lnpl --run` | 0 | PASS (4 passed, 0 failed) | 01-control-spec.log |

**결론: 이 환경에서 파이프라인 7단계 전부 대조군 통과. batch-report에 `N/A(env)`
해당 단계 없음 — 이후 모든 실패는 케이스(어휘/표현) 귀속으로 판정 가능.**

부기: `shorten.lnpl`은 의도적으로 `unknown-verb`(line 57 `return slug`),
`declared-not-enforced`(security jwt), `declared-measured-only`(performance
response) 경고를 낸다(lnpl-verify SKILL이 예고). 진단 메시지 품질: 코드·위치·
기제("derives no Effect and runs as a descriptive no-op")를 모두 서술 — 높음.
