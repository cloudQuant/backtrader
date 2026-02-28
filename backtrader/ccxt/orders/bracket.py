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
from typing import Any, Dict, Optional

# Use integer constants to avoid circular import
# Matches values from backtrader.order.OrderBase
_ORDER_LIMIT = 2
_ORDER_STOP = 3


class BracketState(Enum):
    """Enumeration of bracket order states.

    The bracket order state machine tracks the lifecycle of a bracket order
    from initial submission through entry execution to final exit via either
    stop-loss or take-profit.

    Attributes:
        PENDING: Initial state waiting for entry order to be filled.
        ACTIVE: Entry order filled, protection orders (stop/limit) are active.
        STOPPED: Stop-loss order was filled, position closed with loss.
        TARGETED: Take-profit order was filled, position closed with profit.
        CANCELLED: Bracket was manually cancelled before completion.
        PARTIAL: Partial fill occurred (not fully implemented in current version).
    """

    PENDING = "pending"  # Waiting for entry to fill
    ACTIVE = "active"  # Entry filled, protections active
    STOPPED = "stopped"  # Stop-loss filled
    TARGETED = "targeted"  # Take-profit filled
    CANCELLED = "cancelled"  # Bracket cancelled
    PARTIAL = "partial"  # Partially filled


@dataclass
class BracketOrder:
    """Data class representing a bracket order combination.

    A bracket order consists of three component orders:
    1. Entry order: Opens the position (buy or sell)
    2. Stop-loss order: Closes the position at a loss if price moves against
    3. Take-profit order: Closes the position at a profit if target is reached

    The stop-loss and take-profit orders use OCO (One Cancels Other) logic:
    when one fills, the other is automatically cancelled.

    Attributes:
        bracket_id: Unique identifier for this bracket order.
        entry_order: The order that opens the position.
        stop_order: The stop-loss order that limits downside risk.
        limit_order: The take-profit order that locks in gains.
        state: Current state of the bracket (PENDING, ACTIVE, etc.).
        entry_fill_price: Actual price at which the entry order was filled.
        data: The data feed object associated with this bracket.
        size: Position size (quantity).
        stop_price: Stop-loss trigger price.
        limit_price: Take-profit limit price.
        side: Order side - "buy" for long, "sell" for short.
    """

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
        """Check if the bracket order is currently active.

        A bracket is considered active when the entry order has been filled
        and the protection orders (stop-loss and take-profit) are working.

        Returns:
            True if the bracket state is ACTIVE, False otherwise.
        """
        return self.state == BracketState.ACTIVE

    def is_closed(self) -> bool:
        """Check if the bracket order has been closed.

        A bracket is considered closed when it has reached a terminal state:
        stopped out, take-profit hit, or manually cancelled.

        Returns:
            True if the bracket state is STOPPED, TARGETED, or CANCELLED.
        """
        return self.state in (BracketState.STOPPED, BracketState.TARGETED, BracketState.CANCELLED)


class BracketOrderManager:
    """Manager for bracket order lifecycle with OCO (One Cancels Other) logic.

    The BracketOrderManager handles the creation, tracking, and management of
    bracket orders. When an entry order fills, it automatically creates stop-loss
    and take-profit orders. When either protection order fills, it cancels the
    other to implement OCO behavior.

    Typical usage:
        1. Create manager with broker instance
        2. Call create_bracket() with entry, stop, and limit prices
        3. Call on_order_update() when order status changes
        4. Manager handles OCO logic automatically

    Attributes:
        broker: The broker instance used to create and cancel orders.
        brackets: Dictionary mapping bracket_id to BracketOrder instances.
        _order_to_bracket: Dictionary mapping order IDs to bracket IDs.
        _next_bracket_id: Counter for generating unique bracket IDs.
    """

    def __init__(self, broker):
        """Initialize the BracketOrderManager.

        Args:
            broker: The broker instance to use for order creation and management.
                Must implement buy(), sell(), and cancel() methods.
        """
        self.broker = broker
        self.brackets: Dict[str, BracketOrder] = {}
        self._order_to_bracket: Dict[str, str] = {}
        self._next_bracket_id = 0

    def create_bracket(
        self,
        data,
        size: float,
        entry_price: float,
        stop_price: float,
        limit_price: float,
        entry_type: int = _ORDER_LIMIT,
        side: str = "buy",
    ) -> BracketOrder:
        """Create a new bracket order with entry, stop-loss, and take-profit.

        Creates an entry order at the specified price. When the entry fills,
        stop-loss and take-profit orders will be automatically created.

        Args:
            data: The data feed object for the instrument being traded.
            size: Position size (quantity) to trade.
            entry_price: Price at which to enter the position.
            stop_price: Price at which to trigger stop-loss (exit with loss).
            limit_price: Price at which to take profit (exit with gain).
            entry_type: Order type for entry (default: LIMIT order).
            side: Order side - "buy" for long, "sell" for short positions.

        Returns:
            BracketOrder: The created bracket order instance with a unique
                bracket_id. The entry_order will be created immediately;
                stop_order and limit_order are created after entry fills.
        """
        bracket_id = f"bracket_{self._next_bracket_id}"
        self._next_bracket_id += 1

        # Create entry order
        if side == "buy":
            entry_order = self.broker.buy(owner=None, data=data, size=size, price=entry_price, exectype=entry_type)
        else:
            entry_order = self.broker.sell(owner=None, data=data, size=size, price=entry_price, exectype=entry_type)

        bracket = BracketOrder(
            bracket_id=bracket_id,
            entry_order=entry_order,
            state=BracketState.PENDING,
            data=data,
            size=size,
            stop_price=stop_price,
            limit_price=limit_price,
            side=side,
        )

        self.brackets[bracket_id] = bracket
        order_id = self._get_order_id(entry_order)
        if order_id:
            self._order_to_bracket[order_id] = bracket_id

        return bracket

    def on_order_update(self, order) -> None:
        """Handle order status updates and manage OCO logic.

        This method should be called whenever an order status changes. It handles:
        - Entry order fill: Creates and activates stop-loss and take-profit orders
        - Stop-loss fill: Cancels take-profit order (OCO)
        - Take-profit fill: Cancels stop-loss order (OCO)

        Args:
            order: The order object that was updated. Must have status attribute
                and be trackable via _get_order_id().
        """
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
        """Activate stop-loss and take-profit orders after entry fills.

        When the entry order is filled, this method creates the protection orders.
        For long positions: creates sell stop and sell limit orders.
        For short positions: creates buy stop and buy limit orders.

        Args:
            bracket: The bracket order to activate protection for.
            entry_order: The filled entry order (contains executed price).
        """
        bracket.entry_fill_price = entry_order.executed.price
        bracket.state = BracketState.ACTIVE

        # Create protection orders (opposite side of entry)
        if bracket.side == "buy":
            # For long: sell at stop (below) and sell at limit (above)
            bracket.stop_order = self.broker.sell(
                owner=None,
                data=bracket.data,
                size=bracket.size,
                price=bracket.stop_price,
                exectype=_ORDER_STOP,
            )
            bracket.limit_order = self.broker.sell(
                owner=None,
                data=bracket.data,
                size=bracket.size,
                price=bracket.limit_price,
                exectype=_ORDER_LIMIT,
            )
        else:
            # For short: buy at stop (above) and buy at limit (below)
            bracket.stop_order = self.broker.buy(
                owner=None,
                data=bracket.data,
                size=bracket.size,
                price=bracket.stop_price,
                exectype=_ORDER_STOP,
            )
            bracket.limit_order = self.broker.buy(
                owner=None,
                data=bracket.data,
                size=bracket.size,
                price=bracket.limit_price,
                exectype=_ORDER_LIMIT,
            )

        # Map new orders
        for order in [bracket.stop_order, bracket.limit_order]:
            order_id = self._get_order_id(order)
            if order_id:
                self._order_to_bracket[order_id] = bracket.bracket_id

    def _handle_stop_fill(self, bracket: BracketOrder) -> None:
        """Handle stop-loss order fill by cancelling take-profit (OCO).

        When the stop-loss is filled, the position is closed at a loss.
        The take-profit order is no longer needed and must be cancelled.

        Args:
            bracket: The bracket order whose stop-loss was filled.
        """
        bracket.state = BracketState.STOPPED
        if bracket.limit_order:
            self.broker.cancel(bracket.limit_order)

    def _handle_limit_fill(self, bracket: BracketOrder) -> None:
        """Handle take-profit order fill by cancelling stop-loss (OCO).

        When the take-profit is filled, the position is closed at a profit.
        The stop-loss order is no longer needed and must be cancelled.

        Args:
            bracket: The bracket order whose take-profit was filled.
        """
        bracket.state = BracketState.TARGETED
        if bracket.stop_order:
            self.broker.cancel(bracket.stop_order)

    def cancel_bracket(self, bracket_id: str) -> None:
        """Cancel all orders in a bracket.

        Cancels the entry order (if not yet filled) and any active
        protection orders. Sets the bracket state to CANCELLED.

        Args:
            bracket_id: The unique identifier of the bracket to cancel.
        """
        bracket = self.brackets.get(bracket_id)
        if not bracket:
            return

        bracket.state = BracketState.CANCELLED
        for order in [bracket.entry_order, bracket.stop_order, bracket.limit_order]:
            if order:
                try:
                    self.broker.cancel(order)
                except Exception:
                    pass

    def modify_bracket(self, bracket_id: str, stop_price: float = None, limit_price: float = None) -> bool:
        """Modify stop-loss and/or take-profit prices of an active bracket.

        Cancels existing protection orders and creates new ones with updated
        prices. Only works for brackets in ACTIVE state.

        Args:
            bracket_id: The unique identifier of the bracket to modify.
            stop_price: New stop-loss price. If None, stop order unchanged.
            limit_price: New take-profit price. If None, limit order unchanged.

        Returns:
            True if modification was successful, False if bracket not found
            or not in ACTIVE state.
        """
        bracket = self.brackets.get(bracket_id)
        if not bracket or bracket.state != BracketState.ACTIVE:
            return False

        # Cancel and recreate orders with new prices
        if stop_price and bracket.stop_order:
            self.broker.cancel(bracket.stop_order)
            bracket.stop_price = stop_price
            if bracket.side == "buy":
                bracket.stop_order = self.broker.sell(
                    owner=None,
                    data=bracket.data,
                    size=bracket.size,
                    price=stop_price,
                    exectype=_ORDER_STOP,
                )
            else:
                bracket.stop_order = self.broker.buy(
                    owner=None,
                    data=bracket.data,
                    size=bracket.size,
                    price=stop_price,
                    exectype=_ORDER_STOP,
                )

        if limit_price and bracket.limit_order:
            self.broker.cancel(bracket.limit_order)
            bracket.limit_price = limit_price
            if bracket.side == "buy":
                bracket.limit_order = self.broker.sell(
                    owner=None,
                    data=bracket.data,
                    size=bracket.size,
                    price=limit_price,
                    exectype=_ORDER_LIMIT,
                )
            else:
                bracket.limit_order = self.broker.buy(
                    owner=None,
                    data=bracket.data,
                    size=bracket.size,
                    price=limit_price,
                    exectype=_ORDER_LIMIT,
                )

        return True

    def get_bracket(self, bracket_id: str) -> Optional[BracketOrder]:
        """Retrieve a bracket order by its ID.

        Args:
            bracket_id: The unique identifier of the bracket to retrieve.

        Returns:
            The BracketOrder instance if found, None otherwise.
        """
        return self.brackets.get(bracket_id)

    def get_active_brackets(self) -> list:
        """Get all currently active bracket orders.

        Active brackets are those where the entry has filled but neither
        stop-loss nor take-profit have been triggered yet.

        Returns:
            List of BracketOrder instances in ACTIVE state.
        """
        return [b for b in self.brackets.values() if b.state == BracketState.ACTIVE]

    def _get_order_id(self, order) -> Optional[str]:
        """Extract a unique order ID from an order object.

        Handles different order implementations by checking multiple
        possible attributes where the ID might be stored.

        Args:
            order: The order object to extract ID from.

        Returns:
            The order ID as a string if found, None otherwise.
        """
        if hasattr(order, "ccxt_order") and order.ccxt_order:
            return order.ccxt_order.get("id")
        if hasattr(order, "ref"):
            return str(order.ref)
        return None
