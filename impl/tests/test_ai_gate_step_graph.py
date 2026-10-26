"""`.github/workflows/_ai-gate.yml`의 스텝 그래프를 구조로 검사한다 (issue #260).

스텝마다 `if:`가 정하는 러너 갈래(claude-code / generic-http)와 읽고 쓰는 것($RUNNER_TEMP
파일, steps.<id> 출력)을 뽑아, 읽는 것마다 같은 갈래의 앞선 스텝이 썼는지와 공유 스텝이
두 러너 모두에서 도는지를 본다. CI의 gate 잡에는 PyYAML이 없어 텍스트로 파싱한다.
"""
import os
import re
import textwrap
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REUSABLE = os.path.join(REPO, ".github", "workflows", "_ai-gate.yml")
PATHS = ("claude-code", "generic-http")
SKIP_EQ = "steps.check_secret.outputs.skip == 'true'"
SKIP_NE = "steps.check_secret.outputs.skip != 'true'"
COUNT_EQ = "steps.changed_files.outputs.count == '0'"
COUNT_NE = "steps.changed_files.outputs.count != '0'"
RUNNER_CLAUSES = {"inputs.runner == 'claude-code'": "claude-code",
                  "inputs.runner == 'generic-http'": "generic-http"}

STEP_START = "      - "
NAME_START = "      - name: "
TEMP_FILE = re.compile(r'"?\$RUNNER_TEMP/([A-Za-z0-9._-]+)')
ENV_TEMP_FILE = re.compile(r"\$\{\{ runner\.temp \}\}/([A-Za-z0-9._-]+)")
STEP_REF = re.compile(r"steps\.([A-Za-z_][A-Za-z0-9_-]*)\."
                      r"(?:outputs\.[A-Za-z_][A-Za-z0-9_-]*|outcome|conclusion)")
DISPATCH = re.compile(r'\[ "\$RUNNER" = "([a-z-]+)" \]')


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _key(lines, key):
    """스텝 바로 아래 키(8칸 들여쓰기) `key:`의 값. 없으면 None."""
    prefix = "        %s: " % key
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return None


def _run(lines):
    prefix = "        run: "
    for i, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        value = line[len(prefix):].strip()
        if not value.startswith("|"):
            return value
        body = []
        for nxt in lines[i + 1:]:
            if nxt.strip() and not nxt.startswith(" " * 10):
                break
            body.append(nxt)
        return textwrap.dedent("\n".join(body))
    return ""


def parse_steps(text):
    """`jobs.<job>.steps`를 스텝 dict(name, id, cond, run, text, label) 목록으로 돌려준다.
    주석 줄은 먼저 지운다. 이 파서가 모르는 모양이면 조용히 넘기지 않고 ValueError."""
    head = "\n    steps:\n"
    if head not in text:
        raise ValueError("no steps: region")
    chunks = []
    for line in text[text.index(head) + len(head):].split("\n"):
        if line.startswith(STEP_START):
            if not line.startswith(NAME_START):
                raise ValueError("step does not start with - name: " + line)
            chunks.append([])
        if chunks and not line.strip().startswith("#"):
            chunks[-1].append(line)
    if not chunks:
        raise ValueError("no steps")
    steps = []
    for lines in chunks:
        name = lines[0][len(NAME_START):].strip()
        cond = _key(lines, "if")
        if cond in (">", ">-", "|", "|-"):
            raise ValueError("multi-line if: in step " + name)
        step_id = _key(lines, "id")
        steps.append({"name": name, "id": step_id, "cond": cond, "run": _run(lines),
                      "text": "\n".join(lines), "label": step_id or name})
    return steps


def _conjuncts(step):
    return step["cond"].split(" && ") if step["cond"] is not None else []


def _paths(step):
    runner = [c for c in _conjuncts(step) if "inputs.runner" in c]
    if len(runner) == 1 and runner[0] in RUNNER_CLAUSES:
        return {RUNNER_CLAUSES[runner[0]]}
    return set(PATHS)


def runner_paths(text):
    """스텝 label → 그 스텝이 도는 러너 갈래 집합."""
    return {s["label"]: _paths(s) for s in parse_steps(text)}


def _files(step):
    """run 블록의 $RUNNER_TEMP 파일을 본문 순서대로 (쓰기 여부, 이름) 목록으로."""
    found = []
    for line in step["run"].split("\n"):
        for m in TEMP_FILE.finditer(line):
            before = line[:m.start()]
            found.append((before.endswith("> ") or before.endswith("--out "), m.group(1)))
    return found


def _facts(steps):
    facts = []
    for step in steps:
        dispatch = set(DISPATCH.findall(step["run"]))
        paths = _paths(step)
        files = _files(step)
        facts.append({
            "paths": paths,
            "files": files,
            "writes": {f for is_write, f in files if is_write},
            "reads": {f for is_write, f in files if not is_write},
            "env_reads": ENV_TEMP_FILE.findall(step["text"]),
            "refs": set(STEP_REF.findall(step["text"])),
            "dispatch": bool(dispatch),
            "env_paths": paths & dispatch if dispatch else paths,
        })
    return facts


def _runner_findings(steps):
    found = []
    for step in steps:
        valid = 0
        for c in _conjuncts(step):
            if "inputs.runner" not in c:
                continue
            if c not in RUNNER_CLAUSES or valid:
                found.append("runner: %s has a runner clause other than inputs.runner == "
                             "'claude-code' or 'generic-http': %s" % (step["label"], c))
            else:
                valid += 1
    return found


def _flow_findings(steps, facts):
    found = []
    for i, (step, fact) in enumerate(zip(steps, facts)):
        label = step["label"]

        def written_before(name, path, i=i):
            return any(name in facts[j]["writes"] and path in facts[j]["paths"] for j in range(i))

        # F1: 읽는 파일마다 같은 갈래의 앞선 쓰기가 있어야 한다.
        for path in sorted(fact["paths"]):
            seen = set()
            for is_write, name in fact["files"]:
                if is_write:
                    seen.add(name)
                elif name not in seen and not written_before(name, path):
                    found.append("flow: %s reads $RUNNER_TEMP/%s on %s with no earlier writer"
                                 % (label, name, path))
        for path in sorted(fact["env_paths"]):
            for name in fact["env_reads"]:
                if not written_before(name, path):
                    found.append("flow: %s reads $RUNNER_TEMP/%s on %s with no earlier writer"
                                 % (label, name, path))
        # F2: 읽는 steps.<id>는 앞에서 선언되고, 같은 갈래에서 돌아야 한다.
        for ref in sorted(fact["refs"]):
            owner = [j for j in range(i) if steps[j]["id"] == ref]
            if not owner:
                found.append("flow: %s reads steps.%s before any step declares it" % (label, ref))
            elif not fact["dispatch"]:
                for path in sorted(fact["paths"]):
                    if path not in facts[owner[0]]["paths"]:
                        found.append("flow: %s reads steps.%s on %s but %s does not run there"
                                     % (label, ref, path, ref))
    return found


def _product_findings(steps, facts):
    found = []
    for i, (step, fact) in enumerate(zip(steps, facts)):
        products = []
        if step["id"] is not None and any(step["id"] in f["refs"] for f in facts):
            products.append(("steps.%s" % step["id"], step["id"], None))
        for name in dict.fromkeys(f for is_write, f in fact["files"] if is_write):
            products.append(("$RUNNER_TEMP/%s" % name, None, name))
        # RI: 한 러너로 좁힌 스텝은 그 러너에서 누군가 읽는 것을 만들어야 한다.
        if len(fact["paths"]) == 1 and not products:
            found.append("runner: %s is limited to %s but produces nothing a later step reads"
                         % (step["label"], next(iter(fact["paths"]))))
        # F3: 만든 것은 같은 갈래의 뒤 스텝이 읽어야 한다.
        for path in sorted(fact["paths"]):
            for item, ref, name in products:
                later = [f for f in facts[i + 1:] if path in f["paths"]]
                if ref is not None:
                    used = any(ref in f["refs"] for f in later)
                else:
                    used = any(name in f["reads"] or (name in f["env_reads"] and path in f["env_paths"])
                               for f in later)
                if not used:
                    found.append("flow: %s produces %s on %s with no later reader"
                                 % (step["label"], item, path))
    return found


def _guard_findings(steps):
    ids = [s["id"] for s in steps]
    if "check_secret" not in ids:
        return []
    found = []
    after_secret = steps[ids.index("check_secret") + 1:]
    skip_eq = 0
    for step in after_secret:
        conj = _conjuncts(step)
        if len([c for c in conj if c in (SKIP_EQ, SKIP_NE)]) != 1:
            found.append("guard: %s lacks the check_secret skip guard" % step["label"])
        if SKIP_EQ in conj:
            skip_eq += 1
            for c in conj:
                if c != SKIP_EQ:
                    found.append("guard: %s has an unexpected condition: %s" % (step["label"], c))
    if skip_eq != 1:
        found.append("guard: expected exactly one step with skip == 'true', found %d" % skip_eq)
    if "changed_files" in ids:
        count_eq = 0
        for step in steps[ids.index("changed_files") + 1:]:
            conj = _conjuncts(step)
            if SKIP_NE not in conj:
                continue
            if len([c for c in conj if c in (COUNT_EQ, COUNT_NE)]) != 1:
                found.append("guard: %s lacks the changed_files count guard" % step["label"])
            count_eq += conj.count(COUNT_EQ)
        if count_eq != 1:
            found.append("guard: expected exactly one step with count == '0', found %d" % count_eq)
    for step in after_secret:
        if SKIP_EQ in _conjuncts(step):
            continue
        for c in _conjuncts(step):
            if c not in (SKIP_EQ, SKIP_NE, COUNT_EQ, COUNT_NE) and "inputs.runner" not in c:
                found.append("guard: %s has an unexpected condition: %s" % (step["label"], c))
    return found


def step_graph_findings(text):
    """`text`(재사용 워크플로 원문)의 구조 위반을 문자열 목록으로. 빈 목록이면 통과."""
    steps = parse_steps(text)
    facts = _facts(steps)
    return (_runner_findings(steps) + _flow_findings(steps, facts)
            + _product_findings(steps, facts) + _guard_findings(steps))


def _segment(text, marker):
    """`marker`를 담은 스텝 하나의 (start, end). marker는 파일에 정확히 한 번 있어야 한다."""
    assert text.count(marker) == 1, "%r occurs %d times" % (marker, text.count(marker))
    line = text.rfind("\n", 0, text.index(marker))
    start = (line if text.startswith("\n" + NAME_START, line)
             else text.rfind("\n" + NAME_START, 0, line))
    end = text.find("\n" + NAME_START, line + 1)
    return start, len(text) if end == -1 else end


def _mutate(text, marker, old, new):
    start, end = _segment(text, marker)
    seg = text[start:end]
    assert seg.count(old) == 1, "%r occurs %d times in the %r step" % (old, seg.count(old), marker)
    mutant = text[:start] + seg.replace(old, new) + text[end:]
    assert mutant != text
    return mutant


def _append_to_if(text, marker, suffix):
    start, end = _segment(text, marker)
    seg = text[start:end]
    ifs = re.findall(r"^        if: .*$", seg, re.MULTILINE)
    assert len(ifs) == 1, ifs
    return _mutate(text, marker, ifs[0] + "\n", ifs[0] + suffix + "\n")


def _swap(text, marker_a, marker_b):
    a0, a1 = _segment(text, marker_a)
    b0, b1 = _segment(text, marker_b)
    assert a1 == b0, "steps %r and %r are not adjacent" % (marker_a, marker_b)
    return text[:a0] + text[b0:b1] + text[a0:a1] + text[b1:]


class StepGraphTest(unittest.TestCase):

    def test_real_workflow_has_no_findings(self):
        self.assertEqual(step_graph_findings(_read(REUSABLE)), [])

    def test_real_workflow_runner_paths(self):
        both = set(PATHS)
        expected = {label: both for label in (
            "Checkout", "check_secret", "시크릿 부재 처리", "changed_files", "변경 파일 없음 처리",
            "build_prompt", "판정 환경 준비", "판정 의존성 설치", "verdict", "판정 반영")}
        expected.update({"schema": {"claude-code"}, "claude": {"claude-code"},
                         "http_inputs": {"generic-http"}, "http_runner": {"generic-http"}})
        self.assertEqual(runner_paths(_read(REUSABLE)), expected)

    def test_real_workflow_skip_guards(self):
        # issue #260 낮은 지적: 예전 카운트 테스트는 `!= 'true'` 11줄만 셌고
        # `== 'true'` 한 줄(시크릿 부재 처리)은 세지 않았다.
        conds = [s["cond"] or "" for s in parse_steps(_read(REUSABLE))]
        self.assertEqual(sum(SKIP_NE in c for c in conds), 11)
        self.assertEqual(sum(SKIP_EQ in c for c in conds), 1)

    def test_parser_agrees_with_pyyaml_when_available(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        text = _read(REUSABLE)
        steps = yaml.safe_load(text)["jobs"]["gate"]["steps"]
        self.assertEqual([(s["name"], s.get("id"), s.get("if")) for s in steps],
                         [(p["name"], p["id"], p["cond"]) for p in parse_steps(text)])

    def test_missing_steps_region_raises(self):
        with self.assertRaises(ValueError):
            parse_steps("name: x\njobs:\n")

    def test_step_without_a_name_line_raises(self):
        with self.assertRaises(ValueError):
            parse_steps("jobs:\n  gate:\n    steps:\n      - uses: actions/checkout@v7\n")

    def test_multi_line_if_raises(self):
        with self.assertRaises(ValueError):
            parse_steps("jobs:\n  gate:\n    steps:\n      - name: a\n        if: >-\n"
                        "          x\n        run: echo\n")

    def test_minimal_workflow_has_no_findings(self):
        self.assertEqual(step_graph_findings(
            "jobs:\n  gate:\n    steps:\n      - name: Checkout\n"
            "        uses: actions/checkout@v7\n"), [])


class KnownBadControlTest(unittest.TestCase):
    """알려진 나쁜 워크플로마다 검사가 정해진 지적을 내는지 — 예전 고정 핀이 잡던 것 포함."""

    def findings(self, mutant):
        return step_graph_findings(mutant)

    def setUp(self):
        self.t = _read(REUSABLE)

    def test_m1_swapped_http_steps_read_before_write(self):
        mutant = _swap(self.t, "id: http_inputs", "id: http_runner")
        self.assertIn("flow: http_runner reads $RUNNER_TEMP/ai-gate-prompt.txt on generic-http "
                      "with no earlier writer", self.findings(mutant))

    def test_m2_runner_clause_on_verdict(self):
        mutant = _append_to_if(self.t, "id: verdict", " && inputs.runner == 'claude-code'")
        self.assertIn("flow: 판정 반영 reads steps.verdict on generic-http but verdict does not "
                      "run there", self.findings(mutant))

    def test_m3_renamed_diff_write(self):
        mutant = _mutate(self.t, "id: http_inputs", '> "$RUNNER_TEMP/ai-gate.diff"',
                         '> "$RUNNER_TEMP/ai-gate.dif"')
        self.assertIn("flow: http_runner reads $RUNNER_TEMP/ai-gate.diff on generic-http with no "
                      "earlier writer", self.findings(mutant))

    def test_m4_runner_clause_on_dependency_install(self):
        mutant = _append_to_if(self.t, "name: 판정 의존성 설치", " && inputs.runner == 'claude-code'")
        self.assertIn("runner: 판정 의존성 설치 is limited to claude-code but produces nothing a "
                      "later step reads", self.findings(mutant))

    def test_m5_schema_without_runner_clause(self):
        mutant = _mutate(self.t, "id: schema", " && inputs.runner == 'claude-code'", "")
        self.assertIn("flow: schema produces steps.schema on generic-http with no later reader",
                      self.findings(mutant))

    def test_m6_build_prompt_without_count_guard(self):
        mutant = _mutate(self.t, "id: build_prompt",
                         " && steps.changed_files.outputs.count != '0'", "")
        self.assertIn("guard: build_prompt lacks the changed_files count guard",
                      self.findings(mutant))

    def test_m7_http_inputs_without_runner_clause(self):
        mutant = _mutate(self.t, "id: http_inputs", " && inputs.runner == 'generic-http'", "")
        self.assertIn("flow: http_inputs produces $RUNNER_TEMP/ai-gate-prompt.txt on claude-code "
                      "with no later reader", self.findings(mutant))

    def test_m8_report_without_skip_guard(self):
        mutant = _mutate(self.t, "name: 판정 반영",
                         "if: steps.check_secret.outputs.skip != 'true' && ", "if: ")
        self.assertIn("guard: 판정 반영 lacks the check_secret skip guard", self.findings(mutant))

    def test_m9_negated_runner_clause(self):
        mutant = _mutate(self.t, "id: http_runner", "inputs.runner == 'generic-http'",
                         "inputs.runner != 'claude-code'")
        self.assertIn("runner: http_runner has a runner clause other than inputs.runner == "
                      "'claude-code' or 'generic-http': inputs.runner != 'claude-code'",
                      self.findings(mutant))

    def test_m10_no_skip_true_step(self):
        mutant = _mutate(self.t, "name: 시크릿 부재 처리", "skip == 'true'", "skip != 'true'")
        self.assertIn("guard: expected exactly one step with skip == 'true', found 0",
                      self.findings(mutant))


if __name__ == "__main__":
    unittest.main()
