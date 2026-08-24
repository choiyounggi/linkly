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


if __name__ == "__main__":
    unittest.main()
