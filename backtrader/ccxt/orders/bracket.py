#!/usr/bin/env python
"""Bracket Order Module - OCO (One Cancels Other) orders.

This module provides bracket order functionality for combined entry,
stop-loss, and take-profit orders.

Classes:
    BracketState: Enumeration of bracket order states.
    BracketOrder: Data class for bracket order combination.
    BracketOrderManager: Manager for bracket order lifecycle.

Example:
    >>> manager = BracketOrderManager(broker)
    >>> bracket = manager.create_bracket(
    ...     data=data, size=0.01, entry_price=50000,
    ...     stop_price=49000, limit_price=52000
    ... )
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Any

# Use integer constant to avoid circular import
# Matches bt.Order.Limit = 2 from backtrader.order.OrderBase
_ORDER_LIMIT = 2


class BracketState(Enum):
    """Bracket order state enumeration."""
    PENDING = "pending"      # Waiting for entry to fill
    ACTIVE = "active"        # Entry filled, protections active
    STOPPED = "stopped"      # Stop-loss filled
    TARGETED = "targeted"    # Take-profit filled
    CANCELLED = "cancelled"  # Bracket cancelled
    PARTIAL = "partial"      # Partially filled


@dataclass
class BracketOrder:
    """Bracket order combination (entry + stop + limit)."""
    bracket_id: str
    entry_order: Any = None
    stop_order: Any = None
    limit_order: Any = None
    state: BracketState = BracketState.PENDING
    entry_fill_price: float = 0.0
    data: Any = None
    size: float = 0.0
    stop_price: float = 0.0
    limit_price: float = 0.0
    side: str = "buy"

    def is_active(self) -> bool:
        return self.state == BracketState.ACTIVE

    def is_closed(self) -> bool:
        return self.state in (BracketState.STOPPED, BracketState.TARGETED, BracketState.CANCELLED)


class BracketOrderManager:
    """Manager for bracket order lifecycle with OCO logic."""

    def __init__(self, broker):
        self.broker = broker
        self.brackets: Dict[str, BracketOrder] = {}
        self._order_to_bracket: Dict[str, str] = {}
        self._next_bracket_id = 0

    def create_bracket(self, data, size: float, entry_price: float,
                       stop_price: float, limit_price: float,
                       entry_type: int = _ORDER_LIMIT, side: str = "buy") -> BracketOrder:
        """Create a new bracket order."""
        bracket_id = f"bracket_{self._next_bracket_id}"
        self._next_bracket_id += 1

        # Create entry order
        if side == "buy":
            entry_order = self.broker.buy(owner=None, data=data, size=size,
                                          price=entry_price, exectype=entry_type)
        else:
            entry_order = self.broker.sell(owner=None, data=data, size=size,
                                           price=entry_price, exectype=entry_type)

        bracket = BracketOrder(
            bracket_id=bracket_id, entry_order=entry_order,
            state=BracketState.PENDING, data=data, size=size,
            stop_price=stop_price, limit_price=limit_price, side=side
        )

        self.brackets[bracket_id] = bracket
        order_id = self._get_order_id(entry_order)
        if order_id:
            self._order_to_bracket[order_id] = bracket_id

        return bracket

    def on_order_update(self, order) -> None:
        """Handle order updates and manage OCO logic."""
        order_id = self._get_order_id(order)
        if not order_id or order_id not in self._order_to_bracket:
            return

        bracket_id = self._order_to_bracket[order_id]
        bracket = self.brackets.get(bracket_id)
        if not bracket:
            return

        # Entry order filled - activate protection orders
        if order == bracket.entry_order and order.status == order.Completed:
            self._activate_protection(bracket, order)

        # Protection order filled - cancel the other (OCO)
        elif bracket.state == BracketState.ACTIVE:
            if order == bracket.stop_order and order.status == order.Completed:
                self._handle_stop_fill(bracket)
            elif order == bracket.limit_order and order.status == order.Completed:
                self._handle_limit_fill(bracket)

    def _activate_protection(self, bracket: BracketOrder, entry_order) -> None:
        """Activate stop and limit orders after entry fills."""
        bracket.entry_fill_price = entry_order.executed.price
        bracket.state = BracketState.ACTIVE

        # Create protection orders (opposite side of entry)
        if bracket.side == "buy":
            # For long: sell at stop (below) and sell at limit (above)
            bracket.stop_order = self.broker.sell(
                owner=None, data=bracket.data, size=bracket.size,
                price=bracket.stop_price, exectype=bt.Order.Stop)
            bracket.limit_order = self.broker.sell(
                owner=None, data=bracket.data, size=bracket.size,
                price=bracket.limit_price, exectype=bt.Order.Limit)
        else:
            # For short: buy at stop (above) and buy at limit (below)
            bracket.stop_order = self.broker.buy(
                owner=None, data=bracket.data, size=bracket.size,
                price=bracket.stop_price, exectype=bt.Order.Stop)
            bracket.limit_order = self.broker.buy(
                owner=None, data=bracket.data, size=bracket.size,
                price=bracket.limit_price, exectype=bt.Order.Limit)

        # Map new orders
        for order in [bracket.stop_order, bracket.limit_order]:
            order_id = self._get_order_id(order)
            if order_id:
                self._order_to_bracket[order_id] = bracket.bracket_id

    def _handle_stop_fill(self, bracket: BracketOrder) -> None:
        """Handle stop-loss fill - cancel take-profit (OCO)."""
        bracket.state = BracketState.STOPPED
        if bracket.limit_order:
            self.broker.cancel(bracket.limit_order)

    def _handle_limit_fill(self, bracket: BracketOrder) -> None:
        """Handle take-profit fill - cancel stop-loss (OCO)."""
        bracket.state = BracketState.TARGETED
        if bracket.stop_order:
            self.broker.cancel(bracket.stop_order)

    def cancel_bracket(self, bracket_id: str) -> None:
        """Cancel all orders in a bracket."""
        bracket = self.brackets.get(bracket_id)
        if not bracket:
            return

        bracket.state = BracketState.CANCELLED
        for order in [bracket.entry_order, bracket.stop_order, bracket.limit_order]:
            if order:
                try:
                    self.broker.cancel(order)
                except:
                    pass

    def modify_bracket(self, bracket_id: str, stop_price: float = None,
                       limit_price: float = None) -> bool:
        """Modify stop/limit prices of an active bracket."""
        bracket = self.brackets.get(bracket_id)
        if not bracket or bracket.state != BracketState.ACTIVE:
            return False

        # Cancel and recreate orders with new prices
        if stop_price and bracket.stop_order:
            self.broker.cancel(bracket.stop_order)
            bracket.stop_price = stop_price
            if bracket.side == "buy":
                bracket.stop_order = self.broker.sell(
                    owner=None, data=bracket.data, size=bracket.size,
                    price=stop_price, exectype=bt.Order.Stop)
            else:
                bracket.stop_order = self.broker.buy(
                    owner=None, data=bracket.data, size=bracket.size,
                    price=stop_price, exectype=bt.Order.Stop)

        if limit_price and bracket.limit_order:
            self.broker.cancel(bracket.limit_order)
            bracket.limit_price = limit_price
            if bracket.side == "buy":
                bracket.limit_order = self.broker.sell(
                    owner=None, data=bracket.data, size=bracket.size,
                    price=limit_price, exectype=bt.Order.Limit)
            else:
                bracket.limit_order = self.broker.buy(
                    owner=None, data=bracket.data, size=bracket.size,
                    price=limit_price, exectype=bt.Order.Limit)

        return True

    def get_bracket(self, bracket_id: str) -> Optional[BracketOrder]:
        """Get bracket by ID."""
        return self.brackets.get(bracket_id)

    def get_active_brackets(self) -> list:
        """Get all active brackets."""
        return [b for b in self.brackets.values() if b.state == BracketState.ACTIVE]

    def _get_order_id(self, order) -> Optional[str]:
        """Extract order ID from order object."""
        if hasattr(order, 'ccxt_order') and order.ccxt_order:
            return order.ccxt_order.get('id')
        if hasattr(order, 'ref'):
            return str(order.ref)
        return None
