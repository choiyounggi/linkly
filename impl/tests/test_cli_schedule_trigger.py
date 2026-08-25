"""Issue #81: `lnpl trigger` (external-scheduler entry point, no `serve`
socket needed) and `lnpl schedules --format crontab|systemd` (generated
snippets from `x-lnpl-schedules`).

Normal: `trigger` runs the schedule's linked workflow and exits 0;
`schedules` renders a crontab line calling `lnpl trigger`. Error:
`--schedule` naming an id the module does not declare a schedule event for
is rc 2 (operator error, mirrors `--workflow`'s `WorkflowSelectionError`); a
run whose workflow fails is rc != 0. Boundary: multiple source files (t77
`load_sources`) reach `trigger` the same way `run`'s existing tests already
prove for other subcommands.
"""

import contextlib
import io
import json
import os
import shutil
import unittest

from lnpl import cli

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKDIR = os.path.join(REPO, ".claude", "tmp", "cli-schedule-trigger")

NORMAL_SRC = """service Rollup

entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC

workflow GetReport
    read report
"""

# `validate input` against an entity with a required field and an empty
# payload -> M7-equivalent runtime failure (status != "completed").
FAILING_SRC = """service Rollup

entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC

workflow GetReport
    validate input
    read report
"""

MULTI_ENTITY = """entity Report
    field
        id UUID
"""

MULTI_REST = """service Rollup

event DailyRollup on schedule daily at 00:00 UTC

workflow GetReport
    read report
"""


def run_cli(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cli.main(argv)
    return rc, buf.getvalue()


def _write(name, text):
    os.makedirs(WORKDIR, exist_ok=True)
    path = os.path.join(WORKDIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class ScheduleTriggerTestCase(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(WORKDIR, ignore_errors=True)


class TriggerNormalTest(ScheduleTriggerTestCase):
    def test_normal_trigger_runs_and_exits_zero(self):
        src = _write("normal.lnpl", NORMAL_SRC)

        rc, out = run_cli(["trigger", src, "--schedule", "event.daily.rollup"])

        self.assertEqual(0, rc, out)


class TriggerErrorTest(ScheduleTriggerTestCase):
    def test_error_unknown_schedule_id_is_rc_2(self):
        src = _write("normal.lnpl", NORMAL_SRC)

        rc, out = run_cli(["trigger", src, "--schedule", "event.no-such-event"])

        self.assertEqual(2, rc, out)
        self.assertIn("event.no-such-event", out)

    def test_error_failed_workflow_is_rc_nonzero(self):
        src = _write("failing.lnpl", FAILING_SRC)

        rc, out = run_cli(["trigger", src, "--schedule", "event.daily.rollup",
                           "--payload", _write("empty.json", "{}")])

        self.assertNotEqual(0, rc, out)


class TriggerBoundaryTest(ScheduleTriggerTestCase):
    def test_boundary_multi_file_source_resolves_the_same_way(self):
        a = _write("01_entity.lnpl", MULTI_ENTITY)
        b = _write("02_rest.lnpl", MULTI_REST)

        rc, out = run_cli(["trigger", a, b, "--schedule", "event.daily.rollup"])

        self.assertEqual(0, rc, out)

    def test_boundary_no_schedule_event_declared_is_rc_1(self):
        src = _write("no_schedule.lnpl", MULTI_ENTITY + """
service Rollup

workflow GetReport
    read report
""")

        rc, out = run_cli(["trigger", src, "--schedule", "event.daily.rollup"])

        self.assertEqual(1, rc, out)


class SchedulesNormalTest(ScheduleTriggerTestCase):
    def test_normal_crontab_format_names_the_trigger_command(self):
        src = _write("normal.lnpl", NORMAL_SRC)

        rc, out = run_cli(["schedules", src, "--format", "crontab"])

        self.assertEqual(0, rc, out)
        self.assertIn("0 0 * * *", out)
        self.assertIn("lnpl trigger", out)
        self.assertIn("--schedule event.daily.rollup", out)
        self.assertIn("generated", out.lower())

    def test_normal_systemd_format_names_the_trigger_command(self):
        src = _write("normal.lnpl", NORMAL_SRC)

        rc, out = run_cli(["schedules", src, "--format", "systemd"])

        self.assertEqual(0, rc, out)
        self.assertIn("OnCalendar=", out)
        self.assertIn("lnpl trigger", out)
        self.assertIn("--schedule event.daily.rollup", out)


class SchedulesBoundaryTest(ScheduleTriggerTestCase):
    def test_boundary_no_schedule_declared_is_rc_1(self):
        src = _write("no_schedule.lnpl", MULTI_ENTITY + """
service Rollup

workflow GetReport
    read report
""")

        rc, out = run_cli(["schedules", src, "--format", "crontab"])

        self.assertEqual(1, rc, out)


if __name__ == "__main__":
    unittest.main()
