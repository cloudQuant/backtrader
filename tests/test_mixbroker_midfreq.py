import pytest

from backtrader.brokers.mixbroker import MixBroker
from backtrader.events import BarEvent, OrderBookSnapshot, TickEvent
from backtrader.order import Order


class DummyData:
    def __init__(self, name="BTC/USDT"):
        self._name = name
        self.name = name
        self.symbol = name


def test_mixbroker_process_bar_only_updates_low_frequency_state():
    data = DummyData()
    broker = MixBroker(cash=1000.0)
    order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Market)

    broker.process_bar(
        BarEvent(
            timestamp=2.0,
            symbol=data.symbol,
            open=100.0,
            high=102.0,
            low=99.0,
            close=101.0,
            volume=10.0,
        )
    )

    assert order.status != Order.Completed
    assert broker.pending_orders == [order]
    assert broker.order_history == []
    assert broker.get_completed_bars(data.symbol, 1)[0].close == pytest.approx(101.0)


def test_mixbroker_maintains_orderbook_window_and_bar_indicators():
    symbol = "BTC/USDT"
    broker = MixBroker(max_ob_window=2, max_bar_history=25)

    for timestamp in (1.0, 2.0, 3.0):
        broker.process_orderbook(
            OrderBookSnapshot(
                timestamp=timestamp,
                symbol=symbol,
                bids=[(100.0 + timestamp, 2.0)],
                asks=[(101.0 + timestamp, 1.0)],
            )
        )

    for close in range(1, 21):
        broker.process_bar(
            BarEvent(
                timestamp=float(close + 10),
                symbol=symbol,
                open=float(close),
                high=float(close) + 0.5,
                low=max(float(close) - 0.5, 0.1),
                close=float(close),
                volume=5.0,
            )
        )

    window = broker.get_ob_window(symbol, None)

    assert [snapshot.timestamp for snapshot in window] == [2.0, 3.0]
    assert broker.get_bar_indicator(symbol, "sma_20") == pytest.approx(sum(range(1, 21)) / 20.0)


def test_mixbroker_keeps_tick_as_only_execution_path():
    data = DummyData()
    broker = MixBroker(cash=1000.0)
    broker.setcommission(commission=0.0, name=data.name)
    order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Market)

    broker.process_tick(TickEvent(timestamp=1.0, symbol=data.symbol, price=100.0, volume=1.0))
    broker.process_bar(
        BarEvent(
            timestamp=2.0,
            symbol=data.symbol,
            open=100.0,
            high=102.0,
            low=99.0,
            close=101.0,
            volume=10.0,
        )
    )

    assert order.status == Order.Completed
    assert len(broker.order_history) == 1
    assert broker.order_history[0]["source"] == "tick"
