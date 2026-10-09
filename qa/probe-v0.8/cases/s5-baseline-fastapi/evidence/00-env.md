# 00 — Environment

- 커밋(linkly worktree HEAD, 참고용 — 이 케이스는 그 커밋 내용을 사용하지 않음): 264e3442d653e5534d827687ebac5ede956e801a
- 타임스탬프(시작): 2026-09-05T16:37:22Z
- python: `python3.13 --version` → `Python 3.13.1`
- venv: `.venv-s5` (case-local, python3.13)
- 설치 커맨드: `.venv-s5/bin/pip install fastapi "uvicorn[standard]" pydantic pytest httpx import-linter`
- `pip freeze` (핵심 패키지, 전문은 `src/requirements.txt`):
  ```
  fastapi==0.141.1
  uvicorn==0.52.4
  pydantic==2.13.5
  pydantic_core==2.46.5
  pytest==9.1.1
  httpx==0.28.1
  import-linter==2.15
  starlette==1.6.0
  anyio==4.15.1
  ```
- dev_doctor: 해당 없음 — 이 케이스는 linkly/lnpl 환경이 아니라 별도 파이썬 venv이므로 `scripts/dev_doctor.sh`는 실행하지 않음(범위 밖: impl/, scripts/ 열람 금지).
