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

from .interp import Interpreter, RunError, refinement_index, sample_payload
from .lexer import COMPARATORS
from .repo_policy import binding_name, default_rows

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


# ---- issue #39: return value, entity state, event payload, failure ----------
# Added, never substituted: the seven above keep their exact meaning. Each of the
# five below reads a DIFFERENT observable, so a spec can say which property it is
# asserting instead of inferring it from the step count.

def _expect_result(phrase, result, _interp):
    """`result <ref> <op> <value>` / `result <ref> exists|missing`.

    The condition grammar and the resolver are the guards' own (RFC-0011): the
    text after `result` goes through `parse_condition`, and evaluation goes
    through `_condition_holds` against this run's bindings. Re-implementing
    either here would create a second scope — the outcome this task exists to
    prevent.
    """
    from .condition import ConditionError
    from .interp import _condition_holds
    text = phrase.split(None, 1)[1] if len(phrase.split(None, 1)) > 1 else ""
    if not text:
        raise SpecError("`result` needs a reference and a check: %r" % phrase)
    try:
        ok = _condition_holds(text, result.get("payload", {}),
                              result.get("bindings", {}))
    except (ConditionError, RunError) as exc:
        raise SpecError("unsupported result expectation %r: %s" % (phrase, exc))
    return ok, "%s -> %s" % (text, ok)


def _entity_id_for(interp, name):
    for node in interp.doc["nodes"]:
        if node["kind"] == "Entity" and node.get("name") == name:
            return node["id"]
    raise SpecError("no entity named %r is declared" % name)


def _expect_rows(phrase, _result, interp):
    """`rows <EntityName> <N>` — the store's state after the run.

    Led by `rows`, not by `entity`: `entity` opens a declaration (lexer
    KEYWORDS_TOP), so an expectation starting with it would be parsed as one.
    """
    tokens = phrase.split()
    if len(tokens) != 3 or not tokens[2].isdigit():
        raise SpecError("unsupported rows expectation: %r "
                        "(use `rows <Entity> <N>`)" % phrase)
    entity_id = _entity_id_for(interp, tokens[1])
    got = len(interp.repo.rows.get(entity_id, {}))
    want = int(tokens[2])
    return got == want, "%s rows=%d want=%d" % (tokens[1], got, want)


def _expect_emitted(phrase, _result, interp):
    """`emitted <Name>` / `emitted <Name> count <N>` /
    `emitted <Name> payload <field> exists|missing`.

    Led by `emitted`, not by `event`, for the same reason `rows` is not
    `entity`: `event` opens a declaration.
    """
    tokens = phrase.split()
    if len(tokens) < 2:
        raise SpecError("unsupported emitted expectation: %r" % phrase)
    event_id = None
    for node in interp.doc["nodes"]:
        if node["kind"] == "Event" and node.get("name") == tokens[1]:
            event_id = node["id"]
    if event_id is None:
        raise SpecError("no event named %r is declared" % tokens[1])
    emissions = [e for e in interp.outbox if e["event"] == event_id]

    if len(tokens) == 2:
        return bool(emissions), "%s emissions=%d" % (tokens[1], len(emissions))
    if len(tokens) == 4 and tokens[2] == "count" and tokens[3].isdigit():
        want = int(tokens[3])
        return len(emissions) == want, ("%s emissions=%d want=%d"
                                        % (tokens[1], len(emissions), want))
    if len(tokens) == 5 and tokens[2] == "payload" and tokens[4] in ("exists", "missing"):
        field = tokens[3]
        # An empty outbox carries no payload, so `exists` is false and `missing`
        # is true — the same rule an absent field follows (RFC-0011 §G11.4).
        present = any(e["payload"].get(field) is not None for e in emissions)
        ok = present if tokens[4] == "exists" else not present
        return ok, "%s payload %s present=%s (emissions=%d)" % (
            tokens[1], field, present, len(emissions))
    raise SpecError("unsupported emitted expectation: %r (use `emitted <Name>`, "
                    "`emitted <Name> count <N>`, or `emitted <Name> payload "
                    "<field> exists|missing`)" % phrase)


def _expect_error(phrase, result, _interp):
    """`error step <name…>` / `error reason <substring…>` — the failure contract."""
    tokens = phrase.split()
    if len(tokens) < 3:
        raise SpecError("unsupported error expectation: %r (use `error step "
                        "<name>` or `error reason <substring>`)" % phrase)
    rest = " ".join(tokens[2:])
    if tokens[1] == "step":
        got = result.get("failed_step")
        return got == rest, "failed_step=%r want=%r" % (got, rest)
    if tokens[1] == "reason":
        got = result.get("failure_reason")
        # A run that did not fail has no reason, so the assertion fails rather
        # than matching vacuously against an empty string.
        return got is not None and rest in got, "failure_reason=%r" % got
    raise SpecError("unsupported error expectation: %r (use `error step "
                    "<name>` or `error reason <substring>`)" % phrase)


def _expect_effects(phrase, result, _interp):
    """`effects <N>` — how many effects the run actually performed.

    The total, not a per-step figure: a step name carries spaces, and per-step
    assertion belongs to the issue #36 follow-up that will need it. A step which
    derives no effect lowers this total, which is the hook that follow-up uses.
    """
    tokens = phrase.split()
    if len(tokens) != 2 or not tokens[1].isdigit():
        raise SpecError("unsupported effects expectation: %r (use `effects <N>`)"
                        % phrase)
    got = sum(len(s.get("effects", [])) for s in result["steps"])
    want = int(tokens[1])
    return got == want, "effects=%d want=%d" % (got, want)


EXPECTATIONS = {
    "completed": _expect_completed,
    "failed": _expect_failed,
    "steps": _expect_step_count,
    "slo": _expect_slo,
    "duration": _expect_duration,
    "cache": _expect_cache,
    "attempts": _expect_attempts,
    "result": _expect_result,
    "rows": _expect_rows,
    "emitted": _expect_emitted,
    "error": _expect_error,
    "effects": _expect_effects,
}


def _payload_from_given(given, entity_node, refinements=None, document=None):
    """`given` lines describe the input. Recognized forms:
        `valid <...>`        a narrative fixture marker (any noun) — no field effect
        `empty repository`   run against an empty repository
        `<field> <value>`    set a declared field
        `no <field>`         drop a declared field
        `stored <entity> <field> <value>`
                             prior repository state (issue #39)

    Field forms must name a field the entity declares; anything else is refused.
    A `given` the runner cannot interpret is not silently absorbed as a field
    assignment — a `given` nobody can build is not a fixture (issue #28).

    Returns `(payload, stored)`. `stored` is `{entity_id: {field: value}}`: the
    default seed copies the payload into the row, so without a way to say "the
    stored row differs from the input" a spec cannot express the behaviour issue
    #37 is about at all.
    """
    fields = {f["name"] for f in entity_node["fields"]} if entity_node else set()
    payload = sample_payload([entity_node] if entity_node else [], refinements)
    entities = [n for n in (document or {}).get("nodes", [])
                if n["kind"] == "Entity"]
    stored = {}
    for phrase in given:
        tokens = phrase.split()
        if tokens[0] == "valid" or phrase == "empty repository":
            continue        # narrative fixture handled by `when`
        elif tokens[0] == "stored":
            if len(tokens) != 4:
                raise SpecError(
                    "unsupported given: %r (use `stored <entity> <field> <value>`)"
                    % phrase)
            _name, ent_name, field, value = tokens
            target = next((e for e in entities
                           if binding_name(e) == ent_name), None)
            if target is None:
                raise SpecError("given %r names %r, which is not a declared entity"
                                % (phrase, ent_name))
            if field not in {f["name"] for f in target.get("fields", [])}:
                raise SpecError("given %r names field %r, which entity %s does "
                                "not declare" % (phrase, field, target["name"]))
            stored.setdefault(target["id"], {})[field] = _coerce(value)
        elif tokens[0] == "no" and len(tokens) == 2 and tokens[1] in fields:
            payload.pop(tokens[1], None)
        elif len(tokens) == 2 and tokens[0] in fields:
            # Left as the raw string, exactly as before issue #39: coercing here
            # would change what every existing `given <field> <value>` produces
            # (`name 42` would stop being a valid Text), and the comparison path
            # already coerces a numeric string when it needs a number.
            payload[tokens[0]] = tokens[1]
        else:
            raise SpecError(
                "unsupported given: %r (use `valid <...>`, `empty repository`, "
                "`<field> <value>`, `no <field>` naming a declared field, or "
                "`stored <entity> <field> <value>`)" % phrase)
    if stored and any(g == "empty repository" for g in given):
        raise SpecError(
            "`empty repository` and `stored ...` contradict each other: there is "
            "no row to store into an empty store. Drop one.")
    return payload, stored


def _coerce(text):
    """A `stored` value as an int where it reads as one, else the raw string.

    Applied to `stored` only — new surface with no existing meaning to preserve.
    The row it overrides is a copy of the derived payload, which already carries
    an int for an Integer field, so coercing keeps the override the same shape as
    the value it replaces. The pre-existing `<field> <value>` form deliberately
    does NOT go through here.
    """
    if text.lstrip("-").isdigit():
        return int(text)
    return text


def run_manifest(manifest, document):
    """Execute every case. Returns (passed, failed, report_lines)."""
    entity = next((n for n in document["nodes"] if n["kind"] == "Entity"), None)
    passed, failed, lines = 0, 0, []
    for case in manifest["cases"]:
        payload, stored = _payload_from_given(case["given"], entity,
                                              refinement_index(document),
                                              document)
        empty_repo = any(g == "empty repository" for g in case["given"])
        rows = {} if empty_repo else default_rows(document, case["workflow"], payload)
        for entity_id, overrides in stored.items():
            # The seeded row is a copy of the payload; `stored` is what lets a
            # case say the STORED value differs from the INPUT (issue #37).
            for row in rows.get(entity_id, {}).values():
                row.update(overrides)
        interp = Interpreter(document, repo_rows=rows)
        try:
            result = interp.run_workflow(case["workflow"], payload)
            # `result` expectations resolve bare references against the input, so
            # the runner carries it alongside the bindings the run produced.
            result["payload"] = payload
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
