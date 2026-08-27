"""`lnpl.toml` — non-secret configuration file with a shallow profile overlay
(issue #114).

Only `backend`/`log_format`/`trace_exporter` (scalars) and the `endpoints`/
`secrets` tables are recognized, matching the CLI/env-var surface `cli.py`
already has (`--backend`/`--log-format`/`--trace-exporter`/`--endpoint`/
`--jwt-secret-env`). `[<profile>]` overlays `[default]` one level deep, key
by key — no include, inheritance, or `${VAR:-default}` fallback syntax (D2/D5
in the t114 plan): every value this module resolves must be traceable to one
line in one file.

`[*.secrets]` values are never the secret itself — issue #101's discipline —
only the NAME of an environment variable that holds it, checked against
`_ENV_NAME_RE` before anything else touches it. `${VAR}` substitution inside
ordinary scalar/endpoint strings reads `os.environ` directly and never the
`[*.secrets]` table, so a value can never smuggle a secret through the file
by way of a placeholder.

A missing `lnpl.toml` (the default path, not an explicit `--config`) resolves
to an all-`None`/empty `ResolvedConfig` — every existing flag/env-var-driven
call site stays byte-identical to its pre-#114 behavior (regression, per the
task's `definition_of_done`).
"""

import dataclasses
import os
import re

from .serve import WsgiConfigError

DEFAULT_FILENAME = "lnpl.toml"

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_ENV_NAME_LEN = 64
_VAR_REF_RE = re.compile(r"\$\{([^}]*)\}")

_SCALAR_KEYS = ("backend", "log_format", "trace_exporter")
_SECTION_KEYS = ("endpoints", "secrets")


@dataclasses.dataclass(frozen=True)
class ResolvedConfig:
    """The merged `[default]`+`[<profile>]` view `cli.py` layers CLI flags
    and environment variables on top of. `None` on a scalar means "the file
    said nothing" — the caller's own built-in default applies, the same way
    an omitted CLI flag already does."""

    backend: object = None
    log_format: object = None
    trace_exporter: object = None
    endpoints: dict = dataclasses.field(default_factory=dict)
    secrets: dict = dataclasses.field(default_factory=dict)


def _substitute(value, path):
    """`${VAR}` -> `os.environ[VAR]` for a bare name only — no `${VAR:-def}`
    fallback syntax, so a value can never carry a default that hides a
    missing environment variable (D5)."""

    def repl(match):
        name = match.group(1)
        if not _ENV_NAME_RE.match(name) or len(name) > _MAX_ENV_NAME_LEN:
            raise WsgiConfigError(
                "%s: %r is not a bare ${VAR_NAME} reference — "
                "default-value syntax like ${VAR:-default} is not supported"
                % (path, match.group(0)))
        resolved = os.environ.get(name)
        if resolved is None:
            raise WsgiConfigError(
                "%s references ${%s}, which is not set in the environment"
                % (path, name))
        return resolved

    return _VAR_REF_RE.sub(repl, value)


def _validate_secret_name(value, path):
    """Issue #101 discipline, enforced at load time: a `[*.secrets]` value
    must be shaped like an environment variable NAME, never the secret
    itself — a URL, a token, or anything containing `://` or whitespace is
    rejected before it is ever read."""
    if not _ENV_NAME_RE.match(value) or len(value) > _MAX_ENV_NAME_LEN:
        raise WsgiConfigError(
            "%s looks like a value, not an ENV name — only a bare "
            "environment variable name (e.g. MY_SECRET) is allowed here, "
            "the secret's own value never belongs in lnpl.toml: %r"
            % (path, value))


def _load_table(display_path, name, table):
    """One `[default]` or `[<profile>]` table -> (scalars, endpoints,
    secrets) dicts, each entry substituted/validated and tagged with its own
    `display_path.name.key` for every error this can raise."""
    if not isinstance(table, dict):
        raise WsgiConfigError(
            "%s: [%s] must be a table" % (display_path, name))
    unknown = set(table) - set(_SCALAR_KEYS) - set(_SECTION_KEYS)
    if unknown:
        raise WsgiConfigError(
            "%s: [%s] has unknown key(s) %s — allowed: %s"
            % (display_path, name, ", ".join(sorted(unknown)),
               ", ".join(_SCALAR_KEYS + _SECTION_KEYS)))

    scalars = {}
    for key in _SCALAR_KEYS:
        if key not in table:
            continue
        value = table[key]
        path = "%s: %s.%s" % (display_path, name, key)
        if not isinstance(value, str):
            raise WsgiConfigError(
                "%s must be a string, got %s" % (path, type(value).__name__))
        scalars[key] = _substitute(value, path)

    endpoints = {}
    raw_endpoints = table.get("endpoints", {})
    if not isinstance(raw_endpoints, dict):
        raise WsgiConfigError(
            "%s: [%s.endpoints] must be a table" % (display_path, name))
    for key, value in raw_endpoints.items():
        path = "%s: %s.endpoints.%s" % (display_path, name, key)
        if not isinstance(value, str):
            raise WsgiConfigError(
                "%s must be a string, got %s" % (path, type(value).__name__))
        endpoints[key] = _substitute(value, path)

    secrets = {}
    raw_secrets = table.get("secrets", {})
    if not isinstance(raw_secrets, dict):
        raise WsgiConfigError(
            "%s: [%s.secrets] must be a table" % (display_path, name))
    for key, value in raw_secrets.items():
        path = "%s: %s.secrets.%s" % (display_path, name, key)
        if not isinstance(value, str):
            raise WsgiConfigError(
                "%s must be a string (an environment variable NAME), got %s"
                % (path, type(value).__name__))
        _validate_secret_name(value, path)
        secrets[key] = value

    return scalars, endpoints, secrets


def load_config(path=None, profile=None):
    """`lnpl.toml` (or `path`) -> a `ResolvedConfig` for `profile` (default:
    the `LNPL_PROFILE` environment variable, else `[default]` alone).

    `path is None` (no `--config`) and the default filename does not exist
    in the current directory returns an all-empty `ResolvedConfig()` —
    introducing this file changes nothing for a project that does not have
    one (regression requirement). An explicit `path` that does not exist is
    an error: naming a file that is not there is an operator mistake, not
    "no file".

    Raises `WsgiConfigError` (rc 2 convention, D9) for: a TOML syntax error;
    a top-level key that is not a table; an unknown scalar/section key; a
    `[*.secrets]` value that is not an ENV name; a `${VAR}` reference to an
    unset variable or one using unsupported `${VAR:-default}` syntax; or a
    `--profile`/`LNPL_PROFILE` naming a table that is not in the file.
    """
    explicit_path = path is not None
    if path is None:
        path = DEFAULT_FILENAME
    if not os.path.exists(path):
        if explicit_path:
            raise WsgiConfigError("--config %r: no such file" % path)
        return ResolvedConfig()

    # Imported here, not at module level: `tomllib` is stdlib-only from
    # Python 3.11 (this project supports >=3.9, `pyproject.toml`), and
    # `cli.py` imports this module unconditionally at its own top level —
    # a module-level `import tomllib` would break `python -m lnpl` under
    # the walk-up-failed module-fallback path (`lnpl-diagnostics.sh` step
    # 5) on any interpreter below 3.11, even when no `lnpl.toml` is ever
    # read.
    import tomllib

    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise WsgiConfigError("%s: %s" % (path, exc)) from exc

    for key, value in data.items():
        if not isinstance(value, dict):
            raise WsgiConfigError(
                "%s: top-level key %r must be a table ([%s]) — lnpl.toml "
                "only defines profiles at the top level" % (path, key, key))

    if profile is None:
        profile = os.environ.get("LNPL_PROFILE")

    scalars, endpoints, secrets = _load_table(path, "default", data.get("default", {}))

    if profile is not None and profile != "default":
        if profile not in data:
            available = sorted(set(data) | {"default"})
            raise WsgiConfigError(
                "%s: profile %r not found — available profiles: %s"
                % (path, profile, ", ".join(available)))
        p_scalars, p_endpoints, p_secrets = _load_table(path, profile, data[profile])
        scalars.update(p_scalars)
        endpoints.update(p_endpoints)
        secrets.update(p_secrets)

    return ResolvedConfig(
        backend=scalars.get("backend"),
        log_format=scalars.get("log_format"),
        trace_exporter=scalars.get("trace_exporter"),
        endpoints=endpoints,
        secrets=secrets,
    )
