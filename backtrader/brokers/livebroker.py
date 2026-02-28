#!/usr/bin/env python
"""Live Broker Abstract Base Class.

Defines the common interface that all live trading broker implementations
(CCXT, CTP, IB, Crypto, etc.) should conform to. Existing brokers are
**not** required to inherit from this class immediately — it serves as
a reference contract for new implementations and gradual migration.

Classes:
    LiveBrokerBase: Abstract base for live-trading broker adapters.
"""

from abc import ABC, abstractmethod


class LiveBrokerBase(ABC):
    """Abstract base class for live-trading broker adapters.

    A *broker* translates backtrader order objects into venue-specific
    API calls and tracks order/fill lifecycle. It is responsible for:

    - Submitting, modifying, and cancelling orders.
    - Processing order status updates and fill notifications.
    - Reporting cash and portfolio value.
    - Managing positions.

    Subclasses **must** implement every ``@abstractmethod``.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def start(self):
        """Called by Cerebro when live trading begins.

        Typically loads initial balance and positions from the store.
        """

    @abstractmethod
    def stop(self):
        """Called by Cerebro when live trading ends."""

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    @abstractmethod
    def getcash(self) -> float:
        """Return current available cash."""

    @abstractmethod
    def getvalue(self, datas=None) -> float:
        """Return total portfolio value."""

    @abstractmethod
    def getposition(self, data, clone=True):
        """Return the position for a given data feed.

        Args:
            data: A backtrader data-feed instance.
            clone: If True, return a copy of the position.
        """

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    @abstractmethod
    def submit(self, order):
        """Submit an order to the venue.

        Args:
            order: A backtrader Order instance.

        Returns:
            The submitted order (with ref set).
        """

    @abstractmethod
    def cancel(self, order):
        """Request cancellation of an open order.

        Args:
            order: The order to cancel.
        """

    @abstractmethod
    def next(self):
        """Called on every bar/tick — process pending fills and notifications."""

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    @abstractmethod
    def get_notification(self):
        """Return the next pending notification, or None."""
