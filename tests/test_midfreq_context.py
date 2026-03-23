import pytest

from backtrader.brokers.mixbroker import MixBroker
from backtrader.events import BarEvent, OrderBookSnapshot, TickEvent
from backtrader.order import Order
from backtrader.position import Position


class DummyData:
    def __init__(self, name="BTC/USDT"):
        self._name = name
        self.name = name
        self.symbol = name


def test_midfreq_context_exposes_readonly_state_views():
    symbol = "BTC/USDT"
    broker = MixBroker(cash=1000.0)
    context = broker.get_context()

    orderbook = OrderBookSnapshot(
        timestamp=1.0,
        symbol=symbol,
        bids=[(100.0, 3.0), (99.0, 1.0)],
        asks=[(101.0, 1.0), (102.0, 1.0)],
    )
    broker.process_orderbook(orderbook)

    for close in range(1, 21):
        broker.process_bar(
            BarEvent(
                timestamp=float(close + 1),
                symbol=symbol,
                open=float(close),
                high=float(close) + 0.5,
                low=max(float(close) - 0.5, 0.1),
                close=float(close),
                volume=10.0,
            )
        )

    returned_orderbook = context.get_last_orderbook(symbol)
    returned_bars = context.get_completed_bars(symbol, 20)

    returned_orderbook.bids[0] = (1.0, 1.0)
    returned_bars[0].close = -1.0

    assert context.get_last_orderbook(symbol).bids[0] == (100.0, 3.0)
    assert context.get_completed_bars(symbol, 20)[0].close == 1.0
    assert context.get_ob_ratio(symbol, levels=2, window=1) == pytest.approx(399.0 / 203.0)
    assert context.get_sma(symbol, 20) == pytest.approx(sum(range(1, 21)) / 20.0)
    assert context.get_last_bar(symbol).close == pytest.approx(20.0)
    assert symbol in context.get_symbols()


def test_midfreq_context_reports_account_state_after_tick_execution():
    data = DummyData()
    broker = MixBroker(cash=1000.0)
    broker.setcommission(commission=0.0, name=data.name)
    context = broker.get_context()

    order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Market)
    broker.process_tick(TickEvent(timestamp=1.0, symbol=data.symbol, price=100.0, volume=1.0))

    position = context.get_position(data.symbol)

    assert order.status == Order.Completed
    assert position is not None
    assert position.size == pytest.approx(1.0)
    assert context.get_cash() == pytest.approx(900.0)
    assert context.get_portfolio_value() == pytest.approx(1000.0)
    assert context.get_last_price(data.symbol) == pytest.approx(100.0)


def test_midfreq_context_snapshot_all_includes_symbols_with_open_positions_without_market_events():
    broker = MixBroker(cash=1000.0)
    context = broker.get_context()
    broker._positions["ETH/USDT"] = Position(size=2.0, price=88.0)

    snapshots = context.snapshot_all()

    assert "ETH/USDT" in context.get_symbols()
    assert snapshots["symbols"]["ETH/USDT"]["position"].size == pytest.approx(2.0)
    assert snapshots["symbols"]["ETH/USDT"]["position"].price == pytest.approx(88.0)
    assert snapshots["symbols"]["ETH/USDT"]["last_tick"] is None
    assert snapshots["symbols"]["ETH/USDT"]["last_bar"] is None
