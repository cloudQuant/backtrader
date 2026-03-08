"""Focused runtime-event integration tests for TradeLogger."""

from __future__ import annotations

import json

import backtrader as bt
import pytest

from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store, make_tick


def _read_json_lines(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


@pytest.mark.integration
def test_trade_logger_records_store_and_data_runtime_events(tmp_path):
    """TradeLogger should persist structured store/data runtime events."""
    client = FakeBtApiClient(
        live_ticks={
            DEFAULT_SYMBOL: [
                make_tick(0, 100.0, volume=1.0),
                make_tick(6, 101.0, volume=1.0),
                make_tick(12, 102.0, volume=1.0),
            ]
        }
    )
    store = make_store(api=client)
    data = store.getdata(
        dataname=DEFAULT_SYMBOL,
        timeframe=bt.TimeFrame.Seconds,
        compression=5,
        backfill_start=False,
    )
    broker = store.getbroker()
    cerebro = bt.Cerebro()

    class RuntimeStrategy(bt.Strategy):
        def __init__(self):
            self._routed = False

        def next(self):
            if not self._routed:
                self._routed = True
                order = self.buy(data=self.datas[0], size=1, price=101.0, exectype=bt.Order.Limit)
                self.cancel(order)
                return
            self.cerebro.runstop()

    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(RuntimeStrategy)
    cerebro.addobserver(bt.observers.TradeLogger, log_dir=str(tmp_path), log_format="json")

    results = cerebro.run()

    assert len(results) == 1

    system_entries = _read_json_lines(tmp_path / "system.log")
    monitor_entries = _read_json_lines(tmp_path / "monitor.log")

    system_events = [entry["event_type"] for entry in system_entries]
    monitor_events = [entry["event_type"] for entry in monitor_entries]

    assert "session_started" in system_events
    assert "store_connecting" in system_events
    assert "store_connected" in system_events
    assert "store_ready" in system_events
    assert "market_data_subscribe_request" in system_events
    assert "data_status" in system_events
    assert "session_stopped" in system_events

    assert any(entry["status"] == "LIVE" for entry in system_entries if entry["event_type"] == "data_status")
    assert "order_submit_request" in monitor_events
    assert "order_submit_accepted" in monitor_events
    assert "order_cancel_request" in monitor_events
    assert "order_cancel_submitted" in monitor_events
    assert "monitoring_summary" in monitor_events


@pytest.mark.integration
def test_trade_logger_records_local_rejects_in_error_log(tmp_path):
    """Local broker rejections should be persisted to error.log."""
    client = FakeBtApiClient(
        history={
            DEFAULT_SYMBOL: [
                make_bar(0, 100.0, 101.0, 99.0, 100.5),
                make_bar(1, 100.5, 102.0, 100.0, 101.0),
                make_bar(2, 101.0, 102.5, 100.5, 101.5),
            ]
        }
    )
    store = make_store(
        api=client,
        contract_metadata={DEFAULT_SYMBOL: {"min_price_tick": 0.5}},
    )
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()
    cerebro = bt.Cerebro()

    class RejectingStrategy(bt.Strategy):
        def __init__(self):
            self._sent = False

        def next(self):
            if not self._sent:
                self._sent = True
                self.buy(data=self.datas[0], size=1, price=100.3, exectype=bt.Order.Limit)
                return
            self.cerebro.runstop()

    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(RejectingStrategy)
    cerebro.addobserver(bt.observers.TradeLogger, log_dir=str(tmp_path), log_format="json")

    results = cerebro.run()

    assert len(results) == 1

    error_entries = _read_json_lines(tmp_path / "error.log")
    error_events = [entry["event_type"] for entry in error_entries]

    assert "order_reject_local" in error_events
    assert "order_rejected" in error_events
    assert any(entry["error_code"] == "invalid_price_tick" for entry in error_entries)
