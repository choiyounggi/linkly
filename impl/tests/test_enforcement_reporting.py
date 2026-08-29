"""RFC-0043 (issue #138/#140): a driver factory's optional class/static
`lnpl_enforcement` attribute self-reports how it behaves along a closed axis
table, and the core synthesizes `info` diagnostics from it — the sentence
issue #140's acceptance bar names ("capability kafka를 선언했고, 설치된
드라이버는 at-least-once만 보장하므로 emit userCreated는 중복 전달될 수
있다") has to come out of `lnpl compile` for real.

Two layers are tested separately: `_enforcement_of`/`enforcement_reports`
(the SPI reader — no compilation involved, entry-point injection only) and
`enforcement_diagnostic_records`/the full `compile` path (the capability<->
report bridge, anchored on real compiled IR). Entry-point injection follows
`test_cli_capabilities.py`'s `registered()` pattern: the real
`importlib.metadata.entry_points` is monkeypatched, group-filtered, so one
test can register drivers under several groups (`lnpl.drivers`/
`lnpl.caches`/`lnpl.tokens`) at once without leaking into the others.
"""

import contextlib
import io
import json
import os
import shutil
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import cli
from lnpl import drivers as drivers_module
from lnpl.capabilities import (CAPABILITY_SLOT, ENFORCEMENT_AXIS_VALUES,
                               _enforcement_of, enforcement_reports)

from tests import enforcement_spi_fixture as fx

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGIN = os.path.join(REPO, "examples", "login.lnpl")

DRIVERS_GROUP = drivers_module.DRIVERS_ENTRY_POINT_GROUP
CACHES_GROUP = drivers_module.CACHES_ENTRY_POINT_GROUP
TOKENS_GROUP = drivers_module.TOKENS_ENTRY_POINT_GROUP

# A module with `capability postgres` and one `emit` — RFC-0043 §Examples'
# "kafka-outbox-adjacent" golden-adjacent scenario (Login itself declares no
# `delivery`-bearing capability, so this fixture stands in for it). `create
# payment` (not `find`) so the event's `on Payment create` source actually
# matches this workflow's own create — otherwise `event-source-orphaned`
# (issue #98) rides along, which would make `StrictNonParticipationTest`
# ambiguous about *which* diagnostic (core or RFC-0043) gates `--strict`.
DELIVERY_SRC = """
capability postgres
entity Payment
    field
        id UUID
        amountCents Integer
event userCreated on Payment create
service Checkout
    database
        postgres
workflow Approve
    create payment
    emit userCreated
"""

# No `capability` declaration at all — the delivery-reporting driver below
# must contribute nothing to this module's diagnostics (boundary: capability
# 없는 모듈 emit -> 무진단).
NO_CAPABILITY_EMIT_SRC = """
entity Payment
    field
        id UUID
        amountCents Integer
event userCreated on Payment create
service Checkout
workflow Approve
    create payment
    emit userCreated
"""


def entry_point(group, name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=group)


def registered(*entry_points):
    """Group-filtered patch of the real `importlib.metadata.entry_points`
    (`test_cli_capabilities.py`'s pattern) — every module that calls it
    (`drivers.py`, `capabilities.py`) shares the one real stdlib module
    object, so one patch here reaches all of them."""
    by_group = {}
    for ep in entry_points:
        by_group.setdefault(ep.group, []).append(ep)

    def fake_entry_points(**kwargs):
        return list(by_group.get(kwargs.get("group"), ()))

    return mock.patch.object(importlib_metadata, "entry_points", fake_entry_points)


def _main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _write(workdir, name, text):
    os.makedirs(workdir, exist_ok=True)
    path = os.path.join(workdir, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


# ---------------------------------------------------------------------------
# T1: the SPI reader (`_enforcement_of`, `enforcement_reports`) —
# no compilation, entry-point injection only.
# ---------------------------------------------------------------------------

class EnforcementOfTest(unittest.TestCase):
    """Normal: one valid report per axis, read straight off the fixture
    classes (no entry-point machinery — `_enforcement_of` takes the loaded
    object directly, same as `ep.load()` would hand it)."""

    def test_delivery_axis(self):
        self.assertEqual(_enforcement_of(fx.DeliveryReportingDriver),
                         {"delivery": "at-least-once"})

    def test_isolation_axis(self):
        self.assertEqual(_enforcement_of(fx.IsolationReportingDriver),
                         {"isolation": "read-committed"})

    def test_cache_scope_axis(self):
        self.assertEqual(_enforcement_of(fx.CacheScopeReportingDriver),
                         {"cache_scope": "process-local"})

    def test_token_claims_axis(self):
        self.assertEqual(_enforcement_of(fx.TokenClaimsReportingDriver),
                         {"token_claims": ["sub", "aud", "exp"]})

    # ---- boundary / error --------------------------------------------

    def test_absent_attribute_is_none(self):
        self.assertIsNone(_enforcement_of(fx.NoReportDriver))

    def test_builtin_driver_reports_nothing(self):
        """RFC-0043 §신고 SPI: `fake`/`sqlite` never gained this attribute,
        so a built-in driver class is indistinguishable from "no report"."""
        self.assertIsNone(_enforcement_of(drivers_module.SqliteRepositoryDriver))
        self.assertIsNone(_enforcement_of(drivers_module.HmacTokenProvider))

    def test_unknown_key_is_dropped_but_the_known_axis_survives(self):
        self.assertEqual(_enforcement_of(fx.UnknownKeyDriver),
                         {"delivery": "exactly-once"})

    def test_out_of_vocabulary_value_drops_the_whole_axis(self):
        self.assertIsNone(_enforcement_of(fx.OutOfVocabularyDriver))

    def test_non_list_token_claims_is_dropped(self):
        self.assertIsNone(_enforcement_of(fx.NonListClaimsDriver))

    def test_axis_vocabularies_are_the_closed_rfc_table(self):
        self.assertEqual(set(ENFORCEMENT_AXIS_VALUES),
                         {"delivery", "isolation", "cache_scope"})
        self.assertEqual(ENFORCEMENT_AXIS_VALUES["delivery"],
                         ("at-most-once", "at-least-once", "exactly-once"))
        self.assertEqual(ENFORCEMENT_AXIS_VALUES["isolation"],
                         ("read-uncommitted", "read-committed",
                          "repeatable-read", "serializable"))
        self.assertEqual(ENFORCEMENT_AXIS_VALUES["cache_scope"],
                         ("process-local", "shared"))


class EnforcementReportsTest(unittest.TestCase):
    """`enforcement_reports(slot)`: installed, loadable, reporting drivers
    only — a load failure can't report anything."""

    def test_a_registered_reporting_driver_is_collected_by_entry_point_name(self):
        ep = entry_point(DRIVERS_GROUP, "postgres",
                         "tests.enforcement_spi_fixture:IsolationReportingDriver")
        with registered(ep):
            reports = enforcement_reports("repository")

        self.assertEqual(reports, {"postgres": {"isolation": "read-committed"}})

    def test_a_load_failure_is_silently_excluded(self):
        broken = entry_point(DRIVERS_GROUP, "broken",
                             "tests.no_such_fixture_module_xyz:make_driver")
        with registered(broken):
            reports = enforcement_reports("repository")

        self.assertEqual(reports, {})

    def test_no_registered_drivers_is_an_empty_report(self):
        with registered():
            reports = enforcement_reports("cache")

        self.assertEqual(reports, {})

    def test_unknown_slot_raises(self):
        with self.assertRaises(ValueError):
            enforcement_reports("not-a-real-slot")


# ---------------------------------------------------------------------------
# T3: the capability <-> report bridge, anchored on real compiled IR.
# ---------------------------------------------------------------------------

class DeliveryDiagnosticTest(unittest.TestCase):
    """The issue #140 acceptance sentence, reproduced end to end."""

    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "enforcement-diag")
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)

    def test_the_140_sentence_appears_as_an_info_diagnostic(self):
        src = _write(self.workdir, "delivery.lnpl", DELIVERY_SRC)
        ep = entry_point(DRIVERS_GROUP, "kafka",
                         "tests.enforcement_spi_fixture:DeliveryReportingDriver")
        with registered(ep):
            rc, out, err = _main(["compile", src, "--json"])

        self.assertEqual(rc, 0)
        doc = json.loads(out)
        records = [d for d in doc["diagnostics"] if d["code"].startswith("kafka/")]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["code"], "kafka/delivery-at-least-once")
        self.assertEqual(record["severity"], "info")
        self.assertIn("at-least-once", record["message"])
        self.assertIn("more than once", record["message"])
        self.assertEqual(set(record.keys()),
                         {"code", "severity", "where", "subject", "message", "line"})

    def test_anchored_on_the_emit_step_with_its_line_and_surface_text(self):
        src = _write(self.workdir, "delivery2.lnpl", DELIVERY_SRC)
        ep = entry_point(DRIVERS_GROUP, "kafka",
                         "tests.enforcement_spi_fixture:DeliveryReportingDriver")
        with registered(ep):
            rc, out, err = _main(["compile", src, "--json"])

        self.assertEqual(rc, 0)
        doc = json.loads(out)
        record = next(d for d in doc["diagnostics"] if d["code"].startswith("kafka/"))
        self.assertEqual(record["subject"], "emit userCreated")
        self.assertEqual(record["where"], "wf.approve")
        self.assertEqual(record["line"], 13)

    def test_no_capability_declared_means_no_diagnostic(self):
        """Boundary: an installed, reporting driver contributes nothing to a
        module that never activates its slot (RFC-0043 §매칭 규칙)."""
        src = _write(self.workdir, "nocap.lnpl", NO_CAPABILITY_EMIT_SRC)
        ep = entry_point(DRIVERS_GROUP, "kafka",
                         "tests.enforcement_spi_fixture:DeliveryReportingDriver")
        with registered(ep):
            rc, out, err = _main(["compile", src, "--json"])

        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertFalse(any(d["code"].startswith("kafka/")
                             for d in doc["diagnostics"]))


class FourAxisAnchorTest(unittest.TestCase):
    """One normal case per axis, each checked against its own RFC-0043
    anchor node (measured against `examples/login.lnpl --json`, plan D5)."""

    def _compile_login_with(self, *entry_points):
        with registered(*entry_points):
            rc, out, err = _main(["compile", LOGIN, "--json"])
        self.assertEqual(rc, 0)
        return json.loads(out)["diagnostics"]

    def test_isolation_anchors_on_the_capability_postgres_node(self):
        ep = entry_point(DRIVERS_GROUP, "postgres",
                         "tests.enforcement_spi_fixture:IsolationReportingDriver")
        records = [d for d in self._compile_login_with(ep)
                  if d["code"].startswith("postgres/")]

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["code"], "postgres/isolation-read-committed")
        self.assertEqual(record["subject"], "capability postgres")
        self.assertEqual(record["where"], "svc.login")
        self.assertEqual(record["line"], 18)

    def test_cache_scope_anchors_on_the_performance_cache_node(self):
        ep = entry_point(CACHES_GROUP, "redis",
                         "tests.enforcement_spi_fixture:CacheScopeReportingDriver")
        records = [d for d in self._compile_login_with(ep)
                  if d["code"].startswith("redis/")]

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["code"], "redis/cache-scope-process-local")
        self.assertEqual(record["subject"], "performance cache 5m")
        self.assertEqual(record["where"], "svc.login")

    def test_token_claims_anchors_on_the_security_jwt_node(self):
        ep = entry_point(TOKENS_GROUP, "jwt",
                         "tests.enforcement_spi_fixture:TokenClaimsReportingDriver")
        records = [d for d in self._compile_login_with(ep)
                  if d["code"].startswith("jwt/")]

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["code"], "jwt/token-claims")
        self.assertEqual(record["subject"], "security jwt")
        self.assertEqual(record["where"], "svc.login")
        self.assertIn("sub, aud, exp", record["message"])

    def test_all_three_login_axes_coexist_with_the_unknown_verb_regression(self):
        """RFC-0043 §Examples: the new `info` records and Login's own
        pre-existing `unknown-verb` warnings (issue #36 fixture) coexist."""
        drivers_ep = entry_point(DRIVERS_GROUP, "postgres",
                                 "tests.enforcement_spi_fixture:IsolationReportingDriver")
        caches_ep = entry_point(CACHES_GROUP, "redis",
                                "tests.enforcement_spi_fixture:CacheScopeReportingDriver")
        tokens_ep = entry_point(TOKENS_GROUP, "jwt",
                                "tests.enforcement_spi_fixture:TokenClaimsReportingDriver")
        records = self._compile_login_with(drivers_ep, caches_ep, tokens_ep)

        codes = {d["code"] for d in records}
        self.assertIn("postgres/isolation-read-committed", codes)
        self.assertIn("redis/cache-scope-process-local", codes)
        self.assertIn("jwt/token-claims", codes)
        self.assertIn("unknown-verb", codes)


class StrictNonParticipationTest(unittest.TestCase):
    """RFC-0043 §등급과 게이팅: an enforcement diagnostic never gates
    `--strict`, however high its (fixed) severity — same non-participation
    rule RFC-0042 already gives every `<prefix>/<code>`."""

    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "enforcement-diag")
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)

    def test_strict_stays_rc_0_with_only_enforcement_diagnostics_present(self):
        src = _write(self.workdir, "strict.lnpl", DELIVERY_SRC)
        ep = entry_point(DRIVERS_GROUP, "kafka",
                         "tests.enforcement_spi_fixture:DeliveryReportingDriver")
        with registered(ep):
            rc, out, err = _main(["compile", src, "--strict", "--json"])

        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertTrue(any(d["code"].startswith("kafka/") for d in doc["diagnostics"]))


class CapabilitySlotTableTest(unittest.TestCase):
    def test_matches_the_rfc_matching_table(self):
        self.assertEqual(CAPABILITY_SLOT,
                         {"postgres": "repository", "redis": "cache",
                          "jwt": "token", "http": "network"})


if __name__ == "__main__":
    unittest.main()
