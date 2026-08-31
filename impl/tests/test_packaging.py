"""pyproject.toml이 `lnpl` 콘솔 스크립트를 올바르게 선언하는지 검사한다.

실제 설치를 여기서 하지는 않는다(느리고 네트워크를 탄다). 대신 선언이
정확한지와, 그 선언이 가리키는 대상이 실제로 호출 가능한지를 본다.
"""
import pathlib
import tomllib
import unittest

import lnpl

ROOT = pathlib.Path(__file__).resolve().parents[2]


class PyprojectTest(unittest.TestCase):
    def setUp(self):
        path = ROOT / "pyproject.toml"
        self.assertTrue(path.is_file(), "pyproject.toml이 레포 루트에 없다")
        with open(path, "rb") as fh:
            self.cfg = tomllib.load(fh)

    def test_console_script_points_at_cli_main(self):
        scripts = self.cfg["project"]["scripts"]
        self.assertEqual(scripts["lnpl"], "lnpl.cli:main")

    def test_entry_point_target_is_callable(self):
        from lnpl.cli import main
        self.assertTrue(callable(main))

    def test_package_dir_is_impl(self):
        tool = self.cfg["tool"]["hatch"]["build"]["targets"]["wheel"]
        self.assertEqual(tool["packages"], ["impl/lnpl"])

    def test_version_matches_package_dunder(self):
        self.assertEqual(self.cfg["project"]["version"], lnpl.__version__)

    def test_requires_python_floor_declared(self):
        self.assertEqual(self.cfg["project"]["requires-python"], ">=3.11")

    def test_runtime_dependency_set_is_exactly_jsonschema(self):
        # 의존을 늘리지 않는다는 제약을 테스트로 고정한다.
        deps = self.cfg["project"]["dependencies"]
        self.assertEqual([d.split(">")[0].split("=")[0].strip() for d in deps],
                         ["jsonschema"])


if __name__ == "__main__":
    unittest.main()
