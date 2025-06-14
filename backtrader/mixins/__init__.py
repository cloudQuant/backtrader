#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

"""Backtrader mixins module.

This module provides mixin classes that can be used to add functionality
to other classes without using metaclasses. These mixins are part of the
effort to remove metaprogramming from backtrader while maintaining
backward compatibility.
"""

from .singleton import (
    SingletonMixin,
    ParameterizedSingletonMixin,
    StoreBase,
)

__all__ = [
    'SingletonMixin',
    'ParameterizedSingletonMixin', 
    'StoreBase',
] 