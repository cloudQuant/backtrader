#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test cases for Writer output functionality.

Reference: backtrader-master2/samples/writer-test/
Tests Writer output functionality using a price and SMA crossover strategy.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching common locations.

    This function searches for a data file in several standard locations
    relative to the test directory, including the current directory,
    parent directory, and 'datas' subdirectories.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search locations.
    """
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR / "datas" / filename,
        BASE_DIR.parent / "datas" / filename,
    ]
    for p in search_paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"Cannot find data file: {filename}")


class WriterTestStrategy(bt.Strategy):
    """Strategy to test Writer - price and SMA crossover.

    Strategy logic:
    - Buy when price crosses above SMA
    - Sell and close position when price crosses below SMA

    Attributes:
        crossover: CrossOver indicator tracking price vs SMA.
        bar_num: Counter for the number of bars processed.
        buy_count: Counter for buy orders executed.
        sell_count: Counter for sell orders executed.
    """
    params = (('period', 15),)

    def __init__(self):
        """Initialize the WriterTestStrategy.

        Sets up the Simple Moving Average (SMA) indicator and the crossover
        indicator that tracks when the price crosses above or below the SMA.
        Also initializes counters for tracking bars, buy orders, and sell orders.
        """
        sma = bt.ind.SMA(self.data, period=self.p.period)
        self.crossover = bt.ind.CrossOver(self.data.close, sma)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status changes and update trade counters.

        This method is called by the backtrader engine whenever an order's
        status changes. It tracks completed buy and sell orders by incrementing
        the respective counters.

        Args:
            order: The order object whose status has changed.
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def next(self):
        """Execute the trading logic for each bar.

        This method is called for each bar in the data feed. It implements
        a simple crossover strategy:
        - Buy when price crosses above the SMA (crossover > 0)
        - Close position when price crosses below the SMA (crossover < 0)

        The bar counter is incremented on each call.
        """
        self.bar_num += 1
        if self.crossover > 0 and not self.position:
            self.buy()
        elif self.crossover < 0 and self.position:
            self.close()


def test_writer():
    """Test Writer output functionality.

    This function tests the Writer functionality by running a backtest
    with a price-SMA crossover strategy and verifying the results. It sets up
    a Cerebro engine with data, strategy, and multiple analyzers, then runs
    the backtest and validates the output against expected values.

    Raises:
        AssertionError: If any of the backtest results do not match the
            expected values for bar count, final portfolio value, Sharpe ratio,
            annual return, maximum drawdown, or total trades.
        FileNotFoundError: If the required data file cannot be found.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    cerebro.addstrategy(WriterTestStrategy, period=15)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # Add Writer (no CSV output, only for testing functionality)
    cerebro.addwriter(bt.WriterFile, csv=False, rounding=4)

    # Add complete analyzers - use daily timeframe to calculate Sharpe ratio
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe = strat.analyzers.sharpe.get_analysis()
    ret = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    sharpe_ratio = sharpe.get('sharperatio', None)
    annual_return = ret.get('rnorm', 0)
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    total_trades = trades.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Print results in standard format
    print("\n" + "=" * 50)
    print("Writer Output Functionality Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assert test results
    assert strat.bar_num == 240, f"Expected bar_num=240, got {strat.bar_num}"
    assert abs(final_value - 102841.00) < 0.01, f"Expected final_value=102841.00, got {final_value}"
    assert abs(sharpe_ratio - 0.8252115748419219) < 1e-6, f"Expected sharpe_ratio=0.8252115748419219, got {sharpe_ratio}"
    assert abs(annual_return - 0.0280711170741429) < 1e-6, f"Expected annual_return=0.0280711170741429, got {annual_return}"
    assert abs(max_drawdown - 2.615813541154893) < 1e-6, f"Expected max_drawdown=2.615813541154893, got {max_drawdown}"
    assert total_trades == 12, f"Expected total_trades=12, got {total_trades}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Writer Output Functionality Test")
    print("=" * 60)
    test_writer()
