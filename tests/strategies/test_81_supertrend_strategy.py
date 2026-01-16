#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for SuperTrend Strategy backtesting.

This module implements and tests the SuperTrend strategy, a trend-following
trading approach that uses the Average True Range (ATR) indicator to identify
trend direction and generate buy/sell signals.

The SuperTrend indicator consists of two lines:
1. SuperTrend line: A dynamic support/resistance level
2. Direction line: Indicates uptrend (1) or downtrend (-1)

Reference: https://github.com/Backtesting/strategies

Example:
    To run the test:
        python tests/strategies/test_81_supertrend_strategy.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the full path to a data file by searching multiple locations.

    This function searches for a data file in several common locations relative
    to the current test directory, including the current directory, parent
    directory, and 'datas' subdirectories.

    Args:
        filename: Name of the data file to locate (e.g., 'orcl-1995-2014.txt').

    Returns:
        Path: The absolute path to the first matching data file found.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched locations.

    Example:
        >>> path = resolve_data_path('orcl-1995-2014.txt')
        >>> print(path)
        /path/to/backtrader/tests/datas/orcl-1995-2014.txt
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


class SuperTrendIndicator(bt.Indicator):
    """SuperTrend Indicator.

    A trend-following indicator that uses Average True Range (ATR) to
    identify the direction of the trend and potential entry/exit points.
    The indicator consists of two lines:
    - supertrend: The dynamic support/resistance level
    - direction: Trend direction (1 for uptrend, -1 for downtrend)

    Attributes:
        lines: Tuple containing 'supertrend' and 'direction' line names.
        params: Dictionary with 'period' (ATR period) and 'multiplier'
            (ATR multiplier for band width) parameters.

    Example:
        >>> indicator = SuperTrendIndicator(data, period=10, multiplier=3.0)
        >>> print(indicator.supertrend[0])  # Current SuperTrend value
        >>> print(indicator.direction[0])   # Current trend direction
    """
    lines = ('supertrend', 'direction')
    params = dict(
        period=10,
        multiplier=3.0,
    )

    def __init__(self):
        """Initialize the SuperTrend indicator.

        Sets up the ATR indicator and calculates the middle price (HL2)
        which is the average of high and low prices. These values are
        used in the next() method to calculate the SuperTrend bands.
        """
        self.atr = bt.indicators.ATR(self.data, period=self.p.period)
        self.hl2 = (self.data.high + self.data.low) / 2.0

    def next(self):
        """Calculate the SuperTrend indicator values for the current bar.

        This method implements the SuperTrend algorithm:
        1. Calculate upper and lower bands using ATR
        2. Determine trend direction based on previous values
        3. Update SuperTrend line based on price action and band values

        The algorithm:
        - In uptrend: SuperTrend is max(lower_band, previous_SuperTrend)
        - In downtrend: SuperTrend is min(upper_band, previous_SuperTrend)
        - Trend flips when price crosses the SuperTrend line

        Note:
            During the initialization period (before period+1 bars), the
            indicator uses HL2 as the SuperTrend value and direction=1.
        """
        if len(self) < self.p.period + 1:
            self.lines.supertrend[0] = self.hl2[0]
            self.lines.direction[0] = 1
            return
            
        atr = self.atr[0]
        hl2 = self.hl2[0]
        
        upper_band = hl2 + self.p.multiplier * atr
        lower_band = hl2 - self.p.multiplier * atr
        
        prev_supertrend = self.lines.supertrend[-1]
        prev_direction = self.lines.direction[-1]
        
        # Uptrend
        if prev_direction == 1:
            if self.data.close[0] < prev_supertrend:
                self.lines.supertrend[0] = upper_band
                self.lines.direction[0] = -1
            else:
                self.lines.supertrend[0] = max(lower_band, prev_supertrend)
                self.lines.direction[0] = 1
        # Downtrend
        else:
            if self.data.close[0] > prev_supertrend:
                self.lines.supertrend[0] = lower_band
                self.lines.direction[0] = 1
            else:
                self.lines.supertrend[0] = min(upper_band, prev_supertrend)
                self.lines.direction[0] = -1


class SuperTrendStrategy(bt.Strategy):
    """SuperTrend Strategy.

    A trend-following strategy that generates buy and sell signals based
    on the SuperTrend indicator. The strategy goes long when the trend
    turns positive and exits when the trend turns negative.

    Attributes:
        params: Dictionary containing:
            - stake: Number of shares to trade per order (default: 10)
            - period: ATR period for SuperTrend calculation (default: 10)
            - multiplier: ATR multiplier for SuperTrend bands (default: 3.0)
        dataclose: Reference to the close price of the data feed.
        supertrend: SuperTrendIndicator instance.
        order: Current pending order (None if no pending order).
        bar_num: Counter for the number of bars processed.
        buy_count: Counter for total buy orders executed.
        sell_count: Counter for total sell orders executed.

    Trading Rules:
        - Buy when trend turns up (direction changes from -1 to 1)
        - Sell when trend turns down (direction changes from 1 to -1)

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(SuperTrendStrategy, stake=10, period=10, multiplier=3.0)
        >>> results = cerebro.run()
    """
    params = dict(
        stake=10,
        period=10,
        multiplier=3.0,
    )

    def __init__(self):
        """Initialize the SuperTrend strategy.

        Sets up the data reference, creates the SuperTrend indicator,
        and initializes tracking variables for orders and statistics.
        """
        self.dataclose = self.datas[0].close
        self.supertrend = SuperTrendIndicator(
            self.datas[0],
            period=self.p.period,
            multiplier=self.p.multiplier
        )
        self.order = None

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Called by the backtrader engine when an order's status changes.
        Updates buy/sell counters when orders are completed and clears
        the pending order reference.

        Args:
            order: The Order object with updated status.
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

        This method is called by the backtrader engine for each new bar.
        It implements the following trading logic:
        1. Increment bar counter
        2. Skip if there's a pending order
        3. Generate buy orders when trend turns from down to up
        4. Generate sell orders when in position and trend turns down

        Note:
            Only one position is allowed at a time. The strategy will
            enter long when the SuperTrend direction changes from -1 to 1,
            and exit when the direction changes to -1.
        """
        self.bar_num += 1
        if self.order:
            return

        # Buy when trend turns up
        if not self.position:
            if self.supertrend.direction[0] == 1 and self.supertrend.direction[-1] == -1:
                self.order = self.buy(size=self.p.stake)
        else:
            # Sell when trend turns down
            if self.supertrend.direction[0] == -1:
                self.order = self.sell(size=self.p.stake)


def test_supertrend_strategy():
    """Test the SuperTrend strategy backtest.

    This function sets up a backtest using the SuperTrend strategy with
    Oracle stock data from 2010-2014. It verifies the strategy performance
    metrics match expected values.

    Raises:
        AssertionError: If any of the expected values do not match within
            the specified tolerance.
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
    cerebro.addstrategy(SuperTrendStrategy)
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
    print("SuperTrend Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num == 1247, f"Expected bar_num=1247, got {strat.bar_num}"
    assert abs(final_value - 99999.23) < 0.01, f"Expected final_value=99999.23, got {final_value}"
    assert abs(sharpe_ratio - (-0.003753826957851812)) < 1e-6, f"Expected sharpe_ratio=-0.003753826957851812, got {sharpe_ratio}"
    assert abs(annual_return - (-1.5389488753206686e-06)) < 1e-6, f"Expected annual_return=-1.5389488753206686e-06, got {annual_return}"
    assert abs(max_drawdown - 0.11218870744432227) < 1e-6, f"Expected max_drawdown=0.11218870744432227, got {max_drawdown}"

    print("\nAll tests passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("SuperTrend Strategy Test")
    print("=" * 60)
    test_supertrend_strategy()
