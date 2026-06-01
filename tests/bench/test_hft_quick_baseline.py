from pathlib import Path
import threading
import time

import backtrader as bt
import pytest

from backtrader.channel import StreamingEventQueue
from backtrader.channels.orderbook import OrderBookChannel
from backtrader.channels.tick import TickChannel
from backtrader.brokers.hft import QueueExchangeModel
from backtrader.brokers.tickbroker import TickBroker
from tests.test_utils.hft_scenarios import compare_scenario, get_hft_scenario_specs


class QuickReplayStrategy(bt.Strategy):
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


def _copy_csv_prefix(src: Path, dst: Path, rows: int):
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


def _run_cerebro_with_timeout(cerebro, channel, timeout=5.0):
    timed_out = threading.Event()

    def _stop():
        timed_out.set()
        cerebro.runstop()

    stop_timer = threading.Timer(timeout, _stop)
    stop_timer.daemon = True
    stop_timer.start()
    try:
        return cerebro.run(channel=channel), timed_out.is_set()
    finally:
        stop_timer.cancel()


@pytest.mark.priority_p0
@pytest.mark.integration
def test_hft_quick_replay_baseline_under_15_seconds(tmp_path):
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "datas" / "tick_data"
    tick_src = data_dir / "tick_BTC_USDT.csv"
    orderbook_src = data_dir / "orderbook_BTC_USDT.jsonl"

    tick_dst = tmp_path / tick_src.name
    orderbook_dst = tmp_path / orderbook_src.name
    _copy_csv_prefix(tick_src, tick_dst, rows=250)
    _copy_jsonl_prefix(orderbook_src, orderbook_dst, rows=120)

    tick_channel = TickChannel(symbol="BTC/USDT", dataname=str(tick_dst), validate=True, auto_fix=True)
    orderbook_channel = OrderBookChannel(symbol="BTC/USDT", dataname=str(orderbook_dst), depth=20, validate=True, auto_fix=True)
    queue = StreamingEventQueue(channels=[orderbook_channel, tick_channel], preload_window=5.0)

    cerebro = bt.Cerebro()
    broker = TickBroker(cash=100000.0, exchange_model=QueueExchangeModel())
    broker.setcommission(commission=0.0, name="BTC/USDT")
    cerebro.setbroker(broker)
    cerebro.addstrategy(QuickReplayStrategy, symbol="BTC/USDT")

    start = time.perf_counter()
    results, timed_out = _run_cerebro_with_timeout(cerebro, queue, timeout=5.0)
    elapsed = time.perf_counter() - start
    strategy = results[0]

    data_obj = type("Data", (), {"_name": "BTC/USDT", "symbol": "BTC/USDT"})()
    state = broker.state_values(data_obj)

    assert timed_out is False
    assert elapsed < 15.0, f"elapsed {elapsed:.2f}s exceeds 15s quick baseline"
    assert strategy.tick_seen > 0
    assert strategy.orderbook_seen > 0
    assert len(strategy.completed_orders) >= 2
    assert strategy.completed_orders[0]["side"] == "buy"
    assert strategy.completed_orders[-1]["side"] == "sell"
    assert broker.tick_count > 0
    assert len(broker.order_history) >= 2
    assert state["num_trades"] >= 2
    assert state["trading_volume"] > 0.0
    assert broker.getposition(data_obj).size == pytest.approx(0.0)
    assert broker.getcash() != pytest.approx(100000.0)


@pytest.mark.priority_p0
@pytest.mark.parametrize("scenario_spec", get_hft_scenario_specs(), ids=lambda spec: spec.name)
def test_hft_strategy_scenarios_are_in_quick_baseline_and_match_reference(scenario_spec):
    start = time.perf_counter()
    result = compare_scenario(scenario_spec)
    elapsed = time.perf_counter() - start

    assert elapsed < 15.0, f"scenario {scenario_spec.name} elapsed {elapsed:.2f}s exceeds 15s quick baseline"
    assert result["matches"] == {
        "cash": True,
        "position": True,
        "fills": True,
        "trade_count": True,
    }
    assert result["trade_count"] > 0
