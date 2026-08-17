"""Data-file resolution for lnpl — issue #60.

`mlir/` and `kb/` are the repo's single, canonical data trees (README tree,
RFC-0005). They are never moved. Two different runtimes need to find them
though: a repo checkout (editable install, `PYTHONPATH=impl`) and a
`pip install`-ed wheel that has no repo checkout at all — the wheel instead
carries a copy under the installed `lnpl` package as `lnpl/assets/...`
(`pyproject.toml`'s `force-include`).

`data_path(rel)` is the single resolution chain both runtimes go through:

    1. the wheel's bundled `lnpl/assets/<rel>` (installed, no checkout needed)
    2. `<repo-anchor>/<rel>` (checkout/editable runs, where assets are never
       built)
    3. neither exists — raise with a recovery hint

`rel` is a path relative to the repo root, e.g. "mlir/lnpl.irdl.mlir" or "kb".
"""

import os
from importlib import resources

# This file is <repo>/impl/lnpl/resources.py, so three dirnames reach the repo.
# Anchored on __file__, never cwd — callers run from arbitrary workdirs. Kept
# as a plain module attribute (not computed inline in data_path) so tests can
# monkeypatch it to force path 2/3 independently of the real repo layout.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


class DataNotFoundError(Exception):
    """Raised when neither the packaged assets nor a repo checkout has `rel`."""


def recovery_hint(rel):
    """The D2③ message: what to do when `rel` cannot be resolved."""
    return (
        "lnpl 데이터를 찾을 수 없습니다: %r. "
        "레포 체크아웃에서 실행하거나 --root(agents/kb)를 지정하십시오." % rel)


def data_path(rel):
    """Resolve `rel` (e.g. "mlir/lnpl.irdl.mlir", "kb") to an absolute path.

    Tries the wheel's bundled assets first, then a repo-checkout anchor.
    Raises DataNotFoundError (with `recovery_hint(rel)`) if neither exists.
    """
    try:
        packaged = resources.files("lnpl").joinpath("assets", rel)
        if packaged.is_dir() or packaged.is_file():
            return str(packaged)
    except (ModuleNotFoundError, TypeError):
        pass

    anchored = os.path.join(REPO_ROOT, rel)
    if os.path.isdir(anchored) or os.path.isfile(anchored):
        return anchored

    raise DataNotFoundError(recovery_hint(rel))
