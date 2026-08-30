"""Docker build/run smoke test for the reference deploy image (issue #87).

Not part of `impl/tests` discovery — this exercises an external container
runtime, not `impl/lnpl` itself. Requires `docker` on PATH; skips otherwise.
Run directly from the repo root:

    .venv/bin/python -m unittest discover -s examples/deploy -p "test_*.py" -v

See examples/deploy/README.md for the same procedure run by hand, with the
measured build/run/curl log this test automates.
"""

import json
import pathlib
import shutil
import subprocess
import time
import unittest
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
IMAGE = "linkly-deploy-smoke-test"
_PORT_COUNTER = [18110]

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

    def _run_container(self):
        port = _PORT_COUNTER[0]
        _PORT_COUNTER[0] += 1
        name = f"{IMAGE}-run-{port}"
        subprocess.run(
            ["docker", "run", "-d", "--rm", "-p", f"{port}:8000", "--name", name, IMAGE],
            cwd=REPO_ROOT, check=True, capture_output=True, timeout=30,
        )
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


if __name__ == "__main__":
    unittest.main()
