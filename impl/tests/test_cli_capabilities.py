"""`lnpl capabilities` / `lnpl capabilities --json` — installed-extension
catalog, never-fails discovery (issue #134).

Before this, the only way to learn whether an extension scheme was actually
registered (and actually loadable) was to try it and read the failure —
`pg_available_extensions`'s absence. `capabilities_document()`
(`impl/lnpl/capabilities.py`) is the single source; this command is one of
its two consumers (CLI, MCP `lnpl_capabilities`).

Both the bare form and `--json` print the same stable JSON document — same
convention `lnpl vocab` settled (issue #135), mirrored here (plan D5).

Entry-point injection uses the `driver_spi_fixture` pattern `test_driver_spi.py`
established: `importlib.metadata.entry_points` is monkeypatched to a
controlled, in-process set (group-filtered so unrelated slots stay empty),
and `EntryPoint.load()` itself is never mocked — a genuinely importable
fixture module proves the load-success path for real, and a genuinely
missing module proves the load-failure path for real.
"""

import contextlib
import io
import json
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import cli
from lnpl.capabilities import SLOTS, capabilities_document

CONTRACT_SLOTS = {"repository", "cache", "network", "token", "exporter", "kb",
                  "generators", "diagnostics"}

# The group each slot resolves through, keyed the same way SLOTS is keyed —
# used only to target fixture entry-points at the right slot without leaking
# into the others.
GROUP_OF_SLOT = {slot: group for slot, group, _builtin, _fn in SLOTS}


def _main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def entry_point(group, name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=group)


def entry_point_with_version(group, name, value, version):
    """A registered entry point whose owning distribution resolves, with the
    given `version` — exercises the `version` field's normal (resolvable)
    path. A hand-built `EntryPoint` (via `entry_point()` above) has no
    `.dist` and so is the unresolvable/boundary path instead."""
    class _FakeDist:
        pass
    fake_dist = _FakeDist()
    fake_dist.version = version
    return entry_point(group, name, value)._for(fake_dist)


def registered(*entry_points):
    """Patch the real `importlib.metadata.entry_points` (shared by
    drivers.py/wsgi.py/kb.py) to return only `entry_points`, group-filtered —
    every slot not named in `entry_points` sees an empty registration, so a
    test controls exactly one slot without the others picking up stragglers."""
    by_group = {}
    for ep in entry_points:
        by_group.setdefault(ep.group, []).append(ep)

    def fake_entry_points(**kwargs):
        return list(by_group.get(kwargs.get("group"), ()))

    return mock.patch.object(importlib_metadata, "entry_points", fake_entry_points)


# A real, importable factory (loadable: true) — same fixture module
# test_driver_spi.py's DEMO_ENTRY_POINT resolves.
DEMO_VALUE = "tests.driver_spi_fixture:make_demo_driver"
# A module that does not exist (loadable: false) — mirrors
# test_driver_spi.py's EntryPointLoadFailureTest fixture.
BROKEN_VALUE = "tests.no_such_fixture_module_xyz:make_driver"


class TestCliCapabilities(unittest.TestCase):

    # ---- normal -----------------------------------------------------------

    def test_json_flag_prints_a_valid_document_with_the_eight_contract_slots(self):
        with registered():
            rc, out, err = _main(["capabilities", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        doc = json.loads(out)
        self.assertEqual(set(doc.keys()), {"lnpl_version", "slots"})
        self.assertEqual(set(doc["slots"]), CONTRACT_SLOTS)

    def test_bare_and_json_forms_print_the_identical_document(self):
        with registered():
            rc_bare, out_bare, _ = _main(["capabilities"])
            rc_json, out_json, _ = _main(["capabilities", "--json"])
        self.assertEqual(rc_bare, 0)
        self.assertEqual(rc_json, 0)
        self.assertEqual(json.loads(out_bare), json.loads(out_json))

    def test_cli_output_matches_the_shared_source_function_exactly(self):
        # If cli.py ever hand-builds its own document instead of delegating
        # to capabilities_document(), this is the one test that catches it.
        with registered():
            _rc, out, _err = _main(["capabilities", "--json"])
            expected = capabilities_document()
        self.assertEqual(json.loads(out), expected)

    def test_a_registered_entry_point_with_a_resolvable_distribution_reports_its_version(self):
        versioned = entry_point_with_version(GROUP_OF_SLOT["cache"], "versioned",
                                             DEMO_VALUE, "0.2.1")
        with registered(versioned):
            rc, out, _err = _main(["capabilities", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(doc["slots"]["cache"]["registered"],
                         [{"name": "versioned", "entry_point": DEMO_VALUE,
                           "version": "0.2.1", "loadable": True}])

    def test_each_slot_reports_its_own_builtin_names(self):
        with registered():
            _rc, out, _err = _main(["capabilities", "--json"])
        doc = json.loads(out)
        self.assertEqual(doc["slots"]["repository"]["builtin"], ["fake", "sqlite"])
        self.assertEqual(doc["slots"]["kb"]["builtin"], [])
        self.assertEqual(doc["slots"]["generators"]["builtin"], ["openapi"])
        self.assertEqual(doc["slots"]["diagnostics"]["builtin"], [])

    def test_a_reporting_driver_gets_an_additive_enforcement_key(self):
        """RFC-0043 §매트릭스 실측 렌더링 1: a loadable driver whose
        `lnpl_enforcement` validates gets the key, holding exactly the
        validated report — the same one `enforcement_diagnostic_records`
        would synthesize a diagnostic from (single source of truth)."""
        reporting = entry_point(
            GROUP_OF_SLOT["repository"], "postgres",
            "tests.enforcement_spi_fixture:IsolationReportingDriver")
        with registered(reporting):
            rc, out, _err = _main(["capabilities", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(
            doc["slots"]["repository"]["registered"],
            [{"name": "postgres",
              "entry_point": "tests.enforcement_spi_fixture:IsolationReportingDriver",
              "version": None, "loadable": True,
              "enforcement": {"isolation": "read-committed"}}])

    def test_a_non_reporting_driver_has_no_enforcement_key(self):
        """Boundary: `loadable: true` but no `lnpl_enforcement` — the key is
        absent, never an empty `dict` (RFC-0043 §매트릭스 실측 렌더링 1)."""
        demo = entry_point(GROUP_OF_SLOT["repository"], "demo", DEMO_VALUE)
        with registered(demo):
            rc, out, _err = _main(["capabilities", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        entry = doc["slots"]["repository"]["registered"][0]
        self.assertEqual(entry["name"], "demo")
        self.assertNotIn("enforcement", entry)

    def test_an_unloadable_reporting_looking_entry_point_has_no_enforcement_key(self):
        """Boundary: `loadable: false` means the driver was never imported,
        so there is nothing to read `lnpl_enforcement` off of — no key,
        regardless of what the (unreachable) module might have declared."""
        broken = entry_point(GROUP_OF_SLOT["repository"], "broken", BROKEN_VALUE)
        with registered(broken):
            rc, out, _err = _main(["capabilities", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        entry = doc["slots"]["repository"]["registered"][0]
        self.assertEqual(entry["loadable"], False)
        self.assertNotIn("enforcement", entry)

    # ---- error --------------------------------------------------------------

    def test_an_unloadable_registered_entry_point_is_listed_false_not_raised(self):
        broken = entry_point(GROUP_OF_SLOT["cache"], "broken", BROKEN_VALUE)
        with registered(broken):
            rc, out, err = _main(["capabilities", "--json"])
        self.assertEqual(rc, 0, "a broken registration must never change the exit code")
        self.assertEqual(err, "")
        doc = json.loads(out)
        self.assertEqual(doc["slots"]["cache"]["registered"],
                         [{"name": "broken", "entry_point": BROKEN_VALUE,
                           "version": None, "loadable": False}])

    def test_load_failure_in_one_slot_does_not_disturb_the_others(self):
        broken = entry_point(GROUP_OF_SLOT["network"], "broken", BROKEN_VALUE)
        with registered(broken):
            rc, out, _err = _main(["capabilities", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(doc["slots"]["repository"]["registered"], [])
        self.assertEqual(doc["slots"]["token"]["registered"], [])

    # ---- boundary -----------------------------------------------------------

    def test_zero_registered_entry_points_is_an_empty_list_not_an_error(self):
        with registered():
            rc, out, err = _main(["capabilities", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        doc = json.loads(out)
        for slot in CONTRACT_SLOTS:
            self.assertEqual(doc["slots"][slot]["registered"], [],
                             "slot %r should have no registrations" % slot)

    def test_multiple_registrations_including_a_builtin_shadow_are_all_listed(self):
        # A package registering the same name as a built-in (`fake`) is not
        # hidden or deduplicated away (plan D4, BuiltinShadowingTest spirit).
        loadable = entry_point(GROUP_OF_SLOT["exporter"], "custom", DEMO_VALUE)
        shadow = entry_point(GROUP_OF_SLOT["exporter"], "stderr-json", BROKEN_VALUE)
        with registered(loadable, shadow):
            rc, out, _err = _main(["capabilities", "--json"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        registered_names = {e["name"]: e["loadable"]
                            for e in doc["slots"]["exporter"]["registered"]}
        self.assertEqual(registered_names,
                         {"custom": True, "stderr-json": False})
        self.assertIn("stderr-json", doc["slots"]["exporter"]["builtin"])


if __name__ == "__main__":
    unittest.main()
