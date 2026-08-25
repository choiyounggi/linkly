"""`tracecontext` — pure W3C Trace Context parsing/generation (issue #107, Task 01).

Written against the plan's D4/D5/D9/D10 decisions
(`.orchestration/plans/t107.md`), not against an implementation detail: every
case is either a spec example, a spec-mandated rejection, or a boundary the
plan calls out explicitly.
"""

import unittest

from lnpl.tracecontext import (format_traceparent, new_span_id, new_trace_id,
                                parse_traceparent)


class ParseTraceparentTests(unittest.TestCase):
    def test_spec_example_parses(self):
        # W3C Trace Context §"Examples of HTTP headers"
        raw = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        parsed = parse_traceparent(raw)
        self.assertEqual(parsed, {
            "version": "00",
            "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
            "parent_id": "00f067aa0ba902b7",
            "flags": "01",
        })

    def test_higher_version_is_adopted_not_rejected(self):
        # D4: a version above 00 is not rejected outright; if the first four
        # fields still parse under the 00 layout, adopt them.
        raw = "01-" + "a" * 32 + "-" + "b" * 16 + "-01"
        parsed = parse_traceparent(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["version"], "01")
        self.assertEqual(parsed["trace_id"], "a" * 32)
        self.assertEqual(parsed["parent_id"], "b" * 16)

    def test_version_ff_is_rejected(self):
        # W3C spec: ff is explicitly invalid.
        raw = "ff-" + "a" * 32 + "-" + "b" * 16 + "-01"
        self.assertIsNone(parse_traceparent(raw))

    def test_all_zero_trace_id_is_rejected(self):
        raw = "00-" + "0" * 32 + "-" + "b" * 16 + "-01"
        self.assertIsNone(parse_traceparent(raw))

    def test_all_zero_parent_id_is_rejected(self):
        raw = "00-" + "a" * 32 + "-" + "0" * 16 + "-01"
        self.assertIsNone(parse_traceparent(raw))

    def test_uppercase_hex_is_rejected(self):
        raw = "00-" + "A" * 32 + "-" + "b" * 16 + "-01"
        self.assertIsNone(parse_traceparent(raw))

    def test_wrong_length_trace_id_31_chars_is_rejected(self):
        raw = "00-" + "a" * 31 + "-" + "b" * 16 + "-01"
        self.assertIsNone(parse_traceparent(raw))

    def test_wrong_length_trace_id_33_chars_is_rejected(self):
        raw = "00-" + "a" * 33 + "-" + "b" * 16 + "-01"
        self.assertIsNone(parse_traceparent(raw))

    def test_higher_version_with_extra_trailing_fields_still_parses(self):
        # D4 / spec note: a version above 00 may carry additional
        # vendor-specific fields after the first four. We only read the
        # first four; trailing fields are ignored, not a rejection reason.
        raw = "02-" + "a" * 32 + "-" + "b" * 16 + "-01-extravendorfield"
        parsed = parse_traceparent(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["version"], "02")
        self.assertEqual(parsed["trace_id"], "a" * 32)

    def test_too_few_fields_is_rejected(self):
        raw = "00-" + "a" * 32 + "-" + "b" * 16  # only 3 fields
        self.assertIsNone(parse_traceparent(raw))

    def test_none_is_rejected_without_raising(self):
        self.assertIsNone(parse_traceparent(None))

    def test_empty_string_is_rejected_without_raising(self):
        self.assertIsNone(parse_traceparent(""))

    def test_bytes_is_rejected_without_raising(self):
        self.assertIsNone(parse_traceparent(b"00-" + b"a" * 32 + b"-" + b"b" * 16 + b"-01"))

    def test_number_is_rejected_without_raising(self):
        self.assertIsNone(parse_traceparent(12345))


class FormatTraceparentTests(unittest.TestCase):
    def test_roundtrips_through_parse(self):
        trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        span_id = "00f067aa0ba902b7"
        formatted = format_traceparent(trace_id, span_id, "01")
        parsed = parse_traceparent(formatted)
        self.assertEqual(parsed["trace_id"], trace_id)
        self.assertEqual(parsed["parent_id"], span_id)
        self.assertEqual(parsed["flags"], "01")

    def test_always_emits_version_00(self):
        formatted = format_traceparent("a" * 32, "b" * 16, "01")
        self.assertTrue(formatted.startswith("00-"))

    def test_default_flags_is_01(self):
        formatted = format_traceparent("a" * 32, "b" * 16)
        self.assertEqual(formatted, "00-" + "a" * 32 + "-" + "b" * 16 + "-01")

    def test_invalid_trace_id_raises_value_error(self):
        with self.assertRaises(ValueError):
            format_traceparent("not-hex", "b" * 16, "01")

    def test_wrong_length_span_id_raises_value_error(self):
        with self.assertRaises(ValueError):
            format_traceparent("a" * 32, "b" * 15, "01")


class IdGenerationTests(unittest.TestCase):
    def test_new_trace_id_shape(self):
        trace_id = new_trace_id()
        self.assertEqual(len(trace_id), 32)
        self.assertRegex(trace_id, r"^[0-9a-f]{32}$")

    def test_new_span_id_shape(self):
        span_id = new_span_id()
        self.assertEqual(len(span_id), 16)
        self.assertRegex(span_id, r"^[0-9a-f]{16}$")

    def test_new_trace_id_is_not_constant(self):
        self.assertNotEqual(new_trace_id(), new_trace_id())

    def test_new_span_id_is_not_constant(self):
        self.assertNotEqual(new_span_id(), new_span_id())


if __name__ == "__main__":
    unittest.main()
