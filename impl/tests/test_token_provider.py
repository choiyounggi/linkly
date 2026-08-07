"""The `security jwt` capability's real issue/verify path (issue #25).

`security jwt` reached the OpenAPI document and stopped there: no token was
ever minted and none was ever checked, so a service that declared it was
protected by a sentence. These tests pin the three paths that turn the
declaration into behaviour — issue, verify, and *reject* — and the reject cases
are the ones that carry the weight.

Every rejection case is built by hand rather than by asking the provider for a
bad token, because the attacks worth covering are exactly the ones a cooperating
issuer never produces: a header claiming `alg: none`, a signature from a
different key, an `exp` in the past.
"""

import base64
import hmac
import hashlib
import json
import time
import unittest

from lnpl.drivers import (ACCEPTED_ALGS, HmacTokenProvider, ISSUER, LEEWAY_S,
                          MIN_SECRET_BYTES, TokenError, audience_for_path)

SECRET = b"0123456789abcdef0123456789abcdef"          # exactly 32 bytes
OTHER_SECRET = b"fedcba9876543210fedcba9876543210"
AUDIENCE = "orders"


def _b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def forge(header, claims, secret=None):
    """A token assembled by hand. With `secret` the signature is genuine for
    that key; without it the signature slot holds bytes that verify against
    nothing — the shape an `alg: none` attacker sends."""
    parts = [_b64u(json.dumps(header).encode("utf-8")),
             _b64u(json.dumps(claims).encode("utf-8"))]
    signing_input = (".".join(parts)).encode("ascii")
    if secret is None:
        signature = b""
    else:
        signature = hmac.new(secret, signing_input, hashlib.sha256).digest()
    return ".".join(parts + [_b64u(signature)])


def claims_for(**overrides):
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "alice", "jti": "j-1",
              "iat": now, "nbf": now, "exp": now + 900}
    claims.update(overrides)
    return claims


class IssueTest(unittest.TestCase):

    def setUp(self):
        self.provider = HmacTokenProvider(SECRET)

    def test_an_issued_token_verifies_and_carries_its_claims(self):
        token = self.provider.issue("alice", AUDIENCE)

        claims = self.provider.verify(token, AUDIENCE)

        self.assertEqual(claims["sub"], "alice")
        self.assertEqual(claims["aud"], AUDIENCE)
        self.assertEqual(claims["iss"], ISSUER)

    def test_the_header_declares_the_one_accepted_algorithm(self):
        token = self.provider.issue("alice", AUDIENCE)

        header = json.loads(base64.urlsafe_b64decode(
            token.split(".")[0] + "==="))

        self.assertEqual(header["alg"], "HS256")
        self.assertEqual(header["typ"], "JWT")
        self.assertEqual(ACCEPTED_ALGS, ("HS256",))

    def test_two_tokens_for_one_subject_differ_by_token_id(self):
        """`jti` is what a denylist would key on, so it must be per-token."""
        first = self.provider.verify(self.provider.issue("alice", AUDIENCE), AUDIENCE)
        second = self.provider.verify(self.provider.issue("alice", AUDIENCE), AUDIENCE)

        self.assertNotEqual(first["jti"], second["jti"])

    def test_the_claims_carry_no_payload_beyond_the_fixed_set(self):
        """The payload is base64, not ciphertext — anyone holding the token
        reads every claim, so the set stays minimal."""
        claims = self.provider.verify(self.provider.issue("alice", AUDIENCE), AUDIENCE)

        self.assertEqual(set(claims),
                         {"iss", "aud", "sub", "jti", "iat", "nbf", "exp"})

    def test_a_short_secret_is_refused_without_echoing_it(self):
        short = b"x" * (MIN_SECRET_BYTES - 1)

        with self.assertRaises(TokenError) as caught:
            HmacTokenProvider(short)
        message = str(caught.exception)
        self.assertIn(str(MIN_SECRET_BYTES), message)
        self.assertNotIn(short.decode("ascii"), message)

    def test_secret_length_is_measured_in_bytes_not_characters(self):
        """A 31-character non-ASCII secret is more than 31 bytes of key
        material; measuring characters would reject valid keys and accept
        short ones depending on the alphabet."""
        provider = HmacTokenProvider("é" * 16)          # 32 bytes as UTF-8

        self.assertIsNotNone(provider.issue("alice", AUDIENCE))


class VerifyRejectionTest(unittest.TestCase):

    def setUp(self):
        self.provider = HmacTokenProvider(SECRET)

    def test_a_tampered_signature_is_rejected(self):
        token = self.provider.issue("alice", AUDIENCE)
        head, payload, signature = token.split(".")
        flipped = ("A" if signature[0] != "A" else "B") + signature[1:]

        with self.assertRaises(TokenError) as caught:
            self.provider.verify(".".join([head, payload, flipped]), AUDIENCE)
        self.assertIn("signature", str(caught.exception))

    def test_a_tampered_claim_is_rejected(self):
        """The payload is readable, so the only thing stopping an edit is the
        signature over it."""
        token = self.provider.issue("alice", AUDIENCE)
        signature = token.split(".")[2]
        forged = forge({"alg": "HS256", "typ": "JWT"},
                       claims_for(sub="mallory"))
        head, payload, _ = forged.split(".")

        with self.assertRaises(TokenError) as caught:
            self.provider.verify(".".join([head, payload, signature]), AUDIENCE)
        self.assertIn("signature", str(caught.exception))

    def test_alg_none_is_rejected_before_any_signature_work(self):
        """The attack the algorithm allowlist exists for: the token asks to be
        verified with no algorithm at all."""
        token = forge({"alg": "none", "typ": "JWT"}, claims_for())

        with self.assertRaises(TokenError) as caught:
            self.provider.verify(token, AUDIENCE)
        message = str(caught.exception)
        self.assertIn("alg", message)
        self.assertIn("none", message)

    def test_an_algorithm_outside_the_allowlist_is_rejected(self):
        token = forge({"alg": "HS512", "typ": "JWT"}, claims_for(), SECRET)

        with self.assertRaises(TokenError) as caught:
            self.provider.verify(token, AUDIENCE)
        self.assertIn("HS512", str(caught.exception))

    def test_a_token_signed_with_another_key_is_rejected(self):
        token = HmacTokenProvider(OTHER_SECRET).issue("alice", AUDIENCE)

        with self.assertRaises(TokenError) as caught:
            self.provider.verify(token, AUDIENCE)
        self.assertIn("signature", str(caught.exception))

    def test_an_unexpected_typ_is_rejected(self):
        token = forge({"alg": "HS256", "typ": "at+jwt"}, claims_for(), SECRET)

        with self.assertRaises(TokenError) as caught:
            self.provider.verify(token, AUDIENCE)
        self.assertIn("typ", str(caught.exception))

    def test_a_foreign_issuer_is_rejected(self):
        token = forge({"alg": "HS256", "typ": "JWT"},
                      claims_for(iss="somebody-else"), SECRET)

        with self.assertRaises(TokenError) as caught:
            self.provider.verify(token, AUDIENCE)
        self.assertIn("iss", str(caught.exception))

    def test_a_token_for_another_audience_is_rejected(self):
        """One issuer serves several services; each validates its own value or
        a token minted for the neighbour opens this door."""
        token = self.provider.issue("alice", "payments")

        with self.assertRaises(TokenError) as caught:
            self.provider.verify(token, AUDIENCE)
        message = str(caught.exception)
        self.assertIn("payments", message)
        self.assertIn(AUDIENCE, message)

    def test_a_token_with_no_audience_is_rejected(self):
        claims = claims_for()
        del claims["aud"]
        token = forge({"alg": "HS256", "typ": "JWT"}, claims, SECRET)

        with self.assertRaises(TokenError):
            self.provider.verify(token, AUDIENCE)

    def test_a_string_that_is_not_a_compact_jws_is_rejected(self):
        with self.assertRaises(TokenError) as caught:
            self.provider.verify("not-a-token", AUDIENCE)
        self.assertIn("compact JWS", str(caught.exception))

    def test_an_empty_token_is_rejected(self):
        with self.assertRaises(TokenError):
            self.provider.verify("", AUDIENCE)

    def test_undecodable_base64_is_rejected_as_a_token_fault(self):
        """A malformed token is a 401, never a 500 out of the decoder."""
        with self.assertRaises(TokenError):
            self.provider.verify("!!!.!!!.!!!", AUDIENCE)


class VerifyTimeBoundaryTest(unittest.TestCase):
    """`exp`/`nbf` are enforced with a bounded leeway, so the boundary cases
    are "just inside" and "just outside" that window, not "expired or not"."""

    def setUp(self):
        self.provider = HmacTokenProvider(SECRET)

    def test_a_token_that_expired_within_the_leeway_still_verifies(self):
        now = int(time.time())
        token = forge({"alg": "HS256", "typ": "JWT"},
                      claims_for(exp=now - (LEEWAY_S // 2)), SECRET)

        self.assertEqual(self.provider.verify(token, AUDIENCE)["sub"], "alice")

    def test_a_token_that_expired_past_the_leeway_is_rejected(self):
        now = int(time.time())
        token = forge({"alg": "HS256", "typ": "JWT"},
                      claims_for(exp=now - (LEEWAY_S * 2)), SECRET)

        with self.assertRaises(TokenError) as caught:
            self.provider.verify(token, AUDIENCE)
        self.assertIn("expired", str(caught.exception))

    def test_a_token_not_yet_valid_past_the_leeway_is_rejected(self):
        now = int(time.time())
        token = forge({"alg": "HS256", "typ": "JWT"},
                      claims_for(nbf=now + (LEEWAY_S * 2),
                                 exp=now + 3600), SECRET)

        with self.assertRaises(TokenError) as caught:
            self.provider.verify(token, AUDIENCE)
        self.assertIn("not valid yet", str(caught.exception))

    def test_a_token_that_becomes_valid_within_the_leeway_is_accepted(self):
        """The other side of the nbf boundary. Without this case the leeway
        could be zero — or the nbf check could reject everything future — and
        the rejection test above would still be green."""
        now = int(time.time())
        token = forge({"alg": "HS256", "typ": "JWT"},
                      claims_for(nbf=now + (LEEWAY_S // 2),
                                 exp=now + 3600), SECRET)

        self.assertEqual(self.provider.verify(token, AUDIENCE)["sub"], "alice")

    def test_a_zero_lifetime_token_expires_at_once_and_rides_the_leeway(self):
        """Two facts, and the first is the one that can rot: `ttl_ms=0` must
        stay 0. An implementation writing `ttl_ms or DEFAULT_TTL_MS` turns it
        into 15 minutes, and a test that only checked the token verifies would
        pass on that bug — it verifies either way."""
        token = self.provider.issue("alice", AUDIENCE, ttl_ms=0)

        claims = self.provider.verify(token, AUDIENCE)

        self.assertEqual(claims["exp"] - claims["iat"], 0)
        self.assertEqual(claims["sub"], "alice")

    def test_the_default_lifetime_is_fifteen_minutes(self):
        claims = self.provider.verify(self.provider.issue("alice", AUDIENCE),
                                      AUDIENCE)

        self.assertEqual(claims["exp"] - claims["iat"], 15 * 60)


class AudienceForPathTest(unittest.TestCase):

    def test_the_service_slug_is_the_audience(self):
        self.assertEqual(audience_for_path("/orders/checkout"), "orders")

    def test_a_path_without_a_leading_slash_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            audience_for_path("orders/checkout")
        self.assertIn("orders/checkout", str(caught.exception))

    def test_the_root_path_has_no_service_segment(self):
        with self.assertRaises(ValueError):
            audience_for_path("/")

    def test_an_empty_path_is_rejected(self):
        with self.assertRaises(ValueError):
            audience_for_path("")


if __name__ == "__main__":
    unittest.main()
