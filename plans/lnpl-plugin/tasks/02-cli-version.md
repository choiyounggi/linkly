# Task 02: `lnpl --version`을 추가한다

> 실행자에게: 이 태스크는 `superpowers:subagent-driven-development` 또는
> `superpowers:executing-plans`로 수행한다. 각 Step은 체크박스 단위다.

## Objective
`lnpl --version`이 `lnpl.__version__`을 출력하고 exit 0으로 끝난다. Task 06의
`lnpl-doctor`가 설치된 CLI 버전과 플러그인 버전을 비교하는 유일한 수단이다(A12).

## Files
- Modify: `impl/lnpl/cli.py:291-292` (`main()`의 `ArgumentParser` 생성 직후)
- Modify: `impl/tests/test_cli.py` (새 테스트 클래스 추가)

## Interfaces
- Consumes: Task 01의 콘솔 스크립트 `lnpl`
- Produces: `lnpl --version` → stdout `lnpl <version>`, exit 0. Task 06이 이 출력
  형식(공백으로 분리된 두 번째 필드가 버전)에 의존한다.

## References
- `impl/lnpl/cli.py:291-293` — `main()`. `sub = ap.add_subparsers(dest="cmd", required=True)`
  때문에 서브커맨드가 **필수**다.
- `impl/lnpl/__init__.py:12` — `__version__`.
- `impl/tests/test_cli.py:28` — 기존 `run_cli(argv)` 헬퍼. `--version`은 `SystemExit`을
  던지므로 이 헬퍼로는 잡을 수 없다. 새 테스트는 `assertRaises(SystemExit)`을 쓴다.

## 사전 확인된 사실

`required=True`인 서브파서와 `action="version"`이 충돌하지 않는다. argparse의 version
액션은 파싱 도중 즉시 `parser.exit()`을 호출하므로, "서브커맨드가 필요하다"는 검사에
도달하기 전에 exit 0으로 끝난다. 이번 조사에서 직접 실행해 확인했다:

```
lnpl 0.2.0
SystemExit code: 0
```

## Steps

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`impl/tests/test_cli.py` 끝에 추가한다(파일 상단 import에 `lnpl` 추가):

```python
class TestVersionFlag(unittest.TestCase):
    """`--version`은 서브커맨드 없이도 통해야 한다 (`required=True`인데도).

    lnpl-doctor가 설치된 CLI와 플러그인의 버전을 맞춰보는 유일한 통로다.
    """

    def _version_output(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--version"])
        return caught.exception.code, buf.getvalue().strip()

    def test_exits_zero(self):
        code, _ = self._version_output()
        self.assertEqual(code, 0)

    def test_prints_package_version(self):
        _, text = self._version_output()
        self.assertEqual(text, "lnpl %s" % lnpl.__version__)

    def test_second_field_is_parseable_as_the_version(self):
        # doctor가 `cut -d' ' -f2`로 읽는다. 형식을 테스트로 고정한다.
        _, text = self._version_output()
        self.assertEqual(text.split()[1], lnpl.__version__)

    def test_subcommand_still_required_without_version(self):
        # --version을 추가하면서 서브커맨드 필수성을 잃지 않았는지 확인한다.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit) as caught:
                cli.main([])
        self.assertNotEqual(caught.exception.code, 0)
```

파일 상단 import 블록을 다음으로 바꾼다:

```python
import lnpl
from lnpl import backend, cli
```

- [ ] **Step 2: 실패를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_cli.TestVersionFlag -v 2>&1 | tail -15
```
Expected: FAIL — argparse가 `unrecognized arguments: --version`으로 exit 2를 낸다.

- [ ] **Step 3: 최소 구현**

`impl/lnpl/cli.py`의 `main()`에서 `ArgumentParser` 생성 바로 다음 줄에 추가한다:

```python
def main(argv=None):
    ap = argparse.ArgumentParser(prog="lnpl", description="compile and run LNPL sources")
    ap.add_argument("--version", action="version",
                    version="lnpl %s" % __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
```

파일 상단 import에 다음을 추가한다(기존 상대 import 블록 옆):

```python
from . import __version__
```

- [ ] **Step 4: 테스트 통과를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_cli -v 2>&1 | tail -10
```
Expected: PASS — 기존 CLI 테스트 전부 + 신규 4건.

- [ ] **Step 5: 설치된 스크립트에서도 동작하는지 확인한다**

```bash
mkdir -p .claude/tmp/verchk && python3 -m venv .claude/tmp/verchk/venv && \
.claude/tmp/verchk/venv/bin/pip -q install . && \
.claude/tmp/verchk/venv/bin/lnpl --version; echo "exit=$?"; \
rm -rf .claude/tmp/verchk lnpl.egg-info
```
Expected: `lnpl 0.2.0` / `exit=0`

- [ ] **Step 6: 전체 스위트 무회귀**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl 2>&1 | tail -5
```
Expected: OK

- [ ] **Step 7: 커밋**

```bash
git add impl/lnpl/cli.py impl/tests/test_cli.py
git commit -m "feat(cli): add --version so the plugin can check CLI/plugin version drift

플러그인은 레포에 묶여 커밋 단위로 정합하지만 사용자가 설치한 lnpl은
다른 버전일 수 있다. lnpl-doctor가 비교할 지점을 만든다."
```

## Deliverables
- `impl/lnpl/cli.py` — `--version` 플래그
- `impl/tests/test_cli.py` — `TestVersionFlag` 4건

## Acceptance
1. `lnpl --version` → `lnpl 0.2.0`, exit 0.
2. 서브커맨드 없는 `lnpl` 호출은 여전히 0이 아닌 코드로 끝난다.
3. 출력의 두 번째 필드가 `lnpl.__version__`과 정확히 같다(doctor의 파싱 계약).
4. 전체 스위트 무회귀.
