#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test Case: MACD + DMI Simplified Strategy.

This module tests a simplified trading strategy that combines MACD (Moving Average
Convergence Divergence) and DMI (Directional Movement Index) indicators to generate
trading signals. The strategy uses MACD crossovers as the primary signal and was
designed to avoid attribute conflicts present in earlier backtrader implementations.

Reference: backtrader-strategies/macddmi.py

The strategy implements:
- Entry signals based on MACD line crossing above/below the signal line
- Exit signals on MACD crossover reversal
- Position sizing with configurable stake amount

Test data: Oracle Corporation (ORCL) historical data from 2010-2014
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching multiple possible locations.

    This function searches for a data file in several common locations relative
    to the current script's directory, including the current directory, parent
    directory, and 'datas' subdirectories.

    Args:
        filename: The name of the data file to locate.

    Returns:
        Path: The absolute path to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched locations.

    Search Order:
        1. Current directory (BASE_DIR / filename)
        2. Parent directory (BASE_DIR.parent / filename)
        3. datas/ subdirectory (BASE_DIR / "datas" / filename)
        4. Parent datas/ subdirectory (BASE_DIR.parent / "datas" / filename)
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


class MacdDmiSimpleStrategy(bt.Strategy):
    """MACD + DMI Simplified Strategy.

    A trading strategy that combines MACD (Moving Average Convergence Divergence)
    and DMI (Directional Movement Index) indicators to generate trading signals.
    This is a simplified version designed to avoid attribute conflicts present in
    earlier backtrader implementations.

    Entry Logic:
        - Long: MACD line crosses above signal line (golden cross)
        - Short: MACD line crosses below signal line (death cross)

    Exit Logic:
        - Long position: Close when MACD crosses below signal line
        - Short position: Close when MACD crosses above signal line

    Attributes:
        macd: MACD indicator with configurable periods
        dmi: Directional Movement Index indicator
        macd_cross: Crossover signal indicator (positive for golden cross,
            negative for death cross)
        order: Current pending order (None if no order pending)
        bar_num: Counter for the number of bars processed
        buy_count: Total number of buy orders executed
        sell_count: Total number of sell orders executed

    Parameters:
        stake: Number of shares/contracts per trade (default: 10)
        macd_fast: Fast EMA period for MACD calculation (default: 12)
        macd_slow: Slow EMA period for MACD calculation (default: 26)
        macd_signal: Signal line EMA period for MACD (default: 9)
        dmi_period: Period for DMI calculation (default: 14)
    """
    params = dict(
        stake=10,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        dmi_period=14,
    )

    def __init__(self):
        """Initialize the MACD + DMI strategy.

        Sets up the technical indicators and initializes tracking variables for
        order management and statistics.
        """
        # MACD indicator
        self.macd = bt.indicators.MACD(
            self.data,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal,
        )

        # DMI indicator
        self.dmi = bt.indicators.DirectionalMovementIndex(
            self.data, period=self.p.dmi_period
        )

        # MACD crossover signal
        self.macd_cross = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Called by backtrader when an order's status changes. This method updates
        the buy/sell counters when orders are completed and clears the pending
        order reference.

        Args:
            order: The order object with updated status.

        Note:
            Orders with status Submitted or Accepted are ignored as they are
            still pending execution. Only Completed orders trigger counter updates.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        """Execute trading logic for each bar.

        This method is called by backtrader for each new data bar. It implements
        the core trading strategy:

        1. Increments the bar counter
        2. Checks if there's a pending order (if so, waits)
        3. If no position: enters long on MACD golden cross, short on death cross
        4. If in position: exits on MACD crossover reversal

        Entry signals are based on the MACD crossover indicator:
        - macd_cross > 0: MACD line crossed above signal line (bullish)
        - macd_cross < 0: MACD line crossed below signal line (bearish)

        Note:
            The DMI indicator is calculated but not actively used in this
            simplified version. It's maintained for potential future enhancements.
        """
        self.bar_num += 1

        if self.order:
            return

        plus_di = self.dmi.DIplus[0]
        minus_di = self.dmi.DIminus[0]

        if not self.position:
            # Long entry: MACD golden cross
            if self.macd_cross[0] > 0:
                self.order = self.buy(size=self.p.stake)
            # Short entry: MACD death cross
            elif self.macd_cross[0] < 0:
                self.order = self.sell(size=self.p.stake)
        else:
            # Exit condition: MACD reverse crossover
            if self.position.size > 0 and self.macd_cross[0] < 0:
                self.order = self.close()
            elif self.position.size < 0 and self.macd_cross[0] > 0:
                self.order = self.close()


def test_macd_dmi_simple_strategy():
    """Test the MACD + DMI simplified strategy.

    This test function runs a backtest of the MacdDmiSimpleStrategy using
    Oracle Corporation (ORCL) historical price data from 2010-2014. It verifies
    that the strategy produces consistent results by asserting expected values
    for various performance metrics.

    Test Configuration:
        - Initial capital: $100,000
        - Commission: 0.1% per trade
        - Data period: 2010-01-01 to 2014-12-31
        - Position size: 10 shares per trade

    Performance Metrics Analyzed:
        - Sharpe Ratio: Risk-adjusted return measure
        - Annual Return: Normalized annual return
        - Maximum Drawdown: Largest peak-to-trough decline
        - Final Portfolio Value: Ending cash value

    Expected Results:
        - bar_num: 1223 bars processed
        - final_value: ~$99,948.71 (slight loss)
        - sharpe_ratio: -0.208 (negative risk-adjusted return)
        - annual_return: -0.010% (small negative return)
        - max_drawdown: 12.26% (maximum drawdown)

    Raises:
        AssertionError: If any of the expected values don't match within tolerance.
            Tolerances: 1e-12 for annual_return, 1e-6 for other metrics,
            0.01 for final_value.

    Note:
        The test demonstrates that the simplified MACD strategy produces
        consistent results, even though it doesn't generate positive returns
        for this particular dataset and time period.
    """
    cerebro = bt.Cerebro()
    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(MacdDmiSimpleStrategy)
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
    print("MACD + DMI Simplified Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1223, f"Expected bar_num=1223, got {strat.bar_num}"
    assert abs(final_value - 99948.71) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (-0.20797152972748584)) < 1e-6, f"Expected sharpe_ratio=-0.20797152972748584, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00010284209965205515)) < 1e-12, f"Expected annual_return=-0.00010284209965205515, got {annual_return}"
    assert abs(max_drawdown - 0.12263737758169839) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("MACD + DMI Simplified Strategy Test")
    print("=" * 60)
    test_macd_dmi_simple_strategy()
