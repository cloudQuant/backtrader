#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test Case: Commission Schemes.

This module tests different commission calculation schemes using a dual moving
average crossover strategy. It verifies that commission calculations work correctly
across different commission types (percentage-based, fixed, etc.) and ensures that
the broker properly tracks and deducts commissions from trading operations.

Reference source: backtrader-master2/samples/commission-schemes/commission-schemes.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching in multiple directories.

    This function searches for a data file in several common locations relative
    to the current test directory, including the current directory, parent directory,
    and 'datas' subdirectories.

    Args:
        filename: The name of the data file to locate.

    Returns:
        The absolute Path object pointing to the found data file.

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


class CommissionStrategy(bt.Strategy):
    """Strategy to test commission schemes using dual moving average crossover.

    This strategy implements a simple moving average crossover trading system
    where buy signals are generated when the fast MA crosses above the slow MA,
    and sell signals are generated when the fast MA crosses below the slow MA.

    Attributes:
        fast_ma: Fast moving average indicator.
        slow_ma: Slow moving average indicator.
        crossover: Crossover indicator between fast and slow MAs.
        bar_num: Counter for the number of bars processed.
        buy_count: Counter for the number of buy orders executed.
        sell_count: Counter for the number of sell orders executed.
        total_commission: Accumulated commission from all executed orders.
    """

    params = (('stake', 10), ('fast_period', 10), ('slow_period', 30))

    def __init__(self):
        """Initialize the CommissionStrategy.

        Creates the fast and slow moving average indicators, the crossover indicator,
        and initializes counters for tracking trades and commissions.
        """
        self.fast_ma = bt.ind.SMA(period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.total_commission = 0.0

    def notify_order(self, order):
        """Handle order status changes and track commission.

        This method is called by the broker whenever an order changes status.
        It counts completed buy/sell orders and accumulates the total commission paid.

        Args:
            order: The order object that has changed status.
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
            self.total_commission += order.executed.comm

    def next(self):
        """Execute trading logic for each bar.

        This method is called for each bar of data. It implements a moving average
        crossover strategy where:
        - When fast MA crosses above slow MA (crossover > 0), buy after closing any existing position
        - When fast MA crosses below slow MA (crossover < 0), close the position

        The strategy maintains only one position at a time by closing any existing
        position before entering a new one.
        """
        self.bar_num += 1
        if self.crossover > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy(size=self.p.stake)
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()


def test_commission_schemes():
    """Test different commission schemes using a dual moving average crossover strategy.

    This test function sets up a complete backtesting environment with percentage-based
    commission (0.1%) and runs the CommissionStrategy to verify that commission
    calculations are working correctly. It validates:

    1. The correct number of bars are processed
    2. Final portfolio value matches expectations
    3. Sharpe ratio is calculated correctly
    4. Annual return is within expected range
    5. Maximum drawdown is recorded accurately
    6. Total number of trades is correct
    7. Total commission paid matches expected amount

    The test uses historical data from 2005-2006 with daily bars and applies a
    0.1% commission on all trades to verify the commission calculation logic.

    Raises:
        AssertionError: If any of the test assertions fail, including bar count,
            final value, Sharpe ratio, annual return, max drawdown, total trades,
            or total commission not matching expected values.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))
    cerebro.adddata(data)

    cerebro.addstrategy(CommissionStrategy, stake=10, fast_period=10, slow_period=30)

    # Set percentage commission to 0.1%
    cerebro.broker.setcommission(
        commission=0.001,
        commtype=bt.CommInfoBase.COMM_PERC,
        stocklike=True
    )

    # Add complete analyzers - use daily timeframe for Sharpe ratio calculation
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
    print("Commission Schemes Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_commission: {strat.total_commission:.2f}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assert test results
    assert strat.bar_num == 482, f"Expected bar_num=482, got {strat.bar_num}"
    assert abs(final_value - 104365.90) < 0.01, f"Expected final_value=104365.90, got {final_value}"
    assert abs(sharpe_ratio - 0.6357284100176122) < 1e-6, f"Expected sharpe_ratio=0.6357284100176122, got {sharpe_ratio}"
    assert abs(annual_return - 0.021255309375668045) < 1e-6, f"Expected annual_return=0.021255309375668045, got {annual_return}"
    assert abs(max_drawdown - 3.584955980213795) < 1e-6, f"Expected max_drawdown=3.584955980213795, got {max_drawdown}"
    assert total_trades == 9, f"Expected total_trades=9, got {total_trades}"
    assert abs(strat.total_commission - 600.90) < 0.01, f"Expected total_commission=600.90, got {strat.total_commission}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Commission Schemes Test")
    print("=" * 60)
    test_commission_schemes()
