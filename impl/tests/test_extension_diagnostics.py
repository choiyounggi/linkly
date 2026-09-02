"""RFC-0042 (issue #138): extensions register diagnostics under
`lnpl.diagnostics`, a namespace disjoint from the core's closed `CODES` —
`<prefix>/<code>`, prefix = the entry-point's own name, one prefix one
owner, `info`/`warning` severity only, `--strict` non-participation, and
`check` sees the compiled IR document only (never source text).

Entry-points are constructed in-process against `diagnostics_ext_fixture.py`
and swapped in via `importlib_metadata.entry_points`, mirroring
`test_driver_spi.py`/`test_token_spi.py` — this repo is the only consumer of
its own `lnpl.diagnostics` group, so there is nothing to install.
"""

import contextlib
import io
import json
import os
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import cli
from lnpl import diagnostics as diagnostics_module
from lnpl.diagnostics import ExtensionDiagnosticsError, severity_of

from tests import diagnostics_ext_fixture as fixture

GROUP = diagnostics_module.DIAGNOSTICS_ENTRY_POINT_GROUP

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGIN = os.path.join(REPO, "examples", "login.lnpl")

# A module that compiles with zero core diagnostics, so any diagnostic in the
# output is unambiguously the extension's (verified by hand: `lnpl compile`
# on this source emits an empty diagnostics array, same as
# test_cli_compile_json.py's `CLEAN_SRC`, which this mirrors).
CLEAN_SRC = """
capability postgres
entity Payment
    field
        id UUID
        cardNumber Password
        amountCents Integer
service PaymentService
    policy
        retry 0
workflow Approval
    validate payment
    find payment
    when payment.amountCents <= 1000000
    update payment
"""


def entry_point(name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=GROUP)


def registered(*entry_points):
    """Patch `diagnostics_module.importlib_metadata.entry_points` — the only
    external call `load_extensions` makes — to return exactly
    `entry_points`, regardless of what is actually installed."""
    return mock.patch.object(
        diagnostics_module.importlib_metadata, "entry_points",
        lambda **_kwargs: list(entry_points))


KAFKA_EP = entry_point("kafka", "tests.diagnostics_ext_fixture:register_kafka")


def _main(argv):
    """Drive `cli.main(argv)` with stdout/stderr captured separately."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class ExtensionDiagnosticAppearsInCompileTest(unittest.TestCase):
    """Normal: a registered extension's diagnostic reaches `compile`'s
    stderr prose, `<prefix>/<code>` normalized, registered severity."""

    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "ext-diag")
        os.makedirs(self.workdir, exist_ok=True)
        fixture.CALLS.clear()

    def _write(self, name, text):
        path = os.path.join(self.workdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_appears_prefixed_with_registered_severity_on_stderr(self):
        src = self._write("clean1.lnpl", CLEAN_SRC)
        with registered(KAFKA_EP):
            rc, out, err = _main(["compile", src])

        self.assertEqual(rc, 0)
        self.assertIn("info: kafka/at-least-once", err)
        self.assertIn("1 info, 0 warning(s), 0 error(s)", err)

    def test_appears_in_json_diagnostics_array_with_all_seven_keys(self):
        src = self._write("clean2.lnpl", CLEAN_SRC)
        with registered(KAFKA_EP):
            rc, out, err = _main(["compile", src, "--json"])

        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(len(doc["diagnostics"]), 1)
        record = doc["diagnostics"][0]
        self.assertEqual(record["code"], "kafka/at-least-once")
        self.assertEqual(record["severity"], "info")
        # issue #165: "hint" is present (None here — the kafka fixture
        # registers no per-code hint) rather than omitted, same
        # non-omission rule as the other optional keys.
        self.assertIsNone(record["hint"])
        self.assertEqual(set(record.keys()),
                         {"code", "severity", "where", "subject", "message",
                          "line", "hint"})

    def test_check_receives_only_the_compiled_document_and_empty_config(self):
        src = self._write("clean3.lnpl", CLEAN_SRC)
        with registered(KAFKA_EP):
            rc, out, err = _main(["compile", src, "--json"])

        self.assertEqual(rc, 0)
        self.assertEqual(len(fixture.CALLS), 1)
        document, config = fixture.CALLS[0]
        self.assertEqual(config, {})
        self.assertIsInstance(document, dict)
        self.assertEqual(set(document.keys()),
                         {"lir_version", "module", "nodes", "provenance"})
        doc = json.loads(out)
        self.assertEqual(document["module"], doc["module"])
        self.assertEqual(document["nodes"], doc["nodes"])

    def test_severity_of_resolves_both_bare_and_prefixed_codes(self):
        with registered(KAFKA_EP):
            self.assertEqual(severity_of("kafka/at-least-once"), "info")
        self.assertEqual(severity_of("unknown-verb"), "warning")


class LoadTimeValidationTest(unittest.TestCase):
    """Error: every RFC-0042 load-time rejection raises
    `ExtensionDiagnosticsError` with a message naming what was received, the
    rule it broke, and what else is already registered."""

    def test_regex_violation_is_rejected(self):
        bad = entry_point("Kafka", "tests.diagnostics_ext_fixture:register_kafka")
        with registered(bad):
            with self.assertRaises(ExtensionDiagnosticsError) as caught:
                diagnostics_module.load_extensions()

        message = str(caught.exception)
        self.assertIn("Kafka", message)
        self.assertIn(diagnostics_module._EXTENSION_PREFIX_RE.pattern, message)

    def test_reserved_prefix_lnpl_is_rejected(self):
        bad = entry_point("lnpl", "tests.diagnostics_ext_fixture:register_kafka")
        with registered(bad):
            with self.assertRaises(ExtensionDiagnosticsError) as caught:
                diagnostics_module.load_extensions()

        message = str(caught.exception)
        self.assertIn("lnpl", message)
        self.assertIn("reserved", message)

    def test_reserved_prefix_core_is_rejected(self):
        bad = entry_point("core", "tests.diagnostics_ext_fixture:register_kafka")
        with registered(bad):
            with self.assertRaises(ExtensionDiagnosticsError) as caught:
                diagnostics_module.load_extensions()

        message = str(caught.exception)
        self.assertIn("core", message)
        self.assertIn("reserved", message)

    def test_duplicate_prefix_is_rejected(self):
        second = entry_point("kafka", "tests.diagnostics_ext_fixture:register_empty")
        with registered(KAFKA_EP, second):
            with self.assertRaises(ExtensionDiagnosticsError) as caught:
                diagnostics_module.load_extensions()

        message = str(caught.exception)
        self.assertIn("kafka", message)
        self.assertIn("one prefix, one owner", message)
        self.assertIn("kafka", message.split("registered so far:")[-1])

    def test_error_severity_declaration_is_rejected(self):
        bad = entry_point("kafka",
                          "tests.diagnostics_ext_fixture:register_error_severity")
        with registered(bad):
            with self.assertRaises(ExtensionDiagnosticsError) as caught:
                diagnostics_module.load_extensions()

        message = str(caught.exception)
        self.assertIn("kafka/boom", message)
        self.assertIn("'error'", message)
        self.assertIn("'info' or 'warning'", message)

    def test_reserved_enforcement_code_bare_axis_name_is_rejected(self):
        """RFC-0043 §검사 주체: the reserved pattern is static — it rejects
        regardless of whether any driver by this entry-point name actually
        reports `delivery` this run."""
        bad = entry_point("kafka",
                          "tests.diagnostics_ext_fixture:register_reserved_bare_delivery")
        with registered(bad):
            with self.assertRaises(ExtensionDiagnosticsError) as caught:
                diagnostics_module.load_extensions()

        message = str(caught.exception)
        self.assertIn("kafka/delivery", message)
        self.assertIn("reserved enforcement-code pattern", message)

    def test_reserved_enforcement_code_suffixed_is_rejected(self):
        bad = entry_point("kafka",
                          "tests.diagnostics_ext_fixture:register_reserved_delivery_suffix")
        with registered(bad):
            with self.assertRaises(ExtensionDiagnosticsError) as caught:
                diagnostics_module.load_extensions()

        message = str(caught.exception)
        self.assertIn("kafka/delivery-custom-value", message)
        self.assertIn("reserved enforcement-code pattern", message)

    def test_existing_repo_corpus_code_is_not_caught_by_the_reserved_pattern(self):
        """Regression guard for the corpus sweep plan T2 required before
        adding this rule: `at-least-once` (this repo's only real
        `lnpl.diagnostics` fixture code, used throughout this file) has a
        different prefix shape and must keep loading — the reserved pattern
        must not be so broad it catches the RFC-0042 fixture corpus."""
        with registered(KAFKA_EP):
            registry = diagnostics_module.load_extensions()

        self.assertIn("at-least-once", registry["kafka"]["codes"])

    def test_load_time_rejection_surfaces_as_rc_2_through_compile(self):
        with mock.patch("lnpl.diagnostics.load_extensions",
                        side_effect=ExtensionDiagnosticsError("boom")):
            rc, out, err = _main(["compile", LOGIN])

        self.assertEqual(rc, 2)
        self.assertIn("error: boom", err)
        self.assertEqual(out, "")

    def test_load_time_rejection_surfaces_as_rc_2_through_compile_json(self):
        # `--json` is its own try/except around `extension_diagnostic_records`
        # (distinct from the non-json path above) — still emits the null
        # envelope on stdout so a --json caller never has to branch on
        # "did anything print" (mirrors the LexError/ParseError/LowerError
        # branch's existing contract).
        with mock.patch("lnpl.diagnostics.load_extensions",
                        side_effect=ExtensionDiagnosticsError("boom")):
            rc, out, err = _main(["compile", LOGIN, "--json"])

        self.assertEqual(rc, 2)
        self.assertIn("error: boom", err)
        doc = json.loads(out)
        self.assertEqual(doc, {"lir_version": None, "module": None,
                              "nodes": None, "diagnostics": []})


class StrictNonParticipationTest(unittest.TestCase):
    """Boundary: `--strict` gates on core diagnostics only — an extension's
    diagnostic, however high its severity, never moves the exit code."""

    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "ext-diag")
        os.makedirs(self.workdir, exist_ok=True)

    def _write(self, name, text):
        path = os.path.join(self.workdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_strict_does_not_gate_on_extension_severity(self):
        # CLEAN_SRC has zero core diagnostics; kafka's is `info`. `--strict`
        # (bare) gates at the lowest rung, `info` — if the extension
        # diagnostic participated, rc would be 2.
        src = self._write("strict1.lnpl", CLEAN_SRC)
        with registered(KAFKA_EP):
            rc, out, err = _main(["compile", src, "--strict"])

        self.assertEqual(rc, 0)
        self.assertIn("info: kafka/at-least-once", err)

    def test_strict_still_gates_on_core_severity_with_extension_present(self):
        # LOGIN carries real core warnings (test_cli_compile_json.py).
        # `--strict=warning` must still fail rc 2 — the extension's presence
        # changes nothing about the core gate either way.
        with registered(KAFKA_EP):
            rc_with, _, _ = _main(["compile", LOGIN, "--strict=warning"])
        rc_without, _, _ = _main(["compile", LOGIN, "--strict=warning"])

        self.assertEqual(rc_with, 2)
        self.assertEqual(rc_with, rc_without)

    def test_strict_does_not_gate_on_extension_severity_under_json(self):
        src = self._write("strict2.lnpl", CLEAN_SRC)
        with registered(KAFKA_EP):
            rc, out, err = _main(["compile", src, "--strict", "--json"])

        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(doc["diagnostics"][0]["code"], "kafka/at-least-once")


class UnregisteredCheckCodeTest(unittest.TestCase):
    """Boundary: a `check` diagnostic whose code its own extension never
    registered is dropped and warned about, one line — the rest of that same
    extension's diagnostics still come through (D6: filter, not exception,
    and not a whole-extension kill)."""

    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "ext-diag")
        os.makedirs(self.workdir, exist_ok=True)

    def _write(self, name, text):
        path = os.path.join(self.workdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_unregistered_code_is_dropped_with_one_warning_and_sibling_survives(self):
        src = self._write("partial.lnpl", CLEAN_SRC)
        partial = entry_point(
            "partial", "tests.diagnostics_ext_fixture:register_partial_unknown_code")
        with registered(partial):
            rc, out, err = _main(["compile", src, "--json"])

        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(len(doc["diagnostics"]), 1)
        self.assertEqual(doc["diagnostics"][0]["code"], "partial/known")
        self.assertEqual(
            err.count("did not register — dropping"), 1)
        self.assertIn("'partial'", err)
        self.assertIn("'unknown'", err)


class EmptyRegistrationTest(unittest.TestCase):
    """Boundary: an extension may register zero codes and emit nothing —
    loads and compiles cleanly, no crash."""

    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "ext-diag")
        os.makedirs(self.workdir, exist_ok=True)

    def _write(self, name, text):
        path = os.path.join(self.workdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def test_empty_codes_and_empty_check_result_compiles_cleanly(self):
        src = self._write("empty.lnpl", CLEAN_SRC)
        empty = entry_point("empty", "tests.diagnostics_ext_fixture:register_empty")
        with registered(empty):
            rc, out, err = _main(["compile", src, "--json"])

        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(doc["diagnostics"], [])
        self.assertEqual(err, "")
