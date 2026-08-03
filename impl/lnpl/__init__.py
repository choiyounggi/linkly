"""LNPL reference implementation — parser, IR lowering, interpreter, native backend.

Clarity over speed: this is the executable form of the RFC suite
(WebAssembly reference-interpreter convention, plan.md D20 artifact 3).

`__version__` tracks this package. Two other version strings in this tree are
**separate axes and do not move with it**: `protocol.py`'s `agent.card` version is
the agent protocol's, and `openapi.py`'s default is the version stamped on a
*generated* OpenAPI document.
"""

__version__ = "0.2.0"
