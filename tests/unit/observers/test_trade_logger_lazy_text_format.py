"""TradeLogger only renders specialized text for text-format records."""

from __future__ import annotations

import datetime as dt
import json
import re
from types import SimpleNamespace

import backtrader as bt

from backtrader.observers.trade_logger import TradeLogger


class _CaptureLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(message)


def _bare_trade_logger(log_format):
    trade_logger = object.__new__(TradeLogger)
    trade_logger.p = SimpleNamespace(log_format=log_format)
    trade_logger._strategy_financial_unavailable = {}
    return trade_logger


def test_json_emission_skips_text_factory_without_changing_payload():
    trade_logger = _bare_trade_logger("json")
    sink = _CaptureLogger()
    payload = {
        "event_type": "bar",
        "broker_value": float("nan"),
        "broker_cash": 12.5,
        "strategy_name": "Synthetic",
    }
    trade_logger._strategy_financial_unavailable = {"value": "scope_missing"}
    factory_calls = []

    def forbidden_text_factory():
        factory_calls.append(True)
        raise AssertionError("JSON emission must not render text")

    TradeLogger._emit_payload(
        trade_logger, sink, payload, text_line_factory=forbidden_text_factory
    )

    assert factory_calls == []
    assert len(sink.messages) == 1
    assert json.loads(sink.messages[0]) == {
        "event_type": "bar",
        "broker_value": None,
        "broker_cash": 12.5,
        "strategy_name": "Synthetic",
        "strategy_financial_unavailable": {"broker_value": "scope_missing"},
    }

    baseline_sink = _CaptureLogger()
    TradeLogger._emit_payload(trade_logger, baseline_sink, payload)
    assert sink.messages == baseline_sink.messages


def test_text_factory_runs_once_and_format_can_change_between_records():
    trade_logger = _bare_trade_logger("json")
    sink = _CaptureLogger()
    payload = {"event_type": "bar", "close": 12.5}
    factory_calls = []

    def text_factory():
        factory_calls.append(True)
        return "2026-11-20 | BAR | close=12.5000"

    TradeLogger._emit_payload(trade_logger, sink, payload, text_line_factory=text_factory)
    assert factory_calls == []
    assert json.loads(sink.messages[-1]) == payload

    trade_logger.p.log_format = "text"
    TradeLogger._emit_payload(trade_logger, sink, payload, text_line_factory=text_factory)
    assert factory_calls == [True]
    assert sink.messages[-1] == "2026-11-20 | BAR | close=12.5000"

    trade_logger.p.log_format = "json"
    TradeLogger._emit_payload(trade_logger, sink, payload, text_line_factory=text_factory)
    assert factory_calls == [True]
    assert json.loads(sink.messages[-1]) == payload


def test_emission_reads_format_once_and_keeps_text_fallback():
    class _OneReadParams:
        reads = 0

        @property
        def log_format(self):
            self.reads += 1
            if self.reads > 1:
                raise AssertionError("one record must use one format snapshot")
            return "text"

    trade_logger = object.__new__(TradeLogger)
    trade_logger.p = _OneReadParams()
    trade_logger._strategy_financial_unavailable = {}
    sink = _CaptureLogger()
    TradeLogger._emit_payload(
        trade_logger,
        sink,
        {"log_time": "now", "level": "WARNING", "event_type": "fallback"},
    )
    assert sink.messages == ["now | WARNING | fallback"]

    factory_logger = object.__new__(TradeLogger)
    factory_logger.p = _OneReadParams()
    factory_logger._strategy_financial_unavailable = {}
    factory_sink = _CaptureLogger()
    TradeLogger._emit_payload(
        factory_logger,
        factory_sink,
        {"event_type": "custom"},
        text_line_factory=lambda: "specialized text",
    )
    assert factory_sink.messages == ["specialized text"]
    assert factory_logger.p.reads == 1


class _ThreeBarFeed(bt.feed.DataBase):
    """Three local bars for a real per-bar Cerebro observer pass."""

    def __init__(self):
        super().__init__()
        self._bar_index = 0

    def _load(self):
        if self._bar_index >= 3:
            return False

        index = self._bar_index
        self._bar_index += 1
        self.lines.datetime[0] = bt.date2num(
            dt.datetime(2026, 11, 20, 9, 30) + dt.timedelta(minutes=index)
        )
        self.lines.open[0] = 100.0 + index
        self.lines.high[0] = 101.0 + index
        self.lines.low[0] = 99.0 + index
        self.lines.close[0] = 100.5 + index
        self.lines.volume[0] = 10.0 + index
        self.lines.openinterest[0] = 0.0
        return True


class _FormatSwitchStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=1)
        self.trade_logger = None

    def start(self):
        observers = [item for item in self.stats.items if type(item) is TradeLogger]
        assert len(observers) == 1
        self.trade_logger = observers[0]

    def next(self):
        # Strategy callbacks run before the observer callback for this bar.
        self.trade_logger.p.log_format = ("json", "text", "json")[len(self) - 1]


def test_real_cerebro_preserves_text_rows_and_switches_mode_per_bar(monkeypatch, tmp_path):
    factory_calls = []
    original_emit = TradeLogger._emit_payload

    def track_factory(self, logger, payload, text_line=None, text_line_factory=None):
        if text_line_factory is not None:
            factory = text_line_factory

            def counted_factory():
                factory_calls.append((logger.name, self.p.log_format))
                return factory()

            text_line_factory = counted_factory
        return original_emit(
            self,
            logger,
            payload,
            text_line=text_line,
            text_line_factory=text_line_factory,
        )

    monkeypatch.setattr(TradeLogger, "_emit_payload", track_factory)

    cerebro = bt.Cerebro(stdstats=False, maxcpus=1)
    cerebro.adddata(_ThreeBarFeed(), name="synthetic")
    cerebro.addstrategy(_FormatSwitchStrategy)
    cerebro.addobserver(
        TradeLogger,
        log_dir=str(tmp_path),
        log_format="json",
        log_orders=False,
        log_trades=False,
        log_positions=False,
        log_indicators=True,
        log_signals=False,
        log_ticks=False,
        log_bars=True,
        log_system=False,
        log_monitoring=False,
        log_errors=False,
        log_value=False,
        log_position_snapshot=False,
    )
    cerebro.broker.setcash(10000.0)
    cerebro.run(runonce=False, preload=False)

    bar_lines = (tmp_path / "bar.log").read_text(encoding="utf-8").splitlines()
    indicator_lines = (tmp_path / "indicator.log").read_text(encoding="utf-8").splitlines()
    assert len(bar_lines) == 3
    assert len(indicator_lines) == 3

    bar_records = [json.loads(bar_lines[index]) for index in (0, 2)]
    indicator_records = [json.loads(indicator_lines[index]) for index in (0, 2)]
    assert [row["close"] for row in bar_records] == [100.5, 102.5]
    assert all(row["event_type"] == "bar" for row in bar_records)
    assert all(any("MovingAverageSimple" in key for key in row) for row in indicator_records)

    text_bar_parts = bar_lines[1].split(" | ")
    assert len(text_bar_parts) == 11
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT.+", text_bar_parts[0])
    assert text_bar_parts[1:9] == [
        "BAR",
        "datetime=2026-11-20T09:31:00.000+00:00",
        "data_name=synthetic",
        "open=101.0000",
        "high=102.0000",
        "low=100.0000",
        "close=101.5000",
        "volume=11.00",
    ]
    assert text_bar_parts[9:] == ["broker_value=10000.00", "broker_cash=10000.00"]
    assert " | INDICATOR | datetime=2026-11-20T09:31:00.000+00:00 | " in indicator_lines[1]
    assert "101.5000" in indicator_lines[1]
    assert [mode for _name, mode in factory_calls] == ["text", "text"]
    assert [name.split(":", 1)[0] for name, _mode in factory_calls] == [
        "bt_bar",
        "bt_indicator",
    ]
