from backtrader.channel import DataChannel
from backtrader.events import BarEvent, OrderBookSnapshot, TickEvent
from backtrader.feeds.mixed_channel import MixedChannel


class MemoryChannel(DataChannel):
    def __init__(self, channel_type, symbol, events):
        super().__init__(symbol=symbol, validate=False, auto_fix=False)
        self.channel_type = channel_type
        self._events = list(events)

    def load(self):
        for event in self._events:
            yield event


def test_mixed_channel_orders_same_timestamp_tick_before_orderbook_before_bar():
    symbol = "BTC/USDT"
    tick_channel = MemoryChannel(
        "tick",
        symbol,
        [TickEvent(timestamp=1.0, symbol=symbol, price=100.0, volume=1.0)],
    )
    orderbook_channel = MemoryChannel(
        "orderbook",
        symbol,
        [
            OrderBookSnapshot(
                timestamp=1.0,
                symbol=symbol,
                bids=[(100.0, 2.0)],
                asks=[(101.0, 1.0)],
            )
        ],
    )
    bars = [
        BarEvent(
            timestamp=1.0,
            symbol=symbol,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=10.0,
        )
    ]

    queue = MixedChannel(
        tick_channels=[tick_channel],
        orderbook_channels=[orderbook_channel],
        bars=[bars],
        adaptive=False,
    )

    events = list(queue)

    assert [event.channel_type for event in events] == ["tick", "orderbook", "bar"]


def test_mixed_channel_emits_non_decreasing_timestamps_across_sources():
    symbol = "BTC/USDT"
    tick_channel = MemoryChannel(
        "tick",
        symbol,
        [
            TickEvent(timestamp=2.0, symbol=symbol, price=102.0, volume=1.0),
            TickEvent(timestamp=4.0, symbol=symbol, price=104.0, volume=1.0),
        ],
    )
    orderbook_channel = MemoryChannel(
        "orderbook",
        symbol,
        [
            OrderBookSnapshot(
                timestamp=1.0,
                symbol=symbol,
                bids=[(99.0, 2.0)],
                asks=[(100.0, 1.0)],
            ),
            OrderBookSnapshot(
                timestamp=3.0,
                symbol=symbol,
                bids=[(101.0, 2.0)],
                asks=[(102.0, 1.0)],
            ),
        ],
    )
    bars = [
        BarEvent(
            timestamp=5.0,
            symbol=symbol,
            open=104.0,
            high=105.0,
            low=103.0,
            close=104.5,
            volume=20.0,
        )
    ]

    queue = MixedChannel(
        tick_channels=[tick_channel],
        orderbook_channels=[orderbook_channel],
        bars=[bars],
        adaptive=False,
    )

    timestamps = [event.timestamp for event in queue]

    assert timestamps == sorted(timestamps)
