"""Unit tests for backtrader/channels/live_validator.py - LiveDataValidator."""

import pytest
from backtrader.channels.live_validator import LiveDataValidator
from backtrader.channel import Event, EventPriority
from backtrader.events import TickEvent, OrderBookSnapshot, FundingEvent


def _make_event(data, channel_type, channel_name='BTC/USDT', ts=100.0):
    return Event(
        timestamp=ts, priority=EventPriority.TICK, sequence=0,
        channel_type=channel_type, channel_name=channel_name, data=data,
    )


class TestLiveDataValidator:
    """Test suite for LiveDataValidator class.

    Tests the validation of live market data events including ticks,
    orderbook snapshots, and funding events for anomaly detection.
    """

    def test_basic_creation(self):
        """Test LiveDataValidator initialization with zero counters.

        Verifies that a newly created validator starts with:
        - total_validated counter set to 0
        - total_rejected counter set to 0
        """
        v = LiveDataValidator()
        assert v._total_validated == 0
        assert v._total_rejected == 0

    def test_valid_tick(self):
        """Test validation of a valid tick event.

        Verifies that a well-formed tick event with positive price and volume:
        - Passes validation (returns True)
        - Increments the total_validated counter
        - Does not increment the total_rejected counter
        """
        v = LiveDataValidator()
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50000, volume=1.0, direction='buy')
        event = _make_event(tick, 'tick', ts=100.0)
        assert v.validate(event) is True
        assert v._total_validated == 1
        assert v._total_rejected == 0

    def test_invalid_price_rejected(self):
        """Test rejection of tick with negative price.

        Verifies that a tick event with a negative price:
        - Fails validation (returns False)
        - Is recorded in the anomaly report under 'invalid_price'
        - Increments the total_rejected counter
        """
        v = LiveDataValidator()
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=-1, volume=1.0, direction='buy')
        event = _make_event(tick, 'tick', ts=100.0)
        assert v.validate(event) is False
        assert v._total_rejected == 1
        report = v.get_anomaly_report()
        assert ('tick', 'BTC/USDT') in report
        assert report[('tick', 'BTC/USDT')]['invalid_price'] == 1

    def test_zero_price_rejected(self):
        """Test rejection of tick with zero price.

        Verifies that a tick event with a zero price fails validation,
        as zero-price trades are invalid in real markets.
        """
        v = LiveDataValidator()
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=0, volume=1.0, direction='buy')
        event = _make_event(tick, 'tick', ts=100.0)
        assert v.validate(event) is False

    def test_negative_volume_rejected(self):
        """Test rejection of tick with negative volume.

        Verifies that a tick event with a negative volume fails validation,
        as negative volumes are not valid in real markets.
        """
        v = LiveDataValidator()
        tick = TickEvent(timestamp=100.0, symbol='BTC/USDT', price=50000, volume=-1.0, direction='buy')
        event = _make_event(tick, 'tick', ts=100.0)
        assert v.validate(event) is False

    def test_out_of_order_rejected(self):
        """Test rejection of out-of-order tick events.

        Verifies that tick events arriving with timestamps earlier than
        previously seen events are rejected as out-of-order anomalies.
        """
        v = LiveDataValidator()
        t1 = TickEvent(timestamp=200.0, symbol='X', price=50000, volume=1.0, direction='buy')
        t2 = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')

        e1 = _make_event(t1, 'tick', ts=200.0)
        e2 = _make_event(t2, 'tick', ts=100.0)

        assert v.validate(e1) is True
        assert v.validate(e2) is False
        report = v.get_anomaly_report()
        assert report[('tick', 'BTC/USDT')]['out_of_order'] == 1

    def test_time_jump_warning(self):
        """Test detection of anomalous time jumps in tick sequence.

        Verifies that when the time gap between consecutive ticks exceeds
        max_time_jump threshold, a warning is recorded but the event is
        still accepted (as it may be valid data after a connection gap).
        """
        v = LiveDataValidator(max_time_jump=3600)
        t1 = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        t2 = TickEvent(timestamp=100.0 + 7200, symbol='X', price=50000, volume=1.0, direction='buy')

        assert v.validate(_make_event(t1, 'tick', ts=100.0)) is True
        # Time jump > 3600s → warning but still accepted
        assert v.validate(_make_event(t2, 'tick', ts=7300.0)) is True
        report = v.get_anomaly_report()
        assert report[('tick', 'BTC/USDT')]['time_jump'] == 1

    def test_valid_orderbook(self):
        """Test validation of a valid orderbook snapshot.

        Verifies that a well-formed orderbook with bids and asks
        passes validation successfully.
        """
        v = LiveDataValidator()
        ob = OrderBookSnapshot(timestamp=100.0, symbol='BTC/USDT',
                               bids=[(50000, 1.0)], asks=[(50001, 1.0)])
        event = _make_event(ob, 'orderbook', ts=100.0)
        assert v.validate(event) is True

    def test_empty_orderbook_rejected(self):
        """Test rejection of empty orderbook snapshot.

        Verifies that an orderbook with no bids or asks fails validation
        and is recorded as an empty_orderbook anomaly.
        """
        v = LiveDataValidator()
        ob = OrderBookSnapshot(timestamp=100.0, symbol='BTC/USDT',
                               bids=[], asks=[])
        event = _make_event(ob, 'orderbook', ts=100.0)
        assert v.validate(event) is False
        report = v.get_anomaly_report()
        assert report[('orderbook', 'BTC/USDT')]['empty_orderbook'] == 1

    def test_crossed_book_warning(self):
        """Test detection of crossed orderbook condition.

        Verifies that when the best bid price exceeds the best ask price
        (a crossed book), a warning is recorded but the event is still
        accepted as this can occur in volatile markets.
        """
        v = LiveDataValidator()
        ob = OrderBookSnapshot(timestamp=100.0, symbol='BTC/USDT',
                               bids=[(50001, 1.0)], asks=[(50000, 1.0)])
        event = _make_event(ob, 'orderbook', ts=100.0)
        # Crossed book is warned but accepted
        assert v.validate(event) is True
        report = v.get_anomaly_report()
        assert report[('orderbook', 'BTC/USDT')]['crossed_book'] == 1

    def test_valid_funding(self):
        """Test validation of a valid funding rate event.

        Verifies that a well-formed funding event with a reasonable rate
        and mark price passes validation.
        """
        v = LiveDataValidator()
        fe = FundingEvent(timestamp=100.0, symbol='BTC/USDT', rate=0.0001, mark_price=50000)
        event = _make_event(fe, 'funding', ts=100.0)
        assert v.validate(event) is True

    def test_extreme_funding_rate_warning(self):
        """Test detection of extreme funding rate.

        Verifies that an abnormally high funding rate (e.g., 50%) is
        flagged as an anomaly but still accepted, as extreme rates
        can occur during high volatility.
        """
        v = LiveDataValidator()
        fe = FundingEvent(timestamp=100.0, symbol='BTC/USDT', rate=0.5, mark_price=50000)
        event = _make_event(fe, 'funding', ts=100.0)
        # Extreme rate warned but accepted
        assert v.validate(event) is True
        report = v.get_anomaly_report()
        assert report[('funding', 'BTC/USDT')]['extreme_funding_rate'] == 1

    def test_different_channels_isolated(self):
        """Test that different channels maintain separate timestamp tracking.

        Verifies that events from different channels (e.g., BTC/USDT vs
        ETH/USDT) are tracked independently, so timestamps that are
        out-of-order for one channel are valid for another.
        """
        v = LiveDataValidator()
        t1 = TickEvent(timestamp=200.0, symbol='X', price=50000, volume=1.0, direction='buy')
        t2 = TickEvent(timestamp=100.0, symbol='X', price=3000, volume=1.0, direction='buy')

        e1 = _make_event(t1, 'tick', channel_name='BTC/USDT', ts=200.0)
        e2 = _make_event(t2, 'tick', channel_name='ETH/USDT', ts=100.0)

        assert v.validate(e1) is True
        # Different channel, so ts=100 is fine (not out of order)
        assert v.validate(e2) is True

    def test_stats(self):
        """Test statistics calculation via the stats property.

        Verifies that the validator correctly calculates:
        - total_validated: Total events processed
        - total_rejected: Events that failed validation
        - rejection_rate: Ratio of rejected to validated events
        """
        v = LiveDataValidator()
        tick = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        bad = TickEvent(timestamp=100.0, symbol='X', price=-1, volume=1.0, direction='buy')

        v.validate(_make_event(tick, 'tick', ts=100.0))
        v.validate(_make_event(bad, 'tick', ts=101.0))

        stats = v.stats
        assert stats['total_validated'] == 2
        assert stats['total_rejected'] == 1
        assert stats['rejection_rate'] == 0.5

    def test_reset(self):
        """Test reset method clears all internal state.

        Verifies that calling reset() clears:
        - total_validated counter
        - total_rejected counter
        - anomaly report dictionary
        """
        v = LiveDataValidator()
        tick = TickEvent(timestamp=100.0, symbol='X', price=50000, volume=1.0, direction='buy')
        v.validate(_make_event(tick, 'tick', ts=100.0))
        assert v._total_validated == 1

        v.reset()
        assert v._total_validated == 0
        assert v._total_rejected == 0
        assert v.get_anomaly_report() == {}

    def test_repr(self):
        """Test string representation contains class name.

        Verifies that the __repr__ method returns a string containing
        'LiveDataValidator' for debugging purposes.
        """
        v = LiveDataValidator()
        r = repr(v)
        assert 'LiveDataValidator' in r

    def test_sequential_valid_events(self):
        """Test validation of a large sequence of valid events.

        Verifies that the validator can handle a large number (100) of
        sequential valid tick events without rejecting any, testing
        performance and state management.
        """
        v = LiveDataValidator()
        for i in range(100):
            tick = TickEvent(timestamp=100.0 + i, symbol='X', price=50000 + i, volume=1.0, direction='buy')
            assert v.validate(_make_event(tick, 'tick', ts=100.0 + i)) is True
        assert v._total_validated == 100
        assert v._total_rejected == 0
