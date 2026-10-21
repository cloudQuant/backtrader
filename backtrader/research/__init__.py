"""Small native research-factor API built on Backtrader indicators."""

from .factor_indicator import FactorIndicator
from .factor_strategy import FactorStrategy

__all__ = ("FactorIndicator", "FactorStrategy")
