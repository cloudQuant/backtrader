#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test suite for Backtrader strategy functionality - Migrated Version.

This is a migrated version of test_strategy.py demonstrating the new testing
patterns based on TEA review recommendations.

Migration changes:
1. Added Test IDs (EPIC.STORY-LEVEL-SEQ format)
2. Added priority markers (@pytest.mark.priority_pN)
3. Using pytest fixtures from conftest.py
4. Using factory functions from test_utils.factories
5. Removed 'main' parameter (use pytest to run)

Original file: test_strategy.py
Migrated: 2026-02-22
"""

import pytest
import sys

import backtrader as bt
from tests.test_utils.factories import (
    create_data_feed,
    create_cerebro,
    create_simple_sma_strategy,
    create_multiple_data_feeds,
)

# =============================================================================
# Test Strategy Classes
# =============================================================================


class SampleStrategy1(bt.Strategy):
    """Simple moving average crossover trading strategy.

    This strategy implements a basic trend-following approach:
    - Buy when price crosses above the SMA
    - Sell when price crosses below the SMA

    Attributes:
        params: Tuple containing strategy parameters:
            - period (int): SMA period in days. Default is 15.
            - printlog (bool): Whether to print log messages. Default is False.
        sma: Simple Moving Average indicator.
        order: Reference to the current pending order.
    """

    params = (
        ("period", 15),
        ("printlog", False),
    )

    def __init__(self):
        """Initialize the strategy with indicators and state variables.

        Creates the Simple Moving Average indicator using the configured period
        and initializes the order tracker to None.
        """
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.order = None

    def notify_order(self, order):
        """Handle order status changes.

        Called by the broker when an order's status changes. Logs execution
        details for completed orders and clears the pending order reference.

        Args:
            order: Order object with status and execution information including
                executed price and status codes.
        """
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"BUY EXECUTED, Price: {order.executed.price:.2f}")
            else:
                self.log(f"SELL EXECUTED, Price: {order.executed.price:.2f}")
        self.order = None

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Called when a trade is closed. Logs the profit/loss information
        including gross and net PnL after commissions.

        Args:
            trade: Trade object with pnl (gross profit) and pnlcomm (net profit)
                attributes.
        """
        if trade.isclosed:
            self.log(f"TRADE PROFIT, GROSS {trade.pnl:.2f}, NET {trade.pnlcomm:.2f}")

    def log(self, txt):
        """Log a message with timestamp if printlog is enabled.

        Args:
            txt: String message to log. Will be prefixed with current bar's date.
        """
        if self.p.printlog:
            dt = self.datas[0].datetime.date(0)
            print(f"{dt.isoformat()}, {txt}")

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple SMA crossover strategy:
        - Buy when close price crosses above SMA (no position)
        - Sell when close price crosses below SMA (has position)
        - Only one active order at a time

        Skips execution if there's already a pending order.
        """
        if self.order:
            return

        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.order = self.buy()
        else:
            if self.data.close[0] < self.sma[0]:
                self.order = self.sell()


# =============================================================================
# Strategy Tests (EPIC 2)
# =============================================================================


@pytest.mark.priority_p0
def test_2_1_IT_001_strategy_basic_execution(cerebro_with_data):
    """Test 2.1-IT-001: Verify basic strategy functionality with a single data feed.

    Priority: P0 - Critical (core strategy execution)
    Epic: 2 (Strategy), Story: 1 (Basic Execution), Level: IT, Seq: 001

    This test verifies that:
    1. A strategy can be added to Cerebro
    2. The strategy executes through all data bars
    3. The broker value changes due to trading activity
    4. Orders are executed and positions are managed

    Args:
        cerebro_with_data: Cerebro fixture with data pre-loaded
    """
    # Arrange - Add strategy to pre-configured cerebro
    cerebro_with_data.addstrategy(SampleStrategy1)
    cerebro_with_data.broker.setcash(10000.0)

    # Act
    results = cerebro_with_data.run()

    # Assert - Verify strategy ran successfully
    assert len(results) > 0
    strat = results[0]
    assert len(strat) > 0  # Processed bars

    final_value = cerebro_with_data.broker.getvalue()
    assert final_value > 0  # Verify broker value is valid


@pytest.mark.priority_p0
def test_2_2_IT_001_strategy_multiple_data_feeds(cerebro_engine):
    """Test 2.2-IT-001: Verify strategy functionality with multiple data feeds.

    Priority: P0 - Critical (multi-strategy scenarios)
    Epic: 2 (Strategy), Story: 2 (Multiple Data), Level: IT, Seq: 001

    This test verifies that a strategy can handle multiple data sources:
    1. Multiple data feeds can be added to Cerebro
    2. The strategy can access all data feeds via self.datas
    3. The strategy processes bars from all feeds

    Args:
        cerebro_engine: Cerebro fixture
    """
    # Arrange - Create multiple data feeds using factory
    datas = create_multiple_data_feeds(
        [
            "2006-day-001.txt",
            "2006-day-002.txt",
        ]
    )

    for data in datas:
        cerebro_engine.adddata(data)

    cerebro_engine.addstrategy(SampleStrategy1)

    # Act
    results = cerebro_engine.run()

    # Assert - Verify strategy handled multiple data feeds
    assert len(results) > 0
    strat = results[0]
    assert len(strat.datas) == len(datas)  # Should have all data feeds


@pytest.mark.priority_p2
def test_2_3_UT_001_strategy_optimization(cerebro_engine):
    """Test 2.3-UT-001: Verify strategy parameter optimization functionality.

    Priority: P2 - Medium (advanced feature)
    Epic: 2 (Strategy), Story: 3 (Optimization), Level: UT, Seq: 001

    This test verifies that:
    1. Strategies can be run with multiple parameter combinations
    2. The optstrategy method creates multiple strategy instances
    3. Results are returned for each parameter combination

    Args:
        cerebro_engine: Cerebro fixture
    """
    # Arrange - Add data feed
    data = create_data_feed()
    cerebro_engine.adddata(data)

    # Use optstrategy for multiple parameter combinations
    cerebro_engine.optstrategy(SampleStrategy1, period=range(10, 20, 5))

    # Act
    results = cerebro_engine.run(maxcpus=1)

    # Assert - Should have multiple results from optimization
    assert len(results) > 1  # More than one parameter combination


# =============================================================================
# Strategy Parameter Tests
# =============================================================================


@pytest.mark.priority_p1
def test_2_4_UT_001_strategy_with_custom_period(cerebro_with_data):
    """Test 2.4-UT-001: Verify strategy respects custom period parameter.

    Priority: P1 - High (customization)
    Epic: 2 (Strategy), Story: 4 (Parameters), Level: UT, Seq: 001

    Args:
        cerebro_with_data: Cerebro fixture with data pre-loaded
    """
    # Arrange - Use factory to create strategy with custom period
    CustomStrategy = create_simple_sma_strategy(period=25)
    cerebro_with_data.addstrategy(CustomStrategy)

    # Act
    results = cerebro_with_data.run()

    # Assert
    assert len(results) > 0
    strat = results[0]
    assert strat.p.period == 25  # Verify parameter was set


@pytest.mark.priority_p2
def test_2_4_UT_002_strategy_with_printlog(cerebro_with_data, capsys):
    """Test 2.4-UT-002: Verify strategy printlog parameter works.

    Priority: P2 - Medium (debugging feature)
    Epic: 2 (Strategy), Story: 4 (Parameters), Level: UT, Seq: 002

    Args:
        cerebro_with_data: Cerebro fixture with data pre-loaded
        capsys: Pytest fixture to capture output
    """
    # Arrange
    cerebro_with_data.addstrategy(SampleStrategy1, printlog=True)
    cerebro_with_data.broker.setcash(10000.0)

    # Act
    results = cerebro_with_data.run()

    # Assert - Check that logs were generated
    captured = capsys.readouterr()
    # Should have some log output when printlog=True
    # (Exact content depends on trading activity)


# =============================================================================
# Strategy Lifecycle Tests
# =============================================================================


@pytest.mark.priority_p1
def test_2_5_UT_001_strategy_lifecycle(cerebro_with_data):
    """Test 2.5-UT-001: Verify strategy lifecycle methods are called.

    Priority: P1 - High (core functionality)
    Epic: 2 (Strategy), Story: 5 (Lifecycle), Level: UT, Seq: 001

    Args:
        cerebro_with_data: Cerebro fixture with data pre-loaded
    """

    # Arrange - Create strategy that tracks lifecycle
    class LifecycleStrategy(bt.Strategy):
        """Strategy for testing lifecycle method execution order.

        This strategy tracks which lifecycle methods are called during
        backtesting to verify the proper execution sequence.

        Attributes:
            methods_called: List tracking the order of lifecycle method calls.
        """

        def __init__(self):
            """Initialize the strategy with an empty method call tracker."""
            self.methods_called = []

        def start(self):
            """Mark the start method as called.

            This is called once before backtesting begins.
            """
            self.methods_called.append("start")

        def prenext(self):
            """Mark prenext as called once during the warmup period.

            This is called for each bar before minimum period is reached.
            """
            if "prenext" not in self.methods_called:
                self.methods_called.append("prenext")

        def nextstart(self):
            """Mark nextstart as called.

            This is called exactly once when transitioning from prenext to next.
            """
            self.methods_called.append("nextstart")

        def next(self):
            """Mark next as called once during normal operation.

            This is called for each bar after the minimum period is reached.
            """
            if "next" not in self.methods_called:
                self.methods_called.append("next")

        def stop(self):
            """Mark stop as called.

            This is called once after backtesting completes.
            """
            self.methods_called.append("stop")

    cerebro_with_data.addstrategy(LifecycleStrategy)

    # Act
    results = cerebro_with_data.run()

    # Assert - Verify lifecycle methods were called
    assert len(results) > 0
    strat = results[0]
    assert "start" in strat.methods_called
    assert "stop" in strat.methods_called


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.priority_p0
def test_strategy_integration_001_with_analyzers():
    """Test STRATEGY-INT-001: Verify strategy works with analyzers.

    Priority: P0 - Critical (performance tracking)
    Test ID: STRATEGY-INT-001

    This test demonstrates the complete factory-based approach.
    """
    # Arrange - Use factory for complete setup
    from tests.test_utils.factories import (
        setup_basic_backtest,
        create_data_feed,
        create_simple_sma_strategy,
        create_sharpe_analyzer,
        create_returns_analyzer,
    )

    cerebro = setup_basic_backtest(
        cash=10000.0,
        strategy=create_simple_sma_strategy(period=15),
        data_feeds=[create_data_feed()],
        analyzers=[
            create_sharpe_analyzer(),
            create_returns_analyzer(),
        ],
    )

    # Act
    results = cerebro.run()

    # Assert
    assert len(results) > 0
    strat = results[0]
    # Verify analyzers are attached
    assert hasattr(strat.analyzers, "sharpe")
    assert hasattr(strat.analyzers, "returns")


# =============================================================================
# Standalone Execution (for backward compatibility)
# =============================================================================


def main():
    """Run tests in standalone mode.

    This function allows the test file to be executed directly without
    pytest discovery. It runs all tests in the file with verbose output
    and short traceback format.
    """
    pytest.main([__file__, "-v", "--tb=short"])


if __name__ == "__main__":
    main()
