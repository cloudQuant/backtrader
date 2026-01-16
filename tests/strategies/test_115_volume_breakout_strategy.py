#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case for Volume Breakout Strategy.

This module implements and tests a volume breakout trading strategy that uses
volume spikes combined with RSI indicators for entry and exit signals. The
strategy enters long positions when volume exceeds a moving average threshold
and exits when RSI becomes overbought or a maximum holding period is reached.

Reference: backtrader_NUPL_strategy/hope/Hope_vol.py

The test validates strategy performance using Oracle (ORCL) historical data
from 2010-2014, checking that the strategy produces consistent results with
expected performance metrics including Sharpe ratio, annual returns, and
maximum drawdown.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the absolute path of a data file by searching common directories.

    This function searches for a data file in multiple common locations relative
    to the test directory, including the current directory, parent directory,
    and 'datas' subdirectories. This allows tests to find data files regardless
    of how the test suite is executed.

    Args:
        filename: The name of the data file to locate.

    Returns:
        Path: The absolute path to the first found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched directories.

    Examples:
        >>> path = resolve_data_path("orcl-1995-2014.txt")
        >>> print(path)
        /path/to/tests/datas/orcl-1995-2014.txt
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


class VolumeBreakoutStrategy(bt.Strategy):
    """A momentum-based trading strategy using volume breakout signals.

    This strategy identifies potential breakouts by monitoring volume spikes
    relative to a moving average. When volume exceeds the threshold, it enters
    a long position expecting continued momentum. Exit signals are based on
    RSI overbought conditions or a maximum holding period.

    Entry Logic:
        - Long entry: Current volume > N-day volume SMA * multiplier
        - This identifies unusual trading activity that may precede price moves

    Exit Logic:
        - RSI exit: RSI > threshold (default 70) indicating overbought conditions
        - Time exit: Position held for more than 5 bars

    Attributes:
        vol_ma: Simple moving average of volume for the specified period.
        rsi: Relative Strength Index indicator for exit signals.
        order: Current pending order object (None if no pending order).
        bar_num: Total number of bars processed during the backtest.
        bar_executed: Bar number when the last order was executed.
        buy_count: Total number of buy orders executed during the backtest.
        sell_count: Total number of sell orders executed during the backtest.

    Parameters:
        stake: Number of shares/contracts per trade (default: 10).
        vol_period: Period for volume moving average (default: 20).
        vol_mult: Volume multiplier for breakout signal (default: 1.05).
        rsi_period: Period for RSI calculation (default: 14).
        rsi_exit: RSI threshold for exit signal (default: 70).
    """
    params = dict(
        stake=10,
        vol_period=20,
        vol_mult=1.05,
        rsi_period=14,
        rsi_exit=70,
    )

    def __init__(self):
        """Initialize the VolumeBreakoutStrategy with indicators and tracking variables.

        Sets up the technical indicators (volume SMA and RSI) and initializes
        variables for tracking orders and trade statistics. Indicators are
        automatically registered with the strategy by backtrader.
        """
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=self.p.vol_period)
        self.rsi = bt.indicators.RSI(self.data, period=self.p.rsi_period)

        self.order = None
        self.bar_num = 0
        self.bar_executed = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates from the broker.

        This method is called by backtrader whenever an order's status changes.
        It tracks completed orders to maintain buy/sell statistics and clears
        the pending order reference when the order is complete or cancelled.

        Args:
            order: The order object containing status and execution details.
                Status can be Submitted, Accepted, Completed, or Cancelled.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.bar_executed = len(self)
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        """Execute the main trading logic for each bar.

        This method is called by backtrader for every new bar of data. It implements
        the core trading logic:

        1. Increments the bar counter
        2. Checks if there's a pending order (no action if pending)
        3. If not in position: checks for volume breakout signal to enter long
        4. If in position: checks for exit conditions (RSI overbought or time exit)

        The strategy only takes long positions and enters when volume spikes above
        the moving average threshold, expecting continued momentum.
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Volume breakout condition for entry
            if self.data.volume[0] > self.vol_ma[0] * self.p.vol_mult:
                self.order = self.buy(size=self.p.stake)
        else:
            # Exit conditions: RSI overbought or maximum holding period reached
            if self.rsi[0] > self.p.rsi_exit or len(self) > self.bar_executed + 5:
                self.order = self.close()


def test_volume_breakout_strategy():
    """Test the Volume Breakout strategy with historical data.

    This test validates that the VolumeBreakoutStrategy produces consistent
    and expected results when run on Oracle (ORCL) historical stock data.
    The test performs the following steps:

    1. Loads Oracle stock data from 2010-2014 from a CSV file
    2. Configures a Cerebro backtesting engine with the strategy
    3. Sets initial capital to $100,000 and commission to 0.1%
    4. Adds performance analyzers (Sharpe Ratio, Returns, Drawdown)
    5. Runs the backtest and extracts performance metrics
    6. Validates metrics against expected values with precise tolerances

    The test ensures that changes to the backtrader framework do not
    inadvertently break existing strategy behavior.

    Raises:
        AssertionError: If any performance metric deviates from expected values.
            Tolerances: 0.01 for final_value, 1e-6 for other metrics.

    Note:
        Expected values are based on the reference implementation and
        may need adjustment if the strategy logic or data source changes.
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
    cerebro.addstrategy(VolumeBreakoutStrategy)
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
    print("Volume Breakout Strategy Backtest Results:")
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
    assert strat.bar_num == 1238, f"Expected bar_num=1238, got {strat.bar_num}"
    assert abs(final_value - 99987.80) < 0.01, f"Expected final_value=99987.80, got {final_value}"
    assert abs(sharpe_ratio - (-0.1545232366102227)) < 1e-6, f"Expected sharpe_ratio=-0.1545232366102227, got {sharpe_ratio}"
    assert abs(annual_return - (-2.4463477104822622e-05)) < 1e-6, f"Expected annual_return=-2.4463477104822622e-05, got {annual_return}"
    assert abs(max_drawdown - 0.05240649826015478) < 1e-6, f"Expected max_drawdown=0.05240649826015478, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Volume Breakout Strategy Test")
    print("=" * 60)
    test_volume_breakout_strategy()
