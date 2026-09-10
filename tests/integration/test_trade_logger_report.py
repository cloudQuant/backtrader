"""Integration coverage for TradeLogger's generic in-memory report API."""

from __future__ import annotations

import json

import backtrader as bt
import pandas as pd
import pytest


def _dataframe():
    """Build a small broker-neutral OHLCV input for a normal Cerebro run."""
    index = pd.date_range("2024-01-02", periods=7, freq="D")
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 103.0, 102.0, 101.0, 100.0],
            "high": [101.0, 102.0, 103.0, 104.0, 103.0, 102.0, 101.0],
            "low": [99.0, 100.0, 101.0, 102.0, 101.0, 100.0, 99.0],
            "close": [100.5, 101.5, 102.5, 103.5, 102.5, 101.5, 100.5],
            "volume": [10.0] * 7,
            "openinterest": [0.0] * 7,
        },
        index=index,
    )


@pytest.mark.integration
def test_trade_logger_generic_report_is_live_json_safe_and_frozen(tmp_path):
    """A normal Cerebro run exposes a generic report without file logging."""

    class ReportingStrategy(bt.Strategy):
        """Exercise the observer contract from start, next, and stop hooks."""

        def start(self):
            self.trade_logger = getattr(self.stats, "trade_logger", None)
            assert self.trade_logger is not None
            self.final_before_stop = self.trade_logger.final_report()
            self.start_snapshot = self.trade_logger.snapshot()
            # Preloaded feeds may have their final row buffered during start;
            # a real-time report must not expose that future price as a live
            # position before the first strategy callback.
            assert self.start_snapshot["positions"] == {}

            assert self.trade_logger.update_report_context(
                {"phase": "started", "nested": {"first": True}}, namespace="strategy"
            )
            assert self.trade_logger.update_report_context(
                {"provider": "strategy-detail"}, namespace="custom"
            )

            before_invalid = self.trade_logger.snapshot()["extensions"]
            assert not self.trade_logger.update_report_context(
                {"phase": "invalid", "value": float("nan")}, namespace="strategy"
            )
            assert not self.trade_logger.update_report_context(
                {"nested": {1: "non-string-key"}}, namespace="strategy"
            )
            cycle = {}
            cycle["self"] = cycle
            assert not self.trade_logger.update_report_context(cycle, namespace="strategy")
            assert not self.trade_logger.update_report_context({}, namespace=1)
            assert self.trade_logger.snapshot()["extensions"] == before_invalid

            # These are ordinary generic observer callbacks; no CTP/store
            # implementation is involved in the report contract.
            self.trade_logger.notify_store_event(
                "test_store", event={"event_type": "test_store", "details": {"source": "test"}}
            )
            self.trade_logger.notify_data_event(self.data, "LIVE")
            self.live_reports = []

        def next(self):
            report = self.trade_logger.snapshot()
            self.live_reports.append(report)
            assert report["finalized"] is False
            assert report["portfolio"]["value"] == pytest.approx(self.broker.getvalue())
            position = self.getposition(self.data)
            if position.size:
                assert report["positions"]["asset"]["current_price"] == pytest.approx(
                    self.data.close[0]
                )

            # Returned snapshots are detached from observer-owned state.
            report["extensions"]["strategy"]["phase"] = "caller-mutated"
            assert (
                self.trade_logger.snapshot()["extensions"]["strategy"]["phase"] != "caller-mutated"
            )

            if len(self) == 1:
                self._notify_tick_to_observers(
                    {"symbol": "asset", "price": float(self.data.close[0])}
                )
                self._notify_bar_to_observers(
                    {"symbol": "asset", "close": float(self.data.close[0])}
                )
                self.buy(size=1)
            elif len(self) == 4:
                self.close()

            assert self.trade_logger.update_report_context(
                {"phase": f"bar-{len(self)}", "nested": {"latest_bar": len(self)}},
                namespace="strategy",
            )

        def stop(self):
            # Strategy.stop happens before TradeLogger.stop, so this field must
            # be present in the frozen final report.
            assert self.trade_logger.update_report_context(
                {"phase": "stopped", "nested": {"from_stop": True}, "stop_marker": "present"},
                namespace="strategy",
            )
            self.report_before_observer_stop = self.trade_logger.snapshot()

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(10_000.0)
    cerebro.adddata(bt.feeds.PandasData(dataname=_dataframe()), name="asset")
    cerebro.addstrategy(ReportingStrategy)
    cerebro.addobserver(
        bt.observers.TradeLogger,
        obsname="trade_logger",
        log_dir=str(tmp_path),
        log_orders=False,
        log_trades=False,
        log_positions=False,
        log_indicators=False,
        log_signals=False,
        log_ticks=False,
        log_bars=False,
        log_system=False,
        log_monitoring=False,
        log_errors=False,
        log_value=False,
        log_position_snapshot=False,
        report_max_records=2,
    )

    strategy = cerebro.run()[0]
    trade_logger = strategy.stats.trade_logger
    final_report = trade_logger.final_report()

    assert strategy.final_before_stop is None
    assert strategy.report_before_observer_stop["finalized"] is False
    assert final_report is not None
    assert final_report["finalized"] is True
    assert trade_logger.snapshot() == final_report
    assert trade_logger.report() == final_report

    assert final_report["strategy"]["name"] == "ReportingStrategy"
    assert final_report["portfolio"]["cash"] is not None
    assert final_report["portfolio"]["value"] is not None
    assert "asset" in final_report["positions"]
    assert final_report["event_counts"]["bars"] >= len(strategy.live_reports)
    assert final_report["event_counts"]["orders"] >= 1
    assert final_report["event_counts"]["trades"] >= 1
    assert final_report["event_counts"]["signals"] >= 1
    assert final_report["event_counts"]["ticks"] == 1
    assert final_report["event_counts"]["store"] == 1
    assert final_report["event_counts"]["data"] == 1
    assert len(final_report["order_summaries"]) <= 2
    assert len(final_report["trade_summaries"]) <= 2
    assert final_report["event_counts"]["orders"] > len(final_report["order_summaries"])
    assert final_report["records_dropped"]["orders"] > 0
    assert final_report["extensions"]["strategy"] == {
        "phase": "stopped",
        "nested": {"from_stop": True},
        "stop_marker": "present",
    }
    assert final_report["extensions"]["custom"] == {"provider": "strategy-detail"}
    assert final_report["provider"] != "strategy-detail"
    json.dumps(final_report, allow_nan=False)

    # A final report is immutable to callers and strategy context is rejected
    # after observer stop freezes the internal state.
    final_report["extensions"]["strategy"]["phase"] = "caller-mutated"
    final_report["positions"].clear()
    assert trade_logger.final_report()["extensions"]["strategy"]["phase"] == "stopped"
    assert "asset" in trade_logger.final_report()["positions"]
    assert not trade_logger.update_report_context({"late": True}, namespace="strategy")

    # Disabling every legacy file logger must not make snapshot() write files.
    assert not list(tmp_path.iterdir())


@pytest.mark.integration
def test_trade_logger_snapshot_uses_broker_local_report_cache_only(tmp_path):
    """A generic snapshot must not call live broker getter methods."""

    class GetterForbiddenBroker(bt.brokers.BackBroker):
        """Expose normal local cache while tracking live-style getter calls."""

        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.live_getter_calls = 0

        def getcash(self):
            self.live_getter_calls += 1
            return super().getcash()

        def getvalue(self, datas=None):
            self.live_getter_calls += 1
            return super().getvalue(datas=datas)

        def getposition(self, data, side=None):
            self.live_getter_calls += 1
            return super().getposition(data, side=side)

    class CacheOnlyTradeLogger(bt.observers.TradeLogger):
        """Record whether Observer.stop() invokes a live broker getter."""

        def stop(self):
            before = self._owner.broker.live_getter_calls
            super().stop()
            self.stop_live_getter_calls = self._owner.broker.live_getter_calls - before

    class CacheOnlyStrategy(bt.Strategy):
        def start(self):
            self.trade_logger = self.stats.trade_logger

        def next(self):
            before = self.broker.live_getter_calls
            snapshot = self.trade_logger.snapshot()
            assert snapshot["portfolio"] == {"cash": 10_000.0, "value": 10_000.0}
            assert snapshot["positions"] == {}
            assert self.broker.live_getter_calls == before

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(GetterForbiddenBroker(cash=10_000.0))
    cerebro.adddata(bt.feeds.PandasData(dataname=_dataframe()), name="asset")
    cerebro.addstrategy(CacheOnlyStrategy)
    cerebro.addobserver(
        CacheOnlyTradeLogger,
        obsname="trade_logger",
        log_dir=str(tmp_path),
        log_orders=False,
        log_trades=False,
        log_positions=False,
        log_indicators=False,
        log_signals=False,
        log_ticks=False,
        log_bars=False,
        log_system=False,
        log_monitoring=False,
        log_errors=False,
        log_value=False,
        log_position_snapshot=False,
    )

    strategy = cerebro.run()[0]
    report = strategy.stats.trade_logger.final_report()
    assert report is not None
    assert report["finalized"] is True
    assert report["portfolio"] == {"cash": 10_000.0, "value": 10_000.0}
    assert strategy.stats.trade_logger.stop_live_getter_calls == 0
    assert not list(tmp_path.iterdir())


@pytest.mark.integration
def test_trade_logger_report_preserves_dual_side_position_legs(tmp_path):
    """A generic report must not erase gross legs behind a net position."""

    class DualSideReportingStrategy(bt.Strategy):
        def start(self):
            self.trade_logger = self.stats.trade_logger
            self.live_dual_side_report = None

        def next(self):
            if len(self) == 1:
                self.buy(size=2, position_side="long", offset="open")
            elif len(self) == 2:
                self.sell(size=1, position_side="short", offset="open")
            elif len(self) == 3:
                self.live_dual_side_report = self.trade_logger.snapshot()

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.setbroker(bt.brokers.BackBroker(cash=10_000.0, position_mode="dual_side"))
    cerebro.adddata(bt.feeds.PandasData(dataname=_dataframe()), name="asset")
    cerebro.addstrategy(DualSideReportingStrategy)
    cerebro.addobserver(
        bt.observers.TradeLogger,
        obsname="trade_logger",
        log_dir=str(tmp_path),
        log_orders=False,
        log_trades=False,
        log_positions=False,
        log_indicators=False,
        log_signals=False,
        log_ticks=False,
        log_bars=False,
        log_system=False,
        log_monitoring=False,
        log_errors=False,
        log_value=False,
        log_position_snapshot=False,
    )

    strategy = cerebro.run()[0]
    report = strategy.stats.trade_logger.final_report()
    position = report["positions"]["asset"]
    live_position = strategy.live_dual_side_report["positions"]["asset"]

    assert position["position_mode"] == "dual_side"
    assert position["size"] == pytest.approx(1.0)
    assert position["position_legs"]["long"]["size"] == pytest.approx(2.0)
    assert position["position_legs"]["short"]["size"] == pytest.approx(1.0)
    assert live_position["position_mode"] == "dual_side"
    assert live_position["position_legs"]["long"]["size"] == pytest.approx(2.0)
    assert live_position["position_legs"]["short"]["size"] == pytest.approx(1.0)
    json.dumps(report, allow_nan=False)
    assert not list(tmp_path.iterdir())


@pytest.mark.integration
def test_trade_logger_freezes_report_when_legacy_shutdown_sink_fails(tmp_path):
    """A legacy YAML failure cannot suppress the generic final report."""

    class BrokenSnapshotTradeLogger(bt.observers.TradeLogger):
        def _save_position_snapshot(self):
            raise RuntimeError("simulated legacy snapshot failure")

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(10_000.0)
    cerebro.adddata(bt.feeds.PandasData(dataname=_dataframe()), name="asset")
    cerebro.addstrategy(bt.Strategy)
    cerebro.addobserver(
        BrokenSnapshotTradeLogger,
        obsname="trade_logger",
        log_dir=str(tmp_path),
        log_orders=False,
        log_trades=False,
        log_positions=False,
        log_indicators=False,
        log_signals=False,
        log_ticks=False,
        log_bars=False,
        log_system=False,
        log_monitoring=False,
        log_errors=False,
        log_value=False,
        log_position_snapshot=True,
    )

    strategy = cerebro.run()[0]
    report = strategy.stats.trade_logger.final_report()

    assert report is not None
    assert report["finalized"] is True
    assert report["event_counts"]["errors"] >= 1
