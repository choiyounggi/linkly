"""`.github/workflows/_ai-gate.yml`의 `runner` 입력과 generic-http 갈래 (issue #252).

GitHub Actions는 로컬에서 돌릴 수 없으므로, 바뀐 스텝의 `run:` 블록을 워크플로
파일에서 그대로 잘라 러너와 같은 `bash -e`로 실행하고, 임시 `GITHUB_OUTPUT` 파일에
남은 내용과 stdout을 단언한다 — 부분 문자열 검사는 줄이 `if` 밖으로 옮겨져도 초록이다.
배선(스텝 순서, `if:` 조건, 시크릿 전달)만 텍스트로 고정한다.

claude-code 갈래(기본값)는 오늘과 같은 출력을 내야 한다: 비교 기준 문구는
`orch/prereq-1022`(b1cd523)의 `_ai-gate.yml`에서 그대로 옮겨 왔다.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from http.server import ThreadingHTTPServer

from tests.test_ai_gate_http_runner import DIFF, PROMPT, VERDICT, _ScriptedHandler, ok_reply

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOWS = os.path.join(REPO, ".github", "workflows")
REUSABLE = os.path.join(WORKFLOWS, "_ai-gate.yml")
CALLERS = (os.path.join(WORKFLOWS, "ai-gates.yml"),
           os.path.join(WORKFLOWS, "ai-gates-quality.yml"))

GROUP_LINE = ("  group: ai-gate-${{ inputs.gate_name }}-${{ github.event.pull_request.number }}"
              "${{ inputs.runner != 'claude-code' && format('-{0}', inputs.runner) || '' }}")
KEY = "sk-test-AAAA"
VALID = ('{"gate": "rfc-conformance", "verdict": "pass", "examined": {"files": '
         '["rfcs/0001-example.md"], "note": "synthetic fixture"}, "findings": []}')

# b1cd523 `_ai-gate.yml` l.130 / l.133 (`[$GATE_NAME]` → `[rfc-conformance]`).
MISSING_BLOCKING = ("::error::[rfc-conformance] ANTHROPIC_API_KEY가 없어 게이트를 실행하지 "
                    "못했다 — blocking 게이트이므로 잡을 실패시킨다. docs/CI-GATES.md의 "
                    "시크릿 등록 절차를 보라.")
MISSING_ADVISORY = ("::warning::[rfc-conformance] ANTHROPIC_API_KEY가 없어 이 게이트는 "
                    "실행되지 않았다. 이 잡의 초록불은 '검토했고 문제없음'이 아니라 "
                    "'검토하지 않음'을 뜻한다 — advisory이므로 머지는 막지 않는다.")
# b1cd523 `_ai-gate.yml` l.327 / l.330.
UNAVAILABLE_BLOCKING = ("::error::게이트를 실행하지 못했다(Claude Code 액션 실패 또는 빈 출력) "
                        "— blocking 게이트이므로 잡을 실패시킨다. 원인이 Anthropic API "
                        "5xx/rate-limit 같은 일시 장애라면 재실행(re-run)하라.")
UNAVAILABLE_ADVISORY = ("::warning::게이트를 실행하지 못했다(Claude Code 액션 실패 또는 빈 출력) "
                        "— advisory이므로 잡은 초록불로 남는다. 원인이 일시 장애라면 "
                        "재실행으로 충분하다.")
EMPTY_BLOCKING = ("::error::[test-quality] 변경 파일 0건(삭제 3건) — 게이트가 판정할 수 없다. "
                  "blocking 게이트이므로 잡을 실패시킨다. 삭제만 있는 PR은 skip-ai-gate "
                  "라벨(사유를 PR 본문에)로 우회한다.")
EMPTY_ADVISORY = ("::warning::[prose-factcheck] 변경 파일 0건(삭제 0건) — 이 게이트는 판정하지 "
                  "않았다. 이 잡의 초록불은 '검토하지 않음'을 뜻한다 — advisory이므로 머지는 "
                  "막지 않는다.")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _step_text(marker):
    """`marker` 줄을 담은 스텝 하나의 원문. marker는 파일에 정확히 한 번 있어야 한다."""
    text = _read(REUSABLE)
    if text.count(marker) != 1:
        raise AssertionError("%r occurs %d times in _ai-gate.yml" % (marker, text.count(marker)))
    # marker가 스텝의 `- name:` 줄 자체일 수도 있으므로 그 줄의 시작부터 찾는다.
    line = text.rfind("\n", 0, text.index(marker))
    start = (line if text.startswith("\n      - name:", line)
             else text.rfind("\n      - name:", 0, line))
    end = text.find("\n      - name:", line + 1)
    return text[start:] if end == -1 else text[start:end]


def _run_block(marker):
    step = _step_text(marker)
    head = "\n        run: |\n"
    lines = step[step.index(head) + len(head):].split("\n")
    body = []
    for line in lines:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line)
    while body and not body[-1].strip():
        body.pop()
    return textwrap.dedent("\n".join(body) + "\n")


def _env_lines(marker):
    """스텝의 `env:` 블록 줄(들여쓰기 포함) 목록."""
    step = _step_text(marker)
    head = "\n        env:\n"
    lines = []
    for line in step[step.index(head) + len(head):].split("\n"):
        if not line.startswith(" " * 10):
            break
        lines.append(line)
    return lines


# 러너가 직접 넣어 주는 환경변수 — 스텝 env에 선언하지 않는다.
RUNNER_PROVIDED = {"GITHUB_OUTPUT", "RUNNER_TEMP"}

# 이 태스크가 바꾸거나 새로 만든 스텝의 env 블록 전체(issue #252). claude-code 쪽 (issue #244: 변경 파일 없음 처리)
# 줄은 b1cd523의 `_ai-gate.yml`과 같은 것이다.
STEP_ENV = {
    "id: check_secret": [
        "          ANTHROPIC_API_KEY: ${{ secrets.anthropic_api_key }}",
        "          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.claude_code_oauth_token }}",
        "          RUNNER: ${{ inputs.runner }}",
        "          AI_GATE_HTTP_API_KEY: ${{ secrets.ai_gate_http_api_key }}",
    ],
    "name: 시크릿 부재 처리": [
        "          BLOCKING: ${{ inputs.blocking }}",
        "          GATE_NAME: ${{ inputs.gate_name }}",
        "          MISSING_SECRET: ${{ inputs.runner == 'generic-http' && "
        "'AI_GATE_HTTP_API_KEY' || 'ANTHROPIC_API_KEY' }}",
    ],
    "name: 변경 파일 없음 처리": [
        "          BLOCKING: ${{ inputs.blocking }}",
        "          GATE_NAME: ${{ inputs.gate_name }}",
        "          DELETED: ${{ steps.changed_files.outputs.deleted }}",
    ],
    "id: http_inputs": [
        "          BASE_SHA: ${{ github.event.pull_request.base.sha }}",
        "          HEAD_SHA: ${{ github.event.pull_request.head.sha }}",
        "          PROMPT_TEXT: ${{ steps.build_prompt.outputs.text }}",
    ],
    "id: http_runner": [
        "          AI_GATE_HTTP_API_KEY: ${{ secrets.ai_gate_http_api_key }}",
        "          BASE_URL: ${{ inputs.http_base_url }}",
        "          MODEL: ${{ inputs.http_model }}",
        "          API_STYLE: ${{ inputs.http_api_style }}",
        "          GATE_NAME: ${{ inputs.gate_name }}",
    ],
    "id: verdict": [
        "          GATE_NAME: ${{ inputs.gate_name }}",
        "          EXPECT_NONEMPTY: ${{ inputs.expect_nonempty }}",
        "          CLAUDE_OUTCOME: ${{ steps.claude.outcome }}",
        "          STRUCTURED_OUTPUT: ${{ steps.claude.outputs.structured_output }}",
        "          RUNNER: ${{ inputs.runner }}",
        "          HTTP_OUTCOME: ${{ steps.http_runner.outcome }}",
        "          HTTP_VERDICT_FILE: ${{ runner.temp }}/ai-gate-verdict.json",
    ],
    "name: 판정 반영": [
        "          VERDICT_CODE: ${{ steps.verdict.outputs.code }}",
        "          BLOCKING: ${{ inputs.blocking }}",
        "          RUNNER_LABEL: ${{ inputs.runner == 'generic-http' && "
        "'generic-http 러너' || 'Claude Code 액션' }}",
        "          PROVIDER_LABEL: ${{ inputs.runner == 'generic-http' && "
        "'모델 엔드포인트' || 'Anthropic API' }}",
    ],
}


def _scratch():
    base = os.path.join(REPO, ".claude", "tmp")
    os.makedirs(base, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix="lnpl-t252-", dir=base)


def _exec(script, env, cwd=None):
    """러너와 같은 `bash -e`로 실행하고 (proc, GITHUB_OUTPUT 내용)을 돌려준다."""
    with _scratch() as box:
        out = os.path.join(box, "github_output")
        open(out, "w").close()
        # 러너(ubuntu)의 로캘. bash 5는 UTF-8 로캘에서 `$NAME가`의 한글까지 변수명으로 읽는다.
        full = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": out, "LANG": "C.UTF-8"}
        full.update(env)
        proc = subprocess.run(["bash", "-e", "-c", script], env=full, cwd=cwd,
                              capture_output=True, text=True)
        return proc, _read(out)


class ParseAndInputTest(unittest.TestCase):

    def test_all_three_workflows_parse(self):
        paths = (REUSABLE,) + CALLERS
        try:
            import yaml
        except ImportError:
            yaml = None
        if yaml is not None:
            for path in paths:
                with self.subTest(parser="PyYAML", path=os.path.basename(path)):
                    self.assertIsInstance(yaml.safe_load(_read(path)), dict)
        elif shutil.which("ruby"):
            for path in paths:
                proc = subprocess.run(["ruby", "-ryaml", "-e", "YAML.load_file(ARGV[0])", path],
                                      capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
        else:
            self.skipTest("neither PyYAML nor ruby available")

    def test_runner_input_defaults_to_claude_code(self):
        text = _read(REUSABLE)
        piece = text[text.index("      runner:"):text.index("      http_base_url:")]
        self.assertIn("default: claude-code", piece)
        self.assertIn("type: string", piece)

    def test_new_inputs_and_secret_are_optional(self):
        # 리뷰 r2 재감사 #3 항목 1: 기존 claude-code 호출부 4개는 이 값들을 넘기지
        # 않는다 — 하나라도 required: true가 되면 GitHub가 호출 자체를 거부한다.
        text = _read(REUSABLE)
        nxt = re.compile(r"^(      [a-z_]+:|    secrets:|[a-z]+:)$", re.MULTILINE)
        for key in ("runner", "http_base_url", "http_model", "http_api_style",
                    "ai_gate_http_api_key"):
            with self.subTest(key=key):
                anchor = "\n      %s:\n" % key
                self.assertEqual(text.count(anchor), 1)
                start = text.index(anchor) + len(anchor)
                piece = text[start:nxt.search(text, start).start()]
                self.assertIn("        required: false\n", piece)
                self.assertNotIn("required: true", piece)

    def test_concurrency_group_keeps_the_claude_name_and_suffixes_other_runners(self):
        self.assertIn(GROUP_LINE + "\n", _read(REUSABLE))


class CheckSecretTest(unittest.TestCase):

    def run_check(self, **env):
        return _exec(_run_block("id: check_secret"), env)

    def test_claude_code_without_credentials_skips(self):
        proc, out = self.run_check(RUNNER="claude-code", ANTHROPIC_API_KEY="",
                                   CLAUDE_CODE_OAUTH_TOKEN="")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(out, "skip=true\n")
        self.assertIn("SKIPPED: neither ANTHROPIC_API_KEY nor CLAUDE_CODE_OAUTH_TOKEN is "
                      "configured", proc.stdout)

    def test_claude_code_with_an_api_key_runs(self):
        proc, out = self.run_check(RUNNER="claude-code", ANTHROPIC_API_KEY="x")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(out, "skip=false\n")

    def test_claude_code_ignores_the_http_key(self):
        proc, out = self.run_check(RUNNER="claude-code", AI_GATE_HTTP_API_KEY=KEY)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(out, "skip=true\n")

    def test_generic_http_without_its_key_skips_even_with_anthropic_credentials(self):
        proc, out = self.run_check(RUNNER="generic-http", AI_GATE_HTTP_API_KEY="",
                                   ANTHROPIC_API_KEY="x")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(out, "skip=true\n")
        self.assertIn("SKIPPED: AI_GATE_HTTP_API_KEY is not configured", proc.stdout)

    def test_generic_http_with_its_key_runs_and_prints_only_the_length(self):
        proc, out = self.run_check(RUNNER="generic-http", AI_GATE_HTTP_API_KEY=KEY)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(out, "skip=false\n")
        self.assertIn("credential length: 12", proc.stdout)
        self.assertNotIn(KEY, proc.stdout)

    def test_unknown_runner_fails_the_step(self):
        proc, out = self.run_check(RUNNER="foo", ANTHROPIC_API_KEY="x")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("::error::unknown runner: foo", proc.stdout)
        self.assertEqual(out, "")


class MissingSecretTest(unittest.TestCase):

    def run_missing(self, **env):
        return _exec(_run_block("name: 시크릿 부재 처리"),
                     dict(GATE_NAME="rfc-conformance", **env))

    def test_claude_code_advisory_text_is_unchanged(self):
        proc, _ = self.run_missing(MISSING_SECRET="ANTHROPIC_API_KEY", BLOCKING="false")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, MISSING_ADVISORY + "\n")

    def test_claude_code_blocking_text_is_unchanged_and_fails(self):
        proc, _ = self.run_missing(MISSING_SECRET="ANTHROPIC_API_KEY", BLOCKING="true")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, MISSING_BLOCKING + "\n")

    def test_generic_http_names_its_own_secret(self):
        proc, _ = self.run_missing(MISSING_SECRET="AI_GATE_HTTP_API_KEY", BLOCKING="false")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("AI_GATE_HTTP_API_KEY가 없어", proc.stdout)


class VerdictTest(unittest.TestCase):
    """`판정` 스텝 — 두 러너가 같은 판정 스크립트 호출로 모인다."""

    def run_verdict(self, verdict_text=None, **env):
        with _scratch() as cwd:
            os.symlink(os.path.join(REPO, "scripts"), os.path.join(cwd, "scripts"))
            os.symlink(os.path.join(REPO, "schemas"), os.path.join(cwd, "schemas"))
            verdict_file = os.path.join(cwd, "ai-gate-verdict.json")
            if verdict_text is not None:
                with open(verdict_file, "w", encoding="utf-8") as fh:
                    fh.write(verdict_text)
            full = {"PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"],
                    "GATE_NAME": "rfc-conformance", "EXPECT_NONEMPTY": "true",
                    "HTTP_VERDICT_FILE": verdict_file}
            full.update(env)
            return _exec(_run_block("id: verdict"), full, cwd=cwd)

    def test_generic_http_failure_is_unavailable_even_if_claude_outputs_exist(self):
        proc, out = self.run_verdict(VALID, RUNNER="generic-http", HTTP_OUTCOME="failure",
                                     CLAUDE_OUTCOME="success", STRUCTURED_OUTPUT=VALID)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(out, "code=unavailable\n")

    def test_generic_http_success_without_a_verdict_file_is_unavailable(self):
        proc, out = self.run_verdict(None, RUNNER="generic-http", HTTP_OUTCOME="success",
                                     CLAUDE_OUTCOME="success", STRUCTURED_OUTPUT=VALID)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(out, "code=unavailable\n")

    def test_generic_http_pass_verdict_is_code_0(self):
        proc, out = self.run_verdict(VALID, RUNNER="generic-http", HTTP_OUTCOME="success")
        self.assertEqual(out, "code=0\n", proc.stdout + proc.stderr)

    def test_generic_http_fail_verdict_is_code_1(self):
        proc, out = self.run_verdict(VALID.replace('"pass"', '"fail"'),
                                     RUNNER="generic-http", HTTP_OUTCOME="success")
        self.assertEqual(out, "code=1\n", proc.stdout + proc.stderr)

    def test_generic_http_wrong_gate_is_code_2(self):
        proc, out = self.run_verdict(VALID.replace('"rfc-conformance"', '"other-gate"'),
                                     RUNNER="generic-http", HTTP_OUTCOME="success")
        self.assertEqual(out, "code=2\n", proc.stdout + proc.stderr)

    def test_claude_code_failure_message_is_unchanged(self):
        proc, out = self.run_verdict(None, RUNNER="claude-code", CLAUDE_OUTCOME="failure",
                                     STRUCTURED_OUTPUT="")
        self.assertEqual(out, "code=unavailable\n")
        self.assertIn("게이트를 실행하지 못했다(claude 스텝 outcome=failure, structured_output "
                      "길이=0)", proc.stdout)

    def test_claude_code_pass_is_code_0(self):
        proc, out = self.run_verdict(None, RUNNER="claude-code", CLAUDE_OUTCOME="success",
                                     STRUCTURED_OUTPUT=VALID)
        self.assertEqual(out, "code=0\n", proc.stdout + proc.stderr)


class VerdictReportTest(unittest.TestCase):
    """`판정 반영`의 unavailable 문구 — claude-code에서는 오늘 문구 그대로."""

    def run_report(self, **env):
        return _exec(_run_block("name: 판정 반영"), dict(VERDICT_CODE="unavailable", **env))

    def test_claude_code_advisory_text_is_unchanged(self):
        proc, _ = self.run_report(BLOCKING="false", RUNNER_LABEL="Claude Code 액션",
                                  PROVIDER_LABEL="Anthropic API")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, UNAVAILABLE_ADVISORY + "\n")

    def test_claude_code_blocking_text_is_unchanged(self):
        proc, _ = self.run_report(BLOCKING="true", RUNNER_LABEL="Claude Code 액션",
                                  PROVIDER_LABEL="Anthropic API")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, UNAVAILABLE_BLOCKING + "\n")

    def test_generic_http_labels_are_rendered(self):
        proc, _ = self.run_report(BLOCKING="true", RUNNER_LABEL="generic-http 러너",
                                  PROVIDER_LABEL="모델 엔드포인트")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("generic-http 러너", proc.stdout)
        self.assertIn("모델 엔드포인트", proc.stdout)


class HttpRunnerStepTest(unittest.TestCase):
    """`generic-http 게이트 실행` 스텝의 run 블록을 그대로 실행한다 — 리뷰 r2 재감사:
    플래그·스크립트 경로·스키마 경로가 틀려도 테스트는 초록이고 CI에서는 매번
    unavailable(advisory면 초록)이었다."""

    def start(self):
        handler = type("_Scripted", (_ScriptedHandler,), {"script": [ok_reply()], "calls": []})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            thread.join()
            server.server_close()

        self.addCleanup(stop)
        host, port = server.server_address
        return "http://%s:%d/v1" % (host, port), handler.calls

    def invoke(self, api_style):
        """run 블록을 실행하고 (proc, 판정 파일 내용, 기록된 요청들)을 돌려준다. 모델·게이트
        값은 일부러 픽스처(fake-model, rfc-conformance)와 다르게 준다 — 그래야 run
        블록에 값이 하드코딩되면 드러난다(리뷰 r2 재감사 #3 항목 5)."""
        url, calls = self.start()
        with _scratch() as box:
            checkout = os.path.join(box, "checkout")
            temp = os.path.join(box, "runner_temp")
            os.makedirs(checkout)
            os.makedirs(temp)
            os.symlink(os.path.join(REPO, "scripts"), os.path.join(checkout, "scripts"))
            os.symlink(os.path.join(REPO, "schemas"), os.path.join(checkout, "schemas"))
            with open(os.path.join(temp, "ai-gate-prompt.txt"), "w", encoding="utf-8") as fh:
                fh.write(PROMPT)
            with open(os.path.join(temp, "ai-gate.diff"), "wb") as fh:
                fh.write(DIFF)
            env = {"PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"],
                   "AI_GATE_HTTP_API_KEY": KEY, "BASE_URL": url, "MODEL": "step-model",
                   "API_STYLE": api_style, "GATE_NAME": "golden-approval", "RUNNER_TEMP": temp}
            proc, _ = _exec(_run_block("id: http_runner"), env, cwd=checkout)
            path = os.path.join(temp, "ai-gate-verdict.json")
            verdict = _read(path) if os.path.exists(path) else None
        return proc, verdict, calls

    def test_the_step_sends_the_configured_model_and_gate(self):
        proc, verdict, calls = self.invoke("")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(verdict), VERDICT)
        self.assertNotIn(KEY, proc.stdout + proc.stderr)
        self.assertEqual(len(calls), 1)
        body = calls[0]["body"]
        self.assertEqual(body["model"], "step-model")
        self.assertIn('"gate" field must be "golden-approval"', body["messages"][0]["content"])
        self.assertEqual((body["max_tokens"], body["temperature"]), (16384, 0))  # 빈 값 → classic

    def test_the_step_passes_the_reasoning_api_style_through(self):
        # 항목 3: `--api-style classic`으로 하드코딩되면 reasoning 엔드포인트가 400을 낸다.
        proc, verdict, calls = self.invoke("reasoning")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(verdict), VERDICT)
        body = calls[0]["body"]
        self.assertEqual(body.get("max_completion_tokens"), 32768, body)
        self.assertNotIn("max_tokens", body)
        self.assertNotIn("temperature", body)

    def test_the_workflow_invocation_writes_the_verdict_file(self):
        url, calls = self.start()
        with _scratch() as box:
            checkout = os.path.join(box, "checkout")
            temp = os.path.join(box, "runner_temp")
            os.makedirs(checkout)
            os.makedirs(temp)
            os.symlink(os.path.join(REPO, "scripts"), os.path.join(checkout, "scripts"))
            os.symlink(os.path.join(REPO, "schemas"), os.path.join(checkout, "schemas"))
            with open(os.path.join(temp, "ai-gate-prompt.txt"), "w", encoding="utf-8") as fh:
                fh.write(PROMPT)
            with open(os.path.join(temp, "ai-gate.diff"), "wb") as fh:
                fh.write(DIFF)
            env = {"PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"],
                   "AI_GATE_HTTP_API_KEY": KEY, "BASE_URL": url, "MODEL": "fake-model",
                   "API_STYLE": "", "GATE_NAME": "rfc-conformance", "RUNNER_TEMP": temp}
            proc, _ = _exec(_run_block("id: http_runner"), env, cwd=checkout)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(json.loads(_read(os.path.join(temp, "ai-gate-verdict.json"))),
                             VERDICT)
        self.assertNotIn(KEY, proc.stdout + proc.stderr)
        self.assertEqual(len(calls), 1)
        body = calls[0]["body"]
        self.assertEqual(body["model"], "fake-model")
        self.assertEqual(body["max_tokens"], 16384)  # API_STYLE 비어 있음 → classic
        self.assertIn('"gate" field must be "rfc-conformance"', body["messages"][0]["content"])
        self.assertIn("GATE PROMPT MARKER", body["messages"][1]["content"])
        self.assertIn("diff --git a/rfcs/0001-example.md", body["messages"][1]["content"])


class HttpInputsTest(unittest.TestCase):

    def test_prompt_and_diff_are_written_to_runner_temp(self):
        git_env = {"PATH": os.environ["PATH"], "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_CONFIG_GLOBAL": os.devnull}

        def git(*args):
            return subprocess.run(["git", "-c", "user.name=t252", "-c",
                                   "user.email=t252@example.invalid", *args], cwd=repo,
                                  env=git_env, capture_output=True, text=True,
                                  check=True).stdout.strip()

        with _scratch() as box:
            repo = os.path.join(box, "repo")
            temp = os.path.join(box, "runner_temp")
            os.makedirs(repo)
            os.makedirs(temp)
            git("init", "-q")
            with open(os.path.join(repo, "a.txt"), "w") as fh:
                fh.write("old\n")
            git("add", "a.txt")
            git("commit", "-q", "-m", "base")
            base = git("rev-parse", "HEAD")
            with open(os.path.join(repo, "a.txt"), "w") as fh:
                fh.write("new\n")
            git("commit", "-q", "-am", "head")
            head = git("rev-parse", "HEAD")

            proc, _ = _exec(_run_block("id: http_inputs"),
                            dict(git_env, BASE_SHA=base, HEAD_SHA=head, PROMPT_TEXT="PROMPT",
                                 RUNNER_TEMP=temp), cwd=repo)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(_read(os.path.join(temp, "ai-gate-prompt.txt")), "PROMPT\n")
            self.assertTrue(_read(os.path.join(temp, "ai-gate.diff"))
                            .startswith("diff --git a/a.txt b/a.txt"))

    def test_diff_is_exactly_the_pr_side_of_a_diverged_history(self):
        # 리뷰 r2 재감사 #3 항목 2: base가 갈라진 뒤 앞서 나갔고(b.txt), PR이 파일 하나를
        # 지웠고(gone.txt), 체크아웃은 PR head가 아니다(CI의 merge ref처럼 base 쪽이다).
        # 옳은 범위(merge-base..HEAD_SHA, 삭제 제외)는 a.txt와 added.txt만 담는다.
        git_env = {"PATH": os.environ["PATH"], "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_CONFIG_GLOBAL": os.devnull}

        def git(*args):
            return subprocess.run(["git", "-c", "user.name=t252", "-c",
                                   "user.email=t252@example.invalid", *args], cwd=repo,
                                  env=git_env, capture_output=True, text=True,
                                  check=True).stdout.strip()

        def write(name, text):
            with open(os.path.join(repo, name), "w") as fh:
                fh.write(text)

        with _scratch() as box:
            repo = os.path.join(box, "repo")
            temp = os.path.join(box, "runner_temp")
            os.makedirs(repo)
            os.makedirs(temp)
            git("init", "-q")
            write("a.txt", "old\n")
            write("b.txt", "b1\n")
            write("gone.txt", "g\n")
            git("add", "a.txt", "b.txt", "gone.txt")
            git("commit", "-q", "-m", "root")
            root = git("rev-parse", "HEAD")
            write("b.txt", "b2\n")
            git("commit", "-q", "-am", "base moves on")
            base = git("rev-parse", "HEAD")
            git("checkout", "-q", root)
            write("a.txt", "new\n")
            write("added.txt", "added\n")
            git("rm", "-q", "gone.txt")
            git("add", "a.txt", "added.txt")
            git("commit", "-q", "-m", "pr")
            head = git("rev-parse", "HEAD")
            git("checkout", "-q", base)

            proc, _ = _exec(_run_block("id: http_inputs"),
                            dict(git_env, BASE_SHA=base, HEAD_SHA=head, PROMPT_TEXT="PROMPT",
                                 RUNNER_TEMP=temp), cwd=repo)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            diff = _read(os.path.join(temp, "ai-gate.diff"))
        self.assertEqual(re.findall(r"^diff --git a/(\S+) b/", diff, re.MULTILINE),
                         ["a.txt", "added.txt"], diff)
        self.assertIn("\n+new\n", diff)
        self.assertNotIn("b2", diff)


def _bash_major():
    out = subprocess.run(["bash", "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


class EmptyChangeSetTest(unittest.TestCase):
    """#244 R12: 변경 파일 0건(삭제만 / 빈 diff)은 판정 불가 — blocking이면 실패, advisory면 경고."""

    def run_empty(self, **env):
        return _exec(_run_block("name: 변경 파일 없음 처리"), env)

    def test_blocking_gate_fails_on_zero_changed_files(self):
        proc, _ = self.run_empty(BLOCKING="true", GATE_NAME="test-quality", DELETED="3")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, EMPTY_BLOCKING + "\n")

    def test_advisory_gate_warns_on_zero_changed_files(self):
        proc, _ = self.run_empty(BLOCKING="false", GATE_NAME="prose-factcheck", DELETED="0")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, EMPTY_ADVISORY + "\n")

    def _file_list_output(self, edit_b):
        if _bash_major() < 4:
            self.skipTest("PATH bash is older than 4; the step uses mapfile (the runner has bash 5)")
        git_env = {"PATH": os.environ["PATH"], "GIT_CONFIG_NOSYSTEM": "1",
                   "GIT_CONFIG_GLOBAL": os.devnull}
        with _scratch() as box:
            repo = os.path.join(box, "repo")
            os.makedirs(repo)

            def git(*args):
                return subprocess.run(["git", "-c", "user.name=t244", "-c",
                                       "user.email=t244@example.invalid", *args], cwd=repo,
                                      env=git_env, capture_output=True, text=True,
                                      check=True).stdout.strip()

            git("init", "-q")
            for name in ("a.txt", "b.txt", "c.txt"):
                with open(os.path.join(repo, name), "w") as fh:
                    fh.write(name + "\n")
            git("add", "a.txt", "b.txt", "c.txt")
            git("commit", "-q", "-m", "base")
            base = git("rev-parse", "HEAD")
            git("rm", "-q", "a.txt")
            if edit_b:
                with open(os.path.join(repo, "b.txt"), "w") as fh:
                    fh.write("changed\n")
                git("add", "b.txt")
            else:
                git("rm", "-q", "b.txt")
            git("commit", "-q", "-m", "head")
            head = git("rev-parse", "HEAD")
            proc, out = _exec(_run_block("id: changed_files"),
                              dict(git_env, BASE_SHA=base, HEAD_SHA=head, PATHS_NOTE="t244"),
                              cwd=repo)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return out.splitlines()

    def test_deletion_only_diff_counts_zero_and_reports_deletions(self):
        lines = self._file_list_output(edit_b=False)
        self.assertIn("count=0", lines)
        self.assertIn("deleted=2", lines)

    def test_mixed_diff_counts_edits_and_deletions(self):
        lines = self._file_list_output(edit_b=True)
        self.assertIn("count=1", lines)
        self.assertIn("deleted=1", lines)

    def test_empty_change_step_is_wired_after_the_file_list(self):
        self.assertIn("        if: steps.check_secret.outputs.skip != 'true' && "
                      "steps.changed_files.outputs.count == '0'\n",
                      _step_text("name: 변경 파일 없음 처리"))
        text = _read(REUSABLE)
        self.assertLess(text.index("id: changed_files"), text.index("name: 변경 파일 없음 처리"))
        self.assertLess(text.index("name: 변경 파일 없음 처리"), text.index("id: build_prompt"))


class WiringTest(unittest.TestCase):

    def test_every_gated_step_still_checks_the_secret(self):
        self.assertEqual(_read(REUSABLE).count("steps.check_secret.outputs.skip != 'true'"), 11)

    def test_claude_only_steps_are_gated_on_the_claude_runner(self):
        for marker in ("id: claude", "id: schema"):
            with self.subTest(marker=marker):
                self.assertIn("&& inputs.runner == 'claude-code'", _step_text(marker))

    def test_http_runner_step_is_wired(self):
        step = _step_text("id: http_runner")
        self.assertIn("continue-on-error: true", step)
        self.assertIn("inputs.runner == 'generic-http'", step)
        self.assertIn("AI_GATE_HTTP_API_KEY: ${{ secrets.ai_gate_http_api_key }}", step)

    def test_both_generic_http_steps_run_only_for_the_generic_http_runner(self):
        line = ("        if: steps.check_secret.outputs.skip != 'true' && "
                "steps.changed_files.outputs.count != '0' && inputs.runner == 'generic-http'\n")
        for marker in ("id: http_inputs", "id: http_runner"):
            with self.subTest(marker=marker):
                self.assertIn(line, _step_text(marker))

    def test_http_steps_sit_between_dependency_install_and_verdict(self):
        text = _read(REUSABLE)
        self.assertLess(text.index("name: 판정 의존성 설치"), text.index("id: http_inputs"))
        # 리뷰 r3 B1: 순서가 뒤바뀌면 러너가 프롬프트·diff 파일보다 먼저 돈다.
        self.assertLess(text.index("id: http_inputs"), text.index("id: http_runner"))
        self.assertLess(text.index("id: http_runner"), text.index("id: verdict"))

    def test_shared_steps_run_for_both_runners(self):
        # 리뷰 r3 B2: 공유 스텝에 runner 조건이 붙으면 다른 러너가 빈 입력으로
        # unavailable(advisory면 초록)이 된다. `if:` 줄 전체를 고정한다.
        both = ("        if: steps.check_secret.outputs.skip != 'true' && "
                "steps.changed_files.outputs.count != '0'\n")
        for marker, line in (("id: changed_files",
                              "        if: steps.check_secret.outputs.skip != 'true'\n"),
                             ("id: build_prompt", both),
                             ("name: 판정 환경 준비", both),
                             ("name: 판정 의존성 설치", both),
                             ("id: verdict", both),
                             ("name: 판정 반영", both)):
            with self.subTest(marker=marker):
                self.assertIn(line, _step_text(marker))

    def test_runner_dependent_env_values_are_pinned_verbatim(self):
        # 리뷰 r2 A1: 위 MissingSecretTest·VerdictReportTest는 이 값을 직접 주입하므로,
        # 워크플로가 claude-code 기본값으로 실제 무엇을 넘기는지는 여기서 고정한다.
        for marker, line in (
                ("name: 시크릿 부재 처리",
                 "          MISSING_SECRET: ${{ inputs.runner == 'generic-http' && "
                 "'AI_GATE_HTTP_API_KEY' || 'ANTHROPIC_API_KEY' }}\n"),
                ("name: 판정 반영",
                 "          RUNNER_LABEL: ${{ inputs.runner == 'generic-http' && "
                 "'generic-http 러너' || 'Claude Code 액션' }}\n"),
                ("name: 판정 반영",
                 "          PROVIDER_LABEL: ${{ inputs.runner == 'generic-http' && "
                 "'모델 엔드포인트' || 'Anthropic API' }}\n")):
            with self.subTest(env=line.split(":")[0].strip()):
                self.assertIn(line, _step_text(marker))

    def test_changed_steps_env_blocks_are_pinned_verbatim(self):
        # 리뷰 r2 재감사: 동작 테스트는 env 값을 직접 주입하므로, 판정의 RUNNER/
        # HTTP_OUTCOME 줄을 지워도 초록이었다 — CI에서는 generic-http가 매번
        # unavailable(advisory면 초록)이 된다. 바뀐 스텝의 env 블록 전체를 고정한다.
        for marker, lines in STEP_ENV.items():
            with self.subTest(step=marker):
                self.assertEqual(_env_lines(marker), lines)

    def test_every_variable_a_changed_run_block_reads_is_declared(self):
        # run 쪽 이름만 바뀌어도(예: $BASE_URL → $BASEURL) 같은 조용한 unavailable이 된다.
        for marker in STEP_ENV:
            with self.subTest(step=marker):
                run = _run_block(marker)
                read = set(re.findall(r"\$\{?#?([A-Z_][A-Z0-9_]*)", run))
                declared = {line.split(":")[0].strip() for line in _env_lines(marker)}
                local = set(re.findall(r"(?:^|[\s;(])([A-Z_][A-Z0-9_]*)=", run, re.MULTILINE))
                self.assertTrue(read, run)
                self.assertEqual(read - declared - local - RUNNER_PROVIDED, set())

    def test_runner_temp_file_names_agree_across_steps(self):
        # 리뷰 r2 A2: 한쪽 이름만 바뀌어도 CI에서는 매번 code=unavailable(advisory면
        # 초록)이 된다. 각 스텝에서 이름을 뽑아 서로 같은지 본다.
        writes = re.findall(r'> "\$RUNNER_TEMP/([^"]+)"', _run_block("id: http_inputs"))
        runner = _run_block("id: http_runner")
        reads = [re.search(r'--%s "\$RUNNER_TEMP/([^"]+)"' % flag, runner)
                 for flag in ("prompt-file", "diff-file", "out")]
        self.assertTrue(all(reads), runner)
        prompt, diff, out = (m.group(1) for m in reads)
        verdict = re.search(r"^          HTTP_VERDICT_FILE: \$\{\{ runner\.temp \}\}/(\S+)$",
                            _step_text("id: verdict"), re.MULTILINE)
        self.assertIsNotNone(verdict)
        self.assertEqual(writes, [prompt, diff])
        self.assertEqual(verdict.group(1), out)
        self.assertEqual(len({prompt, diff, out}), 3)

    def test_claude_action_pin_is_unchanged(self):
        self.assertEqual(_read(REUSABLE).count(
            "uses: anthropics/claude-code-action@a874e9ecd7bb36efdad65429c6b35815f5a08f10"), 1)


class CalledJobNameTest(unittest.TestCase):
    """#244: 재사용 잡 `gate`에는 `name:`이 없다 — 체크 이름은 `<호출 잡> / gate`."""

    def test_called_job_has_no_name(self):
        text = _read(REUSABLE)
        self.assertEqual(text.count("\n  gate:\n"), 1)
        self.assertEqual(re.search(r"^jobs:\n  ([a-z][a-z0-9_-]*):$", text, re.M).group(1), "gate")
        job = text[text.index("\n  gate:\n") + 1:]
        self.assertEqual(re.findall(r"^    name:.*$", job, re.M), [])


def _job_text(path, job):
    """호출부 `path`의 잡 `job` 하나(다음 최상위 잡 키 직전까지)."""
    text = _read(path)
    anchor = "\n  " + job + ":\n"
    if text.count(anchor) != 1:
        raise AssertionError("%r occurs %d times in %s" % (anchor, text.count(anchor), path))
    start = text.index(anchor) + 1
    nxt = re.compile(r"^  [a-z][a-z0-9-]*:$", re.MULTILINE).search(text, start + len(anchor))
    return text[start:nxt.start()] if nxt else text[start:]


def _blocking(path, job):
    """호출부 `path`의 잡 `job`이 넘기는 `blocking:` 값 하나."""
    values = re.findall(r"^      blocking: (true|false)$", _job_text(path, job), re.M)
    if len(values) != 1:
        raise AssertionError("%s/%s has %d blocking lines" % (path, job, len(values)))
    return values[0]


class PromotedGateTest(unittest.TestCase):
    """#244: test-quality(claude-code) 하나만 blocking이고, 그 값이 판정 불가 갈래 셋을 모두 실패로 만든다."""

    def test_only_the_test_quality_claude_job_is_blocking(self):
        for jobs in (CallerWiringTest.OLD_JOBS, CallerWiringTest.NEW_JOBS):
            for path, names in jobs.items():
                for job in names:
                    with self.subTest(job=job):
                        expected = "true" if (path, job) == (CALLERS[1], "test-quality") else "false"
                        self.assertEqual(_blocking(path, job), expected)
        total = 0
        for name in sorted(os.listdir(WORKFLOWS)):
            if name.endswith(".yml"):
                total += len(re.findall(r"^ +blocking: true$", _read(os.path.join(WORKFLOWS, name)), re.M))
        self.assertEqual(total, 1)

    def test_promoted_gate_fails_closed_without_credentials(self):
        proc, _ = _exec(_run_block("name: 시크릿 부재 처리"),
                        dict(GATE_NAME="test-quality", MISSING_SECRET="ANTHROPIC_API_KEY",
                             BLOCKING=_blocking(CALLERS[1], "test-quality")))
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(proc.stdout.startswith(
            "::error::[test-quality] ANTHROPIC_API_KEY가 없어 게이트를 실행하지 못했다"), proc.stdout)

    def test_promoted_gate_fails_closed_when_unavailable(self):
        proc, _ = _exec(_run_block("name: 판정 반영"),
                        dict(VERDICT_CODE="unavailable", BLOCKING=_blocking(CALLERS[1], "test-quality"),
                             RUNNER_LABEL="Claude Code 액션", PROVIDER_LABEL="Anthropic API"))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, UNAVAILABLE_BLOCKING + "\n")

    def test_promoted_gate_fails_closed_on_zero_changed_files(self):
        proc, _ = _exec(_run_block("name: 변경 파일 없음 처리"),
                        dict(GATE_NAME="test-quality", DELETED="3",
                             BLOCKING=_blocking(CALLERS[1], "test-quality")))
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, EMPTY_BLOCKING + "\n")

    def test_advisory_sibling_still_passes_without_credentials(self):
        proc, _ = _exec(_run_block("name: 시크릿 부재 처리"),
                        dict(GATE_NAME="prose-factcheck", MISSING_SECRET="ANTHROPIC_API_KEY",
                             BLOCKING=_blocking(CALLERS[1], "prose-factcheck")))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.startswith("::warning::"), proc.stdout)


class PromotedContextLiteralTest(unittest.TestCase):
    """#244: required check `test-quality / gate`를 영원히 대기시킬 수 있는 변경을 막는다."""

    def test_trigger_and_jobs_cannot_strand_the_required_check(self):
        caller = _read(CALLERS[1])
        lines = caller.split("\n")
        i = lines.index("on:")
        self.assertEqual(lines[i + 1], "  pull_request:")
        nxt = next(line for line in lines[i + 2:] if line.strip())
        self.assertLessEqual(len(nxt) - len(nxt.lstrip(" ")), 2, nxt)
        self.assertEqual(re.findall(r"^ +paths(?:-ignore)?:", caller, re.M), [])
        self.assertEqual(caller.count("\n  test-quality:\n"), 1)
        job = _job_text(CALLERS[1], "test-quality")
        self.assertIn("      gate_name: test-quality\n", job)
        self.assertEqual(re.findall(r"^    if:.*$", job, re.M), [])
        reusable = _read(REUSABLE)
        self.assertEqual(re.findall(r"^  ([a-z][a-z0-9_-]*):$",
                                    reusable[reusable.index("\njobs:\n"):], re.M), ["gate"])
        self.assertEqual(re.findall(r"^    name:.*$",
                                    reusable[reusable.index("\n  gate:\n"):], re.M), [])


class CallerWiringTest(unittest.TestCase):
    """호출부 — 기존 4개 잡은 그대로, 게이트마다 `-generic-http` 잡 하나(R-t252-1)."""

    NEW_JOBS = {CALLERS[0]: ("rfc-conformance-generic-http", "golden-approval-generic-http"),
                CALLERS[1]: ("test-quality-generic-http", "prose-factcheck-generic-http")}
    OLD_JOBS = {CALLERS[0]: ("rfc-conformance", "golden-approval"),
                CALLERS[1]: ("test-quality", "prose-factcheck")}

    def test_generic_http_jobs_are_gated_on_the_variable_and_pass_only_the_http_key(self):
        for path, jobs in self.NEW_JOBS.items():
            for job in jobs:
                with self.subTest(job=job):
                    text = _job_text(path, job)
                    for line in ("if: vars.AI_GATE_HTTP_BASE_URL != ''",
                                 "runner: generic-http",
                                 "http_base_url: ${{ vars.AI_GATE_HTTP_BASE_URL }}",
                                 "http_model: ${{ vars.AI_GATE_HTTP_MODEL }}",
                                 "http_api_style: ${{ vars.AI_GATE_HTTP_API_STYLE }}",
                                 "ai_gate_http_api_key: ${{ secrets.AI_GATE_HTTP_API_KEY }}"):
                        self.assertIn(line, text)
                    self.assertNotIn("anthropic_api_key", text)
                    self.assertNotIn("claude_code_oauth_token", text)

    def test_generic_http_job_runs_the_gate_it_is_named_after(self):
        for path, jobs in self.NEW_JOBS.items():
            for job in jobs:
                with self.subTest(job=job):
                    gate = re.search(r"^      gate_name: (\S+)$", _job_text(path, job),
                                     re.MULTILINE).group(1)
                    self.assertEqual(gate, job[:-len("-generic-http")])

    def test_generic_http_jobs_are_advisory_and_use_their_own_prompt(self):
        # 리뷰 r2 재감사 #3 항목 4: R-t252-1은 advisory 잡이다. 다른 게이트의 프롬프트나
        # 꺼진 공허한 통과 탐지는 테스트에서 초록이고 CI에서만 다르게 돈다.
        for path, jobs in self.NEW_JOBS.items():
            for job in jobs:
                with self.subTest(job=job):
                    text = _job_text(path, job)
                    gate = job[:-len("-generic-http")]
                    self.assertIn("      prompt_file: .github/ai-gates/%s.md\n" % gate, text)
                    self.assertIn("      blocking: false\n", text)
                    self.assertIn("      expect_nonempty: true\n", text)
                    self.assertNotIn("blocking: true", text)
                    self.assertNotIn("expect_nonempty: false", text)

    def test_existing_jobs_get_no_runner_and_no_http_key(self):
        for path, jobs in self.OLD_JOBS.items():
            for job in jobs:
                with self.subTest(job=job):
                    text = _job_text(path, job)
                    self.assertNotIn("runner:", text)
                    self.assertNotIn("ai_gate_http_api_key", text)

    def test_each_caller_calls_the_reusable_workflow_four_times(self):
        for path in CALLERS:
            with self.subTest(path=os.path.basename(path)):
                self.assertEqual(_read(path).count("uses: ./.github/workflows/_ai-gate.yml"), 4)


if __name__ == "__main__":
    unittest.main()
