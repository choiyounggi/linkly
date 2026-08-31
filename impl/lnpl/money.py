"""Money 평가 채널 — minor-unit 코덱, ISO 4217 exponent, half-to-even 나눗셈,
같은-통화 순서·덧셈. RFC-0044 §Reference-level Specification 1·2·4·5 SSOT.

RFC-0016 §2가 DateTime에 세운 패턴을 그대로 따른다: 선언·저장·와이어 표면
(`{"amount": <decimal-string>, "currency": <alpha-3>}`, `types.py`)은 이 모듈이
손대지 않는 정본이고, 이 모듈이 여는 것은 **평가 채널**뿐이다 — Money 값을
minor-unit 부호 있는 64비트 정수 하나로 인코딩해야만 순서 비교·덧셈·평균이
계산 가능해진다.

이 모듈은 어떤 것도 부르지 않고, 어떤 것에서도 불리지 않는다(배선 없음) —
`lower.py`/`interp.py`/`condition.py`/`spec.py`를 import하지 않으며, 그것들도
아직 이 모듈을 import하지 않는다. RFC-0045(avg/min/max)가 유일한 예정 소비자다.
"""

import re
from decimal import Decimal, ROUND_HALF_EVEN

INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1

_ALPHA3_RE = re.compile(r"^[A-Z]{3}$")


class MoneyError(Exception):
    """이 모듈 고유의 예외 base. `interp.RunError`가 아니다 — 이 모듈은
    `interp.py`를 import하지 않는다(배선 없음). `code`는 RFC-0044가 정한
    진단 코드 문자열이고, 호출자(RFC-0045의 avg/min/max/sum)가 이 값을 그대로
    자신의 `RunError`로 옮긴다.
    """
    code = None

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class MoneyEncodePrecisionError(MoneyError):
    """RFC-0044 §1 `money-encode-precision` — 단일 값의 인코딩이 실패했다:
    소수부 자릿수가 통화의 exponent와 어긋나거나, 통화 코드 자체가 유효하지
    않거나(형태 오류·비활성), 값이 64비트 minor-unit 도메인을 벗어난다."""
    code = "money-encode-precision"


class MoneyCurrencyMismatchError(MoneyError):
    """RFC-0044 §5 `money-currency-mismatch` — 이미 인코딩된 두 Money 값을
    순서 비교하거나 더하려 했는데 통화 코드가 다르다."""
    code = "money-currency-mismatch"


# RFC-0044 §2 — 닫힌 두 예외 버킷. 그 밖의 활성 코드는 전부 exponent 2(기본).
# 이 두 목록 자체가 정본이다: additive하게만(신규 통화가 이 두 버킷 중 하나에
# 들어갈 때만) 갱신한다 — 임의로 2를 다른 값으로 바꾸지 않는다.
CURRENCY_EXPONENT = {
    # exponent 0 — 소수 자릿수 없음 (16종)
    "BIF": 0, "CLP": 0, "DJF": 0, "GNF": 0, "ISK": 0, "JPY": 0, "KMF": 0,
    "KRW": 0, "PYG": 0, "RWF": 0, "UGX": 0, "VND": 0, "VUV": 0, "XAF": 0,
    "XOF": 0, "XPF": 0,
    # exponent 3 — 3자리 소수 (7종)
    "BHD": 3, "IQD": 3, "JOD": 3, "KWD": 3, "LYD": 3, "OMR": 3, "TND": 3,
}

# 활성 ISO 4217 alpha-3 코드 집합의 스냅샷 — CURRENCY_EXPONENT에 없는 코드가
# "형태만 맞으면 기본값 2로 어림짐작"이 아니라 "이 집합에 실제로 속하는지"로
# 판정되게 하는 두 번째 단계(RFC-0044 §2: "형태가 유효해도 활성 통화 표에
# 없으면 exponent 조회가 실패한다"). 표에 없는 문자열(가상 통화, 폐기된 코드,
# 오타)은 형태가 맞아도 여기서 거부된다.
#
# 출처: https://en.wikipedia.org/wiki/ISO_4217 "Active codes" 표(2026-01-01
# 기준, `mcp__brave-search__brave_web_search` + WebFetch로 2026-08-31 조회).
_ACTIVE_CURRENCY_CODES = frozenset({
    "AED", "AFN", "ALL", "AMD", "AOA", "ARS", "AUD", "AWG", "AZN", "BAM",
    "BBD", "BDT", "BHD", "BIF", "BMD", "BND", "BOB", "BOV", "BRL", "BSD",
    "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHE", "CHF", "CHW", "CLF",
    "CLP", "CNY", "COP", "COU", "CRC", "CUP", "CVE", "CZK", "DJF", "DKK",
    "DOP", "DZD", "EGP", "ERN", "ETB", "EUR", "FJD", "FKP", "GBP", "GEL",
    "GHS", "GIP", "GMD", "GNF", "GTQ", "GYD", "HKD", "HNL", "HTG", "HUF",
    "IDR", "ILS", "INR", "IQD", "IRR", "ISK", "JMD", "JOD", "JPY", "KES",
    "KGS", "KHR", "KMF", "KPW", "KRW", "KWD", "KYD", "KZT", "LAK", "LBP",
    "LKR", "LRD", "LSL", "LYD", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT",
    "MOP", "MRU", "MUR", "MVR", "MWK", "MXN", "MXV", "MYR", "MZN", "NAD",
    "NGN", "NIO", "NOK", "NPR", "NZD", "OMR", "PAB", "PEN", "PGK", "PHP",
    "PKR", "PLN", "PYG", "QAR", "RON", "RSD", "RUB", "RWF", "SAR", "SBD",
    "SCR", "SDG", "SEK", "SGD", "SHP", "SLE", "SOS", "SRD", "SSP", "STN",
    "SVC", "SYP", "SZL", "THB", "TJS", "TMT", "TND", "TOP", "TRY", "TTD",
    "TWD", "TZS", "UAH", "UGX", "USD", "USN", "UYI", "UYU", "UYW", "UZS",
    "VED", "VES", "VND", "VUV", "XAF", "XAG", "XAU", "XBA", "XBB", "XBC",
    "XBD", "XCD", "XDR", "XOF", "XPD", "XPF", "XPT", "XSU", "XTS", "XUA",
    "XXX", "YER", "ZAR", "ZMW", "ZWG",
})


def exponent(currency):
    """ISO 4217 alpha-3 코드 -> 소수 자릿수. RFC-0044 §2 SSOT.

    두 단계 조회: (1) alpha-3 형태 검사, (2) 활성 코드 집합 소속 검사.
    형태만 맞는 미지의 코드(예: `XYZ`)는 형태 검사를 통과해도 2단계에서
    거부된다 — "표에 없으면 2로 어림짐작"하지 않는다(RFC-0044 §2).
    """
    if not isinstance(currency, str) or not _ALPHA3_RE.match(currency):
        raise MoneyEncodePrecisionError(
            "%r is not a valid ISO 4217 alpha-3 currency code" % (currency,))
    if currency in CURRENCY_EXPONENT:
        return CURRENCY_EXPONENT[currency]
    if currency in _ACTIVE_CURRENCY_CODES:
        return 2
    raise MoneyEncodePrecisionError(
        "%r has valid alpha-3 shape but is not an active ISO 4217 currency "
        "code" % (currency,))


def encode_money(amount, currency):
    """decimal-string + alpha-3 통화 -> (minor: int, currency: str).
    RFC-0044 §1 SSOT.

    `float`를 한 번도 거치지 않는다 — `amount`는 `Decimal.as_tuple()`의
    부호·자릿수·지수만으로 정수로 재구성되고, 그 정수 재구성 경로는 Decimal의
    산술 컨텍스트(기본 28유효자릿수)에도 의존하지 않는다.

    반올림하지 않는다 — 소수부 자릿수가 `exponent(currency)`와 정확히 같지
    않으면 (부족해도 과해도) 거부한다.
    """
    exp = exponent(currency)
    if not isinstance(amount, str):
        raise MoneyEncodePrecisionError(
            "%r is not a decimal-string amount" % (amount,))
    try:
        d = Decimal(amount)
    except Exception:
        raise MoneyEncodePrecisionError("%r is not a decimal amount" % (amount,))
    if not d.is_finite():
        raise MoneyEncodePrecisionError(
            "%r is not a finite decimal amount" % (amount,))

    sign, digits, e = d.as_tuple()
    places = -e if e < 0 else 0
    if places != exp:
        raise MoneyEncodePrecisionError(
            "%s has %d decimal place(s), currency %s requires exactly %d"
            % (amount, places, currency, exp))

    unscaled = int("".join(str(digit) for digit in digits)) if digits else 0
    if e > 0:
        unscaled *= 10 ** e
    minor = -unscaled if sign else unscaled

    if not (INT64_MIN <= minor <= INT64_MAX):
        raise MoneyEncodePrecisionError(
            "%s %s is outside the 64-bit minor-unit domain" % (amount, currency))
    return minor, currency


def avg_round(total, count):
    """half-to-even 나눗셈 — `avg_round(total, count) -> int`.
    RFC-0044 §4 SSOT.

    5로 끝나는 동점을 가장 가까운 짝수로 반올림한다(IEEE 754 기본 반올림
    모드). `count <= 0`은 이 함수의 정의역 밖이라 `ValueError`를 올린다 —
    빈 RowSet을 어떤 `RunError`로 실패시키는지는 호출자(RFC-0045 §3)의 몫이다.
    """
    if count <= 0:
        raise ValueError("avg_round: count must be positive, got %r" % (count,))
    quotient = (Decimal(total) / Decimal(count)).quantize(
        Decimal(1), rounding=ROUND_HALF_EVEN)
    return int(quotient)


def compare(a, b):
    """같은-통화 순서 비교. `a < b`면 음수, `a > b`면 양수, 같으면 0.
    RFC-0044 §5 SSOT. `a`/`b`는 `encode_money`가 낸 `(minor, currency)` 쌍.

    통화가 다르면 `MoneyCurrencyMismatchError`. 등가(`==`/`!=`)는 이 함수의
    대상이 아니다 — 등가는 구조적 비교라 이 평가기를 거치지 않는다
    (RFC-0044 §5).
    """
    a_minor, a_currency = a
    b_minor, b_currency = b
    if a_currency != b_currency:
        raise MoneyCurrencyMismatchError(
            "cannot compare %s and %s: different currencies"
            % (a_currency, b_currency))
    return (a_minor > b_minor) - (a_minor < b_minor)


def add(a, b):
    """같은-통화 덧셈. `a`/`b`는 `encode_money`가 낸 `(minor, currency)` 쌍.
    RFC-0044 §5 SSOT.

    통화가 다르면 `MoneyCurrencyMismatchError`.
    """
    a_minor, a_currency = a
    b_minor, b_currency = b
    if a_currency != b_currency:
        raise MoneyCurrencyMismatchError(
            "cannot add %s and %s: different currencies"
            % (a_currency, b_currency))
    return a_minor + b_minor, a_currency
