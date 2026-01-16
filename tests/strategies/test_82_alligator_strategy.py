#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Alligator Strategy

Reference: https://github.com/Backtesting/strategies
Bill Williams Alligator indicator strategy
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching in common directories.

    This function searches for a data file in several possible locations
    relative to the current script's directory. It checks the script's
    directory, parent directory, and 'datas' subdirectories.

    Args:
        filename: The name of the data file to locate.

    Returns:
        Path: The absolute path to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of
            the search paths.

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


class AlligatorIndicator(bt.Indicator):
    """Alligator Indicator - Bill Williams.

    The Alligator indicator consists of three smoothed moving averages:
    - Jaw (blue line): 13-period SMMA, shifted forward 8 bars
    - Teeth (red line): 8-period SMMA, shifted forward 5 bars
    - Lips (green line): 5-period SMMA, shifted forward 3 bars

    The indicator is used to identify trending periods and potential
    entry/exit points. When the three lines are intertwined, the market
    is ranging. When they separate, a trend is emerging.

    Attributes:
        jaw: The jaw line (13-period SMMA)
        teeth: The teeth line (8-period SMMA)
        lips: The lips line (5-period SMMA)

    Args:
        jaw_period: Period for the jaw line calculation (default: 13).
        teeth_period: Period for the teeth line calculation (default: 8).
        lips_period: Period for the lips line calculation (default: 5).
    """
    lines = ('jaw', 'teeth', 'lips')
    params = dict(
        jaw_period=13,
        teeth_period=8,
        lips_period=5,
    )

    def __init__(self):
        """Initialize the Alligator indicator.

        Creates three Smoothed Moving Average (SMMA) lines for the jaw,
        teeth, and lips. The SMMA is equivalent to an EMA with alpha = 1/period.
        """
        self.lines.jaw = bt.indicators.SmoothedMovingAverage(
            self.data.close, period=self.p.jaw_period
        )
        self.lines.teeth = bt.indicators.SmoothedMovingAverage(
            self.data.close, period=self.p.teeth_period
        )
        self.lines.lips = bt.indicators.SmoothedMovingAverage(
            self.data.close, period=self.p.lips_period
        )


class AlligatorStrategy(bt.Strategy):
    """Alligator trading strategy.

    This strategy implements a simple Alligator-based trading approach:
    - Buy when price breaks above the jaw line
    - Sell when price breaks below the jaw line

    The jaw line acts as a trend filter - when price is above it, the
    trend is considered bullish, and when below, bearish.

    Attributes:
        dataclose: Reference to close prices
        alligator: Alligator indicator instance
        order: Current pending order
        bar_num: Number of bars processed
        buy_count: Number of buy orders executed
        sell_count: Number of sell orders executed

    Args:
        stake: Number of shares to trade per order (default: 10).
        jaw_period: Period for the Alligator jaw line (default: 13).
        teeth_period: Period for the Alligator teeth line (default: 8).
        lips_period: Period for the Alligator lips line (default: 5).
    """
    params = dict(
        stake=10,
        jaw_period=13,
        teeth_period=8,
        lips_period=5,
    )

    def __init__(self):
        """Initialize the Alligator strategy.

        Sets up the data reference, creates the Alligator indicator,
        and initializes tracking variables for orders and bar counts.
        """
        self.dataclose = self.datas[0].close
        self.alligator = AlligatorIndicator(
            self.datas[0],
            jaw_period=self.p.jaw_period,
            teeth_period=self.p.teeth_period,
            lips_period=self.p.lips_period
        )
        self.order = None

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status notifications.

        Updates buy/sell counters when orders are completed and clears
        the pending order reference.

        Args:
            order: The order object with status information.
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

        This method is called on each bar of data. It implements the
        Alligator-based trading logic:
        - Buy signal: Price closes above the jaw line (no position)
        - Sell signal: Price closes below the jaw line (holding position)

        Only one order is allowed at a time. If an order is pending,
        no new orders are placed.
        """
        self.bar_num += 1
        if self.order:
            return

        # Buy when price is above the jaw line
        if not self.position:
            if self.dataclose[0] > self.alligator.jaw[0]:
                self.order = self.buy(size=self.p.stake)
        else:
            # Sell when price breaks below the jaw line
            if self.dataclose[0] < self.alligator.jaw[0]:
                self.order = self.sell(size=self.p.stake)


def test_alligator_strategy():
    """Test the Alligator strategy.

    This function sets up and runs a backtest of the Alligator strategy
    using historical Oracle stock data from 2010-2014. It validates
    the strategy performance against expected values.

    The test uses:
    - Oracle stock data (2010-2014)
    - Initial cash: $100,000
    - Commission: 0.1%
    - Position size: 10 shares per trade

    Raises:
        AssertionError: If any of the performance metrics don't match
            expected values within specified tolerance.
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
    cerebro.addstrategy(AlligatorStrategy)
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
    print("Alligator Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1245, f"Expected bar_num=1245, got {strat.bar_num}"
    assert abs(final_value - 100011.2) < 0.01, f"Expected final_value=100011.2, got {final_value}"
    assert abs(sharpe_ratio - (0.04724483526577409)) < 1e-6, f"Expected sharpe_ratio=0.04724483526577409, got {sharpe_ratio}"
    assert abs(annual_return - (2.2461836991998968e-05)) < 1e-6, f"Expected annual_return=2.2461836991998968e-05, got {annual_return}"
    assert abs(max_drawdown - 0.1353106121383434) < 1e-6, f"Expected max_drawdown=0.1353106121383434, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Alligator Strategy Test")
    print("=" * 60)
    test_alligator_strategy()
