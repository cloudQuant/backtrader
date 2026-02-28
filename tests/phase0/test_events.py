"""Unit tests for backtrader/events.py - EventData and concrete event types."""

import pytest
from backtrader.events import (
    BarEvent,
    EventData,
    FundingEvent,
    FundingEventAdapter,
    OrderBookEventAdapter,
    OrderBookSnapshot,
    TickEvent,
    TickEventAdapter,
)


# ============================================================
# TickEvent Tests
# ============================================================

class TestTickEvent:
    """Test cases for the TickEvent class."""

    def test_basic_creation(self):
        """Test basic TickEvent object creation and attribute access."""
        tick = TickEvent(
            timestamp=1609459200.123,
            symbol='BTC/USDT',
            price=50000.5,
            volume=1.234,
            direction='buy',
        )
        assert tick.event_type == 'tick'
        assert tick.timestamp == 1609459200.123
        assert tick.symbol == 'BTC/USDT'
        assert tick.price == 50000.5
        assert tick.volume == 1.234
        assert tick.direction == 'buy'

    def test_validate_valid_tick(self):
        """Test validation passes for a valid tick event."""
        tick = TickEvent(
            timestamp=100.0, symbol='BTC/USDT',
            price=50000, volume=1.0, direction='buy'
        )
        assert tick.validate() is True

    def test_validate_zero_volume(self):
        """Test validation passes when volume is zero."""
        tick = TickEvent(
            timestamp=100.0, symbol='BTC/USDT',
            price=50000, volume=0.0, direction='sell'
        )
        assert tick.validate() is True

    def test_validate_negative_price(self):
        """Test validation fails when price is negative."""
        tick = TickEvent(
            timestamp=100.0, symbol='BTC/USDT',
            price=-1.0, volume=1.0, direction='buy'
        )
        assert tick.validate() is False

    def test_validate_zero_price(self):
        """Test validation fails when price is zero."""
        tick = TickEvent(
            timestamp=100.0, symbol='BTC/USDT',
            price=0.0, volume=1.0, direction='buy'
        )
        assert tick.validate() is False

    def test_validate_negative_volume(self):
        """Test validation fails when volume is negative."""
        tick = TickEvent(
            timestamp=100.0, symbol='BTC/USDT',
            price=50000, volume=-1.0, direction='buy'
        )
        assert tick.validate() is False

    def test_validate_invalid_direction(self):
        """Test validation fails with invalid trade direction."""
        tick = TickEvent(
            timestamp=100.0, symbol='BTC/USDT',
            price=50000, volume=1.0, direction='unknown'
        )
        assert tick.validate() is False

    def test_validate_zero_timestamp(self):
        """Test validation fails when timestamp is zero."""
        tick = TickEvent(
            timestamp=0.0, symbol='BTC/USDT',
            price=50000, volume=1.0, direction='buy'
        )
        assert tick.validate() is False

    def test_validate_empty_symbol(self):
        """Test validation fails when symbol is empty string."""
        tick = TickEvent(
            timestamp=100.0, symbol='',
            price=50000, volume=1.0, direction='buy'
        )
        assert tick.validate() is False

    def test_validate_optional_bid_ask(self):
        """Test validation passes with valid optional bid/ask data."""
        tick = TickEvent(
            timestamp=100.0, symbol='BTC/USDT',
            price=50000, volume=1.0, direction='buy',
            bid_price=49999.0, ask_price=50001.0,
            bid_volume=10.0, ask_volume=5.0,
        )
        assert tick.validate() is True

    def test_validate_negative_bid_price(self):
        """Test validation fails when bid price is negative."""
        tick = TickEvent(
            timestamp=100.0, symbol='BTC/USDT',
            price=50000, volume=1.0, direction='buy',
            bid_price=-1.0,
        )
        assert tick.validate() is False

    def test_validate_negative_ask_volume(self):
        """Test validation fails when ask volume is negative."""
        tick = TickEvent(
            timestamp=100.0, symbol='BTC/USDT',
            price=50000, volume=1.0, direction='buy',
            ask_volume=-1.0,
        )
        assert tick.validate() is False

    def test_default_values(self):
        """Test default values for optional TickEvent attributes."""
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT')
        assert tick.price == 0.0
        assert tick.volume == 0.0
        assert tick.direction == 'buy'
        assert tick.trade_id == ''
        assert tick.bid_price is None
        assert tick.exchange == ''
        assert tick.asset_type == 'spot'

    def test_local_time(self):
        """Test validation passes with valid local time."""
        tick = TickEvent(
            timestamp=100.0, symbol='BTC/USDT',
            price=50000, volume=1.0, direction='buy',
            local_time=100.5,
        )
        assert tick.local_time == 100.5
        assert tick.validate() is True

    def test_invalid_local_time(self):
        """Test validation fails when local time is negative."""
        tick = TickEvent(
            timestamp=100.0, symbol='BTC/USDT',
            price=50000, volume=1.0, direction='buy',
            local_time=-1.0,
        )
        assert tick.validate() is False


# ============================================================
# OrderBookSnapshot Tests
# ============================================================

class TestOrderBookSnapshot:
    """Test cases for the OrderBookSnapshot class."""

    def _make_ob(self, **kwargs):
        """Helper method to create an OrderBookSnapshot with default values.

        Args:
            **kwargs: Optional keyword arguments to override defaults.

        Returns:
            OrderBookSnapshot: A new order book snapshot instance.
        """
        defaults = dict(
            timestamp=100.0,
            symbol='BTC/USDT',
            bids=[(50000, 1.0), (49999, 2.0), (49998, 3.0)],
            asks=[(50001, 1.0), (50002, 2.0), (50003, 3.0)],
        )
        defaults.update(kwargs)
        return OrderBookSnapshot(**defaults)

    def test_basic_creation(self):
        """Test basic OrderBookSnapshot creation and key properties."""
        ob = self._make_ob()
        assert ob.event_type == 'orderbook'
        assert ob.best_bid == 50000
        assert ob.best_ask == 50001

    def test_spread(self):
        """Test calculation of bid-ask spread."""
        ob = self._make_ob()
        assert ob.spread == 1.0

    def test_mid_price(self):
        """Test calculation of mid price."""
        ob = self._make_ob()
        assert ob.mid_price == 50000.5

    def test_validate_valid(self):
        """Test validation passes for a valid order book snapshot."""
        ob = self._make_ob()
        assert ob.validate() is True

    def test_validate_empty_bids(self):
        """Test validation fails when bids list is empty."""
        ob = self._make_ob(bids=[])
        assert ob.validate() is False

    def test_validate_empty_asks(self):
        """Test validation fails when asks list is empty."""
        ob = self._make_ob(asks=[])
        assert ob.validate() is False

    def test_validate_bids_not_descending(self):
        """Test validation fails when bid prices are not in descending order."""
        ob = self._make_ob(bids=[(49999, 1.0), (50000, 2.0)])
        assert ob.validate() is False

    def test_validate_asks_not_ascending(self):
        """Test validation fails when ask prices are not in ascending order."""
        ob = self._make_ob(asks=[(50002, 1.0), (50001, 2.0)])
        assert ob.validate() is False

    def test_validate_negative_spread(self):
        """Test validation fails when spread is negative (crossed market)."""
        ob = self._make_ob(
            bids=[(50002, 1.0)],
            asks=[(50001, 1.0)],
        )
        assert ob.validate() is False

    def test_validate_zero_spread(self):
        """Test validation fails when spread is zero."""
        ob = self._make_ob(
            bids=[(50000, 1.0)],
            asks=[(50000, 1.0)],
        )
        assert ob.validate() is False

    def test_validate_zero_price(self):
        """Test validation fails when price is zero."""
        ob = self._make_ob(bids=[(0, 1.0)], asks=[(1, 1.0)])
        assert ob.validate() is False

    def test_validate_zero_qty(self):
        """Test validation fails when quantity is zero."""
        ob = self._make_ob(
            bids=[(50000, 0.0)],
            asks=[(50001, 1.0)],
        )
        assert ob.validate() is False

    def test_empty_ob_properties(self):
        """Test properties return None for empty order book."""
        ob = OrderBookSnapshot(timestamp=100.0, symbol='X')
        assert ob.best_bid is None
        assert ob.best_ask is None
        assert ob.spread is None
        assert ob.mid_price is None


# ============================================================
# FundingEvent Tests
# ============================================================

class TestFundingEvent:
    """Test cases for the FundingEvent class."""

    def test_basic_creation(self):
        """Test basic FundingEvent object creation."""
        f = FundingEvent(
            timestamp=100.0, symbol='BTC/USDT',
            rate=0.0001, mark_price=50000.0,
            next_funding_time=200.0,
        )
        assert f.event_type == 'funding'
        assert f.rate == 0.0001

    def test_validate_valid(self):
        """Test validation passes for a valid funding event."""
        f = FundingEvent(
            timestamp=100.0, symbol='BTC/USDT',
            rate=0.0001, mark_price=50000.0,
            next_funding_time=200.0,
        )
        assert f.validate() is True

    def test_validate_zero_mark_price(self):
        """Test validation fails when mark price is zero."""
        f = FundingEvent(
            timestamp=100.0, symbol='BTC/USDT',
            rate=0.0001, mark_price=0.0,
        )
        assert f.validate() is False

    def test_validate_extreme_rate(self):
        """Test validation fails when funding rate is too extreme."""
        f = FundingEvent(
            timestamp=100.0, symbol='BTC/USDT',
            rate=1.0, mark_price=50000.0,
        )
        assert f.validate() is False

    def test_validate_negative_rate(self):
        """Test validation passes with negative funding rate."""
        f = FundingEvent(
            timestamp=100.0, symbol='BTC/USDT',
            rate=-0.0001, mark_price=50000.0,
        )
        assert f.validate() is True

    def test_validate_next_funding_before_current(self):
        """Test validation fails when next funding time is before current time."""
        f = FundingEvent(
            timestamp=200.0, symbol='BTC/USDT',
            rate=0.0001, mark_price=50000.0,
            next_funding_time=100.0,
        )
        assert f.validate() is False


# ============================================================
# BarEvent Tests
# ============================================================

class TestBarEvent:
    """Test cases for the BarEvent class."""

    def test_basic_creation(self):
        """Test basic BarEvent object creation."""
        bar = BarEvent(
            timestamp=100.0, symbol='BTC/USDT',
            open=50000, high=50100, low=49900, close=50050,
            volume=123.45,
        )
        assert bar.event_type == 'bar'

    def test_validate_valid(self):
        """Test validation passes for a valid OHLCV bar."""
        bar = BarEvent(
            timestamp=100.0, symbol='BTC/USDT',
            open=50000, high=50100, low=49900, close=50050,
            volume=123.45,
        )
        assert bar.validate() is True

    def test_validate_high_less_than_low(self):
        """Test validation fails when high price is less than low price."""
        bar = BarEvent(
            timestamp=100.0, symbol='BTC/USDT',
            open=50000, high=49900, low=50100, close=50050,
            volume=100,
        )
        assert bar.validate() is False

    def test_validate_high_less_than_open(self):
        """Test validation fails when high price is less than open price."""
        bar = BarEvent(
            timestamp=100.0, symbol='BTC/USDT',
            open=50200, high=50100, low=49900, close=50050,
            volume=100,
        )
        assert bar.validate() is False

    def test_validate_low_greater_than_close(self):
        """Test validation fails when low price is greater than close price."""
        bar = BarEvent(
            timestamp=100.0, symbol='BTC/USDT',
            open=50000, high=50100, low=50060, close=50050,
            volume=100,
        )
        assert bar.validate() is False

    def test_validate_negative_volume(self):
        """Test validation fails when volume is negative."""
        bar = BarEvent(
            timestamp=100.0, symbol='BTC/USDT',
            open=50000, high=50100, low=49900, close=50050,
            volume=-1.0,
        )
        assert bar.validate() is False

    def test_validate_zero_price(self):
        """Test validation fails when any price is zero."""
        bar = BarEvent(
            timestamp=100.0, symbol='BTC/USDT',
            open=0, high=50100, low=49900, close=50050,
            volume=100,
        )
        assert bar.validate() is False


# ============================================================
# Adapter Tests
# ============================================================

class TestTickEventAdapter:
    """Test cases for the TickEventAdapter class."""

    def test_adapter_interface(self):
        """Test all TickEventAdapter interface methods return correct values."""
        tick = TickEvent(
            timestamp=100.0, symbol='BTC/USDT', exchange='binance',
            asset_type='spot', price=50000, volume=1.0, direction='buy',
            bid_price=49999, ask_price=50001, bid_volume=10.0, ask_volume=5.0,
            local_time=100.5,
        )
        adapter = TickEventAdapter(tick)

        assert adapter.get_event() == 'TickerEvent'
        assert adapter.get_exchange_name() == 'binance'
        assert adapter.get_symbol_name() == 'BTC/USDT'
        assert adapter.get_asset_type() == 'spot'
        assert adapter.get_server_time() == 100.0
        assert adapter.get_local_update_time() == 100.5
        assert adapter.get_last_price() == 50000
        assert adapter.get_last_volume() == 1.0
        assert adapter.get_bid_price() == 49999
        assert adapter.get_ask_price() == 50001
        assert adapter.get_bid_volume() == 10.0
        assert adapter.get_ask_volume() == 5.0

    def test_adapter_str(self):
        """Test string representation of TickEventAdapter contains key info."""
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        adapter = TickEventAdapter(tick)
        s = str(adapter)
        assert 'BTC/USDT' in s
        assert '50000' in s


class TestOrderBookEventAdapter:
    """Test cases for the OrderBookEventAdapter class."""

    def test_adapter_interface(self):
        """Test all OrderBookEventAdapter interface methods return correct values."""
        ob = OrderBookSnapshot(
            timestamp=100.0, symbol='BTC/USDT', exchange='binance',
            bids=[(50000, 1.0), (49999, 2.0)],
            asks=[(50001, 1.5), (50002, 2.5)],
        )
        adapter = OrderBookEventAdapter(ob)

        assert adapter.get_event() == 'OrderBookEvent'
        assert adapter.get_exchange_name() == 'binance'
        assert adapter.get_symbol_name() == 'BTC/USDT'
        assert adapter.get_server_time() == 100.0
        assert adapter.get_bid_price_list() == [50000, 49999]
        assert adapter.get_ask_price_list() == [50001, 50002]
        assert adapter.get_bid_volume_list() == [1.0, 2.0]
        assert adapter.get_ask_volume_list() == [1.5, 2.5]


class TestFundingEventAdapter:
    """Test cases for the FundingEventAdapter class."""

    def test_adapter_interface(self):
        """Test all FundingEventAdapter interface methods return correct values."""
        f = FundingEvent(
            timestamp=100.0, symbol='BTC/USDT', exchange='binance',
            rate=0.0001, mark_price=50000, next_funding_time=200.0,
            predicted_rate=0.00012,
        )
        adapter = FundingEventAdapter(f)

        assert adapter.get_event_type() == 'FundingEvent'
        assert adapter.get_exchange_name() == 'binance'
        assert adapter.get_symbol_name() == 'BTC/USDT'
        assert adapter.get_server_time() == 100.0
        assert adapter.get_current_funding_rate() == 0.0001
        assert adapter.get_next_funding_time() == 200.0
        assert adapter.get_next_funding_rate() == 0.00012
