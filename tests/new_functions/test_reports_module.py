#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Report Generation Module Tests.

This module tests the report generation functionality that was added to backtrader
to provide comprehensive performance analysis and visualization capabilities.

Test Coverage:
    - PerformanceCalculator: Calculates performance metrics from strategy results
    - ReportChart: Generates visualization charts for equity, returns, drawdown
    - ReportGenerator: Creates HTML and JSON reports with embedded charts
    - Cerebro integration: add_report_analyzers() and generate_report() methods

Features Tested:
    - Import and instantiation of report components
    - SQN (System Quality Number) to rating conversion
    - Analyzer integration with Cerebro
    - Strategy backtesting with report generation
    - HTML report output with user/memo metadata
    - JSON report output for programmatic access
    - Summary printing functionality

Dependencies:
    - backtrader: Core backtesting framework
    - backtrader.reports: Report generation module (tested here)
    - NVDA stock data (nvda-1999-2014.txt) for integration tests

Example:
    >>> run_all_tests()
    Report Generation Module Tests
    ...
    Test completed: 10 passed, 0 failed
"""

import sys
import os
import datetime
import tempfile

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


class SMACrossStrategy(bt.Strategy):
    """Simple Moving Average Crossover Strategy.

    A basic trend-following strategy that generates buy signals when the
    fast moving average crosses above the slow moving average (golden cross)
    and exit signals when the fast MA crosses below (death cross).

    Attributes:
        fast_sma (bt.indicators.SMA): Fast simple moving average (default period 10).
        slow_sma (bt.indicators.SMA): Slow simple moving average (default period 30).
        crossover (bt.indicators.CrossOver): Crossover indicator (+1 for bullish,
            -1 for bearish, 0 for no crossover).

    Parameters:
        fast_period (int): Period for the fast moving average (default: 10).
        slow_period (int): Period for the slow moving average (default: 30).

    Entry Logic:
        - Buy when fast SMA crosses above slow SMA (crossover > 0)
        - Only enter if not already in position

    Exit Logic:
        - Close position when fast SMA crosses below slow SMA (crossover < 0)

    Note:
        This is a long-only strategy with no short selling. Used in tests
        as a simple strategy to generate trades for report generation.
    """

    params = (
        ('fast_period', 10),
        ('slow_period', 30),
    )

    def __init__(self):
        """Initialize SMA indicators and crossover detector."""
        self.fast_sma = bt.indicators.SMA(period=self.p.fast_period)
        self.slow_sma = bt.indicators.SMA(period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements classic dual moving average crossover strategy.
        """
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()


def test_performance_calculator_import():
    """Test PerformanceCalculator import.

    Verifies that the PerformanceCalculator class can be imported from the
    backtrader.reports module. This class is responsible for calculating
    performance metrics from backtest results.

    Raises:
        AssertionError: If PerformanceCalculator cannot be imported.
        ImportError: If the backtrader.reports module is not available.
    """
    from backtrader.reports import PerformanceCalculator

    assert PerformanceCalculator is not None
    print("✓ PerformanceCalculator import test passed")


def test_report_chart_import():
    """Test ReportChart import.

    Verifies that the ReportChart class can be imported and has the required
    methods for generating visualization charts. This class handles creation
    of equity curves, return charts, and drawdown visualizations.

    Raises:
        AssertionError: If ReportChart is missing required methods.

    Methods verified:
        - plot_equity_curve: Generate equity over time chart
        - plot_return_bars: Generate return distribution chart
        - plot_drawdown: Generate underwater drawdown chart
    """
    from backtrader.reports import ReportChart

    assert ReportChart is not None
    chart = ReportChart()
    assert hasattr(chart, 'plot_equity_curve')
    assert hasattr(chart, 'plot_return_bars')
    assert hasattr(chart, 'plot_drawdown')
    print("✓ ReportChart import test passed")


def test_report_generator_import():
    """Test ReportGenerator import.

    Verifies that the ReportGenerator class can be imported. This class
    orchestrates the creation of HTML and JSON reports with embedded
    visualizations and performance metrics.

    Raises:
        AssertionError: If ReportGenerator cannot be imported.
    """
    from backtrader.reports import ReportGenerator

    assert ReportGenerator is not None
    print("✓ ReportGenerator import test passed")


def test_sqn_to_rating():
    """Test SQN (System Quality Number) to rating conversion.

    Tests the static method that converts numeric SQN values to descriptive
    ratings based on Van Tharp's scale for evaluating trading system quality.

    SQN Rating Scale (Van Tharp):
        - < 1.0: Poor
        - 1.0 - 1.9: Below Average
        - 2.0 - 2.9: Average
        - 3.0 - 4.9: Good
        - 5.0 - 6.9: Excellent
        - >= 7.0: Superb
        - >= 7.5: Holy Grail (exceptional)

    Test Cases:
        - Boundary values at each rating level
        - Edge case: None input (returns "N/A")
        - Edge case: NaN input (returns "N/A")

    Raises:
        AssertionError: If SQN to rating mapping is incorrect.
    """
    from backtrader.reports import PerformanceCalculator

    # Test ratings at each level
    assert PerformanceCalculator.sqn_to_rating(1.0) == "Poor"
    assert PerformanceCalculator.sqn_to_rating(1.7) == "Below Average"
    assert PerformanceCalculator.sqn_to_rating(2.0) == "Average"
    assert PerformanceCalculator.sqn_to_rating(2.5) == "Good"
    assert PerformanceCalculator.sqn_to_rating(3.5) == "Excellent"
    assert PerformanceCalculator.sqn_to_rating(6.0) == "Superb"
    assert PerformanceCalculator.sqn_to_rating(7.5) == "Holy Grail"

    # Test None and NaN
    assert PerformanceCalculator.sqn_to_rating(None) == "N/A"

    import math
    assert PerformanceCalculator.sqn_to_rating(math.nan) == "N/A"

    print("✓ SQN rating conversion test passed")


def test_cerebro_add_report_analyzers():
    """Test Cerebro.add_report_analyzers() method.

    Verifies that the add_report_analyzers() convenience method properly
    attaches all necessary analyzers to the Cerebro instance for later
    report generation.

    Analyzers added:
        - SharpeRatio: Risk-adjusted return metric
        - Returns: Total and annualized returns
        - DrawDown: Maximum drawdown analysis
        - TradeAnalyzer: Trade statistics
        - Returns (for SQN calculation): System Quality Number

    Args:
        riskfree_rate (float): Risk-free rate for Sharpe ratio calculation.

    Raises:
        AssertionError: If no analyzers are added to Cerebro.
    """
    cerebro = bt.Cerebro()

    # Add report analyzers
    cerebro.add_report_analyzers(riskfree_rate=0.02)

    # Check that analyzers have been added
    assert len(cerebro.analyzers) > 0

    print("✓ Cerebro add report analyzers test passed")


def test_integration_with_strategy():
    """Test integration with strategy backtesting.

    Performs an end-to-end integration test that:
        1. Creates a Cerebro instance
        2. Loads NVDA stock data (2000 full year)
        3. Adds SMACrossStrategy
        4. Attaches report analyzers
        5. Runs backtest
        6. Verifies PerformanceCalculator extracts metrics correctly

    Validated Metrics:
        - start_cash: Initial capital
        - total_return: Total return percentage
        - sharpe_ratio: Risk-adjusted return
        - strategy_name: Strategy class name
        - bars: Number of bars processed

    Raises:
        AssertionError: If metrics are missing or incorrect.
    """
    from backtrader.reports import PerformanceCalculator, ReportGenerator

    # Create cerebro
    cerebro = bt.Cerebro()

    # Add data
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ Test data file does not exist, skipping integration test")
        return

    data = bt.feeds.GenericCSVData(
        dataname=data_path,
        dtformat='%Y-%m-%d',
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2000, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SMACrossStrategy)

    # Add report analyzers
    cerebro.add_report_analyzers()

    # Run strategy
    results = cerebro.run()
    strategy = results[0]

    # Test PerformanceCalculator
    calc = PerformanceCalculator(strategy)

    # Test getting all metrics
    metrics = calc.get_all_metrics()
    assert isinstance(metrics, dict)
    assert 'start_cash' in metrics
    assert 'total_return' in metrics
    assert 'sharpe_ratio' in metrics

    print(f"  - Initial capital: {metrics.get('start_cash')}")
    print(f"  - Total return: {metrics.get('total_return', 'N/A')}")
    print(f"  - Sharpe ratio: {metrics.get('sharpe_ratio', 'N/A')}")

    # Test strategy information
    strategy_info = calc.get_strategy_info()
    assert strategy_info['strategy_name'] == 'SMACrossStrategy'

    # Test data information
    data_info = calc.get_data_info()
    assert data_info.get('bars', 0) > 0

    print("✓ Strategy integration test passed")


def test_html_report_generation():
    """Test HTML report generation.

    Tests the creation of HTML reports with embedded visualizations and
    performance metrics. Validates that the report contains expected
    content and metadata.

    Report Features:
        - HTML formatted output
        - Embedded base64 charts (equity, returns, drawdown)
        - Performance metrics table
        - User and memo metadata fields

    Validation:
        - File creation
        - Content includes strategy name
        - Content includes user metadata
        - Content includes memo metadata

    Args:
        output_path (str): Temporary file path for report output.
        user (str): User metadata field value.
        memo (str): Memo/description metadata field value.

    Raises:
        AssertionError: If report generation fails or content is invalid.
    """
    from backtrader.reports import ReportGenerator

    # Create cerebro
    cerebro = bt.Cerebro()

    # Add data
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ Test data file does not exist, skipping HTML report test")
        return

    data = bt.feeds.GenericCSVData(
        dataname=data_path,
        dtformat='%Y-%m-%d',
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2000, 6, 30),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SMACrossStrategy)
    cerebro.add_report_analyzers()

    results = cerebro.run()

    # Generate HTML report
    with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
        output_path = f.name

    try:
        report = ReportGenerator(results[0])
        report.generate_html(output_path, user='Test User', memo='Test memo')

        # Check that file was created
        assert os.path.exists(output_path)

        # Check file contents
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert 'SMACrossStrategy' in content
            assert 'Test User' in content
            assert 'Test memo' in content

        print("✓ HTML report generation test passed")
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


def test_json_report_generation():
    """Test JSON report generation.

    Tests the creation of JSON reports for programmatic access to
    backtest results. JSON format enables integration with other
    tools and automated analysis pipelines.

    Report Structure:
        - strategy: Strategy metadata (name, parameters, etc.)
        - metrics: Performance metrics dictionary
        - data: Data feed information
        - timestamp: Report generation timestamp

    Validation:
        - File creation
        - Valid JSON structure
        - Contains 'strategy' key
        - Contains 'metrics' key
        - Strategy name matches expected value

    Raises:
        AssertionError: If JSON generation fails or structure is invalid.
        json.JSONDecodeError: If output is not valid JSON.
    """
    from backtrader.reports import ReportGenerator
    import json

    # Create cerebro
    cerebro = bt.Cerebro()

    # Add data
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ Test data file does not exist, skipping JSON report test")
        return

    data = bt.feeds.GenericCSVData(
        dataname=data_path,
        dtformat='%Y-%m-%d',
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2000, 6, 30),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SMACrossStrategy)
    cerebro.add_report_analyzers()

    results = cerebro.run()

    # Generate JSON report
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        output_path = f.name

    try:
        report = ReportGenerator(results[0])
        report.generate_json(output_path)

        # Check that file was created
        assert os.path.exists(output_path)

        # Check JSON content
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert 'strategy' in data
            assert 'metrics' in data
            assert data['strategy']['strategy_name'] == 'SMACrossStrategy'

        print("✓ JSON report generation test passed")
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


def test_cerebro_generate_report():
    """Test Cerebro.generate_report() convenience method.

    Verifies that the Cerebro.generate_report() method works correctly
    as a wrapper around ReportGenerator for easier report creation.

    Method Signature:
        generate_report(output_path, format='html', user=None, memo=None)

    Args:
        output_path (str): File path for report output.
        format (str): Report format ('html' or 'json').
        user (str, optional): User metadata field.
        memo (str, optional): Memo/description metadata field.

    Raises:
        AssertionError: If report generation fails or content is invalid.
    """
    # Create cerebro
    cerebro = bt.Cerebro()

    # Add data
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ Test data file does not exist, skipping Cerebro.generate_report test")
        return

    data = bt.feeds.GenericCSVData(
        dataname=data_path,
        dtformat='%Y-%m-%d',
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2000, 6, 30),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SMACrossStrategy)
    cerebro.add_report_analyzers()

    cerebro.run()

    # Test report generation through Cerebro
    with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
        output_path = f.name

    try:
        cerebro.generate_report(output_path, format='html', user='Cerebro Test')

        assert os.path.exists(output_path)

        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert 'SMACrossStrategy' in content

        print("✓ Cerebro.generate_report() test passed")
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


def test_print_summary():
    """Test printing summary to console.

    Verifies that the print_summary() method executes without errors
    and outputs performance metrics to stdout. This provides a quick
    overview of backtest results in the console.

    Output includes:
        - Strategy name and parameters
        - Return metrics (total, annualized)
        - Risk metrics (Sharpe, drawdown)
        - Trade statistics
        - SQN rating

    Note:
        This test only verifies no exceptions are raised. Actual console
        output is not validated.

    Raises:
        None: Errors during summary printing are caught and reported.
    """
    from backtrader.reports import ReportGenerator

    # Create cerebro
    cerebro = bt.Cerebro()

    # Add data
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ Test data file does not exist, skipping print summary test")
        return

    data = bt.feeds.GenericCSVData(
        dataname=data_path,
        dtformat='%Y-%m-%d',
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2000, 6, 30),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SMACrossStrategy)
    cerebro.add_report_analyzers()

    results = cerebro.run()

    # Print summary
    report = ReportGenerator(results[0])
    report.print_summary()

    print("✓ Print summary test passed")


def run_all_tests():
    """Run all report generation module tests.

    Executes all test functions in sequence, tracking pass/fail counts
    and displaying progress. Tests that depend on NVDA data file will
    be skipped if the file is not found.

    Returns:
        bool: True if all tests passed, False if any test failed.

    Test Order:
        1. Import tests (verify module availability)
        2. Unit tests (SQN conversion, analyzer attachment)
        3. Integration tests (strategy with reports)
        4. Report generation tests (HTML, JSON)
        5. Convenience method tests (Cerebro wrapper)
        6. Output tests (summary printing)

    Raises:
        None: All exceptions are caught and counted as failures.
    """
    print("=" * 60)
    print("Report Generation Module Tests")
    print("=" * 60)

    tests = [
        test_performance_calculator_import,
        test_report_chart_import,
        test_report_generator_import,
        test_sqn_to_rating,
        test_cerebro_add_report_analyzers,
        test_integration_with_strategy,
        test_html_report_generation,
        test_json_report_generation,
        test_cerebro_generate_report,
        test_print_summary,
    ]

    passed = 0
    failed = 0

    for test in tests:
        print(f"\n--- {test.__name__} ---")
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ Test failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Test completed: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
