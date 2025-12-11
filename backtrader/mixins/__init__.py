#!/usr/bin/env python

"""Backtrader mixins module.

This module provides mixin classes that can be used to add functionality
to other classes without using metaclasses. These mixins are part of the
effort to remove metaprogramming from backtrader while maintaining
backward compatibility.
"""

from .singleton import (
    ParameterizedSingletonMixin,
    SingletonMixin,
    StoreBase,
)

__all__ = [
    "SingletonMixin",
    "ParameterizedSingletonMixin",
    "StoreBase",
]
