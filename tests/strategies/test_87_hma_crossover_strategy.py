#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: HMA Crossover Hull Moving Average Strategy

This module tests a trading strategy based on Hull Moving Average (HMA) crossovers.
The strategy uses fast and slow HMAs to generate entry and exit signals.

Reference: https://github.com/Backtrader1.0/strategies/hma_crossover.py

Strategy Logic:
    - Long Entry: Fast HMA crosses above slow HMA
    - Short Entry: Fast HMA crosses below slow HMA
    - Long Exit: Fast HMA falls below slow HMA
    - Short Exit: Fast HMA rises above slow HMA

The strategy also uses Average True Range (ATR) as a volatility reference
indicator, though it is not directly used in the trading logic.

Test Data:
    - Uses Oracle Corporation (ORCL) historical data from 2010-2014
    - Initial capital: $100,000
    - Commission: 0.1% per trade
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching common locations.

    This function searches for a data file in several possible directories
    relative to the current test file location. It checks the current directory,
    parent directory, and 'datas' subdirectories in both locations.

    Args:
        filename (str): The name of the data file to locate.

    Returns:
        Path: The absolute path to the first matching file found.

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


class HmaCrossoverStrategy(bt.Strategy):
    """HMA Crossover Hull Moving Average Strategy.

    This strategy implements a dual moving average crossover system using
    Hull Moving Averages (HMA), which are known for reducing lag compared
    to traditional moving averages.

    Trading Logic:
        Long Entry:
            - Fast HMA crosses above slow HMA (bullish signal)
        Short Entry:
            - Fast HMA crosses below slow HMA (bearish signal)
        Long Exit:
            - Fast HMA falls below slow HMA
        Short Exit:
            - Fast HMA rises above slow HMA

    The strategy also calculates Average True Range (ATR) as a reference
    for market volatility, though it is not directly used in position sizing
    or stop-loss logic in this implementation.

    Attributes:
        dataclose: Reference to the close price of the primary data feed.
        hma_fast: Fast Hull Moving Average indicator.
        hma_slow: Slow Hull Moving Average indicator.
        atr: Average True Range indicator for volatility measurement.
        order: Reference to the current pending order.
        prev_rel: Boolean indicating if fast HMA was above slow HMA on
            the previous bar.
        bar_num: Counter for the number of bars processed.
        buy_count: Counter for the number of buy orders executed.
        sell_count: Counter for the number of sell orders executed.

    Parameters:
        stake (int): Number of shares/contracts per trade. Default is 10.
        hma_fast (int): Period for the fast HMA. Default is 60.
        hma_slow (int): Period for the slow HMA. Default is 90.
        atr_period (int): Period for the ATR indicator. Default is 14.
    """
    params = dict(
        stake=10,
        hma_fast=60,
        hma_slow=90,
        atr_period=14,
    )

    def __init__(self):
        """Initialize the HMA Crossover strategy.

        Sets up the indicators and tracking variables for the strategy.
        Initializes fast and slow Hull Moving Averages, ATR indicator,
        and counters for tracking trades and bars.
        """
        self.dataclose = self.datas[0].close

        # Hull Moving Average indicators
        self.hma_fast = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.hma_fast
        )
        self.hma_slow = bt.indicators.HullMovingAverage(
            self.data.close, period=self.p.hma_slow
        )

        # ATR indicator
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)

        self.order = None
        self.prev_rel = None  # fast > slow on previous bar

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        This method is called by the backtrader engine when an order's
        status changes. It tracks completed orders by incrementing the
        buy_count or sell_count counters and clears the pending order
        reference when the order is no longer active.

        Args:
            order (bt.Order): The order object with updated status.

        Order Status Handling:
            - Submitted/Accepted: Order is pending, no action needed.
            - Completed: Order was filled, increment the appropriate counter.
            - Other statuses: Clear the order reference to allow new trades.
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
        It implements the core crossover logic to generate entry and exit signals.

        The strategy:
        1. Checks if there's a pending order (if so, waits)
        2. Compares fast and slow HMA values to detect crossovers
        3. Enters long when fast HMA crosses above slow HMA
        4. Enters short when fast HMA crosses below slow HMA
        5. Exits positions when the crossover reverses

        Note:
            The crossover is detected by comparing the current relationship
            (rel_now) with the previous bar's relationship (prev_rel). A
            crossover occurs when these values differ.
        """
        self.bar_num += 1

        if self.order:
            return

        f0, s0 = float(self.hma_fast[0]), float(self.hma_slow[0])
        rel_now = f0 > s0

        if self.prev_rel is None:
            self.prev_rel = rel_now
            return

        pos_sz = self.position.size

        # Long entry: fast line crosses above slow line from below
        if pos_sz == 0 and (not self.prev_rel) and rel_now:
            self.order = self.buy(size=self.p.stake)

        # Short entry: fast line crosses below slow line from above
        elif pos_sz == 0 and self.prev_rel and (not rel_now):
            self.order = self.sell(size=self.p.stake)

        # Long exit: fast line falls below slow line
        elif pos_sz > 0 and not rel_now:
            self.order = self.close()

        # Short exit: fast line rises above slow line
        elif pos_sz < 0 and rel_now:
            self.order = self.close()

        self.prev_rel = rel_now


def test_hma_crossover_strategy():
    """Test the HMA Crossover strategy with historical data.

    This function runs a backtest of the HMA Crossover strategy using
    Oracle Corporation (ORCL) historical price data from 2010-2014.
    It validates the strategy's performance against expected results.

    Test Configuration:
        - Data: ORCL daily prices from 2010-01-01 to 2014-12-31
        - Initial Capital: $100,000
        - Commission: 0.1% per trade
        - Strategy Parameters: Default (stake=10, hma_fast=60, hma_slow=90)

    Expected Results:
        - Bars processed: 1160
        - Final portfolio value: $100,081.45
        - Sharpe Ratio: 0.5100011168586044
        - Annual Return: 0.00016323774473640581
        - Maximum Drawdown: 10.33%

    Analyzers:
        - SharpeRatio: Risk-adjusted return metric
        - Returns: Annualized normalized return
        - DrawDown: Maximum peak-to-trough decline

    Raises:
        AssertionError: If any of the performance metrics do not match
            expected values within specified tolerances.
        FileNotFoundError: If the required data file cannot be located.
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
    cerebro.addstrategy(HmaCrossoverStrategy)
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
    print("HMA Crossover Hull Moving Average Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1160, f"Expected bar_num=1160, got {strat.bar_num}"
    assert abs(final_value - 100081.45) < 0.01, f"Expected final_value=100081.45, got {final_value}"
    assert abs(sharpe_ratio - (0.5100011168586044)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.00016323774473640581)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.10334345093914488) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("HMA Crossover Hull Moving Average Strategy Test")
    print("=" * 60)
    test_hma_crossover_strategy()
