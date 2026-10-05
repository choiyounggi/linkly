"""`.github/workflows/release.yml`의 배선 단언 — GitHub Actions는 로컬에서
실행할 수 없으므로, 워크플로 파일의 **소스 텍스트**에 대해 단언한다
(issue #154).

이 파일은 YAML을 실행하지 않는다. `release` 잡이 하드코딩된
"See CHANGELOG.md for details."로 되돌아가거나 `--notes-file` 배선이
조용히 사라지는 회귀를 잡는 것이 목적이다.
"""
import os
import re
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RELEASE_YML_PATH = os.path.join(REPO, ".github", "workflows", "release.yml")
DOCKERFILE_PATH = os.path.join(REPO, "docker", "Dockerfile")


def _read():
    with open(RELEASE_YML_PATH, encoding="utf-8") as fh:
        return fh.read()


def _read_dockerfile():
    with open(DOCKERFILE_PATH, encoding="utf-8") as fh:
        return fh.read()


def _image_job_text():
    """The `image:` job's own text, isolated from the rest of release.yml
    (issue #190) — every assertion below that must not false-positive on
    `gates`/`build`/`release`'s unrelated text scopes itself to this slice.
    """
    text = _read()
    start = text.index("\n  image:\n")
    end = text.index("\n  publish-pypi:\n")
    return text[start:end]


def _computed_tags(tag, owner):
    """Run the `Compute image tags` step's own script under bash and return
    the tag lines it writes to `$GITHUB_OUTPUT` — text presence alone cannot
    tell whether the `X.Y` echo still sits inside the pre-release guard.
    """
    job_text = _image_job_text()
    start = job_text.index("        id: vars\n        run: |\n")
    start = job_text.index("run: |\n", start) + len("run: |\n")
    end = job_text.index("\n\n      - name:", start)
    script = "\n".join(line[10:] for line in job_text[start:end].split("\n"))
    proc = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        env={"PATH": os.environ["PATH"], "TAG": tag, "REPO_OWNER": owner,
             "GITHUB_OUTPUT": "/dev/stdout"},
        capture_output=True, text=True, check=True,
    )
    lines = proc.stdout.splitlines()
    if lines[0] != "tags<<TAGEOF" or lines[-1] != "TAGEOF":
        raise AssertionError("unexpected $GITHUB_OUTPUT shape: %r" % lines)
    return lines[1:-1]


class ReleaseNotesWiringTest(unittest.TestCase):
    def test_uses_notes_file_flag(self):
        self.assertIn("--notes-file", _read())

    def test_hardcoded_placeholder_notes_are_gone(self):
        self.assertNotIn("See CHANGELOG.md for details.", _read())

    def test_calls_changelog_section_script(self):
        self.assertIn("scripts/changelog_section.py", _read())


class ImageJobWiringTest(unittest.TestCase):
    """issue #190: the release-tag image job that builds docker/Dockerfile,
    smoke-tests it, and pushes to GHCR. Each test below is scoped to catch
    one specific regression; see docs/RELEASING.md step 5 for what this job
    does end to end.
    """

    def test_image_job_exists_and_needs_gates(self):
        self.assertIn("\n  image:\n", _read())
        self.assertIn("needs: gates", _image_job_text())

    def test_no_job_level_tag_filter_added(self):
        # the job relies solely on the workflow-level `on: push: tags: [v*]`
        # trigger, exactly like the existing build/release jobs — it must
        # not grow its own `if: startsWith(github.ref, ...)` filter.
        self.assertNotIn("startsWith(github.ref", _image_job_text())

    def test_smoke_precedes_login_and_push(self):
        text = _read()
        smoke_idx = text.index("docker run --rm -d --name linkly-smoke")
        login_idx = text.index("uses: docker/login-action")
        self.assertLess(smoke_idx, login_idx)

    def test_exactly_two_tag_forms_and_no_latest(self):
        job_text = _image_job_text()
        self.assertIn("${image}:${TAG}", job_text)
        self.assertIn("${image}:${xy}", job_text)
        # ":latest" (a tag reference), not the bare word -- `runs-on:
        # ubuntu-latest` legitimately contains "latest" with no colon
        # before it, and must not trip this assertion.
        self.assertNotIn(":latest", job_text)

    def test_pre_release_tag_skips_the_floating_alias(self):
        job_text = _image_job_text()
        self.assertIn('if [[ "$TAG" != *-* ]]; then', job_text)

    def test_release_tag_yields_exactly_the_version_and_the_minor_alias(self):
        self.assertEqual(
            _computed_tags("v1.2.3", "Some-Owner"),
            ["ghcr.io/some-owner/linkly:v1.2.3", "ghcr.io/some-owner/linkly:1.2"],
        )

    def test_pre_release_tag_yields_only_the_version_tag(self):
        self.assertEqual(
            _computed_tags("v1.2.3-rc1", "some-owner"),
            ["ghcr.io/some-owner/linkly:v1.2.3-rc1"],
        )

    def test_two_digit_minor_is_not_truncated_in_the_alias(self):
        self.assertEqual(
            _computed_tags("v0.10.0", "some-owner"),
            ["ghcr.io/some-owner/linkly:v0.10.0", "ghcr.io/some-owner/linkly:0.10"],
        )

    def test_no_untrusted_github_expression_in_run_blocks(self):
        # matches a `run:` value whether it is a single-line command or a
        # `run: |` block, up to the next step's `- name:`/`- uses:` marker —
        # covers both forms this job actually uses.
        job_text = _image_job_text()
        run_values = re.findall(
            r"run: (.*?)(?=\n      - name:|\n      - uses:|\Z)", job_text, re.DOTALL
        )
        self.assertTrue(run_values, "no run: value found to scan")
        for run_value in run_values:
            self.assertNotIn("${{ github.", run_value)

    def test_permissions_are_exactly_contents_read_and_packages_write(self):
        self.assertIn(
            "permissions:\n      contents: read\n      packages: write\n",
            _image_job_text(),
        )
        self.assertNotIn("id-token:", _image_job_text())
        self.assertNotIn("attestations:", _image_job_text())

    def test_publish_pypi_still_disabled(self):
        text = _read()
        start = text.index("\n  publish-pypi:\n")
        self.assertIn("if: false", text[start:])

    def test_dockerfile_path_and_digest_pin_referenced(self):
        self.assertIn("docker/Dockerfile", _image_job_text())
        dockerfile_text = _read_dockerfile()
        self.assertEqual(
            dockerfile_text.count("python:3.13-slim-bookworm@sha256:"), 2
        )

    def test_third_party_actions_are_sha_pinned_with_a_version_comment(self):
        text = _read()
        for action, sha, version in [
            ("docker/setup-buildx-action", "f87e5991a6d7451dcb8d9637bfbc97413f497069", "v4.4.1"),
            ("docker/login-action", "dbcb813823bdd20940b903addbd779551569679f", "v4.6.0"),
            ("docker/build-push-action", "c3c9e263c25d99ce0380d002d59b67737d91b0dc", "v7.4.0"),
        ]:
            self.assertIn("uses: %s@%s # %s" % (action, sha, version), text)

    def test_sbom_and_provenance_attestations_requested(self):
        job_text = _image_job_text()
        self.assertIn("sbom: true", job_text)
        self.assertIn("provenance: true", job_text)


if __name__ == "__main__":
    unittest.main()
