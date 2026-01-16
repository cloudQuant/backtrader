#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case: Price Channel strategy.

This module tests the Price Channel strategy implementation, which uses
price channel breakouts to determine trend direction and generate trading
signals. The strategy goes long when price creates an N-day high and exits
when price falls below an M-day low.

The test uses historical Oracle Corporation (ORCL) stock data from 2010-2014
to validate the strategy's performance metrics including Sharpe ratio,
annual return, and maximum drawdown.
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
    to the test file directory, including the current directory, parent directory,
    and 'datas' subdirectories.

    Args:
        filename: The name of the data file to locate.

    Returns:
        Path: The resolved path to the data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched locations.

    Example:
        >>> path = resolve_data_path("orcl-1995-2014.txt")
        >>> print(path)
        /path/to/tests/strategies/datas/orcl-1995-2014.txt
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


class PriceChannelStrategy(bt.Strategy):
    """Price Channel breakout trading strategy.

    This strategy implements a trend-following approach based on price channel
    breakouts. It enters long positions when the price breaks above the highest
    high of the specified entry period and exits when the price breaks below
    the lowest low of the exit period.

    Entry conditions:
        - Long: Price creates N-day high (breaks above entry_period highest high)

    Exit conditions:
        - Long: Price falls below M-day low (breaks below exit_period lowest low)

    Attributes:
        params: Dictionary containing strategy parameters:
            - stake (int): Number of shares/contracts per trade (default: 10)
            - entry_period (int): Period for highest high calculation (default: 20)
            - exit_period (int): Period for lowest low calculation (default: 10)

    Note:
        This strategy only implements long positions. Short selling is not
        supported in this implementation.
    """
    params = dict(
        stake=10,
        entry_period=20,
        exit_period=10,
    )

    def __init__(self):
        """Initialize the Price Channel strategy with indicators and state variables.

        Sets up the highest high and lowest low indicators used for signal
        generation, and initializes tracking variables for order management
        and performance statistics.

        Attributes created:
            highest_entry: Indicator tracking the highest high over entry_period.
            lowest_exit: Indicator tracking the lowest low over exit_period.
            order: Reference to the current pending order (None if no pending order).
            bar_num: Counter for the number of bars processed.
            buy_count: Counter for the number of buy orders executed.
            sell_count: Counter for the number of sell orders executed.
        """
        self.highest_entry = bt.indicators.Highest(self.data.high, period=self.p.entry_period)
        self.lowest_exit = bt.indicators.Lowest(self.data.low, period=self.p.exit_period)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track execution statistics.

        Called by the backtrader engine when an order's status changes. Updates
        the buy/sell counters when orders are completed and clears the order
        reference when the order is no longer active.

        Args:
            order: The order object with updated status information.

        Note:
            This method ignores Submitted and Accepted status notifications,
            only processing Completed orders. The order reference is set to
            None after processing to allow new orders to be placed.
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

        This method is called by the backtrader engine for each bar of data.
        It implements the core trading logic:

        1. Increments the bar counter
        2. Checks if there's a pending order (if so, returns early)
        3. If no position: Enters long when price breaks above entry_period high
        4. If has position: Exits when price breaks below exit_period low

        Note:
            The strategy uses [0] for current bar values and [-1] for
            previous bar values when comparing to indicator levels.
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Price creates new high
            if self.data.high[0] >= self.highest_entry[-1]:
                self.order = self.buy(size=self.p.stake)
        else:
            # Price creates new low
            if self.data.low[0] <= self.lowest_exit[-1]:
                self.order = self.close()


def test_price_channel_strategy():
    """Test the Price Channel strategy with historical data.

    This function sets up and runs a backtest of the PriceChannelStrategy
    using Oracle Corporation (ORCL) stock data from 2010-2014. It validates
    the strategy's performance against expected values for various metrics.

    The test:
        - Loads historical price data from a CSV file
        - Configures the strategy with default parameters (stake=10, entry_period=20, exit_period=10)
        - Sets initial cash to 100,000 and commission to 0.1%
        - Adds performance analyzers (Sharpe Ratio, Returns, Drawdown)
        - Runs the backtest and validates results against expected values

    Raises:
        AssertionError: If any of the performance metrics don't match expected
            values within specified tolerances.

    Note:
        Performance assertions use precise tolerances:
        - final_value: 0.01 tolerance
        - Other metrics: 1e-6 tolerance

    Expected values:
        - bar_num: 1238
        - final_value: 100050.36
        - sharpe_ratio: 0.5592202866492985
        - annual_return: 0.00010094130513364865
        - max_drawdown: 0.06631886254244598
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
    cerebro.addstrategy(PriceChannelStrategy)
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
    print("Price Channel strategy backtest results:")
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
    assert abs(final_value - 100050.36) < 0.01, f"Expected final_value=100050.36, got {final_value}"
    assert abs(sharpe_ratio - (0.5592202866492985)) < 1e-6, f"Expected sharpe_ratio=0.5592202866492985, got {sharpe_ratio}"
    assert abs(annual_return - (0.00010094130513364865)) < 1e-6, f"Expected annual_return=0.00010094130513364865, got {annual_return}"
    assert abs(max_drawdown - 0.06631886254244598) < 1e-6, f"Expected max_drawdown=0.06631886254244598, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Price Channel strategy test")
    print("=" * 60)
    test_price_channel_strategy()
