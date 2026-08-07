# 00 — 환경·기준점 (r2 재측정)

- 날짜: 2026-08-07 (KST)
- 기준 commit: `6d84bd6f9f41e4978f916ee191ab4216cf591da9` (main 머지 — #43~#50 구현, RFC-0014~0017)
- 원 실측 대조 기준: commit 713a4cb, 2026-08-05 (`qa/cases/payment-refund/`)
- lnpl 버전: `lnpl 0.2.0` (raw/version.out)
- venv: 워크트리 자체 `.venv` (python3.13, `pip install -e .` rc=0) — 상대경로 호출
- 셸 환경: `PATH=/opt/homebrew/opt/llvm/bin:...`, `CPATH`/`LIBRARY_PATH`=`xcrun --show-sdk-path` 기준 (셸마다 export)
- `bash scripts/dev_doctor.sh` → **rc=0** (raw/doctor.out)

## --strict 가용성 (브리프 제약 3)

`lnpl run --help`(raw/run-help.out)에 `--strict` 존재:
> `--strict  exit 2 if any diagnostic is reported (otherwise the exit code is unchanged)`

원 실측(2026-08-05) 당시에는 없던 옵션 — 재측정에서는 대표 셀에 유/무 양쪽 실행을 구분 기록한다(D5).

## CLI 표면 (raw/help.out)

서브커맨드: `compile, run, spec, openapi, build, diff, kb, agents`.
`run --payload`는 이제 **JSON 파일** 인자로 문서화됨(원 실측은 인라인 JSON 문자열 사용) — 차이는 authoring 단계에서 실측.
