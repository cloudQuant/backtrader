"""Shared explicit native Alpha101 construction helpers.

The helpers come from the fixed Iteration 45 representative implementation.
They build ordinary Backtrader Indicator/Lines children and keep formula
evaluation inside the FactorIndicator/FactorStrategy lifecycle. New native
formulas should subclass :class:`NativeAlphaBase` and implement
``_make_formula`` directly; this module does not provide a formula parser.
"""

from typing import Any

from ..representative import _RepresentativeFactor


class NativeAlphaBase(_RepresentativeFactor):
    """Base for explicit, next-driven Alpha101 production indicators."""

    lines: Any = ("factor",)


__all__ = ("NativeAlphaBase",)
