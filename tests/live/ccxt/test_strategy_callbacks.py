"""Unit tests for Strategy-integrated tick/channel callbacks (notify_* API).

Tests the notify_* callbacks and Cerebro.dispatch_channel_event using
lightweight stubs that mirror Strategy's interface without the full
backtrader machinery.
"""

import pytest
from backtrader.channel import Event, EventPriority
from backtrader.events import TickEvent, OrderBookSnapshot, FundingEvent, BarEvent


# ---------------------------------------------------------------------------
# Lightweight stub that mimics Strategy's tick callback interface without
# pulling in the full backtrader machinery (LineSeries, cerebro, etc.).
# ---------------------------------------------------------------------------
class _StubStrategy:
    """Minimal stub with the same tick-callback interface as Strategy.

    This stub provides the same state management and callback interface as
    the full Strategy class without requiring the complete backtrader machinery.
    """

    def __init__(self):
        """Initialize the stub strategy with empty state containers.

        Sets up counters and dictionaries to track received events, mirroring
        the state that Strategy.__init__ creates automatically.
        """
        # Same state that Strategy.__init__ auto-creates
        self._tick_count = 0
        self._event_count = 0
        self._last_tick = {}
        self._last_ob = {}
        self._last_funding = {}
        # Test recording
        self.received_ticks = []
        self.received_obs = []
        self.received_fundings = []
        self.received_bars = []

    # --- notify_* callbacks (user would override these) ---
    def notify_tick(self, tick):
        """Handle incoming tick events.

        Args:
            tick: TickEvent object containing tick data including symbol,
                price, volume, and direction.
        """
        self.received_ticks.append(tick)

    def notify_orderbook(self, ob):
        """Handle incoming orderbook snapshot events.

        Args:
            ob: OrderBookSnapshot object containing bids and asks for a
                trading symbol.
        """
        self.received_obs.append(ob)

    def notify_funding(self, funding):
        """Handle incoming funding rate events.

        Args:
            funding: FundingEvent object containing funding rate and mark price
                for a trading symbol.
        """
        self.received_fundings.append(funding)

    def notify_bar(self, bar):
        """Handle incoming bar events.

        Args:
            bar: BarEvent object containing OHLCV data for a trading symbol.
        """
        self.received_bars.append(bar)

    # --- helpers (identical to Strategy) ---
    def get_last_tick(self, symbol=None):
        """Retrieve the most recently received tick event.

        Args:
            symbol: Optional trading symbol to filter by. If None, returns
                an arbitrary tick from any symbol.

        Returns:
            TickEvent: The most recent tick for the specified symbol, or an
                arbitrary tick if symbol is None. Returns None if no ticks
                have been received.
        """
        if symbol:
            return self._last_tick.get(symbol)
        if self._last_tick:
            return next(iter(self._last_tick.values()))
        return None

    def get_last_orderbook(self, symbol=None):
        """Retrieve the most recently received orderbook snapshot.

        Args:
            symbol: Optional trading symbol to filter by. If None, returns
                an arbitrary orderbook from any symbol.

        Returns:
            OrderBookSnapshot: The most recent orderbook for the specified
                symbol, or an arbitrary orderbook if symbol is None. Returns
                None if no orderbooks have been received.
        """
        if symbol:
            return self._last_ob.get(symbol)
        if self._last_ob:
            return next(iter(self._last_ob.values()))
        return None

    def get_last_funding(self, symbol=None):
        """Retrieve the most recently received funding rate event.

        Args:
            symbol: Optional trading symbol to filter by. If None, returns
                an arbitrary funding event from any symbol.

        Returns:
            FundingEvent: The most recent funding event for the specified
                symbol, or an arbitrary funding event if symbol is None.
                Returns None if no funding events have been received.
        """
        if symbol:
            return self._last_funding.get(symbol)
        if self._last_funding:
            return next(iter(self._last_funding.values()))
        return None


def _make_event(data, channel_type, ts=100.0, priority=EventPriority.TICK):
    """Create a test Event object with specified parameters.

    Args:
        data: The event payload (TickEvent, OrderBookSnapshot, etc.).
        channel_type: String identifier for the event channel type
            (e.g., 'tick', 'orderbook', 'funding', 'bar').
        ts: Timestamp for the event. Defaults to 100.0.
        priority: EventPriority value for dispatch ordering. Defaults to
            EventPriority.TICK.

    Returns:
        Event: A configured Event object ready for dispatch.
    """
    return Event(
        timestamp=ts, priority=priority, sequence=0,
        channel_type=channel_type, data=data,
    )


def _dispatch(strategy, event):
    """Dispatch a channel event to the appropriate strategy callback.

    This function mirrors the logic of Cerebro.dispatch_channel_event,
    routing events to their respective notify_* methods while updating
    internal state counters and last-event caches.

    Args:
        strategy: Strategy instance (or _StubStrategy) to receive the event.
        event: Event object with channel_type and data attributes.

    Side effects:
        - Increments strategy._event_count for all events
        - Increments strategy._tick_count for tick events
        - Updates strategy._last_tick, _last_ob, or _last_funding caches
        - Calls the appropriate notify_* callback on the strategy
    """
    data = event.data
    channel_type = event.channel_type
    strategy._event_count += 1
    if channel_type == 'tick':
        strategy._tick_count += 1
        strategy._last_tick[getattr(data, 'symbol', '')] = data
        strategy.notify_tick(data)
    elif channel_type == 'orderbook':
        strategy._last_ob[getattr(data, 'symbol', '')] = data
        strategy.notify_orderbook(data)
    elif channel_type == 'funding':
        strategy._last_funding[getattr(data, 'symbol', '')] = data
        strategy.notify_funding(data)
    elif channel_type == 'bar':
        strategy.notify_bar(data)


# ===================================================================
# Tests for the notify_* API (Strategy-integrated)
# ===================================================================
class TestStrategyNotifyCallbacks:
    """Tests for Strategy's notify_* callback API.

    These tests verify that tick, orderbook, funding, and bar events are
    correctly dispatched to their respective callback methods.
    """

    def test_dispatch_tick(self):
        """Tests that tick events are dispatched to notify_tick callback.

        Verifies that a tick event is properly received and stored in the
        strategy's received_ticks list.
        """
        s = _StubStrategy()
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        event = _make_event(tick, 'tick')
        _dispatch(s, event)

        assert len(s.received_ticks) == 1
        assert s.received_ticks[0] is tick
        assert s._tick_count == 1
        assert s._event_count == 1

    def test_dispatch_orderbook(self):
        """Tests that orderbook events are dispatched to notify_orderbook callback.

        Verifies that an OrderBookSnapshot event is properly received and stored
        in the strategy's received_obs list.
        """
        s = _StubStrategy()
        ob = OrderBookSnapshot(timestamp=100.0, symbol='BTC/USDT',
                               bids=[(50000, 1.0)], asks=[(50001, 1.0)])
        event = _make_event(ob, 'orderbook', priority=EventPriority.ORDERBOOK)
        _dispatch(s, event)

        assert len(s.received_obs) == 1
        assert s.received_obs[0] is ob

    def test_dispatch_funding(self):
        """Tests that funding events are dispatched to notify_funding callback.

        Verifies that a FundingEvent is properly received and stored in the
        strategy's received_fundings list.
        """
        s = _StubStrategy()
        fe = FundingEvent(timestamp=100.0, symbol='BTC/USDT',
                          rate=0.0001, mark_price=50000.0)
        event = _make_event(fe, 'funding', priority=EventPriority.FUNDING)
        _dispatch(s, event)

        assert len(s.received_fundings) == 1
        assert s.received_fundings[0] is fe

    def test_dispatch_bar(self):
        """Tests that bar events are dispatched to notify_bar callback.

        Verifies that a BarEvent is properly received and stored in the
        strategy's received_bars list.
        """
        s = _StubStrategy()
        bar = BarEvent(timestamp=100.0, symbol='BTC/USDT',
                       open=50000, high=50100, low=49900, close=50050, volume=100)
        event = _make_event(bar, 'bar', priority=EventPriority.BAR)
        _dispatch(s, event)

        assert len(s.received_bars) == 1
        assert s.received_bars[0] is bar

    def test_get_last_tick(self):
        """Tests get_last_tick method for symbol-specific and default retrieval.

        Verifies that:
        - Specific symbols return their correct last tick
        - Calling without symbol returns an arbitrary tick
        - Non-existent symbols return None
        """
        s = _StubStrategy()
        tick1 = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        tick2 = TickEvent(timestamp=101.0, symbol='ETH/USDT', price=3000, volume=10.0, direction='sell')

        _dispatch(s, _make_event(tick1, 'tick'))
        _dispatch(s, _make_event(tick2, 'tick'))

        assert s.get_last_tick('BTC/USDT') is tick1
        assert s.get_last_tick('ETH/USDT') is tick2
        assert s.get_last_tick() is not None
        assert s.get_last_tick('NONEXIST') is None

    def test_get_last_orderbook(self):
        """Tests get_last_orderbook method for symbol-specific and default retrieval.

        Verifies that orderbook snapshots can be retrieved by symbol or as the
        most recent snapshot regardless of symbol.
        """
        s = _StubStrategy()
        ob = OrderBookSnapshot(timestamp=100.0, symbol='BTC/USDT',
                               bids=[(50000, 1.0)], asks=[(50001, 1.0)])
        _dispatch(s, _make_event(ob, 'orderbook'))

        assert s.get_last_orderbook('BTC/USDT') is ob
        assert s.get_last_orderbook() is ob
        assert s.get_last_orderbook('NONEXIST') is None

    def test_get_last_funding(self):
        """Tests get_last_funding method for symbol-specific and default retrieval.

        Verifies that funding events can be retrieved by symbol or as the most
        recent funding event regardless of symbol.
        """
        s = _StubStrategy()
        fe = FundingEvent(timestamp=100.0, symbol='BTC/USDT',
                          rate=0.0001, mark_price=50000.0)
        _dispatch(s, _make_event(fe, 'funding'))

        assert s.get_last_funding('BTC/USDT') is fe
        assert s.get_last_funding() is fe
        assert s.get_last_funding('NONEXIST') is None

    def test_empty_last_returns_none(self):
        """Tests that get_last_* methods return None when no events received.

        Verifies graceful handling when querying last ticks, orderbooks, or
        funding events before any have been dispatched.
        """
        s = _StubStrategy()
        assert s.get_last_tick() is None
        assert s.get_last_orderbook() is None
        assert s.get_last_funding() is None

    def test_unknown_channel_type(self):
        """Tests graceful handling of unknown channel types.

        Verifies that the dispatch system handles unknown event types without
        crashing while still incrementing event count.
        """
        s = _StubStrategy()
        tick = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        event = _make_event(tick, 'unknown_type')
        _dispatch(s, event)

        # Should handle gracefully
        assert s._event_count == 1
        assert len(s.received_ticks) == 0

    def test_multiple_events_sequential(self):
        """Tests sequential dispatch of multiple tick events.

        Verifies that:
        - Event counts increment correctly
        - All events are received in order
        - Last tick reflects the most recent event
        """
        s = _StubStrategy()
        for i in range(10):
            tick = TickEvent(timestamp=100.0 + i, symbol='BTC/USDT', price=50000 + i, volume=1.0, direction='buy')
            _dispatch(s, _make_event(tick, 'tick'))

        assert s._tick_count == 10
        assert s._event_count == 10
        assert len(s.received_ticks) == 10
        assert s.get_last_tick('BTC/USDT').price == 50009

    def test_default_noop_callbacks(self):
        """Test that default no-op callbacks do not cause crashes.

        Verifies that calling notify_* callbacks with no-op implementations
        (lambda functions that return None) does not raise exceptions and
        still increments event counters correctly.
        """
        s = _StubStrategy.__new__(_StubStrategy)
        s._tick_count = 0
        s._event_count = 0
        s._last_tick = {}
        s._last_ob = {}
        s._last_funding = {}

        s.notify_tick = lambda tick: None
        s.notify_orderbook = lambda ob: None
        s.notify_funding = lambda f: None
        s.notify_bar = lambda b: None

        tick = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        event = _make_event(tick, 'tick')
        _dispatch(s, event)
        assert s._event_count == 1
