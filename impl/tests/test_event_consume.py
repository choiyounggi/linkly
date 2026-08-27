"""`consume by <Workflow>` — the subscription half of event consumption
(issue #118, D1-D3).

`event <E> subscribe` (issue #103) opts an event into an SSE stream for HTTP
clients; it does not run anything. `event <E> consume by <Workflow>` is the
other, previously-missing half: on arrival, run `<Workflow>`. The two are
independent opt-ins on the same declaration — neither excludes the other, and
neither excludes an `on <Entity> ...`/`on schedule ...` publish source.

D1 — grammar: exactly `consume by <Workflow>` (three tokens), at most once
per event; an undeclared target is a compile error naming the candidates
(the same convention `emit`'s undeclared-event check already uses, issue #45).

D2 — IR: `Event.consume` is a `nodeId` (the target workflow's id), present
only when declared — `schemas/lir.schema.json` and `scripts/validate_ir.py`
cover the wire shape; this file covers the lowering that produces it.

D3 — cycle detection: event -> its consuming workflow -> that workflow's own
`emit`/`publish` -> ... -> the same event again is a *warning*
(`event-consume-cycle`), never a `LowerError` — a guard inside the consuming
workflow may keep the cycle from ever actually firing at run time, so the
program is not necessarily wrong.
"""
import unittest

from lnpl.diagnostics import CODES, Diagnostics, SEVERITY_OF
from lnpl.lower import LowerError, _check_event_consume_cycles, lower
from lnpl.parser import parse

GOLDEN = """
capability postgres
entity User
    field
        id UUID
        email Email
service LoginService
    policy
        retry 3
workflow Login
    validate input
    authenticate
    cache user
"""


def ir(source, name="t"):
    return lower(parse(source), name).to_document()


def by_id(doc):
    return {n["id"]: n for n in doc["nodes"]}


def diagnose(source, code, name="t"):
    module = lower(parse(source), name)
    return list(module.diagnostics.by_code(code))


class TestConsumeByGrammarAndLowering(unittest.TestCase):
    """D1 — parsing and the compile-time existence check."""

    def test_consume_by_a_declared_workflow_lowers_to_the_workflow_id(self):
        src = GOLDEN + "event OrderPlaced on User create\n    consume by Login\n"
        node = by_id(ir(src))["event.order.placed"]
        self.assertEqual(node["consume"], "wf.login")

    def test_consume_by_an_undeclared_workflow_is_rejected_with_candidates(self):
        src = GOLDEN + "event OrderPlaced on User create\n    consume by Ghost\n"
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        msg = str(ctx.exception)
        self.assertIn("Ghost", msg)
        self.assertIn("not a declared workflow", msg)
        self.assertIn("wf.login", msg)          # the one candidate available

    def test_consume_by_twice_is_rejected(self):
        src = (GOLDEN + "event OrderPlaced on User create\n"
                        "    consume by Login\n    consume by Login\n")
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        self.assertIn("declares `consume by` twice", str(ctx.exception))

    def test_malformed_consume_line_is_rejected(self):
        src = GOLDEN + "event OrderPlaced on User create\n    consume Login\n"
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        msg = str(ctx.exception)
        self.assertIn("consume by <Workflow>", msg)
        self.assertIn("subscribe", msg)   # stray-line message still names both

    def test_consume_by_coexists_with_subscribe_and_an_on_source(self):
        """Neither `subscribe` (SSE) nor the publish source excludes `consume
        by` (issue #118, D1: "subscribe/on과 배타적이지 않음")."""
        src = (GOLDEN + "event OrderPlaced on User create\n"
                        "    subscribe\n    consume by Login\n")
        node = by_id(ir(src))["event.order.placed"]
        self.assertTrue(node["subscribe"])
        self.assertEqual(node["consume"], "wf.login")
        self.assertEqual(node["source"], {"ref": "entity.user", "on": "create"})

    def test_boundary_no_consume_clause_omits_the_field_entirely(self):
        src = GOLDEN + "event OrderPlaced on User create\n"
        node = by_id(ir(src))["event.order.placed"]
        self.assertNotIn("consume", node)

    def test_a_module_with_no_workflows_still_says_none_declared(self):
        src = "entity User\n    field\n        id UUID\n" \
              "event OrderPlaced on User create\n    consume by Ghost\n"
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        self.assertIn("none declared", str(ctx.exception))


class TestConsumeCycleIsRegisteredAndGraded(unittest.TestCase):
    def test_code_is_registered(self):
        self.assertIn("event-consume-cycle", CODES)

    def test_severity_is_warning_not_an_error(self):
        # RFC-0021's question: editing the program (dropping `consume by` or
        # the `emit`) removes it -> warning, same test as `unknown-verb`. It
        # is not a LowerError because a guard may keep the loop from firing.
        self.assertEqual(SEVERITY_OF["event-consume-cycle"], "warning")


class TestConsumeCycleDetection(unittest.TestCase):
    """D3 — event -> consume workflow -> that workflow's own emit -> ... """

    def test_direct_self_cycle_fires_a_warning(self):
        # OrderPlaced is consumed by Login, and Login itself emits OrderPlaced
        # back — a runtime dispatch of OrderPlaced would re-run Login forever.
        src = (GOLDEN.replace(
                    "workflow Login\n",
                    "event OrderPlaced on User create\n"
                    "    consume by Login\nworkflow Login\n")
                .replace("    cache user\n", "    cache user\n    emit orderPlaced\n"))
        found = diagnose(src, "event-consume-cycle")
        self.assertEqual(len(found), 1, [d.subject for d in found])
        self.assertIn("event.order.placed", found[0].message)
        self.assertIn("wf.login", found[0].message)

    def test_boundary_consume_without_a_matching_emit_is_not_a_cycle(self):
        src = GOLDEN + "event OrderPlaced on User create\n    consume by Login\n"
        self.assertEqual(diagnose(src, "event-consume-cycle"), [])

    def test_boundary_emit_without_consume_is_not_a_cycle(self):
        src = (GOLDEN.replace(
                    "workflow Login\n",
                    "event OrderPlaced on User create\nworkflow Login\n")
                .replace("    cache user\n", "    cache user\n    emit orderPlaced\n"))
        self.assertEqual(diagnose(src, "event-consume-cycle"), [])

    def test_two_hop_cycle_across_two_workflows_fires_once(self):
        # A consumes E1, A's workflow emits E2; E2 is consumed by B, whose
        # workflow emits E1 back — the cycle spans two events/two workflows.
        src = """
capability postgres
entity User
    field
        id UUID
event First on User create
    consume by A
event Second on User create
    consume by B
service S
workflow A
    validate input
    emit second
workflow B
    validate input
    emit first
"""
        found = diagnose(src, "event-consume-cycle")
        self.assertEqual(len(found), 1, [d.subject for d in found])

    def test_boundary_a_long_acyclic_chain_does_not_recurse_or_warn(self):
        """A module with hundreds of unrelated `consume by`/`emit` pairs
        chained one after another must not blow Python's recursion limit —
        the graph walk is iterative for exactly this reason. 2000 hops is
        well past the ~500-hop depth a naive recursive DFS would crash at
        (default recursion limit 1000, ~2 frames per hop)."""
        n = 2000
        event_consumes = {"event.e%d" % i: "wf.w%d" % i for i in range(n)}
        emits_by_workflow = {"wf.w%d" % i: {"event.e%d" % (i + 1)}
                             for i in range(n - 1)}
        diagnostics = Diagnostics()
        _check_event_consume_cycles(event_consumes, emits_by_workflow, diagnostics)
        self.assertEqual(list(diagnostics), [])

    def test_boundary_a_long_chain_that_closes_into_a_cycle_is_still_found(self):
        n = 2000
        event_consumes = {"event.e%d" % i: "wf.w%d" % i for i in range(n)}
        emits_by_workflow = {"wf.w%d" % i: {"event.e%d" % ((i + 1) % n)}
                             for i in range(n)}
        diagnostics = Diagnostics()
        _check_event_consume_cycles(event_consumes, emits_by_workflow, diagnostics)
        found = diagnostics.by_code("event-consume-cycle")
        self.assertEqual(len(found), 1, [d.subject for d in found])


if __name__ == "__main__":
    unittest.main()
