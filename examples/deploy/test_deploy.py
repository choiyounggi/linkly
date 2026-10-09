"""Docker build/run smoke test for the reference deploy image (issue #87).

Not part of `impl/tests` discovery — this exercises an external container
runtime, not `impl/lnpl` itself. Requires `docker` on PATH; skips otherwise.
Run directly from the repo root:

    .venv/bin/python -m unittest discover -s examples/deploy -p "test_*.py" -v

See examples/deploy/README.md for the same procedure run by hand, with the
measured build/run/curl log this test automates.
"""

import http.client
import json
import os
import pathlib
import re
import shutil
import ssl
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
IMAGE = "linkly-deploy-smoke-test"
_PORT_COUNTER = [18110]

# issue #189: generated compose / k8s checks (run by hand like the rest).
SMOKE_IMAGE = "linkly-compose-smoke-test"
KUBECONFORM_IMAGE = "ghcr.io/yannh/kubeconform:v0.6.7"
BACKING_IMAGES = ("postgres:16", "redis:7")
LINKHUB = REPO_ROOT / "examples" / "linkhub.lnpl"
SMOKE_ENV = dict(os.environ, POSTGRES_PASSWORD="compose-smoke-only")

SAVE_BOOKMARK_BODY = json.dumps({
    "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
    "url": "https://example.com/a",
    "title": "Example",
    "owner": "3f2504e0-4f89-41d3-9a0c-0305e82c3302",
    "savedAt": "2026-08-24T09:00:00Z",
    "visits": 0,
}).encode()


@unittest.skipUnless(shutil.which("docker"), "docker not on PATH")
class DeployDockerfileTest(unittest.TestCase):
    """Builds examples/deploy/Dockerfile once, boots a fresh container per case."""

    @classmethod
    def setUpClass(cls):
        subprocess.run(
            [
                "docker", "build",
                "-f", "examples/deploy/Dockerfile",
                "--build-context", "repo=.",
                "-t", IMAGE,
                "examples/deploy",
            ],
            cwd=REPO_ROOT, check=True, capture_output=True, timeout=300,
        )

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "rmi", IMAGE], capture_output=True)

    def _run_container(self, env=None):
        port = _PORT_COUNTER[0]
        _PORT_COUNTER[0] += 1
        name = f"{IMAGE}-run-{port}"
        cmd = ["docker", "run", "-d", "--rm", "-p", f"{port}:8000", "--name", name]
        for key, value in (env or {}).items():
            cmd.extend(["-e", f"{key}={value}"])
        cmd.append(IMAGE)
        subprocess.run(cmd, cwd=REPO_ROOT, check=True, capture_output=True, timeout=30)
        self.addCleanup(subprocess.run, ["docker", "stop", name], capture_output=True)
        time.sleep(2)
        return port

    def test_save_bookmark_workflow_completes_with_200(self):
        port = self._run_container()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/link-hub-service/save-bookmark",
            data=SAVE_BOOKMARK_BODY,
            headers={"Authorization": "Bearer any"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body = json.loads(resp.read())
        assert status == 200, f"expected 200, got {status}"
        assert body["status"] == "completed", body

    def test_unknown_path_returns_404(self):
        port = self._run_container()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/no/such/path")
        try:
            urllib.request.urlopen(req, timeout=10)
            raise AssertionError("expected HTTPError for an unregistered path, request succeeded")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404, f"expected 404, got {exc.code}"

    def test_malformed_json_body_returns_400(self):
        port = self._run_container()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/link-hub-service/save-bookmark",
            data=b"not-json",
            headers={"Authorization": "Bearer any"},
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            raise AssertionError("expected HTTPError for a malformed JSON body, request succeeded")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400, f"expected 400, got {exc.code}"

    def test_metrics_env_var_exposes_metrics_endpoint(self):
        port = self._run_container(env={"LNPL_METRICS": "1"})
        req = urllib.request.Request(f"http://127.0.0.1:{port}/-/metrics")
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body = resp.read()
        assert status == 200, f"expected 200, got {status}"
        assert len(body) > 0, "expected a non-empty Prometheus body"

    def test_metrics_env_var_absent_by_default_returns_404(self):
        port = self._run_container()
        req = urllib.request.Request(f"http://127.0.0.1:{port}/-/metrics")
        try:
            urllib.request.urlopen(req, timeout=10)
            raise AssertionError("expected HTTPError, request succeeded")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404, f"expected 404, got {exc.code}"

    def test_rate_limit_env_var_returns_429_beyond_limit(self):
        """env LNPL_RATE_LIMIT=1: the TokenBucket starts with 1 token and
        refills about 1 token/second, far slower than 10 requests issued
        back-to-back with no sleep. The "at least one 429" assertion holds
        while the 10 requests finish within 1 second in total, which a
        loopback round trip to a fake-backend workflow does."""
        port = self._run_container(env={"LNPL_RATE_LIMIT": "1"})
        statuses = []
        retry_afters = []
        for _ in range(10):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/link-hub-service/save-bookmark",
                data=SAVE_BOOKMARK_BODY,
                headers={"Authorization": "Bearer any"},
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    statuses.append(resp.status)
                    retry_afters.append(None)
            except urllib.error.HTTPError as exc:
                statuses.append(exc.code)
                retry_afters.append(exc.headers.get("Retry-After"))
        assert statuses[0] == 200, f"expected request 1 to be 200, got {statuses[0]}"
        assert 429 in statuses[1:], f"expected at least one 429 in {statuses[1:]}"
        for status, retry_after in zip(statuses, retry_afters):
            if status == 429:
                assert retry_after is not None, "a 429 response is missing Retry-After"


@unittest.skipUnless(shutil.which("docker") and shutil.which("openssl"),
                     "docker and openssl both required")
class NginxConfigTest(unittest.TestCase):
    """issue #148: `nginx.conf` is a config file, not a running service --
    `nginx -t` (the official `nginx:alpine` image, read-only bind mounts, no
    container left running afterward) is the only way to verify it parses
    without standing up a whole TLS-terminated stack. A throwaway
    self-signed cert satisfies `ssl_certificate`'s existence check; `nginx
    -t` validates syntax/references, not certificate trust."""

    @classmethod
    def setUpClass(cls):
        cls.certs_dir = REPO_ROOT / ".claude" / "tmp" / "nginx-config-test-certs"
        cls.certs_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048",
             "-keyout", str(cls.certs_dir / "privkey.pem"),
             "-out", str(cls.certs_dir / "fullchain.pem"),
             "-days", "1", "-nodes", "-subj", "/CN=localhost"],
            check=True, capture_output=True, timeout=30,
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.certs_dir, ignore_errors=True)

    def test_normal_nginx_conf_syntax_is_valid(self):
        result = subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{REPO_ROOT / 'examples' / 'deploy' / 'nginx.conf'}:/etc/nginx/conf.d/default.conf:ro",
             "-v", f"{self.certs_dir}:/etc/nginx/certs:ro",
             "nginx:alpine", "nginx", "-t"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, (
            f"nginx -t failed (rc={result.returncode}):\n{result.stderr}")
        assert "syntax is ok" in result.stderr, result.stderr
        assert "test is successful" in result.stderr, result.stderr

    def test_error_a_deliberately_broken_directive_fails_nginx_t(self):
        # Boundary/negative control: proves the test above is actually
        # exercising nginx's parser, not just "docker ran and exited 0."
        broken = self.certs_dir / "broken.conf"
        broken.write_text("server { listen 443 ssl; not_a_real_directive; }\n")
        result = subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{broken}:/etc/nginx/conf.d/default.conf:ro",
             "-v", f"{self.certs_dir}:/etc/nginx/certs:ro",
             "nginx:alpine", "nginx", "-t"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode != 0, "a broken directive should fail nginx -t"
        assert "not_a_real_directive" in result.stderr, result.stderr


_UNVERIFIED_TLS = ssl.create_default_context()
_UNVERIFIED_TLS.check_hostname = False
_UNVERIFIED_TLS.verify_mode = ssl.CERT_NONE


def _wait_until_ready(port, path, timeout=15, tls=False):
    scheme = "https" if tls else "http"
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            urllib.request.urlopen(
                f"{scheme}://127.0.0.1:{port}{path}", timeout=1,
                context=_UNVERIFIED_TLS if tls else None)
            return
        except Exception as exc:
            last_exc = exc
            time.sleep(0.2)
    raise AssertionError(f"port {port}{path} never answered: {last_exc}")


@unittest.skipUnless(shutil.which("docker") and shutil.which("openssl"),
                     "docker and openssl both required")
class TwoInstanceGatewayRateLimitTest(unittest.TestCase):
    """issue #194: `--rate-limit`/`LNPL_RATE_LIMIT` is a per-process token
    bucket (docs/serving.md "Rate limit") -- with K instances behind a
    load balancer the combined admitted rate is N x K, no shared cap, and
    there is no per-client limit either. This proves the documented fix on
    the SHIPPED reference: the gateway config under test is
    examples/deploy/nginx.conf itself, read at test time, with only two
    things changed -- an `upstream` block naming the two linkly containers
    is prepended, and the two `proxy_pass http://127.0.0.1:8000;` lines
    point at it. `limit_req_zone`/`limit_req`/`limit_req_status` are the
    file's own, so deleting them from the shipped file turns this red.
    TLS is kept: the throwaway certificate is mounted and requests go over
    https with an unverified context.

    Arithmetic (nginx leaky bucket with `nodelay`,
    ngx_http_limit_req_module,
    https://nginx.org/en/docs/http/ngx_http_limit_req_module.html):
    the zone keeps an "excess" counter in 1/1000-request units. Each
    request adds 1000, and the counter decays by `rate` units per ms
    (rate=20r/s -> 20 units/ms). A request is rejected once excess would
    exceed `burst * 1000`. So the first request plus `burst` more are
    admitted at once (burst + 1 = 11 for burst=10), and every further
    1000 units of decay -- 1000 / rate = 50 ms at 20r/s, one token per
    50 ms -- admits one more. (The time for a FULL burst to decay is
    burst * 50 = 500 ms; that is not the bound that matters here.) The
    number admitted out of 20 back-to-back requests is therefore
        burst + 1 <= admitted <= burst + 1 + floor(elapsed_ms / 50)
    where elapsed_ms is the measured wall-clock time of the whole burst.
    The test asserts that range, not an exact 11, so a slow host cannot
    make correct code fail; at least one 429 must remain. Measured
    2026-10-06 on an idle laptop: 11 admitted / 9 rejected, 11-17 ms for
    12 requests.

    `rate` and `burst` are parsed from the shipped file, so retuning it
    does not break the test (as long as burst + 1 < 20, the request count). Short fixed per-call tags (not
    `self._testMethodName`) name every docker resource below: an nginx
    `upstream { server <name>:8000; }` name is DNS-resolved at nginx
    startup, and a long name can pass the 63-character DNS label limit
    (RFC 1035), which makes nginx exit with `host not found in upstream`
    -- seen by the test only as a bare ConnectionRefusedError.
    """

    IMAGE = "linkly-two-instance-smoke-test"
    NGINX_CONF = REPO_ROOT / "examples" / "deploy" / "nginx.conf"
    PROXY_PASS = "proxy_pass http://127.0.0.1:8000;"
    COUNT = 20

    @classmethod
    def setUpClass(cls):
        subprocess.run(
            [
                "docker", "build",
                "-f", "examples/deploy/Dockerfile",
                "--build-context", "repo=.",
                "-t", cls.IMAGE,
                "examples/deploy",
            ],
            cwd=REPO_ROOT, check=True, capture_output=True, timeout=300,
        )
        cls.certs_dir = REPO_ROOT / ".claude" / "tmp" / "t194-gw-certs"
        cls.certs_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048",
             "-keyout", str(cls.certs_dir / "privkey.pem"),
             "-out", str(cls.certs_dir / "fullchain.pem"),
             "-days", "1", "-nodes", "-subj", "/CN=localhost"],
            check=True, capture_output=True, timeout=30,
        )

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "rmi", cls.IMAGE], capture_output=True)
        shutil.rmtree(cls.certs_dir, ignore_errors=True)

    def _shipped_conf_for(self, upstream_names):
        """The shipped nginx.conf with only the upstream swapped in."""
        text = self.NGINX_CONF.read_text()
        assert text.count(self.PROXY_PASS) == 2, (
            f"expected exactly 2 `{self.PROXY_PASS}` lines in the shipped "
            f"nginx.conf, found {text.count(self.PROXY_PASS)}")
        upstream = "upstream linkly_upstream {\n" + "".join(
            f"    server {name}:8000;\n" for name in upstream_names) + "}\n\n"
        return upstream + text.replace(
            self.PROXY_PASS, "proxy_pass http://linkly_upstream;")

    def _shipped_limits(self):
        text = self.NGINX_CONF.read_text()
        rate = re.search(r"limit_req_zone\s.*\brate=(\d+)r/s;", text)
        burst = re.search(r"^\s*limit_req\s+zone=\S+\s+burst=(\d+)\s+nodelay;",
                          text, re.MULTILINE)
        assert rate and burst, (
            "shipped nginx.conf has no `limit_req_zone ... rate=Nr/s;` / "
            "`limit_req zone=... burst=N nodelay;` pair")
        return int(rate.group(1)), int(burst.group(1))

    def _start_stack(self, tag):
        """Fresh scratch network + 2 linkly containers + 1 nginx gateway
        for this call alone; everything created here is removed via
        addCleanup regardless of how the test ends."""
        network = f"linkly-t194-net-{tag}"
        subprocess.run(["docker", "network", "create", network],
                       check=True, capture_output=True, timeout=30)
        self.addCleanup(subprocess.run, ["docker", "network", "rm", network],
                        capture_output=True)

        upstream_names = []
        for suffix in ("a", "b"):
            name = f"linkly-t194-{tag}-{suffix}"
            subprocess.run(
                ["docker", "run", "-d", "--rm", "--name", name,
                 "--network", network, self.IMAGE],
                cwd=REPO_ROOT, check=True, capture_output=True, timeout=30,
            )
            self.addCleanup(subprocess.run, ["docker", "stop", name],
                            capture_output=True)
            upstream_names.append(name)

        gw_port = _PORT_COUNTER[0]
        _PORT_COUNTER[0] += 1
        gw_name = f"linkly-t194-{tag}-gw"
        conf_dir = REPO_ROOT / ".claude" / "tmp" / f"t194-gw-conf-{tag}"
        conf_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, conf_dir, ignore_errors=True)
        (conf_dir / "default.conf").write_text(
            self._shipped_conf_for(upstream_names))
        subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", gw_name,
             "--network", network, "-p", f"{gw_port}:443",
             "-v", f"{conf_dir / 'default.conf'}:/etc/nginx/conf.d/default.conf:ro",
             "-v", f"{self.certs_dir}:/etc/nginx/certs:ro",
             "nginx:alpine"],
            cwd=REPO_ROOT, check=True, capture_output=True, timeout=30,
        )
        self.addCleanup(subprocess.run, ["docker", "stop", gw_name],
                        capture_output=True)
        _wait_until_ready(gw_port, "/-/healthz", tls=True)
        return gw_port

    def _send_burst(self, port, tls, path="/link-hub-service/save-bookmark"):
        """Returns (statuses, elapsed_ms) for COUNT back-to-back POSTs over
        one already-connected connection (connect time is not counted)."""
        if tls:
            conn = http.client.HTTPSConnection(
                "127.0.0.1", port, context=_UNVERIFIED_TLS)
        else:
            conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.connect()
        statuses = []
        started = time.perf_counter()
        for _ in range(self.COUNT):
            conn.request(
                "POST", path, body=SAVE_BOOKMARK_BODY,
                headers={"Authorization": "Bearer any",
                         "Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            resp.read()
            statuses.append(resp.status)
        elapsed_ms = (time.perf_counter() - started) * 1000
        conn.close()
        return statuses, elapsed_ms

    def test_combined_admitted_count_is_bounded_by_the_gateway_limit(self):
        rate, burst = self._shipped_limits()
        port = self._start_stack("comb")
        statuses, elapsed_ms = self._send_burst(port, tls=True)
        admitted = statuses.count(200)
        rejected = statuses.count(429)
        ms_per_token = 1000 / rate
        upper = burst + 1 + int(elapsed_ms // ms_per_token)
        detail = f"{statuses} in {elapsed_ms:.1f} ms"
        assert admitted + rejected == self.COUNT, detail
        assert rejected >= 1, f"the gateway never rejected: {detail}"
        assert burst + 1 <= admitted <= upper, (
            f"expected {burst + 1} <= admitted <= {upper}, got {admitted}: "
            f"{detail}")

    def test_healthz_is_never_rate_limited_at_the_gateway(self):
        port = self._start_stack("hz")
        self._send_burst(port, tls=True)  # saturate the shared zone first
        conn = http.client.HTTPSConnection(
            "127.0.0.1", port, context=_UNVERIFIED_TLS)
        healthz_statuses = []
        for _ in range(self.COUNT):
            conn.request("GET", "/-/healthz")
            resp = conn.getresponse()
            resp.read()
            healthz_statuses.append(resp.status)
        conn.close()
        assert healthz_statuses == [200] * self.COUNT, healthz_statuses

    def test_single_instance_without_a_gateway_admits_every_request(self):
        port = _PORT_COUNTER[0]
        _PORT_COUNTER[0] += 1
        name = "linkly-t194-solo-direct"
        subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", name,
             "-p", f"{port}:8000", self.IMAGE],
            cwd=REPO_ROOT, check=True, capture_output=True, timeout=30,
        )
        self.addCleanup(subprocess.run, ["docker", "stop", name],
                        capture_output=True)
        _wait_until_ready(port, "/-/healthz")
        statuses, _ = self._send_burst(port, tls=False)
        assert statuses == [200] * self.COUNT, (
            f"expected all {self.COUNT} admitted with no gateway in front "
            f"and no LNPL_RATE_LIMIT set, got {statuses}")


def _image_present(ref):
    return subprocess.run(["docker", "image", "inspect", ref],
                          capture_output=True).returncode == 0


def _lnpl_generate(name, out_dir, *sets):
    """`lnpl generate <name> examples/linkhub.lnpl --out <out_dir> --set ...`
    running this worktree's code (PYTHONPATH=impl)."""
    cmd = [sys.executable, "-m", "lnpl", "generate", name, str(LINKHUB),
           "--out", str(out_dir)]
    cmd += [x for s in sets for x in ("--set", s)]
    return subprocess.run(
        cmd, cwd=REPO_ROOT, env=dict(os.environ, PYTHONPATH=str(REPO_ROOT / "impl")),
        check=True, capture_output=True, timeout=120)


def _scratch_dir(test, tag):
    path = REPO_ROOT / ".claude" / "tmp" / ("deploy-%s-%d" % (tag, _PORT_COUNTER[0]))
    path.mkdir(parents=True, exist_ok=True)
    test.addCleanup(shutil.rmtree, path, True)
    return path


@unittest.skipUnless(shutil.which("docker"), "docker not on PATH")
class ComposeGeneratorSmokeTest(unittest.TestCase):
    """issue #189: generated compose boots to readyz 200 (by hand)."""

    @classmethod
    def setUpClass(cls):
        cls.had = {ref: _image_present(ref) for ref in BACKING_IMAGES}
        subprocess.run(
            ["docker", "build", "-f", "docker/Dockerfile", "-t", SMOKE_IMAGE, "."],
            cwd=REPO_ROOT, check=True, capture_output=True, timeout=600)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["docker", "rmi", SMOKE_IMAGE], capture_output=True)
        for ref in BACKING_IMAGES:
            if not cls.had[ref]:
                subprocess.run(["docker", "rmi", ref], capture_output=True)

    def test_generated_compose_boots_to_readyz_200(self):
        port = _PORT_COUNTER[0]
        _PORT_COUNTER[0] += 1
        out = _scratch_dir(self, "compose")
        project = "linkly-compose-smoke-%d" % port
        _lnpl_generate("compose", out, "image=" + SMOKE_IMAGE,
                       "port=%d" % port, "source=" + str(LINKHUB))
        compose = ["docker", "compose", "-p", project, "-f", str(out / "compose.yaml")]
        # LIFO: `down` runs before the scratch dir is removed.
        self.addCleanup(subprocess.run, compose + ["down", "-v", "--rmi", "local"],
                        env=SMOKE_ENV, capture_output=True, timeout=180)
        up = subprocess.run(
            compose + ["up", "-d", "--wait", "--wait-timeout", "120"],
            env=SMOKE_ENV, capture_output=True, text=True, timeout=300)
        self.assertEqual(up.returncode, 0, up.stderr)
        with urllib.request.urlopen("http://127.0.0.1:%d/-/readyz" % port,
                                    timeout=10) as resp:
            self.assertEqual(resp.status, 200)
        ps = subprocess.run(
            compose + ["ps", "--format", "{{.Service}} {{.Health}}"],
            env=SMOKE_ENV, capture_output=True, text=True, timeout=60)
        self.assertEqual(sorted(ps.stdout.split("\n")[:-1]),
                         ["app healthy", "postgres healthy", "redis healthy"])

    def test_compose_config_round_trips_a_hostile_image(self):
        hostile = "a: b # c 'q' \"dq\"\n- *x &y !z {w} [v] $HOME \\ \t \u00e9 \u2028"
        out = _scratch_dir(self, "hostile")
        _lnpl_generate("compose", out, "image=" + hostile)
        done = subprocess.run(
            ["docker", "compose", "-f", str(out / "compose.yaml"), "config",
             "--format", "json"],
            env=SMOKE_ENV, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        # `docker compose config` prints `$` in its escaped `$$` form.
        self.assertEqual(json.loads(done.stdout)["services"]["app"]["image"],
                         hostile.replace("$", "$$"))


@unittest.skipUnless(shutil.which("docker"), "docker not on PATH")
class K8sKubeconformTest(unittest.TestCase):
    """issue #189: `kubectl apply --dry-run=client` needs an API server for
    discovery even with --validate=false, so the no-cluster check is
    kubeconform (needs network for its schemas)."""

    @classmethod
    def setUpClass(cls):
        cls.had = _image_present(KUBECONFORM_IMAGE)

    @classmethod
    def tearDownClass(cls):
        if not cls.had:
            subprocess.run(["docker", "rmi", KUBECONFORM_IMAGE], capture_output=True)

    def _kubeconform(self, data):
        return subprocess.run(
            ["docker", "run", "--rm", "-i", KUBECONFORM_IMAGE, "-strict",
             "-summary", "-"],
            input=data, capture_output=True, timeout=300)

    def _generated(self):
        out = _scratch_dir(self, "k8s")
        _lnpl_generate("k8s", out)
        return (out / "k8s.yaml").read_bytes()

    def test_generated_k8s_passes_kubeconform(self):
        result = self._kubeconform(self._generated())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"Invalid: 0, Errors: 0", result.stdout)

    def test_reverse_control_a_misspelled_field_fails(self):
        data = self._generated().replace(b"terminationGracePeriodSeconds",
                                         b"terminationGracePeriodSecond")
        result = self._kubeconform(data)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
