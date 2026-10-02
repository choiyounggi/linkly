"""`scripts/load_probe.py`의 순수 함수 — 네트워크 없이 검증한다.

issue #180: postgres 백엔드 `lnpl serve`의 지속 부하 상한을 재는 open-loop
부하 생성기다. 이 파일은 측정값을 만드는 계산(백분위, 워밍업 제외, 10초
구간 집계)과 인자 검증만 본다. 기대값은 전부 공식에서 손으로 계산한 것이고
스크립트를 돌려 얻은 값이 아니다.
"""
import argparse
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import load_probe  # noqa: E402


def row(t_start, status, latency_ms, error=""):
    return (t_start, status, latency_ms, error)


class PercentileTest(unittest.TestCase):
    def test_median_of_odd_list_is_the_middle_value(self):
        # k = (5 - 1) * 0.5 = 2 -> 정확히 인덱스 2.
        self.assertEqual(load_probe.percentile([10, 20, 30, 40, 50], 0.5), 30)

    def test_p95_interpolates_between_neighbours(self):
        # k = (5 - 1) * 0.95 = 3.8 -> 40 + (50 - 40) * 0.8 = 48.
        self.assertAlmostEqual(load_probe.percentile([10, 20, 30, 40, 50], 0.95), 48.0)

    def test_median_of_even_list_is_the_midpoint(self):
        # k = (2 - 1) * 0.5 = 0.5 -> 10 + (20 - 10) * 0.5 = 15.
        self.assertAlmostEqual(load_probe.percentile([10, 20], 0.5), 15.0)

    def test_empty_list_has_no_percentile(self):
        self.assertIsNone(load_probe.percentile([], 0.5))

    def test_single_sample_is_every_percentile(self):
        self.assertEqual(load_probe.percentile([7.5], 0.5), 7.5)
        self.assertEqual(load_probe.percentile([7.5], 0.99), 7.5)

    def test_p0_and_p100_are_the_extremes(self):
        self.assertEqual(load_probe.percentile([1, 2, 3], 0.0), 1)
        self.assertEqual(load_probe.percentile([1, 2, 3], 1.0), 3)


class ArgumentValidationTest(unittest.TestCase):
    def test_positive_float_accepts_a_positive_number(self):
        self.assertEqual(load_probe.positive_float("2.5"), 2.5)
        self.assertEqual(load_probe.positive_float("100"), 100.0)

    def test_positive_float_rejects_zero_and_negative(self):
        for text in ("0", "-5", "0.0"):
            with self.subTest(text=text):
                with self.assertRaises(argparse.ArgumentTypeError) as caught:
                    load_probe.positive_float(text)
                self.assertIn("positive", str(caught.exception))

    def test_positive_float_rejects_non_numbers_and_non_finite(self):
        for text in ("abc", "", "nan", "inf"):
            with self.subTest(text=text):
                with self.assertRaises(argparse.ArgumentTypeError):
                    load_probe.positive_float(text)

    def test_url_validator_keeps_a_real_url(self):
        self.assertEqual(load_probe.non_empty_url("http://127.0.0.1:18180/x"),
                         "http://127.0.0.1:18180/x")

    def test_url_validator_rejects_empty_and_blank(self):
        for text in ("", "   "):
            with self.subTest(text=repr(text)):
                with self.assertRaises(argparse.ArgumentTypeError) as caught:
                    load_probe.non_empty_url(text)
                self.assertIn("empty", str(caught.exception))

    def _parse(self, argv):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            args = load_probe.build_parser().parse_args(argv)
        return args, stderr.getvalue()

    def _rejected(self, argv):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught:
                load_probe.build_parser().parse_args(argv)
        return caught.exception.code, stderr.getvalue()

    def test_parser_exits_2_on_invalid_rps(self):
        code, stderr = self._rejected(
            ["--url", "http://x", "--out", "o.csv", "--rps", "0"])
        self.assertEqual(code, 2)
        self.assertIn("--rps", stderr)

    def test_parser_exits_2_on_invalid_seconds_and_warmup(self):
        for flag in ("--seconds", "--warmup"):
            with self.subTest(flag=flag):
                code, stderr = self._rejected(
                    ["--url", "http://x", "--out", "o.csv", flag, "-1"])
                self.assertEqual(code, 2)
                self.assertIn(flag, stderr)

    def test_parser_exits_2_on_empty_url_and_missing_required(self):
        code, stderr = self._rejected(["--url", "", "--out", "o.csv"])
        self.assertEqual(code, 2)
        self.assertIn("--url", stderr)
        code, _ = self._rejected(["--url", "http://x"])
        self.assertEqual(code, 2)

    def test_parser_defaults_and_overrides(self):
        args, _ = self._parse(["--url", "http://x", "--out", "o.csv"])
        self.assertEqual((args.rps, args.seconds, args.warmup, args.method, args.body),
                         (100.0, 60.0, 5.0, "GET", None))
        args, _ = self._parse(["--url", "http://x", "--out", "o.csv", "--rps", "25",
                               "--seconds", "90", "--warmup", "5",
                               "--method", "POST", "--body", "{}"])
        self.assertEqual((args.rps, args.seconds, args.method, args.body),
                         (25.0, 90.0, "POST", "{}"))


class SummarizeTest(unittest.TestCase):
    def test_warmup_rows_are_excluded_and_errors_counted(self):
        rows = [
            row(1.0, 200, 999.0),          # 워밍업 구간 — 전부 제외
            row(5.0, 200, 10.0),           # 경계: t_start == warmup 은 포함
            row(6.0, 200, 20.0),
            row(7.0, 500, 30.0),           # non-2xx
            row(8.0, None, 40.0, "TimeoutError:x"),   # 응답 없음
        ]
        summary = load_probe.summarize(rows, warmup=5.0)
        self.assertEqual(summary["total"], 5)
        self.assertEqual(summary["post_warmup"], 4)
        self.assertEqual(summary["ok"], 2)
        self.assertEqual(summary["errors"], 2)
        self.assertAlmostEqual(summary["error_rate"], 50.0)
        # 지연 백분위는 워밍업 이후 전 요청(에러 포함) 기준: [10, 20, 30, 40].
        # p50: k = 1.5 -> 25. p95: k = 2.85 -> 30 + 10 * 0.85 = 38.5.
        self.assertAlmostEqual(summary["p50"], 25.0)
        self.assertAlmostEqual(summary["p95"], 38.5)
        # p99: k = 2.97 -> 30 + 10 * 0.97 = 39.7.
        self.assertAlmostEqual(summary["p99"], 39.7)

    def test_no_post_warmup_rows_gives_no_rate_and_no_percentiles(self):
        for rows in ([], [row(1.0, 200, 3.0)]):
            with self.subTest(rows=rows):
                summary = load_probe.summarize(rows, warmup=5.0)
                self.assertEqual(summary["post_warmup"], 0)
                self.assertEqual(summary["errors"], 0)
                self.assertIsNone(summary["error_rate"])
                self.assertIsNone(summary["p50"])
                self.assertIsNone(summary["p99"])

    def test_3xx_and_1xx_are_not_ok(self):
        summary = load_probe.summarize(
            [row(5.0, 302, 1.0), row(5.1, 199, 1.0), row(5.2, 299, 1.0)], warmup=5.0)
        self.assertEqual(summary["ok"], 1)
        self.assertEqual(summary["errors"], 2)


class BucketTableTest(unittest.TestCase):
    def test_rows_land_in_ten_second_buckets_counted_from_warmup(self):
        rows = [
            row(5.0, 200, 10.0), row(14.9, 200, 30.0),     # 0-10s
            row(15.0, 200, 100.0),                         # 10-20s (경계는 다음 구간)
            row(25.0, 200, 7.0), row(26.0, 200, 9.0), row(27.0, 200, 2.0),  # 20-30s
        ]
        self.assertEqual(
            load_probe.bucket_table(rows, warmup=5.0, seconds=35.0),
            [(0.0, 20.0, 30.0, 2), (10.0, 100.0, 100.0, 1), (20.0, 6.0, 9.0, 3)])

    def test_single_sample_fills_exactly_one_bucket(self):
        table = load_probe.bucket_table([row(12.0, 200, 4.5)], warmup=5.0, seconds=25.0)
        self.assertEqual(table, [(0.0, 4.5, 4.5, 1), (10.0, None, None, 0)])
        non_empty = [b for b in table if b[3] > 0]
        self.assertEqual(len(non_empty), 1)
        self.assertEqual(non_empty[0][1], non_empty[0][2])

    def test_empty_rows_give_every_bucket_empty(self):
        self.assertEqual(
            load_probe.bucket_table([], warmup=5.0, seconds=25.0),
            [(0.0, None, None, 0), (10.0, None, None, 0)])

    def test_warmup_rows_and_non_2xx_rows_are_left_out(self):
        rows = [
            row(4.999, 200, 500.0),               # 워밍업
            row(6.0, 200, 8.0),
            row(7.0, 503, 900.0),                 # non-2xx
            row(8.0, None, 10000.0, "timeout"),   # 응답 없음
        ]
        self.assertEqual(load_probe.bucket_table(rows, warmup=5.0, seconds=15.0),
                         [(0.0, 8.0, 8.0, 1)])

    def test_last_partial_bucket_is_kept(self):
        # 60초 실행, 워밍업 5초 -> 55초 구간 = 10초 구간 5개 + 5초짜리 1개.
        table = load_probe.bucket_table([row(59.0, 200, 3.0)], warmup=5.0, seconds=60.0)
        self.assertEqual([b[0] for b in table], [0.0, 10.0, 20.0, 30.0, 40.0, 50.0])
        self.assertEqual(table[-1], (50.0, 3.0, 3.0, 1))

    def test_run_no_longer_than_warmup_has_no_buckets(self):
        self.assertEqual(load_probe.bucket_table([row(1.0, 200, 3.0)],
                                                 warmup=5.0, seconds=5.0), [])
        self.assertEqual(load_probe.bucket_table([], warmup=5.0, seconds=3.0), [])

    def test_row_at_or_after_the_end_of_the_run_is_dropped(self):
        rows = [row(14.9, 200, 2.0), row(15.0, 200, 700.0), row(40.0, 200, 900.0)]
        self.assertEqual(load_probe.bucket_table(rows, warmup=5.0, seconds=15.0),
                         [(0.0, 2.0, 2.0, 1)])

    def test_custom_bucket_width(self):
        rows = [row(0.5, 200, 2.0), row(1.5, 200, 4.0), row(1.9, 200, 6.0)]
        self.assertEqual(
            load_probe.bucket_table(rows, warmup=0.5, seconds=2.5, bucket_s=1),
            [(0.0, 2.0, 2.0, 1), (1.0, 5.0, 6.0, 2)])

    def test_format_bucket_line(self):
        self.assertEqual(load_probe.format_bucket((0.0, 1.189, 10.86, 1000), 10),
                         "bucket=0-10s mean=1.19ms max=10.86ms n=1000")
        self.assertEqual(load_probe.format_bucket((10.0, None, None, 0), 10),
                         "bucket=10-20s mean=- max=- n=0")


class OutputTest(unittest.TestCase):
    ROWS = [
        row(1.0, 200, 50.0),
        row(5.0, 200, 10.0),
        row(6.0, 200, 30.0),
        row(16.0, None, 10000.0, "TimeoutError:timed out"),
    ]

    def test_csv_has_a_header_and_one_line_per_request(self):
        out = io.StringIO()
        load_probe.write_csv(self.ROWS, out)
        self.assertEqual(out.getvalue().splitlines(), [
            "t_start,status,latency_ms,error",
            "1.0,200,50.0,",
            "5.0,200,10.0,",
            "6.0,200,30.0,",
            "16.0,,10000.0,TimeoutError:timed out",
        ])

    def test_csv_of_no_requests_is_only_the_header(self):
        out = io.StringIO()
        load_probe.write_csv([], out)
        self.assertEqual(out.getvalue().splitlines(), ["t_start,status,latency_ms,error"])

    def _main(self, rows, argv):
        stdout = io.StringIO()
        with mock.patch.object(load_probe, "run_load", return_value=rows) as run_load:
            with contextlib.redirect_stdout(stdout):
                code = load_probe.main(argv)
        return code, stdout.getvalue().splitlines(), run_load

    def test_main_prints_summary_then_buckets(self):
        code, lines, run_load = self._main(self.ROWS, [
            "--url", "http://127.0.0.1:1/x", "--out", os.devnull, "--rps", "20",
            "--seconds", "25", "--warmup", "5", "--method", "POST", "--body", "{}"])
        self.assertEqual(code, 0)
        run_load.assert_called_once_with("http://127.0.0.1:1/x", 20.0, 25.0, "POST", b"{}")
        # 워밍업 이후 3건: 지연 [10, 30, 10000], 1건 실패.
        # p50 = 30. p95: k = 1.9 -> 30 + 9970 * 0.9 = 9003. p99: k = 1.98 -> 9800.6.
        self.assertEqual(lines, [
            "total=4 post_warmup=3 ok=2 error_or_non2xx=1",
            "p50=30.00ms p95=9003.00ms p99=9800.60ms",
            "error_rate=33.33%",
            "bucket=0-10s mean=20.00ms max=30.00ms n=2",
            "bucket=10-20s mean=- max=- n=0",
        ])

    def test_main_with_no_requests_prints_counts_and_empty_buckets_only(self):
        code, lines, run_load = self._main([], [
            "--url", "http://127.0.0.1:1/x", "--out", os.devnull, "--seconds", "15"])
        self.assertEqual(code, 0)
        run_load.assert_called_once_with("http://127.0.0.1:1/x", 100.0, 15.0, "GET", None)
        self.assertEqual(lines, [
            "total=0 post_warmup=0 ok=0 error_or_non2xx=0",
            "bucket=0-10s mean=- max=- n=0",
        ])


if __name__ == "__main__":
    unittest.main()
