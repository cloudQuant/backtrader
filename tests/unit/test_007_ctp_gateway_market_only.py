from __future__ import annotations

import importlib.util
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "examples" / "live" / "007_ctp_gateway" / "market_only_runner.py"
SPEC = importlib.util.spec_from_file_location("_test_007_market_only_runner", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
market_only = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = market_only
SPEC.loader.exec_module(market_only)


class FiniteReader:
    def __init__(self, ticks=()):
        self._ticks = list(ticks)
        self.started = False
        self.closed = False
        self.finished = False

    def start(self):
        self.started = True

    def poll(self, timeout_ms=20):
        if self._ticks:
            return self._ticks.pop(0)
        self.finished = True
        return None

    def close(self):
        self.closed = True


def _reader_factory(ticks_by_symbol=None):
    readers = []
    ticks_by_symbol = ticks_by_symbol or {}

    def make(symbol, venue):
        reader = FiniteReader(ticks_by_symbol.get(symbol, ()))
        readers.append(reader)
        return reader

    return make, readers


@pytest.mark.parametrize("strategy_name", tuple(market_only.STRATEGIES))
def test_all_007_strategies_start_without_restore_or_trading(strategy_name):
    make_reader, readers = _reader_factory()
    cerebro = market_only._create_cerebro(strategy_name, make_reader)
    results = cerebro.run(runonce=False, preload=False, exactbars=1)

    assert len(results) == 1
    strategy = results[0]
    assert strategy.market_only_started
    assert all(reader.started for reader in readers)
    assert all(reader.finished for reader in readers)
    assert type(cerebro.getbroker()) is market_only.MarketOnlyBroker
    assert not cerebro.stores
    assert not hasattr(cerebro.getbroker(), "take_over_restored_orders")
    assert not cerebro.getbroker().orders
    if strategy_name != "sa_dual_ma_gateway":
        assert strategy.p.enable_trading is False
        broker = cerebro.getbroker()
        position_reads = []

        def unexpected_position_read(*args, **kwargs):
            position_reads.append((args, kwargs))
            raise AssertionError("market-only strategy must not query the broker")

        broker.get_strategy_position = unexpected_position_read
        for symbol, _venue in market_only.STRATEGIES[strategy_name].instruments:
            assert math.isnan(strategy._refresh_position(symbol))
            assert math.isnan(strategy._position_size(symbol))
            assert math.isnan(strategy.position_cache[symbol])
            assert symbol in strategy._unreadable_positions()
        if len(market_only.STRATEGIES[strategy_name].instruments) > 1:
            assert strategy._pair_is_flat() is False
            assert strategy._pair_is_open() is False
        assert position_reads == []
    else:
        assert strategy._own_sizes() is None
    assert not cerebro.getbroker().orders


def test_market_tick_advances_feed_and_is_delivered_as_observation():
    tick = market_only.MarketOnlyTick(
        symbol="rb2701",
        price=3456.0,
        event_time=datetime(2026, 11, 26, 2, 0, tzinfo=timezone.utc),
    )
    make_reader, readers = _reader_factory({"rb2701": [tick]})
    cerebro = market_only._create_cerebro("tickbroker_single_symbol_gateway", make_reader)
    strategy = cerebro.run(runonce=False, preload=False, exactbars=1)[0]

    assert strategy.market_only_tick_count == 1
    assert strategy.datas[0]._observed_ticks == 1
    assert "rb2701" in strategy._unreadable_positions()
    assert not strategy.broker.orders
    assert all(reader.closed is False for reader in readers)  # caller owns source closure


def test_unknown_position_and_sa_order_paths_fail_closed():
    broker = market_only.MarketOnlyBroker()
    with pytest.raises(market_only.MarketOnlyPositionUnknown, match="POSITION_UNKNOWN"):
        broker.get_strategy_position(object(), object())
    with pytest.raises(market_only.MarketOnlyPositionUnknown, match="POSITION_UNKNOWN"):
        broker.getposition(object())
    with pytest.raises(market_only.MarketOnlyOrderRejected, match="MARKET_ONLY_ORDER_REJECTED"):
        broker.buy(None, None)
    with pytest.raises(market_only.MarketOnlyOrderRejected, match="MARKET_ONLY_CANCEL_REJECTED"):
        broker.cancel(None)
    assert not broker.orders

    strategy_class = market_only._guarded_strategy("sa_dual_ma_gateway")
    guard = object.__new__(strategy_class)
    with pytest.raises(market_only.MarketOnlyOrderRejected, match="MARKET_ONLY_ORDER_REJECTED"):
        guard.buy(None)
    with pytest.raises(market_only.MarketOnlyOrderRejected, match="MARKET_ONLY_CANCEL_REJECTED"):
        guard.cancel(None)


def test_each_trading_strategy_is_explicitly_disabled():
    names = [name for name in market_only.STRATEGIES if name != "sa_dual_ma_gateway"]
    assert len(names) == 10
    for name in names:
        guarded = market_only._guarded_strategy(name)
        kwargs = market_only._strategy_kwargs(guarded)
        assert kwargs["enable_trading"] is False


def test_fresh_run_identity_does_not_read_previous_stop_marker(tmp_path, monkeypatch):
    previous = tmp_path / "previous-generation"
    previous.mkdir()
    marker = previous / ".stop"
    marker.write_text("preserve", encoding="utf-8")
    new_root = tmp_path / "new-run-root"

    original_open = Path.open

    def deny_previous_open(path, *args, **kwargs):
        if path.resolve() == marker.resolve():
            raise AssertionError("previous stop marker must not be read")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_previous_open)
    first = market_only.create_market_only_run_identity(new_root)
    second = market_only.create_market_only_run_identity(new_root)

    assert first.run_id != second.run_id
    assert first.run_root != second.run_root
    assert first.run_root.parent == new_root / "market-only"
    monkeypatch.undo()
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_runner_rejects_strategy_groups_and_overlapping_same_identity_calls(tmp_path):
    with pytest.raises(market_only.MarketOnlyError, match="SINGLE_STRATEGY_RUN_REQUIRED"):
        market_only.run_market_only(
            tuple(market_only.STRATEGIES),
            connection=object(),
            run_root=tmp_path / "group",
        )
    assert not (tmp_path / "group").exists()

    assert market_only._RUN_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(market_only.MarketOnlyError, match="MARKET_ONLY_RUN_ALREADY_ACTIVE"):
            market_only.run_market_only(
                "sa_dual_ma_gateway",
                connection=object(),
                run_root=tmp_path / "overlap",
            )
    finally:
        market_only._RUN_LOCK.release()
    assert not (tmp_path / "overlap").exists()


def test_uncertain_close_blocks_next_runtime_without_clearing_retained_session(
    tmp_path, monkeypatch
):
    created_sessions = []

    class CloseFailSession:
        def __init__(self, connection):
            self.connection = connection
            self.started = False
            created_sessions.append(self)

        def start(self):
            self.started = True

        def close(self):
            raise RuntimeError("close status unknown")

    class FinishedCerebro:
        def run(self, **kwargs):
            return []

    retained = []
    monkeypatch.setattr(market_only, "_UNCERTAIN_SESSIONS", retained)
    monkeypatch.setattr(market_only, "CtpGatewayMarketOnlySession", CloseFailSession)
    monkeypatch.setattr(market_only, "_create_cerebro", lambda *args, **kwargs: FinishedCerebro())
    run_root = tmp_path / "uncertain"

    with pytest.raises(market_only.MarketOnlyError, match="MARKET_SESSION_CLOSE_UNCERTAIN"):
        market_only.run_market_only(
            "sa_dual_ma_gateway", connection=object(), run_root=run_root
        )
    assert len(created_sessions) == 1
    assert retained == [created_sessions[0]]
    run_dirs_before = tuple((run_root / "market-only").iterdir())

    with pytest.raises(
        market_only.MarketOnlyError, match="MARKET_ONLY_UNCERTAIN_SESSION_RETAINED"
    ):
        market_only.run_market_only(
            "sa_dual_ma_gateway", connection=object(), run_root=run_root
        )

    assert len(created_sessions) == 1
    assert retained == [created_sessions[0]]
    assert tuple((run_root / "market-only").iterdir()) == run_dirs_before
