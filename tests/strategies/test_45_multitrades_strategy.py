#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test suite for MultiTrades Strategy.

This module tests the multi-trade ID functionality which allows managing
multiple concurrent trades with different trade IDs.

Reference: backtrader-master2/samples/multitrades/multitrades.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import itertools
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching in common locations.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Absolute path to the data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search locations.
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


class MultiTradesStrategy(bt.Strategy):
    """Strategy using multiple trade IDs to manage concurrent trades.

    This strategy demonstrates the use of trade IDs to manage multiple
    concurrent trades independently. Each trade is tracked separately
    using its unique trade ID.

    Attributes:
        params: Dictionary containing strategy parameters.
            period (int): SMA period for signal generation (default: 15).
            stake (int): Number of shares/contracts per trade (default: 1).
            onlylong (bool): If True, only take long positions (default: False).
            mtrade (bool): If True, use multiple trade IDs (default: True).
    """

    params = dict(
        period=15,
        stake=1,
        onlylong=False,
        mtrade=True,
    )

    def __init__(self):
        """Initialize the MultiTrades strategy with indicators and tracking variables.

        Sets up the technical indicators (SMA and crossover), configures trade ID
        cycling for multi-trade mode, and initializes all tracking variables for
        performance monitoring.

        The trade ID cycling allows managing multiple concurrent trades:
        - With mtrade=True: cycles through trade IDs [0, 1, 2]
        - With mtrade=False: always uses trade ID [0]

        Attributes initialized:
            order: Stores pending order reference (None if no pending order).
            signal: Crossover indicator (+1 for bullish, -1 for bearish).
            tradeid: Iterator cycling through available trade IDs.
            curtradeid: Current active trade ID for position tracking.
            bar_num: Counter for number of bars processed.
            buy_count: Counter for total buy orders executed.
            sell_count: Counter for total sell orders executed.
            win_count: Counter for profitable trades.
            loss_count: Counter for unprofitable trades.
            sum_profit: Accumulated profit/loss from all closed trades.
        """
        self.order = None
        # Create SMA and crossover signal
        sma = bt.ind.SMA(self.data, period=self.p.period)
        self.signal = bt.ind.CrossOver(self.data.close, sma)

        # Cycle through trade IDs (0, 1, 2) for multi-trade mode
        # This allows up to 3 concurrent trades to be tracked independently
        if self.p.mtrade:
            self.tradeid = itertools.cycle([0, 1, 2])
        else:
            self.tradeid = itertools.cycle([0])

        self.curtradeid = 0

        # Initialize tracking variables for performance analysis
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        """Handle order status updates.

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

    def notify_trade(self, trade):
        """Handle trade completion updates.

        Args:
            trade: The trade object with profit/loss information.

        Note:
            This method is called when a trade is closed (position fully exited).
            Tracks win/loss statistics and cumulative profit/loss.
        """
        if trade.isclosed:
            # Add profit/loss including commissions to total
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        """Execute trading logic for each bar.

        Strategy logic:
        1. On bullish crossover: close existing trade (if any) and open new long
        2. On bearish crossover: close existing trade (if any) and open new short
        3. Each trade gets a unique trade ID for independent tracking

        The strategy uses trade IDs to manage multiple concurrent positions,
        allowing independent tracking and exit of each trade.
        """
        self.bar_num += 1

        # Skip if order already pending to prevent order stacking
        if self.order:
            return

        if self.signal > 0.0:
            # Bullish crossover detected - price crossed above SMA
            # Close any existing position with current trade ID before opening new one
            if self.position:
                self.close(tradeid=self.curtradeid)
            # Get next trade ID from the cycle for the new trade
            self.curtradeid = next(self.tradeid)
            # Open long position with the new trade ID
            self.buy(size=self.p.stake, tradeid=self.curtradeid)

        elif self.signal < 0.0:
            # Bearish crossover detected - price crossed below SMA
            # Close any existing position with current trade ID before opening new one
            if self.position:
                self.close(tradeid=self.curtradeid)
            # Only enter short if not restricted to long-only mode
            if not self.p.onlylong:
                self.curtradeid = next(self.tradeid)
                # Open short position with the new trade ID
                self.sell(size=self.p.stake, tradeid=self.curtradeid)

    def stop(self):
        """Print strategy performance summary after backtest completion.

        Calculates and displays:
        - Final datetime and bar number
        - Total buy and sell order counts
        - Win/loss statistics with win rate percentage
        - Total profit/loss including commissions
        """
        # Calculate win rate as percentage, avoiding division by zero
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
              f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
              f"wins={self.win_count}, losses={self.loss_count}, "
              f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}")


def test_multitrades_strategy():
    """Test the MultiTrades strategy backtest execution.

    This test verifies that multiple trade IDs work correctly by running
    a backtest and asserting the expected performance metrics.

    Test configuration:
    - Initial cash: 100,000
    - Data period: 2006-01-01 to 2006-12-31
    - SMA period: 15 bars
    - Stake per trade: 10
    - Multi-trade mode: Enabled (cycles through trade IDs 0, 1, 2)

    Expected results:
    - Final portfolio value: ~100,916.10
    - Bars processed: 240
    - Annual return: ~0.9%
    - Max drawdown: ~3.2%

    Raises:
        AssertionError: If any performance metric deviates from expected values.
    """
    # Initialize Cerebro engine with standard statistics enabled
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    # Resolve data file path and load historical price data
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="DATA")

    # Add strategy with multi-trade mode enabled
    cerebro.addstrategy(MultiTradesStrategy, period=15, stake=10, mtrade=True)

    # Add performance analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("Running backtest...")
    # Run the backtest and get results
    results = cerebro.run()
    strat = results[0]

    # Extract analysis results
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("MultiTrades Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assert expected results with tolerance for floating point comparison
    # Tolerance: 0.01 for final_value, 1e-6 for other metrics
    assert strat.bar_num == 240, f"Expected bar_num=240, got {strat.bar_num}"
    assert abs(final_value - 100916.1) < 0.01, f"Expected final_value=100916.10, got {final_value}"
    assert sharpe_ratio is None, f"Expected sharpe_ratio=None, got {sharpe_ratio}"
    assert abs(annual_return - (0.009052737167560457)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 3.195383835382446) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("MultiTrades Strategy Test")
    print("=" * 60)
    test_multitrades_strategy()
