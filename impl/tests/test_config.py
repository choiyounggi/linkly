"""`lnpl.toml` 로더 + 프로파일 오버레이 (issue #114).

파일이 없으면 기존 동작과 바이트 동일해야 한다는 회귀 요구사항, `[*.secrets]`가
ENV 이름 형식만 허용한다는 issue #101 규율, `${VAR}` 치환이 순수 ENV 참조로만
한정된다는 D5를 각각 정상/에러/경계 케이스로 고정한다.
"""

import os
import shutil
import tempfile
import unittest

from lnpl.config import ResolvedConfig, load_config
from lnpl.serve import WsgiConfigError

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLAUDE_TMP = os.path.join(REPO, ".claude", "tmp")


def _write(dirpath, name, content):
    path = os.path.join(dirpath, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        os.makedirs(CLAUDE_TMP, exist_ok=True)
        self._tmp = tempfile.TemporaryDirectory(dir=CLAUDE_TMP)
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name
        self._env_backup = dict(os.environ)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self._env_backup)


class NoFileRegressionTest(ConfigTestCase):
    """DoD: 파일이 없으면 현행 동작 그대로 — 회귀 방지."""

    def test_missing_default_path_returns_empty_config(self):
        cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, cwd)
        self.assertFalse(os.path.exists("lnpl.toml"))
        cfg = load_config()
        self.assertEqual(cfg, ResolvedConfig())
        self.assertIsNone(cfg.backend)
        self.assertIsNone(cfg.log_format)
        self.assertIsNone(cfg.trace_exporter)
        self.assertEqual(cfg.endpoints, {})
        self.assertEqual(cfg.secrets, {})

    def test_explicit_config_path_missing_is_an_error(self):
        missing = os.path.join(self.dir, "nope.toml")
        with self.assertRaises(WsgiConfigError) as ctx:
            load_config(path=missing)
        self.assertIn("no such file", str(ctx.exception))


class EmptyFileTest(ConfigTestCase):
    def test_empty_file_resolves_to_empty_config(self):
        path = _write(self.dir, "lnpl.toml", "")
        cfg = load_config(path=path)
        self.assertEqual(cfg, ResolvedConfig())

    def test_empty_secrets_table_is_not_an_error(self):
        path = _write(self.dir, "lnpl.toml", "[default.secrets]\n")
        cfg = load_config(path=path)
        self.assertEqual(cfg.secrets, {})


class DefaultOnlyTest(ConfigTestCase):
    def test_scalars_and_sections_load_from_default_alone(self):
        path = _write(self.dir, "lnpl.toml", """
[default]
backend = "sqlite:./app.db"
log_format = "json"
trace_exporter = "stderr-json"

[default.endpoints]
payments = "https://api.example.com/pay"

[default.secrets]
jwt = "LNPL_JWT_SECRET"
""")
        cfg = load_config(path=path)
        self.assertEqual(cfg.backend, "sqlite:./app.db")
        self.assertEqual(cfg.log_format, "json")
        self.assertEqual(cfg.trace_exporter, "stderr-json")
        self.assertEqual(cfg.endpoints, {"payments": "https://api.example.com/pay"})
        self.assertEqual(cfg.secrets, {"jwt": "LNPL_JWT_SECRET"})


class ProfileOverlayTest(ConfigTestCase):
    """D2: `[<profile>]`는 `[default]` 위에 키 단위로만 얕게 얹힌다."""

    TOML = """
[default]
backend = "fake"
log_format = "text"

[default.endpoints]
payments = "https://default.example.com/pay"
inventory = "https://default.example.com/inv"

[default.secrets]
jwt = "LNPL_JWT_SECRET"

[staging]
backend = "sqlite:./staging.db"

[staging.endpoints]
payments = "https://staging.example.com/pay"

[staging.secrets]
jwt = "STAGING_JWT_SECRET"
"""

    def _load(self, profile=None, env_profile=None):
        path = _write(self.dir, "lnpl.toml", self.TOML)
        if env_profile is not None:
            os.environ["LNPL_PROFILE"] = env_profile
        return load_config(path=path, profile=profile)

    def test_unselected_profile_is_default_only(self):
        cfg = self._load()
        self.assertEqual(cfg.backend, "fake")
        self.assertEqual(cfg.endpoints, {
            "payments": "https://default.example.com/pay",
            "inventory": "https://default.example.com/inv",
        })
        self.assertEqual(cfg.secrets, {"jwt": "LNPL_JWT_SECRET"})

    def test_profile_overrides_scalar_key(self):
        cfg = self._load(profile="staging")
        self.assertEqual(cfg.backend, "sqlite:./staging.db")
        # 프로파일이 건드리지 않은 스칼라는 default에서 그대로 내려온다.
        self.assertEqual(cfg.log_format, "text")

    def test_profile_overlay_is_key_by_key_not_section_wide(self):
        cfg = self._load(profile="staging")
        # staging.endpoints는 payments만 덮는다 — inventory는 default에서 유지.
        self.assertEqual(cfg.endpoints, {
            "payments": "https://staging.example.com/pay",
            "inventory": "https://default.example.com/inv",
        })
        self.assertEqual(cfg.secrets, {"jwt": "STAGING_JWT_SECRET"})

    def test_explicit_profile_flag_wins_over_env_var(self):
        cfg = self._load(profile="staging", env_profile="default")
        self.assertEqual(cfg.backend, "sqlite:./staging.db")

    def test_env_var_selects_profile_when_flag_omitted(self):
        cfg = self._load(profile=None, env_profile="staging")
        self.assertEqual(cfg.backend, "sqlite:./staging.db")

    def test_unknown_profile_is_rejected_with_available_list(self):
        path = _write(self.dir, "lnpl.toml", self.TOML)
        with self.assertRaises(WsgiConfigError) as ctx:
            load_config(path=path, profile="production")
        message = str(ctx.exception)
        self.assertIn("production", message)
        self.assertIn("staging", message)
        self.assertIn("default", message)


class SecretsFormatTest(ConfigTestCase):
    """D4: `[*.secrets]` 값은 ENV 이름 형식만 — 값 유입을 막는다."""

    def test_url_shaped_secret_value_is_rejected(self):
        path = _write(self.dir, "lnpl.toml", """
[default.secrets]
jwt = "https://leaked-secret.example.com/token"
""")
        with self.assertRaises(WsgiConfigError) as ctx:
            load_config(path=path)
        self.assertIn("default.secrets.jwt", str(ctx.exception))

    def test_secret_value_with_whitespace_is_rejected(self):
        path = _write(self.dir, "lnpl.toml", """
[default.secrets]
jwt = "not an env name"
""")
        with self.assertRaises(WsgiConfigError):
            load_config(path=path)

    def test_secret_name_over_length_limit_is_rejected(self):
        path = _write(self.dir, "lnpl.toml", '[default.secrets]\njwt = "%s"\n' % ("A" * 65))
        with self.assertRaises(WsgiConfigError):
            load_config(path=path)

    def test_well_formed_env_name_is_accepted(self):
        path = _write(self.dir, "lnpl.toml", """
[default.secrets]
jwt = "MY_APP_JWT_SECRET_1"
""")
        cfg = load_config(path=path)
        self.assertEqual(cfg.secrets, {"jwt": "MY_APP_JWT_SECRET_1"})


class VarSubstitutionTest(ConfigTestCase):
    """D5: `${VAR}`는 순수 ENV 참조만 — 기본값 문법 없음."""

    def test_defined_var_is_substituted(self):
        os.environ["LNPL_T114_DB_PATH"] = "/var/lib/app.db"
        path = _write(self.dir, "lnpl.toml", """
[default]
backend = "sqlite:${LNPL_T114_DB_PATH}"
""")
        cfg = load_config(path=path)
        self.assertEqual(cfg.backend, "sqlite:/var/lib/app.db")

    def test_undefined_var_is_rejected_with_key_path(self):
        os.environ.pop("LNPL_T114_UNSET_VAR", None)
        path = _write(self.dir, "lnpl.toml", """
[default]
backend = "sqlite:${LNPL_T114_UNSET_VAR}"
""")
        with self.assertRaises(WsgiConfigError) as ctx:
            load_config(path=path)
        message = str(ctx.exception)
        self.assertIn("default.backend", message)
        self.assertIn("LNPL_T114_UNSET_VAR", message)

    def test_default_value_syntax_is_rejected(self):
        path = _write(self.dir, "lnpl.toml", """
[default]
backend = "sqlite:${LNPL_T114_UNSET_VAR:-fallback.db}"
""")
        with self.assertRaises(WsgiConfigError) as ctx:
            load_config(path=path)
        self.assertIn("default-value syntax", str(ctx.exception))

    def test_substitution_does_not_apply_inside_secrets(self):
        # secrets는 ENV 이름 형식 검증만 받는다 — `${...}`가 문자 그대로 있으면
        # 애초에 이름 정규식에 맞지 않아 거부된다(치환 구멍이 없다는 뜻).
        os.environ["LNPL_T114_JWT_NAME"] = "REAL_SECRET_ENV"
        path = _write(self.dir, "lnpl.toml", """
[default.secrets]
jwt = "${LNPL_T114_JWT_NAME}"
""")
        with self.assertRaises(WsgiConfigError):
            load_config(path=path)


class MalformedFileTest(ConfigTestCase):
    def test_toml_syntax_error_is_rejected(self):
        path = _write(self.dir, "lnpl.toml", "[default\nbackend = fake")
        with self.assertRaises(WsgiConfigError):
            load_config(path=path)

    def test_non_table_top_level_key_is_rejected(self):
        path = _write(self.dir, "lnpl.toml", 'stray = "value"\n')
        with self.assertRaises(WsgiConfigError) as ctx:
            load_config(path=path)
        self.assertIn("stray", str(ctx.exception))

    def test_unknown_key_in_default_is_rejected(self):
        path = _write(self.dir, "lnpl.toml", '[default]\nnetwork = "http"\n')
        with self.assertRaises(WsgiConfigError) as ctx:
            load_config(path=path)
        self.assertIn("network", str(ctx.exception))

    def test_non_string_scalar_is_rejected(self):
        path = _write(self.dir, "lnpl.toml", "[default]\nbackend = 5\n")
        with self.assertRaises(WsgiConfigError):
            load_config(path=path)

    def test_endpoints_section_must_be_a_table(self):
        path = _write(self.dir, "lnpl.toml", '[default]\nendpoints = "nope"\n')
        with self.assertRaises(WsgiConfigError):
            load_config(path=path)


if __name__ == "__main__":
    unittest.main()
