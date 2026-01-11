#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Data Pandas Data Loading

Reference source: backtrader-master2/samples/data-pandas/data-pandas.py
Tests loading data from Pandas DataFrame using a simple dual moving average crossover strategy.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import pandas as pd
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolves the absolute path of a data file by searching common directories.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Absolute Path object pointing to the data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the search paths.
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


class SimpleMAStrategy(bt.Strategy):
    """Simple dual moving average crossover strategy for testing Pandas data loading.

    Strategy logic:
        - Buy when fast MA crosses above slow MA
        - Sell and close position when fast MA crosses below slow MA

    Attributes:
        fast_ma: Fast moving average indicator.
        slow_ma: Slow moving average indicator.
        crossover: Crossover indicator between fast and slow MAs.
        order: Current pending order.
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
    """
    params = (('fast_period', 10), ('slow_period', 30))

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables.

        Sets up the fast and slow moving averages, crossover indicator,
        and initializes counters for orders and bars.
        """
        self.fast_ma = bt.ind.SMA(period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Called when an order's status changes. Tracks completed buy/sell orders
        and clears the pending order reference when the order is no longer alive.

        Args:
            order: The order object with updated status.
        """
        if not order.alive():
            self.order = None
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def notify_trade(self, trade):
        """Handle trade notifications.

        Called when a trade is opened or closed. This method is required by the
        Strategy interface but is currently unused in this implementation.

        Args:
            trade: The trade object containing trade information.
        """

    def next(self):
        """Execute trading logic for each bar.

        Implements the dual moving average crossover strategy:
        1. Increment bar counter
        2. Skip if there's a pending order
        3. If crossover is positive (fast MA above slow MA), close any existing
           position and open a long position
        4. If crossover is negative (fast MA below slow MA), close any position
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

    def stop(self):
        """Called when the backtest is finished.

        This method is required by the Strategy interface but is currently
        unused in this implementation. It can be used for cleanup or final
        logging operations.
        """


def test_data_pandas():
    """Tests Pandas data loading functionality with a simple strategy.

    This test loads data from a CSV file into a Pandas DataFrame, then uses
    bt.feeds.PandasData to load it into the backtrader engine. It runs a
    simple dual moving average crossover strategy and verifies the results.

    Raises:
        AssertionError: If any of the test assertions fail (bar count, final
            value, Sharpe ratio, annual return, max drawdown, or trade count).
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")

    # Read CSV into DataFrame
    dataframe = pd.read_csv(
        str(data_path),
        header=0,
        parse_dates=True,
        index_col=0,
    )

    print(f"DataFrame shape: {dataframe.shape}")

    # Load data using PandasData
    data = bt.feeds.PandasData(dataname=dataframe, nocase=True)
    cerebro.adddata(data)

    # Add simple dual moving average crossover strategy
    cerebro.addstrategy(SimpleMAStrategy, fast_period=10, slow_period=30)

    # Add complete analyzers - calculate Sharpe ratio using daily timeframe
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Print results in standard format
    print("\n" + "=" * 50)
    print("Data Pandas Data Loading Backtest Results:")
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
    assert strat.bar_num == 482, f"Expected bar_num=482, got {strat.bar_num}"
    assert abs(final_value - 100496.68) < 0.01, f"Expected final_value=100496.68, got {final_value}"
    assert abs(sharpe_ratio - 0.7052880693319075) < 1e-6, f"Expected sharpe_ratio=0.7052880693319075, got {sharpe_ratio}"
    assert abs(annual_return - 0.0024415216620913218) < 1e-6, f"Expected annual_return=0.0024415216620913218, got {annual_return}"
    assert abs(max_drawdown - 0.35642156216533016) < 1e-6, f"Expected max_drawdown=0.35642156216533016, got {max_drawdown}"
    assert total_trades == 9, f"Expected total_trades=9, got {total_trades}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Data Pandas Data Loading Test")
    print("=" * 60)
    test_data_pandas()
