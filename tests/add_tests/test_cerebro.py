#!/usr/bin/env python
"""Test suite for Cerebro backtesting engine functionality.

This module contains tests for the core Cerebro engine, which is the main
orchestrator for backtesting in the backtrader framework. Tests cover:

* Basic Cerebro operations with data feeds and strategies
* Analyzer integration for performance metrics
* Observer integration for chart tracking

The tests use a simple moving average crossover strategy to verify
that Cerebro correctly orchestrates the backtesting workflow.
"""

import backtrader as bt


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime


class SimpleStrategy(bt.Strategy):
    """A simple moving average crossover trading strategy.

    This strategy implements a basic trend-following approach using a
    Simple Moving Average (SMA) indicator. It buys when price crosses
    above the SMA and closes positions when price crosses below.

    Attributes:
        sma (bt.indicators.SMA): The simple moving average indicator with
            a period of 15 bars.
    """
    def __init__(self):
        """Initialize the strategy and create indicators.

        Creates the Simple Moving Average indicator that will be used
        for trading signals.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple crossover strategy:
        - Buy when close price crosses above SMA (no existing position)
        - Close position when close price crosses below SMA

        The strategy only holds one position at a time (long-only).
        """
        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.buy()
        elif self.data.close[0] < self.sma[0]:
            self.close()


def test_cerebro_basic(main=False):
    """Test basic Cerebro engine functionality with a simple strategy.

    This test verifies that Cerebro can successfully:
    * Load and configure a data feed from a CSV file
    * Add and execute a trading strategy
    * Set initial broker cash
    * Run a complete backtest
    * Return a valid portfolio value

    The test uses 2006 daily price data and a simple SMA crossover strategy.

    Args:
        main (bool): If True, print debug output. Default is False.

    Raises:
        AssertionError: If the broker portfolio value is not positive after
            the backtest completes.

    Returns:
        None: This function performs assertions but does not return a value.
    """
    cerebro = bt.Cerebro()

    # Create a data feed
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(SimpleStrategy)
    cerebro.broker.setcash(10000.0)

    if main:
        # print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())  # Removed for performance
        pass

    cerebro.run()

    if main:
        # print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())  # Removed for performance
        pass

    # Verify cerebro ran
    assert cerebro.broker.getvalue() > 0


def test_cerebro_analyzer(main=False):
    """Test Cerebro engine with integrated analyzers.

    This test verifies that Cerebro can successfully:
    * Add SharpeRatio and Returns analyzers to a strategy
    * Execute backtest with analyzers collecting metrics
    * Access analyzer results from the completed strategy
    * Validate that analyzers are properly attached

    Analyzers provide performance metrics such as risk-adjusted returns
    and drawdown statistics that are essential for strategy evaluation.

    Args:
        main (bool): If True, print analyzer results to console. Default is False.

    Raises:
        AssertionError: If the sharpe or returns analyzers are not found
            in the strategy's analyzers collection.

    Returns:
        None: This function performs assertions but does not return a value.
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(SimpleStrategy)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

    results = cerebro.run()
    strat = results[0]

    if main:
        # print('Sharpe Ratio:', strat.analyzers.sharpe.get_analysis())  # Removed for performance
        pass
        print("Returns:", strat.analyzers.returns.get_analysis())

    # Verify analyzers worked
    assert hasattr(strat.analyzers, "sharpe")
    assert hasattr(strat.analyzers, "returns")


def test_cerebro_observer(main=False):
    """Test Cerebro engine with integrated observers.

    This test verifies that Cerebro can successfully:
    * Add observers to track portfolio metrics during backtesting
    * Execute backtest with observers collecting data
    * Validate that observers are properly attached to the strategy

    Observers track metrics like drawdown, cash value, and trade statistics
    throughout the backtest, which are typically used for visualization
    and post-analysis.

    Args:
        main (bool): If True, print debug output. Default is False.

    Raises:
        AssertionError: If no strategies were returned or if no observers
            are attached to the strategy.

    Returns:
        None: This function performs assertions but does not return a value.
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(SimpleStrategy)
    cerebro.addobserver(bt.observers.DrawDown)

    results = cerebro.run()

    # Verify observer was added
    assert len(results) > 0
    assert len(results[0].observers) > 0

    if main:
        # print('Cerebro with observers test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_cerebro_basic(main=True)
    test_cerebro_analyzer(main=True)
    test_cerebro_observer(main=True)
