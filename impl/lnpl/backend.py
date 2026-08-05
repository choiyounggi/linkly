"""Execution mode B — Semantic IR -> MLIR -> LLVM IR -> native binary.

RFC-0004 stages S4-S7, including the custom `lnpl` dialect S4 calls for. The
dialect is defined declaratively in `mlir/lnpl.irdl.mlir` and registered into
stock `mlir-opt` with `--irdl-file`, so it needs no C++ TableGen build and adds
no build dependency beyond the `brew install llvm` mode B already required.

`_lnpl_ops` is the only place the IR is read for code generation. Two renderings
consume that op stream: `emit_lnpl_mlir` serialises it as `lnpl` dialect text
(S4), and `_render_std` lowers it to `func` + `scf` + `arith` (S5). Because both
views come from one structure, the artifact and the compiled module cannot
describe different workflows by accident; `build()` additionally runs the dialect
verifier over the emitted `lnpl` module and fails the compile if it is rejected.

Node ids survive into MLIR on both paths RFC-0004 requires: the discardable
`lnpl.node_id` attribute, whose presence and string type the dialect verifier
enforces, and a `loc("<node id>")` the debug info follows. Unrolled guards keep
one node id across their rounds and are distinguished by `lnpl.unroll_round`.

What ends up compiled is a module reproducing the workflow's **observable**
behaviour: step order, policy outcomes, exit status. The effects call into a small
C runtime shim (printf-based trace) so the native binary emits the same step lines
mode A does — that is what the differential check compares.

Two gaps remain, recorded in `rfcs/0004-compiler.md` §Open Questions: S5 consumes
the op stream rather than re-parsing the `lnpl` module, and the RFC's S3 compile
context side table does not exist, so only the compile decisions present at
emission time are materialised as attributes.

Pipeline:

    IR --emit_lnpl_mlir--> .lnpl.mlir --verify(mlir-opt --irdl-file)-->
        --_render_std--> .mlir --mlir-opt--> LLVM dialect --mlir-translate--> .ll
        --clang--> native binary
"""

import json
import os
import shutil
import subprocess
import tempfile

from lnpl.condition import parse_condition, Presence, Comparison
# The seed/key policy both modes read (issue #35). Imported, never restated: a
# second copy of the seeding rule is the defect Wave 1 removed when three seeding
# sites became one. `repo_policy` imports nothing from `interp`/`backend`/`cli`,
# so this is cycle-safe.
from lnpl.repo_policy import READ_OPS, seeded_entities

MLIR_OPT = "mlir-opt"
MLIR_TRANSLATE = "mlir-translate"
BREW_LLVM_BIN = "/opt/homebrew/opt/llvm/bin"

# This file is <repo>/impl/lnpl/backend.py, so three dirnames reach the repo.
# The dialect definition is located from here rather than from the cwd, because
# `build()` runs against an arbitrary workdir while the tests run from the root.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
LNPL_IRDL_PATH = os.path.join(REPO_ROOT, "mlir", "lnpl.irdl.mlir")
# RFC-0004 OQ①: the one committed, machine-read declaration of the pinned
# LLVM/MLIR version. Anchored on __file__ (like LNPL_IRDL_PATH), never cwd —
# `build()` runs in an arbitrary workdir.
LLVM_PIN_PATH = os.path.join(REPO_ROOT, "mlir", "llvm.pin")


class BackendError(Exception):
    """Raised when the native pipeline cannot run or produces an error."""


def tool(name):
    """Locate an LLVM/MLIR tool, preferring a keg-only homebrew install."""
    candidate = os.path.join(BREW_LLVM_BIN, name)
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    found = shutil.which(name)
    if found:
        return found
    raise BackendError(
        "%s not found. Mode B needs MLIR/LLVM tools — install them with "
        "`brew install llvm` (they land in %s)." % (name, BREW_LLVM_BIN))


def pinned_llvm_version():
    """The single pinned LLVM/MLIR version, read from mlir/llvm.pin (RFC-0004 OQ①).

    The pin file is the one machine-read declaration of the version; nothing else
    in the tree restates it. Format: one `llvm <version>` line.
    """
    with open(LLVM_PIN_PATH, encoding="utf-8") as fh:
        line = fh.readline().strip()
    parts = line.split()
    if len(parts) != 2 or parts[0] != "llvm":
        raise BackendError(
            "mlir/llvm.pin must be one line `llvm <version>`, got %r" % line)
    return parts[1]


def toolchain_available():
    for name in (MLIR_OPT, MLIR_TRANSLATE, "clang"):
        try:
            tool(name)
        except BackendError:
            return False
    return True


def verify_lnpl_module(text, stage="S4 (lnpl dialect verification)", path=None):
    """Run the `lnpl` dialect's verifier over a module; return the round trip.

    With `path`, the file at that path is verified **in place** — so the artifact
    `build()` wrote is the object that actually gets checked, and a failure names
    the file the caller can go read. Without it, `text` is staged under the repo's
    own tmp directory (never the system temp dir) and removed afterwards.

    `--mlir-print-debuginfo` is not cosmetic: without it `mlir-opt` prints no
    `loc(...)` at all, so the round trip could not show that the Location half of
    RFC-0004's two traceability paths survived. The `lnpl.node_id` attribute is
    discardable by design, which is exactly why the Location must be observable.
    """
    staged = None
    if path is None:
        tmpdir = os.path.join(REPO_ROOT, ".claude", "tmp")
        os.makedirs(tmpdir, exist_ok=True)
        # mkstemp, not a fixed name: builds can run concurrently.
        fd, staged = tempfile.mkstemp(dir=tmpdir, suffix=".lnpl.mlir")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        target = staged
    else:
        target = path

    try:
        return _run([tool(MLIR_OPT), "--irdl-file", LNPL_IRDL_PATH,
                     "--mlir-print-debuginfo", target], stage)
    finally:
        if staged is not None:
            os.remove(staged)


def _field_ident(name):
    """The emitted identifier for a condition field's logical name (RFC-0011).

    `product.stock` is a legal `Reference` and a legal MLIR SSA name, but not a
    legal C identifier — `int64_t product.stock` does not compile. This is the
    ONE place the logical name becomes an identifier; `emit_mlir`'s signature and
    guard comparisons and `runtime_c`'s declaration and call site all route
    through it.

    Every other surface keeps the logical name: `condition_field_names`, the
    field order persisted next to the binary, `run_binary`'s value mapping, and
    the CLI's `--field NAME=VALUE`. Mangling is what the emitter needs, not what
    the operator types.
    """
    return name.replace(".", "__")


def _extract_condition_field(cond_str):
    """RFC-0008 G8: Extract field name from condition string.

    Returns (field_name, op, value) for Comparison or (field_name, 'exists'|'missing') for Presence.
    Used to populate lnpl_run parameter list and generate arith.cmpi code.
    """
    try:
        cond = parse_condition(cond_str)
    except Exception:
        return None

    if isinstance(cond, Presence):
        return (cond.field, cond.kind)  # (field, 'exists'|'missing')
    elif isinstance(cond, Comparison):
        return (cond.field, cond.op, cond.value)  # (field, op, value_ms)
    return None


def _compile_condition(cond_str, field_var_name):
    """RFC-0008 G8: Compile condition to MLIR i1 predicate using field parameter.

    Args:
        cond_str: condition string (e.g., "counter >= 10")
        field_var_name: MLIR variable name for the field (e.g., "%counter")

    Returns:
        MLIR code that evaluates the condition (e.g., "%cond = arith.cmpi sge, %counter, %c10 : i64")
    """
    extracted = _extract_condition_field(cond_str)
    if not extracted:
        return None

    if len(extracted) == 2:  # Presence
        field, kind = extracted
        # Presence: check if field is not null/zero
        # For now, field existence is assumed true (parameter presence means it exists)
        return "%c1"
    elif len(extracted) == 3:  # Comparison
        field, op, value = extracted
        # Comparison: field op value (value is already in milliseconds if Duration)
        # Convert op to arith.cmpi predicate
        op_map = {
            '<': 'slt',
            '<=': 'sle',
            '>': 'sgt',
            '>=': 'sge',
            '==': 'eq',
            '!=': 'ne',
        }
        pred = op_map.get(op)
        if not pred:
            return "%c1"
        # Generate: %cond = arith.cmpi <pred>, %field, %const : i64
        return f"arith.cmpi {pred}, {_field_ident(field_var_name)}, %c{value} : i64"
    return "%c1"


# ---- S4: Semantic IR -> MLIR (standard dialects) ---------------------------

_UNTIL_ROUND_CAP = 16


def _steps_in_order(nodes, ids, out):
    """Flatten the body the way mode A does, so both modes agree on step order.

    Guards are resolved at compile time only when their outcome is decidable from
    the IR alone; `when` is not, so a guarded step is emitted with a runtime flag
    the caller supplies. `repeat` and `until` are constants, so they unroll.

    RFC-0008 G10: until unrolls to _UNTIL_ROUND_CAP iterations (matching Mode A).
    Condition evaluation deferred to runtime (see _compile_condition).
    """
    for nid in ids:
        node = nodes[nid]
        kind = node["kind"]
        if kind == "WorkflowStep":
            out.append((node, None))
        elif kind in ("Concurrency", "Pipeline"):
            _steps_in_order(nodes, node.get("children", []), out)
        elif kind == "Guard":
            if node["mode"] == "repeat":
                for _ in range(int(node["count"])):
                    _steps_in_order(nodes, node.get("children", []), out)
            elif node["mode"] == "when":
                # RFC-0008 G9: when becomes arith.cmpi + scf.if
                inner = []
                _steps_in_order(nodes, node.get("children", []), inner)
                for step, _cond in inner:
                    out.append((step, ("when", node.get("condition"))))
            elif node["mode"] == "until":
                # RFC-0008 G10: until unrolls to round_cap (16) iterations.
                # Condition evaluation deferred; unrolling ensures Mode A ≈ Mode B.
                inner = []
                _steps_in_order(nodes, node.get("children", []), inner)
                for _ in range(_UNTIL_ROUND_CAP):
                    for step, _cond in inner:
                        out.append((step, ("until", node.get("condition"))))
            else:
                raise BackendError("unknown guard mode %r" % node["mode"])
        else:
            raise BackendError("workflow body cannot contain %s" % kind)
    return out


# `until c` repeats while c is false, so each unrolled round is guarded by the
# negation of the condition's comparison.
_NEGATED_CMP = {"<": "sge", "<=": "sgt", ">": "sle", ">=": "slt",
                "==": "ne", "!=": "eq"}


def _workflow_steps(document, workflow_id):
    nodes = {n["id"]: n for n in document["nodes"]}
    wf = nodes.get(workflow_id)
    if wf is None or wf["kind"] != "Workflow":
        raise BackendError("no such workflow: %r" % workflow_id)
    return nodes, _steps_in_order(nodes, wf.get("children", []), [])


def condition_field_names(document, workflow_id):
    """RFC-0008 G8: the ordered condition-field list `lnpl_run` takes as i64 params.

    Single source of truth. `emit_mlir` builds the signature from this, `runtime_c`
    declares and forwards exactly these, and `run_binary` supplies values in this
    order. C linkage matches on symbol name only, so if any of the three derived
    the list independently a disagreement would surface as an uninitialised
    register rather than a link error.
    """
    _, steps = _workflow_steps(document, workflow_id)
    fields = set()
    for _step, cond in steps:
        if cond and isinstance(cond, tuple) and len(cond) == 2:
            _mode, cond_str = cond
            extracted = _extract_condition_field(cond_str)
            if extracted:
                fields.add(extracted[0])
    return sorted(fields)


def encode_condition_value(value):
    """Coerce a condition-field value to the i64 the guard compares against.

    `bool` is accepted because it is an `int` in Python and 0/1 is a meaningful
    i64. Everything else non-integral is rejected rather than truncated, so a
    guard never silently compares against a rounded or coerced value.
    """
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return value
    raise BackendError(
        "condition field value must be an integer, got %r (%s)"
        % (value, type(value).__name__))


def _constraints_of_kind(document, workflow_id, kind):
    """The owning service's constraint nodes of one `kind`, in declared order.

    Mirrors the interpreter's constraint resolution (interp `_constraints`): the
    `Service` whose children include the workflow, then its `constraints` list.
    One lookup shared by every derivation below, so a second reading of "which
    service owns this workflow" cannot drift from the first.
    """
    nodes = {n["id"]: n for n in document["nodes"]}
    service = next((n for n in document["nodes"]
                    if n["kind"] == "Service"
                    and workflow_id in n.get("children", [])), None)
    if service is None:
        return []
    return [nodes[cid] for cid in service.get("constraints", [])
            if nodes.get(cid) is not None and nodes[cid].get("kind") == kind]


def _has_cache_budget(document, workflow_id):
    """True if the service owning `workflow_id` declares a cache TTL budget.

    RFC-0003 requires every cache key to carry a TTL, so without this budget a
    `CacheAccess set` cannot run — mode A raises, and mode B must agree.
    """
    for node in _constraints_of_kind(document, workflow_id, "Performance"):
        for budget in node.get("budgets", []):
            if budget.get("metric") == "cache":
                return True
    return False


# --- the retry model, mirrored from the interpreter ---------------------------
#
# RFC-0004 §실행 모드와 semantic equivalence names "정책 집행 결과 — retry 판정"
# as observable 2 and "관측성 신호 — trace 구조(step = span)" as observable 3, so
# how many times a failing step ran is part of the contract, not a timing detail.
# It shows up in the trace because `interp._run_step` re-runs every effect the
# step owns on each attempt while `_run_effect` appends its child span before the
# raise: mode A's failing step holds one copy of the failing prefix per attempt.
#
# These constants MIRROR `interp` rather than importing it. Mode B must not depend
# on mode A — an `import interp` here is the first thing an audit of "does mode B
# read mode A?" would flag — and `_has_cache_budget` set the same precedent for
# constraint resolution. The cost of a mirror is drift, so the guard against it is
# `TestModeBDerivesRetryAttempts`, which checks the derived attempt count against
# mode A's actual trace over a (retry × timeout × position) matrix rather than
# against a restatement of the rule. If a third consumer ever needs this model,
# extract it to a neutral module instead of adding a second mirror.
_STEP_COST_MS = 5        # interp `Clock.step_cost_ms`, advanced once per step
_READ_MISS_COST_MS = 1   # interp `_run_effect` advances 1ms before raising

# RFC-0003 §retry 멱등 판정 기준, as interp `IDEMPOTENT_OPS` encodes it.
_IDEMPOTENT_OPS = {
    ("RepositoryCall", "read"), ("RepositoryCall", "query"),
    ("RepositoryCall", "delete"), ("RepositoryCall", "update"),
    ("CacheAccess", "get"), ("CacheAccess", "set"), ("CacheAccess", "invalidate"),
}


def _backoff_ms(attempt):
    """Capped exponential backoff — interp `_backoff_ms`, deterministic (no jitter)."""
    return min(100 * (2 ** (attempt - 1)), 1000)


def _duration_ms(text):
    """`3s` -> 3000. Mirrors interp `_duration_ms`, raising a BackendError instead."""
    for unit, mult in (("ms", 1), ("s", 1000), ("m", 60000)):
        if str(text).endswith(unit):
            head = str(text)[: -len(unit)]
            if head.isdigit():
                return int(head) * mult
    raise BackendError("not a duration: %r" % text)


def _retry_policy(document, workflow_id):
    """`(retry, timeout_ms)` from the owning service's `Policy` constraints."""
    retry, timeout_ms = 0, None
    for node in _constraints_of_kind(document, workflow_id, "Policy"):
        for rule in node.get("rules", []):
            if rule["name"] == "retry":
                retry = int(rule["value"])
            elif rule["name"] == "timeout":
                timeout_ms = _duration_ms(rule["value"])
    return retry, timeout_ms


def _failure_attempts(nodes, op, fail_at, steps_before, retry, timeout_ms):
    """How many times mode A runs `op` before giving up on its failing effect.

    This is interp's retry loop and nothing more (`run_workflow`'s while/except
    plus `_retryable`), evaluated statically:

      * the step is retryable only if EVERY effect it owns is idempotent — the
        whole step re-runs, so one non-idempotent effect disqualifies all of them.
        That is what makes a create conflict a single attempt at any budget;
      * the deadline is absolute, so the clock matters: each preceding step costs
        `_STEP_COST_MS`, and a failing read costs `_READ_MISS_COST_MS` per attempt
        (`Cache.set` and a create conflict raise without advancing).

    `steps_before` counts every op ahead of this one, which assumes each of them
    ran. That is exact when none is guarded, and part of the same guarded-effect
    limitation documented in `_lnpl_ops`: a guard's truth is a per-run fact this
    compile-time derivation cannot know.
    """
    if retry <= 0:
        return 1
    for effect in op["effects"]:
        kind = effect["kind"]
        operation = nodes[effect["node_id"]].get("operation")
        if kind in ("RepositoryCall", "CacheAccess") \
                and (kind, operation) not in _IDEMPOTENT_OPS:
            return 1
        if kind in ("NetworkCall", "EventEmit"):
            return 1

    failing = nodes[op["effects"][fail_at]["node_id"]]
    per_attempt = (_READ_MISS_COST_MS
                   if op["effects"][fail_at]["kind"] == "RepositoryCall"
                   and failing.get("operation") in READ_OPS else 0)

    clock = _STEP_COST_MS * steps_before
    attempts = 1
    while True:
        clock += per_attempt
        if attempts > retry:
            return attempts
        if timeout_ms is not None and clock + _backoff_ms(attempts) >= timeout_ms:
            return attempts
        clock += _backoff_ms(attempts)
        attempts += 1


def _walk_markers(nodes, ids, out):
    """Pre-order DFS: append one marker tuple per structural node, then recurse.

    A marker is `(op_name, node_id, extra_attr_pairs)`. `WorkflowStep`s are not
    markers — their ids and effects come from `_lnpl_ops`; their children are
    effects, not structural, so we do not recurse into them.
    """
    for nid in ids:
        node = nodes[nid]
        kind = node["kind"]
        if kind == "Concurrency":
            out.append(("lnpl.concurrency", nid, [
                ("lnpl.mode", node.get("mode")),
                ("lnpl.children", list(node.get("children", []))),
            ]))
            _walk_markers(nodes, node.get("children", []), out)
        elif kind == "Pipeline":
            out.append(("lnpl.pipeline", nid, [
                ("lnpl.name", node.get("name")),
                ("lnpl.children", list(node.get("children", []))),
            ]))
            _walk_markers(nodes, node.get("children", []), out)
        elif kind == "Guard":
            out.append(("lnpl.guard", nid, [
                ("lnpl.mode", node.get("mode")),
                ("lnpl.guard_condition", node.get("condition")),
                ("lnpl.count", node.get("count")),
                ("lnpl.children", list(node.get("children", []))),
            ]))
            _walk_markers(nodes, node.get("children", []), out)


def _structural_markers(document, workflow_id):
    """RFC-0004 ③/④: flat marker ops for Guard/Concurrency/Pipeline nodes.

    `_steps_in_order` flattens these structural nodes out of the step stream, so
    their ids never reached the artifact (③) and a parallel workflow was
    byte-identical to its sequential form (④). This walks the *un-flattened* node
    tree and materialises one marker op per structural node, carrying its id,
    mode, and ordered immediate children. It reads only the node tree — the
    step/effect stream (`_lnpl_ops`) is neither read nor modified here.
    """
    nodes = {n["id"]: n for n in document["nodes"]}
    wf = nodes.get(workflow_id)
    if wf is None or wf["kind"] != "Workflow":
        raise BackendError("no such workflow: %r" % workflow_id)
    markers = []
    _walk_markers(nodes, wf.get("children", []), markers)
    return markers


def _lnpl_ops(document, workflow_id, seeded=None):
    """S4: the `lnpl` op stream, plus the module-level attributes.

    `seeded` is the run's seed condition — the set of entity ids that start with a
    row. `None` means the default role-based policy
    (`repo_policy.seeded_entities`); `frozenset()` is the `--no-row` case. It is
    the ONE input mode B derives its repository outcome from, and mode A is given
    the same condition materialised as rows, so neither mode reads the other's
    answer (the arrangement `_derive_skip_from_payload` uses for the skip flag).

    This is the one place the Semantic IR is read for code generation. Both
    renderings consume the result — `emit_lnpl_mlir` serialises it as `lnpl`
    dialect text and `_render_std` lowers it to standard dialects — so the two
    modules cannot describe different workflows by construction.

    Steps come from `_workflow_steps`, which calls the module-global
    `_steps_in_order`. That indirection is load-bearing: the deliberate-mismatch
    tests monkeypatch that name, and flattening the body here instead would
    disarm them. `TestOpStreamRoutesThroughStepsInOrder` pins it.
    """
    nodes, steps = _workflow_steps(document, workflow_id)

    # Two passes. A node id repeats only when an unrolled guard emitted it more
    # than once — `until` (guarded rounds) or `repeat` (no guard attached at all)
    # — and RFC-0004's 1:다 확장 rule wants every one of those ops to keep the
    # same id. Counting first keeps the round marker off the ordinary case, where
    # a bare index already identifies the op.
    occurrences = {}
    for step, _cond in steps:
        occurrences[step["id"]] = occurrences.get(step["id"], 0) + 1

    rounds = {}
    ops = []
    for idx, (step, cond) in enumerate(steps, start=1):
        node_id = step["id"]
        guard_mode = guard_condition = None
        if cond and isinstance(cond, tuple) and len(cond) == 2:
            guard_mode, guard_condition = cond

        unroll_round = None
        if occurrences[node_id] > 1:
            rounds[node_id] = rounds.get(node_id, 0) + 1
            unroll_round = rounds[node_id]

        ops.append({
            "node_id": node_id,
            "name": step["name"],
            "index": idx,
            "guard_mode": guard_mode,
            "guard_condition": guard_condition,
            "unroll_round": unroll_round,
            # Read `children` off the dict we were handed rather than off
            # `document`: one divergence test strips them to prove the
            # differential check can go red, and re-reading the document would
            # put the effects back and silently disarm it.
            "effects": [{"node_id": child_id, "kind": nodes[child_id]["kind"]}
                        for child_id in step.get("children", [])],
        })

    module_attrs = {
        "lnpl.module": document["module"],
        "lnpl.lir_version": document["lir_version"],
        "lnpl.workflow": workflow_id,
        # From the single source of truth, never re-derived here: three sites
        # deriving this list independently is the defect PR #4 existed to fix.
        "lnpl.condition_fields": condition_field_names(document, workflow_id),
    }

    # RFC-0003 / issue #9: mode A refuses a `CacheAccess set` that has no cache-TTL
    # budget — interp `Cache.set` raises, and the run's status becomes "failed".
    # Mode B used to print the effect and complete, so the two modes disagreed on
    # exactly that workflow. Budget presence is a static (compile-time) property of
    # the owning service, so mode B reaches the same *observable* outcome without
    # any new runtime parameter: when the budget is absent, the run stops at the
    # first unconditional such set and reports "failed".
    #
    # The trace is matched to mode A precisely. In `_run_effect`, the failing
    # step's effects run in order; the cache effect's child span is appended
    # BEFORE `Cache.set` raises, and effects after it never run. So mode A's
    # failing step holds the effects up to and INCLUDING the cache set, and no
    # later step. Truncate to exactly that — both the trailing effects of the
    # failing step and every later step — or a multi-effect step would make mode B
    # emit effects mode A never reached. Guarded sets are left alone: a skipped set
    # is never reached, so it must not force a failure.
    #
    # Issue #35 adds the repository failures to the same scan, because mode A has
    # exactly ONE failure point — `run_workflow` breaks out of the step loop at the
    # first failed step — so two independent scans could disagree about which
    # failure comes first. What makes the repository answerable statically is the
    # single-key invariant `repo_policy` establishes: one run has one payload, so
    # every call against entity E addresses the same key and each entity's table
    # holds at most one row. "Does E's create conflict?" therefore reduces to a
    # document-derivable question — E conflicts iff it is seeded or an earlier
    # call already created it — with no interpreter state and no runtime channel.
    #
    # KNOWN LIMITATION, deliberate. A guarded op is skipped in BOTH directions: it
    # cannot force a failure, and it cannot record a create either. The first is
    # the cache rule's reason (a guard may never be taken, so failing the run on it
    # would invent a failure mode A never has). The second follows from the same
    # uncertainty — crediting a create that may not happen would make a LATER
    # unguarded create conflict for a row that was never written. So: a repository
    # failure inside a guard that IS taken at runtime is not reproduced here. The
    # honest alternative would be to evaluate guards statically, which the payload
    # forbids — a guard's truth is a per-run fact, and mode B specialises at
    # compile time. Reported rather than papered over.
    #
    # A shipped example now contains a guarded repository call: `create order` in
    # `examples/checkout.lnpl` sits under `when product.stock > 0`, the exact
    # read-then-create shape issue #35 names. It is safe for a reason, not by
    # exemption — `entity.order` is create-only, so the role-based seed never
    # writes it and no earlier call creates it, and a create against an entity
    # nothing holds inserts rather than conflicts. So there is nothing for the
    # skip above to lose. That is a claim about consequences, so it is checked as
    # one: `test_no_shipped_example_has_a_guarded_repository_call_that_can_fail`
    # re-derives, for every example and both seeds the policy can produce, whether
    # any guarded call could fail, and goes red on the first that could.
    terminal_status = None
    has_cache_budget = _has_cache_budget(document, workflow_id)
    seeded_now = set(seeded_entities(document, workflow_id) if seeded is None
                     else seeded)
    created = set()
    for cut, op in enumerate(ops):
        if op["guard_mode"] is not None:
            continue
        fail_at = None
        for index, effect in enumerate(op["effects"]):
            node = nodes[effect["node_id"]]
            kind, operation = effect["kind"], node.get("operation")
            if kind == "CacheAccess" and operation == "set" and not has_cache_budget:
                fail_at = index
            elif kind == "RepositoryCall" and operation in READ_OPS:
                if node["entity"] not in seeded_now and node["entity"] not in created:
                    fail_at = index
            elif kind == "RepositoryCall" and operation == "create":
                if node["entity"] in seeded_now or node["entity"] in created:
                    fail_at = index
                else:
                    created.add(node["entity"])
            if fail_at is not None:
                break
        if fail_at is not None:
            retry, timeout_ms = _retry_policy(document, workflow_id)
            attempts = _failure_attempts(nodes, op, fail_at, cut, retry, timeout_ms)
            truncated = dict(op)
            # One copy of the failing prefix per attempt: mode A re-runs the whole
            # step each time and its child spans accumulate on one span. The
            # multiplicity lives in the op stream, so `emit_lnpl_mlir` and
            # `_render_std` expand it identically — one structure, two views.
            truncated["effects"] = op["effects"][:fail_at + 1] * attempts
            ops = ops[:cut] + [truncated]
            terminal_status = "failed"
            break
    if terminal_status is not None:
        module_attrs["lnpl.terminal_status"] = terminal_status

    return module_attrs, ops


def _mlir_escape(text):
    r"""Escape a Python string for an MLIR string literal.

    The backslash must go first, or escaping the quote would produce one. Getting
    this wrong is silent rather than loud for some inputs: the grammar accepts
    step names with arbitrary characters (the lexer splits on whitespace), so a
    name containing a literal `\n` emitted unescaped becomes a real newline that
    MLIR accepts and the C shim prints as two trace lines. `\b` at least fails
    loudly with "unknown escape in string literal".
    """
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _mlir_str(text):
    return '"%s"' % _mlir_escape(text)


def _mlir_attr(value):
    """Render one attribute value. Ints carry an explicit i64 type."""
    if isinstance(value, bool):
        raise BackendError("boolean attributes are not part of the lnpl dialect")
    if isinstance(value, int):
        return "%d : i64" % value
    if isinstance(value, (list, tuple)):
        return "[%s]" % ", ".join(_mlir_str(item) for item in value)
    return _mlir_str(value)


def _mlir_attr_dict(pairs):
    return ", ".join("%s = %s" % (key, _mlir_attr(value))
                     for key, value in pairs if value is not None)


def emit_lnpl_mlir(document, workflow_id, seeded=None):
    """S4: Semantic IR -> `lnpl` dialect MLIR.

    `seeded` is the run's seed condition; see `_lnpl_ops`.

    Every op carries the originating node id on both paths RFC-0004 requires: the
    discardable attribute `lnpl.node_id` that passes read, and a `loc(...)` that
    diagnostics and debug info follow. The dialect's verifier enforces the
    attribute's presence and type (see `mlir/lnpl.irdl.mlir`); `build()` runs that
    verifier over the emitted module, so a module that loses a node id fails the
    compile rather than producing a binary that cannot be traced back.
    """
    module_attrs, ops = _lnpl_ops(document, workflow_id, seeded)

    lines = [
        "// Generated from Semantic IR (lir_version %s, module %s) — do not edit."
        % (module_attrs["lnpl.lir_version"], module_attrs["lnpl.module"]),
        "// RFC-0004 S4: the custom `lnpl` dialect, registered into stock",
        "// mlir-opt via --irdl-file=mlir/lnpl.irdl.mlir (no C++ TableGen build).",
        "module attributes {%s} {" % _mlir_attr_dict(sorted(module_attrs.items())),
    ]

    # RFC-0004 ③/④: structural marker ops (from the un-flattened node tree) as a
    # prefix block, so Guard/Concurrency/Pipeline ids reach the artifact and a
    # parallel workflow differs from its sequential form. `_lnpl_ops`'s step/effect
    # stream below is untouched, so the standard-dialect lowering is unchanged.
    for opname, node_id, extra in _structural_markers(document, workflow_id):
        lines.append('  "%s"() {%s} : () -> () loc(%s)' % (
            opname,
            _mlir_attr_dict([("lnpl.node_id", node_id)] + extra),
            _mlir_str(node_id)))

    for op in ops:
        lines.append('  "lnpl.step"() {%s} : () -> () loc(%s)' % (
            _mlir_attr_dict([
                ("lnpl.node_id", op["node_id"]),
                ("lnpl.name", op["name"]),
                ("lnpl.index", op["index"]),
                ("lnpl.guard_mode", op["guard_mode"]),
                ("lnpl.guard_condition", op["guard_condition"]),
                ("lnpl.unroll_round", op["unroll_round"]),
            ]),
            _mlir_str(op["node_id"])))
        for effect in op["effects"]:
            lines.append('  "lnpl.effect"() {%s} : () -> () loc(%s)' % (
                _mlir_attr_dict([
                    ("lnpl.node_id", effect["node_id"]),
                    ("lnpl.kind", effect["kind"]),
                    ("lnpl.step", op["node_id"]),
                ]),
                _mlir_str(effect["node_id"])))

    lines.append("}")
    return "\n".join(lines) + "\n"


def _render_std(module_attrs, ops):
    """S5: the `lnpl` op stream -> standard-dialect MLIR (func, arith, scf).

    Reads nothing but the op stream, so this rendering and the `lnpl` module
    `emit_lnpl_mlir` writes are two views of one structure rather than two
    independent readings of the IR.
    """
    lines = [
        "// Generated from Semantic IR (lir_version %s, module %s) — do not edit."
        % (module_attrs["lnpl.lir_version"], module_attrs["lnpl.module"]),
        "// RFC-0004 S5: standard dialects (func, arith), lowered from the `lnpl`",
        "// dialect module emitted at S4 (see mlir/lnpl.irdl.mlir).",
        "module {",
        '  func.func private @lnpl_step(!llvm.ptr, i32) -> i32',
        '  func.func private @lnpl_effect(!llvm.ptr, !llvm.ptr) -> ()',
        "",
    ]
    # String globals for the step and effect names.
    strings = {}

    def intern(text):
        if text not in strings:
            strings[text] = "s%d" % len(strings)
        return strings[text]

    # This order decides the @s<N> numbering and therefore the emitted bytes:
    # each step's name first, then that step's effect kinds, in order.
    for op in ops:
        intern(op["name"])
        for effect in op["effects"]:
            intern(effect["kind"])

    for text, sym in strings.items():
        # Shares _mlir_escape with the lnpl rendering. This line previously
        # escaped only the quote, which let a name containing a literal `\n`
        # become a real newline in the global — the C shim then printed two trace
        # lines and the differential check reported a divergence that was an
        # emitter bug, not a backend disagreement. No fixture contains a
        # backslash, so the fix does not move any recorded byte.
        encoded = _mlir_escape(text)
        lines.append('  llvm.mlir.global internal constant @%s("%s\\00")'
                     % (sym, encoded))
    lines.append("")

    # RFC-0008 G8: condition fields become i64 parameters, in the one order
    # condition_field_names defines (see its docstring for why that matters).
    params = ["%skip : i32"]
    for field in module_attrs["lnpl.condition_fields"]:
        params.append(f"%{_field_ident(field)} : i64")
    params_str = ", ".join(params)

    lines.append(f"  func.func @lnpl_run({params_str}) -> i32 {{")
    lines.append("    %c0 = arith.constant 0 : i32")
    lines.append("    %c1 = arith.constant 1 : i32")

    # Declare i64 constants for condition comparisons
    # Collect all i64 values used in condition comparisons
    cond_i64_values = set()
    for entry in ops:
        if entry["guard_condition"]:
            extracted = _extract_condition_field(entry["guard_condition"])
            if extracted and len(extracted) == 3:  # Comparison
                cond_i64_values.add(extracted[2])

    # Declare all i64 constants upfront
    for value in sorted(cond_i64_values):
        lines.append(f"    %c{value}_i64 = arith.constant {value} : i64")

    # `entry`, not `op` — the guard branches below unpack `field, op, value` from
    # a parsed condition, and a loop named `op` would be shadowed mid-body.
    for entry in ops:
        idx = entry["index"]
        sym = strings[entry["name"]]
        guard_mode = entry["guard_mode"]
        guard_str = entry["guard_condition"]

        guard_desc = ""
        if guard_mode and guard_str:
            guard_desc = "  (guarded by `%s` %s)" % (guard_mode, guard_str)

        lines.append("    // step %d: %s%s"
                     % (idx, entry["name"], guard_desc))
        lines.append("    %%p%d = llvm.mlir.addressof @%s : !llvm.ptr" % (idx, sym))
        lines.append("    %%i%d = arith.constant %d : i32" % (idx, idx))

        if guard_mode == "when":
            # RFC-0008 G8-G9: when becomes scf.if with condition evaluation
            extracted = _extract_condition_field(guard_str) if guard_str else None

            if extracted and len(extracted) == 3:  # Comparison
                field, op, value = extracted
                op_map = {'<': 'slt', '<=': 'sle', '>': 'sgt', '>=': 'sge', '==': 'eq', '!=': 'ne'}
                pred = op_map.get(op, 'eq')
                # Generate comparison: %cond_idx = arith.cmpi pred, %field, %const : i64
                # Use pre-declared constant %c<value>_i64
                lines.append(f"    %cond{idx} = arith.cmpi {pred}, "
                             f"%{_field_ident(field)}, %c{value}_i64 : i64")
                lines.append(f"    scf.if %cond{idx} {{")
            else:
                # Presence or unparseable: use caller-supplied skip flag
                # skip=1 means "skip condition evaluation and execute", so we negate it
                lines.append("    %%skip%d = arith.cmpi eq, %%skip, %%c0 : i32" % idx)
                lines.append("    scf.if %%skip%d {" % idx)

            # RFC-0008: When condition is true, execute the guarded step
            lines.append("      %%r%d = func.call @lnpl_step(%%p%d, %%i%d) : "
                         "(!llvm.ptr, i32) -> i32" % (idx, idx, idx))
            for cn, effect in enumerate(entry["effects"]):
                ksym = strings[effect["kind"]]
                lines.append("      %%k%d_%d = llvm.mlir.addressof @%s : !llvm.ptr"
                             % (idx, cn, ksym))
                lines.append("      func.call @lnpl_effect(%%p%d, %%k%d_%d) : "
                             "(!llvm.ptr, !llvm.ptr) -> ()" % (idx, idx, cn))
            lines.append("    }")
        elif guard_mode == "until":
            # RFC-0008 G10 / issue #3. `_steps_in_order` has already unrolled the
            # loop to _UNTIL_ROUND_CAP, so what is left is to make each round obey
            # the condition instead of running unconditionally — which is what made
            # mode B behave as though the condition never became true.
            #
            # `until c` repeats *while `c` is false*, so each round is guarded by the
            # negation of c. Nothing in the IR mutates a condition field mid-run, so
            # c is constant across the workflow and this yields the same two outcomes
            # mode A can produce: zero rounds, or the cap.
            extracted = _extract_condition_field(guard_str) if guard_str else None
            round_guard = None
            if extracted and len(extracted) == 3:
                field, op, value = extracted
                negated = _NEGATED_CMP.get(op)
                if negated:
                    round_guard = ("    %%ucond%d = arith.cmpi %s, %%%s, %%c%s_i64 "
                                   ": i64" % (idx, negated, _field_ident(field),
                                              value))

            if round_guard:
                lines.append(round_guard)
                lines.append("    scf.if %%ucond%d {" % idx)
                body, close = "      ", ["    }"]
            else:
                # Presence or unparseable: no evaluator, so keep the previous
                # unconditional emission rather than inventing a decision.
                body, close = "    ", []

            lines.append("%s%%r%d = func.call @lnpl_step(%%p%d, %%i%d) : "
                         "(!llvm.ptr, i32) -> i32" % (body, idx, idx, idx))
            for cn, effect in enumerate(entry["effects"]):
                ksym = strings[effect["kind"]]
                lines.append("%s%%k%d_%d = llvm.mlir.addressof @%s : !llvm.ptr"
                             % (body, idx, cn, ksym))
                lines.append("%sfunc.call @lnpl_effect(%%p%d, %%k%d_%d) : "
                             "(!llvm.ptr, !llvm.ptr) -> ()" % (body, idx, idx, cn))
            lines.extend(close)
        else:
            # No guard: unconditional step
            lines.append("    %%r%d = func.call @lnpl_step(%%p%d, %%i%d) : "
                         "(!llvm.ptr, i32) -> i32" % (idx, idx, idx))
            for cn, effect in enumerate(entry["effects"]):
                ksym = strings[effect["kind"]]
                lines.append("    %%k%d_%d = llvm.mlir.addressof @%s : !llvm.ptr"
                             % (idx, cn, ksym))
                lines.append("    func.call @lnpl_effect(%%p%d, %%k%d_%d) : "
                             "(!llvm.ptr, !llvm.ptr) -> ()" % (idx, idx, cn))

    # issue #9: a run that reached an unbudgeted CacheAccess set returns non-zero,
    # which the C shim renders as `status failed` — the same outcome mode A gives.
    ret_val = "%c1" if module_attrs.get("lnpl.terminal_status") == "failed" else "%c0"
    lines.append("    return %s : i32" % ret_val)
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines) + "\n"


def emit_mlir(document, workflow_id, seeded=None):
    """Semantic IR -> standard-dialect MLIR, by way of the `lnpl` dialect (S4-S5).

    `seeded` is the run's seed condition; see `_lnpl_ops`.

    The op stream this renders is the one `emit_lnpl_mlir` serialises, so the
    standard-dialect module and the `lnpl` module cannot describe different
    workflows. The signature and the output are unchanged from before the dialect
    existed; `impl/tests/golden/` holds the pre-change bytes that prove it.
    """
    return _render_std(*_lnpl_ops(document, workflow_id, seeded))


RUNTIME_C_HEADER = r"""/* Mode B runtime shim — generated, do not edit.
 * Emits the same observable step trace mode A does, so the differential check
 * compares behaviour rather than formatting.
 *
 * RFC-0008 G8: condition field values arrive as command-line arguments —
 * argv[1] is the skip flag and argv[2..] are the i64 condition fields, in the
 * order condition_field_names() defines. The declaration and the forwarding
 * below are generated from that same list, because C linkage matches on symbol
 * name only: a hand-written declaration that disagreed with the MLIR signature
 * would compile and link, then read an uninitialised register.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

int lnpl_step(const char *name, int index) {
  printf("step %d %s\n", index, name);
  return 0;
}

void lnpl_effect(const char *step, const char *kind) {
  printf("effect %s %s\n", step, kind);
}
"""


def runtime_c(field_names):
    """Generate the mode B shim for exactly `field_names` (ordered).

    Kept in lockstep with `emit_mlir` by taking the same list, so the arity and
    the positional meaning of `lnpl_run`'s parameters cannot drift.
    """
    idents = [_field_ident(f) for f in field_names]
    decl_params = ", ".join(["int skip"] + ["int64_t %s" % f for f in idents])
    reads = "\n".join(
        "  int64_t %s = (argc > %d) ? strtoll(argv[%d], NULL, 10) : 0;"
        % (f, i, i)
        for i, f in enumerate(idents, start=2))
    call_args = ", ".join(["skip"] + idents)
    fields_note = ", ".join("argv[%d]=%s" % (i, f)
                            for i, f in enumerate(field_names, start=2)) or "none"
    return (
        RUNTIME_C_HEADER
        + "\n/* Condition fields: %s */\n" % fields_note
        + "int lnpl_run(%s);\n\n" % decl_params
        + "int main(int argc, char **argv) {\n"
        + "  int skip = (argc > 1 && argv[1][0] == '1') ? 1 : 0;\n"
        + (reads + "\n" if reads else "")
        + "\n  int rc = lnpl_run(%s);\n" % call_args
        + '  printf("status %s\\n", rc == 0 ? "completed" : "failed");\n'
        + "  return rc;\n}\n")


def build(document, workflow_id, workdir, keep_intermediate=True, seeded=None):
    """Run S4-S7. Returns the path to the native binary.

    `seeded` is the run's seed condition (see `_lnpl_ops`): it specialises the
    module, exactly as the cache-TTL budget does. A runtime flag was the
    alternative, and it is the wrong one — deciding the repository outcome at run
    time means the generated module branches on repository state, which is a
    store inside the native runtime. Mode B is rebuilt per `observe_mode_b` call
    anyway, so specialising costs nothing.

    Stages on disk, in order: `module.lnpl.mlir` (S4, verified against the `lnpl`
    dialect), `module.mlir` (S5 standard dialects), `module.llvm.mlir` (S6),
    `module.ll`, and the binary (S7).
    """
    os.makedirs(workdir, exist_ok=True)
    lnpl_path = os.path.join(workdir, "module.lnpl.mlir")
    mlir_path = os.path.join(workdir, "module.mlir")
    llvm_dialect = os.path.join(workdir, "module.llvm.mlir")
    ll_path = os.path.join(workdir, "module.ll")
    c_path = os.path.join(workdir, "runtime.c")
    bin_path = os.path.join(workdir, "module")

    fields = condition_field_names(document, workflow_id)

    # S4. Written before it is verified, so a rejected module is on disk to read.
    # The gate is not advisory: RFC-0004 treats a decision that failed to
    # materialise as a failed conversion, so nothing downstream runs and no
    # binary appears. `path=` verifies this file rather than a staged copy, which
    # keeps the artifact and the verified object the same thing.
    lnpl_text = emit_lnpl_mlir(document, workflow_id, seeded)
    with open(lnpl_path, "w", encoding="utf-8") as fh:
        fh.write(lnpl_text)
    verify_lnpl_module(lnpl_text, path=lnpl_path)

    with open(mlir_path, "w", encoding="utf-8") as fh:
        fh.write(emit_mlir(document, workflow_id, seeded))
    with open(c_path, "w", encoding="utf-8") as fh:
        fh.write(runtime_c(fields))
    # Persist the parameter order next to the binary so run_binary binds values by
    # name instead of re-deriving an order that could disagree with the build.
    with open(_fields_path(bin_path), "w", encoding="utf-8") as fh:
        json.dump(fields, fh)

    # scf -> cf -> llvm: without --convert-cf-to-llvm the branches a `when` guard
    # produces stop at the cf dialect, and mlir-translate cannot read them.
    _run([tool(MLIR_OPT), mlir_path,
          "--convert-scf-to-cf", "--convert-cf-to-llvm",
          "--convert-func-to-llvm", "--convert-arith-to-llvm",
          "--reconcile-unrealized-casts",
          "-o", llvm_dialect], "S5-S6 (mlir-opt: standard dialects -> LLVM dialect)")
    _run([tool(MLIR_TRANSLATE), "--mlir-to-llvmir", llvm_dialect, "-o", ll_path],
         "S6 (mlir-translate: LLVM dialect -> LLVM IR)")
    _run([tool("clang"), ll_path, c_path, "-o", bin_path],
         "S7 (clang: LLVM IR + runtime -> native binary)")

    if not keep_intermediate:
        for path in (lnpl_path, mlir_path, llvm_dialect, ll_path, c_path):
            os.remove(path)
    return bin_path


def _run(argv, stage):
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BackendError("%s failed (exit %d)\n$ %s\n%s"
                           % (stage, proc.returncode, " ".join(argv),
                              (proc.stderr or proc.stdout).strip()))
    return proc.stdout


def _fields_path(bin_path):
    return bin_path + ".fields.json"


def run_binary(bin_path, skip=False, condition_fields=None):
    """Execute the native binary; returns (exit_code, stdout lines).

    Args:
        bin_path: path to the binary
        skip: skip flag for Presence `when` guards
        condition_fields: field_name -> value (RFC-0008 G8). Values are bound by
            name to the parameter order recorded at build time, so extra keys are
            ignored and missing condition fields default to 0. Callers therefore
            cannot shift a value into the wrong parameter by passing an unrelated
            field.
    """
    args = [bin_path, "1" if skip else "0"]
    values = condition_fields or {}
    for name in values:
        encode_condition_value(values[name])   # reject non-integers up front

    try:
        with open(_fields_path(bin_path), encoding="utf-8") as fh:
            order = json.load(fh)
    except OSError:
        raise BackendError(
            "missing %s — the binary's condition-field order is recorded at build "
            "time; rebuild with build() rather than invoking a stale binary"
            % os.path.basename(_fields_path(bin_path)))

    for name in order:
        args.append(str(encode_condition_value(values.get(name, 0))))

    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode, proc.stdout.splitlines()
