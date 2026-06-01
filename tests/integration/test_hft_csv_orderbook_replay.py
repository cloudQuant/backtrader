from pathlib import Path

import backtrader as bt
import pytest

from backtrader.channel import StreamingEventQueue
from backtrader.channels.orderbook import OrderBookChannel
from backtrader.channels.tick import TickChannel
from backtrader.brokers.hft import QueueExchangeModel
from backtrader.brokers.tickbroker import TickBroker


class ReplayIntegrationStrategy(bt.Strategy):
    params = (("symbol", "BTC/USDT"),)

    def __init__(self):
        self.tick_seen = 0
        self.orderbook_seen = 0
        self.completed_orders = []
        self.pending_order = None
        self._data_obj = type("Data", (), {"_name": self.p.symbol, "symbol": self.p.symbol})()

    def notify_order(self, order):
        if order.status == order.Completed:
            self.completed_orders.append(
                {
                    "side": "buy" if order.isbuy() else "sell",
                    "price": order.executed.price,
                    "size": order.executed.size,
                }
            )
        if not order.alive():
            self.pending_order = None

    def notify_orderbook(self, orderbook):
        if orderbook.symbol != self.p.symbol:
            return
        self.orderbook_seen += 1
        if self.pending_order is not None:
            return
        if self.orderbook_seen == 5 and self.broker.getposition(self._data_obj).size <= 0:
            self.pending_order = self.buy(data=self._data_obj, size=0.01, exectype=0)

    def notify_tick(self, tick):
        if tick.symbol != self.p.symbol:
            return
        self.tick_seen += 1
        if self.pending_order is not None:
            return
        if self.tick_seen >= 25 and self.broker.getposition(self._data_obj).size > 0:
            self.pending_order = self.sell(data=self._data_obj, size=0.01, exectype=0)


def _copy_prefix(src: Path, dst: Path, rows: int):
    with src.open("r", encoding="utf-8") as fsrc, dst.open("w", encoding="utf-8", newline="") as fdst:
        for index, line in enumerate(fsrc):
            if index == 0:
                fdst.write(line)
                continue
            if index > rows:
                break
            fdst.write(line)


def _copy_jsonl_prefix(src: Path, dst: Path, rows: int):
    with src.open("r", encoding="utf-8") as fsrc, dst.open("w", encoding="utf-8") as fdst:
        for index, line in enumerate(fsrc, 1):
            if index > rows:
                break
            fdst.write(line)


@pytest.mark.integration
def test_tickbroker_replays_real_tick_csv_and_orderbook_jsonl(tmp_path):
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "datas" / "tick_data"
    tick_src = data_dir / "tick_BTC_USDT.csv"
    ob_src = data_dir / "orderbook_BTC_USDT.jsonl"

    tick_dst = tmp_path / tick_src.name
    ob_dst = tmp_path / ob_src.name
    _copy_prefix(tick_src, tick_dst, rows=250)
    _copy_jsonl_prefix(ob_src, ob_dst, rows=120)

    tick_channel = TickChannel(symbol="BTC/USDT", dataname=str(tick_dst), validate=True, auto_fix=True)
    orderbook_channel = OrderBookChannel(symbol="BTC/USDT", dataname=str(ob_dst), depth=20, validate=True, auto_fix=True)
    queue = StreamingEventQueue(channels=[orderbook_channel, tick_channel], preload_window=5.0)

    cerebro = bt.Cerebro()
    broker = TickBroker(cash=100000.0, exchange_model=QueueExchangeModel())
    broker.setcommission(commission=0.0, name="BTC/USDT")
    cerebro.setbroker(broker)
    cerebro.addstrategy(ReplayIntegrationStrategy, symbol="BTC/USDT")

    results = cerebro.run(channel=queue)
    strat = results[0]

    data_obj = type("Data", (), {"_name": "BTC/USDT", "symbol": "BTC/USDT"})()
    state = broker.state_values(data_obj)

    assert strat.tick_seen > 0
    assert strat.orderbook_seen > 0
    assert len(strat.completed_orders) >= 2
    assert strat.completed_orders[0]["side"] == "buy"
    assert strat.completed_orders[-1]["side"] == "sell"
    assert broker.tick_count > 0
    assert len(broker.order_history) >= 2
    assert state["num_trades"] >= 2
    assert state["trading_volume"] > 0.0
    assert broker.getposition(data_obj).size == pytest.approx(0.0)
    assert broker.getcash() != pytest.approx(100000.0)
