"""Unit tests for backtrader/brokers/tickbroker.py - TickBroker."""

import pytest
from backtrader.brokers.tickbroker import TickBroker
from backtrader.events import TickEvent
from backtrader.order import Order


class _MockData:
    """Mock data feed for order creation."""

    def __init__(self, name='BTC/USDT'):
        """Initialize a mock data feed with a symbol name.

        Args:
            name: The trading symbol name (default: 'BTC/USDT').
        """
        self._name = name
        self.symbol = name


class TestTickBroker:
    """Test suite for TickBroker class."""

    def _make_broker(self, **kwargs):
        """Create a TickBroker instance with default cash.

        Args:
            **kwargs: Additional arguments to pass to TickBroker.

        Returns:
            TickBroker: A new broker instance with default cash of 100000.0.
        """
        defaults = dict(cash=100000.0, slippage_perc=0.0, slippage_fixed=0.0)
        defaults.update(kwargs)
        return TickBroker(**defaults)

    def _make_tick(self, price=50000.0, volume=1.0, direction='buy', ts=100.0, symbol='BTC/USDT'):
        """Create a mock TickEvent for testing.

        Args:
            price: Tick price.
            volume: Tick volume.
            direction: Tick direction ('buy' or 'sell').
            ts: Tick timestamp.
            symbol: Trading symbol.

        Returns:
            TickEvent: A new tick event with the specified parameters.
        """
        return TickEvent(timestamp=ts, symbol=symbol, price=price, volume=volume, direction=direction)

    def test_initial_state(self):
        """Test TickBroker initialization with default values."""
        b = self._make_broker()
        assert b.getcash() == 100000.0
        assert b.getvalue() == 100000.0
        assert b.pending_orders == []
        assert b.tick_count == 0

    def test_buy_market_order(self):
        """Test market buy order execution.

        Verifies that a market buy order is created, added to pending
        orders, and executed when a matching tick is processed.
        """
        b = self._make_broker()
        data = _MockData()
        order = b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)

        assert order is not None
        assert len(b.pending_orders) == 1

        tick = self._make_tick(price=50000.0)
        b.process_tick(tick)

        assert len(b.pending_orders) == 0
        assert b.getcash() < 100000.0
        pos = b.getposition(data)
        assert pos.size == 1.0

    def test_sell_market_order(self):
        """Test market sell order execution.

        Verifies that a sell order closes an existing position when
        a matching tick is processed.
        """
        b = self._make_broker()
        data = _MockData()

        # First buy
        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))

        # Then sell
        b.sell(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50100.0, ts=101.0))

        pos = b.getposition(data)
        assert pos.size == 0.0

    def test_limit_buy_order_filled(self):
        """Test limit buy order execution when price is below limit.

        Verifies that a limit buy order is filled when the market
        price goes below the limit price.
        """
        b = self._make_broker()
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, price=50000.0, exectype=Order.Limit)

        # Tick below limit -> filled
        b.process_tick(self._make_tick(price=49999.0, ts=100.0))
        assert len(b.pending_orders) == 0
        assert b.getposition(data).size == 1.0

    def test_limit_buy_order_not_filled(self):
        """Test limit buy order not filled when price is above limit.

        Verifies that a limit buy order remains pending when the
        market price stays above the limit price.
        """
        b = self._make_broker()
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, price=49000.0, exectype=Order.Limit)

        # Tick above limit -> not filled
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))
        assert len(b.pending_orders) == 1

    def test_limit_sell_order_filled(self):
        """Test limit sell order execution when price is above limit.

        Verifies that a limit sell order is filled when the market
        price goes above the limit price.
        """
        b = self._make_broker()
        data = _MockData()

        # Establish position
        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))

        # Limit sell above current
        b.sell(owner=None, data=data, size=1.0, price=50100.0, exectype=Order.Limit)
        b.process_tick(self._make_tick(price=50200.0, ts=101.0))
        assert len(b.pending_orders) == 0

    def test_stop_buy_order(self):
        """Test stop buy order execution.

        Verifies that a stop buy order is triggered when the market
        price rises above the stop price.
        """
        b = self._make_broker()
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, price=51000.0, exectype=Order.Stop)

        # Below stop -> not triggered
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))
        assert len(b.pending_orders) == 1

        # Above stop -> triggered
        b.process_tick(self._make_tick(price=51500.0, ts=101.0))
        assert len(b.pending_orders) == 0
        assert b.getposition(data).size == 1.0

    def test_stop_sell_order(self):
        """Test stop sell order execution.

        Verifies that a stop sell order is triggered when the market
        price falls below the stop price.
        """
        b = self._make_broker()
        data = _MockData()

        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))

        b.sell(owner=None, data=data, size=1.0, price=49000.0, exectype=Order.Stop)

        # Above stop
        b.process_tick(self._make_tick(price=49500.0, ts=101.0))
        assert len(b.pending_orders) == 1

        # Below stop
        b.process_tick(self._make_tick(price=48500.0, ts=102.0))
        assert len(b.pending_orders) == 0

    def test_stoplimit_buy_order(self):
        """Test stop-limit buy order execution.

        Verifies that a stop-limit buy order becomes a limit order
        when the stop price is triggered, and fills only when the
        price is at or below the limit price.
        """
        b = self._make_broker()
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, price=51000.0, plimit=51500.0, exectype=Order.StopLimit)

        # Below stop -> not triggered
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))
        assert len(b.pending_orders) == 1

        # Above stop -> triggered, but above limit
        b.process_tick(self._make_tick(price=52000.0, ts=101.0))
        assert len(b.pending_orders) == 1  # Triggered but price > limit

        # Now price falls within limit
        b.process_tick(self._make_tick(price=51200.0, ts=102.0))
        assert len(b.pending_orders) == 0

    def test_slippage_percentage(self):
        """Test percentage-based slippage on buy orders.

        Verifies that buy orders are filled at a price adjusted by
        the percentage slippage factor.
        """
        b = self._make_broker(slippage_perc=0.001)  # 0.1%
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50000.0))

        # Fill should be at 50000 + 50000*0.001 = 50050
        history = b.order_history
        assert len(history) == 1
        assert history[0]['price'] == 50050.0

    def test_slippage_fixed(self):
        """Test fixed amount slippage on buy orders.

        Verifies that buy orders are filled at a price adjusted by
        the fixed slippage amount.
        """
        b = self._make_broker(slippage_fixed=10.0)
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50000.0))

        history = b.order_history
        assert history[0]['price'] == 50010.0

    def test_sell_slippage(self):
        """Test slippage on sell orders.

        Verifies that sell orders are filled at a price adjusted
        downward by the slippage amount.
        """
        b = self._make_broker(slippage_fixed=10.0)
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))

        b.sell(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50000.0, ts=101.0))

        # Sell slippage goes the other way: 50000 - 10 = 49990
        assert b.order_history[1]['price'] == 49990.0

    def test_cancel_order(self):
        """Test cancellation of a pending order.

        Verifies that a pending limit order can be cancelled and
        is removed from the broker's pending orders list.
        """
        b = self._make_broker()
        data = _MockData()
        order = b.buy(owner=None, data=data, size=1.0, price=40000.0, exectype=Order.Limit)
        assert len(b.pending_orders) == 1

        b.cancel(order)
        assert len(b.pending_orders) == 0

    def test_cancel_nonexistent_order(self):
        """Test cancellation of an already filled order.

        Verifies that attempting to cancel an already filled order
        (no longer pending) is a no-op and does not raise an error.
        """
        b = self._make_broker()
        data = _MockData()
        order = b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50000.0))

        # Already filled, cancel should be no-op
        b.cancel(order)

    def test_multiple_orders_different_symbols(self):
        """Test handling orders for multiple trading symbols.

        Verifies that orders for different symbols are processed
        independently based on the tick symbol.
        """
        b = self._make_broker()
        data1 = _MockData('BTC/USDT')
        data2 = _MockData('ETH/USDT')

        b.buy(owner=None, data=data1, size=1.0, exectype=Order.Market)
        b.buy(owner=None, data=data2, size=10.0, exectype=Order.Market)

        # Only BTC tick
        b.process_tick(self._make_tick(price=50000.0, symbol='BTC/USDT'))
        assert len(b.pending_orders) == 1

        # ETH tick
        b.process_tick(self._make_tick(price=3000.0, symbol='ETH/USDT'))
        assert len(b.pending_orders) == 0

    def test_tick_count(self):
        """Test tracking of processed ticks.

        Verifies that the broker accurately counts the number of
        ticks processed.
        """
        b = self._make_broker()
        for i in range(5):
            b.process_tick(self._make_tick(ts=100.0 + i))
        assert b.tick_count == 5

    def test_notifications(self):
        """Test order status notifications.

        Verifies that the broker generates notifications for order
        submission and completion.
        """
        b = self._make_broker()
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)

        # Should have submit notification
        notif = b.get_notification()
        assert notif is not None

        b.process_tick(self._make_tick(price=50000.0))

        # Should have completed notification
        notif2 = b.get_notification()
        assert notif2 is not None

        # No more
        assert b.get_notification() is None

    def test_getvalue_with_position(self):
        """Test portfolio value calculation with an open position.

        Verifies that the broker's value calculation includes both
        cash and the current value of open positions.
        """
        b = self._make_broker()
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)
        b.process_tick(self._make_tick(price=50000.0, ts=100.0))

        # Price goes up
        b.process_tick(self._make_tick(price=51000.0, ts=101.0))
        value = b.getvalue()
        # cash = 100000 - 50000 = 50000, position = 1 * 51000 = 51000
        assert value == 50000.0 + 51000.0
