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
import sys
import tempfile
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


def _job_text(text, job):
    """`job`'s own text: from its two-space `<job>:` key line to the next
    two-space job key, or to end of file when it is the last job (issue
    #245). Two-space comment lines never match the job-key pattern.
    """
    start = text.index("\n  %s:\n" % job)
    nxt = re.search(r"\n  [A-Za-z0-9_-]+:\n", text[start + 1:])
    if nxt is None:
        return text[start:]
    return text[start:start + 1 + nxt.start()]


def _publish_wiring_problems(job_text):
    """Every way `job_text` differs from the enabled publish-pypi wiring
    (issue #245), as fixed strings in a fixed order. Exact four-space
    indents: a key moved under a step (eight spaces) does not count.
    """
    problems = []
    if "\n    if:" in job_text:
        problems.append("job-level if present")
    if "\n    environment: pypi\n" not in job_text:
        problems.append("environment is not pypi")
    if "\n    needs: [build, release]\n" not in job_text:
        problems.append("needs is not [build, release]")
    if re.search(r"\n    permissions:\n      id-token: write[^\n]*\n    [a-z]", job_text) is None:
        problems.append("permissions is not exactly id-token: write")
    if re.search(r"uses: pypa/gh-action-pypi-publish@[0-9a-f]{40} # v\d+\.\d+\.\d+$",
                 job_text, re.M) is None:
        problems.append("publish action is not SHA-pinned")
    if "skip-existing" in job_text:
        problems.append("skip-existing is set")
    return problems


def _tag_guard_script():
    """The `gates` job's tag/version guard step script, dedented the way
    `_computed_tags` dedents the image job's script (issue #245).
    """
    job_text = _job_text(_read(), "gates")
    marker = ("      - name: Tag matches the pyproject version (issue #245)\n"
              "        run: |\n")
    start = job_text.index(marker) + len(marker)
    end = job_text.index("\n\n      - ", start)
    return "\n".join(line[10:] for line in job_text[start:end].split("\n")) + "\n"


def _run_tag_guard(tag, version):
    """Run the guard step under `bash -e` (the runner's command for a step
    without `shell:`) next to a synthetic pyproject.toml; return (rc, stdout).
    """
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "pyproject.toml"), "w", encoding="utf-8") as fh:
            fh.write('[project]\nname = "lnpl"\nversion = "%s"\n' % version)
        with open(os.path.join(tmp, "step.sh"), "w", encoding="utf-8") as fh:
            fh.write(_tag_guard_script())
        proc = subprocess.run(
            ["bash", "-e", "step.sh"], cwd=tmp,
            env={"PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"],
                 "GITHUB_REF_NAME": tag},
            capture_output=True, text=True,
        )
    return proc.returncode, proc.stdout


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


PIN_LINE = ("uses: pypa/gh-action-pypi-publish@"
            "7245906fb61fa33a13554f9d5fb856fe61758086 # v1.14.3")


def _publish_job():
    return _job_text(_read(), "publish-pypi")


class PublishPypiWiringTest(unittest.TestCase):
    """issue #245: publish-pypi is enabled behind `environment: pypi`,
    runs only after build and release, holds only `id-token: write`, and
    uses a SHA-pinned publish action without `skip-existing`.
    """

    def _mutant(self, old, new):
        job = _publish_job()
        self.assertIn(old, job)
        return job.replace(old, new, 1)

    def test_real_publish_job_has_no_wiring_problems(self):
        self.assertEqual(_publish_wiring_problems(_publish_job()), [])

    def test_publish_step_is_pinned_to_the_v1_14_3_commit(self):
        job = _publish_job()
        self.assertIn(PIN_LINE, job)
        self.assertNotIn("@release/v1", job)

    def test_dist_is_downloaded_before_publishing_under_the_enabled_name(self):
        job = _publish_job()
        self.assertLess(job.index("uses: actions/download-artifact@"),
                        job.index("uses: pypa/gh-action-pypi-publish@"))
        self.assertIn("\n    name: Publish to PyPI (Trusted Publishing)\n", job)

    def test_reintroduced_if_false_is_reported(self):
        mutant = self._mutant("  publish-pypi:\n", "  publish-pypi:\n    if: false\n")
        self.assertEqual(_publish_wiring_problems(mutant), ["job-level if present"])

    def test_missing_environment_is_reported(self):
        mutant = self._mutant("    environment: pypi\n", "")
        self.assertEqual(_publish_wiring_problems(mutant), ["environment is not pypi"])

    def test_environment_moved_under_a_step_is_reported(self):
        mutant = self._mutant("    environment: pypi\n", "")
        self.assertIn(PIN_LINE + "\n", mutant)
        mutant = mutant.replace(PIN_LINE + "\n", PIN_LINE + "\n        environment: pypi\n")
        self.assertEqual(_publish_wiring_problems(mutant), ["environment is not pypi"])

    def test_needs_without_release_is_reported(self):
        mutant = self._mutant("needs: [build, release]", "needs: build")
        self.assertEqual(_publish_wiring_problems(mutant), ["needs is not [build, release]"])

    def test_extra_permission_and_floating_ref_are_reported(self):
        mutant = self._mutant(
            "      id-token: write  # required for PyPI Trusted Publishing (OIDC)\n",
            "      id-token: write  # required for PyPI Trusted Publishing (OIDC)\n"
            "      contents: write\n")
        self.assertIn(PIN_LINE, mutant)
        mutant = mutant.replace(PIN_LINE, "uses: pypa/gh-action-pypi-publish@release/v1")
        self.assertEqual(_publish_wiring_problems(mutant),
                         ["permissions is not exactly id-token: write",
                          "publish action is not SHA-pinned"])

    def test_skip_existing_is_reported(self):
        mutant = self._mutant(PIN_LINE + "\n",
                              PIN_LINE + "\n        with:\n          skip-existing: true\n")
        self.assertEqual(_publish_wiring_problems(mutant), ["skip-existing is set"])

    def test_last_job_slice_runs_to_end_of_file_and_stops_at_a_following_job(self):
        text = _read()
        job = _job_text(text, "publish-pypi")
        self.assertEqual(job, text[text.index("\n  publish-pypi:\n"):])
        self.assertEqual(_job_text(job + "\n  later:\n    runs-on: x\n", "publish-pypi"), job)

    def test_empty_job_body_reports_the_four_missing_keys(self):
        self.assertEqual(_publish_wiring_problems("\n  publish-pypi:\n"),
                         ["environment is not pypi",
                          "needs is not [build, release]",
                          "permissions is not exactly id-token: write",
                          "publish action is not SHA-pinned"])


class TagVersionGuardTest(unittest.TestCase):
    """issue #245: `gates` fails when the pushed tag (minus a leading `v`)
    differs from pyproject.toml's [project] version, so build, release and
    publish-pypi never run for a mismatched tag.
    """

    def test_matching_tag_passes(self):
        rc, out = _run_tag_guard("v0.9.0", "0.9.0")
        self.assertEqual(rc, 0)
        self.assertIn("tag v0.9.0 matches pyproject.toml version 0.9.0", out)

    def test_tag_on_a_later_dev_commit_fails(self):
        rc, out = _run_tag_guard("v0.9.0", "0.9.1.dev0")
        self.assertEqual(rc, 1)
        self.assertIn("::error::tag v0.9.0 does not match pyproject.toml version 0.9.1.dev0", out)

    def test_pre_release_suffix_is_not_trimmed(self):
        rc, out = _run_tag_guard("v0.9.0-rc1", "0.9.0")
        self.assertEqual(rc, 1)
        self.assertIn("::error::tag v0.9.0-rc1 does not match pyproject.toml version 0.9.0", out)

    def test_empty_tag_fails(self):
        rc, out = _run_tag_guard("", "0.9.0")
        self.assertEqual(rc, 1)
        self.assertIn("::error::tag  does not match pyproject.toml version 0.9.0", out)
        script = _tag_guard_script()
        self.assertIn("GITHUB_REF_NAME", script)
        self.assertNotIn("${{", script)


if __name__ == "__main__":
    unittest.main()
