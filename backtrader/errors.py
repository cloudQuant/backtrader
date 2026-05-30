#!/usr/bin/env python
"""Exception Classes Module - Custom exceptions for backtrader.

This module defines the exception hierarchy used throughout the
backtrader framework.

Classes:
    BacktraderError: Base exception for all backtrader exceptions.
    StrategySkipError: Raised to skip a strategy during optimization.
    ModuleImportError: Raised when a required module cannot be imported.
    FromModuleImportError: Raised when a from-style import fails.
    DataError: Raised for data-feed/parsing problems.
    BrokerError: Raised for broker/execution problems.
    OrderError: Raised for order-related problems (subclass of BrokerError).
    ConfigError: Raised for invalid configuration/parameters.

Example:
    Raising StrategySkipError during optimization:
    >>> class MyStrategy(bt.Strategy):
    ...     params = (('period', 20),)
    ...
    ...     def __init__(self):
    ...         if self.p.period < 5:
    ...             raise bt.errors.StrategySkipError()
"""

# 'from errors import *' exports the base and the most commonly raised classes.
# The category classes are additive (new parents only); existing classes and
# their inheritance are unchanged so isinstance() checks stay compatible.
__all__ = [
    "BacktraderError",
    "StrategySkipError",
    "DataError",
    "BrokerError",
    "OrderError",
    "ConfigError",
]


# BacktraderError class
class BacktraderError(Exception):
    """Base exception for all backtrader exceptions."""

    pass


# StrategySkipError, only this class is used in cerebro
class StrategySkipError(BacktraderError):
    """Requests the platform to skip this strategy for backtesting. To be
    raised during the initialization (``__init__``) phase of the instance"""

    pass


# ModuleImportError class
class ModuleImportError(BacktraderError):
    """Raised if a class requests a module to be present to work and it cannot
    be imported"""

    def __init__(self, message, *args):
        """Initialize the ModuleImportError.

        Args:
            message: Error message.
            *args: Additional arguments.
        """
        super().__init__(message, *args)


# FromModuleImportError class
class FromModuleImportError(ModuleImportError):
    """Raised if a class requests a module to be present to work and it cannot
    be imported"""

    def __init__(self, message, *args):
        """Initialize the FromModuleImportError.

        Args:
            message: Error message.
            *args: Additional arguments.
        """
        super().__init__(message, *args)


# ---------------------------------------------------------------------------
# Business exception categories (additive, Sprint 3).
#
# These give callers a meaningful hierarchy to catch
# (e.g. ``except bt.errors.DataError``) without having to enumerate stdlib
# exceptions. They all derive from BacktraderError, so existing
# ``except BacktraderError`` handlers keep working. Nothing here changes the
# parent of a previously existing class, so isinstance() behavior is
# backward compatible.
# ---------------------------------------------------------------------------


class DataError(BacktraderError):
    """Raised for data-feed problems: loading, parsing, or alignment failures."""

    pass


class BrokerError(BacktraderError):
    """Raised for broker/execution problems: cash, margin, or matching failures."""

    pass


class OrderError(BrokerError):
    """Raised for order-related problems: invalid size/price or rejected orders."""

    pass


class ConfigError(BacktraderError):
    """Raised for invalid configuration or parameter values."""

    pass
