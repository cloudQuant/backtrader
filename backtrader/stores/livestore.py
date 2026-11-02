#!/usr/bin/env python
"""Common live Store contract layered on the per-instance Store base.

Defines the common interface for live trading store implementations.
The current project direction uses ``BtApiStore`` as the unified adapter
and keeps this base class as the reference contract for future providers.

Classes:
    LiveStoreBase: Per-instance Store contract for live-trading adapters.

Example:
    class MyExchangeStore(LiveStoreBase):
        def start(self): ...
        def stop(self): ...
        def get_cash(self): ...
        ...
"""

from ..store import Store


class LiveStoreBase(Store):
    """Per-instance base class for live-trading store adapters.

    A *store* is the bridge between backtrader and an external trading
    venue (exchange, broker gateway, etc.).  It is responsible for:

    - Managing the network connection lifecycle.
    - Providing account balance / position queries.
    - Creating matching broker and data-feed instances.
    - Optionally subscribing to real-time market data.

    This class keeps the common Backtrader Store instance shape while defining
    the live-store interface. Required methods raise ``NotImplementedError``
    until a concrete adapter supplies them.
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def start(self, data=None, broker=None):
        """Establish the connection to the trading venue.

        Args:
            data: Optional data-feed instance to register on start.
            broker: Optional broker instance to attach on start.
        """
        raise NotImplementedError("A live Store must implement start()")

    def stop(self):
        """Gracefully disconnect and release resources."""
        raise NotImplementedError("A live Store must implement stop()")

    @property
    def is_connected(self) -> bool:
        """Return ``True`` when the store is ready to accept requests."""
        raise NotImplementedError("A live Store must implement is_connected")

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    def getbroker(self, *args, **kwargs):
        """Return a broker instance bound to this store."""
        raise NotImplementedError("A live Store must implement getbroker()")

    def getdata(self, *args, **kwargs):
        """Return a data-feed instance bound to this store."""
        raise NotImplementedError("A live Store must implement getdata()")

    # ------------------------------------------------------------------
    # Account queries
    # ------------------------------------------------------------------

    def get_cash(self) -> float:
        """Return current available cash."""
        raise NotImplementedError("A live Store must implement get_cash()")

    def get_value(self) -> float:
        """Return total account value (cash + positions)."""
        raise NotImplementedError("A live Store must implement get_value()")

    def get_balance(self):
        """Refresh cached cash/value from the venue.

        Implementations should respect rate-limiting to avoid API bans.
        """
        raise NotImplementedError("A live Store must implement get_balance()")

    def get_positions(self) -> list:
        """Return a list of open positions.

        Each position should be a dict with at least:
        ``instrument``, ``direction``, ``volume``, ``price``.
        """
        raise NotImplementedError("A live Store must implement get_positions()")

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

    def poll_live(self, dataname: str):
        """Poll the next completed live bar for *dataname* (optional)."""
        return

    def poll_tick(self, dataname: str):
        """Poll the next live tick for *dataname* (optional)."""
        return

    def poll_orderbook(self, dataname: str):
        """Poll the next live order book snapshot for *dataname* (optional)."""
        return

    def has_pending_tick(self, dataname: str) -> bool:
        """Return whether *dataname* has queued live ticks (optional)."""
        return False

    def has_pending_orderbook(self, dataname: str) -> bool:
        """Return whether *dataname* has queued order book data (optional)."""
        return False

    def supports_live_ticks(self, dataname: str) -> bool:
        """Return whether the store can stream live ticks for *dataname* (optional)."""
        return False

    def supports_live_orderbook(self, dataname: str) -> bool:
        """Return whether the store can stream live order books for *dataname* (optional)."""
        return False
