# Task 06: `lnpl-doctor` 스킬 — 설치·버전 불일치를 진단한다

> 실행자에게: 이 태스크는 `superpowers:subagent-driven-development` 또는
> `superpowers:executing-plans`로 수행한다. 각 Step은 체크박스 단위다.

## Objective
플러그인은 설치됐는데 `lnpl` CLI가 없거나 버전이 어긋난 상태를 사람이 읽을 수 있게
진단한다. 훅이 조용히 죽어 있을 때 사용자가 갈 곳이다(Task 05가 이 스킬 이름을 안내한다).

## Files
- Create: `plugins/lnpl/skills/lnpl-doctor/SKILL.md`
- Create: `plugins/lnpl/scripts/doctor.sh`
- Create: `impl/tests/test_plugin_doctor.py`

## Interfaces
- Consumes: Task 01의 콘솔 스크립트 `lnpl`, Task 02의 `lnpl --version`
  (출력의 두 번째 필드가 버전이라는 계약)
- Produces: `bash plugins/lnpl/scripts/doctor.sh` — 정상이면 exit 0, 문제가 있으면 exit 1

## 설계 결정

`plugin.json`은 **Task 07**에서 만들어진다. doctor는 그 파일이 없어도 동작해야 한다
(없으면 버전 비교만 건너뛴다). 이렇게 두면 Task 순서가 순환하지 않고, 사용자가
플러그인 없이 스크립트만 떼어 써도 동작한다.

## 선행 조건 — `lnpl` 콘솔 스크립트가 venv에 있어야 한다

`run_doctor`는 `<repo>/.venv/bin`을 PATH 앞에 붙이고, `doctor.sh`는 `command -v lnpl`로
CLI를 찾는다. venv에 `jsonschema`만 넣으면 `lnpl`이 없어서 doctor가 "CLI 없음" 분기로
빠지고, 정상 경로 테스트가 실제 원인과 무관하게 실패한다(Task 05에서 실측된 함정).

Step 1 전에 반드시:

```bash
.venv/bin/pip -q install . && ls -l .venv/bin/lnpl
```

## References
- `impl/lnpl/cli.py` — `--version` 출력 형식 `lnpl <version>` (Task 02)
- `impl/lnpl/__init__.py:12` — `__version__`
- `plans/lnpl-plugin/plan.md` A12 — 버전 정합 확인이 필요한 이유

## Steps

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`impl/tests/test_plugin_doctor.py`:

```python
"""lnpl-doctor 스크립트의 계약 테스트.

플러그인은 레포에 묶여 커밋 단위로 정합하지만(A2), 사용자가 설치한 lnpl은
다른 버전일 수 있다. drift가 배포 경계에서 다시 나타나는 유일한 지점이라
여기서만 런타임 검사를 한다.
"""
import json
import os
import shutil
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCTOR = os.path.join(REPO, "plugins", "lnpl", "scripts", "doctor.sh")
SKILL_MD = os.path.join(REPO, "plugins", "lnpl", "skills", "lnpl-doctor", "SKILL.md")
TMP = os.path.join(REPO, ".claude", "tmp", "doctortest")


def run_doctor(env=None, plugin_root=None):
    run_env = dict(os.environ)
    run_env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + run_env["PATH"]
    run_env["PYTHONPATH"] = os.path.join(REPO, "impl")
    run_env["CLAUDE_PLUGIN_ROOT"] = plugin_root or os.path.join(REPO, "plugins", "lnpl")
    if env:
        run_env.update(env)
    return subprocess.run(["bash", DOCTOR], capture_output=True, text=True, env=run_env)


class DoctorTest(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_doctor_script_exists(self):
        self.assertTrue(os.path.isfile(DOCTOR))

    def test_reports_healthy_when_cli_is_present(self):
        proc = run_doctor()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("lnpl", proc.stdout)

    def test_reports_the_installed_version(self):
        import lnpl
        proc = run_doctor()
        self.assertIn(lnpl.__version__, proc.stdout)

    def test_fails_when_cli_is_absent(self):
        proc = run_doctor(env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("pip install", proc.stdout)

    def test_tolerates_a_missing_plugin_json(self):
        # plugin.json은 Task 07 산출물이다. 없어도 죽지 않아야 한다.
        os.makedirs(TMP, exist_ok=True)
        proc = run_doctor(plugin_root=TMP)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_flags_a_version_mismatch(self):
        os.makedirs(os.path.join(TMP, ".claude-plugin"), exist_ok=True)
        with open(os.path.join(TMP, ".claude-plugin", "plugin.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"name": "lnpl", "version": "9.9.9"}, fh)
        proc = run_doctor(plugin_root=TMP)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("9.9.9", proc.stdout)

    def test_passes_when_versions_agree(self):
        import lnpl
        os.makedirs(os.path.join(TMP, ".claude-plugin"), exist_ok=True)
        with open(os.path.join(TMP, ".claude-plugin", "plugin.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"name": "lnpl", "version": lnpl.__version__}, fh)
        proc = run_doctor(plugin_root=TMP)
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_skill_file_exists_and_names_itself(self):
        self.assertTrue(os.path.isfile(SKILL_MD))
        with open(SKILL_MD, encoding="utf-8") as fh:
            head = fh.read(400)
        self.assertIn("name: lnpl-doctor", head)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_plugin_doctor -v 2>&1 | tail -12
```
Expected: FAIL — `doctor.sh`가 없다.

- [ ] **Step 3: `doctor.sh`를 만든다**

`plugins/lnpl/scripts/doctor.sh`:

```bash
#!/usr/bin/env bash
# linkly / lnpl — 설치 상태 진단.
#
# 플러그인 자체는 레포에 묶여 커밋 단위로 정합하지만, 사용자가 설치한 lnpl CLI는
# 다른 버전일 수 있다. drift가 배포 경계에서 다시 나타나는 지점이 여기다.
#
# exit 0 = 정상, exit 1 = 조치가 필요하다.
set -uo pipefail

PROBLEMS=0

echo "lnpl 플러그인 진단"
echo "-------------------"

if command -v lnpl >/dev/null 2>&1; then
  echo "CLI 경로   : $(command -v lnpl)"
else
  echo "CLI 경로   : 없음"
  echo ""
  echo "lnpl CLI가 PATH에 없다. linkly 체크아웃에서 설치하라:"
  echo "    pip install /path/to/linkly"
  echo ""
  echo "설치 없이 쓰려면 레포 안에서:"
  echo "    PYTHONPATH=impl python -m lnpl compile <파일>"
  exit 1
fi

CLI_VERSION=$(lnpl --version 2>/dev/null | awk '{print $2}')
if [ -z "$CLI_VERSION" ]; then
  echo "CLI 버전   : 읽을 수 없음 (--version 미지원 — 구버전이다)"
  echo ""
  echo "설치된 lnpl이 --version을 모른다. 최신 체크아웃으로 재설치하라:"
  echo "    pip install --force-reinstall /path/to/linkly"
  exit 1
fi
echo "CLI 버전   : ${CLI_VERSION}"

PLUGIN_JSON="${CLAUDE_PLUGIN_ROOT:-}/.claude-plugin/plugin.json"
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -f "$PLUGIN_JSON" ]; then
  PLUGIN_VERSION=$(jq -r '.version // empty' "$PLUGIN_JSON" 2>/dev/null)
  echo "플러그인   : ${PLUGIN_VERSION:-알 수 없음}"
  if [ -n "$PLUGIN_VERSION" ] && [ "$PLUGIN_VERSION" != "$CLI_VERSION" ]; then
    echo ""
    echo "버전 불일치: 플러그인 ${PLUGIN_VERSION} vs CLI ${CLI_VERSION}."
    echo "플러그인의 어휘 문서는 ${PLUGIN_VERSION} 시점의 소스에서 생성됐다."
    echo "둘을 맞춰라 — 같은 체크아웃에서 재설치하거나 플러그인을 갱신하라."
    PROBLEMS=1
  fi
else
  echo "플러그인   : plugin.json 없음 (버전 비교 건너뜀)"
fi

# CLI가 실제로 컴파일까지 가는지 본다 — PATH에 있다는 것만으로는 부족하다.
# 프로브는 플러그인 설치 경로가 아니라 사용자 상태 디렉터리에 쓴다(훅의 마커와 같은 곳).
PROBE_DIR="${HOME}/.claude/lnpl-plugin/doctor-probe"
mkdir -p "$PROBE_DIR" 2>/dev/null
PROBE="${PROBE_DIR}/probe.lnpl"
printf 'entity Note\n    field\n        id UUID\n\nworkflow Save\n    validate input\n    create note\n' > "$PROBE" 2>/dev/null
if lnpl compile "$PROBE" >/dev/null 2>&1; then
  echo "컴파일     : 정상"
else
  echo "컴파일     : 실패"
  echo ""
  echo "lnpl이 최소 예제조차 컴파일하지 못한다. 설치가 손상됐다."
  PROBLEMS=1
fi
rm -rf "$PROBE_DIR" 2>/dev/null

echo ""
if [ "$PROBLEMS" -eq 0 ]; then
  echo "이상 없음."
else
  echo "위 항목을 조치하라."
fi
exit "$PROBLEMS"
```

- [ ] **Step 4: 스킬 문서를 쓴다**

`plugins/lnpl/skills/lnpl-doctor/SKILL.md`:

````markdown
---
name: lnpl-doctor
description: Use when the lnpl CLI is missing, the .lnpl diagnostics hook is silent, `lnpl` commands fail, or the plugin and the installed CLI may have drifted apart in version. Diagnoses installation and version mismatch for the linkly platform.
---

# lnpl 설치 진단

플러그인이 설치돼 있어도 `lnpl` CLI가 없으면 진단 훅이 조용히 꺼져 있게 된다.
어휘 문서는 특정 커밋의 소스에서 생성된 산출물이라, CLI 버전이 어긋나면 문서가
실제 동작과 다른 것을 가르칠 수 있다.

## 진단 실행

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/doctor.sh
```

exit 0이면 이상 없음. exit 1이면 출력에 적힌 조치를 그대로 따른다.

## 무엇을 보는가

| 항목 | 문제일 때의 뜻 |
|------|-----------------|
| CLI 경로 | `lnpl`이 PATH에 없다 → 진단 훅이 전부 꺼져 있다 |
| CLI 버전 | `--version`을 모른다 → 구버전 설치다 |
| 플러그인 버전 | CLI와 다르다 → 어휘 문서가 실제 동작과 어긋날 수 있다 |
| 컴파일 | 최소 예제도 실패한다 → 설치가 손상됐다 |

## 설치

linkly 체크아웃에서:

```bash
pip install /path/to/linkly
```

설치 없이 레포 안에서만 쓸 거라면:

```bash
PYTHONPATH=impl python -m lnpl compile <파일>
```

이 경우 `lnpl`이 PATH에 없으므로 진단 훅은 계속 꺼져 있다.
````

- [ ] **Step 5: 실행 권한을 준다**

```bash
chmod +x plugins/lnpl/scripts/doctor.sh
```

- [ ] **Step 6: 테스트 통과를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_plugin_doctor -v 2>&1 | tail -12
```
Expected: PASS (8 tests)

- [ ] **Step 7: 손으로 한 번 돌려본다**

```bash
CLAUDE_PLUGIN_ROOT="$PWD/plugins/lnpl" PATH="$PWD/.venv/bin:$PATH" PYTHONPATH=impl \
  bash plugins/lnpl/scripts/doctor.sh; echo "exit=$?"
```
Expected: CLI 경로·버전·컴파일 정상이 찍히고 `exit=0`.
(이 시점엔 `plugin.json`이 없으므로 "버전 비교 건너뜀"이 정상이다.)

- [ ] **Step 8: 전체 스위트 무회귀**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl 2>&1 | tail -5
```
Expected: OK

- [ ] **Step 9: 커밋**

```bash
git add plugins/lnpl/skills/lnpl-doctor/ plugins/lnpl/scripts/ impl/tests/test_plugin_doctor.py
git commit -m "feat(plugin): add lnpl-doctor for install and version-drift diagnosis

플러그인은 레포에 묶여 정합하지만 사용자가 설치한 CLI는 다를 수 있다.
어휘 문서가 특정 커밋의 산출물이라 버전이 어긋나면 실제 동작과 다른 것을
가르칠 수 있다 — 배포 경계에서만 필요한 런타임 검사다."
```

## Deliverables
- `plugins/lnpl/scripts/doctor.sh` (실행 권한 포함)
- `plugins/lnpl/skills/lnpl-doctor/SKILL.md`
- `impl/tests/test_plugin_doctor.py` — 8건

## Acceptance
1. CLI가 있으면 exit 0이고 경로·버전·컴파일 결과를 출력한다.
2. CLI가 없으면 exit 1이고 `pip install` 안내가 나온다.
3. `plugin.json`이 없어도 죽지 않고 exit 0(비교만 건너뜀).
4. `plugin.json`의 버전이 CLI와 다르면 exit 1이고 양쪽 버전이 출력된다.
5. 두 버전이 같으면 exit 0.
6. 전체 스위트 무회귀.
