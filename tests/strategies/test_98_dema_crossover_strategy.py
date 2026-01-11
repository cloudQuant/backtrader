#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for DEMA Crossover Strategy.

This module tests a Double Exponential Moving Average (DEMA) crossover strategy
that uses fast and slow DEMA lines to generate trading signals. The strategy
enters long positions when the fast DEMA crosses above the slow DEMA (golden cross)
and exits when the fast DEMA crosses below the slow DEMA (death cross).

Reference: backtrader-strategies-compendium/strategies/dema.py

Example:
    To run the test directly::

        python -m tests.strategies.test_98_dema_crossover_strategy

    Or use pytest::

        pytest tests/strategies/test_98_dema_crossover_strategy.py -v
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching common locations.

    This function searches for a data file in several predefined locations
    relative to the current test directory, making it easier to run tests
    from different working directories.

    Args:
        filename (str): The name of the data file to locate.

    Returns:
        Path: The absolute path to the first matching data file found.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths. The error message includes the filename that was
            not found.

    Search Paths:
        The function searches in the following order:
        1. BASE_DIR / filename
        2. BASE_DIR.parent / filename
        3. BASE_DIR / "datas" / filename
        4. BASE_DIR.parent / "datas" / filename
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


class DemaCrossoverStrategy(bt.Strategy):
    """DEMA Crossover Double Exponential Moving Average Strategy.

    This strategy implements a trend-following approach using two DEMA indicators
    with different periods. It generates buy signals when the fast DEMA crosses
    above the slow DEMA (golden cross) and sell signals when the fast DEMA crosses
    below the slow DEMA (death cross).

    Entry conditions:
        - Long: Fast DEMA crosses above Slow DEMA (crossover > 0)

    Exit conditions:
        - Close Position: Fast DEMA crosses below Slow DEMA (crossover < 0)

    Attributes:
        dema_fast (bt.indicators.DEMA): Fast DEMA indicator with short period.
        dema_slow (bt.indicators.DEMA): Slow DEMA indicator with long period.
        crossover (bt.indicators.CrossOver): Crossover indicator tracking the
            relationship between fast and slow DEMA. Positive values indicate
            fast DEMA is above slow DEMA, negative values indicate below.
        order (bt.Order): Current pending order, or None if no order is pending.
        bar_num (int): Counter tracking the number of bars processed.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.
    """
    params = dict(
        stake=10,
        fast_period=5,
        slow_period=21,
    )

    def __init__(self):
        """Initialize the DEMA Crossover Strategy.

        Sets up the DEMA indicators, crossover signal, and tracking variables.
        The fast DEMA reacts quickly to price changes while the slow DEMA
        provides a smoother trend line.
        """
        self.dema_fast = bt.indicators.DEMA(self.data, period=self.p.fast_period)
        self.dema_slow = bt.indicators.DEMA(self.data, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.dema_fast, self.dema_slow)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Called by the backtrader engine when an order changes status. This method
        tracks completed orders by incrementing buy/sell counters and resets the
        pending order reference when the order is complete.

        Args:
            order (bt.Order): The order object with updated status.
                Status can be Submitted, Accepted, Completed, Canceled, Expired, or Margin.

        Note:
            Submitted and Accepted orders are ignored as they are still pending.
            Only Completed orders trigger buy/sell counter updates.
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
        It implements the core strategy logic:

        1. Increments the bar counter
        2. Skips trading if an order is already pending
        3. If no position exists, enters long when golden cross occurs
        4. If position exists, exits when death cross occurs

        The strategy only takes long positions and uses close orders to exit.
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # DEMA golden cross - fast DEMA crosses above slow DEMA
            if self.crossover[0] > 0:
                self.order = self.buy(size=self.p.stake)
        else:
            # DEMA death cross - fast DEMA crosses below slow DEMA
            if self.crossover[0] < 0:
                self.order = self.close()


def test_dema_crossover_strategy():
    """Test the DEMA Crossover Strategy with historical data.

    This function sets up and runs a backtest of the DemaCrossoverStrategy using
    Oracle (ORCL) historical stock data from 2010-2014. It validates the strategy
    performance against expected values for key metrics.

    The test configuration:
        - Initial capital: $100,000
        - Commission: 0.1% per trade
        - Fast DEMA period: 5 bars
        - Slow DEMA period: 21 bars
        - Position size: 10 shares per trade
        - Date range: 2010-01-01 to 2014-12-31

    Expected results:
        - Bars processed: 1216
        - Final portfolio value: $100,010.66
        - Sharpe ratio: 0.0838 (risk-free rate: 0%)
        - Annual return: ~0.0021%
        - Maximum drawdown: 9.48%

    Raises:
        AssertionError: If any of the performance metrics do not match expected
            values within specified tolerance levels.
        FileNotFoundError: If the data file 'orcl-1995-2014.txt' cannot be
            located in any of the search paths.

    Note:
        Final value tolerance is 0.01 (1 cent), while other metrics use a
        tolerance of 1e-6 for floating-point comparison.
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
    cerebro.addstrategy(DemaCrossoverStrategy)
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
    print("DEMA Crossover Double Exponential Moving Average Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1216, f"Expected bar_num=1216, got {strat.bar_num}"
    assert abs(final_value - 100010.66) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (0.08380775797931977)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (2.1377028602817796e-05)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.09484526475149473) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("DEMA Crossover Double Exponential Moving Average Strategy Test")
    print("=" * 60)
    test_dema_crossover_strategy()
