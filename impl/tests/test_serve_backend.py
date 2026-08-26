"""`lnpl serve` over a real backend, and M3a — a token that is actually checked.

Two things change for the server in issue #25, and each is a claim the previous
contract explicitly disclaimed:

  The store survives the request. `docs/serving.md` said state does not outlive
  a request because the repository was seeded per request in memory. With
  `--backend sqlite:` it does, and the test for that is a second request meeting
  the first one's write.

  401 stops meaning "no header". It meant presence only — any bytes in
  `Authorization` passed. With a token provider the header is verified, and the
  cases that matter are the ones a cooperating client never sends.

The masking sweep rides along because swapping the store is exactly the kind of
change that quietly reroutes a value: same declaration, different code path to
the response.
"""

import http.client
import io
import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lnpl.cli import main
from lnpl.drivers import HmacTokenProvider, SqliteRepositoryDriver, audience_for_path
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.serve import serve

from tests.fixtures import SECRET_ACCOUNT

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHORTEN = os.path.join(REPO, "examples", "shorten.lnpl")
SHORTEN_PATH = "/shorten-service/shorten"
ACCOUNT_PATH = "/account-service/fetch"
SECRET = "0123456789abcdef0123456789abcdef"

# The same full, valid Link payload `test_serve.py` uses — every field the
# `validate input` step requires, `owner` included.
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


def compile_source(source, module="m"):
    return lower(parse(source), module).to_document()


class BackendServerTestCase(unittest.TestCase):
    """One server per test on an ephemeral port; teardown always runs."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name

    def store(self, name="store.db"):
        return os.path.join(self.dir, name)

    def start(self, doc, repository_factory=None, token_provider=None):
        server = serve(doc, port=0, repository_factory=repository_factory,
                       token_provider=token_provider)
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def sqlite_factory(self, path):
        """Records both the drivers handed out and the closes they received.

        Counting `close()` calls rather than only inspecting the connection
        afterwards: a driver that was never closed but happens to hold `None`
        would satisfy a state check and still be the leak.
        """
        opened, closed = [], []

        def factory():
            driver = SqliteRepositoryDriver(path)
            real_close = driver.close

            def closing():
                closed.append(driver)
                return real_close()

            driver.close = closing
            opened.append(driver)
            return driver

        self.opened, self.closed = opened, closed
        return factory

    def wait_until(self, predicate, what, timeout=5.0):
        """Wait for a condition the serving thread reaches on its own.

        The store is released AFTER the response is written — correct order,
        and it means the client can be holding the reply while the handler is
        still in its `finally`. Asserting straight after the response would be
        racing the server, so this waits on the condition instead of sleeping a
        guessed interval.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("timed out waiting for %s" % what)

    def post(self, port, path, payload, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("POST", path, body=json.dumps(payload).encode(),
                     headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read()
        return resp, raw


class RealStoreServingTest(BackendServerTestCase):

    def test_a_request_completes_end_to_end_against_a_real_store(self):
        port = self.start(compile_file(SHORTEN),
                          repository_factory=self.sqlite_factory(self.store()))

        resp, raw = self.post(port, SHORTEN_PATH, LINK_PAYLOAD,
                              {"Authorization": "Bearer anything"})

        self.assertEqual(200, resp.status)
        body = json.loads(raw)
        self.assertEqual("completed", body["status"])
        self.assertTrue(os.path.isfile(self.store()))

    def test_the_store_outlives_the_request_that_wrote_it(self):
        """The second request meets the first one's `create link`. Per-request
        in-memory seeding cannot produce this — it is the whole difference."""
        port = self.start(compile_file(SHORTEN),
                          repository_factory=self.sqlite_factory(self.store()))
        first, _ = self.post(port, SHORTEN_PATH, LINK_PAYLOAD,
                             {"Authorization": "Bearer anything"})

        resp, raw = self.post(port, SHORTEN_PATH, LINK_PAYLOAD,
                              {"Authorization": "Bearer anything"})

        self.assertEqual(200, first.status)
        self.assertEqual(409, resp.status)          # issue #113, M8a
        body = json.loads(raw)
        self.assertEqual("conflict", body["code"])
        self.assertIn("create conflicts", body["detail"])

    def test_the_fake_backend_is_the_negative_control_for_that(self):
        """Same two requests with no factory: 200 both times. Without this the
        500 above would read as a broken workflow, not as persistence."""
        port = self.start(compile_file(SHORTEN))
        first, _ = self.post(port, SHORTEN_PATH, LINK_PAYLOAD,
                             {"Authorization": "Bearer anything"})

        resp, _ = self.post(port, SHORTEN_PATH, LINK_PAYLOAD,
                            {"Authorization": "Bearer anything"})

        self.assertEqual(200, first.status)
        self.assertEqual(200, resp.status)

    def test_every_request_gets_and_releases_its_own_connection(self):
        """One driver per request, confined to the thread that serves it —
        and released whichever way the request ends."""
        port = self.start(compile_file(SHORTEN),
                          repository_factory=self.sqlite_factory(self.store()))

        self.post(port, SHORTEN_PATH, LINK_PAYLOAD,
                  {"Authorization": "Bearer anything"})
        self.post(port, SHORTEN_PATH, LINK_PAYLOAD,
                  {"Authorization": "Bearer anything"})   # this one fails (409)

        self.wait_until(lambda: len(self.closed) == 2,
                        "both requests to release their store")
        self.assertEqual(2, len(self.opened))
        self.assertEqual(self.opened, self.closed,
                         "a request did not release the store it opened")


class MaskingAcrossBackendsTest(BackendServerTestCase):
    """A `Password` value must not reach the response on any backend.

    The response body is the channel that carries the payload here, so it is
    the channel swept. `label` is the negative control: if it were missing too,
    the body was not the payload-carrying channel and the secret's absence
    would prove nothing about masking.
    """

    SECRET_VALUE = "4111111111111111"

    def payload(self):
        return {"id": "a-1", "label": "primary", "cardSecret": self.SECRET_VALUE}

    def test_the_secret_does_not_reach_the_response_on_a_real_store(self):
        port = self.start(compile_source(SECRET_ACCOUNT),
                          repository_factory=self.sqlite_factory(self.store()))

        resp, raw = self.post(port, ACCOUNT_PATH, self.payload())

        self.assertEqual(200, resp.status)
        text = raw.decode("utf-8")
        self.assertNotIn(self.SECRET_VALUE, text)
        self.assertIn("primary", text)          # control present: body captured
        self.assertIn("***", text)

    def test_the_fake_store_masks_the_same_value_the_same_way(self):
        port = self.start(compile_source(SECRET_ACCOUNT))

        resp, raw = self.post(port, ACCOUNT_PATH, self.payload())

        self.assertEqual(200, resp.status)
        text = raw.decode("utf-8")
        self.assertNotIn(self.SECRET_VALUE, text)
        self.assertIn("primary", text)

    def test_the_store_itself_holds_the_value_the_response_masks(self):
        """Masking is an output contract, not an encryption one — the row does
        carry the real value. Stating that here keeps the two assertions above
        from being read as a claim about the store."""
        path = self.store()
        port = self.start(compile_source(SECRET_ACCOUNT),
                          repository_factory=self.sqlite_factory(path))
        self.post(port, ACCOUNT_PATH, self.payload())

        driver = SqliteRepositoryDriver(path)
        self.addCleanup(driver.close)
        row = driver.execute("entity.account", "read", "entity.account#a-1")

        self.assertEqual(self.SECRET_VALUE, row["cardSecret"])


class TokenVerificationTest(BackendServerTestCase):
    """M3 keeps its meaning; M3a is the new row."""

    def setUp(self):
        super().setUp()
        self.provider = HmacTokenProvider(SECRET)
        self.audience = audience_for_path(SHORTEN_PATH)

    def serve_secured(self):
        return self.start(compile_file(SHORTEN), token_provider=self.provider)

    def bearer(self, token):
        return {"Authorization": "Bearer %s" % token}

    def test_a_valid_token_is_served(self):
        port = self.serve_secured()
        token = self.provider.issue("alice", self.audience)

        resp, _ = self.post(port, SHORTEN_PATH, LINK_PAYLOAD, self.bearer(token))

        self.assertEqual(200, resp.status)

    def test_a_missing_header_is_still_auth_missing(self):
        """M3 unchanged: the row that already shipped keeps its code."""
        port = self.serve_secured()

        resp, raw = self.post(port, SHORTEN_PATH, LINK_PAYLOAD)

        self.assertEqual(401, resp.status)
        self.assertEqual("auth-missing", json.loads(raw)["code"])

    def test_a_tampered_token_is_auth_invalid(self):
        port = self.serve_secured()
        token = self.provider.issue("alice", self.audience)
        head, payload, signature = token.split(".")
        broken = "%s.%s.%s" % (head, payload,
                               ("A" if signature[0] != "A" else "B") + signature[1:])

        resp, raw = self.post(port, SHORTEN_PATH, LINK_PAYLOAD, self.bearer(broken))

        self.assertEqual(401, resp.status)
        self.assertEqual("auth-invalid", json.loads(raw)["code"])

    def test_an_expired_token_is_auth_invalid(self):
        port = self.serve_secured()
        stale = HmacTokenProvider(SECRET)
        token = stale.issue("alice", self.audience, ttl_ms=-3600 * 1000)

        resp, raw = self.post(port, SHORTEN_PATH, LINK_PAYLOAD, self.bearer(token))

        self.assertEqual(401, resp.status)
        self.assertEqual("auth-invalid", json.loads(raw)["code"])

    def test_a_token_for_another_service_is_auth_invalid(self):
        port = self.serve_secured()
        token = self.provider.issue("alice", "some-other-service")

        resp, raw = self.post(port, SHORTEN_PATH, LINK_PAYLOAD, self.bearer(token))

        self.assertEqual(401, resp.status)
        self.assertEqual("auth-invalid", json.loads(raw)["code"])

    def test_a_non_bearer_authorization_is_auth_invalid(self):
        port = self.serve_secured()

        resp, raw = self.post(port, SHORTEN_PATH, LINK_PAYLOAD,
                              {"Authorization": "Basic dXNlcjpwYXNz"})

        self.assertEqual(401, resp.status)
        self.assertEqual("auth-invalid", json.loads(raw)["code"])

    def test_the_rejection_does_not_say_which_check_failed(self):
        """An attacker tuning a forgery learns nothing from the response; the
        server's own stderr carries the detail, keyed by correlation id."""
        port = self.serve_secured()
        token = self.provider.issue("alice", "some-other-service")

        resp, raw = self.post(port, SHORTEN_PATH, LINK_PAYLOAD, self.bearer(token))

        text = raw.decode("utf-8")
        body = json.loads(raw)
        self.assertEqual(401, resp.status)
        # Assert what the body IS before asserting what it is not: an empty or
        # differently-shaped body would satisfy every `assertNotIn` below while
        # proving nothing about the rejection.
        self.assertEqual("auth-invalid", body["code"])
        self.assertTrue(body["correlation_id"].startswith("req-"))
        for leak in ("audience", "signature", "expired", "some-other-service"):
            self.assertNotIn(leak, text)

    def test_without_a_provider_any_header_still_passes(self):
        """The default did not move: a server started with no provider behaves
        exactly as it did before this issue."""
        port = self.start(compile_file(SHORTEN))

        resp, _ = self.post(port, SHORTEN_PATH, LINK_PAYLOAD,
                            {"Authorization": "Bearer not-a-real-token"})

        self.assertEqual(200, resp.status)


class ServeCommandRejectionTest(unittest.TestCase):
    """A misconfigured server fails before it binds a socket."""

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_an_unknown_backend_stops_the_server_starting(self):
        rc, out, err = self.run_cli(["serve", SHORTEN, "--port", "0",
                                     "--backend", "redis://x"])

        self.assertEqual(2, rc)
        self.assertIn("redis://x", err)
        self.assertNotIn("serving", out)

    def test_an_unset_secret_variable_stops_the_server_starting(self):
        rc, out, err = self.run_cli(["serve", SHORTEN, "--port", "0",
                                     "--jwt-secret-env", "LNPL_UNSET_XYZ"])

        self.assertEqual(2, rc)
        self.assertIn("LNPL_UNSET_XYZ", err)
        self.assertNotIn("serving", out)

    def test_a_short_secret_stops_the_server_starting(self):
        previous = os.environ.get("LNPL_SHORT_SECRET")
        os.environ["LNPL_SHORT_SECRET"] = "too-short"
        self.addCleanup(lambda: os.environ.pop("LNPL_SHORT_SECRET", None)
                        if previous is None
                        else os.environ.update({"LNPL_SHORT_SECRET": previous}))

        rc, out, err = self.run_cli(["serve", SHORTEN, "--port", "0",
                                     "--jwt-secret-env", "LNPL_SHORT_SECRET"])

        self.assertEqual(2, rc)
        self.assertIn("32", err)
        self.assertNotIn("too-short", err)
        self.assertNotIn("serving", out)


class ServingDocumentTest(unittest.TestCase):
    """The mapping table is normative, so a row that only exists in the code is
    an undocumented contract and a row that only exists in the document is a
    promise nothing keeps.

    Both directions are checked because only one of them fails loudly on its
    own: an undocumented code path still works, and stays invisible until a
    client depends on behaviour nobody wrote down.
    """

    def setUp(self):
        with open(os.path.join(REPO, "docs", "serving.md"), encoding="utf-8") as fh:
            self.serving = fh.read()

    def test_every_problem_code_the_server_can_send_is_documented(self):
        from lnpl.serve import _TITLES

        undocumented = sorted(code for code in _TITLES
                              if code not in self.serving)

        self.assertEqual([], undocumented)

    def test_the_m3a_row_names_the_flag_that_turns_it_on(self):
        """M3a only exists when a provider is configured; a row that omits the
        flag reads as an unconditional behaviour change."""
        row = next((line for line in self.serving.splitlines()
                    if line.startswith("| M3a ")), None)

        self.assertIsNotNone(row, "docs/serving.md has no M3a row")
        self.assertIn("auth-invalid", row)
        self.assertIn("401", row)
        self.assertIn("--jwt-secret-env", self.serving)

    def test_the_contract_no_longer_claims_state_cannot_survive_a_request(self):
        """The old limit said the store does not outlive a request. It now can,
        and leaving the sentence would make the document the wrong answer to
        the question this issue exists to change."""
        self.assertIn("--backend sqlite:", self.serving)
        self.assertNotIn("#25가 열려 있는 동안", self.serving)

    def test_the_backends_document_exists_and_is_pointed_at(self):
        path = os.path.join(REPO, "docs", "backends.md")

        self.assertTrue(os.path.isfile(path))
        self.assertIn("docs/backends.md", self.serving)


if __name__ == "__main__":
    unittest.main()
