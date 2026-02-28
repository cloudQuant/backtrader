#!/usr/bin/env python
"""Live Feed Abstract Base Class.

Defines the common interface that all live trading data feed implementations
(CCXT, CTP, IB, Crypto, etc.) should conform to. Existing feeds are
**not** required to inherit from this class immediately — it serves as
a reference contract for new implementations and gradual migration.

Classes:
    LiveFeedBase: Abstract base for live-trading data feeds.
"""

from abc import ABC, abstractmethod


class LiveFeedBase(ABC):
    """Abstract base class for live-trading data feeds.

    A *live feed* streams real-time market data (ticks or bars) from a
    trading venue into backtrader's Line system. It is responsible for:

    - Connecting to the store's market data channel.
    - Aggregating ticks into OHLCV bars (if tick-based).
    - Optionally back-filling historical data on startup.
    - Signalling when live data begins (``LIVE`` status).

    Subclasses **must** implement every ``@abstractmethod``.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def start(self):
        """Connect to the store and begin receiving data."""

    @abstractmethod
    def stop(self):
        """Disconnect and release resources."""

    @abstractmethod
    def islive(self) -> bool:
        """Return ``True`` to indicate this is a live (not historical) feed."""

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    @abstractmethod
    def _load(self) -> bool:
        """Load the next bar/tick into the Line buffers.

        Returns:
            True if a new bar was loaded, False if no more data.
        """

    # ------------------------------------------------------------------
    # Optional: historical backfill
    # ------------------------------------------------------------------

    def haslivedata(self) -> bool:
        """Return True if live data is currently available in the queue."""
        return False

    def _load_history(self) -> bool:
        """Load historical bars for backfill (optional).

        Returns:
            True if a historical bar was loaded, False when done.
        """
        return False
