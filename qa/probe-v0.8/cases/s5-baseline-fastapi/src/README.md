# OrderHub (S5 baseline)

Setup: `python3.13 -m venv .venv-s5 && .venv-s5/bin/pip install -r src/requirements.txt`
Test: `ORDERHUB_TEST_HOOKS=1 .venv-s5/bin/pytest -q tests` (from the case dir)
Lint (R1 boundary): `PYTHONPATH=src .venv-s5/bin/lint-imports --config .importlinter`
Run: `PYTHONPATH=src ORDERHUB_DB=<path>.db .venv-s5/bin/python -m orderhub.seed && PYTHONPATH=src ORDERHUB_DB=<path>.db .venv-s5/bin/uvicorn orderhub.app:app --port 8765`
