"""Unified event data structures for tick-level backtesting and live trading.

This module defines the base EventData class and concrete event types used
across all data channels. Events use Python dataclasses for performance
and type safety.

Event Types:
    - TickEvent: Individual trade/tick data
    - OrderBookSnapshot: Order book depth snapshot
    - FundingEvent: Funding rate data for perpetual contracts
    - BarEvent: OHLCV bar data

Example:
    Creating a tick event::

        tick = TickEvent(
            timestamp=1609459200.123,
            symbol='BTC/USDT',
            price=50000.5,
            volume=1.234,
            direction='buy'
        )
        assert tick.validate()
        assert tick.event_type == 'tick'
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class EventData(ABC):
    """Base class for all event data.

    All event types share common fields: timestamp, symbol, exchange,
    asset_type, and local_time. Subclasses must implement event_type
    property and can override validate() for type-specific checks.

    Attributes:
        timestamp: Unix timestamp in seconds (supports millisecond precision).
        symbol: Trading pair symbol (e.g., 'BTC/USDT').
        exchange: Exchange name (e.g., 'binance').
        asset_type: Asset type ('spot', 'swap', 'futures').
        local_time: Local receive timestamp (for latency tracking).
    """

    timestamp: float
    symbol: str
    exchange: str = ""
    asset_type: str = "spot"
    local_time: Optional[float] = None

    @property
    @abstractmethod
    def event_type(self) -> str:
        """Return the event type identifier string."""
        pass

    def validate(self) -> bool:
        """Validate common event fields.

        Returns:
            True if valid, False otherwise.
        """
        if not isinstance(self.timestamp, (int, float)) or self.timestamp <= 0:
            return False
        if not isinstance(self.symbol, str) or not self.symbol:
            return False
        if self.local_time is not None:
            if not isinstance(self.local_time, (int, float)) or self.local_time <= 0:
                return False
        return True


@dataclass
class TickEvent(EventData):
    """Tick/trade event data.

    Represents a single trade execution on an exchange. Compatible with
    the existing TickerData interface via adapter pattern.

    Attributes:
        price: Trade execution price.
        volume: Trade execution volume/amount.
        direction: Trade direction ('buy' or 'sell').
        trade_id: Exchange trade identifier.
        bid_price: Best bid price at time of trade.
        ask_price: Best ask price at time of trade.
        bid_volume: Best bid volume at time of trade.
        ask_volume: Best ask volume at time of trade.
    """

    price: float = 0.0
    volume: float = 0.0
    direction: str = "buy"
    trade_id: str = ""
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    bid_volume: Optional[float] = None
    ask_volume: Optional[float] = None

    @property
    def event_type(self) -> str:
        """Return the event type identifier.

        Returns:
            str: The string 'tick' for tick events.
        """
        return "tick"

    def validate(self) -> bool:
        """Validate tick-specific fields.

        Checks:
            - Common fields valid (via super)
            - Price > 0
            - Volume >= 0
            - Direction is 'buy' or 'sell'
            - Optional bid/ask prices > 0 if present
        """
        if not super().validate():
            return False
        if not isinstance(self.price, (int, float)) or self.price <= 0:
            return False
        if not isinstance(self.volume, (int, float)) or self.volume < 0:
            return False
        if self.direction not in ("buy", "sell"):
            return False
        if self.bid_price is not None and self.bid_price <= 0:
            return False
        if self.ask_price is not None and self.ask_price <= 0:
            return False
        if self.bid_volume is not None and self.bid_volume < 0:
            return False
        if self.ask_volume is not None and self.ask_volume < 0:
            return False
        return True


@dataclass
class OrderBookSnapshot(EventData):
    """Order book depth snapshot.

    Stores bid/ask depth levels as lists of (price, quantity) tuples.
    Bids are in descending price order, asks in ascending price order.

    Attributes:
        bids: List of (price, quantity) tuples, descending by price.
        asks: List of (price, quantity) tuples, ascending by price.
    """

    bids: List[Tuple[float, float]] = field(default_factory=list)
    asks: List[Tuple[float, float]] = field(default_factory=list)

    @property
    def event_type(self) -> str:
        """Return the event type identifier.

        Returns:
            str: The string 'orderbook' for order book snapshot events.
        """
        return "orderbook"

    @property
    def best_bid(self) -> Optional[float]:
        """Best (highest) bid price."""
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        """Best (lowest) ask price."""
        return self.asks[0][0] if self.asks else None

    @property
    def spread(self) -> Optional[float]:
        """Spread between best ask and best bid."""
        if self.best_bid is not None and self.best_ask is not None:
            return self.best_ask - self.best_bid
        return None

    @property
    def mid_price(self) -> Optional[float]:
        """Mid price between best bid and best ask."""
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2.0
        return None

    def validate(self) -> bool:
        """Validate order book specific fields.

        Checks:
            - Common fields valid (via super)
            - At least one bid and one ask level
            - Bids in descending order
            - Asks in ascending order
            - Best ask > best bid (positive spread)
            - All prices > 0 and quantities > 0
        """
        if not super().validate():
            return False
        if not self.bids or not self.asks:
            return False
        # Validate bid levels: descending order, positive values
        for i, (price, qty) in enumerate(self.bids):
            if price <= 0 or qty <= 0:
                return False
            if i > 0 and price > self.bids[i - 1][0]:
                return False
        # Validate ask levels: ascending order, positive values
        for i, (price, qty) in enumerate(self.asks):
            if price <= 0 or qty <= 0:
                return False
            if i > 0 and price < self.asks[i - 1][0]:
                return False
        # Spread check: best ask must be greater than best bid
        if self.bids[0][0] >= self.asks[0][0]:
            return False
        return True


@dataclass
class FundingEvent(EventData):
    """Funding rate event for perpetual contracts.

    Attributes:
        rate: Current funding rate.
        mark_price: Current mark price.
        next_funding_time: Timestamp of next funding settlement.
        predicted_rate: Predicted next funding rate.
    """

    rate: float = 0.0
    mark_price: float = 0.0
    next_funding_time: float = 0.0
    predicted_rate: float = 0.0

    @property
    def event_type(self) -> str:
        """Return the event type identifier.

        Returns:
            str: The string 'funding' for funding rate events.
        """
        return "funding"

    def validate(self) -> bool:
        """Validate funding event fields.

        Checks:
            - Common fields valid (via super)
            - Mark price > 0
            - Funding rate within reasonable range (-1, 1)
            - Next funding time > current timestamp
        """
        if not super().validate():
            return False
        if not isinstance(self.mark_price, (int, float)) or self.mark_price <= 0:
            return False
        if not isinstance(self.rate, (int, float)):
            return False
        if abs(self.rate) >= 1.0:
            return False
        if self.next_funding_time > 0 and self.next_funding_time < self.timestamp:
            return False
        return True


@dataclass
class BarEvent(EventData):
    """OHLCV bar event data.

    Compatible with existing backtrader bar-level data format.

    Attributes:
        open: Opening price.
        high: Highest price.
        low: Lowest price.
        close: Closing price.
        volume: Total volume during bar period.
        openinterest: Open interest (for futures).
    """

    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    openinterest: float = 0.0

    @property
    def event_type(self) -> str:
        """Return the event type identifier.

        Returns:
            str: The string 'bar' for OHLCV bar events.
        """
        return "bar"

    def validate(self) -> bool:
        """Validate bar event fields.

        Checks:
            - Common fields valid (via super)
            - All OHLC prices > 0
            - High >= Low
            - High >= Open, Close
            - Low <= Open, Close
            - Volume >= 0
        """
        if not super().validate():
            return False
        for price in (self.open, self.high, self.low, self.close):
            if not isinstance(price, (int, float)) or price <= 0:
                return False
        if self.high < self.low:
            return False
        if self.high < self.open or self.high < self.close:
            return False
        if self.low > self.open or self.low > self.close:
            return False
        if not isinstance(self.volume, (int, float)) or self.volume < 0:
            return False
        return True


# --- Adapter classes for backward compatibility ---


class TickEventAdapter:
    """Adapter: TickEvent -> TickerData interface.

    Wraps a TickEvent to provide the TickerData interface for backward
    compatibility with existing code that uses TickerData.

    Example::

        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        adapter = TickEventAdapter(tick)
        assert adapter.get_last_price() == 50000

    Attributes:
        event: Event type identifier string.
        _tick: The underlying TickEvent instance.
    """

    def __init__(self, tick_event: TickEvent):
        """Initialize the adapter with a TickEvent.

        Args:
            tick_event: The TickEvent instance to wrap.
        """
        self.event = "TickerEvent"
        self._tick = tick_event

    def get_event(self):
        """Return the event type identifier.

        Returns:
            str: The event type string "TickerEvent".
        """
        return self.event

    def get_exchange_name(self):
        """Return the exchange name from the tick event.

        Returns:
            str: The exchange name (e.g., 'binance').
        """
        return self._tick.exchange

    def get_local_update_time(self):
        """Return the local update timestamp.

        Returns:
            float: The local receive timestamp, or the server timestamp if
                local_time is not set.
        """
        return self._tick.local_time or self._tick.timestamp

    def get_symbol_name(self):
        """Return the trading pair symbol.

        Returns:
            str: The symbol name (e.g., 'BTC/USDT').
        """
        return self._tick.symbol

    def get_asset_type(self):
        """Return the asset type.

        Returns:
            str: The asset type ('spot', 'swap', or 'futures').
        """
        return self._tick.asset_type

    def get_server_time(self):
        """Return the server timestamp from the tick event.

        Returns:
            float: The Unix timestamp in seconds.
        """
        return self._tick.timestamp

    def get_bid_price(self):
        """Return the best bid price.

        Returns:
            Optional[float]: The best bid price, or None if not available.
        """
        return self._tick.bid_price

    def get_ask_price(self):
        """Return the best ask price.

        Returns:
            Optional[float]: The best ask price, or None if not available.
        """
        return self._tick.ask_price

    def get_bid_volume(self):
        """Return the best bid volume.

        Returns:
            Optional[float]: The best bid volume, or None if not available.
        """
        return self._tick.bid_volume

    def get_ask_volume(self):
        """Return the best ask volume.

        Returns:
            Optional[float]: The best ask volume, or None if not available.
        """
        return self._tick.ask_volume

    def get_last_price(self):
        """Return the last trade price.

        Returns:
            float: The last execution price.
        """
        return self._tick.price

    def get_last_volume(self):
        """Return the last trade volume.

        Returns:
            float: The last execution volume/amount.
        """
        return self._tick.volume

    def __str__(self):
        """Return a string representation of the adapter.

        Returns:
            str: A descriptive string showing symbol, price, volume, and direction.
        """
        return (
            f"TickEventAdapter({self._tick.symbol} "
            f"price={self._tick.price} vol={self._tick.volume} "
            f"dir={self._tick.direction})"
        )

    def __repr__(self):
        """Return the string representation for debugging.

        Returns:
            str: Same as __str__().
        """
        return self.__str__()


class OrderBookEventAdapter:
    """Adapter: OrderBookSnapshot -> OrderBookData interface.

    Wraps an OrderBookSnapshot to provide the OrderBookData interface for
    backward compatibility with existing code.

    Attributes:
        event: Event type identifier string.
        _ob: The underlying OrderBookSnapshot instance.
    """

    def __init__(self, ob_event: OrderBookSnapshot):
        """Initialize the adapter with an OrderBookSnapshot.

        Args:
            ob_event: The OrderBookSnapshot instance to wrap.
        """
        self.event = "OrderBookEvent"
        self._ob = ob_event

    def get_event(self):
        """Return the event type identifier.

        Returns:
            str: The event type string "OrderBookEvent".
        """
        return self.event

    def get_exchange_name(self):
        """Return the exchange name from the order book event.

        Returns:
            str: The exchange name (e.g., 'binance').
        """
        return self._ob.exchange

    def get_local_update_time(self):
        """Return the local update timestamp.

        Returns:
            float: The local receive timestamp, or the server timestamp if
                local_time is not set.
        """
        return self._ob.local_time or self._ob.timestamp

    def get_symbol_name(self):
        """Return the trading pair symbol.

        Returns:
            str: The symbol name (e.g., 'BTC/USDT').
        """
        return self._ob.symbol

    def get_asset_type(self):
        """Return the asset type.

        Returns:
            str: The asset type ('spot', 'swap', or 'futures').
        """
        return self._ob.asset_type

    def get_server_time(self):
        """Return the server timestamp from the order book event.

        Returns:
            float: The Unix timestamp in seconds.
        """
        return self._ob.timestamp

    def get_bid_price_list(self):
        """Return a list of bid prices.

        Returns:
            List[float]: List of bid prices in descending order.
        """
        return [b[0] for b in self._ob.bids]

    def get_ask_price_list(self):
        """Return a list of ask prices.

        Returns:
            List[float]: List of ask prices in ascending order.
        """
        return [a[0] for a in self._ob.asks]

    def get_bid_volume_list(self):
        """Return a list of bid volumes.

        Returns:
            List[float]: List of bid quantities corresponding to bid prices.
        """
        return [b[1] for b in self._ob.bids]

    def get_ask_volume_list(self):
        """Return a list of ask volumes.

        Returns:
            List[float]: List of ask quantities corresponding to ask prices.
        """
        return [a[1] for a in self._ob.asks]

    def __str__(self):
        """Return a string representation of the adapter.

        Returns:
            str: A descriptive string showing symbol, best bid, and best ask.
        """
        return f"OrderBookEventAdapter({self._ob.symbol} bid={self._ob.best_bid} ask={self._ob.best_ask})"

    def __repr__(self):
        """Return the string representation for debugging.

        Returns:
            str: Same as __str__().
        """
        return self.__str__()


class FundingEventAdapter:
    """Adapter: FundingEvent -> FundingRateData interface.

    Wraps a FundingEvent to provide the FundingRateData interface for
    backward compatibility with existing code.

    Attributes:
        event: Event type identifier string.
        _funding: The underlying FundingEvent instance.
    """

    def __init__(self, funding_event: FundingEvent):
        """Initialize the adapter with a FundingEvent.

        Args:
            funding_event: The FundingEvent instance to wrap.
        """
        self.event = "FundingEvent"
        self._funding = funding_event

    def get_event_type(self):
        """Return the event type identifier.

        Returns:
            str: The event type string "FundingEvent".
        """
        return self.event

    def get_exchange_name(self):
        """Return the exchange name from the funding event.

        Returns:
            str: The exchange name (e.g., 'binance').
        """
        return self._funding.exchange

    def get_server_time(self):
        """Return the server timestamp from the funding event.

        Returns:
            float: The Unix timestamp in seconds.
        """
        return self._funding.timestamp

    def get_local_update_time(self):
        """Return the local update timestamp.

        Returns:
            float: The local receive timestamp, or the server timestamp if
                local_time is not set.
        """
        return self._funding.local_time or self._funding.timestamp

    def get_asset_type(self):
        """Return the asset type.

        Returns:
            str: The asset type ('spot', 'swap', or 'futures').
        """
        return self._funding.asset_type

    def get_symbol_name(self):
        """Return the trading pair symbol.

        Returns:
            str: The symbol name (e.g., 'BTC/USDT').
        """
        return self._funding.symbol

    def get_current_funding_rate(self):
        """Return the current funding rate.

        Returns:
            float: The current funding rate as a decimal (e.g., 0.0001 for 0.01%).
        """
        return self._funding.rate

    def get_next_funding_time(self):
        """Return the timestamp of the next funding settlement.

        Returns:
            float: The Unix timestamp of the next funding payment.
        """
        return self._funding.next_funding_time

    def get_next_funding_rate(self):
        """Return the predicted next funding rate.

        Returns:
            float: The predicted funding rate for the next period.
        """
        return self._funding.predicted_rate

    def __str__(self):
        """Return a string representation of the adapter.

        Returns:
            str: A descriptive string showing symbol and funding rate.
        """
        return f"FundingEventAdapter({self._funding.symbol} rate={self._funding.rate})"

    def __repr__(self):
        """Return the string representation for debugging.

        Returns:
            str: Same as __str__().
        """
        return self.__str__()
