#!/usr/bin/env python
# When using 'from error import *', only import these two classes: BacktraderError and StrategySkipError
__all__ = ["BacktraderError", "StrategySkipError"]


# BacktraderError class
class BacktraderError(Exception):
    """Base exception for all other exceptions"""

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
