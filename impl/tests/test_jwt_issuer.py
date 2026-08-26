"""`--jwt-issuer` (issue #119b, D3): the `iss` a verified token must carry is
now an operator choice, not a `drivers.py` module constant.

`security role <r>` (t119, issue #119 A) reads its role claim out of a token
the built-in `HmacTokenProvider` both issues and verifies — self-asserted,
`docs/serving.md` says so plainly. This flag does not change that on its own:
`HmacTokenProvider` is still HMAC, still dev/test (D2). What it removes is the
one thing that was hardcoded for no reason beyond history — the expected `iss`
string — so an operator can at least stop trusting the literal `"lnpl"` value
without reaching for the `lnpl.tokens` SPI (Task 03) yet. The two properties
that matter here: an unset `--jwt-issuer` is byte-identical to before this
issue, and the checklist order `verify()` uses (alg -> signature -> claims)
does not move just because `iss` is now an instance value instead of a
constant.
"""

import base64
import http.client
import io
import json
import os
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lnpl.cli import main
from lnpl.drivers import ACCEPTED_ALGS, HmacTokenProvider, ISSUER, TokenError
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.serve import serve

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHORTEN = os.path.join(REPO, "examples", "shorten.lnpl")
SHORTEN_PATH = "/shorten-service/shorten"
SECRET = "0123456789abcdef0123456789abcdef"
AUDIENCE = "shorten-service"

LINK_PAYLOAD = {
    "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
    "slug": "abc-123",
    "target": "https://example.com/a",
    "owner": "3f2504e0-4f89-41d3-9a0c-0305e82c3302",
    "clicks": 0,
    "createdAt": "2026-07-31T09:00:00Z",
}


def compile_file(path):
    with open(path, encoding="utf-8") as fh:
        return lower(parse(fh.read()),
                     os.path.splitext(os.path.basename(path))[0]).to_document()


class ConstructorTest(unittest.TestCase):
    """The provider-level surface `--jwt-issuer` is built on."""

    def test_an_unspecified_issuer_defaults_to_the_module_constant(self):
        default = HmacTokenProvider(SECRET)
        explicit = HmacTokenProvider(SECRET, issuer=ISSUER)

        token = default.issue("alice", AUDIENCE)

        # Byte-identical regression (D3): the two constructions verify
        # identically, and the token minted by one verifies under the other.
        self.assertEqual(default.verify(token, AUDIENCE)["iss"], ISSUER)
        self.assertEqual(explicit.verify(token, AUDIENCE)["iss"], ISSUER)

    def test_a_custom_issuer_is_minted_and_accepted(self):
        provider = HmacTokenProvider(SECRET, issuer="https://idp.example")

        token = provider.issue("alice", AUDIENCE)
        claims = provider.verify(token, AUDIENCE)

        self.assertEqual(claims["iss"], "https://idp.example")

    def test_a_token_from_the_wrong_issuer_is_rejected(self):
        default_issuer = HmacTokenProvider(SECRET)
        custom_issuer = HmacTokenProvider(SECRET, issuer="https://idp.example")

        token = default_issuer.issue("alice", AUDIENCE)   # iss="lnpl"

        with self.assertRaises(TokenError) as caught:
            custom_issuer.verify(token, AUDIENCE)
        message = str(caught.exception)
        self.assertIn(ISSUER, message)
        self.assertIn("https://idp.example", message)

    def test_an_empty_issuer_is_refused_at_construction(self):
        """Boundary: `--jwt-issuer ""` is not "unset" — `None` means unset.
        An empty string can never match a real `iss`, so it is refused up
        front instead of silently minting a provider that rejects every
        token (D3's "결정한 동작(거부 권장)")."""
        with self.assertRaises(TokenError) as caught:
            HmacTokenProvider(SECRET, issuer="")
        self.assertIn("empty", str(caught.exception))

    def test_the_accepted_algorithm_list_is_unchanged_by_this_task(self):
        """Task 01 moves the allowlist reference onto the instance (prep for
        Task 03's SPI) but must not widen it (D1 is Task 03/SPI territory)."""
        provider = HmacTokenProvider(SECRET, issuer="https://idp.example")

        token = provider.issue("alice", AUDIENCE)

        header = json.loads(
            base64.urlsafe_b64decode(token.split(".")[0] + "==="))
        self.assertEqual(header["alg"], "HS256")
        self.assertEqual(ACCEPTED_ALGS, ("HS256",))


class CheckOrderRegressionTest(unittest.TestCase):
    """The checklist order in `verify()` does not move: alg settles before
    any key is used, signature settles before any claim (including the now-
    configurable `iss`) is trusted."""

    def test_a_bad_signature_fails_before_iss_is_even_considered(self):
        provider = HmacTokenProvider(SECRET, issuer="https://idp.example")
        token = provider.issue("alice", AUDIENCE)
        head, payload, signature = token.split(".")
        flipped = ("A" if signature[0] != "A" else "B") + signature[1:]

        with self.assertRaises(TokenError) as caught:
            provider.verify(".".join([head, payload, flipped]), AUDIENCE)
        # If iss were checked first, the message would talk about iss; the
        # order guarantee means it talks about the signature instead, exactly
        # as it did before `iss` became a per-instance value.
        self.assertIn("signature", str(caught.exception))


class ServerWiringTest(unittest.TestCase):
    """End-to-end: a provider built with a custom issuer, wired the same way
    `cli.py`'s `_token_provider` wires it, actually gates the served route."""

    def setUp(self):
        self.doc = compile_file(SHORTEN)

    def start(self, token_provider):
        server = serve(self.doc, port=0, token_provider=token_provider)
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def post(self, port, token):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("POST", SHORTEN_PATH, body=json.dumps(LINK_PAYLOAD).encode(),
                     headers={"Authorization": "Bearer %s" % token})
        resp = conn.getresponse()
        return resp, resp.read()

    def test_a_token_matching_the_configured_issuer_is_served(self):
        provider = HmacTokenProvider(SECRET, issuer="https://idp.example")
        port = self.start(provider)
        token = provider.issue("alice", AUDIENCE)

        resp, _ = self.post(port, token)

        self.assertEqual(200, resp.status)

    def test_a_token_from_a_different_issuer_is_rejected(self):
        server_side = HmacTokenProvider(SECRET, issuer="https://idp.example")
        port = self.start(server_side)
        # Minted with the default issuer ("lnpl"), not the one the server
        # expects — same secret, wrong `iss`.
        rogue_token = HmacTokenProvider(SECRET).issue("alice", AUDIENCE)

        resp, raw = self.post(port, rogue_token)

        self.assertEqual(401, resp.status)
        self.assertEqual("auth-invalid", json.loads(raw)["code"])

    def test_unset_jwt_issuer_still_accepts_the_pre_existing_lnpl_tokens(self):
        """The regression DoD requires: default server behavior (issuer
        omitted) is byte-identical to before #119b existed."""
        server_side = HmacTokenProvider(SECRET)   # no issuer= given
        port = self.start(server_side)
        token = server_side.issue("alice", AUDIENCE)

        resp, _ = self.post(port, token)

        self.assertEqual(200, resp.status)


class CliRejectionTest(unittest.TestCase):
    """`--jwt-issuer` reaches the same fail-fast-at-launch path every other
    `serve` selector uses (`ServeCommandRejectionTest`, test_serve_backend.py)."""

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def setUp(self):
        previous = os.environ.get("LNPL_JWT_ISSUER_TEST_SECRET")
        os.environ["LNPL_JWT_ISSUER_TEST_SECRET"] = SECRET
        self.addCleanup(
            lambda: os.environ.pop("LNPL_JWT_ISSUER_TEST_SECRET", None)
            if previous is None
            else os.environ.update({"LNPL_JWT_ISSUER_TEST_SECRET": previous}))

    def test_an_empty_jwt_issuer_stops_the_server_starting(self):
        rc, out, err = self.run_cli(
            ["serve", SHORTEN, "--port", "0",
             "--jwt-secret-env", "LNPL_JWT_ISSUER_TEST_SECRET",
             "--jwt-issuer", ""])

        self.assertEqual(2, rc)
        self.assertIn("empty", err)
        self.assertNotIn("serving", out)


if __name__ == "__main__":
    unittest.main()
