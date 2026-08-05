# Task 01: `lnpl`을 레포 밖에서 실행 가능한 패키지로 만든다

> 실행자에게: 이 태스크는 `superpowers:subagent-driven-development` 또는
> `superpowers:executing-plans`로 수행한다. 각 Step은 체크박스 단위다.

## Objective
`pip install .` 후 **linkly 레포 밖 임의 디렉터리에서** `lnpl compile <src>`가 동작한다.
기존 `PYTHONPATH=impl python -m lnpl` 경로는 그대로 살아 있어야 한다(README:147).

이게 P0인 이유: 대상 사용자는 정의상 linkly 레포 밖에서 자기 `.lnpl` 프로젝트를
쓰는 사람이다. 이것 없이는 플러그인이 설치돼도 훅이 전부 죽는다(F8).

## Files
- Create: `pyproject.toml`
- Create: `impl/tests/test_packaging.py`
- Modify: `.gitignore` (빌드 산출물 `build/`, `dist/`, `*.egg-info/` 무시)

## Interfaces
- Produces: 콘솔 스크립트 `lnpl` → `lnpl.cli:main`. Task 02·05·06이 이 이름에 의존한다.
- Consumes: 없음 (첫 태스크)

## References
- `impl/lnpl/cli.py:291` — `main(argv=None)`. 이미 엔트리포인트 시그니처를 갖췄다.
- `impl/lnpl/__init__.py:12` — `__version__ = "0.2.0"`. 버전 단일 출처.
- `README.md:146-150` — 깨뜨리면 안 되는 기존 실행 경로.

## Steps

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`impl/tests/test_packaging.py`:

```python
"""pyproject.toml이 `lnpl` 콘솔 스크립트를 올바르게 선언하는지 검사한다.

실제 설치를 여기서 하지는 않는다(느리고 네트워크를 탄다). 대신 선언이
정확한지와, 그 선언이 가리키는 대상이 실제로 호출 가능한지를 본다.
"""
import pathlib
import tomllib
import unittest

import lnpl

ROOT = pathlib.Path(__file__).resolve().parents[2]


class PyprojectTest(unittest.TestCase):
    def setUp(self):
        path = ROOT / "pyproject.toml"
        self.assertTrue(path.is_file(), "pyproject.toml이 레포 루트에 없다")
        with open(path, "rb") as fh:
            self.cfg = tomllib.load(fh)

    def test_console_script_points_at_cli_main(self):
        scripts = self.cfg["project"]["scripts"]
        self.assertEqual(scripts["lnpl"], "lnpl.cli:main")

    def test_entry_point_target_is_callable(self):
        from lnpl.cli import main
        self.assertTrue(callable(main))

    def test_package_dir_is_impl(self):
        tool = self.cfg["tool"]["setuptools"]
        self.assertEqual(tool["package-dir"], {"": "impl"})
        self.assertEqual(tool["packages"], ["lnpl"])

    def test_version_matches_package_dunder(self):
        self.assertEqual(self.cfg["project"]["version"], lnpl.__version__)

    def test_requires_python_floor_declared(self):
        self.assertEqual(self.cfg["project"]["requires-python"], ">=3.9")

    def test_runtime_dependency_set_is_exactly_jsonschema(self):
        # 의존을 늘리지 않는다는 제약을 테스트로 고정한다.
        deps = self.cfg["project"]["dependencies"]
        self.assertEqual([d.split(">")[0].split("=")[0].strip() for d in deps],
                         ["jsonschema"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_packaging -v 2>&1 | tail -20
```
Expected: FAIL — `pyproject.toml이 레포 루트에 없다`

- [ ] **Step 3: `pyproject.toml`을 만든다**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "lnpl"
version = "0.2.0"
description = "LNPL — the surface language, Semantic IR, and runtime of the linkly LLM-native programming platform"
readme = "README.md"
requires-python = ">=3.9"
license = { file = "LICENSE" }
dependencies = ["jsonschema"]

[project.scripts]
lnpl = "lnpl.cli:main"

[tool.setuptools]
package-dir = { "" = "impl" }
packages = ["lnpl"]
```

주의: `version`은 `lnpl.__version__`과 같아야 한다(Global Constraints의 버전 단일
출처). 손으로 둘을 맞추고, Step 1의 `test_version_matches_package_dunder`가 어긋남을
잡는다.

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_packaging -v 2>&1 | tail -10
```
Expected: PASS (6 tests)

- [ ] **Step 5: 실제 설치를 검증한다 (수용 기준 1)**

레포 밖에서 도는지가 이 태스크의 전부다. 선언 검사만으로는 증명되지 않는다.

```bash
mkdir -p .claude/tmp/pkgtest && \
python3.13 -m venv .claude/tmp/pkgtest/venv && \
.claude/tmp/pkgtest/venv/bin/pip -q install . && \
printf 'capability postgres\n\nentity Note\n    field\n        id UUID\n\nworkflow Save\n    validate input\n    create note\n' > .claude/tmp/pkgtest/probe.lnpl && \
cd .claude/tmp/pkgtest && ./venv/bin/lnpl compile probe.lnpl | head -5; echo "exit=$?"
```
Expected: IR JSON이 출력되고 `exit=0`. **레포 루트가 아닌 `cwd`에서 실행됐다는 점이
핵심이다.**

- [ ] **Step 6: 기존 실행 경로가 살아 있는지 확인한다**

```bash
cd "$(git rev-parse --show-toplevel)" && \
PYTHONPATH=impl .venv/bin/python -m lnpl compile examples/login.lnpl | head -3
```
Expected: IR JSON 출력. README:147이 여전히 유효하다.

- [ ] **Step 7: 검증용 산출물을 지우고 `.gitignore`를 갱신한다**

```bash
rm -rf .claude/tmp/pkgtest lnpl.egg-info impl/lnpl.egg-info
```

`.gitignore`에 다음 세 줄을 추가한다(이미 있으면 건너뛴다):

```
build/
dist/
*.egg-info/
```

- [ ] **Step 8: 전체 테스트 무회귀를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl 2>&1 | tail -5
```
Expected: OK — 기존 386건 + 신규 6건이 전부 통과.

- [ ] **Step 9: 커밋**

```bash
git add pyproject.toml impl/tests/test_packaging.py .gitignore
git commit -m "feat(packaging): make lnpl installable so the CLI runs outside the repo

대상 사용자는 linkly 레포 밖에서 .lnpl을 쓴다. package-dir로 impl/이 소스
루트라는 기존 사실을 선언하고 콘솔 스크립트만 추가한다 — PYTHONPATH=impl
경로는 그대로다."
```

## Deliverables
- `pyproject.toml` — `lnpl` 콘솔 스크립트, `package-dir = {"" = "impl"}`
- `impl/tests/test_packaging.py` — 6건
- `.gitignore` 갱신

## Acceptance
1. 레포 밖 `cwd`에서 `lnpl compile`이 exit 0으로 동작한다(Step 5로 실증).
2. `PYTHONPATH=impl python -m lnpl`이 여전히 동작한다(Step 6).
3. `pyproject.toml`의 `version`이 `lnpl.__version__`과 같다.
4. 런타임 의존이 `jsonschema` 하나로 유지된다.
5. 전체 스위트 무회귀.
