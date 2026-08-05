# Task 05: `.lnpl` 저장 직후 진단을 모델에게 되돌리는 훅

> 실행자에게: 이 태스크는 `superpowers:subagent-driven-development` 또는
> `superpowers:executing-plans`로 수행한다. 각 Step은 체크박스 단위다.

## Objective
`*.lnpl`을 Write/Edit한 직후 `lnpl compile`을 돌리고, 진단이 있으면 모델에게
전달한다. 조용히 실패하는 언어를 즉시 피드백 언어로 바꾸는 단일 최대 가치 부품이다.

## Files
- Create: `plugins/lnpl/hooks/hooks.json`
- Create: `plugins/lnpl/hooks/lnpl-diagnostics.sh`
- Create: `impl/tests/test_plugin_hook.py`

## Interfaces
- Consumes: Task 01의 콘솔 스크립트 `lnpl`; Task 04의 `lnpl-doctor` 스킬 이름(안내 문구에만)
- Produces: `plugins/lnpl/hooks/hooks.json` — Task 07의 플러그인 루트가 담는다

## 사전 확인된 사실 (전부 이번 조사에서 직접 실행함)

| 사실 | 확인 결과 |
|------|-----------|
| 훅 입력은 stdin JSON | `INPUT=$(cat)` 후 `jq -r '.tool_input.file_path'` — groundwork/guardrails가 쓰는 계약 |
| PostToolUse 출력 규칙 | exit 0 = 조용, **exit 2 = stderr가 모델에게 전달** |
| exit 2가 쓰기를 되돌리지 않음 | PostToolUse는 도구 실행 **후**에 돈다 → A6(차단 안 함)과 정합 |
| 진단은 stderr, 종료 코드는 0 | `compile examples/shorten.lnpl` → `rc=0`, stderr 3 warnings |
| 진단 없는 소스는 stderr가 빈다 | entity+workflow만 있는 최소 소스 → `rc=0`, stderr `[]` |
| 예약어는 exit 2 | `if` 사용 → `rc=2`, `compile error: line 6: 'if' is reserved …` |
| stderr만 캡처하는 관용구 | `OUT=$(lnpl compile "$F" 2>&1 >/dev/null)` — 순서가 중요하다 |

**레포의 어떤 `examples/*.lnpl`도 진단 0건이 아니다**(셋 다 경고를 낸다). 그래서
"깨끗한 파일 → exit 0" 테스트는 소스를 직접 만들어야 한다.

## Steps

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`impl/tests/test_plugin_hook.py`:

```python
"""PostToolUse 진단 훅의 계약 테스트.

훅은 stdin으로 JSON을 받고, `.lnpl`일 때만 컴파일하고, 진단이 있으면
exit 2 + stderr로 모델에게 되돌린다. `lnpl`이 없으면 사용자 워크플로를
깨지 않는다(세션당 한 번만 안내).
"""
import json
import os
import shutil
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "plugins", "lnpl", "hooks", "lnpl-diagnostics.sh")
TMP = os.path.join(REPO, ".claude", "tmp", "hooktest")

CLEAN = ("entity Note\n    field\n        id UUID\n\n"
         "workflow Save\n    validate input\n    create note\n")
NOISY = ("entity Note\n    field\n        id UUID\n\n"
         "workflow Save\n    validate input\n    return note\n")
BROKEN = ("entity Note\n    field\n        id UUID\n\n"
          "workflow Save\n    if something\n")


def write(name, text):
    os.makedirs(TMP, exist_ok=True)
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def run_hook(file_path, session="s1", env=None):
    payload = json.dumps({"session_id": session, "cwd": REPO,
                          "hook_event_name": "PostToolUse", "tool_name": "Write",
                          "tool_input": {"file_path": file_path}})
    run_env = dict(os.environ)
    # 설치 없이도 `lnpl`이 잡히도록 venv의 bin을 앞에 둔다.
    run_env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + run_env["PATH"]
    run_env["PYTHONPATH"] = os.path.join(REPO, "impl")
    if env:
        run_env.update(env)
    return subprocess.run(["bash", HOOK], input=payload, capture_output=True,
                          text=True, env=run_env)


class DiagnosticsHookTest(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_hook_script_exists(self):
        self.assertTrue(os.path.isfile(HOOK))

    def test_ignores_non_lnpl_files(self):
        path = write("notes.md", "# hello")
        proc = run_hook(path)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr.strip(), "")

    def test_ignores_missing_file_path(self):
        proc = subprocess.run(["bash", HOOK], input=json.dumps({"tool_name": "Write"}),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)

    def test_ignores_a_path_that_does_not_exist(self):
        proc = run_hook(os.path.join(TMP, "ghost.lnpl"))
        self.assertEqual(proc.returncode, 0)

    def test_silent_on_a_clean_source(self):
        proc = run_hook(write("clean.lnpl", CLEAN))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr.strip(), "")

    def test_reports_unknown_verb_back_to_the_model(self):
        proc = run_hook(write("noisy.lnpl", NOISY))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown-verb", proc.stderr)
        self.assertIn("return", proc.stderr)

    def test_reports_a_compile_error(self):
        proc = run_hook(write("broken.lnpl", BROKEN))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("reserved", proc.stderr)

    def test_golden_shorten_example_surfaces_its_three_warnings(self):
        # 계획서 수용 기준 4. 합성 파일이 아니라 레포가 커밋한 실제 소스로
        # 확인한다 — shorten.lnpl은 세 가지 증상을 의도적으로 보존한 교보재다.
        proc = run_hook(os.path.join(REPO, "examples", "shorten.lnpl"))
        self.assertEqual(proc.returncode, 2)
        for code in ("declared-not-enforced", "declared-measured-only",
                     "unknown-verb"):
            self.assertIn(code, proc.stderr)

    def test_missing_cli_notifies_once_then_stays_quiet(self):
        marker_home = os.path.join(TMP, "home")
        os.makedirs(marker_home, exist_ok=True)
        path = write("clean.lnpl", CLEAN)
        # PATH에서 lnpl을 제거하고, 마커가 쌓일 HOME도 격리한다.
        stripped = {"PATH": "/usr/bin:/bin", "HOME": marker_home}
        first = run_hook(path, session="missing-cli", env=stripped)
        self.assertEqual(first.returncode, 2)
        self.assertIn("lnpl-doctor", first.stderr)
        second = run_hook(path, session="missing-cli", env=stripped)
        self.assertEqual(second.returncode, 0,
                         "같은 세션에서 두 번째 안내가 나가면 소음이다")

    def test_missing_cli_notifies_again_in_a_different_session(self):
        marker_home = os.path.join(TMP, "home2")
        os.makedirs(marker_home, exist_ok=True)
        path = write("clean.lnpl", CLEAN)
        stripped = {"PATH": "/usr/bin:/bin", "HOME": marker_home}
        run_hook(path, session="sess-a", env=stripped)
        other = run_hook(path, session="sess-b", env=stripped)
        self.assertEqual(other.returncode, 2)

    def test_hooks_json_wires_write_and_edit(self):
        with open(os.path.join(REPO, "plugins", "lnpl", "hooks", "hooks.json"),
                  encoding="utf-8") as fh:
            cfg = json.load(fh)
        entries = cfg["hooks"]["PostToolUse"]
        self.assertEqual(entries[0]["matcher"], "Write|Edit")
        command = entries[0]["hooks"][0]["command"]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", command)
        self.assertIn("lnpl-diagnostics.sh", command)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_plugin_hook -v 2>&1 | tail -12
```
Expected: FAIL — 훅 스크립트가 없다.

- [ ] **Step 3: 훅 스크립트를 만든다**

`plugins/lnpl/hooks/lnpl-diagnostics.sh`:

```bash
#!/usr/bin/env bash
# linkly / lnpl — PostToolUse 진단 훅.
#
# `.lnpl`을 Write/Edit한 직후 `lnpl compile`을 돌리고 진단을 모델에게 되돌린다.
#
# 왜 필요한가: `lnpl compile`은 진단을 stderr로 내보내고 **종료 코드 0**으로
# 끝난다. 즉 아무도 보지 않으면 사라진다. 사전에 없는 동사는 에러가 아니라
# 효과 없는 no-op이고(issue #36), 선언 중 상당수는 집행되지 않는다(issue #38).
# 그 사실이 작성 시점에 보이지 않으면 리뷰 때까지 아무도 모른다.
#
# 계약:
#   exit 0 — 조용. exit 2 — stderr가 모델에게 전달된다.
#   PostToolUse는 도구 실행 뒤에 돌기 때문에 exit 2가 쓰기를 되돌리지 않는다.
set -uo pipefail

INPUT=$(cat)

FILE=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -n "$FILE" ] || exit 0
case "$FILE" in
  *.lnpl) ;;
  *) exit 0 ;;
esac
[ -f "$FILE" ] || exit 0

# `lnpl`이 없으면 사용자 워크플로를 깨지 않는다. 다만 세션당 한 번은 알린다 —
# 훅이 조용히 죽어 있으면 플러그인이 설치된 줄 알면서 아무 보호도 못 받는다.
if ! command -v lnpl >/dev/null 2>&1; then
  SESSION=$(printf '%s' "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null)
  MARK_DIR="${HOME}/.claude/lnpl-plugin"
  MARK="${MARK_DIR}/notified-${SESSION}"
  [ -e "$MARK" ] && exit 0
  mkdir -p "$MARK_DIR" 2>/dev/null && : > "$MARK" 2>/dev/null
  echo "lnpl CLI가 PATH에 없어 .lnpl 진단을 건너뛰었다. \`lnpl-doctor\` 스킬로 진단하라." >&2
  exit 2
fi

# stdout(IR)은 버리고 stderr(진단)만 잡는다. 리디렉션 순서가 중요하다.
OUT=$(lnpl compile "$FILE" 2>&1 >/dev/null)
RC=$?

if [ "$RC" -ne 0 ]; then
  {
    echo "\`$FILE\`이 컴파일되지 않는다:"
    echo "$OUT"
  } >&2
  exit 2
fi

if [ -n "$OUT" ]; then
  {
    echo "\`$FILE\` 진단:"
    echo "$OUT"
    echo ""
    echo "각 항목이 의도한 것인지 확인하라. unknown-verb는 그 스텝이 아무 효과도"
    echo "내지 않는다는 뜻이고, declared-not-enforced는 선언이 실행을 바꾸지"
    echo "않는다는 뜻이다. 어휘는 \`lnpl-authoring\` 스킬의 references/를 본다."
  } >&2
  exit 2
fi

exit 0
```

- [ ] **Step 4: `hooks.json`을 만든다**

`plugins/lnpl/hooks/hooks.json`:

```json
{
  "description": "lnpl 진단 훅 — .lnpl을 Write/Edit한 직후 컴파일 진단을 모델에게 되돌린다.",
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/lnpl-diagnostics.sh",
            "timeout": 20
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 5: 실행 권한을 준다**

```bash
chmod +x plugins/lnpl/hooks/lnpl-diagnostics.sh
```

- [ ] **Step 6: 테스트 통과를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_plugin_hook -v 2>&1 | tail -15
```
Expected: PASS (11 tests)

- [ ] **Step 7: 훅을 손으로 한 번 구동한다**

```bash
mkdir -p .claude/tmp/hookdemo && \
printf 'entity Note\n    field\n        id UUID\n\nworkflow Save\n    validate input\n    return note\n' \
  > .claude/tmp/hookdemo/demo.lnpl && \
printf '{"session_id":"demo","tool_name":"Write","tool_input":{"file_path":"%s/.claude/tmp/hookdemo/demo.lnpl"}}' "$PWD" \
  | PATH="$PWD/.venv/bin:$PATH" PYTHONPATH=impl bash plugins/lnpl/hooks/lnpl-diagnostics.sh; \
echo "exit=$?"; rm -rf .claude/tmp/hookdemo
```

Expected: `demo.lnpl 진단:` 과 `unknown-verb ... return` 이 보이고 `exit=2`.

- [ ] **Step 8: 전체 스위트 무회귀**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl 2>&1 | tail -5
```
Expected: OK

- [ ] **Step 9: 커밋**

```bash
git add plugins/lnpl/hooks/ impl/tests/test_plugin_hook.py
git commit -m "feat(plugin): surface lnpl compile diagnostics at write time

lnpl compile은 진단을 stderr로 내보내고 종료 코드 0으로 끝난다 — 아무도
보지 않으면 사라진다. 사전에 없는 동사는 no-op이고(#36) 선언 상당수는
집행되지 않는데(#38), 그 사실이 작성 시점에 보이지 않으면 리뷰까지 아무도
모른다. PostToolUse는 쓰기 뒤에 돌기 때문에 exit 2가 편집을 되돌리지 않는다."
```

## Deliverables
- `plugins/lnpl/hooks/lnpl-diagnostics.sh` (실행 권한 포함)
- `plugins/lnpl/hooks/hooks.json`
- `impl/tests/test_plugin_hook.py` — 11건

## Acceptance
1. `.lnpl`이 아닌 파일, 없는 경로, 빈 `file_path`에서 exit 0 + 무출력.
2. 진단 0건인 소스에서 exit 0 + 무출력.
3. `return` 같은 미등록 동사가 있으면 exit 2이고 stderr에 `unknown-verb`가 실린다.
   커밋된 `examples/shorten.lnpl`로도 세 진단 코드가 전부 표면화된다(계획서 수용 기준 4).
4. 예약어 등 컴파일 오류는 exit 2이고 stderr에 원인이 실린다.
5. `lnpl`이 PATH에 없으면 **세션당 한 번만** exit 2로 안내하고, 같은 세션의 두 번째
   호출부터는 exit 0. 다른 세션에서는 다시 안내한다.
6. `hooks.json`이 `Write|Edit`을 매칭하고 `${CLAUDE_PLUGIN_ROOT}`로 경로를 잡는다.
7. 전체 스위트 무회귀.