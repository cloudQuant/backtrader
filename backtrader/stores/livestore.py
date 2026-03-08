#!/usr/bin/env python
"""Live Store Abstract Base Class.

Defines the common interface for live trading store implementations.
The current project direction uses ``BtApiStore`` as the unified adapter
and keeps this base class as the reference contract for future providers.

Classes:
    LiveStoreBase: Abstract base for live-trading store adapters.

Example:
    class MyExchangeStore(LiveStoreBase):
        def start(self): ...
        def stop(self): ...
        def get_cash(self): ...
        ...
"""

from abc import ABC, abstractmethod


class LiveStoreBase(ABC):
    """Abstract base class for live-trading store adapters.

    A *store* is the bridge between backtrader and an external trading
    venue (exchange, broker gateway, etc.).  It is responsible for:

    - Managing the network connection lifecycle.
    - Providing account balance / position queries.
    - Creating matching broker and data-feed instances.
    - Optionally subscribing to real-time market data.

    Subclasses **must** implement every ``@abstractmethod``.
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def start(self):
        """Establish the connection to the trading venue."""

    @abstractmethod
    def stop(self):
        """Gracefully disconnect and release resources."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return ``True`` when the store is ready to accept requests."""

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @abstractmethod
    def getbroker(self, *args, **kwargs):
        """Return a broker instance bound to this store."""

    @abstractmethod
    def getdata(self, *args, **kwargs):
        """Return a data-feed instance bound to this store."""

    # ------------------------------------------------------------------
    # Account queries
    # ------------------------------------------------------------------

    @abstractmethod
    def get_cash(self) -> float:
        """Return current available cash."""

    @abstractmethod
    def get_value(self) -> float:
        """Return total account value (cash + positions)."""

    @abstractmethod
    def get_balance(self):
        """Refresh cached cash/value from the venue.

        Implementations should respect rate-limiting to avoid API bans.
        """

    @abstractmethod
    def get_positions(self) -> list:
        """Return a list of open positions.

        Each position should be a dict with at least:
        ``instrument``, ``direction``, ``volume``, ``price``.
        """

    # ------------------------------------------------------------------
    # Optional: market data registration
    # ------------------------------------------------------------------

    def register(self, feed):
        """Register a data feed with the store (optional).

        Args:
            feed: A backtrader data-feed instance.
        """

    def subscribe(self, dataname: str):
        """Subscribe to market data for *dataname* (optional)."""
