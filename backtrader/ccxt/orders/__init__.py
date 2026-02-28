#!/usr/bin/env python
"""CCXT Orders Module - Advanced order types.

This module provides advanced order management functionality for CCXT brokers,
including Bracket orders (OCO - One Cancels Other) which allow traders to
automatically set stop-loss and take-profit orders when entering a position.

A bracket order consists of three component orders:
1. Entry order: Opens the position (buy or sell)
2. Stop-loss order: Closes the position at a loss if price moves against
3. Take-profit order: Closes the position at a profit if target is reached

The stop-loss and take-profit orders use OCO (One Cancels Other) logic:
when one fills, the other is automatically cancelled.

Classes:
    BracketOrder: Data class representing a bracket order combination.
    BracketState: Enumeration of bracket order states.
    BracketOrderManager: Manager for bracket order lifecycle.

Example:
    >>> from backtrader.ccxt.orders import BracketOrderManager
    >>> manager = BracketOrderManager(broker)
    >>> bracket = manager.create_bracket(
    ...     data=data, size=0.01, entry_price=50000,
    ...     stop_price=49000, limit_price=52000
    ... )
"""

from .bracket import BracketOrder, BracketOrderManager, BracketState

__all__ = [
    "BracketOrder",
    "BracketState",
    "BracketOrderManager",
]
