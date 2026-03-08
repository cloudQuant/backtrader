#!/usr/bin/env python
"""SimNow CTP live certification tests for TradeLogger runtime audit logs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path

import pytest

_TEST_FILE = Path(__file__).resolve()
_REPO_ROOT = _TEST_FILE.parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed
from tests.live.test_simnow_ctp import _started_store

_DEFAULT_CASE_TIMEOUT = 180
_CASE_TIMEOUTS = {
    "runtime_audit": 90,
    "local_error_audit": 60,
}


def _read_json_lines(path: Path):
    """Read JSON-lines log content."""
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _case_runtime_audit():
    """Verify runtime audit logs for a real submit/cancel cycle."""
    symbol = os.getenv("SIMNOW_ORDER_SYMBOL", os.getenv("SIMNOW_TICK_SYMBOL", "rb2610"))
    bar_seconds = int(os.getenv("SIMNOW_CERT_BAR_SECONDS", "5"))
    timeout_seconds = int(os.getenv("SIMNOW_CERT_TIMEOUT", "45"))
    price_offset = float(os.getenv("SIMNOW_ORDER_PRICE_OFFSET", "20"))

    with tempfile.TemporaryDirectory(prefix="simnow-trade-logger-") as log_dir:
        with _started_store(stop_on_exit=False) as (store, _config, _env_key):
            broker = BtApiBroker(store=store)
            data = BtApiFeed(
                store=store,
                dataname=symbol,
                timeframe=bt.TimeFrame.Seconds,
                compression=bar_seconds,
                backfill_start=False,
            )

            cerebro = bt.Cerebro()
            cerebro.setbroker(broker)
            cerebro.adddata(data)

            class RuntimeAuditStrategy(bt.Strategy):
                def __init__(self):
                    self.bar_count = 0
                    self.order = None
                    self.order_statuses = []
                    self.remote_event_types = set()

                def notify_store(self, msg, *args, **kwargs):
                    event = kwargs.get("event")
                    if not isinstance(event, dict):
                        return

                    event_type = str(event.get("event_type") or "")
                    if event_type in {
                        "order_status_accepted",
                        "order_status_canceled",
                        "order_status_completed",
                        "trade_execution",
                        "order_reject_remote",
                    }:
                        self.remote_event_types.add(event_type)

                def notify_order(self, order):
                    self.order_statuses.append(order.getstatusname())
                    if self.remote_event_types and order.getstatusname() in {
                        "Accepted",
                        "Partial",
                        "Completed",
                        "Canceled",
                        "Rejected",
                    }:
                        self.cerebro.runstop()

                def next(self):
                    self.bar_count += 1
                    if self.order is not None:
                        return

                    reference_price = float(self.data.close[0])
                    limit_price = max(reference_price - price_offset, 1.0)
                    self.order = self.buy(
                        size=1,
                        exectype=bt.Order.Limit,
                        price=limit_price,
                        offset="open",
                    )
                    assert self.order is not None, "Failed to create live order"
                    self.cancel(self.order)

            cerebro.addstrategy(RuntimeAuditStrategy)
            cerebro.addobserver(bt.observers.TradeLogger, log_dir=log_dir, log_format="json")

            stop_timer = threading.Timer(timeout_seconds, cerebro.runstop)
            stop_timer.daemon = True
            stop_timer.start()
            try:
                print(f"运行 live 监管日志验收: symbol={symbol} timeout={timeout_seconds}s")
                results = cerebro.run()
            finally:
                stop_timer.cancel()

        strategy = results[0] if results else None
        assert strategy is not None, "Strategy did not run"
        if strategy.bar_count <= 0:
            pytest.skip(f"No completed live bars received for {symbol} within {timeout_seconds}s")

        system_entries = _read_json_lines(Path(log_dir) / "system.log")
        monitor_entries = _read_json_lines(Path(log_dir) / "monitor.log")
        order_entries = _read_json_lines(Path(log_dir) / "order.log")

        system_events = [entry["event_type"] for entry in system_entries]
        monitor_events = [entry["event_type"] for entry in monitor_entries]
        order_statuses = {entry["status"] for entry in order_entries}

        assert "session_started" in system_events
        assert "store_connecting" in system_events
        assert "store_connected" in system_events
        assert "store_auth_success" in system_events
        assert "store_login_success" in system_events
        assert "market_data_subscribe_request" in system_events
        assert "data_status" in system_events
        assert "session_stopped" in system_events
        assert any(entry["status"] == "LIVE" for entry in system_entries if entry["event_type"] == "data_status")

        assert "order_submit_request" in monitor_events
        assert "order_submit_accepted" in monitor_events
        assert "order_cancel_request" in monitor_events
        assert "order_cancel_submitted" in monitor_events
        assert "monitoring_summary" in monitor_events

        assert order_entries, "order.log should contain at least one lifecycle entry"
        assert order_statuses & {
            "Submitted",
            "Accepted",
            "Partial",
            "Completed",
            "Canceled",
            "Rejected",
        }
        assert strategy.remote_event_types, "No remote CTP callback event was observed during audit"

        print(
            "✓ live 监管日志验收通过: bars=%d orders=%s remote=%s log_dir=%s"
            % (
                strategy.bar_count,
                strategy.order_statuses,
                sorted(strategy.remote_event_types),
                log_dir,
            )
        )


def _case_local_error_audit():
    """Verify local validation failures are captured in runtime audit logs."""
    symbol = os.getenv("SIMNOW_TICK_SYMBOL", "rb2610")
    bar_seconds = int(os.getenv("SIMNOW_CERT_BAR_SECONDS", "5"))
    timeout_seconds = int(os.getenv("SIMNOW_CERT_ERROR_TIMEOUT", "30"))

    with tempfile.TemporaryDirectory(prefix="simnow-trade-logger-error-") as log_dir:
        with _started_store(stop_on_exit=False) as (store, _config, _env_key):
            broker = BtApiBroker(
                store=store,
                contract_metadata={symbol: {"min_price_tick": 1.0}},
            )
            data = BtApiFeed(
                store=store,
                dataname=symbol,
                timeframe=bt.TimeFrame.Seconds,
                compression=bar_seconds,
                backfill_start=False,
            )

            cerebro = bt.Cerebro()
            cerebro.setbroker(broker)
            cerebro.adddata(data)

            class ErrorAuditStrategy(bt.Strategy):
                def __init__(self):
                    self.bar_count = 0
                    self.order = None

                def next(self):
                    self.bar_count += 1
                    if self.order is not None:
                        self.cerebro.runstop()
                        return

                    reference_price = float(self.data.close[0])
                    invalid_price = max(reference_price - 0.5, 0.5)
                    self.order = self.buy(
                        size=1,
                        exectype=bt.Order.Limit,
                        price=invalid_price,
                        offset="open",
                    )
                    assert self.order is not None, "Expected a rejected local order object"

                def notify_order(self, order):
                    if order.status == bt.Order.Rejected:
                        self.cerebro.runstop()

            cerebro.addstrategy(ErrorAuditStrategy)
            cerebro.addobserver(bt.observers.TradeLogger, log_dir=log_dir, log_format="json")

            stop_timer = threading.Timer(timeout_seconds, cerebro.runstop)
            stop_timer.daemon = True
            stop_timer.start()
            try:
                print(f"运行本地拒单日志验收: symbol={symbol} timeout={timeout_seconds}s")
                results = cerebro.run()
            finally:
                stop_timer.cancel()

        strategy = results[0] if results else None
        assert strategy is not None, "Strategy did not run"
        if strategy.bar_count <= 0:
            pytest.skip(f"No completed live bars received for {symbol} within {timeout_seconds}s")

        error_entries = _read_json_lines(Path(log_dir) / "error.log")
        order_entries = _read_json_lines(Path(log_dir) / "order.log")

        error_events = [entry["event_type"] for entry in error_entries]
        error_codes = {entry["error_code"] for entry in error_entries}
        order_statuses = {entry["status"] for entry in order_entries}

        assert "order_reject_local" in error_events
        assert "order_rejected" in error_events
        assert "invalid_price_tick" in error_codes
        assert "Rejected" in order_statuses

        print("✓ 本地拒单监管日志验收通过: errors=%s log_dir=%s" % (sorted(error_events), log_dir))


_CASE_HANDLERS = {
    "runtime_audit": _case_runtime_audit,
    "local_error_audit": _case_local_error_audit,
}


def _emit_subprocess_output(completed):
    """Relay child process output into the parent pytest process."""
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)


def _run_live_case(case_name):
    """Execute a live certification case in an isolated subprocess."""
    cmd = [sys.executable, "-u", str(_TEST_FILE), "--subprocess-case", case_name]
    timeout = _CASE_TIMEOUTS.get(case_name, _DEFAULT_CASE_TIMEOUT)

    try:
        completed = subprocess.run(
            cmd,
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"SimNow certification case '{case_name}' timed out after {timeout}s: {exc}")

    _emit_subprocess_output(completed)
    if completed.returncode == 3:
        pytest.skip(f"SimNow certification case '{case_name}' skipped")
    assert completed.returncode == 0, f"SimNow certification case '{case_name}' failed"


def _run_subprocess_case(case_name):
    """Run the actual live certification case and hard-exit after completion."""
    handler = _CASE_HANDLERS.get(case_name)
    if handler is None:
        print(f"Unknown subprocess case: {case_name}", file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(2)

    try:
        handler()
    except pytest.skip.Exception as exc:
        print(f"SKIPPED: {exc}")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(3)
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


@pytest.mark.live
def test_simnow_trade_logger_runtime_audit():
    _run_live_case("runtime_audit")


@pytest.mark.live
def test_simnow_trade_logger_local_error_audit():
    _run_live_case("local_error_audit")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--subprocess-case")
    args, passthrough = parser.parse_known_args()

    if args.subprocess_case:
        _run_subprocess_case(args.subprocess_case)

    raise SystemExit(pytest.main([__file__, *passthrough]))
