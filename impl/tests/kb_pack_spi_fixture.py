"""Zero-arg pack-root factories used only to prove the `lnpl.kb` entry-points
discovery path resolves end-to-end (issue #137) — registration wiring, not
pack content. A `lnpl.kb` entry-point's loaded value is a zero-argument
callable (`() -> str`), but a temp fixture directory's path is only known at
test run time, so each factory here reads its root from an env var the test
sets immediately before triggering discovery (mirrors
`tests.driver_spi_fixture`'s role for the `lnpl.drivers` group).
"""

import os


def _root_from_env(var_name):
    root = os.environ.get(var_name)
    if not root:
        raise RuntimeError("%s not set — fixture misuse" % var_name)
    return root


def pack_root_alpha():
    return _root_from_env("LNPL_KB_PACK_FIXTURE_ROOT_ALPHA")


def pack_root_beta():
    return _root_from_env("LNPL_KB_PACK_FIXTURE_ROOT_BETA")
