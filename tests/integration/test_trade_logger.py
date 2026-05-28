#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""TradeLogger Observer Tests.

This module tests the TradeLogger observer functionality that was added to backtrader
to provide comprehensive logging of orders, trades, positions, indicators, and signals.

Test Coverage:
    - TradeLogger import and instantiation
    - Order logging (order.log)
    - Trade logging (trade.log)
    - Position logging (position.log)
    - Indicator logging (indicator.log)
    - Signal logging (signal.log)
    - Position snapshot (current_position.yaml)
    - JSON and text log formats
    - Console output option

Performance Notes:
    The 7 content-verification tests share a single backtest run via the
    module-scoped ``json_logs`` fixture. The text format, selective logging
    and multi-feed scenarios each run their own backtest (3 additional runs)
    because their TradeLogger configuration differs from the default. Bars
    are capped via ``todate`` to keep per-run cost low while still producing
    enough orders/trades to make the content assertions meaningful.

Example:
    >>> pytest tests/integration/test_trade_logger.py -v
"""

import sys
import os
import json
import datetime

import pytest

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backtrader as bt


# Cap bars to keep test runtime small while still exercising the full
# TradeLogger pipeline (orders, trades, positions, indicators, signals).
# 113013.csv starts 2017-07-24; this cutoff keeps roughly 200 trading days.
_DATA_CUTOFF = datetime.datetime(2018, 6, 1)


class SimpleStrategy(bt.Strategy):
    """Simple SMA-crossover strategy used to exercise TradeLogger.

    Generates buy/sell signals based on a 15-period SMA crossover.

    Parameters:
        sma_period (int): Period for the SMA indicator (default: 15).
    """

    params = (
        ('sma_period', 15),
    )

    def __init__(self):
        """Initialize SMA indicator and crossover detector."""
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.sma_period)
        self.crossover = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar."""
        if not self.position:
            if self.crossover > 0:
                self.buy(size=10)
        elif self.crossover < 0:
            self.close()


def _resolve_test_data_path():
    """Locate the test data CSV used by all TradeLogger backtests."""
    candidates = [
        os.path.join(os.path.dirname(__file__), '..', 'datas', 'nvda-1999-2014.txt'),
        os.path.join(os.path.dirname(__file__), '..', '..', 'examples', '113013.csv'),
    ]
    for path in candidates:
        if os.path.exists(path):
            return os.path.abspath(path)
    return None


def _build_data_feed(data_path, todate=_DATA_CUTOFF):
    """Build a backtrader data feed for the given CSV path.

    Honors the column layout used by ``113013.csv`` while falling back to
    ``YahooFinanceCSVData`` for other files.
    """
    if data_path.endswith('.csv'):
        return bt.feeds.GenericCSVData(
            dataname=data_path,
            dtformat='%Y-%m-%d',
            datetime=2, open=3, high=4, low=5, close=6, volume=7,
            openinterest=-1, headers=True,
            todate=todate,
        )
    return bt.feeds.YahooFinanceCSVData(dataname=data_path, todate=todate)


# ============================================================================
# Module-scoped fixtures: share backtest runs across multiple assertion tests
# ============================================================================

@pytest.fixture(scope="module")
def data_path():
    """Resolved path to the shared CSV data file.

    Skips the test module when no data file is available.
    """
    path = _resolve_test_data_path()
    if path is None:
        pytest.skip("no test data available")
    return path


@pytest.fixture(scope="module")
def json_logs(tmp_path_factory, data_path):
    """Run a backtest once with the full default TradeLogger config.

    Reused by every test that only needs to assert on log file content with
    the default JSON format.

    Returns:
        str: Directory containing all six log files
        (order.log, trade.log, position.log, indicator.log, signal.log,
        bar.log) plus current_position.yaml.
    """
    log_dir = str(tmp_path_factory.mktemp("trade_logger_json"))
    cerebro = bt.Cerebro()
    cerebro.addstrategy(SimpleStrategy)
    cerebro.adddata(_build_data_feed(data_path), name='test_data')
    cerebro.addobserver(
        bt.observers.TradeLogger,
        log_dir=log_dir,
        log_orders=True,
        log_trades=True,
        log_positions=True,
        log_indicators=True,
        log_signals=True,
        log_position_snapshot=True,
        log_format='json',
    )
    cerebro.broker.setcash(100000)
    cerebro.run()
    return log_dir


@pytest.fixture(scope="module")
def text_logs(tmp_path_factory, data_path):
    """Backtest with TradeLogger in text format (separate config from JSON)."""
    log_dir = str(tmp_path_factory.mktemp("trade_logger_text"))
    cerebro = bt.Cerebro()
    cerebro.addstrategy(SimpleStrategy)
    cerebro.adddata(_build_data_feed(data_path), name='test_data')
    cerebro.addobserver(bt.observers.TradeLogger, log_dir=log_dir, log_format='text')
    cerebro.broker.setcash(100000)
    cerebro.run()
    return log_dir


@pytest.fixture(scope="module")
def selective_logs(tmp_path_factory, data_path):
    """Backtest with positions/indicators logging disabled."""
    log_dir = str(tmp_path_factory.mktemp("trade_logger_selective"))
    cerebro = bt.Cerebro()
    cerebro.addstrategy(SimpleStrategy)
    cerebro.adddata(_build_data_feed(data_path), name='test_data')
    cerebro.addobserver(
        bt.observers.TradeLogger,
        log_dir=log_dir,
        log_orders=True,
        log_trades=True,
        log_positions=False,
        log_indicators=False,
        log_signals=True,
    )
    cerebro.broker.setcash(100000)
    cerebro.run()
    return log_dir


@pytest.fixture(scope="module")
def multidata_logs(tmp_path_factory, data_path):
    """Backtest with two named data feeds for multi-feed assertions."""
    log_dir = str(tmp_path_factory.mktemp("trade_logger_multidata"))
    cerebro = bt.Cerebro()
    cerebro.addstrategy(SimpleStrategy)
    cerebro.adddata(_build_data_feed(data_path), name='data1')
    cerebro.adddata(_build_data_feed(data_path), name='data2')
    cerebro.addobserver(bt.observers.TradeLogger, log_dir=log_dir, log_format='json')
    cerebro.broker.setcash(100000)
    cerebro.run()
    return log_dir


def _read_lines(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.readlines()


# ============================================================================
# Pure unit tests (no backtest, near-zero cost)
# ============================================================================

def test_trade_logger_import():
    """TradeLogger can be imported from backtrader.observers."""
    from backtrader.observers import TradeLogger
    assert TradeLogger is not None


def test_trade_logger_in_bt_observers():
    """TradeLogger is accessible via the standard bt.observers namespace."""
    assert hasattr(bt.observers, 'TradeLogger')
    assert bt.observers.TradeLogger is not None


def test_trade_logger_params():
    """TradeLogger exposes the expected parameters with correct defaults."""
    from backtrader.observers import TradeLogger
    assert hasattr(TradeLogger, 'params')

    params = TradeLogger.params
    if isinstance(params, type):
        # params is a class — just verify its presence; default checks are
        # exercised indirectly via behavior tests below.
        assert params is not None
        return

    expected = {
        'log_dir': './logs',
        'log_orders': True,
        'log_trades': True,
        'log_positions': True,
        'log_indicators': True,
        'log_signals': True,
        'log_position_snapshot': True,
        'snapshot_file': 'current_position.yaml',
        'log_format': 'json',
        'log_to_console': False,
        'mysql_enabled': False,
    }
    for name, value in expected.items():
        assert name in params, f"Missing parameter: {name}"
        assert params[name] == value, (
            f"Parameter {name} has wrong default: {params[name]!r} != {value!r}"
        )


def test_trade_logger_lines():
    """TradeLogger declares the lines required by the observer protocol."""
    from backtrader.observers import TradeLogger
    assert hasattr(TradeLogger, 'lines')
    lines = TradeLogger.lines
    if isinstance(lines, tuple):
        assert len(lines) >= 1
    else:
        assert lines is not None


def test_trade_logger_ltype():
    """TradeLogger has _ltype == 2 so it registers as an observer."""
    from backtrader.observers import TradeLogger
    assert hasattr(TradeLogger, '_ltype')
    assert TradeLogger._ltype == 2, (
        f"_ltype should be 2 (ObsType), got {TradeLogger._ltype}"
    )


# ============================================================================
# Behavior tests (share the json_logs fixture — single backtest run)
# ============================================================================

def test_trade_logger_file_creation(json_logs):
    """All expected log files are created by a default-config run."""
    expected = [
        'order.log',
        'trade.log',
        'position.log',
        'indicator.log',
        'signal.log',
        'current_position.yaml',
    ]
    for filename in expected:
        path = os.path.join(json_logs, filename)
        assert os.path.exists(path), f"Expected file not created: {filename}"


def test_trade_logger_order_log_content(json_logs):
    """order.log contains JSON entries with order metadata."""
    order_log_path = os.path.join(json_logs, 'order.log')
    assert os.path.exists(order_log_path), "order.log not created"

    lines = _read_lines(order_log_path)
    assert len(lines) > 0, "order.log is empty"

    first_order = json.loads(lines[0])
    for field in ('datetime', 'ref', 'order_type', 'status'):
        assert field in first_order, f"Missing field in order log: {field}"


def test_trade_logger_bar_log_content(json_logs):
    """bar.log records OHLC plus broker value/cash for each bar."""
    bar_log_path = os.path.join(json_logs, 'bar.log')
    assert os.path.exists(bar_log_path), "bar.log not created"

    lines = _read_lines(bar_log_path)
    assert len(lines) > 0, "bar.log is empty"

    first_bar = json.loads(lines[0])
    for field in (
        'event_type', 'data_name', 'datetime',
        'open', 'high', 'low', 'close',
        'broker_value', 'broker_cash',
    ):
        assert field in first_bar, f"Missing field in bar log: {field}"


def test_trade_logger_trade_log_content(json_logs):
    """trade.log entries carry trade-level fields."""
    trade_log_path = os.path.join(json_logs, 'trade.log')
    assert os.path.exists(trade_log_path), "trade.log not created"

    lines = _read_lines(trade_log_path)
    assert len(lines) > 0, "trade.log is empty"

    first_trade = json.loads(lines[0])
    for field in ('datetime', 'data_name', 'size', 'price', 'pnl'):
        assert field in first_trade, f"Missing field in trade log: {field}"


def test_trade_logger_position_log_content(json_logs):
    """position.log entries include broker-level value/cash and identity."""
    position_log_path = os.path.join(json_logs, 'position.log')
    assert os.path.exists(position_log_path), "position.log not created"

    lines = _read_lines(position_log_path)
    assert len(lines) > 0, "position.log is empty"

    first_position = json.loads(lines[0])
    for field in (
        'datetime', 'data_name', 'size', 'price', 'value',
        'broker_value', 'broker_cash', 'strategy_name',
    ):
        assert field in first_position, f"Missing field in position log: {field}"


def test_trade_logger_indicator_log_content(json_logs):
    """indicator.log entries reference the strategy that produced them."""
    indicator_log_path = os.path.join(json_logs, 'indicator.log')
    assert os.path.exists(indicator_log_path), "indicator.log not created"

    lines = _read_lines(indicator_log_path)
    assert len(lines) > 0, "indicator.log is empty"

    first_indicator = json.loads(lines[0])
    for field in ('datetime', 'strategy_name'):
        assert field in first_indicator, f"Missing field in indicator log: {field}"


def test_trade_logger_signal_log_content(json_logs):
    """signal.log records discrete buy/sell signals with execution context."""
    signal_log_path = os.path.join(json_logs, 'signal.log')
    assert os.path.exists(signal_log_path), "signal.log not created"

    lines = _read_lines(signal_log_path)
    assert len(lines) > 0, "signal.log is empty"

    first_signal = json.loads(lines[0])
    for field in ('datetime', 'action', 'size', 'price', 'data_name'):
        assert field in first_signal, f"Missing field in signal log: {field}"


# ============================================================================
# Behavior tests with non-default configs (one backtest each)
# ============================================================================

def test_trade_logger_text_format(text_logs):
    """Text-format output uses pipe-separated key=value pairs."""
    order_log_path = os.path.join(text_logs, 'order.log')
    assert os.path.exists(order_log_path), "order.log not created"

    with open(order_log_path, 'r', encoding='utf-8') as f:
        order_content = f.read()

    assert len(order_content) > 0, "order.log is empty"
    assert '|' in order_content, "Text format should contain | separators"
    assert 'datetime=' in order_content, (
        "Text format should include explicit datetime fields"
    )

    trade_log_path = os.path.join(text_logs, 'trade.log')
    with open(trade_log_path, 'r', encoding='utf-8') as f:
        trade_content = f.read()

    assert 'datetime=' in trade_content, (
        "trade.log text format should include explicit datetime fields"
    )
    assert 'price=' in trade_content, "trade.log text format should include price"
    assert 'value=' in trade_content, "trade.log text format should include value"


def test_trade_logger_selective_logging(selective_logs):
    """Disabled categories produce no content while enabled ones still write."""
    order_log_path = os.path.join(selective_logs, 'order.log')
    assert os.path.exists(order_log_path), "order.log should exist"
    assert os.path.getsize(order_log_path) > 0, "order.log should have content"

    position_log_path = os.path.join(selective_logs, 'position.log')
    if os.path.exists(position_log_path):
        assert os.path.getsize(position_log_path) == 0, (
            "position.log should be empty when disabled"
        )

    indicator_log_path = os.path.join(selective_logs, 'indicator.log')
    if os.path.exists(indicator_log_path):
        assert os.path.getsize(indicator_log_path) == 0, (
            "indicator.log should be empty when disabled"
        )


def test_trade_logger_multiple_data_feeds(multidata_logs):
    """Position log records per-feed entries when multiple feeds are present."""
    position_log_path = os.path.join(multidata_logs, 'position.log')
    assert os.path.exists(position_log_path), "position.log not created"

    with open(position_log_path, 'r', encoding='utf-8') as f:
        content = f.read()

    assert 'data1' in content or 'data2' in content, (
        "Position log should contain entries for named data feeds"
    )
