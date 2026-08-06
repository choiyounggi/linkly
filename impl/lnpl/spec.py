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
    """[Decl] -> manifest dict. Workflows without a `spec` clause are skipped.

    Each `spec` block is one case (issue #46): the parser keeps a block's
    given/when/expect on the block itself (`Decl.extra["specs"]`), so a second
    block no longer merges into the first. A single block keeps the exact
    pre-#46 case name — the committed golden manifests are byte-compared.
    """
    cases = []
    for d in decls:
        if d.kind != "workflow" or "spec" not in d.clauses:
            continue
        if d.clauses["spec"]:
            raise SpecError("workflow %s: the `spec` keyword takes no content lines — "
                            "put them under given/when/expect" % d.name)
        blocks = d.extra.get("specs") or []
        # Sections written before the first `spec` keyword landed in the
        # legacy shared clause lists; with blocks present they would be
        # silently dropped — refuse instead of losing declared lines.
        stray = [k for k in ("given", "when", "expect") if d.clauses.get(k)]
        if stray:
            raise SpecError(
                "workflow %s: %s lines appear before the first `spec` block — "
                "move them under it" % (d.name, "/".join(stray)))
        for i, block in enumerate(blocks, 1):
            label = ("a spec" if len(blocks) == 1
                     else "spec block %d" % i)
            given = [" ".join(l.tokens) for l in block["given"]]
            when = [" ".join(l.tokens) for l in block["when"]]
            expect = [" ".join(l.tokens) for l in block["expect"]]
            if not when:
                raise SpecError("workflow %s: %s needs a `when` section"
                                % (d.name, label))
            if not expect:
                raise SpecError("workflow %s: %s needs an `expect` section"
                                % (d.name, label))
            name = ("%s spec" % d.name if len(blocks) == 1
                    else "%s spec %d" % (d.name, i))
            cases.append({"name": name,
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

    The condition grammar and the resolver are the guards' own (RFC-0012): the
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
        # is true — the same rule an absent field follows (RFC-0012 §G12.4).
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
    """`effects <N>` — the total effect count; `effects complete` — no no-op step.

    `effects complete` closes issue #39's second acceptance item. A verb outside
    `lower.VERB_LEXICON` derives no Effect (issue #36), so the step runs and does
    nothing — while `expect steps N` counts it and passes, leaving the spec GREEN
    with the implementation missing. This form asserts that every step which RAN
    performed at least one effect, and names the ones that did not.

    It is opt-in rather than an automatic failure whenever the module carries an
    `unknown-verb` diagnostic, because a descriptive step is a legitimate way to
    write LNPL: the golden `examples/login.lnpl` declares three (`generate
    token`, `audit login`, `return token`), and `diagnostics.py` records that as
    intended usage. Failing every such spec would reject the golden scenario, so
    the author states the guarantee where the author means it.

    Scope is what this run executed. A no-op under a guard that closed never ran
    and is not counted here; the compile-time `unknown-verb` diagnostic is what
    reports that one, and `lnpl spec` now prints it.
    """
    tokens = phrase.split()
    if len(tokens) == 2 and tokens[1] == "complete":
        idle = [s["step"] for s in result["steps"] if not s.get("effects")]
        return not idle, ("steps with no effect: %s" % ", ".join(idle) if idle
                          else "every step performed an effect")
    if len(tokens) != 2 or not tokens[1].isdigit():
        raise SpecError("unsupported effects expectation: %r "
                        "(use `effects <N>` or `effects complete`)" % phrase)
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
    field_types = ({f["name"]: f["type"] for f in entity_node["fields"]}
                   if entity_node else {})
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
            # The declared name (`Product`) or the binding name (`product`) —
            # `rows <Entity> <N>` accepts the declared name, and issue #46
            # measured that accepting only the lowercase form here reported a
            # DECLARED entity as undeclared (t1 F-8, t2 F-12).
            target = next((e for e in entities
                           if e.get("name") == ent_name
                           or binding_name(e) == ent_name), None)
            if target is None:
                raise SpecError(
                    "given %r names %r, which is not a declared entity "
                    "(declared: %s)"
                    % (phrase, ent_name,
                       ", ".join(e.get("name", "?") for e in entities) or "none"))
            if field not in {f["name"] for f in target.get("fields", [])}:
                raise SpecError("given %r names field %r, which entity %s does "
                                "not declare" % (phrase, field, target["name"]))
            stored.setdefault(target["id"], {})[field] = _coerce(value)
        elif tokens[0] == "no" and len(tokens) == 2 and tokens[1] in fields:
            payload.pop(tokens[1], None)
        elif len(tokens) == 2 and tokens[0] in fields:
            # Integer-shaped fields coerce; everything else keeps the raw
            # string so `name 42` stays a valid Text (the pre-#39 contract).
            # The coercion exists because `check_semantic_type` for Integer is
            # an isinstance check: a raw "150" fails the validate step that the
            # JSON payload `150` passes, so the spec could not run the same
            # payload as `lnpl run` (issue #46 — t4 F-5, t2 F-11).
            payload[tokens[0]] = _typed_value(tokens[1],
                                              field_types.get(tokens[0]),
                                              refinements)
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


def _typed_value(text, type_name, refinements):
    """A `given <field> <value>` token in the declared field's shape.

    Only Integer-shaped fields (the declared type, or a refinement whose base
    is Integer) coerce a digit-string to int — Integer is the one semantic
    type whose check is an isinstance, so it is the one a raw string can never
    satisfy. A non-numeric string is left raw and fails validation loudly
    rather than being reinterpreted.
    """
    refinement = None if refinements is None else refinements.get(type_name)
    base = refinement["base"] if refinement else type_name
    if base == "Integer" and text.lstrip("-").isdigit():
        return int(text)
    return text


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


def _validated_entities(document, workflow_id):
    """The Entity nodes the workflow's semantic-type `Validation` effects name.

    The spec fixture must hold a value for every field those validations check
    (issue #48); entities the workflow never validates stay out of the payload,
    so their absence remains observable to Presence guards.
    """
    nodes = {n["id"]: n for n in document.get("nodes", [])}
    wf = nodes.get(workflow_id)
    out, seen = [], set()
    stack = list(wf.get("children", [])) if wf else []
    while stack:
        node = nodes.get(stack.pop(0))
        if node is None:
            continue
        stack.extend(node.get("children", []))
        if node.get("kind") == "Validation" \
                and node.get("rule") == "semantic-types":
            entity = nodes.get(node.get("target"))
            if entity is not None and entity.get("kind") == "Entity" \
                    and entity["id"] not in seen:
                seen.add(entity["id"])
                out.append(entity)
    return out


def run_manifest(manifest, document):
    """Execute every case. Returns (passed, failed, report_lines)."""
    entity = next((n for n in document["nodes"] if n["kind"] == "Entity"), None)
    passed, failed, lines = 0, 0, []
    for case in manifest["cases"]:
        payload, stored = _payload_from_given(case["given"], entity,
                                              refinement_index(document),
                                              document)
        # `validate <entity>` checks the entity the step names (issue #48), so
        # a payload holding only the first entity's fields fails validation of
        # any later entity. Underlay a sample for exactly the validated
        # entities — no more: merging EVERY entity would flip Presence guards
        # that read another entity's absent field (t4's `priorNotification
        # missing`). Given-derived values win on shared keys, and
        # `_payload_from_given`'s own contract (fields resolve against the
        # first entity) is unchanged.
        validated = _validated_entities(document, case["workflow"])
        if validated:
            payload = {**sample_payload(validated,
                                        refinement_index(document)),
                       **payload}
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
        case_failed = False
        for phrase in case["expect"]:
            key = phrase.split()[0]
            check = EXPECTATIONS.get(key)
            if check is None:
                failed += 1
                case_failed = True
                lines.append("FAIL %s — unsupported expectation %r (known: %s)"
                             % (case["name"], phrase, ", ".join(sorted(EXPECTATIONS))))
                continue
            ok, detail = check(phrase, result, interp)
            if ok:
                passed += 1
                lines.append("PASS %s — %s (%s)" % (case["name"], phrase, detail))
            else:
                failed += 1
                case_failed = True
                lines.append("FAIL %s — %s (%s)" % (case["name"], phrase, detail))
        # Issue #46 (t4 F-12): a run that completed with status=failed knows
        # its failed_step/failure_reason, but the report never said them —
        # diagnosing a FAIL required a separate `lnpl run` probe. One line per
        # failing case; a completed run has no failed step to report.
        if case_failed and result["status"] == "failed":
            lines.append("     reason: step=%r — %s"
                         % (result.get("failed_step"),
                            result.get("failure_reason")))
    return passed, failed, lines
