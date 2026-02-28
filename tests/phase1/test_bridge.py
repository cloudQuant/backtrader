"""Unit tests for backtrader/channels/bridge.py - ChannelBridge."""

import math

import pytest

from backtrader.channels.bridge import ChannelBridge, _BridgeLine
from backtrader.channels.tick import TickChannel
from backtrader.events import TickEvent, OrderBookSnapshot


class _FakeChannel:
    channel_type = 'tick'
    symbol = 'BTC/USDT'


class TestChannelBridge:
    """Test cases for the ChannelBridge class."""

    def test_basic_creation(self):
        """Test basic ChannelBridge creation and initial state.

        Verifies that a ChannelBridge can be created with specified fields
        and initializes with zero count and zero length.
        """
        ch = _FakeChannel()
        bridge = ChannelBridge(ch, fields=['price', 'volume'])
        assert bridge.fields == ['price', 'volume']
        assert bridge.count == 0
        assert len(bridge) == 0

    def test_update_and_access(self):
        """Test updating bridge with tick data and accessing values.

        Verifies that:
        - The bridge correctly updates from a TickEvent
        - Count and length increment properly
        - Field values are accessible via bracket notation
        """
        ch = _FakeChannel()
        bridge = ChannelBridge(ch, fields=['price', 'volume'])

        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        bridge.update(tick)

        assert bridge.count == 1
        assert len(bridge) == 1
        assert bridge['price'][0] == 50000
        assert bridge['volume'][0] == 1.0

    def test_indexing_multiple_values(self):
        """Test indexing with multiple stored values.

        Verifies that:
        - Multiple updates store values correctly
        - Index 0 returns the latest value
        - Negative indices return previous values
        """
        ch = _FakeChannel()
        bridge = ChannelBridge(ch, fields=['price'])

        for i in range(5):
            tick = TickEvent(timestamp=100.0 + i, symbol='X', price=50000 + i, volume=1.0, direction='buy')
            bridge.update(tick)

        assert bridge['price'][0] == 50004   # latest
        assert bridge['price'][-1] == 50003  # previous
        assert bridge['price'][-2] == 50002

    def test_invalid_field_key_error(self):
        """Test that accessing a non-existent field raises KeyError.

        Verifies that attempting to access a field that was not
        declared during bridge creation results in a KeyError.
        """
        ch = _FakeChannel()
        bridge = ChannelBridge(ch, fields=['price'])
        with pytest.raises(KeyError):
            bridge['nonexistent']

    def test_default_fields_tick(self):
        """Test default field selection for tick channels.

        Verifies that when no fields are specified for a tick channel,
        the bridge automatically includes price, volume, and timestamp.
        """
        ch = _FakeChannel()
        ch.channel_type = 'tick'
        bridge = ChannelBridge(ch)
        assert 'price' in bridge.fields
        assert 'volume' in bridge.fields
        assert 'timestamp' in bridge.fields

    def test_default_fields_bar(self):
        """Test default field selection for bar channels.

        Verifies that when no fields are specified for a bar channel,
        the bridge automatically includes open and close prices.
        """
        ch = _FakeChannel()
        ch.channel_type = 'bar'
        bridge = ChannelBridge(ch)
        assert 'open' in bridge.fields
        assert 'close' in bridge.fields

    def test_missing_field_nan(self):
        """Test that missing fields return NaN values.

        Verifies that when a field does not exist in the incoming
        event data, the bridge stores NaN for that field.
        """
        ch = _FakeChannel()
        bridge = ChannelBridge(ch, fields=['price', 'nonexistent_field'])

        tick = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        bridge.update(tick)

        assert bridge['price'][0] == 50000
        assert math.isnan(bridge['nonexistent_field'][0])

    def test_empty_line_returns_nan(self):
        """Test that accessing an empty bridge returns NaN.

        Verifies that when no data has been added to the bridge,
        attempting to access a field value returns NaN.
        """
        ch = _FakeChannel()
        bridge = ChannelBridge(ch, fields=['price'])
        assert math.isnan(bridge['price'][0])

    def test_future_index_returns_nan(self):
        """Test that accessing future indices returns NaN.

        Verifies that attempting to access data at an index beyond
        the current count returns NaN.
        """
        ch = _FakeChannel()
        bridge = ChannelBridge(ch, fields=['price'])
        tick = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        bridge.update(tick)
        assert math.isnan(bridge['price'][1])

    def test_out_of_range_negative_returns_nan(self):
        """Test that out-of-range negative indices return NaN.

        Verifies that attempting to access data at a negative index
        beyond the available history returns NaN.
        """
        ch = _FakeChannel()
        bridge = ChannelBridge(ch, fields=['price'])
        tick = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        bridge.update(tick)
        assert math.isnan(bridge['price'][-10])

    def test_repr(self):
        """Test the string representation of ChannelBridge.

        Verifies that the repr output includes the class name
        for identification purposes.
        """
        ch = _FakeChannel()
        bridge = ChannelBridge(ch, fields=['price'])
        r = repr(bridge)
        assert 'ChannelBridge' in r

    def test_maxlen(self):
        """Test maximum length constraint on the bridge.

        Verifies that:
        - The bridge respects the maxlen parameter
        - Older values are discarded when the limit is exceeded
        - The most recent values are retained
        """
        ch = _FakeChannel()
        bridge = ChannelBridge(ch, fields=['price'], maxlen=3)
        for i in range(5):
            tick = TickEvent(timestamp=100.0 + i, symbol='X', price=50000 + i, volume=1.0, direction='buy')
            bridge.update(tick)
        assert len(bridge) == 3
        assert bridge['price'][0] == 50004
