"""`lnpl.money` — RFC-0044 §Reference-level Specification 1·2·4·5, issue #145.

Money 평가 채널의 배선 없는(caller 없는) 순수 모듈. RFC-0045(avg/min/max)가
유일한 예정 소비자이고, 이 파일은 그 계약(minor-unit 코덱, exponent 조회,
half-to-even `avg_round`, 같은-통화 순서·덧셈)만 고정한다.
"""

import unittest
from decimal import Decimal

from lnpl.money import (
    CURRENCY_EXPONENT,
    MoneyCurrencyMismatchError,
    MoneyEncodePrecisionError,
    add,
    avg_round,
    compare,
    encode_money,
    exponent,
)


class ExponentBucketCountTest(unittest.TestCase):

    # (정상) RFC-0044 §2의 두 예외 버킷이 정확히 16종·7종이라는 닫힌 계약을
    # 직접 센다 — 구현이 표를 잘못 옮겨 적었으면 여기서 즉시 드러난다.
    def test_exponent_zero_bucket_has_exactly_sixteen_currencies(self):
        zero_bucket = [c for c, exp in CURRENCY_EXPONENT.items() if exp == 0]

        self.assertEqual(16, len(zero_bucket))

    def test_exponent_three_bucket_has_exactly_seven_currencies(self):
        three_bucket = [c for c, exp in CURRENCY_EXPONENT.items() if exp == 3]

        self.assertEqual(7, len(three_bucket))

    # (경계) 두 예외 버킷 밖의 표본 통화는 기본값 2를 받는다.
    def test_a_currency_outside_both_exception_buckets_defaults_to_two(self):
        self.assertEqual(2, exponent("USD"))
        self.assertEqual(2, exponent("EUR"))


class ExponentLookupTest(unittest.TestCase):

    # (에러) 형태는 alpha-3이지만 활성 ISO 4217 코드 집합에 없는 문자열은
    # 거부된다 — D4b의 핵심 함정: 표에 없다고 2로 어림짐작하지 않는다.
    def test_a_well_formed_but_inactive_code_is_rejected(self):
        with self.assertRaises(MoneyEncodePrecisionError) as ctx:
            exponent("XYZ")

        self.assertEqual("money-encode-precision", ctx.exception.code)

    # (에러) 폐기된 통화 코드(구 짐바브웨 달러, ZWG로 대체됨)도 같은 이유로
    # 거부된다 — 형태 검사만으로는 못 잡는 사례.
    def test_a_deprecated_currency_code_is_rejected(self):
        with self.assertRaises(MoneyEncodePrecisionError):
            exponent("ZWL")

    # (에러) alpha-3 형태 자체가 틀리면 활성 코드 집합을 보기 전에 거부된다.
    def test_wrong_length_code_is_rejected(self):
        with self.assertRaises(MoneyEncodePrecisionError):
            exponent("US")

        with self.assertRaises(MoneyEncodePrecisionError):
            exponent("USDD")

    def test_lowercase_code_is_rejected(self):
        with self.assertRaises(MoneyEncodePrecisionError):
            exponent("usd")

    def test_non_string_code_is_rejected(self):
        with self.assertRaises(MoneyEncodePrecisionError):
            exponent(123)


class EncodeMoneyRoundTripTest(unittest.TestCase):

    # (정상) exponent 0 버킷(JPY) — 소수점 없이 정수 그대로 minor unit.
    def test_exponent_zero_bucket_round_trips(self):
        minor, currency = encode_money("1500", "JPY")

        self.assertEqual(1500, minor)
        self.assertEqual("JPY", currency)
        self.assertEqual(Decimal("1500"), Decimal(minor).scaleb(-exponent("JPY")))

    # (정상) exponent 2 버킷(USD, 기본값) — 소수 두 자리.
    def test_exponent_two_bucket_round_trips(self):
        minor, currency = encode_money("19.99", "USD")

        self.assertEqual(1999, minor)
        self.assertEqual("USD", currency)
        self.assertEqual(Decimal("19.99"), Decimal(minor).scaleb(-exponent("USD")))

    # (정상) exponent 3 버킷(BHD) — 소수 세 자리.
    def test_exponent_three_bucket_round_trips(self):
        minor, currency = encode_money("12.345", "BHD")

        self.assertEqual(12345, minor)
        self.assertEqual("BHD", currency)
        self.assertEqual(Decimal("12.345"), Decimal(minor).scaleb(-exponent("BHD")))

    # (경계) 0 — 통화의 exponent에 맞는 소수 자리로 쓴 0은 유효하다.
    def test_zero_amount_matching_the_currency_exponent(self):
        self.assertEqual((0, "USD"), encode_money("0.00", "USD"))
        self.assertEqual((0, "JPY"), encode_money("0", "JPY"))

    # (경계) 음수 금액.
    def test_negative_amount(self):
        self.assertEqual((-500, "USD"), encode_money("-5.00", "USD"))

    # (경계) i64 경계 근처 — 정확히 INT64_MAX인 값은 통과, 하나 넘으면 거부.
    def test_i64_boundary(self):
        self.assertEqual(
            (9223372036854775807, "JPY"), encode_money("9223372036854775807", "JPY"))

        with self.assertRaises(MoneyEncodePrecisionError):
            encode_money("9223372036854775808", "JPY")

    # (에러) 소수부 자릿수가 통화의 exponent와 다르면 반올림하지 않고 거부한다
    # — RFC-0044 §1의 핵심 계약.
    def test_decimal_places_mismatching_the_exponent_is_rejected(self):
        with self.assertRaises(MoneyEncodePrecisionError) as ctx:
            encode_money("5.5", "USD")

        self.assertEqual("money-encode-precision", ctx.exception.code)

        with self.assertRaises(MoneyEncodePrecisionError):
            # 0(JPY 필요)인데 소수점이 있다.
            encode_money("5.0", "JPY")

        with self.assertRaises(MoneyEncodePrecisionError):
            # 0(USD 필요 2자리)인데 소수점 자체가 없다.
            encode_money("0", "USD")

    # (에러) 활성이 아닌 통화 코드로는 인코딩할 수 없다.
    def test_encoding_with_an_inactive_currency_is_rejected(self):
        with self.assertRaises(MoneyEncodePrecisionError):
            encode_money("10.00", "XYZ")

    # (에러) 형태 자체가 틀린 통화 코드.
    def test_encoding_with_a_malformed_currency_is_rejected(self):
        with self.assertRaises(MoneyEncodePrecisionError):
            encode_money("10.00", "US")


class AvgRoundHalfToEvenTest(unittest.TestCase):

    # (정상) 나누어떨어지는 경우 — 반올림 자체가 필요 없다
    # (RFC-0045 §Examples "1.00USD + 2.00USD"의 실측치).
    def test_exact_division_needs_no_rounding(self):
        self.assertEqual(150, avg_round(300, 2))

    # (정책 고정 — 짝수 방향) 101/2 = 50.5 -> 가장 가까운 짝수는 50(내림쪽).
    # `ROUND_HALF_UP`으로 바꾸면 51이 나와 이 단언이 깨진다.
    def test_half_to_even_rounds_down_to_an_even_quotient(self):
        self.assertEqual(50, avg_round(101, 2))

    # (정책 고정 — 홀수 방향) 103/2 = 51.5 -> 가장 가까운 짝수는 52(올림쪽).
    # 절삭(내림)으로 바꾸면 51이 나와 이 단언이 깨진다.
    def test_half_to_even_rounds_up_to_an_even_quotient(self):
        self.assertEqual(52, avg_round(103, 2))

    # (경계) count == 0 — 빈 RowSet 경계. 정의역 밖이므로 ValueError.
    # `RunError` 매핑은 호출자(RFC-0045 §3)의 몫이라 여기서는 만들지 않는다.
    def test_zero_count_is_out_of_domain(self):
        with self.assertRaises(ValueError):
            avg_round(100, 0)

    # (경계) 음수 count도 정의역 밖이다.
    def test_negative_count_is_out_of_domain(self):
        with self.assertRaises(ValueError):
            avg_round(100, -1)


class SameCurrencyCompareAndAddTest(unittest.TestCase):

    # (정상) 같은 통화의 순서 비교.
    def test_compare_orders_same_currency_values(self):
        self.assertLess(compare((100, "USD"), (200, "USD")), 0)
        self.assertGreater(compare((200, "USD"), (100, "USD")), 0)
        self.assertEqual(0, compare((100, "USD"), (100, "USD")))

    # (정상) 같은 통화의 덧셈.
    def test_add_sums_same_currency_values(self):
        self.assertEqual((300, "USD"), add((100, "USD"), (200, "USD")))

    # (에러) 통화가 다른 두 값을 비교하면 실패한다.
    def test_comparing_different_currencies_raises(self):
        with self.assertRaises(MoneyCurrencyMismatchError) as ctx:
            compare((100, "USD"), (100, "EUR"))

        self.assertEqual("money-currency-mismatch", ctx.exception.code)

    # (에러) 통화가 다른 두 값을 더하면 실패한다.
    def test_adding_different_currencies_raises(self):
        with self.assertRaises(MoneyCurrencyMismatchError) as ctx:
            add((100, "USD"), (100, "EUR"))

        self.assertEqual("money-currency-mismatch", ctx.exception.code)


if __name__ == "__main__":
    unittest.main()
