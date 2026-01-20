#!/usr/bin/env python
"""CCXT Orders Module - Advanced order types.

This module provides advanced order management including Bracket orders
(OCO - One Cancels Other).

Classes:
    BracketOrder: Bracket order data class.
    BracketState: Bracket order state enumeration.
    BracketOrderManager: Manager for bracket order lifecycle.
"""

from .bracket import BracketOrder, BracketState, BracketOrderManager

__all__ = [
    'BracketOrder',
    'BracketState',
    'BracketOrderManager',
]
