"""The golden scenario is machine-generated, not hand-maintained.

`examples/login.lir.json` must be exactly what the compiler emits from
`examples/login.lnpl`. This is what keeps the grammar, the IR, and the runtime
timeline from drifting apart as the RFCs change.

`examples/checkout.lir.json` is the second such pair (issue #35). Login is a
single-entity workflow, so it cannot exercise the case the issue reports: a
workflow that READS one entity and CREATES another. Checkout does, and it runs
green only under Wave 1's role-based seed rule — Product is read so it is
seeded, Order is only created so its table starts empty and `create order`
inserts instead of conflicting. `TestCheckoutExecution` asserts that *reason*,
not just the green, so a silent widening of the seed rule fails loudly here.

Both pairs run the same five assertions through `GoldenPairContract`. Neither
`.lir.json` is ever hand-edited: when one goes stale the fix is to regenerate it
with the command in the failure message.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from lnpl.interp import Interpreter, refinement_index, sample_payload
from lnpl.lower import lower
from lnpl.openapi import generate as generate_openapi
from lnpl.parser import parse
from lnpl.repo_policy import default_rows, row_key, seeded_entities
from lnpl.spec import extract
from tests.fixtures import (CHECKOUT_LIR, CHECKOUT_LNPL, SHORTEN_LIR,
                            SHORTEN_LNPL, SHORTEN_OPENAPI, SHORTEN_SPEC)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "examples", "login.lnpl")
GOLDEN_IR = os.path.join(REPO, "examples", "login.lir.json")
VALIDATOR = os.path.join(REPO, "scripts", "validate_ir.py")

PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
           "email": "user@example.com",
           "password": "s3cret-value",
           "createdAt": "2026-07-31T09:00:00Z"}

CHECKOUT_WORKFLOW = "wf.checkout"


def compile_module(path):
    """Compile a committed source exactly as `lnpl compile` does.

    The module name comes from the file name, which is what `cli._compile`
    does — deriving it here keeps the compiled document identical to the one
    the CLI writes into the golden.
    """
    with open(path, encoding="utf-8") as fh:
        return lower(parse(fh.read()),
                     os.path.splitext(os.path.basename(path))[0]).to_document()


def compile_golden():
    return compile_module(SRC)


def compile_checkout():
    return compile_module(CHECKOUT_LNPL)


def checkout_payload(document):
    """The default fixture the CLI runs with: every field of every entity."""
    return sample_payload([n for n in document["nodes"] if n["kind"] == "Entity"])


class GoldenPairContract:
    """The assertions every committed <source, IR> pair must satisfy.

    A plain mixin, not a `TestCase`: unittest collects only `TestCase`
    subclasses, so these run once per concrete pair below and never on their
    own. Each concrete class supplies the pair's paths and the two id facts that
    are genuinely per-module.
    """

    SRC = None
    GOLDEN_IR = None
    FIRST_NODE_ID = None
    LAST_NODE_IDS = None
    REGEN_CMD = None

    @classmethod
    def compile_source(cls):
        return compile_module(cls.SRC)

    def test_source_compiles_to_the_committed_ir(self):
        with open(self.GOLDEN_IR, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(self.compile_source(), committed,
                         "%s is stale — regenerate it with `%s`"
                         % (os.path.relpath(self.GOLDEN_IR, REPO), self.REGEN_CMD))

    def test_node_ids_and_order_are_stable(self):
        ids = [n["id"] for n in self.compile_source()["nodes"]]
        self.assertEqual(ids[0], self.FIRST_NODE_ID)
        self.assertEqual(ids[-len(self.LAST_NODE_IDS):], self.LAST_NODE_IDS)
        self.assertEqual(len(ids), len(set(ids)))       # ids are unique

    def test_committed_ir_passes_the_schema_validator(self):
        proc = subprocess.run([sys.executable, VALIDATOR, self.GOLDEN_IR],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_every_reference_resolves(self):
        doc = self.compile_source()
        ids = {n["id"] for n in doc["nodes"]}
        for node in doc["nodes"]:
            for key in ("children", "requires", "constraints"):
                for ref in node.get(key, []):
                    self.assertIn(ref, ids, "dangling %s in %s" % (key, node["id"]))
            for key in ("entity", "event"):
                if key in node:
                    self.assertIn(node[key], ids)
            if "source" in node:
                self.assertIn(node["source"]["ref"], ids)

    def test_each_node_has_at_most_one_owner(self):
        doc = self.compile_source()
        owners = {}
        for node in doc["nodes"]:
            for child in node.get("children", []):
                self.assertNotIn(child, owners,
                                 "%s is owned by both %s and %s"
                                 % (child, owners.get(child), node["id"]))
                owners[child] = node["id"]


class TestGoldenPair(GoldenPairContract, unittest.TestCase):
    SRC = SRC
    GOLDEN_IR = GOLDEN_IR
    FIRST_NODE_ID = "svc.login"
    LAST_NODE_IDS = ["cap.postgres", "cap.redis", "cap.jwt"]
    REGEN_CMD = "python3 -m lnpl compile examples/login.lnpl -o examples/login.lir.json"


class TestCheckoutGoldenPair(GoldenPairContract, unittest.TestCase):
    SRC = CHECKOUT_LNPL
    GOLDEN_IR = CHECKOUT_LIR
    FIRST_NODE_ID = "svc.checkout"
    LAST_NODE_IDS = ["cap.postgres", "cap.redis", "cap.jwt"]
    REGEN_CMD = ("python3 -m lnpl compile examples/checkout.lnpl "
                 "-o examples/checkout.lir.json")


class TestShortenGoldenPair(GoldenPairContract, unittest.TestCase):
    SRC = SHORTEN_LNPL
    GOLDEN_IR = SHORTEN_LIR
    # Refinement nodes lead the canonical order (`lower.lower` adds them before
    # the services), so unlike login and checkout this pair's first node is a
    # refinement rather than the service.
    FIRST_NODE_ID = "refine.click.count"
    LAST_NODE_IDS = ["cap.postgres", "cap.redis", "cap.jwt"]
    REGEN_CMD = ("python3 -m lnpl compile examples/shorten.lnpl "
                 "-o examples/shorten.lir.json")


class TestShortenGeneratedArtifacts(unittest.TestCase):
    """The `.spec.json` and `.openapi.json` halves of the quartet.

    `GoldenPairContract` pins only the IR. These two files are generated from
    the same source by `lnpl spec` / `lnpl openapi`, so an unchecked copy is a
    spec that can drift silently once the generator changes; the committed file
    is the must-pass input. Each comparison calls the generator exactly the way
    `cli.cmd_spec` / `cli.cmd_openapi` do, so it compares against the same call
    that produced the golden.
    """

    def _committed(self, path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_the_committed_spec_manifest_is_what_the_cli_emits(self):
        with open(SHORTEN_LNPL, encoding="utf-8") as fh:
            decls = parse(fh.read())
        self.assertEqual(extract(decls, "shorten"),
                         self._committed(SHORTEN_SPEC),
                         "examples/shorten.spec.json is stale — regenerate it "
                         "with `python3 -m lnpl spec examples/shorten.lnpl "
                         "-o examples/shorten.spec.json`")

    def test_the_committed_openapi_document_is_what_the_cli_emits(self):
        self.assertEqual(generate_openapi(compile_module(SHORTEN_LNPL)),
                         self._committed(SHORTEN_OPENAPI),
                         "examples/shorten.openapi.json is stale — regenerate "
                         "it with `python3 -m lnpl openapi "
                         "examples/shorten.lnpl -o examples/shorten.openapi.json`")

    def test_the_openapi_projection_carries_the_refinement_constraints(self):
        # The facets must survive into the API contract, not just the IR — that
        # projection is what makes `Slug`/`Url` visible to a client generator,
        # and it is the half of issue #31 a runtime test cannot observe.
        schemas = self._committed(SHORTEN_OPENAPI)["components"]["schemas"]
        self.assertEqual(schemas["Slug"],
                         {"type": "string", "pattern": "^[a-z0-9-]{1,64}$",
                          "maxLength": 64})
        self.assertEqual(schemas["Url"],
                         {"type": "string", "pattern": "^https?://[^\\s]+$",
                          "maxLength": 2048})
        self.assertEqual(schemas["ClickCount"],
                         {"type": "integer", "format": "int64", "minimum": 0})
        self.assertEqual(schemas["Link"]["properties"]["slug"],
                         {"$ref": "#/components/schemas/Slug"})
        self.assertEqual(schemas["Link"]["properties"]["target"],
                         {"$ref": "#/components/schemas/Url"})


class TestCheckoutShape(unittest.TestCase):
    """The structure the equivalence regression and mode B both quote."""

    def test_the_workflow_reads_product_and_creates_order(self):
        doc = compile_checkout()
        nodes = {n["id"]: n for n in doc["nodes"]}
        self.assertEqual(nodes["wf.checkout.step.2.repo"]["entity"], "entity.product")
        self.assertEqual(nodes["wf.checkout.step.2.repo"]["operation"], "read")
        self.assertEqual(nodes["wf.checkout.step.4.repo"]["entity"], "entity.order")
        self.assertEqual(nodes["wf.checkout.step.4.repo"]["operation"], "create")

    def test_the_guard_owns_only_the_create(self):
        # `when stock > 0` guards exactly one item, so nothing downstream of the
        # create can run when the guard is false.
        guard = {n["id"]: n for n in compile_checkout()["nodes"]}["wf.checkout.guard.1"]
        self.assertEqual(guard["mode"], "when")
        self.assertEqual(guard["condition"], "stock > 0")
        self.assertEqual(guard["children"], ["wf.checkout.step.4"])


class TestCheckoutExecution(unittest.TestCase):
    """Issue #35 completion criterion 1: read-then-create completes under the
    default seed — and completes *because of* the role-based rule, not by luck.
    """

    def test_the_default_seed_runs_read_then_create_to_completion(self):
        doc = compile_checkout()
        payload = checkout_payload(doc)
        interp = Interpreter(doc, repo_rows=default_rows(doc, CHECKOUT_WORKFLOW, payload))
        result = interp.run_workflow(CHECKOUT_WORKFLOW, payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["validate product", "find product",
                          "cache product", "create order"])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(interp.repo.calls,
                         [("entity.product", "read"), ("entity.order", "create")])

    def test_it_completes_because_only_the_entity_it_reads_is_seeded(self):
        # The reason, asserted. Seeding Order too would make `create order`
        # conflict on every run, which is the defect issue #35 reports; this
        # fails loudly if the seed rule ever widens back.
        doc = compile_checkout()
        payload = checkout_payload(doc)
        self.assertEqual(seeded_entities(doc, CHECKOUT_WORKFLOW), {"entity.product"})
        rows = default_rows(doc, CHECKOUT_WORKFLOW, payload)
        self.assertEqual(set(rows), {"entity.product"})
        self.assertEqual(list(rows["entity.product"]),
                         [row_key("entity.product", payload)])

    def test_stock_zero_skips_the_guarded_create(self):
        # Boundary of `when stock > 0`: 0 is the limit, and the Integer sample
        # 1 is one past it — the case above runs the true side.
        doc = compile_checkout()
        payload = dict(checkout_payload(doc))
        self.assertEqual(payload["stock"], 1, "the default payload must take the guard")
        payload["stock"] = 0
        interp = Interpreter(doc, repo_rows=default_rows(doc, CHECKOUT_WORKFLOW, payload))
        result = interp.run_workflow(CHECKOUT_WORKFLOW, payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["validate product", "find product", "cache product"])
        self.assertEqual(result["skipped"], ["wf.checkout.guard.1"])
        # the create never reached the repository
        self.assertEqual(interp.repo.calls, [("entity.product", "read")])

    def test_an_empty_repository_fails_the_read_after_retrying_it(self):
        # The error contract, not just "it failed": which step, which message,
        # and how many attempts the `retry 3` policy spent on it. The effects
        # map below is the mode A observation mode B has to reproduce — a read
        # is idempotent, so the retry emits one RepositoryCall span per attempt.
        doc = compile_checkout()
        payload = checkout_payload(doc)
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow(CHECKOUT_WORKFLOW, payload)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "find product")
        reasons = [e.get("reason") for e in interp.trace.logs
                   if e["message"] == "step failed"]
        self.assertEqual(reasons, ["repository read found no row for entity.product"])
        attempts = {s["step"]: s["attempts"] for s in result["steps"]}
        self.assertEqual(attempts, {"validate product": 1, "find product": 4})
        effects = {span.name: [child.kind for child in span.children]
                   for span in interp.trace.root.children}
        self.assertEqual(effects, {"validate product": ["Validation"],
                                   "find product": ["RepositoryCall"] * 4})
        self.assertEqual(interp.repo.calls, [("entity.product", "read")] * 4)


class TestCheckoutGoldenControls(unittest.TestCase):
    """A negative control per golden check, each mutating only what its own
    check owns — so a green run above states what it proved rather than only
    that it ran. This mirrors `scripts/validate_ir.py --self-test`, which pairs
    its one positive with three seeded faults.
    """

    def _tmpdir(self):
        # `.claude/tmp`, never /tmp: the repo writes temp dirs inside the
        # worktree, and the CLI already defaults its workdirs there.
        base = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(base, exist_ok=True)
        path = tempfile.mkdtemp(dir=base)
        self.addCleanup(shutil.rmtree, path, True)
        return path

    def _committed_ir(self):
        with open(CHECKOUT_LIR, encoding="utf-8") as fh:
            return json.load(fh)

    def test_a_drifted_golden_is_rejected_by_the_equality_check(self):
        # Control for test_source_compiles_to_the_committed_ir: rename one node
        # and the comparison must reject it. Without this, an equality between
        # two things that are equal by construction would look just as green.
        drifted = self._committed_ir()
        workflow = next(n for n in drifted["nodes"] if n["id"] == CHECKOUT_WORKFLOW)
        self.assertEqual(workflow["name"], "Checkout")
        workflow["name"] = "CheckoutDrifted"
        self.assertNotEqual(compile_checkout(), drifted)

    def test_an_ir_missing_a_required_field_is_rejected_by_the_validator(self):
        # Control for test_committed_ir_passes_the_schema_validator, dropping
        # the same required field the validator's own self-test drops.
        broken = self._committed_ir()
        workflow = next(n for n in broken["nodes"] if n["id"] == CHECKOUT_WORKFLOW)
        del workflow["name"]
        path = os.path.join(self._tmpdir(), "broken.lir.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(broken, fh)
        proc = subprocess.run([sys.executable, VALIDATOR, path],
                              capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0,
                            "the validator accepted a workflow with no name")
        report = proc.stdout + proc.stderr
        self.assertIn("INVALID", report)
        self.assertIn(CHECKOUT_WORKFLOW, report,
                      "the report must name the node it rejected")


SHORTEN_WORKFLOW = "wf.shorten"


class TestShortenRefinementIsLoadBearing(unittest.TestCase):
    """Issue #31 criterion 3: `Slug`/`Url`/`ClickCount` are not decoration.

    Naming a field `Slug` proves nothing on its own — what proves it is that a
    value the facet forbids is REJECTED. Every case below runs the same
    workflow with the same derived payload and changes exactly one field, so
    each verdict is attributable to that one field's facet. The reason string
    is asserted verbatim, not just the failure: a bare "it failed" passes when
    the wrong field fails for the wrong reason.

    `TestShortenTextDegradationControl` below is the other half — it shows the
    same payloads pass once the refinements are taken away.
    """

    def _doc(self):
        return compile_module(SHORTEN_LNPL)

    def _payload(self, doc, **overrides):
        """The CLI's own default fixture, with `overrides` applied.

        `sample_payload` derives each value from the field's type and verifies
        it against that type, so the unmodified payload is valid by
        construction — which is what makes a single override attributable.
        """
        payload = dict(sample_payload(
            [n for n in doc["nodes"] if n["kind"] == "Entity"],
            refinement_index(doc)))
        payload.update(overrides)
        return payload

    def _run(self, doc, payload):
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow(SHORTEN_WORKFLOW, payload)
        reasons = [e.get("reason") for e in interp.trace.logs
                   if e["message"] == "step failed"]
        return result, reasons

    def test_the_derived_payload_completes(self):
        doc = self._doc()
        payload = self._payload(doc)
        # Non-vacuity: the three refined fields must actually be in the payload,
        # otherwise every rejection case below would be testing an absent value.
        self.assertEqual(payload["slug"], "text")
        self.assertEqual(payload["target"], "https://example.com/a")
        self.assertEqual(payload["clicks"], 1)
        result, reasons = self._run(doc, payload)
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["failed_step"])
        self.assertEqual(reasons, [])
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["validate input", "authorize owner", "create link",
                          "cache link", "emit linkCreated", "return slug"])

    def test_a_target_that_is_not_a_url_is_rejected(self):
        doc = self._doc()
        result, reasons = self._run(doc, self._payload(doc, target="not-a-url"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "validate input")
        # The reason renders the pattern with `%r`, so the backslash arrives
        # doubled: four here is two in the message the caller reads.
        self.assertEqual(
            reasons,
            ["field 'target' does not match Url's pattern "
             "'^https?://[^\\\\s]+$'"])

    def test_a_slug_with_uppercase_is_rejected(self):
        doc = self._doc()
        result, reasons = self._run(doc, self._payload(doc, slug="Bad_Slug"))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "validate input")
        self.assertEqual(
            reasons,
            ["field 'slug' does not match Slug's pattern '^[a-z0-9-]{1,64}$'"])

    def test_a_negative_click_count_is_rejected(self):
        # The declared refinement, not a preset: this is the half of the
        # mechanism a module author writes by hand.
        doc = self._doc()
        result, reasons = self._run(doc, self._payload(doc, clicks=-1))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "validate input")
        self.assertEqual(reasons, ["field 'clicks' violates ClickCount's min 0"])

    def test_the_slug_length_limit_is_exact(self):
        # Boundary: `maxLength 64` accepts 64 and rejects 65 — off-by-one either
        # way would leave one of these two assertions red.
        doc = self._doc()
        at_limit, reasons = self._run(doc, self._payload(doc, slug="a" * 64))
        self.assertEqual(at_limit["status"], "completed")
        self.assertEqual(reasons, [])
        over, reasons = self._run(doc, self._payload(doc, slug="a" * 65))
        self.assertEqual(over["status"], "failed")
        self.assertEqual(over["failed_step"], "validate input")
        self.assertEqual(reasons,
                         ["field 'slug' is longer than Slug's maxLength 64 (65)"])

    def test_the_url_length_limit_is_exact(self):
        doc = self._doc()
        prefix = "https://e.co/"                       # 13 chars, matches Url
        at_limit, reasons = self._run(
            doc, self._payload(doc, target=prefix + "a" * (2048 - len(prefix))))
        self.assertEqual(at_limit["status"], "completed")
        self.assertEqual(reasons, [])
        over, reasons = self._run(
            doc, self._payload(doc, target=prefix + "a" * (2049 - len(prefix))))
        self.assertEqual(over["status"], "failed")
        self.assertEqual(over["failed_step"], "validate input")
        self.assertEqual(
            reasons, ["field 'target' is longer than Url's maxLength 2048 (2049)"])

    def test_a_missing_refined_field_is_rejected(self):
        # Boundary: the absent value. `validate input` requires every declared
        # field, so dropping one is refused before any facet is applied.
        doc = self._doc()
        payload = self._payload(doc)
        del payload["slug"]
        result, reasons = self._run(doc, payload)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "validate input")
        self.assertEqual(reasons, ["missing required field 'slug'"])


class TestShortenTextDegradationControl(unittest.TestCase):
    """The BEFORE picture, asserted — the negative control for the class above.

    Issue #31's symptom was that `slug`/`target` had to be declared `Text`,
    losing their meaning and their validation. This compiles that degraded twin
    from the committed source (only the two field type names replaced) and
    shows the SAME payload the refined module rejects is ACCEPTED there.

    Without this control the rejection tests could be green for some reason
    other than the facets — a required field, an unrelated guard, a typo in the
    workflow. It mutates only what it owns: the two type names.
    """

    def _degraded_source(self):
        with open(SHORTEN_LNPL, encoding="utf-8") as fh:
            source = fh.read()
        degraded = source
        for refined, base in (("\n        slug Slug\n", "\n        slug Text\n"),
                              ("\n        target Url\n", "\n        target Text\n")):
            self.assertIn(refined, degraded,
                          "this control is anchored on the exact field line %r; "
                          "examples/shorten.lnpl no longer declares it, so the "
                          "control would silently degrade to a no-op" % refined)
            degraded = degraded.replace(refined, base)
        return degraded

    def _degraded_doc(self):
        return lower(parse(self._degraded_source()), "shorten").to_document()

    def test_text_accepts_what_the_refinement_rejects(self):
        doc = self._degraded_doc()
        payload = dict(sample_payload(
            [n for n in doc["nodes"] if n["kind"] == "Entity"],
            refinement_index(doc)))
        payload["slug"] = "Bad_Slug"
        payload["target"] = "not-a-url"
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow(SHORTEN_WORKFLOW, payload)
        self.assertEqual(result["status"], "completed",
                         "under `Text` the bad payload must pass — that loss is "
                         "exactly what issue #31 reports")
        self.assertIsNone(result["failed_step"])

    def test_the_degradation_removes_the_two_presets_and_nothing_else(self):
        # The control must actually take the mechanism away, not merely rename
        # it: `refine.slug` and `refine.url` are emitted on use, so dropping the
        # uses drops the nodes. The declared `ClickCount` is untouched, which is
        # what keeps this a one-variable control.
        degraded = {n["id"] for n in self._degraded_doc()["nodes"]
                    if n["kind"] == "Refinement"}
        self.assertEqual(degraded, {"refine.click.count"})
        refined = {n["id"] for n in compile_module(SHORTEN_LNPL)["nodes"]
                   if n["kind"] == "Refinement"}
        self.assertEqual(refined,
                         {"refine.click.count", "refine.slug", "refine.url"})

    def test_the_degraded_fields_are_text_in_the_entity(self):
        entity = next(n for n in self._degraded_doc()["nodes"]
                      if n["id"] == "entity.link")
        types = {f["name"]: f["type"] for f in entity["fields"]}
        self.assertEqual(types["slug"], "Text")
        self.assertEqual(types["target"], "Text")
        # and the committed example is the opposite — the retired symptom
        committed = next(n for n in compile_module(SHORTEN_LNPL)["nodes"]
                         if n["id"] == "entity.link")
        committed_types = {f["name"]: f["type"] for f in committed["fields"]}
        self.assertEqual(committed_types["slug"], "Slug")
        self.assertEqual(committed_types["target"], "Url")
        self.assertNotIn("Text", committed_types.values())


class TestGoldenExecution(unittest.TestCase):
    def test_golden_runs_to_completion(self):
        doc = compile_golden()
        interp = Interpreter(doc, repo_rows={"entity.user": {row_key("entity.user", PAYLOAD): dict(PAYLOAD)}})
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["steps"]), 6)

    def test_timeline_matches_the_declared_six_steps(self):
        doc = compile_golden()
        interp = Interpreter(doc, repo_rows={"entity.user": {row_key("entity.user", PAYLOAD): dict(PAYLOAD)}})
        interp.run_workflow("wf.login", PAYLOAD)
        self.assertEqual([s.name for s in interp.trace.root.children],
                         ["validate input", "authenticate", "cache user",
                          "generate token", "audit login", "return token"])

    def test_golden_meets_its_own_response_slo(self):
        doc = compile_golden()
        interp = Interpreter(doc, repo_rows={"entity.user": {row_key("entity.user", PAYLOAD): dict(PAYLOAD)}})
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertTrue(result["slo_met"], "golden run exceeded response < 50ms")

    def test_empty_repository_exercises_retry_then_fails(self):
        doc = compile_golden()
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "authenticate")


if __name__ == "__main__":
    unittest.main()
