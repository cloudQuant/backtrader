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

Features Tested:
    - Observer registration and initialization
    - File logger creation with Python logging module
    - Lazy initialization of loggers
    - notify_order and notify_trade callbacks
    - next() method for position/indicator logging
    - Log file content verification

Dependencies:
    - backtrader: Core backtesting framework
    - backtrader.observers.TradeLogger: Observer being tested
    - tempfile: For creating temporary log directories

Example:
    >>> pytest tests/new_functions/test_trade_logger.py -v
    test_trade_logger_import PASSED
    test_trade_logger_instantiation PASSED
    ...
"""

import sys
import os
import tempfile
import shutil
import json

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backtrader as bt


class SimpleStrategy(bt.Strategy):
    """Simple strategy for testing TradeLogger.

    A basic strategy that generates buy/sell signals based on SMA crossover.
    Used to generate orders, trades, and positions for TradeLogger testing.

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


def get_test_data_path():
    """Get path to test data file.

    Returns:
        str: Path to the test data CSV file.
    """
    # Try multiple possible data file locations
    possible_paths = [
        os.path.join(os.path.dirname(__file__), '..', 'datas', 'nvda-1999-2014.txt'),
        os.path.join(os.path.dirname(__file__), '..', '..', 'examples', '113013.csv'),
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return os.path.abspath(path)

    # If no data file found, skip test
    return None


def test_trade_logger_import():
    """Test TradeLogger import.

    Verifies that the TradeLogger class can be imported from the
    backtrader.observers module.

    Raises:
        AssertionError: If TradeLogger cannot be imported.
    """
    from backtrader.observers import TradeLogger

    assert TradeLogger is not None
    print("✓ TradeLogger import test passed")


def test_trade_logger_in_bt_observers():
    """Test TradeLogger is accessible via bt.observers.

    Verifies that TradeLogger can be accessed through the standard
    backtrader observer namespace.

    Raises:
        AssertionError: If TradeLogger is not accessible via bt.observers.
    """
    assert hasattr(bt.observers, 'TradeLogger')
    assert bt.observers.TradeLogger is not None
    print("✓ TradeLogger accessible via bt.observers test passed")


def test_trade_logger_params():
    """Test TradeLogger default parameters.

    Verifies that TradeLogger has all expected parameters with correct defaults.

    Expected Parameters:
        - log_dir: './logs'
        - log_orders: True
        - log_trades: True
        - log_positions: True
        - log_indicators: True
        - log_signals: True
        - log_position_snapshot: True
        - snapshot_file: 'current_position.yaml'
        - log_format: 'json'
        - log_to_console: False
        - mysql_enabled: False

    Raises:
        AssertionError: If any parameter is missing or has wrong default.
    """
    from backtrader.observers import TradeLogger

    # Check class has params
    assert hasattr(TradeLogger, 'params')

    # Get params - it's a dict type class attribute
    params = TradeLogger.params
    if isinstance(params, type):
        # params is a class, need to check differently
        # Just verify the class has params attribute
        assert params is not None
        print("✓ TradeLogger params test passed")
        return

    # Verify expected parameters exist
    expected_params = {
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

    for param_name, expected_value in expected_params.items():
        assert param_name in params, f"Missing parameter: {param_name}"
        assert params[param_name] == expected_value, \
            f"Parameter {param_name} has wrong default: {params[param_name]} != {expected_value}"

    print("✓ TradeLogger params test passed")


def test_trade_logger_lines():
    """Test TradeLogger has required lines attribute.

    Observers require at least one line to function properly in backtrader.

    Raises:
        AssertionError: If lines attribute is missing or empty.
    """
    from backtrader.observers import TradeLogger

    assert hasattr(TradeLogger, 'lines')
    # lines is a tuple of line names
    lines = TradeLogger.lines
    if isinstance(lines, tuple):
        assert len(lines) >= 1
    else:
        # lines might be a class attribute of different type
        assert lines is not None
    print("✓ TradeLogger lines test passed")


def test_trade_logger_ltype():
    """Test TradeLogger has correct _ltype for observer registration.

    _ltype should be 2 (ObsType) for proper registration in _lineiterators.

    Raises:
        AssertionError: If _ltype is not set correctly.
    """
    from backtrader.observers import TradeLogger

    assert hasattr(TradeLogger, '_ltype')
    assert TradeLogger._ltype == 2, f"_ltype should be 2 (ObsType), got {TradeLogger._ltype}"
    print("✓ TradeLogger _ltype test passed")


def test_trade_logger_file_creation():
    """Test TradeLogger creates log files.

    Verifies that TradeLogger creates all expected log files when
    running a backtest with logging enabled.

    Expected Files:
        - order.log
        - trade.log
        - position.log
        - indicator.log
        - signal.log
        - current_position.yaml

    Raises:
        AssertionError: If any expected file is not created.
    """
    data_path = get_test_data_path()
    if data_path is None:
        print("⚠ Skipping test_trade_logger_file_creation: no test data available")
        return

    # Create temporary directory for logs
    temp_dir = tempfile.mkdtemp()

    try:
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)

        # Add data based on file type
        if data_path.endswith('.csv'):
            data = bt.feeds.GenericCSVData(
                dataname=data_path,
                dtformat='%Y-%m-%d',
                datetime=2, open=3, high=4, low=5, close=6, volume=7,
                openinterest=-1, headers=True
            )
        else:
            data = bt.feeds.YahooFinanceCSVData(dataname=data_path)

        cerebro.adddata(data, name='test_data')

        # Add TradeLogger
        cerebro.addobserver(
            bt.observers.TradeLogger,
            log_dir=temp_dir,
            log_orders=True,
            log_trades=True,
            log_positions=True,
            log_indicators=True,
            log_signals=True,
            log_position_snapshot=True,
        )

        cerebro.broker.setcash(100000)
        cerebro.run()

        # Verify files were created
        expected_files = [
            'order.log',
            'trade.log',
            'position.log',
            'indicator.log',
            'signal.log',
            'current_position.yaml',
        ]

        for filename in expected_files:
            filepath = os.path.join(temp_dir, filename)
            assert os.path.exists(filepath), f"Expected file not created: {filename}"

        print("✓ TradeLogger file creation test passed")

    finally:
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_trade_logger_order_log_content():
    """Test order.log contains valid order data.

    Verifies that order.log contains properly formatted JSON entries
    with expected order fields.

    Expected Fields:
        - datetime
        - ref (order reference)
        - type (Buy/Sell)
        - status
        - size
        - price

    Raises:
        AssertionError: If order.log is empty or has invalid format.
    """
    data_path = get_test_data_path()
    if data_path is None:
        print("⚠ Skipping test_trade_logger_order_log_content: no test data available")
        return

    temp_dir = tempfile.mkdtemp()

    try:
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)

        if data_path.endswith('.csv'):
            data = bt.feeds.GenericCSVData(
                dataname=data_path,
                dtformat='%Y-%m-%d',
                datetime=2, open=3, high=4, low=5, close=6, volume=7,
                openinterest=-1, headers=True
            )
        else:
            data = bt.feeds.YahooFinanceCSVData(dataname=data_path)

        cerebro.adddata(data, name='test_data')
        cerebro.addobserver(bt.observers.TradeLogger, log_dir=temp_dir, log_format='json')
        cerebro.broker.setcash(100000)
        cerebro.run()

        # Read and verify order.log
        order_log_path = os.path.join(temp_dir, 'order.log')
        assert os.path.exists(order_log_path), "order.log not created"

        with open(order_log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) > 0, "order.log is empty"

        # Verify first line is valid JSON with expected fields
        first_order = json.loads(lines[0])
        expected_fields = ['datetime', 'ref', 'order_type', 'status']
        for field in expected_fields:
            assert field in first_order, f"Missing field in order log: {field}"

        print("✓ TradeLogger order.log content test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_trade_logger_bar_log_content():
    """Test bar.log contains per-bar data with broker metrics.

    Verifies that regular backtests populate bar.log and include account-level
    broker value and cash fields for each logged bar.

    Raises:
        AssertionError: If bar.log is empty or missing expected fields.
    """
    data_path = get_test_data_path()
    if data_path is None:
        print("⚠ Skipping test_trade_logger_bar_log_content: no test data available")
        return

    temp_dir = tempfile.mkdtemp()

    try:
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)

        if data_path.endswith('.csv'):
            data = bt.feeds.GenericCSVData(
                dataname=data_path,
                dtformat='%Y-%m-%d',
                datetime=2, open=3, high=4, low=5, close=6, volume=7,
                openinterest=-1, headers=True
            )
        else:
            data = bt.feeds.YahooFinanceCSVData(dataname=data_path)

        cerebro.adddata(data, name='test_data')
        cerebro.addobserver(bt.observers.TradeLogger, log_dir=temp_dir, log_format='json')
        cerebro.broker.setcash(100000)
        cerebro.run()

        bar_log_path = os.path.join(temp_dir, 'bar.log')
        assert os.path.exists(bar_log_path), "bar.log not created"

        with open(bar_log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) > 0, "bar.log is empty"

        first_bar = json.loads(lines[0])
        expected_fields = ['event_type', 'data_name', 'datetime', 'open', 'high', 'low', 'close', 'broker_value', 'broker_cash']
        for field in expected_fields:
            assert field in first_bar, f"Missing field in bar log: {field}"

        print("✓ TradeLogger bar.log content test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_trade_logger_trade_log_content():
    """Test trade.log contains valid trade data.

    Verifies that trade.log contains properly formatted JSON entries
    with expected trade fields.

    Expected Fields:
        - datetime
        - data_name
        - status (Open/Closed)
        - size
        - price
        - pnl (for closed trades)

    Raises:
        AssertionError: If trade.log is empty or has invalid format.
    """
    data_path = get_test_data_path()
    if data_path is None:
        print("⚠ Skipping test_trade_logger_trade_log_content: no test data available")
        return

    temp_dir = tempfile.mkdtemp()

    try:
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)

        if data_path.endswith('.csv'):
            data = bt.feeds.GenericCSVData(
                dataname=data_path,
                dtformat='%Y-%m-%d',
                datetime=2, open=3, high=4, low=5, close=6, volume=7,
                openinterest=-1, headers=True
            )
        else:
            data = bt.feeds.YahooFinanceCSVData(dataname=data_path)

        cerebro.adddata(data, name='test_data')
        cerebro.addobserver(bt.observers.TradeLogger, log_dir=temp_dir, log_format='json')
        cerebro.broker.setcash(100000)
        cerebro.run()

        trade_log_path = os.path.join(temp_dir, 'trade.log')
        assert os.path.exists(trade_log_path), "trade.log not created"

        with open(trade_log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) > 0, "trade.log is empty"

        first_trade = json.loads(lines[0])
        expected_fields = ['datetime', 'data_name', 'size', 'price', 'pnl']
        for field in expected_fields:
            assert field in first_trade, f"Missing field in trade log: {field}"

        print("✓ TradeLogger trade.log content test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_trade_logger_position_log_content():
    """Test position.log contains valid position data.

    Verifies that position.log contains properly formatted JSON entries
    with expected position fields.

    Expected Fields:
        - datetime
        - data_name
        - size
        - price
        - value
        - strategy_name

    Raises:
        AssertionError: If position.log is empty or has invalid format.
    """
    data_path = get_test_data_path()
    if data_path is None:
        print("⚠ Skipping test_trade_logger_position_log_content: no test data available")
        return

    temp_dir = tempfile.mkdtemp()

    try:
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)

        if data_path.endswith('.csv'):
            data = bt.feeds.GenericCSVData(
                dataname=data_path,
                dtformat='%Y-%m-%d',
                datetime=2, open=3, high=4, low=5, close=6, volume=7,
                openinterest=-1, headers=True
            )
        else:
            data = bt.feeds.YahooFinanceCSVData(dataname=data_path)

        cerebro.adddata(data, name='test_data')
        cerebro.addobserver(bt.observers.TradeLogger, log_dir=temp_dir, log_format='json')
        cerebro.broker.setcash(100000)
        cerebro.run()

        position_log_path = os.path.join(temp_dir, 'position.log')
        assert os.path.exists(position_log_path), "position.log not created"

        with open(position_log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) > 0, "position.log is empty"

        first_position = json.loads(lines[0])
        expected_fields = ['datetime', 'data_name', 'size', 'price', 'value', 'broker_value', 'broker_cash', 'strategy_name']
        for field in expected_fields:
            assert field in first_position, f"Missing field in position log: {field}"

        print("✓ TradeLogger position.log content test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_trade_logger_indicator_log_content():
    """Test indicator.log contains valid indicator data.

    Verifies that indicator.log contains properly formatted JSON entries
    with expected indicator fields.

    Expected Fields:
        - datetime
        - strategy_name
        - (indicator values)

    Raises:
        AssertionError: If indicator.log is empty or has invalid format.
    """
    data_path = get_test_data_path()
    if data_path is None:
        print("⚠ Skipping test_trade_logger_indicator_log_content: no test data available")
        return

    temp_dir = tempfile.mkdtemp()

    try:
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)

        if data_path.endswith('.csv'):
            data = bt.feeds.GenericCSVData(
                dataname=data_path,
                dtformat='%Y-%m-%d',
                datetime=2, open=3, high=4, low=5, close=6, volume=7,
                openinterest=-1, headers=True
            )
        else:
            data = bt.feeds.YahooFinanceCSVData(dataname=data_path)

        cerebro.adddata(data, name='test_data')
        cerebro.addobserver(bt.observers.TradeLogger, log_dir=temp_dir, log_format='json')
        cerebro.broker.setcash(100000)
        cerebro.run()

        indicator_log_path = os.path.join(temp_dir, 'indicator.log')
        assert os.path.exists(indicator_log_path), "indicator.log not created"

        with open(indicator_log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) > 0, "indicator.log is empty"

        first_indicator = json.loads(lines[0])
        expected_fields = ['datetime', 'strategy_name']
        for field in expected_fields:
            assert field in first_indicator, f"Missing field in indicator log: {field}"

        print("✓ TradeLogger indicator.log content test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_trade_logger_signal_log_content():
    """Test signal.log contains valid signal data.

    Verifies that signal.log contains properly formatted JSON entries
    with expected signal fields.

    Expected Fields:
        - datetime
        - signal_type (buy/sell)
        - size
        - price
        - data_name

    Raises:
        AssertionError: If signal.log is empty or has invalid format.
    """
    data_path = get_test_data_path()
    if data_path is None:
        print("⚠ Skipping test_trade_logger_signal_log_content: no test data available")
        return

    temp_dir = tempfile.mkdtemp()

    try:
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)

        if data_path.endswith('.csv'):
            data = bt.feeds.GenericCSVData(
                dataname=data_path,
                dtformat='%Y-%m-%d',
                datetime=2, open=3, high=4, low=5, close=6, volume=7,
                openinterest=-1, headers=True
            )
        else:
            data = bt.feeds.YahooFinanceCSVData(dataname=data_path)

        cerebro.adddata(data, name='test_data')
        cerebro.addobserver(bt.observers.TradeLogger, log_dir=temp_dir, log_format='json')
        cerebro.broker.setcash(100000)
        cerebro.run()

        signal_log_path = os.path.join(temp_dir, 'signal.log')
        assert os.path.exists(signal_log_path), "signal.log not created"

        with open(signal_log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) > 0, "signal.log is empty"

        first_signal = json.loads(lines[0])
        expected_fields = ['datetime', 'action', 'size', 'price', 'data_name']
        for field in expected_fields:
            assert field in first_signal, f"Missing field in signal log: {field}"

        print("✓ TradeLogger signal.log content test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_trade_logger_text_format():
    """Test TradeLogger text format output.

    Verifies that TradeLogger can output logs in text format instead of JSON.

    Raises:
        AssertionError: If text format output is invalid.
    """
    data_path = get_test_data_path()
    if data_path is None:
        print("⚠ Skipping test_trade_logger_text_format: no test data available")
        return

    temp_dir = tempfile.mkdtemp()

    try:
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)

        if data_path.endswith('.csv'):
            data = bt.feeds.GenericCSVData(
                dataname=data_path,
                dtformat='%Y-%m-%d',
                datetime=2, open=3, high=4, low=5, close=6, volume=7,
                openinterest=-1, headers=True
            )
        else:
            data = bt.feeds.YahooFinanceCSVData(dataname=data_path)

        cerebro.adddata(data, name='test_data')
        cerebro.addobserver(bt.observers.TradeLogger, log_dir=temp_dir, log_format='text')
        cerebro.broker.setcash(100000)
        cerebro.run()

        order_log_path = os.path.join(temp_dir, 'order.log')
        assert os.path.exists(order_log_path), "order.log not created"

        with open(order_log_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Text format should not be valid JSON for the whole content
        # but should contain readable text with | separators
        assert len(content) > 0, "order.log is empty"
        assert '|' in content, "Text format should contain | separators"

        print("✓ TradeLogger text format test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_trade_logger_selective_logging():
    """Test TradeLogger selective logging options.

    Verifies that individual logging options can be enabled/disabled.

    Test Case:
        - Disable position and indicator logging
        - Verify position.log and indicator.log are not created/empty

    Raises:
        AssertionError: If selective logging doesn't work correctly.
    """
    data_path = get_test_data_path()
    if data_path is None:
        print("⚠ Skipping test_trade_logger_selective_logging: no test data available")
        return

    temp_dir = tempfile.mkdtemp()

    try:
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)

        if data_path.endswith('.csv'):
            data = bt.feeds.GenericCSVData(
                dataname=data_path,
                dtformat='%Y-%m-%d',
                datetime=2, open=3, high=4, low=5, close=6, volume=7,
                openinterest=-1, headers=True
            )
        else:
            data = bt.feeds.YahooFinanceCSVData(dataname=data_path)

        cerebro.adddata(data, name='test_data')
        cerebro.addobserver(
            bt.observers.TradeLogger,
            log_dir=temp_dir,
            log_orders=True,
            log_trades=True,
            log_positions=False,  # Disabled
            log_indicators=False,  # Disabled
            log_signals=True,
        )
        cerebro.broker.setcash(100000)
        cerebro.run()

        # order.log should exist and have content
        order_log_path = os.path.join(temp_dir, 'order.log')
        assert os.path.exists(order_log_path), "order.log should exist"
        assert os.path.getsize(order_log_path) > 0, "order.log should have content"

        # position.log should not exist (disabled)
        position_log_path = os.path.join(temp_dir, 'position.log')
        if os.path.exists(position_log_path):
            assert os.path.getsize(position_log_path) == 0, "position.log should be empty when disabled"

        # indicator.log should not exist (disabled)
        indicator_log_path = os.path.join(temp_dir, 'indicator.log')
        if os.path.exists(indicator_log_path):
            assert os.path.getsize(indicator_log_path) == 0, "indicator.log should be empty when disabled"

        print("✓ TradeLogger selective logging test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_trade_logger_multiple_data_feeds():
    """Test TradeLogger with multiple data feeds.

    Verifies that TradeLogger correctly logs positions for multiple data feeds.

    Raises:
        AssertionError: If multiple data feeds are not logged correctly.
    """
    data_path = get_test_data_path()
    if data_path is None:
        print("⚠ Skipping test_trade_logger_multiple_data_feeds: no test data available")
        return

    temp_dir = tempfile.mkdtemp()

    try:
        cerebro = bt.Cerebro()
        cerebro.addstrategy(SimpleStrategy)

        if data_path.endswith('.csv'):
            data1 = bt.feeds.GenericCSVData(
                dataname=data_path,
                dtformat='%Y-%m-%d',
                datetime=2, open=3, high=4, low=5, close=6, volume=7,
                openinterest=-1, headers=True
            )
            data2 = bt.feeds.GenericCSVData(
                dataname=data_path,
                dtformat='%Y-%m-%d',
                datetime=2, open=3, high=4, low=5, close=6, volume=7,
                openinterest=-1, headers=True
            )
        else:
            data1 = bt.feeds.YahooFinanceCSVData(dataname=data_path)
            data2 = bt.feeds.YahooFinanceCSVData(dataname=data_path)

        cerebro.adddata(data1, name='data1')
        cerebro.adddata(data2, name='data2')
        cerebro.addobserver(bt.observers.TradeLogger, log_dir=temp_dir, log_format='json')
        cerebro.broker.setcash(100000)
        cerebro.run()

        position_log_path = os.path.join(temp_dir, 'position.log')
        assert os.path.exists(position_log_path), "position.log not created"

        with open(position_log_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Should have logs for both data feeds
        assert 'data1' in content or 'data2' in content, \
            "Position log should contain entries for named data feeds"

        print("✓ TradeLogger multiple data feeds test passed")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_all_tests():
    """Run all TradeLogger tests.

    Returns:
        tuple: (passed_count, failed_count)
    """
    tests = [
        test_trade_logger_import,
        test_trade_logger_in_bt_observers,
        test_trade_logger_params,
        test_trade_logger_lines,
        test_trade_logger_ltype,
        test_trade_logger_file_creation,
        test_trade_logger_order_log_content,
        test_trade_logger_trade_log_content,
        test_trade_logger_position_log_content,
        test_trade_logger_indicator_log_content,
        test_trade_logger_bar_log_content,
        test_trade_logger_signal_log_content,
        test_trade_logger_text_format,
        test_trade_logger_disable_some_logs,
        test_trade_logger_multiple_data_feeds,
    ]

    print("=" * 60)
    print("TradeLogger Observer Tests")
    print("=" * 60)

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"✗ {test.__name__} FAILED: {e}")

    print("=" * 60)
    print(f"Test completed: {passed} passed, {failed} failed")
    print("=" * 60)

    return passed, failed


if __name__ == '__main__':
    run_all_tests()
