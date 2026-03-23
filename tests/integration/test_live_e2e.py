from pathlib import Path
import threading

import backtrader as bt
import pytest

from backtrader.profiles import LiveProfile, build_cerebro
from tests.fixtures.fake_btapi import (
    DEFAULT_SYMBOL,
    FakeBtApiClient,
    make_orderbook,
    make_store,
    make_tick,
)


class UnifiedProfileStrategy(bt.Strategy):
    def __init__(self):
        self.next_count = 0
        self.tick_count = 0
        self.orderbook_count = 0
        self.bar_closes = []

    def notify_tick(self, tick):
        self.tick_count += 1

    def notify_orderbook(self, orderbook):
        self.orderbook_count += 1

    def next(self):
        self.next_count += 1
        self.bar_closes.append(float(self.datas[0].close[0]))
        profile = getattr(self.cerebro, "live_profile", None)
        target_next_count = 1 if getattr(profile, "is_live", False) else 2
        if self.next_count >= target_next_count:
            self.cerebro.runstop()


@pytest.mark.integration
def test_build_cerebro_switches_same_strategy_between_backtest_and_live():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"

    backtest_profile = LiveProfile(
        mode="backtest",
        strategy=UnifiedProfileStrategy,
        dataname=str(datapath),
        broker_kwargs={"cash": 5000.0},
    )
    backtest_cerebro = build_cerebro(backtest_profile)
    backtest_result = backtest_cerebro.run()[0]

    client = FakeBtApiClient(
        live_ticks={
            DEFAULT_SYMBOL: [
                make_tick(0, 100.0, volume=1.0),
                make_tick(2, 101.0, volume=1.0),
                make_tick(6, 102.0, volume=1.0),
                make_tick(8, 103.0, volume=1.0),
            ]
        },
        live_orderbooks={
            DEFAULT_SYMBOL: [
                make_orderbook(1, 99.8, 100.2),
                make_orderbook(7, 101.8, 102.2),
            ]
        },
    )
    live_profile = LiveProfile(
        mode="live",
        strategy=UnifiedProfileStrategy,
        dataname=DEFAULT_SYMBOL,
        store_factory=lambda: make_store(api=client),
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )
    live_cerebro = build_cerebro(live_profile)
    stop_timer = threading.Timer(0.5, live_cerebro.runstop)
    stop_timer.daemon = True
    stop_timer.start()
    try:
        live_result = live_cerebro.run()[0]
    finally:
        stop_timer.cancel()

    assert isinstance(backtest_result, UnifiedProfileStrategy)
    assert isinstance(live_result, UnifiedProfileStrategy)
    assert backtest_result.next_count >= 2
    assert live_result.next_count == 1
    assert live_result.tick_count == 4
    assert live_result.orderbook_count == 2
    assert backtest_result.bar_closes
    assert live_result.bar_closes == [101.0]


@pytest.mark.integration
def test_build_cerebro_runs_multi_symbol_live_profile_end_to_end():
    symbol_a = "BTC/USDT"
    symbol_b = "ETH/USDT"

    class MultiSymbolLiveStrategy(bt.Strategy):
        def __init__(self):
            self.next_count = 0
            self.bar_snapshots = []

        def next(self):
            self.next_count += 1
            self.bar_snapshots.append(tuple(float(data.close[0]) for data in self.datas))
            self.cerebro.runstop()

    client = FakeBtApiClient(
        live_ticks={
            symbol_a: [
                make_tick(0, 100.0, volume=1.0, symbol=symbol_a),
                make_tick(6, 101.0, volume=1.0, symbol=symbol_a),
            ],
            symbol_b: [
                make_tick(1, 200.0, volume=1.0, symbol=symbol_b),
                make_tick(7, 202.0, volume=1.0, symbol=symbol_b),
            ],
        }
    )
    live_profile = LiveProfile(
        mode="live",
        frequency="hft",
        strategy=MultiSymbolLiveStrategy,
        symbols=(symbol_a, symbol_b),
        store_factory=lambda: make_store(api=client),
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )
    live_cerebro = build_cerebro(live_profile)
    stop_timer = threading.Timer(0.5, live_cerebro.runstop)
    stop_timer.daemon = True
    stop_timer.start()
    try:
        live_result = live_cerebro.run()[0]
    finally:
        stop_timer.cancel()

    assert isinstance(live_result, MultiSymbolLiveStrategy)
    assert live_result.next_count == 1
    assert live_result.bar_snapshots == [(100.0, 200.0)]


@pytest.mark.integration
def test_build_cerebro_preserves_broker_query_semantics_between_backtest_and_live():
    datapath = Path(__file__).resolve().parents[1] / "datas" / "2006-01-02-volume-min-001.txt"

    class QueryContractStrategy(bt.Strategy):
        def __init__(self):
            self.snapshots = []

        def next(self):
            position = self.broker.getposition(self.datas[0])
            self.snapshots.append(
                {
                    "cash": float(self.broker.getcash()),
                    "value": float(self.broker.getvalue()),
                    "size": float(position.size),
                    "price": float(position.price),
                }
            )
            self.cerebro.runstop()

    backtest_profile = LiveProfile(
        mode="backtest",
        strategy=QueryContractStrategy,
        dataname=str(datapath),
        broker_kwargs={"cash": 5000.0},
    )
    backtest_result = build_cerebro(backtest_profile).run()[0]

    client = FakeBtApiClient(
        balance={"cash": 1250.0, "value": 1450.0},
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2, "price": 99.5}],
        live_ticks={
            DEFAULT_SYMBOL: [
                make_tick(0, 100.0, volume=1.0),
                make_tick(6, 101.0, volume=1.0),
            ]
        },
    )
    live_profile = LiveProfile(
        mode="live",
        strategy=QueryContractStrategy,
        dataname=DEFAULT_SYMBOL,
        store_factory=lambda: make_store(api=client),
        data_kwargs={"timeframe": bt.TimeFrame.Seconds, "compression": 5, "backfill_start": False},
    )
    live_cerebro = build_cerebro(live_profile)
    stop_timer = threading.Timer(0.5, live_cerebro.runstop)
    stop_timer.daemon = True
    stop_timer.start()
    try:
        live_result = live_cerebro.run()[0]
    finally:
        stop_timer.cancel()

    assert backtest_result.snapshots == [{"cash": 5000.0, "value": 5000.0, "size": 0.0, "price": 0.0}]
    assert live_result.snapshots == [{"cash": 1250.0, "value": 1450.0, "size": 2.0, "price": 99.5}]
