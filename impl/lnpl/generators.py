"""Generator SPI — external code-generation targets over the Semantic IR
(issue #139). The IR is the hub `README.md` claims it to be only if what
consumes it isn't hard-wired into the core, the way `openapi.py` used to be
(CHARTER §Auto Generation lists 15 targets; a core that hand-writes all of
them is a core that is wrong for every organization but the one it guessed).

protoc plugin model: a generator is `generate(document, options) ->
{relative_path: bytes}` — a map, not a file write. The writer that turns that
map into real files under `--out` lives here, in one place, so a generator
never gets filesystem access itself: no `--dry-run`/overwrite/path-escape
policy to re-implement per generator (the same reason protoc's own
`CodeGeneratorResponse` is a map rather than letting a plugin write files).

Discipline mirrors `drivers.py`'s `open_repository` (issue #75): a built-in
name is matched first and can never be shadowed by an entry-point of the same
name; an unregistered name states itself, the built-in set, and the
registered set rather than resolving to something plausible; every failure —
an unregistered name, a failed entry-point load, or an exception out of the
generator's own `generate()` — leaves as the single `GeneratorError`
(`docs/backends.md` §12 has the registration shape).
"""

import os
from importlib import metadata as importlib_metadata

from . import openapi as _openapi


class GeneratorError(Exception):
    """The one error type every generator SPI failure leaves as — an
    unregistered name, a failed entry-point load, an exception raised by the
    generator itself, or a returned path that escapes `--out`."""


# issue #139: the entry-points group an external package registers a
# `generate(document, options)` callable under (`[project.entry-points.
# "lnpl.generators"]` in its own pyproject.toml — `docs/backends.md` §12 has
# the example, `lnpl.drivers` §8 mirrored). The built-in name (below) is
# matched before this group is ever consulted, so a registered entry-point
# can never shadow it.
GENERATORS_ENTRY_POINT_GROUP = "lnpl.generators"

# The closed table of built-in generator names `lnpl generate <name>` accepts
# without an entry-point lookup — `drivers.py`'s `BACKENDS` /
# `BUILTIN_TOKEN_PROVIDERS` mirrored.
BUILTIN_GENERATORS = ("openapi",)


def _generator_entry_points():
    """Every entry-point registered under `lnpl.generators` — same stdlib
    API version split `drivers._driver_entry_points()` already handles: 3.10+
    takes `group=` as a select filter; 3.9's `entry_points()` takes none and
    returns a `{group: [EntryPoint, ...]}` dict instead."""
    try:
        return importlib_metadata.entry_points(group=GENERATORS_ENTRY_POINT_GROUP)
    except TypeError:
        return importlib_metadata.entry_points().get(
            GENERATORS_ENTRY_POINT_GROUP, [])


def resolve_generator(name):
    """`<name>` -> a `generate(document, options)` callable, or raise
    `GeneratorError`. The built-in `openapi` generator always wins over an
    entry-point of the same name."""
    if name == "openapi":
        return _openapi.generate_files
    for entry_point in _generator_entry_points():
        if entry_point.name == name:
            try:
                return entry_point.load()
            except Exception as exc:
                raise GeneratorError(
                    "generator %r registered via entry-point %r failed to "
                    "load: %s" % (name, entry_point.value, exc)) from exc
    raise GeneratorError(
        "unknown generator %r (built-in: %s; registered entry-points: %s)"
        % (name, ", ".join(BUILTIN_GENERATORS),
           ", ".join(sorted(ep.name for ep in _generator_entry_points()))
           or "none"))


def run_generator(generator, document, options, out_dir):
    """Call `generator(document, options)`, translate any exception it
    raises into `GeneratorError`, then write the returned `{relative_path:
    bytes}` map under `out_dir`.

    Every key is validated — rejecting an empty or absolute path, or one
    that resolves outside `out_dir` (`..`, or a symlink hop) — before
    anything is written, so one escaping key leaves `out_dir` untouched
    rather than partially written. `out_dir` itself must be non-empty: an
    empty string is a `--out` value argparse accepts as "present" but
    `os.path.realpath("")` resolves to the current directory, which would
    silently defeat the whole reason `--out` is required (cwd scatter
    prevention, `docs/backends.md` §12). Returns the sorted list of relative
    paths written (`[]` for an empty map).
    """
    try:
        result = generator(document, options)
    except GeneratorError:
        raise
    except Exception as exc:
        raise GeneratorError(
            "generator raised %s: %s" % (type(exc).__name__, exc)) from exc

    if not out_dir:
        raise GeneratorError(
            "--out must be a non-empty directory path, got %r" % out_dir)

    out_root = os.path.realpath(out_dir)
    destinations = {}
    for relpath in result:
        if not relpath or os.path.isabs(relpath):
            raise GeneratorError(
                "generator output key %r is not a valid relative path" % relpath)
        dest = os.path.realpath(os.path.join(out_root, relpath))
        if dest != out_root and os.path.commonpath([dest, out_root]) != out_root:
            raise GeneratorError(
                "generator output key %r escapes --out %r" % (relpath, out_dir))
        destinations[relpath] = dest

    for relpath, dest in destinations.items():
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(result[relpath])
    return sorted(destinations)
