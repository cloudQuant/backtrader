"""Source-owned TradeLogger configuration snapshot lifecycle tests."""

from __future__ import annotations

import datetime as dt
import re
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.observers.trade_logger import (
    TradeLogger,
    TradeLoggerConfigSnapshotError,
    TradeLoggerConfigSnapshotV1,
)


class _OneBarFeed(bt.feed.DataBase):
    """One local synthetic bar for the ordinary Cerebro observer lifecycle."""

    def __init__(self):
        super().__init__()
        self._loaded = False

    def _load(self):
        if self._loaded:
            return False
        self._loaded = True
        self.lines.datetime[0] = bt.date2num(dt.datetime(2026, 10, 9, 12, 0, 0))
        self.lines.open[0] = 100.0
        self.lines.high[0] = 101.0
        self.lines.low[0] = 99.0
        self.lines.close[0] = 100.5
        self.lines.volume[0] = 1.0
        self.lines.openinterest[0] = 0.0
        return True


class _CaptureStrategy(bt.Strategy):
    """Read the actual observer receipt after Cerebro starts its observers."""

    def start(self):
        observers = [observer for observer in self.stats.items if type(observer) is TradeLogger]
        assert len(observers) == 1
        self.trade_logger = observers[0]
        self.config_receipt = self.trade_logger.config_snapshot()
        self.same_config_receipt = self.trade_logger.config_snapshot()

    def next(self):
        current_threshold = self.trade_logger.p.submit_count_warn_threshold
        self.trade_logger.p.submit_count_warn_threshold = current_threshold + 1
        try:
            self.trade_logger.config_snapshot()
        except TradeLoggerConfigSnapshotError:
            self.changed_params_rejected = True
        else:
            self.changed_params_rejected = False
        finally:
            self.trade_logger.p.submit_count_warn_threshold = current_threshold

        report_started_at = self.trade_logger._report_started_at
        self.trade_logger._report_started_at = "changed-start-time"
        try:
            self.trade_logger.config_snapshot()
        except TradeLoggerConfigSnapshotError:
            self.changed_start_time_rejected = True
        else:
            self.changed_start_time_rejected = False
        finally:
            self.trade_logger._report_started_at = report_started_at
        self.cerebro.runstop()


def _run_one_bar(monkeypatch, threshold=5):
    events = []

    def no_file_sinks(self):
        self._loggers_initialized = True
        self._monitor_logger = object()

    def capture_event(self, _sink, payload, text_line=None):
        events.append(payload)

    monkeypatch.setattr(TradeLogger, "_init_loggers", no_file_sinks)
    monkeypatch.setattr(TradeLogger, "_emit_payload", capture_event)

    cerebro = bt.Cerebro(stdstats=False, maxcpus=1)
    cerebro.adddata(_OneBarFeed())
    cerebro.addstrategy(_CaptureStrategy)
    cerebro.addobserver(
        TradeLogger,
        submit_count_warn_threshold=threshold,
        cancel_count_warn_threshold=0,
        submit_cancel_total_warn_threshold=0,
        duplicate_order_warn_threshold=0,
        duplicate_order_window_seconds=60.0,
        log_dir="unused-test-sink",
        log_position_snapshot=False,
        startup_snapshot_file=None,
        mysql_enabled=False,
    )
    strategy = cerebro.run(runonce=False, preload=False)[0]
    return strategy, events


def test_active_cerebro_trade_logger_returns_its_start_receipt(monkeypatch):
    strategy, events = _run_one_bar(monkeypatch)
    receipt = strategy.config_receipt
    config_event = next(
        event for event in events if event["event_type"] == "risk_threshold_configured"
    )

    assert type(receipt) is TradeLoggerConfigSnapshotV1
    assert receipt.schema == "iteration41.backtrader.trade_logger.config_snapshot.v1"
    assert re.fullmatch(r"[0-9a-f]{32}", receipt.config_snapshot_id)
    assert receipt.run_id == strategy.trade_logger._run_id
    assert receipt.observer_generation == 1
    assert dict(receipt.threshold_projection) == {
        "submit_count_warn_threshold": 5,
        "cancel_count_warn_threshold": 0,
        "submit_cancel_total_warn_threshold": 0,
        "duplicate_order_warn_threshold": 0,
        "duplicate_order_window_seconds": 60.0,
    }
    assert config_event["details"]["config_snapshot_id"] == receipt.config_snapshot_id
    assert config_event["details"]["observer_generation"] == receipt.observer_generation
    assert config_event["event_ref"] == receipt.config_event_ref
    assert config_event["event_time"] == receipt.config_event_occurred_at
    assert strategy.same_config_receipt is receipt
    assert strategy.changed_params_rejected is True
    assert strategy.changed_start_time_rejected is True
    with pytest.raises((AttributeError, TypeError)):
        receipt.config_snapshot_id = "caller-selected"
    with pytest.raises(TradeLoggerConfigSnapshotError):
        strategy.trade_logger.config_snapshot()


def test_readback_rejects_changed_params_and_stopped_logger(monkeypatch):
    strategy, _events = _run_one_bar(monkeypatch)
    assert strategy.changed_params_rejected is True
    # Cerebro's normal stop has closed this observer before returning.
    with pytest.raises(TradeLoggerConfigSnapshotError):
        strategy.trade_logger.config_snapshot()


def test_unattached_logger_start_does_not_mint_a_snapshot():
    logger = object.__new__(TradeLogger)
    logger._owner = None
    logger._ltype = 2
    logger.p = type(
        "Params",
        (),
        {
            "submit_count_warn_threshold": 5,
            "cancel_count_warn_threshold": 0,
            "submit_cancel_total_warn_threshold": 0,
            "duplicate_order_warn_threshold": 0,
            "duplicate_order_window_seconds": 60.0,
        },
    )()
    logger._run_id = "trade-log-test"
    logger._report_started_at = "2026-10-09T12:00:00+08:00"
    logger._config_snapshot_generation = 0
    logger._config_snapshot_receipt = None
    logger._config_snapshot_pending = None
    logger._config_snapshot_active = False

    logger._begin_config_snapshot()

    assert logger._config_snapshot_generation == 0
    assert logger._config_snapshot_receipt is None
    with pytest.raises(TradeLoggerConfigSnapshotError):
        logger.config_snapshot()


def test_direct_start_cannot_mint_after_legacy_self_registration(monkeypatch):
    owner = SimpleNamespace(_lineiterators={2: []}, stats=SimpleNamespace(items=[]))
    logger = object.__new__(TradeLogger)
    logger._owner = owner
    logger._ltype = 2
    logger.p = SimpleNamespace(
        submit_count_warn_threshold=5,
        cancel_count_warn_threshold=0,
        submit_cancel_total_warn_threshold=0,
        duplicate_order_warn_threshold=0,
        duplicate_order_window_seconds=60.0,
    )
    logger._run_id = "direct-start-test"
    logger._config_snapshot_generation = 0
    logger._config_snapshot_receipt = None
    logger._config_snapshot_pending = None
    logger._config_snapshot_active = False
    logger._config_snapshot_engine_start = False
    logger._report_finalized = False
    logger._report_started_at = None

    monkeypatch.setattr(TradeLogger, "_ensure_loggers_initialized", lambda self: None)
    monkeypatch.setattr(
        TradeLogger,
        "_start_report",
        lambda self: setattr(self, "_report_started_at", "2026-10-09T12:00:00+08:00"),
    )
    monkeypatch.setattr(TradeLogger, "_save_startup_position_snapshot", lambda self: None)
    monkeypatch.setattr(TradeLogger, "_log_event", lambda self, *args, **kwargs: None)
    monkeypatch.setattr(TradeLogger, "_log_configured_risk_thresholds", lambda self: None)

    logger.start()
    logger._start()

    assert owner._lineiterators[2] == [logger]
    assert logger._config_snapshot_generation == 0
    assert logger._config_snapshot_receipt is None
    with pytest.raises(TradeLoggerConfigSnapshotError):
        logger.config_snapshot()
