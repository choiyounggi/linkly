# Analysis — i169-mutation-baseline

## Requirements
| Rule | Concrete example | Open question |
|------|------------------|---------------|
| R1: baseline/no-op RED 시 하네스가 실패 증거를 출력한다 | Given 러너에서 baseline 스위트가 FAILED(6) / When `mutation_check.py` 실행 / Then stdout에 "baseline is not green (RED)"와 함께 실패 테스트 요약(FAIL:/ERROR: 줄 + unittest 말미 요약)이 bounded tail로 찍힌다 | |
| R2: mutation full-matrix 잡을 수동 트리거할 수 있다 | Given 브랜치 push / When `gh workflow run "Mutation testing" --ref <branch>` / Then mutation-weekly 잡이 그 브랜치에서 실행된다 | |
| R3: hosted 러너에서 baseline이 green이다 | Given workflow_dispatch 실행 / When 잡 로그의 harness 출력 확인 / Then "baseline (unmutated copy): GREEN" | |
| R4: 기존 소비자 계약 불변 | Given `tests.test_mutation_*` 4개 모듈 + `scripts/mutation_scope_select.py` / When 변경 후 실행 / Then rc=0, `mc.main()`·`mc.MUTATIONS`·`TREE_CONTENTS` 인터페이스 그대로 | |

## Ground truth
- Baseline: PYTHONPATH=impl .venv/bin/python -m unittest tests.test_mutation_tree tests.test_mutation_scope_select tests.test_mutation_workflow tests.test_mutation_report -q -> rc=0, HEAD 8620f8b, git status clean

### Affected files
- `impl/tests/mutation_check.py` — evidence: `grep -n "capture_output=True" impl/tests/mutation_check.py` -> 1 hit (run_suite가 스위트 출력을 버림; baseline RED 시 진단 0줄이 러너 로그 실측으로 확인됨, run 33663504271)
- `.github/workflows/mutation.yml` — evidence: `grep -n "workflow_dispatch" .github/workflows/mutation.yml` -> 0 hits (schedule·pull_request만 존재; 수용 기준의 "full-matrix 1회 green 관측"에 수동 트리거 필요)
- `impl/tests/test_mutation_workflow.py` — evidence: `grep -n "def test_" impl/tests/test_mutation_workflow.py` -> 12 hits (mutation.yml 소스 텍스트 계약 테스트 — 트리거 추가 시 여기에 테스트 추가)
- `scripts/mutation_report.py` + `impl/tests/test_mutation_report.py` — evidence: `grep -rn "run_suite\|baseline" scripts/mutation_report.py` (하네스 stdout 파서 — 새 진단 줄이 파서를 깨지 않아야 함; T1에서 계약 확인 필수)

## Constraints
- main 브랜치 보호(enforce_admins, PR+green 필수) — checked: `gh api repos/{owner}/{repo}/branches/main/protection` (메모리 linkly-161-166-shipped 실측; 직접 push 불가, 브랜치+PR 경로)
- mutation 앵커 문자열 보존: `MUTATIONS` 튜플의 anchor는 대상 파일(`lnpl/*.py`)의 리터럴 텍스트 — `impl/tests/mutation_check.py`·`.github/workflows/mutation.yml` 수정은 앵커 파일이 아니므로 안전 — checked: `grep -c "lnpl/" impl/tests/mutation_check.py` (앵커 relpath는 전부 lnpl/ 아래)
- `test_mutation_workflow.py`는 mutation.yml의 소스 텍스트를 직접 파싱해 단정(`test_no_continue_on_error_anywhere`, `test_rc_captured_before_parse_step` 등) — 트리거/if 조건 수정 시 이 계약을 위반하면 안 됨 — checked: `PYTHONPATH=impl .venv/bin/python -m unittest tests.test_mutation_workflow -q` -> rc=0
- 이 PR의 mutation-pr 잡은 zero-anchor 스킵(#168) 경로를 탄다(변경 파일에 앵커 없음) — baseline 검증은 workflow_dispatch로만 가능 — checked: `PYTHONPATH=impl .venv/bin/python scripts/mutation_scope_select.py .github/workflows/mutation.yml` -> "no anchor intersects"

## Spikes
- **CI 조건 로컬 재현 (완료)**: python3.13 fresh venv + `pip install .`만, `make_tree` 복사본에서 `.venv` 제거, LLVM env 셋 후 전체 discover 실행.
  - PATH에 `lnpl` 콘솔 스크립트가 **없으면**: `Ran 3773, FAILED (failures=6)` — 전부 `test_plugin_doctor`/`test_plugin_manifest`의 CLI-부재 실패. 러너에는 setup-python bin이 PATH에 있어 이 조건은 CI와 다름(스파이크 충실도 결함이었음).
  - PATH 보정 후(CI-충실): `Ran 3773, OK (skipped=2)` — **macOS에서는 재현 불가**.
  - 결론: RED 원인은 Linux/러너 특이 델타. 유력 후보 = **툴체인 존재 시에만 unskip되는 mode-B 테스트 무리**(ci.yml gate 잡은 툴체인 없이 돌고, modeb-linux 잡은 test_repo_state만 돌므로, "ubuntu+툴체인+전체 스위트"는 mutation baseline이 유일 경로); 차순위 = 로컬에서 `venv_above()` skip되는 `test_plugin_hook` 격리 테스트 2건(러너에선 실행; 단 ci.yml gate 잡에서 이미 green이므로 가능성 낮음).
  - **러너 실측 없이는 실패 집합 확정 불가** — 그래서 T1(진단 표면화)+T2(dispatch 트리거)를 먼저 랜딩하고 T3에서 실측한다. 실패 집합이 확정되면 수정 결정은 Phase B/C repair 라운드로 재진입한다(계획된 2단계 구조, 방치된 미결정이 아님).

## Research
| Query | Source | Applied |
|-------|--------|---------|
| mutation testing CI baseline must be green surface test suite failure output mutmut cosmic-ray practice (brave_web_search) | cosmic-ray.readthedocs.io — "If the test suite does not pass in the absence of mutations, the results are essentially useless"; cosmic-ray는 전용 `baseline` 명령이 실패 출력을 그대로 노출 | R1의 설계 근거: baseline 실패는 표준적으로 *출력을 보여주며* 실패해야 한다. 본 하네스도 RED 시 스위트 출력 tail을 인쇄하도록 수정(T1) |
