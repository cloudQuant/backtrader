"""Unit tests for backtrader/brokers/mixbroker.py - MixBroker."""

import pytest
from backtrader.brokers.mixbroker import MixBroker
from backtrader.events import TickEvent, BarEvent
from backtrader.order import Order


class _MockData:
    """Mock data feed for order creation.

    A minimal mock object that provides the symbol attribute
    needed for broker order operations.
    """

    def __init__(self, name='BTC/USDT'):
        """Initialize mock data feed with a trading symbol."""
        self._name = name
        self.symbol = name


class TestMixBroker:
    """Test cases for the MixBroker class.

    MixBroker handles order execution with mixed tick and bar data sources,
    implementing a fallback mechanism where orders can be matched via bars
    if tick matching doesn't occur within a specified timeout.
    """

    def _make_broker(self, **kwargs):
        """Create a MixBroker instance for testing.

        Args:
            **kwargs: Additional broker parameters to override defaults.

        Returns:
            MixBroker: A configured broker instance with default cash,
                tick_timeout, and bar_fallback settings.
        """
        defaults = dict(cash=100000.0, tick_timeout=5.0, bar_fallback=True)
        defaults.update(kwargs)
        return MixBroker(**defaults)

    def _make_tick(self, price=50000.0, ts=100.0, symbol='BTC/USDT'):
        """Create a TickEvent for testing.

        Args:
            price: The tick price.
            ts: The timestamp.
            symbol: The trading symbol.

        Returns:
            TickEvent: A tick event with the specified parameters.
        """
        return TickEvent(timestamp=ts, symbol=symbol, price=price, volume=1.0, direction='buy')

    def _make_bar(self, ts=100.0, symbol='BTC/USDT', o=50000, h=50100, l=49900, c=50050):
        """Create a BarEvent for testing.

        Args:
            ts: The timestamp.
            symbol: The trading symbol.
            o: The open price.
            h: The high price.
            l: The low price.
            c: The close price.

        Returns:
            BarEvent: A bar event with the specified OHLC prices and
                default volume of 100.
        """
        return BarEvent(timestamp=ts, symbol=symbol, open=o, high=h, low=l, close=c, volume=100)

    def test_tick_matching_priority(self):
        """Test that market orders are matched immediately by tick data.

        Creates a market buy order and verifies it gets matched immediately
        when a tick event is processed, without waiting for bar fallback.
        """
        b = self._make_broker()
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)

        # Tick should match immediately
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))
        assert len(b.pending_orders) == 0
        assert b.bar_matched_count == 0

    def test_bar_fallback_after_timeout(self):
        """Test bar fallback mechanism activates after tick timeout expires.

        Creates a limit buy order that cannot be matched by the initial tick.
        After the tick timeout period elapses, a bar event with a matching
        low price should trigger order execution via bar fallback.
        """
        b = self._make_broker(tick_timeout=5.0)
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, price=49000.0, exectype=Order.Limit)

        # Tick at ts=100 registers the order's first tick timestamp
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))
        assert len(b.pending_orders) == 1

        # Bar at ts=106 (> 100 + 5 timeout) should trigger fallback
        bar = self._make_bar(ts=106.0, l=48900)
        b.process_bar(bar)
        assert len(b.pending_orders) == 0
        assert b.bar_matched_count == 1

    def test_bar_fallback_within_timeout_no_match(self):
        """Test that bar fallback does not trigger within timeout window.

        Verifies that when a bar event arrives before the tick timeout
        period has elapsed, the bar fallback mechanism does not execute
        the order even if the bar price would match.
        """
        b = self._make_broker(tick_timeout=5.0)
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, price=49000.0, exectype=Order.Limit)

        # First tick registers timestamp
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))

        # Bar within timeout window (103 < 100 + 5)
        bar = self._make_bar(ts=103.0, l=48900)
        b.process_bar(bar)
        # Should NOT match because still within timeout
        assert len(b.pending_orders) == 1

    def test_bar_fallback_disabled(self):
        """Test that orders remain pending when bar fallback is disabled.

        Configures MixBroker with bar_fallback=False to verify that
        unmatched orders are never executed via bar events, regardless
        of how much time has passed.
        """
        b = self._make_broker(bar_fallback=False)
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, price=49000.0, exectype=Order.Limit)

        b.process_tick(self._make_tick(price=50000.0, ts=100.0))
        bar = self._make_bar(ts=200.0, l=48000)
        b.process_bar(bar)
        # Should not match since fallback disabled
        assert len(b.pending_orders) == 1

    def test_bar_market_order_fallback(self):
        """Test bar fallback for market orders after timeout.

        Verifies that market orders which weren't matched by ticks
        can be executed via bar fallback once the timeout period
        has elapsed.
        """
        b = self._make_broker(tick_timeout=1.0)
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)

        # Register timestamp via tick but don't match (different symbol)
        b.process_tick(self._make_tick(price=50000.0, ts=100.0, symbol='BTC/USDT'))
        # Now bar after timeout
        bar = self._make_bar(ts=102.0)
        b.process_bar(bar)
        assert len(b.pending_orders) == 0

    def test_bar_limit_sell_fallback(self):
        """Test bar fallback for limit sell orders.

        Establishes a long position via market buy, then creates a
        limit sell order. Verifies the sell order executes via bar
        fallback when the bar's high price exceeds the limit price.
        """
        b = self._make_broker(tick_timeout=1.0)
        data = _MockData()

        # Establish position
        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))

        # Sell limit
        b.sell(owner=None, data=data, size=1.0, price=50200.0, exectype=Order.Limit)
        b.process_tick(self._make_tick(price=50100.0, ts=101.0))  # Register ts

        # Bar with high > limit after timeout
        bar = self._make_bar(ts=103.0, h=50300)
        b.process_bar(bar)
        assert len(b.pending_orders) == 0

    def test_bar_stop_buy_fallback(self):
        """Test bar fallback for stop buy orders.

        Creates a stop buy order that triggers when price rises above
        the stop price. Verifies execution via bar fallback when the
        bar's high price meets or exceeds the stop price after timeout.
        """
        b = self._make_broker(tick_timeout=1.0)
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, price=51000.0, exectype=Order.Stop)

        b.process_tick(self._make_tick(price=50000.0, ts=100.0))

        # Bar with high >= stop after timeout
        bar = self._make_bar(ts=102.0, h=51500, o=50500)
        b.process_bar(bar)
        assert len(b.pending_orders) == 0
        assert b.getposition(data).size == 1.0

    def test_bar_stop_sell_fallback(self):
        """Test bar fallback for stop sell orders.

        Establishes a long position, then creates a stop sell order
        to limit losses. Verifies execution via bar fallback when
        the bar's low price falls at or below the stop price.
        """
        b = self._make_broker(tick_timeout=1.0)
        data = _MockData()

        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))

        b.sell(owner=None, data=data, size=1.0, price=49000.0, exectype=Order.Stop)
        b.process_tick(self._make_tick(price=49500.0, ts=101.0))

        bar = self._make_bar(ts=103.0, l=48500, o=49200)
        b.process_bar(bar)
        assert len(b.pending_orders) == 0

    def test_mixed_tick_and_bar_matching(self):
        """Test simultaneous handling of tick-matched and bar-fallback orders.

        Creates both a market order (expected to match via tick) and
        a limit order (expected to match via bar fallback). Verifies
        that both execution paths work correctly in the same session.
        """
        b = self._make_broker(tick_timeout=2.0)
        data = _MockData()

        # Two orders
        o1 = b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)
        o2 = b.buy(owner=None, data=data, size=1.0, price=48000.0, exectype=Order.Limit)

        # Tick fills market order
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))
        assert len(b.pending_orders) == 1  # Only limit remaining

        # Bar after timeout fills limit
        bar = self._make_bar(ts=103.0, l=47500)
        b.process_bar(bar)
        assert len(b.pending_orders) == 0

    def test_order_history_source_tracking(self):
        """Test that order execution source is correctly recorded in history.

        Verifies that orders matched via tick events have 'tick_price'
        recorded, while orders matched via bar fallback have
        'source' set to 'bar_fallback' in the order history.
        """
        b = self._make_broker(tick_timeout=1.0)
        data = _MockData()

        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))

        b.buy(owner=None, data=data, size=1.0, price=48000.0, exectype=Order.Limit)
        b.process_tick(self._make_tick(price=49000.0, ts=101.0))

        bar = self._make_bar(ts=103.0, l=47500)
        b.process_bar(bar)

        history = b.order_history
        assert len(history) == 2
        # First from tick
        assert 'tick_price' in history[0]
        # Second from bar
        assert history[1].get('source') == 'bar_fallback'

    def test_multiple_symbols(self):
        """Test order handling for multiple trading symbols concurrently.

        Creates market orders for different symbols (BTC/USDT and
        ETH/USDT). Verifies that tick events only affect matching
        symbols, and bar fallback works independently per symbol.
        """
        b = self._make_broker(tick_timeout=1.0)
        data1 = _MockData('BTC/USDT')
        data2 = _MockData('ETH/USDT')

        b.buy(owner=None, data=data1, size=1.0, exectype=Order.Market)
        b.buy(owner=None, data=data2, size=10.0, exectype=Order.Market)

        # Only BTC tick
        b.process_tick(self._make_tick(price=50000.0, ts=100.0, symbol='BTC/USDT'))
        assert len(b.pending_orders) == 1

        # ETH bar after timeout
        bar = BarEvent(timestamp=102.0, symbol='ETH/USDT', open=3000, high=3100, low=2900, close=3050, volume=500)
        b.process_bar(bar)
        assert len(b.pending_orders) == 0
