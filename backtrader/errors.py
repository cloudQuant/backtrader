#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

# 从from error import * 的时候，只导入下面两个类BacktraderError和StrategySkipError
__all__ = ['BacktraderError', 'StrategySkipError']


# BacktraderError类
class BacktraderError(Exception):
    """Base exception for all other exceptions"""
    pass

# StrategySkipError，只有这个类在cerebro中用到了
class StrategySkipError(BacktraderError):
    """Requests the platform to skip this strategy for backtesting. To be
    raised during the initialization (``__init__``) phase of the instance"""
    pass

# ModuleImportError类
class ModuleImportError(BacktraderError):
    """Raised if a class requests a module to be present to work and it cannot
    be imported"""
    def __init__(self, message, *args):
        super(ModuleImportError, self).__init__(message)
        self.args = args

# FromModuleImportError类
class FromModuleImportError(ModuleImportError):
    """Raised if a class requests a module to be present to work and it cannot
    be imported"""
    def __init__(self, message, *args):
        super(FromModuleImportError, self).__init__(message, *args)
