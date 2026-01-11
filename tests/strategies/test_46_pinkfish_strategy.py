#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test suite for Pinkfish Challenge Strategy.

This module tests the Pinkfish Challenge strategy which buys when price
makes a new N-day high and sells after holding for a fixed number of days.

Reference: backtrader-master2/samples/pinkfish-challenge/pinkfish-challenge.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
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


class PinkfishStrategy(bt.Strategy):
    """Pinkfish Challenge strategy - buy on N-day high, sell after fixed days.

    This strategy implements a simple trend-following approach:
    1. Buy when price makes a new N-day high
    2. Hold for a fixed number of days
    3. Sell regardless of price

    Attributes:
        params: Dictionary containing strategy parameters.
            highperiod (int): Number of days to check for highest high (default: 20).
            sellafter (int): Number of bars to hold before selling (default: 2).
    """

    params = (
        ('highperiod', 20),
        ('sellafter', 2),
    )

    def __init__(self):
        """Initialize the Pinkfish Challenge strategy.

        Sets up the indicator for tracking highest highs and initializes
        performance tracking variables for monitoring trade statistics.

        Attributes initialized:
            highest: Indicator tracking the N-day highest high price.
            inmarket: Bar number when entering a position (0 if not in market).
            bar_num: Total number of bars processed during backtest.
            buy_count: Total number of buy orders executed.
            sell_count: Total number of sell orders executed.
            win_count: Number of profitable trades closed.
            loss_count: Number of unprofitable trades closed.
            sum_profit: Cumulative profit/loss from all closed trades.
        """
        # Track the highest high over the specified period
        # This indicator updates each bar to show the maximum high price
        # over the last highperiod bars
        self.highest = bt.ind.Highest(self.data.high, period=self.p.highperiod)

        # Track which bar we entered the market
        # Used to calculate how many bars we've held a position
        # Value is 0 when not in market, otherwise set to len(self) on entry
        self.inmarket = 0

        # Initialize tracking variables for performance analysis
        self.bar_num = 0      # Counter for total bars processed
        self.buy_count = 0    # Total buy orders completed
        self.sell_count = 0   # Total sell orders completed
        self.win_count = 0    # Profitable closed trades
        self.loss_count = 0   # Unprofitable closed trades
        self.sum_profit = 0.0 # Cumulative PnL including commissions

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object with status information.
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def notify_trade(self, trade):
        """Handle trade completion updates.

        Args:
            trade: The trade object with profit/loss information.
        """
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        """Execute trading logic for each bar.

        Strategy logic:
        1. If not in position: buy when current high equals N-day highest high
        2. If in position: sell after holding for specified number of bars
        """
        self.bar_num += 1

        if not self.position:
            # Enter when price makes new N-day high
            if self.data.high[0] >= self.highest[0]:
                self.buy()
                self.inmarket = len(self)
        else:
            # Exit after holding for specified number of bars
            if (len(self) - self.inmarket) >= self.p.sellafter:
                self.sell()

    def stop(self):
        """Print strategy performance summary after backtest completion."""
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
              f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
              f"wins={self.win_count}, losses={self.loss_count}, "
              f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}")


def test_pinkfish_strategy():
    """Test the Pinkfish Challenge strategy backtest execution.

    This test verifies that the Pinkfish Challenge strategy works correctly
    by running a backtest and asserting the expected performance metrics.

    Raises:
        AssertionError: If any performance metric deviates from expected values.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(50000.0)

    print("Loading data...")
    data_path = resolve_data_path("yhoo-1996-2014.txt")
    data = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="YHOO")

    cerebro.addstrategy(PinkfishStrategy, highperiod=20, sellafter=2)
    cerebro.addsizer(bt.sizers.FixedSize, stake=100)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("Running backtest...")
    results = cerebro.run()
    strat = results[0]

    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Pinkfish Challenge Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Tolerance: 0.01 for final_value, 1e-6 for other metrics
    assert strat.bar_num == 484, f"Expected bar_num=484, got {strat.bar_num}"
    assert abs(final_value - 49739.0) < 0.01, f"Expected final_value=49739.00, got {final_value}"
    assert abs(sharpe_ratio - (-2.519733167360895)) < 1e-6, f"Expected sharpe_ratio=-2.519733167360895, got {sharpe_ratio}"
    assert abs(annual_return - (-0.002618603816279576)) < 1e-6, f"Expected annual_return=-0.002618603816279576, got {annual_return}"
    assert abs(max_drawdown - 0.8234965704259053) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Pinkfish Challenge Strategy Test")
    print("=" * 60)
    test_pinkfish_strategy()
