"""A minimal generator used only to prove the `lnpl.generators`
entry-points discovery path works end-to-end (issue #139) — registration
wiring, not generator quality.

Unlike a driver factory (`tests.driver_spi_fixture`'s `module:factory` names
a callable that *builds* the object), a generator entry-point names the
`generate(document, options)` callable directly — the protoc plugin model
has no per-call construction step. `EntryPoint(name="demo",
value="tests.generator_spi_fixture:generate", group="lnpl.generators")` is
the shape `test_generator_spi.py` constructs directly, the same way
`test_driver_spi.py` builds its own `EntryPoint`s rather than installing a
second package (`lnpl-dev-env`'s stdlib-only constraint — this repo is the
only consumer of its own entry-points groups).
"""


def generate(document, options):
    return {"demo.txt": ("module=%s" % document.get("module", "")).encode("utf-8")}


def generate_escaping(document, options):
    """Proves the core writer's path-escape rejection reaches all the way
    through the CLI, not just `run_generator` called directly."""
    return {"../escape.txt": b"x"}


def generate_empty(document, options):
    """Proves an empty map reaches the CLI as rc 0 with nothing written."""
    return {}
