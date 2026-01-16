#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Chandelier Exit strategy

Reference: backtrader-strategies-compendium/strategies/MA_Chandelier.py
Uses Chandelier Exit indicator combined with moving average crossover
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching common directories.

    This function searches for data files in several standard locations
    relative to the test file directory, including the current directory,
    parent directory, and 'datas' subdirectories.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the first found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths.
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


class ChandelierExitIndicator(bt.Indicator):
    """Chandelier Exit volatility-based trailing stop indicator.

    This indicator calculates trailing stop levels for both long and short
    positions based on the Highest high, Lowest low, and Average True Range (ATR).

    Lines:
        long: Long exit level (Highest high - ATR * multiplier)
        short: Short exit level (Lowest low + ATR * multiplier)

    Params:
        period (int): Lookback period for Highest/Lowest and ATR calculation. Default is 22.
        multip (float): Multiplier for ATR. Default is 3.
    """
    lines = ('long', 'short')
    params = dict(period=22, multip=3)
    plotinfo = dict(subplot=False)

    def __init__(self):
        """Initialize the Chandelier Exit indicator.

        Sets up the calculation pipeline by:
        1. Computing the Highest high over the lookback period
        2. Computing the Lowest low over the lookback period
        3. Computing Average True Range (ATR) over the lookback period
        4. Calculating long exit as Highest high - (ATR * multiplier)
        5. Calculating short exit as Lowest low + (ATR * multiplier)
        """
        highest = bt.ind.Highest(self.data.high, period=self.p.period)
        lowest = bt.ind.Lowest(self.data.low, period=self.p.period)
        atr = self.p.multip * bt.ind.ATR(self.data, period=self.p.period)
        self.lines.long = highest - atr
        self.lines.short = lowest + atr


class ChandelierExitStrategy(bt.Strategy):
    """Chandelier Exit trailing stop strategy.

    This strategy combines moving average crossover with the Chandelier Exit
    indicator to determine entry and exit points.

    Entry conditions:
        Long: SMA8 > SMA15 AND Price > Chandelier Short

    Exit conditions:
        SMA8 < SMA15 AND Price < Chandelier Long

    Args:
        stake (int): Number of shares to trade. Default is 10.
        sma_fast (int): Fast SMA period. Default is 8.
        sma_slow (int): Slow SMA period. Default is 15.
        ce_period (int): Chandelier Exit period. Default is 22.
        ce_mult (float): Chandelier Exit ATR multiplier. Default is 3.

    Attributes:
        sma_fast: Fast simple moving average indicator.
        sma_slow: Slow simple moving average indicator.
        ce: Chandelier Exit indicator instance.
        order: Current pending order.
        bar_num: Number of bars processed.
        buy_count: Total number of buy orders executed.
        sell_count: Total number of sell orders executed.
    """
    params = dict(
        stake=10,
        sma_fast=8,
        sma_slow=15,
        ce_period=22,
        ce_mult=3,
    )

    def __init__(self):
        """Initialize the Chandelier Exit strategy.

        Sets up the required indicators and initializes tracking variables:
        - Fast and slow Simple Moving Averages for trend detection
        - Chandelier Exit indicator for trailing stop levels
        - Order tracking to prevent duplicate orders
        - Counters for bars processed and trades executed
        """
        self.sma_fast = bt.indicators.SMA(self.data, period=self.p.sma_fast)
        self.sma_slow = bt.indicators.SMA(self.data, period=self.p.sma_slow)
        self.ce = ChandelierExitIndicator(
            self.data, period=self.p.ce_period, multip=self.p.ce_mult
        )

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status notifications.

        Updates trade counters when orders are completed and clears the
        pending order reference. Ignores orders that are still pending
        (Submitted or Accepted status).

        Args:
            order: The Order object with updated status information.
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
        """Execute the strategy logic for each bar.

        This method is called on every bar during the backtest. It:
        1. Increments the bar counter
        2. Skips trading if an order is already pending
        3. If no position: Enters long when SMA fast > SMA slow AND
           price > Chandelier short exit level
        4. If in position: Exits when SMA fast < SMA slow AND
           price < Chandelier long exit level

        The Chandelier Exit acts as a volatility-adjusted trailing stop,
        helping to protect profits during adverse price movements.
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # SMA golden cross AND price above Chandelier Short
            if self.sma_fast[0] > self.sma_slow[0] and self.data.close[0] > self.ce.short[0]:
                self.order = self.buy(size=self.p.stake)
        else:
            # SMA death cross AND price below Chandelier Long
            if self.sma_fast[0] < self.sma_slow[0] and self.data.close[0] < self.ce.long[0]:
                self.order = self.close()


def test_chandelier_exit_strategy():
    """Test the Chandelier Exit strategy backtest.

    This function sets up and runs a backtest of the Chandelier Exit strategy
    using Oracle (ORCL) historical data from 2010-2014. It verifies the
    strategy performance metrics including Sharpe ratio, annual returns,
    maximum drawdown, and final portfolio value.

    The test loads data, configures the cerebro engine with the strategy,
    sets initial cash to 100,000, applies a 0.1% commission, and runs the
    backtest with Sharpe Ratio, Returns, and DrawDown analyzers.

    Raises:
        AssertionError: If any of the performance metrics don't match expected values.
            - bar_num must equal 1235
            - final_value must equal 100018.36 (within 0.01 tolerance)
            - sharpe_ratio must equal 0.1430114511805932 (within 1e-6 tolerance)
            - annual_return must equal 3.681229236697967e-05 (within 1e-6 tolerance)
            - max_drawdown must equal 0.08411419340257008 (within 1e-6 tolerance)
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
    cerebro.addstrategy(ChandelierExitStrategy)
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
    print("Chandelier Exit Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assertions - using precise assertions
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1235, f"Expected bar_num=1235, got {strat.bar_num}"
    assert abs(final_value - 100018.36) < 0.01, f"Expected final_value=100018.36, got {final_value}"
    assert abs(sharpe_ratio - (0.1430114511805932)) < 1e-6, f"Expected sharpe_ratio=0.1430114511805932, got {sharpe_ratio}"
    assert abs(annual_return - (3.681229236697967e-05)) < 1e-6, f"Expected annual_return=3.681229236697967e-05, got {annual_return}"
    assert abs(max_drawdown - 0.08411419340257008) < 1e-6, f"Expected max_drawdown=0.08411419340257008, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Chandelier Exit Strategy Test")
    print("=" * 60)
    test_chandelier_exit_strategy()
