"""Unit tests for backtrader/brokers/obbroker.py - OrderBookBroker."""

import pytest

from backtrader.brokers.obbroker import OrderBookBroker
from backtrader.brokers.impact_models import LinearImpactModel, SquareRootImpactModel
from backtrader.events import OrderBookSnapshot
from backtrader.order import Order


class _MockData:
    """Mock data object for testing.

    Attributes:
        _name: Internal name identifier.
        symbol: Trading symbol name.
    """

    def __init__(self, name='BTC/USDT'):
        """Initialize a mock data object.

        Args:
            name: The trading symbol name. Defaults to 'BTC/USDT'.
        """
        self._name = name
        self.symbol = name


def _make_ob(bids=None, asks=None, ts=100.0, symbol='BTC/USDT'):
    """Create an OrderBookSnapshot for testing.

    Args:
        bids: List of (price, size) tuples for bid levels. Defaults to
            [(50000, 1.0), (49999, 2.0), (49998, 3.0)].
        asks: List of (price, size) tuples for ask levels. Defaults to
            [(50001, 1.0), (50002, 2.0), (50003, 3.0)].
        ts: Timestamp for the orderbook snapshot. Defaults to 100.0.
        symbol: Trading symbol. Defaults to 'BTC/USDT'.

    Returns:
        OrderBookSnapshot: A test orderbook snapshot.
    """
    if bids is None:
        bids = [(50000, 1.0), (49999, 2.0), (49998, 3.0)]
    if asks is None:
        asks = [(50001, 1.0), (50002, 2.0), (50003, 3.0)]
    return OrderBookSnapshot(timestamp=ts, symbol=symbol, bids=bids, asks=asks)


class TestOrderBookBroker:
    """Test suite for OrderBookBroker class.

    Tests cover market orders, limit orders, partial fills, multi-level
    fills, and symbol isolation.
    """

    def _make_broker(self, **kwargs):
        """Create an OrderBookBroker instance for testing.

        Args:
            **kwargs: Additional arguments to pass to OrderBookBroker.

        Returns:
            OrderBookBroker: A broker instance with default cash of 100000.0.
        """
        defaults = dict(cash=100000.0)
        defaults.update(kwargs)
        return OrderBookBroker(**defaults)

    def test_basic_creation(self):
        """Test basic OrderBookBroker instantiation.

        Verifies that a broker can be created with the default cash amount.
        """
        b = self._make_broker()
        assert b.getcash() == 100000.0

    def test_market_buy_single_level(self):
        """Test market buy order filled at a single ask level.

        Creates a market buy order for 0.5 units and verifies it is filled
        at the best ask price (50001.0).
        """
        b = self._make_broker()
        data = _MockData()
        b.buy(owner=None, data=data, size=0.5, exectype=Order.Market)

        ob = _make_ob(asks=[(50001, 1.0), (50002, 2.0)])
        b.process_orderbook(ob)

        assert len(b.pending_orders) == 0
        pos = b.getposition(data)
        assert pos.size == 0.5
        # Filled at first ask level
        history = b.order_history
        assert abs(history[0]['price'] - 50001.0) < 0.01

    def test_market_buy_multi_level(self):
        """Test market buy order filled across multiple ask levels.

        Creates a market buy order for 2.5 units that requires walking
        up the order book. Verifies the weighted average price is correct.
        """
        b = self._make_broker()
        data = _MockData()
        b.buy(owner=None, data=data, size=2.5, exectype=Order.Market)

        ob = _make_ob(asks=[(50001, 1.0), (50002, 1.0), (50003, 1.0)])
        b.process_orderbook(ob)

        assert len(b.pending_orders) == 0
        pos = b.getposition(data)
        assert pos.size == 2.5
        # Weighted avg: (50001*1 + 50002*1 + 50003*0.5) / 2.5
        expected = (50001 * 1.0 + 50002 * 1.0 + 50003 * 0.5) / 2.5
        assert abs(b.order_history[0]['price'] - expected) < 0.01

    def test_market_sell_single_level(self):
        """Test market sell order filled at a single bid level.

        First establishes a long position via tick event, then creates a
        market sell order that is filled at the best bid price (50000.0).
        """
        b = self._make_broker()
        data = _MockData()
        # Establish position via tick
        from backtrader.events import TickEvent
        tick = TickEvent(timestamp=99.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        b.buy(owner=None, data=data, size=2.0, exectype=Order.Market)
        b.process_tick(tick)

        # Now sell via OB
        b.sell(owner=None, data=data, size=1.0, exectype=Order.Market)
        ob = _make_ob(bids=[(50000, 5.0), (49999, 5.0)])
        b.process_orderbook(ob)

        assert len(b.pending_orders) == 0
        assert abs(b.order_history[-1]['price'] - 50000.0) < 0.01

    def test_market_sell_multi_level(self):
        """Test market sell order filled across multiple bid levels.

        First establishes a long position, then creates a market sell
        order that requires walking down the order book. Verifies the
        weighted average price is correct.
        """
        b = self._make_broker()
        data = _MockData()
        from backtrader.events import TickEvent
        tick = TickEvent(timestamp=99.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        b.buy(owner=None, data=data, size=5.0, exectype=Order.Market)
        b.process_tick(tick)

        b.sell(owner=None, data=data, size=3.0, exectype=Order.Market)
        ob = _make_ob(bids=[(50000, 1.0), (49999, 1.0), (49998, 5.0)])
        b.process_orderbook(ob)

        expected = (50000 * 1.0 + 49999 * 1.0 + 49998 * 1.0) / 3.0
        assert abs(b.order_history[-1]['price'] - expected) < 0.01

    def test_limit_buy_triggered(self):
        """Test limit buy order that is immediately triggered.

        Creates a limit buy order at 50001.0 and verifies it is filled
        when an ask level exists at that price.
        """
        b = self._make_broker()
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, price=50001.0, exectype=Order.Limit)

        ob = _make_ob(asks=[(50001, 2.0)])
        b.process_orderbook(ob)
        assert len(b.pending_orders) == 0

    def test_limit_buy_not_triggered(self):
        """Test limit buy order that is not triggered.

        Creates a limit buy order at 49999.0 and verifies it remains
        pending when the best ask is higher (50001.0).
        """
        b = self._make_broker()
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, price=49999.0, exectype=Order.Limit)

        ob = _make_ob(asks=[(50001, 2.0)])
        b.process_orderbook(ob)
        assert len(b.pending_orders) == 1

    def test_partial_fill_depth(self):
        """Test market order partially filled due to insufficient depth.

        Creates a market buy order for 10.0 units but only 6.0 units are
        available in the order book. Verifies partial fill behavior when
        allow_partial is True.
        """
        b = self._make_broker()
        data = _MockData()
        b.buy(owner=None, data=data, size=10.0, exectype=Order.Market)

        # Only 6 units available in book
        ob = _make_ob(asks=[(50001, 1.0), (50002, 2.0), (50003, 3.0)])
        b.process_orderbook(ob)

        # With allow_partial=True, should fill 6 of 10
        pos = b.getposition(data)
        assert pos.size == 6.0

    def test_different_symbols_isolated(self):
        """Test that orders for different symbols remain isolated.

        Creates market orders for two different symbols (BTC/USDT and
        ETH/USDT). Verifies that processing only the BTC orderbook fills
        only the BTC order, leaving ETH order pending.
        """
        b = self._make_broker()
        data1 = _MockData('BTC/USDT')
        data2 = _MockData('ETH/USDT')

        b.buy(owner=None, data=data1, size=1.0, exectype=Order.Market)
        b.buy(owner=None, data=data2, size=1.0, exectype=Order.Market)

        # Only BTC orderbook
        ob_btc = _make_ob(symbol='BTC/USDT')
        b.process_orderbook(ob_btc)
        assert len(b.pending_orders) == 1  # ETH still pending

    def test_max_depth_levels(self):
        """Test market order respects max_depth_levels configuration.

        Creates a market buy order for 10.0 units with max_depth_levels=2.
        Verifies that only the first 2 levels of the order book are used,
        resulting in a partial fill of 3.0 units.
        """
        b = self._make_broker(max_depth_levels=2)
        data = _MockData()
        b.buy(owner=None, data=data, size=10.0, exectype=Order.Market)

        # 3 levels but max_depth_levels=2
        ob = _make_ob(asks=[(50001, 1.0), (50002, 2.0), (50003, 100.0)])
        b.process_orderbook(ob)

        # Should only fill from first 2 levels = 3 units
        pos = b.getposition(data)
        assert pos.size == 3.0


class TestImpactModels:
    """Test suite for market impact models.

    Tests cover LinearImpactModel and SquareRootImpactModel
    calculations with various parameters.
    """

    def test_linear_impact(self):
        """Test LinearImpactModel calculates impact correctly.

        Verifies that linear impact is calculated as:
        coefficient * size * price
        """
        model = LinearImpactModel(coefficient=0.001)
        impact = model.calculate_impact(price=50000, size=10.0)
        assert abs(impact - 0.001 * 10.0 * 50000) < 0.01

    def test_linear_impact_negative_size(self):
        """Test LinearImpactModel treats negative size same as positive.

        Verifies that sell orders (negative size) have the same impact
        as buy orders of the same magnitude.
        """
        model = LinearImpactModel(coefficient=0.001)
        impact = model.calculate_impact(price=50000, size=-10.0)
        assert impact == model.calculate_impact(price=50000, size=10.0)

    def test_sqrt_impact(self):
        """Test SquareRootImpactModel calculates impact correctly.

        Verifies that square root impact is calculated as:
        coefficient * sqrt(size) * price
        """
        import math
        model = SquareRootImpactModel(coefficient=0.01)
        impact = model.calculate_impact(price=50000, size=100.0)
        expected = 0.01 * math.sqrt(100.0) * 50000
        assert abs(impact - expected) < 0.01

    def test_sqrt_impact_with_daily_volume(self):
        """Test SquareRootImpactModel with daily_volume parameter.

        Verifies that square root impact with daily volume is calculated as:
        coefficient * sqrt(size / daily_volume) * price
        """
        import math
        model = SquareRootImpactModel(coefficient=0.01, daily_volume=1000.0)
        impact = model.calculate_impact(price=50000, size=100.0)
        expected = 0.01 * math.sqrt(100.0 / 1000.0) * 50000
        assert abs(impact - expected) < 0.01

    def test_sqrt_impact_zero_size(self):
        """Test SquareRootImpactModel returns zero for zero size.

        Verifies that orders with zero size have zero market impact.
        """
        model = SquareRootImpactModel(coefficient=0.01)
        assert model.calculate_impact(price=50000, size=0.0) == 0.0

    def test_ob_broker_with_impact_model(self):
        """Test OrderBookBroker applies impact model when enabled.

        Creates a broker with a LinearImpactModel and enable_impact=True.
        Verifies that the filled price includes the impact adjustment.
        """
        model = LinearImpactModel(coefficient=0.001)
        b = OrderBookBroker(cash=100000.0, impact_model=model, enable_impact=True)
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)

        ob = _make_ob(asks=[(50001, 5.0)])
        b.process_orderbook(ob)

        # Price with impact should be > 50001
        history = b.order_history
        assert history[0]['price'] > 50001.0

    def test_ob_broker_without_impact(self):
        """Test OrderBookBroker ignores impact model when disabled.

        Creates a broker with a LinearImpactModel but enable_impact=False.
        Verifies that the filled price equals the order book price without
        impact adjustment.
        """
        model = LinearImpactModel(coefficient=0.001)
        b = OrderBookBroker(cash=100000.0, impact_model=model, enable_impact=False)
        data = _MockData()
        b.buy(owner=None, data=data, size=1.0, exectype=Order.Market)

        ob = _make_ob(asks=[(50001, 5.0)])
        b.process_orderbook(ob)

        # Impact disabled, should fill at 50001
        assert abs(b.order_history[0]['price'] - 50001.0) < 0.01
