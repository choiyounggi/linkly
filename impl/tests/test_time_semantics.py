"""Issue #49 — time value semantics and the schedule trigger, reproduced first.

Every test in `TestRedRepro` asserts the FINAL behaviour RFC-0016 defines, so on
the code that shipped before this issue they all fail. That failing run is the
evidence the tests guard the reported defects rather than the fix
(`.orchestration/verify/i49-time-schedule.md` keeps its output).

The reproductions are the QA report's own:

  t2 F-5  "결제 후 30일 이내 환불" had no syntax: `30d` was not a duration (the
          units stopped at `m`), and a `DateTime` operand was refused outright,
          so the window could only be written by precomputing an `ageDays`
          Integer field — which moves the responsibility for ageing the row
          outside the platform.
  t3 F-2  "매일 자정 실행" had no vocabulary at all: `schedule`/`cron`/`daily`
          are 0 hits across the generated references, and `performance batch`
          parses but is unenforced, so there was no in-language workaround.

A note on F-5 ③ (`payment.createdAt <= 43200m`), because the QA report and this
suite disagree on purpose: the report saw it compile and then fail at RUNTIME
with a raw `TypeError`. RFC-0015 (issue #47) already pulled that forward to a
compile error. What RFC-0016 changes is the *reason* — `DateTime` stops being a
type with "no evaluator" and becomes a type with a DIMENSION, so the refusal
names the mismatch (instant vs scalar) instead of excluding the type.
"""

import os
import shutil
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.backend import BackendError, encode_condition_value
from lnpl.condition import (ConditionError, INT64_MAX, encode_instant,
                            is_instant_text, looks_like_instant, parse_value,
                            value_to_string)
from lnpl.diagnostics import ENFORCEMENT
from lnpl.interp import Interpreter, RunError
from lnpl.lexer import LexError, parse_duration_ms
from lnpl.lower import LowerError, lower
from lnpl.openapi import generate
from lnpl.parser import ParseError, parse
from lnpl.repo_policy import default_rows, row_key

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = os.path.join(REPO, ".claude", "tmp")

NEEDS_TOOLS = unittest.skipUnless(
    backend.toolchain_available(),
    "MLIR/LLVM toolchain not installed (brew install llvm)")

DAY_MS = 86400000

PAYMENT_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

# The 30-day refund window. `input.requestedAt` is the injected instant RFC-0016
# §Open Questions describes: the caller supplies "now" as a payload field, so
# both modes read the same value through the existing i64 parameter channel and
# no wall-clock primitive is needed.
REFUND_WINDOW = """capability postgres

entity Payment
    field
        id UUID
        createdAt DateTime

entity Refund
    field
        id UUID
        requestedAt DateTime

service RefundService
    policy
        timeout 5s

workflow RefundPayment
    read payment
    when input.requestedAt - payment.createdAt <= 30d
    create refund
"""

SCHEDULE_EVENT = """capability postgres

entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC
"""


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


def run_window(created_at, requested_at):
    """Run REFUND_WINDOW with one stored Payment row and an injected instant."""
    doc = compile_doc(REFUND_WINDOW, "refund")
    payload = {"id": PAYMENT_ID, "createdAt": created_at,
               "requestedAt": requested_at}
    rows = {"entity.payment": {row_key("entity.payment", payload):
                               {"id": PAYMENT_ID, "createdAt": created_at}}}
    return Interpreter(doc, repo_rows=rows).run_workflow("wf.refund.payment",
                                                         payload)


class TestRedRepro(unittest.TestCase):
    """The two blockers, each asserted at its final contract."""

    def test_time_window_compiles(self):
        """t2 F-5: the 30-day window is expressible — `DateTime` arithmetic + `30d`."""
        doc = compile_doc(REFUND_WINDOW, "refund")
        guards = nodes_of(doc, "Guard")
        self.assertEqual(len(guards), 1)
        self.assertEqual(guards[0]["condition"],
                         "input.requestedAt - payment.createdAt <= 30d")

    def test_time_window_admits_a_refund_inside_it(self):
        """t2 F-5: 19 days after payment -> the refund IS created."""
        result = run_window("2026-07-01T00:00:00Z", "2026-07-20T00:00:00Z")
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["read payment", "create refund"])
        self.assertEqual(result["skipped"], [])

    def test_time_window_refuses_a_refund_outside_it(self):
        """t2 F-5: 31 days after payment -> the refund is NOT created.

        The refusal happens inside the language. i44's contract holds: the run
        still reports `completed`, and the skip is the observable signal.
        """
        result = run_window("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]], ["read payment"])
        self.assertEqual(len(result["skipped"]), 1)

    def test_schedule_trigger_lowers(self):
        """t3 F-2: `on schedule daily at 00:00 UTC` reaches the IR."""
        doc = compile_doc(SCHEDULE_EVENT, "rollup")
        events = nodes_of(doc, "Event")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source"],
                         {"every": "daily", "at": "00:00", "zone": "UTC"})


class TestInstantCodec(unittest.TestCase):
    """The one encoder both modes call. Normal, error and boundary."""

    def test_a_zoned_timestamp_encodes_to_utc_epoch_milliseconds(self):
        self.assertEqual(encode_instant("1970-01-01T00:00:00Z", "t"), 0)
        self.assertEqual(encode_instant("1970-01-02T00:00:00Z", "t"), DAY_MS)

    def test_a_numeric_offset_is_normalised_to_utc(self):
        """`09:00+09:00` and `00:00Z` are the same instant, so the same integer."""
        self.assertEqual(encode_instant("2026-07-31T09:00:00+09:00", "t"),
                         encode_instant("2026-07-31T00:00:00Z", "t"))
        self.assertEqual(encode_instant("2026-07-31T00:00:00-05:00", "t"),
                         encode_instant("2026-07-31T05:00:00Z", "t"))

    def test_a_zoneless_timestamp_is_refused_and_the_message_says_why(self):
        with self.assertRaises(ConditionError) as ctx:
            encode_instant("2026-07-31T09:00:00", "payment.createdAt")
        message = str(ctx.exception)
        self.assertIn("payment.createdAt", message)
        self.assertIn("zone designator", message)
        self.assertIn("`Z`", message)

    def test_a_zone_abbreviation_is_refused(self):
        """`KST` is ambiguous, so it never becomes an instant."""
        with self.assertRaises(ConditionError):
            encode_instant("2026-07-31T09:00:00 KST", "t")

    def test_a_non_timestamp_is_refused_as_such(self):
        for raw in ("not a date", "", "12345"):
            with self.assertRaises(ConditionError) as ctx:
                encode_instant(raw, "t")
            self.assertIn("not a date-time", str(ctx.exception))

    def test_an_impossible_date_is_refused(self):
        for raw in ("2026-13-01T00:00:00Z", "2026-00-10T00:00:00Z",
                    "2026-07-31T25:00:00Z", "2026-07-31T00:61:00Z"):
            with self.assertRaises(ConditionError):
                encode_instant(raw, "t")

    def test_boundary_instants_before_the_epoch_are_negative(self):
        self.assertEqual(encode_instant("1969-12-31T00:00:00Z", "t"), -DAY_MS)

    def test_boundary_sub_second_precision_truncates_to_milliseconds(self):
        self.assertEqual(encode_instant("1970-01-01T00:00:00.5Z", "t"), 500)
        self.assertEqual(encode_instant("1970-01-01T00:00:00.0005Z", "t"), 0)
        self.assertEqual(encode_instant("1970-01-01T00:00:00.999Z", "t"), 999)

    def test_the_two_shape_predicates_disagree_only_about_the_zone(self):
        zoned, bare = "2026-07-31T09:00:00Z", "2026-07-31T09:00:00"
        self.assertTrue(is_instant_text(zoned))
        self.assertTrue(looks_like_instant(zoned))
        self.assertFalse(is_instant_text(bare))
        self.assertTrue(looks_like_instant(bare),
                        "an unzoned timestamp must still be recognised as one, "
                        "or its diagnostic names the wrong problem")
        self.assertFalse(looks_like_instant("12345"))
        self.assertFalse(is_instant_text(None))


class TestDurationUnits(unittest.TestCase):
    """`h` and `d`, and the single table the whole toolchain reads."""

    def test_the_new_units_are_exact_millisecond_counts(self):
        self.assertEqual(parse_duration_ms("1h"), 3600000)
        self.assertEqual(parse_duration_ms("30d"), 30 * DAY_MS)

    def test_every_path_reads_one_table(self):
        """The multiplier used to be spelled out at five call sites."""
        from lnpl.backend import _duration_ms as backend_ms
        from lnpl.interp import _duration_ms as interp_ms
        self.assertEqual(parse_duration_ms("2d"), 2 * DAY_MS)
        self.assertEqual(interp_ms("2d"), 2 * DAY_MS)
        self.assertEqual(backend_ms("2d"), 2 * DAY_MS)

    def test_a_longer_suffix_wins(self):
        """`3ms` is three milliseconds, not three minutes and a stray `s`."""
        self.assertEqual(parse_duration_ms("3ms"), 3)
        self.assertEqual(parse_duration_ms("3m"), 180000)

    def test_error_a_non_duration_is_refused(self):
        for tok in ("d", "xd", "3y", "3w"):
            with self.assertRaises(LexError):
                parse_duration_ms(tok)

    def test_boundary_a_duration_past_the_i64_domain_is_refused(self):
        with self.assertRaises(ConditionError) as ctx:
            parse_value("99999999999999999999d")
        self.assertIn("64-bit", str(ctx.exception))

    def test_boundary_an_integer_literal_past_the_i64_domain_is_refused(self):
        with self.assertRaises(ConditionError):
            parse_value(str(INT64_MAX + 1))

    def test_rendering_picks_the_coarsest_exact_unit(self):
        self.assertEqual(value_to_string(parse_value("30d")), "30d")
        self.assertEqual(value_to_string(parse_value("24h")), "1d")
        self.assertEqual(value_to_string(parse_value("90m")), "90m")
        self.assertEqual(value_to_string(parse_value("0ms")), "0ms")


class TestDimensionRules(unittest.TestCase):
    """RFC-0016's two-dimension lattice, decided at compile time."""

    def compile_fails(self, source, *fragments):
        with self.assertRaises((LowerError, ParseError)) as ctx:
            compile_doc(source, "m")
        message = str(ctx.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message

    def workflow(self, guard):
        return REFUND_WINDOW.replace(
            "when input.requestedAt - payment.createdAt <= 30d",
            "when " + guard)

    def test_an_elapsed_duration_compares_to_a_duration(self):
        compile_doc(self.workflow(
            "input.requestedAt - payment.createdAt <= 30d"), "m")

    def test_two_instants_compare_to_each_other(self):
        compile_doc(self.workflow("payment.createdAt <= input.requestedAt"), "m")

    def test_error_an_instant_may_not_be_compared_to_a_duration(self):
        """t2 F-5 ③: `payment.createdAt <= 43200m` names a real mismatch now."""
        self.compile_fails(self.workflow("payment.createdAt <= 43200m"),
                           "payment.createdAt", "instant", "scalar",
                           "compares like with like")

    def test_error_an_instant_may_not_be_compared_to_a_plain_number(self):
        self.compile_fails(self.workflow("payment.createdAt > 0"),
                           "instant", "scalar")

    def test_error_two_instants_may_not_be_added(self):
        self.compile_fails(
            self.workflow("payment.createdAt + input.requestedAt <= 30d"),
            "adds two instants", "subtract them")

    def test_an_instant_plus_a_duration_is_still_an_instant(self):
        compile_doc(self.workflow(
            "payment.createdAt + 30d >= input.requestedAt"), "m")

    def test_boundary_a_bare_reference_keeps_todays_permissiveness(self):
        """No new compile-time refusal: an undeclared name is a runtime question."""
        compile_doc(self.workflow("someField <= 30d"), "m")

    def test_boundary_an_integer_field_may_still_meet_a_duration(self):
        """`scalar` deliberately holds both, so no existing program breaks."""
        source = REFUND_WINDOW.replace("        requestedAt DateTime",
                                       "        requestedAt DateTime\n"
                                       "        attempts Integer")
        source = source.replace(
            "when input.requestedAt - payment.createdAt <= 30d",
            "when input.attempts <= 30d")
        compile_doc(source, "m")

    def test_error_a_type_with_no_evaluator_is_still_refused(self):
        source = REFUND_WINDOW.replace("        createdAt DateTime",
                                       "        createdAt DateTime\n"
                                       "        fee Money")
        source = source.replace(
            "when input.requestedAt - payment.createdAt <= 30d",
            "when payment.fee > 0")
        self.compile_fails(source, "neither Integer nor DateTime", "Money")


class TestTimeWindowBoundaries(unittest.TestCase):
    """`<=` is inclusive: the window's own edge, and one millisecond each side."""

    def _at(self, offset_ms):
        base = "2026-07-01T00:00:00Z"
        start = encode_instant(base, "t")
        millis = start + offset_ms
        seconds, ms = divmod(millis, 1000)
        import datetime
        stamp = datetime.datetime.fromtimestamp(
            seconds, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        return base, "%s.%03dZ" % (stamp, ms)

    def _ran(self, offset_ms):
        created, requested = self._at(offset_ms)
        return [s["step"] for s in run_window(created, requested)["steps"]]

    def test_exactly_thirty_days_is_inside_the_window(self):
        self.assertIn("create refund", self._ran(30 * DAY_MS))

    def test_one_millisecond_under_thirty_days_is_inside(self):
        self.assertIn("create refund", self._ran(30 * DAY_MS - 1))

    def test_one_millisecond_over_thirty_days_is_outside(self):
        self.assertNotIn("create refund", self._ran(30 * DAY_MS + 1))

    def test_boundary_a_zero_length_gap_is_inside(self):
        self.assertIn("create refund", self._ran(0))

    def test_boundary_a_negative_gap_is_inside(self):
        """A refund requested before the payment is a negative elapsed time,
        which is still `<= 30d`. The window bounds lateness, not order."""
        self.assertIn("create refund", self._ran(-DAY_MS))

    def test_error_a_zoneless_stored_value_raises_the_existing_run_error(self):
        """A value fault in a guard is `RunError`, which the CLI reports as
        `runtime error: ...` with rc=3.

        This is the contract a malformed condition value already had (the
        pre-RFC-0016 `Cannot compare non-numeric` took the same path), so time
        values reuse it rather than introducing a class of their own. It is NOT
        the in-run step failure contract (`status: failed`, rc=1): a guard is
        evaluated while the step list is being flattened, before any step runs.
        """
        with self.assertRaises(RunError) as ctx:
            run_window("2026-07-01T00:00:00", "2026-07-02T00:00:00Z")
        message = str(ctx.exception)
        self.assertIn("zone designator", message)
        self.assertIn("payment.createdAt", message)


class TestModeBInjection(unittest.TestCase):
    """The value mode B puts on the i64 channel is the value mode A computed."""

    def test_both_modes_encode_one_string_to_one_integer(self):
        stamp = "2026-07-31T09:00:00Z"
        self.assertEqual(encode_condition_value(stamp),
                         encode_instant(stamp, "t"))

    def test_integers_and_booleans_keep_their_existing_path(self):
        self.assertEqual(encode_condition_value(7), 7)
        self.assertEqual(encode_condition_value(True), 1)
        self.assertEqual(encode_condition_value(False), 0)

    def test_error_a_zoneless_value_is_refused_with_the_reason(self):
        with self.assertRaises(BackendError) as ctx:
            encode_condition_value("2026-07-31T09:00:00")
        self.assertIn("zone designator", str(ctx.exception))

    def test_error_other_text_is_still_refused(self):
        with self.assertRaises(BackendError):
            encode_condition_value("nonsense")

    def test_boundary_pre_epoch_instants_cross_the_channel(self):
        self.assertEqual(encode_condition_value("1969-12-31T00:00:00Z"), -DAY_MS)


class TestScheduleTrigger(unittest.TestCase):
    """The declaration, its refusals, and the fact that nothing runs it."""

    def source(self, spec="daily at 00:00 UTC"):
        return SCHEDULE_EVENT.replace("daily at 00:00 UTC", spec)

    def compile_fails(self, spec, *fragments):
        with self.assertRaises((LowerError, ParseError)) as ctx:
            compile_doc(self.source(spec), "m")
        message = str(ctx.exception)
        for fragment in fragments:
            self.assertIn(fragment, message)
        return message

    def test_the_entity_source_form_is_untouched(self):
        doc = compile_doc("capability postgres\n\nentity Order\n    field\n"
                          "        id UUID\n\nevent Placed on Order create\n", "m")
        event = nodes_of(doc, "Event")[0]
        self.assertEqual(event["source"], {"ref": "entity.order", "on": "create"})

    def test_error_an_unknown_recurrence_names_the_allowed_set(self):
        self.compile_fails("weekly at 00:00 UTC", "weekly", "allowed: daily")

    def test_error_a_non_utc_zone_names_the_allowed_set(self):
        self.compile_fails("daily at 00:00 KST", "KST", "allowed: UTC")

    def test_error_an_iana_zone_explains_the_build_machine_problem(self):
        self.compile_fails("daily at 00:00 Asia/Seoul", "Asia/Seoul",
                           "tz database", "machine")

    def test_error_a_malformed_shape_names_the_expected_form(self):
        with self.assertRaises(ParseError) as ctx:
            compile_doc(self.source("daily 00:00 UTC"), "m")
        self.assertIn("on schedule <every> at <HH:MM> <zone>", str(ctx.exception))

    def test_boundary_the_first_and_last_admissible_minute(self):
        for at in ("00:00", "23:59"):
            doc = compile_doc(self.source("daily at %s UTC" % at), "m")
            self.assertEqual(nodes_of(doc, "Event")[0]["source"]["at"], at)

    def test_boundary_times_one_step_outside_the_range_are_refused(self):
        for at in ("24:00", "00:60", "0:00", "000:00"):
            self.compile_fails("daily at %s UTC" % at, "time of day")

    def test_the_declaration_reports_that_nothing_runs_it(self):
        """t3 F-2's real complaint was silence, not absence. issue #81 gave
        the declaration a real trigger surface, so the message now names it
        instead of naming #26 (the issue that used to own "nobody built
        this yet") — but the core complaint (nothing calls it BY DEFAULT)
        still has to survive, or the diagnostic would be a false all-clear.
        """
        mod = lower(parse(SCHEDULE_EVENT), "rollup")
        subjects = [d.subject for d in mod.diagnostics.all()]
        self.assertIn("event schedule", subjects)
        diag = [d for d in mod.diagnostics.all()
                if d.subject == "event schedule"][0]
        self.assertEqual(diag.code, "declared-not-enforced")
        # #52: a legitimate schedule declaration is `info` — the platform
        # stating what it does, not a mistake the author can edit away.
        self.assertEqual(diag.severity, "info")
        self.assertIn("lnpl trigger", diag.message)
        self.assertIn("default", diag.message)

    def test_negative_control_a_document_without_a_schedule_is_silent(self):
        mod = lower(parse("capability postgres\n\nentity Order\n    field\n"
                          "        id UUID\n\nevent Placed on Order create\n"), "m")
        self.assertNotIn("event schedule",
                         [d.subject for d in mod.diagnostics.all()])

    def test_two_schedules_report_twice(self):
        source = SCHEDULE_EVENT + "\nevent NightlyPurge on schedule daily at 03:00 UTC\n"
        mod = lower(parse(source), "m")
        self.assertEqual(
            len([d for d in mod.diagnostics.all()
                 if d.subject == "event schedule"]), 2)


class TestScheduleOpenApi(unittest.TestCase):
    """The schedule reaches the contract as metadata, never as a path."""

    def test_a_schedule_appears_as_a_document_extension(self):
        spec = generate(compile_doc(SCHEDULE_EVENT, "rollup"))
        self.assertEqual(spec["x-lnpl-schedules"],
                         [{"event": "event.daily.rollup", "every": "daily",
                           "at": "00:00", "zone": "UTC",
                           "enforcement": "unenforced"}])

    def test_the_enforcement_field_comes_from_the_matrix(self):
        spec = generate(compile_doc(SCHEDULE_EVENT, "rollup"))
        self.assertEqual(spec["x-lnpl-schedules"][0]["enforcement"],
                         ENFORCEMENT[("event", "schedule")][0])

    def test_a_schedule_creates_no_http_path(self):
        spec = generate(compile_doc(SCHEDULE_EVENT, "rollup"))
        self.assertEqual(spec["paths"], {})

    def test_negative_control_a_document_without_schedules_omits_the_key(self):
        """Every pre-RFC-0016 document must generate byte-identical output."""
        spec = generate(compile_doc(REFUND_WINDOW, "refund"))
        self.assertNotIn("x-lnpl-schedules", spec)

    def test_an_entity_source_event_is_not_listed_as_a_schedule(self):
        source = SCHEDULE_EVENT + "\nevent Stored on Report create\n"
        spec = generate(compile_doc(source, "rollup"))
        self.assertEqual(len(spec["x-lnpl-schedules"]), 1)


@NEEDS_TOOLS
class TestTimeWindowModeEquivalence(unittest.TestCase):
    """The window decides the same steps in both modes, proved by a flip."""

    def setUp(self):
        os.makedirs(TMP, exist_ok=True)
        self.workdir = tempfile.mkdtemp(prefix="lnpl-i49-", dir=TMP)
        self.doc = compile_doc(REFUND_WINDOW, "refund")

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _payload(self, requested):
        return {"id": PAYMENT_ID, "createdAt": "2026-07-01T00:00:00Z",
                "requestedAt": requested}

    def _both(self, requested):
        payload = self._payload(requested)
        rows = default_rows(self.doc, "wf.refund.payment", payload)
        rows.setdefault("entity.payment", {})
        rows["entity.payment"][row_key("entity.payment", payload)] = {
            "id": PAYMENT_ID, "createdAt": payload["createdAt"]}
        a = differential.observe_mode_a(self.doc, "wf.refund.payment", payload,
                                        rows)
        b = differential.observe_mode_b(self.doc, "wf.refund.payment",
                                        self.workdir, payload=payload)
        return a, b

    def test_control_pair_the_two_payloads_produce_different_step_sets(self):
        """Before claiming agreement, prove the value reaches the guard at all.

        Two runs of ONE program whose only difference is the instant. If both
        produced the same steps the equivalence below would be vacuous — it
        would agree about a value nothing read.
        """
        inside, _ = self._both("2026-07-20T00:00:00Z")
        outside, _ = self._both("2026-08-05T00:00:00Z")
        self.assertNotEqual(inside["order"], outside["order"],
                            "the instant never reached the guard")
        self.assertIn("create", " ".join(inside["order"]).lower())
        self.assertNotIn("create", " ".join(outside["order"]).lower())

    def test_inside_the_window_both_modes_run_the_same_steps(self):
        a, b = self._both("2026-07-20T00:00:00Z")
        self.assertEqual(a["order"], b["order"])

    def test_outside_the_window_both_modes_skip_the_same_steps(self):
        a, b = self._both("2026-08-05T00:00:00Z")
        self.assertEqual(a["order"], b["order"])

    def test_differential_reports_equivalent_on_both_sides_of_the_window(self):
        for requested in ("2026-07-20T00:00:00Z", "2026-08-05T00:00:00Z"):
            payload = self._payload(requested)
            rows = default_rows(self.doc, "wf.refund.payment", payload)
            rows.setdefault("entity.payment", {})
            rows["entity.payment"][row_key("entity.payment", payload)] = {
                "id": PAYMENT_ID, "createdAt": payload["createdAt"]}
            ok, report = differential.verify(self.doc, "wf.refund.payment",
                                             payload, rows, self.workdir)
            self.assertTrue(ok, "\n".join(report))

    def test_negative_control_a_seeded_divergence_is_caught(self):
        """A comparator flipped in ONE mode must turn the verdict red.

        Without this the equivalence tests above only ever show green, and a
        comparison that never runs is indistinguishable from one that agrees.
        """
        payload = self._payload("2026-07-20T00:00:00Z")
        rows = default_rows(self.doc, "wf.refund.payment", payload)
        rows.setdefault("entity.payment", {})
        rows["entity.payment"][row_key("entity.payment", payload)] = {
            "id": PAYMENT_ID, "createdAt": payload["createdAt"]}

        mutant = compile_doc(
            REFUND_WINDOW.replace("<= 30d", "> 30d"), "refund")
        # Mode A observes the mutant (guard inverted); mode B observes the
        # original. A comparator that decides nothing would leave these equal.
        a = differential.observe_mode_a(mutant, "wf.refund.payment", payload,
                                        rows)
        b = differential.observe_mode_b(self.doc, "wf.refund.payment",
                                        self.workdir, payload=payload)
        self.assertNotEqual(a["order"], b["order"],
                            "flipping the guard changed nothing — the "
                            "comparison is not being evaluated")


if __name__ == "__main__":
    unittest.main()
