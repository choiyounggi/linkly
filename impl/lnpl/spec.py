"""`spec` blocks -> a test-suite artifact (plan.md D20 artifact 4).

RFC-0002 Appendix A.4-2 decided that `spec` is *not* an IR node: a specification
of expected behaviour is a test artifact, not part of the program's meaning. This
module produces that artifact.

It emits a **declarative manifest**, not generated code. Generating a test file
would put an LLM (or a template) between the declaration and what runs, which is
the synthesis route this platform rejected — the same reason agents propose IR
rather than source (RFC-0002 §Prior Art). The manifest is data; `run_manifest`
executes it against the interpreter.

Manifest shape:

    {"spec_version": "0.1", "module": "login",
     "cases": [{"name": "...", "workflow": "wf.login",
                "given": [...], "when": [...], "expect": [...]}]}
"""

from .interp import Interpreter, RunError, sample_payload
from .lexer import COMPARATORS
from .repo_policy import default_rows

SPEC_VERSION = "0.1"


class SpecError(Exception):
    """Raised when a spec block or an expectation cannot be understood."""


def extract(decls, module_name):
    """[Decl] -> manifest dict. Workflows without a `spec` clause are skipped."""
    cases = []
    for d in decls:
        if d.kind != "workflow" or "spec" not in d.clauses:
            continue
        # The parser stores given/when/expect as sibling clauses (they are clause
        # keywords), so read them by name; `spec` itself is the marker.
        if d.clauses["spec"]:
            raise SpecError("workflow %s: the `spec` keyword takes no content lines — "
                            "put them under given/when/expect" % d.name)
        given = [" ".join(l.tokens) for l in d.clauses.get("given", [])]
        when = [" ".join(l.tokens) for l in d.clauses.get("when", [])]
        expect = [" ".join(l.tokens) for l in d.clauses.get("expect", [])]
        if not when:
            raise SpecError("workflow %s: a spec needs a `when` section" % d.name)
        if not expect:
            raise SpecError("workflow %s: a spec needs an `expect` section" % d.name)
        cases.append({"name": "%s spec" % d.name,
                      "workflow": _workflow_id(d.name),
                      "given": given, "when": when, "expect": expect})
    return {"spec_version": SPEC_VERSION, "module": module_name, "cases": cases}


def _workflow_id(name):
    from .lower import derive_id
    return derive_id(name, "Workflow")


# ---- expectation vocabulary -------------------------------------------------
# Closed, like the verb lexicon: an expectation this module cannot evaluate is an
# error, never a silent pass. A spec that always passes is not a spec.

def _expect_completed(_phrase, result, _interp):
    return result["status"] == "completed", "status=%s" % result["status"]


def _expect_failed(_phrase, result, _interp):
    return result["status"] == "failed", "status=%s" % result["status"]


def _expect_step_count(phrase, result, _interp):
    tokens = phrase.split()
    want = int(tokens[-1])
    got = len(result["steps"])
    return got == want, "steps=%d want=%d" % (got, want)


def _expect_slo(phrase, result, _interp):
    tokens = phrase.split()
    if len(tokens) == 2 and tokens[1] == "met":
        return bool(result.get("slo_met")), "slo_met=%s" % result.get("slo_met")
    raise SpecError("unsupported slo expectation: %r" % phrase)


def _expect_duration(phrase, result, _interp):
    # `duration < 50ms`
    tokens = phrase.split()
    if len(tokens) != 3 or tokens[1] not in COMPARATORS:
        raise SpecError("unsupported duration expectation: %r" % phrase)
    from .interp import _duration_ms
    limit = _duration_ms(tokens[2])
    got = result["duration_ms"]
    ok = {"<": got < limit, "<=": got <= limit,
          ">": got > limit, ">=": got >= limit}[tokens[1]]
    return ok, "duration=%sms limit=%sms" % (got, limit)


def _expect_cache(phrase, _result, interp):
    tokens = phrase.split()
    if len(tokens) == 2 and tokens[1] == "written":
        return len(interp.cache.store) > 0, "cache entries=%d" % len(interp.cache.store)
    raise SpecError("unsupported cache expectation: %r" % phrase)


def _expect_attempts(phrase, result, _interp):
    # `attempts 4` — the highest attempt count any step needed
    want = int(phrase.split()[-1])
    got = max([s["attempts"] for s in result["steps"]] or [0])
    return got == want, "max attempts=%d want=%d" % (got, want)


EXPECTATIONS = {
    "completed": _expect_completed,
    "failed": _expect_failed,
    "steps": _expect_step_count,
    "slo": _expect_slo,
    "duration": _expect_duration,
    "cache": _expect_cache,
    "attempts": _expect_attempts,
}


def _payload_from_given(given, entity_node):
    """`given` lines describe the input. Recognized forms:
        `valid <...>`        a narrative fixture marker (any noun) — no field effect
        `empty repository`   run against an empty repository
        `<field> <value>`    set a declared field
        `no <field>`         drop a declared field

    Field forms must name a field the entity declares; anything else is refused.
    A `given` the runner cannot interpret is not silently absorbed as a field
    assignment — a `given` nobody can build is not a fixture (issue #28).
    """
    fields = {f["name"] for f in entity_node["fields"]} if entity_node else set()
    payload = sample_payload([entity_node] if entity_node else [])
    for phrase in given:
        tokens = phrase.split()
        if tokens[0] == "valid" or phrase == "empty repository":
            continue        # narrative fixture handled by `when`
        elif tokens[0] == "no" and len(tokens) == 2 and tokens[1] in fields:
            payload.pop(tokens[1], None)
        elif len(tokens) == 2 and tokens[0] in fields:
            payload[tokens[0]] = tokens[1]
        else:
            raise SpecError(
                "unsupported given: %r (use `valid <...>`, `empty repository`, "
                "`<field> <value>`, or `no <field>` naming a declared field)" % phrase)
    return payload


def run_manifest(manifest, document):
    """Execute every case. Returns (passed, failed, report_lines)."""
    entity = next((n for n in document["nodes"] if n["kind"] == "Entity"), None)
    passed, failed, lines = 0, 0, []
    for case in manifest["cases"]:
        payload = _payload_from_given(case["given"], entity)
        empty_repo = any(g == "empty repository" for g in case["given"])
        rows = {} if empty_repo else default_rows(document, case["workflow"], payload)
        interp = Interpreter(document, repo_rows=rows)
        try:
            result = interp.run_workflow(case["workflow"], payload)
        except RunError as exc:
            failed += 1
            lines.append("FAIL %s — run error: %s" % (case["name"], exc))
            continue
        for phrase in case["expect"]:
            key = phrase.split()[0]
            check = EXPECTATIONS.get(key)
            if check is None:
                failed += 1
                lines.append("FAIL %s — unsupported expectation %r (known: %s)"
                             % (case["name"], phrase, ", ".join(sorted(EXPECTATIONS))))
                continue
            ok, detail = check(phrase, result, interp)
            if ok:
                passed += 1
                lines.append("PASS %s — %s (%s)" % (case["name"], phrase, detail))
            else:
                failed += 1
                lines.append("FAIL %s — %s (%s)" % (case["name"], phrase, detail))
    return passed, failed, lines
