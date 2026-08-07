# 00 — 재측정 환경 스냅샷 (T1)

- 커밋: `6d84bd6f9f41e4978f916ee191ab4216cf591da9` (main 머지 후 — #43~#50 구현 포함)
- 원 실측 환경과의 차이: 원은 `713a4cba`(구현 전) — 이 재측정의 대조 대상 그 자체.
- python: 3.13 (워크트리 자체 `.venv`, `pip install -e .` rc=0 — raw/pip-install.txt)
- lnpl: `lnpl 0.2.0` (`.venv/bin/lnpl --version`)
- LLVM/SDK: `export PATH="/opt/homebrew/opt/llvm/bin:$PATH"; SDK="$(xcrun --show-sdk-path)"; export CPATH="$SDK/usr/include" LIBRARY_PATH="$SDK/usr/lib"` — 셸마다 재설정.
- `bash scripts/dev_doctor.sh` → **rc=0** (raw/doctor.txt)
- 베이스라인: `git status --porcelain -uall`에서 `qa/rerun/`·`.claude/` 밖 항목 0줄 (클린).
- 실행 시각: 2026-08-07 14:1x KST
