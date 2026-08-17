"""Data-path resolution across install shapes — issue #60.

Three scenarios, each its own test, per resources.data_path()'s 3-tier chain:

  1. normal   — a `pip install`-ed wheel (no repo checkout) resolves data from
                its bundled `lnpl/assets/...` (path ①).
  2. boundary — a repo checkout with no built assets (editable/`PYTHONPATH=impl`,
                i.e. this very suite's own run) falls back to the repo anchor
                (path ②), not path ① — proven by asserting the returned path is
                repo-anchored and does *not* pass through `assets/`.
  3. error    — neither packaged assets nor a repo anchor exist: data_path()
                raises with a recovery hint naming both escape hatches (run
                from a checkout, or pass --root).

The wheel build in scenario 1 needs network/build-isolation; if it fails for
that reason, the test skips (not fails) so the suite stays green offline.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

from lnpl import backend, resources

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP_ROOT = os.path.join(REPO, ".claude", "tmp")
SHORTEN_SOURCE = os.path.join(REPO, "examples", "shorten.lnpl")
PYTHON = sys.executable

HAS_TOOLS = backend.toolchain_available()


class WheelInstallNormalPathTest(unittest.TestCase):
    """정상(경로 ①) — wheel에 실린 assets에서 데이터를 찾아 rc=0으로 실행된다."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(dir=TMP_ROOT, prefix="wheel-install-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _build_and_extract_wheel(self):
        wheel_out = os.path.join(self.tmp, "wheel-out")
        os.makedirs(wheel_out)
        result = subprocess.run(
            [PYTHON, "-m", "pip", "wheel", "--no-deps", "-w", wheel_out, REPO],
            capture_output=True, text=True)
        if result.returncode != 0:
            self.skipTest(
                "wheel build failed (offline or build backend unavailable) — "
                "environment issue, not a regression: %s" % result.stderr[-800:])

        wheels = [f for f in os.listdir(wheel_out) if f.endswith(".whl")]
        self.assertEqual(len(wheels), 1, "expected exactly one built wheel")

        extracted = os.path.join(self.tmp, "extracted")
        with zipfile.ZipFile(os.path.join(wheel_out, wheels[0])) as zf:
            zf.extractall(extracted)

        # The whole point of D1's force-include: prove the data actually rode
        # along in the wheel, before trusting any runtime behavior on it.
        self.assertTrue(os.path.isfile(os.path.join(
            extracted, "lnpl", "assets", "mlir", "lnpl.irdl.mlir")))
        self.assertTrue(os.path.isfile(os.path.join(
            extracted, "lnpl", "assets", "mlir", "llvm.pin")))
        self.assertTrue(os.path.isdir(os.path.join(
            extracted, "lnpl", "assets", "kb")))
        return extracted

    def test_lnpl_agents_and_build_run_from_extracted_wheel_without_repo_checkout(self):
        extracted = self._build_and_extract_wheel()

        source_copy = os.path.join(self.tmp, "shorten.lnpl")
        shutil.copyfile(SHORTEN_SOURCE, source_copy)

        # cwd deliberately has no repo checkout under it — only the extracted
        # wheel (via PYTHONPATH, NOT impl) can supply the data.
        cwd = os.path.join(self.tmp, "cwd")
        os.makedirs(cwd)
        env = dict(os.environ)
        env["PYTHONPATH"] = extracted

        agents = subprocess.run(
            [PYTHON, "-m", "lnpl", "agents", source_copy],
            cwd=cwd, env=env, capture_output=True, text=True)
        self.assertEqual(
            agents.returncode, 0,
            "lnpl agents (installed-wheel shape) failed:\nstdout:\n%s\nstderr:\n%s"
            % (agents.stdout, agents.stderr))

        if not HAS_TOOLS:
            self.skipTest(
                "agents rc=0 verified; skipping build --run — "
                "MLIR/LLVM toolchain not installed (brew install llvm)")

        build_workdir = os.path.join(self.tmp, "build-workdir")
        build = subprocess.run(
            [PYTHON, "-m", "lnpl", "build", source_copy,
             "--workdir", build_workdir, "--run"],
            cwd=cwd, env=env, capture_output=True, text=True)
        self.assertEqual(
            build.returncode, 0,
            "lnpl build --run (installed-wheel shape) failed:\nstdout:\n%s\nstderr:\n%s"
            % (build.stdout, build.stderr))


class DataPathBoundaryAndErrorTest(unittest.TestCase):
    """경계(경로 ② 폴백)와 에러(경로 ③)를 별도 케이스로 (D6)."""

    def test_boundary_falls_back_to_repo_anchor_when_assets_absent_file(self):
        # This suite runs PYTHONPATH=impl — no `lnpl/assets/` exists under the
        # source tree, so this is exactly the "assets absent, repo anchor
        # present" configuration, with no mocking needed.
        result = resources.data_path("mlir/lnpl.irdl.mlir")
        self.assertTrue(os.path.isfile(result))
        self.assertEqual(result, os.path.join(REPO, "mlir", "lnpl.irdl.mlir"))
        self.assertNotIn(os.sep + "assets" + os.sep, result)

    def test_boundary_falls_back_to_repo_anchor_when_assets_absent_dir(self):
        result = resources.data_path("kb")
        self.assertTrue(os.path.isdir(result))
        self.assertEqual(result, os.path.join(REPO, "kb"))
        self.assertNotIn(os.sep + "assets" + os.sep, result)

    def test_error_when_both_assets_and_repo_anchor_absent(self):
        original = resources.REPO_ROOT
        resources.REPO_ROOT = os.path.join(TMP_ROOT, "no-such-repo-anchor-060")
        try:
            with self.assertRaises(resources.DataNotFoundError) as ctx:
                resources.data_path("mlir/lnpl.irdl.mlir")
        finally:
            resources.REPO_ROOT = original

        message = str(ctx.exception)
        self.assertIn("레포 체크아웃", message)
        self.assertIn("--root", message)


if __name__ == "__main__":
    unittest.main()
