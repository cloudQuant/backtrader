#!/usr/bin/env python
"""Exception Classes Module - Custom exceptions for backtrader.

This module defines the exception hierarchy used throughout the
backtrader framework.

Classes:
    BacktraderError: Base exception for all backtrader exceptions.
    StrategySkipError: Raised to skip a strategy during optimization.
    ModuleImportError: Raised when a required module cannot be imported.
    FromModuleImportError: Raised when a from-style import fails.

Example:
    Raising StrategySkipError during optimization:
    >>> class MyStrategy(bt.Strategy):
    ...     params = (('period', 20),)
    ...
    ...     def __init__(self):
    ...         if self.p.period < 5:
    ...             raise bt.errors.StrategySkipError()
"""
# When using 'from error import *', only import these two classes: BacktraderError and StrategySkipError
__all__ = ["BacktraderError", "StrategySkipError"]


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
        super().__init__(message)
        self.args = args


# FromModuleImportError class
class FromModuleImportError(ModuleImportError):
    """Raised if a class requests a module to be present to work and it cannot
    be imported"""

    def __init__(self, message, *args):
        super().__init__(message, *args)
