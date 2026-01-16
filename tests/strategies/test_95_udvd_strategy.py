#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""UDVD (Upper/Lower Shadow Difference) Strategy Test Module.

This module implements and tests the UDVD strategy, which uses the relationship
between price closing and opening prices to determine trend direction. The strategy
identifies bullish and bearish market conditions based on candlestick patterns.

Reference: Time_Series_Backtesting/Effective Strategy Library/UDVD Strategy 1.0.py

The core concept is that sustained bullish pressure (positive candle body momentum)
indicates an uptrend, while bearish pressure indicates a downtrend.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching multiple common locations.

    This function searches for data files in several standard locations relative
    to the test directory, making tests more portable across different environments.

    Args:
        filename: Name of the data file to locate (e.g., 'orcl-1995-2014.txt').

    Returns:
        Path: Absolute path to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the search paths.
            The error message includes the filename that was not found.

    Search Order:
        1. Current test directory: tests/strategies/{filename}
        2. Parent tests directory: tests/{filename}
        3. Test datas directory: tests/strategies/datas/{filename}
        4. Parent datas directory: tests/datas/{filename}
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


class UdvdStrategy(bt.Strategy):
    """UDVD (Upper/Lower Shadow Difference) Trading Strategy.

    A simplified trend-following strategy that uses candlestick body momentum
    to determine market direction. The strategy calculates the Simple Moving
    Average (SMA) of the candle body (close - open) to smooth out price noise
    and identify the underlying trend.

    Trading Logic:
        - When SMA of candle body is positive: Enter long position (bullish trend)
        - When SMA of candle body becomes negative or zero: Exit long position

    The strategy assumes that sustained positive candle body pressure indicates
    institutional buying and an uptrend, while negative pressure indicates
    distribution and a downtrend.

    Attributes:
        order: Current pending order object, or None if no order is pending.
        bar_num: Counter tracking the number of bars processed during the backtest.
        buy_count: Total number of buy orders executed during the backtest.
        sell_count: Total number of sell orders executed during the backtest.
        candle_body: Indicator calculating close price minus open price for each bar.
        signal: Simple Moving Average of candle_body over the specified period.

    Args:
        stake: Number of shares/contracts to trade per order. Defaults to 10.
        period: Period for the SMA calculation used to smooth the candle body signal.
            A longer period provides smoother signals but slower reaction to trend changes.
            Defaults to 3.
    """
    params = dict(
        stake=10,
        period=3,
    )

    def __init__(self):
        """Initialize the UDVD strategy indicators and state variables.

        Creates the candle body indicator (close - open) and applies a Simple
        Moving Average (SMA) to smooth the signal. Also initializes tracking
        variables for order management and performance statistics.
        """
        # Calculate bullish/bearish candle signal
        self.candle_body = self.data.close - self.data.open
        self.signal = bt.indicators.SMA(self.candle_body, period=self.p.period)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track execution statistics.

        Called by the backtrader engine when an order's status changes.
        Updates buy/sell counters when orders are executed and clears
        the pending order reference.

        Args:
            order: The order object that has been updated. Contains status,
                execution price, size, and other order-related information.

        Order Status Handling:
            - Submitted/Accepted: No action taken, order still pending.
            - Completed: Increment buy_count or sell_count based on order type.
            - Other statuses: Clear the pending order reference.
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
        """Execute the main trading logic for each bar.

        This method is called by the backtrader engine for each new bar.
        It implements the core UDVD strategy logic: enter long when the
        smoothed candle body signal is positive, exit when it becomes negative.

        The method also ensures only one order is active at a time by
        checking self.order before placing new orders.
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Signal is positive (overall bullish)
            if self.signal[0] > 0:
                self.order = self.buy(size=self.p.stake)
        else:
            # Signal is negative
            if self.signal[0] <= 0:
                self.order = self.close()


def test_udvd_strategy():
    """Test the UDVD strategy with historical data.

    Runs a backtest of the UDVD strategy using Oracle Corporation (ORCL)
    historical stock data from 2010-2014. The test validates that the strategy
    produces expected performance metrics, ensuring the implementation matches
    the reference behavior.

    The test uses the following configuration:
        - Initial capital: $100,000
        - Commission: 0.1% per trade
        - Position size: 10 shares per trade
        - SMA period: 3 bars

    Performance Metrics Validated:
        - Bar count: Number of trading days processed
        - Final portfolio value: End-of-period account value
        - Sharpe ratio: Risk-adjusted return measure
        - Annual return: Normalized annual return
        - Maximum drawdown: Largest peak-to-trough decline

    Raises:
        AssertionError: If any of the performance metrics do not match expected
            values within specified tolerances. Final value tolerance is 0.01,
            other metrics use tolerance of 1e-6 or tighter.

    Expected Values:
        - bar_num: 1255 trading days
        - final_value: approximately $99,939.44
        - sharpe_ratio: -0.21533281426868578
        - annual_return: -0.0001214372697148802
        - max_drawdown: 0.20019346669376056 (20.02%)
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
    cerebro.addstrategy(UdvdStrategy)
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
    print("UDVD Upper/Lower Shadow Difference Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1255, f"Expected bar_num=1255, got {strat.bar_num}"
    assert abs(final_value - 99939.44) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (-0.21533281426868578)) < 1e-6, f"Expected sharpe_ratio=-0.21533281426868578, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0001214372697148802)) < 1e-12, f"Expected annual_return=-0.0001214372697148802, got {annual_return}"
    assert abs(max_drawdown - 0.20019346669376056) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("UDVD Upper/Lower Shadow Difference Strategy Test")
    print("=" * 60)
    test_udvd_strategy()
