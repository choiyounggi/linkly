"""`TokenProviderTCK` validated by its reference implementation (issue #119b,
D5), plus the negative control that makes the TCK trustworthy in the first
place (D7, #115's lesson: a discriminating harness has to be shown failing
something before its passes mean anything).

`HmacTokenProviderTCKTest` below is `HmacTokenProvider` run through every D6
case. `TokenTCKDiscriminatesTest` is the control: `_NoSignatureCheckProvider`
is a `HmacTokenProvider` with exactly one method replaced — the signature
check the D6 item 2 case exists to catch — and the case must fail against it.
Run alone, in isolation, the same way `test_driver_contract.py`'s
`RollbackTCKDiscriminatesTest` proves `RepositoryDriverTCK`'s rollback case
actually discriminates.
"""

import unittest

from lnpl.drivers import HmacTokenProvider, TokenError
from lnpl.testing import TokenProviderTCK

SECRET = "0123456789abcdef0123456789abcdef"


class HmacTokenProviderTCKTest(TokenProviderTCK, unittest.TestCase):
    """D5: the built-in dev/test provider must pass the published contract."""

    def make_provider(self):
        return HmacTokenProvider(SECRET)

    def make_foreign_issuer_provider(self):
        return HmacTokenProvider(SECRET, issuer="https://somebody-else.example")


class _NoSignatureCheckProvider(HmacTokenProvider):
    """Negative control (`testing/quality/harness-reverse-controls`, D7):
    deliberately vulnerable — `_verify_signature` never checks anything, so
    any signature at all, forged or not, is accepted. The D6 item 2 case
    (`test_a_forged_signature_is_rejected`) must NOT pass against this."""

    def _verify_signature(self, encoded_header, encoded_claims, encoded_signature):
        pass


def _run_one_tck_case(provider_factory, foreign_factory, case_name):
    """Run exactly one `TokenProviderTCK` method, in isolation, against a
    provider built by `provider_factory`, and return the `unittest.TestResult`.
    Mirrors `test_driver_contract.py`'s `_run_one_tck_case`."""

    class _OneCase(TokenProviderTCK, unittest.TestCase):
        def make_provider(self):
            return provider_factory()

        def make_foreign_issuer_provider(self):
            return foreign_factory()

    result = unittest.TestResult()
    _OneCase(case_name).run(result)
    return result


class TokenTCKDiscriminatesTest(unittest.TestCase):
    """`harness-reverse-controls` §1/§5: before citing "the forged-signature
    TCK case catches a provider that skips signature verification", require
    that it actually does — negative control fails, positive control passes,
    and both report exactly one test run (a silently-skipped case would read
    as "no failures" for the wrong reason)."""

    CASE = "test_a_forged_signature_is_rejected"

    def test_the_case_fails_against_a_provider_that_skips_signature_checking(self):
        result = _run_one_tck_case(
            lambda: _NoSignatureCheckProvider(SECRET),
            lambda: _NoSignatureCheckProvider(SECRET, issuer="somebody-else"),
            self.CASE)

        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures) + len(result.errors), 1)

    def test_the_case_passes_against_the_real_hmac_provider(self):
        result = _run_one_tck_case(
            lambda: HmacTokenProvider(SECRET),
            lambda: HmacTokenProvider(SECRET, issuer="somebody-else"),
            self.CASE)

        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures) + len(result.errors), 0)


class NegativeControlSanityTest(unittest.TestCase):
    """The fixture itself, checked directly rather than only through the TCK
    result object above — so a bug in `_run_one_tck_case` cannot hide behind
    a bug in the fixture and vice versa."""

    def test_a_tampered_signature_is_accepted_by_the_vulnerable_provider(self):
        """The vulnerability, demonstrated: a signature this provider itself
        never produced still verifies, because nothing checks it."""
        provider = _NoSignatureCheckProvider(SECRET)
        token = provider.issue("alice", "aud")
        head, payload, signature = token.split(".")
        flipped = ("A" if signature[:1] != "A" else "B") + signature[1:]

        claims = provider.verify(".".join([head, payload, flipped]), "aud")

        self.assertEqual(claims["sub"], "alice")

    def test_every_other_check_still_holds_on_the_vulnerable_provider(self):
        """Only the signature check is disabled — alg/typ/iss/aud/exp are
        untouched, so this is a narrow, deliberate control, not a provider
        that has stopped checking anything at all."""
        provider = _NoSignatureCheckProvider(SECRET)
        token = provider.issue("alice", "aud")

        with self.assertRaises(TokenError):
            provider.verify(token, "some-other-aud")


if __name__ == "__main__":
    unittest.main()
