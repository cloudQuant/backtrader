#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case for Sharpe ratio and TimeReturn analyzers.

This test module evaluates the Sharpe ratio and TimeReturn analyzers using a
dual moving average crossover strategy.

Reference: backtrader-master2/samples/sharpe-timereturn/sharpe-timereturn.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching common locations.

    This function searches for a data file in multiple common locations
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


class SharpeTestStrategy(bt.Strategy):
    """Test strategy for Sharpe ratio analysis using dual moving average crossover.

    This strategy implements a simple moving average crossover system where:
    - Buy signal occurs when the fast MA crosses above the slow MA
    - Sell signal occurs when the fast MA crosses below the slow MA

    Attributes:
        crossover: Indicator tracking MA crossover signals
        order: Current pending order
        bar_num: Counter for processed bars
        buy_count: Number of buy orders executed
        sell_count: Number of sell orders executed

    Args:
        p1: Period for the fast moving average (default: 10)
        p2: Period for the slow moving average (default: 30)
    """
    params = (('p1', 10), ('p2', 30))

    def __init__(self):
        """Initialize the SharpeTestStrategy.

        Sets up the moving average indicators and initializes tracking variables
        for orders and trading statistics.
        """
        ma1 = bt.ind.SMA(period=self.p.p1)
        ma2 = bt.ind.SMA(period=self.p.p2)
        self.crossover = bt.ind.CrossOver(ma1, ma2)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order notification events.

        Updates the order reference when orders are completed or cancelled,
        and tracks the count of buy and sell orders executed.

        Args:
            order: The order object that triggered this notification.
        """
        if not order.alive():
            self.order = None
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def next(self):
        """Execute trading logic for each bar.

        Implements the dual moving average crossover strategy:
        - When crossover > 0 (fast MA crosses above slow MA): close existing
          position and buy
        - When crossover < 0 (fast MA crosses below slow MA): close existing
          position
        - Only one order is allowed at a time
        """
        self.bar_num += 1
        if self.order:
            return
        if self.crossover > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()


def test_sharpe_timereturn():
    """Test Sharpe ratio and TimeReturn analyzers.

    This function sets up a backtesting environment with the SharpeTestStrategy,
    runs the backtest, and verifies the results against expected values.

    The test validates:
        - Sharpe ratio calculation
        - Annual return rate
        - Maximum drawdown
        - Total number of trades
        - Final portfolio value

    Raises:
        AssertionError: If any of the test assertions fail
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    cerebro.addstrategy(SharpeTestStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # Add comprehensive analyzers - calculate Sharpe ratio using daily timeframe
    cerebro.addanalyzer(bt.analyzers.TimeReturn, timeframe=bt.TimeFrame.Years, _name="yearly")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, timeframe=bt.TimeFrame.Months, _name="monthly")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    yearly = strat.analyzers.yearly.get_analysis()
    monthly = strat.analyzers.monthly.get_analysis()
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
    print("Sharpe TimeReturn Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print(f"  Yearly Returns: {yearly}")
    print("=" * 50)

    # Assert test results
    assert strat.bar_num == 482, f"Expected bar_num=482, got {strat.bar_num}"
    assert abs(final_value - 104966.80) < 0.01, f"Expected final_value=104966.80, got {final_value}"
    assert abs(sharpe_ratio - 0.7210685207398165) < 1e-6, f"Expected sharpe_ratio=0.7210685207398165, got {sharpe_ratio}"
    assert abs(annual_return - 0.024145144571516192) < 1e-6, f"Expected annual_return=0.024145144571516192, got {annual_return}"
    assert abs(max_drawdown - 3.430658473286522) < 1e-6, f"Expected max_drawdown=3.430658473286522, got {max_drawdown}"
    assert total_trades == 9, f"Expected total_trades=9, got {total_trades}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Sharpe TimeReturn Test")
    print("=" * 60)
    test_sharpe_timereturn()
