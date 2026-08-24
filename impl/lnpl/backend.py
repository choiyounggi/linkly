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

from lnpl.condition import (And, Arith, Comparison, ConditionError, Lit,
                            Presence, Ref, encode_instant, guard_condition_text,
                            is_instant_text, looks_like_instant, parse_condition,
                            references, value_to_string)
from lnpl.interp import (RunError, refinement_index, sample_payload,
                         validate_effect)
# The seed/key policy both modes read (issue #35). Imported, never restated: a
# second copy of the seeding rule is the defect Wave 1 removed when three seeding
# sites became one. `repo_policy` imports nothing from `interp`/`backend`/`cli`,
# so this is cycle-safe.
from lnpl.repo_policy import seeded_entities
from lnpl import resources

MLIR_OPT = "mlir-opt"
MLIR_TRANSLATE = "mlir-translate"
BREW_LLVM_BIN = "/opt/homebrew/opt/llvm/bin"

# This file is <repo>/impl/lnpl/backend.py, so three dirnames reach the repo.
# Kept for the tmp-staging path below (verify_lnpl_module), which is always a
# repo-local directory — never shipped as wheel data.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
# The dialect definition is located via resources.data_path() rather than
# REPO_ROOT directly, so a `pip install`-ed wheel (no repo checkout) resolves
# it from the bundled assets instead — see resources.py. Resolution failure is
# swallowed here (None) rather than raised at import time, so the module still
# imports cleanly; pinned_llvm_version() and verify_lnpl_module() below turn a
# None/missing path into a BackendError with the same recovery hint, instead of
# a raw crash on import or an opaque mlir-opt error at call time.
try:
    LNPL_IRDL_PATH = resources.data_path("mlir/lnpl.irdl.mlir")
except resources.DataNotFoundError:
    LNPL_IRDL_PATH = None
# RFC-0004 OQ①: the one committed, machine-read declaration of the pinned
# LLVM/MLIR version. Resolved the same way as LNPL_IRDL_PATH.
try:
    LLVM_PIN_PATH = resources.data_path("mlir/llvm.pin")
except resources.DataNotFoundError:
    LLVM_PIN_PATH = None


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
    if LLVM_PIN_PATH is None or not os.path.isfile(LLVM_PIN_PATH):
        raise BackendError(resources.recovery_hint("mlir/llvm.pin"))
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
        # Preflight: fail with the recovery hint before mlir-opt's own (far
        # less actionable) "file not found" error.
        if LNPL_IRDL_PATH is None or not os.path.isfile(LNPL_IRDL_PATH):
            raise BackendError(resources.recovery_hint("mlir/lnpl.irdl.mlir"))
        return _run([tool(MLIR_OPT), "--irdl-file", LNPL_IRDL_PATH,
                     "--mlir-print-debuginfo", target], stage)
    finally:
        if staged is not None:
            os.remove(staged)


def _field_ident(name):
    """The emitted identifier for a condition field's logical name (RFC-0012).

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


def _parsed(cond_str):
    """The parsed condition, or None when it is absent or malformed.

    `_extract_condition_field` used to live here and returned a `(field, op,
    value)` tuple, which RFC-0015 made unrepresentable: a comparison now has a
    Value on both sides and a condition can carry several of them. Keeping the
    tuple would have let this file read the left operand and silently ignore the
    right one, so it is gone rather than widened.
    """
    if not cond_str:
        return None
    try:
        return parse_condition(cond_str)
    except Exception:
        return None


def _comparisons(cond):
    """The Comparison terms of a parsed condition, in source order."""
    if isinstance(cond, Comparison):
        return (cond,)
    if isinstance(cond, And):
        return cond.terms
    return ()


# arith.cmpi predicates for the six comparators, and for their negations. `until c`
# repeats *while c is false*, so each unrolled round is guarded by the negation.
_CMP_PRED = {'<': 'slt', '<=': 'sle', '>': 'sgt', '>=': 'sge',
             '==': 'eq', '!=': 'ne'}
_NEGATED_CMP = {"<": "sge", "<=": "sgt", ">": "sle", ">=": "slt",
                "==": "ne", "!=": "eq"}


def _literals(cond):
    """Every integer literal a parsed condition holds, at any operand position.

    RFC-0028 §Reference-level Specification/6: a `/` also needs `%c0_i64` (the
    zero check) and `%c1_i64` (the safe substitute divisor) declared, even
    when neither appears as a literal in the source text — `product.stock /
    input.divisor` has no literal at all.
    """
    out = set()

    def walk(value):
        if isinstance(value, Lit):
            out.add(value.value)
        elif isinstance(value, Arith):
            if value.op == "/":
                out.add(0)
                out.add(1)
            walk(value.left)
            walk(value.right)

    for term in _comparisons(cond):
        walk(term.left)
        walk(term.right)
    return out


_ARITH_MLIR_OP = {"+": "arith.addi", "-": "arith.subi", "*": "arith.muli"}


def _emit_division(left, right, idx, slot, lines):
    """`left / right` (RFC-0028 §Reference-level Specification/6).

    `arith.divsi` is undefined for a 0 divisor, so the divisor is swapped for
    1 whenever it is 0 before dividing — a safe, arbitrary substitute. Mode B
    is not required to AGREE with mode A's `RunError` here (RFC-0015 §5:
    "값 차원은 모드 A가 단독으로 단언한다"); it is only required not to hit
    undefined behaviour. `%c0_i64`/`%c1_i64` are declared by `_literals`
    whenever a condition holds a `/`.
    """
    is_zero = "%%z%s_%s" % (idx, slot)
    lines.append("    %s = arith.cmpi eq, %s, %%c0_i64 : i64" % (is_zero, right))
    safe_right = "%%sr%s_%s" % (idx, slot)
    lines.append("    %s = arith.select %s, %%c1_i64, %s : i64"
                 % (safe_right, is_zero, right))
    name = "%%v%s_%s" % (idx, slot)
    lines.append("    %s = arith.divsi %s, %s : i64" % (name, left, safe_right))
    return name


def _emit_operand(value, idx, slot, lines):
    """One `Value` -> the SSA name holding it, appending any arithmetic first.

    A `Ref` is already a parameter (`condition_field_names` put it in the
    signature) and a `Lit` is already a declared constant, so only `Arith` adds
    an operation — which is the whole of RFC-0015's (`+`/`-`) and RFC-0028's
    (`*`/`/`) arithmetic in mode B.
    """
    if isinstance(value, Ref):
        return "%%%s" % _field_ident(value.name)
    if isinstance(value, Lit):
        return "%%c%d_i64" % value.value
    if isinstance(value, Arith):
        left = _emit_operand(value.left, idx, slot + "l", lines)
        right = _emit_operand(value.right, idx, slot + "r", lines)
        if value.op == "/":
            return _emit_division(left, right, idx, slot, lines)
        op = _ARITH_MLIR_OP[value.op]
        name = "%%v%s_%s" % (idx, slot)
        lines.append("    %s = %s %s, %s : i64" % (name, op, left, right))
        return name
    raise BackendError("cannot emit value %r" % (value,))


def _emit_condition(cond, idx, lines, negate):
    """A parsed condition -> the SSA name of its i1 result, or None.

    None means "this condition has no compiled evaluator" — a Presence, or text
    the parser refused — and the caller falls back to the run-level skip flag,
    exactly as it did before RFC-0015.

    `negate` is for `until`, which repeats *while* its condition is false. A
    single comparison negates by flipping its predicate; a conjunction negates
    by xor with true, because De Morgan expanded by hand in an emitter is a
    second place for the loop's meaning to be wrong.
    """
    terms = _comparisons(cond)
    if not terms:
        return None

    single = len(terms) == 1
    names = []
    for n, term in enumerate(terms):
        left = _emit_operand(term.left, idx, "%dl" % n, lines)
        right = _emit_operand(term.right, idx, "%dr" % n, lines)
        pred = (_NEGATED_CMP if (negate and single) else _CMP_PRED)[term.op]
        # A one-term condition keeps the SSA names it had before RFC-0015
        # (`%cond<idx>` / `%ucond<idx>`). The frozen golden modules in
        # `impl/tests/golden/` are compared as text, so a rename would move
        # bytes for programs whose meaning did not change.
        if single:
            name = "%%ucond%s" % idx if negate else "%%cond%s" % idx
        else:
            name = "%%cond%s_%d" % (idx, n)
        lines.append("    %s = arith.cmpi %s, %s, %s : i64"
                     % (name, pred, left, right))
        names.append(name)

    folded = names[0]
    for n, name in enumerate(names[1:], start=1):
        nxt = "%%and%s_%d" % (idx, n)
        lines.append("    %s = arith.andi %s, %s : i1" % (nxt, folded, name))
        folded = nxt

    if negate and not single:
        nxt = "%%ucond%s" % idx
        lines.append("    %s = arith.xori %s, %%true_i1 : i1" % (nxt, folded))
        folded = nxt
    return folded


def _emit_alt_condition(cond_texts, idx, lines):
    """RFC-0028 §Reference-level Specification/6: OR-fold the primary
    condition and its `or` alternatives, `when`-only (never negated — an
    alt-guard cannot be an `until`, RFC-0028 §Reference-level
    Specification/1).

    Reuses `_emit_condition` per text with a composite `<idx>_<n>` SSA
    namespace, so the single-condition path it also serves stays completely
    untouched (`idx` there is the bare int, unchanged bytes for every
    existing golden fixture).

    Returns `None` — falling back to the run-level skip flag, exactly the
    single-condition contract — if ANY term has no compiled evaluator
    (Presence). Computing only the compilable side would silently
    under-evaluate the OR, contradicting the "every alternative is
    evaluated" rule mode A follows (§Reference-level Specification/4).
    """
    names = []
    for n, text in enumerate(cond_texts):
        emitted = _emit_condition(_parsed(text), "%s_%d" % (idx, n), lines,
                                  negate=False)
        if emitted is None:
            return None
        names.append(emitted)

    folded = names[0]
    for n, name in enumerate(names[1:], start=1):
        nxt = "%%or%s_%d" % (idx, n)
        lines.append("    %s = arith.ori %s, %s : i1" % (nxt, folded, name))
        folded = nxt
    return folded


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
                # RFC-0008 G9: when becomes arith.cmpi + scf.if. RFC-0028: the
                # third element is `alternatives` (`()` for a plain guard —
                # every existing 2-element unpacking site was updated to
                # match, not left to default one in silently).
                inner = []
                _steps_in_order(nodes, node.get("children", []), inner)
                for step, _cond in inner:
                    out.append((step, ("when", node.get("condition"),
                               tuple(node.get("alternatives") or ()))))
            elif node["mode"] == "until":
                # RFC-0008 G10: until unrolls to round_cap (16) iterations.
                # Condition evaluation deferred; unrolling ensures Mode A ≈ Mode B.
                inner = []
                _steps_in_order(nodes, node.get("children", []), inner)
                for _ in range(_UNTIL_ROUND_CAP):
                    for step, _cond in inner:
                        out.append((step, ("until", node.get("condition"), ())))
            else:
                raise BackendError("unknown guard mode %r" % node["mode"])
        else:
            raise BackendError("workflow body cannot contain %s" % kind)
    return out


def _workflow_steps(document, workflow_id):
    nodes = {n["id"]: n for n in document["nodes"]}
    wf = nodes.get(workflow_id)
    if wf is None or wf["kind"] != "Workflow":
        raise BackendError("no such workflow: %r" % workflow_id)
    return nodes, _steps_in_order(nodes, wf.get("children", []), [])


def validation_effect_steps(document, workflow_id):
    """Names of the workflow's steps that carry a `Validation` effect, in order.

    Issue #55 (r1 N-3): mode B specialises at build time, so a `Validation`
    outcome is decided from `_lnpl_ops`'s `payload` — and `cli.cmd_build` passes
    none, which means the derived sample payload, valid by construction. No
    `--field` value can make a refinement fail there, because `--field` feeds
    comparison guards only. This is the list `cmd_build` names when it says so.

    Reads the step order through `_workflow_steps`, the same walk `_lnpl_ops`
    uses, rather than re-deriving it: a second walk could name a step the built
    module does not have. A step whose name repeats (an unrolled `repeat`/`until`
    body) is named once — the diagnostic is about steps, not occurrences.

    Raises `BackendError` for an unknown workflow, via `_workflow_steps`. An
    empty list would read as "nothing to declare" and silence the diagnostic for
    a typo'd `--workflow`.
    """
    nodes, steps = _workflow_steps(document, workflow_id)
    names = []
    for step, _cond in steps:
        if step["name"] in names:
            continue
        if any(nodes[child]["kind"] == "Validation"
               for child in step.get("children", [])):
            names.append(step["name"])
    return names


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
        if cond and isinstance(cond, tuple) and len(cond) == 3:
            _mode, cond_str, alternatives = cond
            # RFC-0028: the union of the condition and every alternative's
            # references — an alt-guard fixes ALL of them as i64 parameters,
            # not only the ones the primary condition happens to read.
            for text in (cond_str,) + tuple(alternatives):
                parsed = _parsed(text)
                if parsed is not None:
                    # RFC-0015: EVERY reference, not the left operand of the
                    # first term. `product.stock >= input.quantity` needs
                    # both sides as parameters, or the compiled guard
                    # compares against a register nobody wrote.
                    fields.update(references(parsed))
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
    if isinstance(value, str) and (is_instant_text(value)
                                   or looks_like_instant(value)):
        # RFC-0016: a DateTime rides the existing i64 parameter channel as UTC
        # epoch-milliseconds. `encode_instant` is the same function mode A calls
        # from `interp.eval_value`, so a value cannot mean two instants.
        try:
            return encode_instant(value, "condition field")
        except ConditionError as e:
            raise BackendError(str(e))
    raise BackendError(
        "condition field value must be an integer or a zoned date-time, got "
        "%r (%s)" % (value, type(value).__name__))


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
# RFC-0025 §10: a backend-local set, NOT `repo_policy.READ_OPS` (`read`+
# `query`) — mode B's fail_at prediction below only ever needs to treat
# `read` as able to fail-on-not-found; `query` (`list`) never fails that way
# (RFC-0025 §5, an empty RowSet is a normal result). A tuple, not a bare `==`
# comparison, so the deliberate-mismatch tests keep the seam they already
# patch (`backend.READ_OPS = ()`) to prove `differential.verify` catches mode
# B losing track of how a read fails.
READ_OPS = ("read",)

_STEP_COST_MS = 5        # interp `Clock.step_cost_ms`, advanced once per step
_READ_MISS_COST_MS = 1   # interp `_run_effect` advances 1ms before raising
# interp `MAX_STEP_ATTEMPTS` — the bound that does not read the declared budget
# (RFC-0003 §Policy Enforcement, as updated by RFC-0013). Mirrored here for the
# same reason as the constants above: mode B must not import mode A. Omitting it
# would make the two modes disagree on any `retry >= 100`, which is a divergence
# `lnpl diff` reports and RFC-0004 §실행 모드와 semantic equivalence forbids.
_MAX_STEP_ATTEMPTS = 100

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
    """`3s` -> 3000. Mirrors interp `_duration_ms`, raising a BackendError instead.

    Both read the one unit table in `lexer`, so a unit the language accepts is a
    unit both modes accept (RFC-0016).
    """
    from lnpl.lexer import duration_ms_or_none
    try:
        value = duration_ms_or_none(str(text))
    except OverflowError as e:
        raise BackendError(str(e))
    if value is None:
        raise BackendError("not a duration: %r" % text)
    return value


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
        # Checked before the declared budget, mirroring `_retryable`'s order.
        if attempts >= _MAX_STEP_ATTEMPTS:
            return attempts
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
                # RFC-0028 §Reference-level Specification/6. `None` (omitted
                # by `_mlir_attr_dict`'s `is not None` filter) for every
                # guard this RFC does not touch — `_mlir_attr` already
                # renders a list/tuple, so no new serialisation is needed.
                ("lnpl.guard_alternatives", node.get("alternatives") or None),
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


def _validation_fails(nodes, effect, payload, refinements):
    """Whether mode A's validate step would reject `payload` (issue #48).

    The judgement is interp's own `validate_effect` — one validator, both
    modes — so this derivation cannot drift from what the interpreter enforces.
    """
    try:
        validate_effect(nodes, effect, payload, refinements)
    except RunError:
        return True
    return False


def _lnpl_ops(document, workflow_id, seeded=None, payload=None):
    """S4: the `lnpl` op stream, plus the module-level attributes.

    `seeded` is the run's seed condition — the set of entity ids that start with a
    row. `None` means the default role-based policy
    (`repo_policy.seeded_entities`); `frozenset()` is the `--no-row` case. It is
    the ONE input mode B derives its repository outcome from, and mode A is given
    the same condition materialised as rows, so neither mode reads the other's
    answer (the arrangement `_derive_skip_from_payload` uses for the skip flag).

    `payload` is the run's input values — the second input the derivation reads,
    for `Validation` effects only (issue #48): a refinement facet's truth is a
    payload fact, and mode B specialises at compile time, so the validation
    outcome is decided here exactly as the repository outcome is decided from
    the seed. `None` means the same derived sample mode A's default run uses
    (`cli.cmd_run` / `cmd_diff`), which is valid by construction — so a caller
    that supplies no payload derives no failure.

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
        guard_alternatives = ()
        if cond and isinstance(cond, tuple) and len(cond) == 3:
            guard_mode, guard_condition, guard_alternatives = cond

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
            # RFC-0028 §Reference-level Specification/6. `()` for every guard
            # this RFC does not touch (`until`, or a plain `when`).
            "guard_alternatives": guard_alternatives,
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
    refinements = refinement_index(document)
    if payload is None:
        payload = sample_payload([n for n in document.get("nodes", [])
                                  if n["kind"] == "Entity"], refinements)
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
                # RFC-0025 §5/§6.1: `READ_OPS` here is `("read",)` (module-
                # local, above) — narrowed from `repo_policy.READ_OPS`
                # (read+query). `query` (`list`) never fails on finding
                # nothing, it binds an empty RowSet (interp
                # `FakeRepository`/driver `query` returns `[]`, never raises).
                # Predicting failure here for an unseeded `query`-only entity
                # would have mode B diverge from mode A on every `list` of a
                # genuinely empty store — exactly the 0-row case RFC-0025 §5
                # makes routine, not exceptional.
                if node["entity"] not in seeded_now and node["entity"] not in created:
                    fail_at = index
            elif kind == "RepositoryCall" and operation == "create":
                if node["entity"] in seeded_now or node["entity"] in created:
                    fail_at = index
                else:
                    created.add(node["entity"])
            elif kind == "Validation" and _validation_fails(nodes, node,
                                                            payload,
                                                            refinements):
                fail_at = index
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


def step_plan(document, workflow_id, seeded=None, payload=None):
    """The ordered step plan mode B compiled — `observe_mode_b`'s skip input.

    A guard that does not hold produces no output at all in mode B: `scf.if`
    simply does not call `lnpl_step`, and the binary's stdout has no line for it.
    So a skip is observable only as an ABSENCE, and an absence is meaningless
    without the list it is absent from. That list is this.

    It comes from `_lnpl_ops` — the same derivation `emit_lnpl_mlir` and
    `_render_std` consume — rather than from a second walk of the document, so
    the plan cannot describe a workflow other than the one that was built. That
    is also why nothing here touches the emitted MLIR: the observation is
    reconstructed from what the binary printed, not from a new branch compiled
    into it, which keeps `impl/tests/golden/*.std.mlir` byte-identical (issue #44).

    `seeded` and `payload` are the run's specialisation inputs; see `_lnpl_ops`.
    """
    _module_attrs, ops = _lnpl_ops(document, workflow_id, seeded, payload)
    return ops


def ran_step_indices(lines):
    """The plan indices the binary printed, from its stdout `lines`.

    The index, not the name, is what identifies WHICH planned op ran: a workflow
    may declare the same step twice (`load user` inside a guard and again outside
    it), and matching on the name would let a step that ran mask an identically
    named one that was skipped.

    Kept as strings, because the only thing they are compared against is
    `str(entry["index"])` in `restore_skips`.
    """
    indices = set()
    for line in lines:
        parts = line.split(" ", 2)
        if parts[0] == "step" and len(parts) == 3:
            indices.add(parts[1])
    return indices


def restore_skips(document, workflow_id, ran_indices, seeded=None, payload=None):
    """The skip records mode B can observe, restored from the compiled plan.

    RFC-0014 §2.6: a guard mode B did not take prints nothing at all — `scf.if`
    simply does not call `lnpl_step` — so the skip is observable only as an
    ABSENCE from the plan the module was built from. Reading it back this way
    rather than emitting a marker op is what keeps the compiled module
    byte-identical, which `impl/tests/golden/*.std.mlir` requires (those fixtures
    are pre-change snapshots and are never regenerated).

    Returns one record per skipped STEP, carrying exactly the four fields both
    modes can observe — `{mode, condition, step, rounds}`. The grain and the
    field set are the contract: `differential._normalise_skips` projects mode A's
    per-guard records onto the same shape, and an IR node id has no counterpart
    here at all (RFC-0014 §2.4).

    `ran_indices` is what the binary printed (`ran_step_indices`). `seeded` and
    `payload` MUST be the same values the module was built with, or the plan
    describes a different specialisation than the one that ran; see `_lnpl_ops`.

    Callers: `differential.observe_mode_b` (the comparison) and `cli.cmd_build`
    (the operator-facing surface, issue #55). One derivation, two readers — a
    second copy of this reading could disagree with the first about what mode B
    observed.
    """
    skips = []
    for entry in step_plan(document, workflow_id, seeded=seeded, payload=payload):
        if entry["guard_mode"] is None or str(entry["index"]) in ran_indices:
            continue
        if entry["guard_mode"] == "until" and (entry["unroll_round"] or 1) != 1:
            # `until` is unrolled to the round cap, and nothing in the IR mutates
            # a condition field mid-run, so the loop runs either zero rounds or
            # all of them. Round 1's absence already says "zero rounds"; counting
            # rounds 2..N again would report one skip per unrolled round against
            # mode A's single record.
            continue
        skips.append({"mode": entry["guard_mode"],
                      # RFC-0028 §Reference-level Specification/5: the same
                      # SSOT join `interp._skip_record` uses, so an alt-guard's
                      # combined text cannot drift between the two modes.
                      "condition": guard_condition_text(
                          entry["guard_condition"], entry["guard_alternatives"]),
                      "step": entry["name"],
                      "rounds": 0 if entry["guard_mode"] == "until" else None})
    return skips


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


def emit_lnpl_mlir(document, workflow_id, seeded=None, payload=None):
    """S4: Semantic IR -> `lnpl` dialect MLIR.

    `seeded` is the run's seed condition and `payload` the run's input values
    (validation derivation, issue #48); see `_lnpl_ops`.

    Every op carries the originating node id on both paths RFC-0004 requires: the
    discardable attribute `lnpl.node_id` that passes read, and a `loc(...)` that
    diagnostics and debug info follow. The dialect's verifier enforces the
    attribute's presence and type (see `mlir/lnpl.irdl.mlir`); `build()` runs that
    verifier over the emitted module, so a module that loses a node id fails the
    compile rather than producing a binary that cannot be traced back.
    """
    module_attrs, ops = _lnpl_ops(document, workflow_id, seeded, payload)

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
                ("lnpl.guard_alternatives", list(op["guard_alternatives"]) or None),
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

    # Declare i64 constants for condition comparisons. RFC-0015 put literals on
    # either side of a comparator and inside arithmetic, so the sweep is over
    # every `Lit` the condition holds rather than over one right-hand value.
    # RFC-0028: every alternative is swept too, not only the primary.
    cond_i64_values = set()
    for entry in ops:
        for text in (entry["guard_condition"],) + tuple(entry["guard_alternatives"]):
            parsed = _parsed(text)
            if parsed is not None:
                cond_i64_values.update(_literals(parsed))

    # Declare all i64 constants upfront
    for value in sorted(cond_i64_values):
        lines.append(f"    %c{value}_i64 = arith.constant {value} : i64")
    if any(_parsed(e["guard_condition"]) is not None
           and isinstance(_parsed(e["guard_condition"]), And)
           and e["guard_mode"] == "until" for e in ops):
        # `until (A and B)` negates the whole conjunction, and De Morgan is not
        # something to expand by hand in an emitter — xor with true does it.
        lines.append("    %true_i1 = arith.constant true")

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
            guard_alts = entry["guard_alternatives"]
            if guard_alts:
                # RFC-0028 §Reference-level Specification/6: OR-fold, a
                # brand-new code path — the `else` below is untouched, so
                # every existing golden fixture (no alternatives) still runs
                # through the exact `_emit_condition` call it always has.
                emitted = _emit_alt_condition((guard_str,) + tuple(guard_alts),
                                              idx, lines)
            else:
                parsed = _parsed(guard_str)
                emitted = _emit_condition(parsed, idx, lines, negate=False)

            if emitted is not None:
                lines.append(f"    scf.if {emitted} {{")
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
            parsed = _parsed(guard_str)
            emitted = _emit_condition(parsed, idx, lines, negate=True)

            if emitted is not None:
                lines.append("    scf.if %s {" % emitted)
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


def emit_mlir(document, workflow_id, seeded=None, payload=None):
    """Semantic IR -> standard-dialect MLIR, by way of the `lnpl` dialect (S4-S5).

    `seeded` is the run's seed condition and `payload` the run's input values
    (validation derivation, issue #48); see `_lnpl_ops`.

    The op stream this renders is the one `emit_lnpl_mlir` serialises, so the
    standard-dialect module and the `lnpl` module cannot describe different
    workflows. The signature and the output are unchanged from before the dialect
    existed; `impl/tests/golden/` holds the pre-change bytes that prove it.
    """
    return _render_std(*_lnpl_ops(document, workflow_id, seeded, payload))


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


def build(document, workflow_id, workdir, keep_intermediate=True, seeded=None,
          payload=None):
    """Run S4-S7. Returns the path to the native binary.

    `seeded` is the run's seed condition (see `_lnpl_ops`): it specialises the
    module, exactly as the cache-TTL budget does. A runtime flag was the
    alternative, and it is the wrong one — deciding the repository outcome at run
    time means the generated module branches on repository state, which is a
    store inside the native runtime. Mode B is rebuilt per `observe_mode_b` call
    anyway, so specialising costs nothing. `payload` specialises the validation
    outcome the same way (issue #48; see `_lnpl_ops`).

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
    lnpl_text = emit_lnpl_mlir(document, workflow_id, seeded, payload)
    with open(lnpl_path, "w", encoding="utf-8") as fh:
        fh.write(lnpl_text)
    verify_lnpl_module(lnpl_text, path=lnpl_path)

    with open(mlir_path, "w", encoding="utf-8") as fh:
        fh.write(emit_mlir(document, workflow_id, seeded, payload))
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
