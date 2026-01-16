#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Pair Trade Bollinger Pair Trading Bollinger Strategy.

Reference: https://github.com/mean_reversion_strategies
Uses Bollinger Bands and simplified hedge ratio for pair trading.
The original strategy uses Kalman Filter, here simplified to rolling OLS regression.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import numpy as np
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching in common directories.

    This function searches for a data file in multiple possible locations
    relative to the current test file directory. This allows tests to find
    their data files regardless of whether they are run from the tests/
    directory or the project root.

    Args:
        filename: The name of the data file to locate.

    Returns:
        Path: The absolute path to the first matching data file found.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched directories.

    Search Order:
        1. Current test directory (tests/strategies/)
        2. Parent test directory (tests/)
        3. Current test directory/datas/
        4. Parent test directory/datas/
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


class PairTradeBollingerStrategy(bt.Strategy):
    """Pair trading Bollinger Bands strategy.

    Uses two correlated assets for pair trading:
    - Calculate the Z-Score of the price spread
    - Go long on spread when Z-Score is below lower band
    - Go short on spread when Z-Score is above upper band
    - Close positions when Z-Score returns to mean
    """
    params = dict(
        lookback=20,
        entry_zscore=1.5,
        exit_zscore=0.2,
        stake=10,
    )

    def __init__(self):
        """Initialize the Pair Trade Bollinger Strategy.

        Sets up the strategy by:
        - Storing references to close prices of both data feeds
        - Initializing tracking variables for orders, statistics, and position state
        - Creating an empty spread history list for hedge ratio calculations

        Attributes:
            data0_close: Reference to close prices of the first asset (data0).
            data1_close: Reference to close prices of the second asset (data1).
            order: Current pending order, or None if no orders are pending.
            spread_history: List tracking historical spread values for Z-score calculation.
            hedge_ratio: Current hedge ratio used to size positions in the second asset.
                Starts at 1.0 and is updated dynamically using rolling regression.
            bar_num: Counter for the number of bars processed.
            buy_count: Counter for total buy orders executed.
            sell_count: Counter for total sell orders executed.
            position_state: Current position state encoded as:
                0 - Flat (no position)
                1 - Long spread (long data0, short data1)
                -1 - Short spread (short data0, long data1)
        """
        self.data0_close = self.datas[0].close
        self.data1_close = self.datas[1].close
        self.order = None

        self.spread_history = []
        self.hedge_ratio = 1.0

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

        # Position state: 0=flat, 1=long spread, -1=short spread
        self.position_state = 0

    def notify_order(self, order):
        """Handle order status notifications.

        This method is called by the backtrader engine whenever an order's
        status changes. It updates the buy/sell counters when orders are
        completed and clears the pending order reference.

        Args:
            order: The order object with updated status information.

        Order Status Handling:
            - Submitted/Acpected: No action taken, order is still pending.
            - Completed: Increments buy_count or sell_count based on order type.
            - Other statuses: Clears the pending order reference.

        Note:
            This method only tracks completed orders. Rejected, cancelled,
            or expired orders will also result in clearing self.order.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.order = None

    def calculate_zscore(self):
        """Calculate the Z-Score of the price spread.

        Returns:
            float: The Z-Score value, or 0 if insufficient data.
        """
        if len(self.spread_history) < self.p.lookback:
            return 0
        
        recent = self.spread_history[-self.p.lookback:]
        mean = np.mean(recent)
        std = np.std(recent)
        if std == 0:
            return 0
        return (self.spread_history[-1] - mean) / std

    def calculate_hedge_ratio(self):
        """Calculate hedge ratio using rolling regression.

        Returns:
            float: The calculated hedge ratio, or 1.0 if calculation fails.
        """
        if len(self) < self.p.lookback:
            return 1.0
        
        y = [self.data0_close[-i] for i in range(self.p.lookback)]
        x = [self.data1_close[-i] for i in range(self.p.lookback)]
        
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        
        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(len(x)))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(len(x)))
        
        if denominator == 0:
            return 1.0
        return numerator / denominator

    def next(self):
        """Execute trading logic for each bar.

        This method is called for every bar of data during the backtest.
        It implements the core pair trading logic:

        1. Updates the hedge ratio using rolling regression
        2. Calculates the current spread between the two assets
        3. Computes the Z-Score of the spread
        4. Enters positions when the Z-Score exceeds entry thresholds
        5. Exits positions when the Z-Score reverts toward the mean

        Trading Logic:
            - When flat (position_state == 0):
                * Go long spread if Z-Score < -entry_zscore (buy data0, sell data1)
                * Go short spread if Z-Score > entry_zscore (sell data0, buy data1)
            - When long spread (position_state == 1):
                * Close both legs if Z-Score > -exit_zscore
            - When short spread (position_state == -1):
                * Close both legs if Z-Score < exit_zscore

        Note:
            - No new orders are placed if there's a pending order
            - The hedge ratio is recalculated each bar using rolling OLS regression
            - Position sizing for data1 is adjusted by the hedge ratio
        """
        self.bar_num += 1

        # Update hedge ratio
        self.hedge_ratio = self.calculate_hedge_ratio()

        # Calculate spread
        spread = self.data0_close[0] - self.hedge_ratio * self.data1_close[0]
        self.spread_history.append(spread)

        if len(self.spread_history) < self.p.lookback:
            return

        zscore = self.calculate_zscore()

        if self.order:
            return

        # Trading logic
        if self.position_state == 0:
            # When flat
            if zscore < -self.p.entry_zscore:
                # Go long spread: buy data0, sell data1
                self.buy(data=self.datas[0], size=self.p.stake)
                self.sell(data=self.datas[1], size=int(self.p.stake * self.hedge_ratio))
                self.position_state = 1
            elif zscore > self.p.entry_zscore:
                # Go short spread: sell data0, buy data1
                self.sell(data=self.datas[0], size=self.p.stake)
                self.buy(data=self.datas[1], size=int(self.p.stake * self.hedge_ratio))
                self.position_state = -1

        elif self.position_state == 1:
            # When long spread, close position when Z-Score returns to mean
            if zscore > -self.p.exit_zscore:
                self.close(data=self.datas[0])
                self.close(data=self.datas[1])
                self.position_state = 0

        elif self.position_state == -1:
            # When short spread, close position when Z-Score returns to mean
            if zscore < self.p.exit_zscore:
                self.close(data=self.datas[0])
                self.close(data=self.datas[1])
                self.position_state = 0


def test_pair_trade_bollinger_strategy():
    """Run a backtest of the Pair Trade Bollinger strategy.

    This test function sets up and executes a complete backtest using historical
    data for two assets (ORCL and NVDA) to validate the Pair Trade Bollinger
    strategy implementation. It verifies that the strategy produces expected
    results for key performance metrics.

    Test Setup:
        - Initial capital: $100,000
        - Commission: 0.1% per trade
        - Data period: 2010-01-01 to 2014-12-31
        - Assets: Oracle (ORCL) and NVIDIA (NVDA)
        - Strategy parameters: lookback=20, entry_zscore=1.5, exit_zscore=0.2, stake=10

    Analyzers:
        - Sharpe Ratio: Risk-adjusted return metric
        - Returns: Annualized normalized returns
        - DrawDown: Maximum drawdown analysis

    Assertions:
        - bar_num equals 1257
        - final_value equals 99877.16 (within 0.01 tolerance)
        - sharpe_ratio equals -1.4903824617023596 (within 1e-6 tolerance)
        - annual_return equals -0.00024639413813618824 (within 1e-6 tolerance)
        - max_drawdown equals 0.14492238860330459 (within 1e-6 tolerance)

    Raises:
        AssertionError: If any of the expected values do not match within tolerance.
        FileNotFoundError: If the required data files cannot be located.

    Note:
        This test uses actual historical data to produce deterministic results.
        The assertions verify that the strategy behavior matches expected values
        after the metaclass removal refactoring.
    """
    cerebro = bt.Cerebro()

    # Load two data sources (using same data but different time periods to simulate pairs)
    data_path = resolve_data_path("orcl-1995-2014.txt")
    
    data0 = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    data_path_1 = resolve_data_path("nvda-1999-2014.txt")
    data1 = bt.feeds.GenericCSVData(
        dataname=str(data_path_1),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    
    cerebro.adddata(data0, name='asset0')
    cerebro.adddata(data1, name='asset1')
    cerebro.addstrategy(PairTradeBollingerStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Pair Trade Bollinger Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num == 1257, f"Expected bar_num=1257, got {strat.bar_num}"
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert abs(final_value - 99877.16) < 0.01, f"Expected final_value=99877.16, got {final_value}"
    assert abs(sharpe_ratio - (-1.4903824617023596)) < 1e-6, f"Expected sharpe_ratio=-1.4903824617023596, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00024639413813618824)) < 1e-6, f"Expected annual_return=-0.00024639413813618824, got {annual_return}"
    assert abs(max_drawdown - 0.14492238860330459) < 1e-6, f"Expected max_drawdown=0.14492238860330459, got {max_drawdown}"

    print("\nAll tests passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Pair Trade Bollinger Strategy Test")
    print("=" * 60)
    test_pair_trade_bollinger_strategy()
