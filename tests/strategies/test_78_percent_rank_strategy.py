#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test suite for Percent Rank strategy.

This module tests a mean reversion strategy based on the percentile ranking
of MACD histogram values. It buys when the indicator is at extreme lows and
sells when at extreme highs.

Reference: https://github.com/backtrader/backhacker
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching common locations.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any search path.
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


class PercentRankStrategy(bt.Strategy):
    """Percent Rank mean reversion strategy.

    This strategy uses percentile ranking of MACD histogram values to identify
    extreme conditions for mean reversion trades. It waits for confirmation
    before entering positions.

    Trading Rules:
        - Buy when percentile drops to limit1 (e.g., 10%), then rises above limit2 (e.g., 30%)
        - Sell when percentile rises to (100-limit1) (e.g., 90%), then falls below (100-limit2) (e.g., 70%)

    Attributes:
        dataclose: Close price data series.
        ma1: Short-term EMA for MACD calculation.
        ma2: Long-term EMA for MACD calculation.
        diff: MACD histogram (EMA1 - EMA2).
        prank: Percentile rank of MACD histogram (0-100 scale).
        buy_limit1: Lower percentile threshold for buy signal.
        sell_limit1: Upper percentile threshold for sell signal.
        buy_limit2: Confirmation threshold for buy entry.
        sell_limit2: Confirmation threshold for sell entry.
        pending_buy: Flag indicating buy signal triggered, waiting for confirmation.
        pending_sell: Flag indicating sell signal triggered, waiting for confirmation.
        order: Current pending order.
        last_operation: Last executed operation ("BUY" or "SELL").
        bar_num: Number of bars processed.
        buy_count: Total buy orders executed.
        sell_count: Total sell orders executed.

    Args:
        stake: Number of shares per trade (default: 10).
        percent_period: Period for percentile rank calculation (default: 200).
        limit1: Initial trigger threshold (default: 10).
        limit2: Confirmation threshold (default: 30).
        period1: Short EMA period for MACD (default: 12).
        period2: Long EMA period for MACD (default: 26).
    """
    params = dict(
        stake=10,
        percent_period=200,
        limit1=10,
        limit2=30,
        period1=12,
        period2=26,
    )

    def __init__(self):
        """Initialize strategy indicators and state variables."""
        self.dataclose = self.datas[0].close
        self.ma1 = bt.ind.EMA(self.datas[0], period=self.p.period1)
        self.ma2 = bt.ind.EMA(self.datas[0], period=self.p.period2)
        self.diff = self.ma1 - self.ma2
        self.prank = bt.ind.PercentRank(self.diff, period=self.p.percent_period) * 100

        self.buy_limit1 = self.p.limit1
        self.sell_limit1 = 100 - self.buy_limit1
        self.buy_limit2 = self.p.limit2
        self.sell_limit2 = 100 - self.buy_limit2

        self.pending_buy = False
        self.pending_sell = False

        self.order = None
        self.last_operation = "SELL"

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object with updated status.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.last_operation = "BUY"
            else:
                self.sell_count += 1
                self.last_operation = "SELL"
        self.order = None

    def next(self):
        """Execute trading logic for each bar.

        Implements a two-stage entry system: initial trigger at extreme levels,
        followed by confirmation when percentile moves back toward mean.
        """
        self.bar_num += 1
        if self.order:
            return

        # Buy logic: Wait for extreme low, then confirmation on rise
        if self.last_operation != "BUY":
            if self.prank[0] <= self.buy_limit1:
                # Trigger: percentile at extreme low
                self.pending_buy = True
            elif self.pending_buy and self.prank[0] >= self.buy_limit2:
                # Confirmation: percentile has risen back up
                self.pending_buy = False
                self.order = self.buy(size=self.p.stake)

        # Sell logic: Wait for extreme high, then confirmation on decline
        if self.last_operation != "SELL":
            if self.prank[0] >= self.sell_limit1:
                # Trigger: percentile at extreme high
                self.pending_sell = True
            elif self.pending_sell and self.prank[0] <= self.sell_limit2:
                # Confirmation: percentile has fallen back down
                self.pending_sell = False
                self.order = self.sell(size=self.p.stake)


def test_percent_rank_strategy():
    """Test the Percent Rank strategy backtest.

    This test runs a backtest on Oracle stock data (2000-2014) and validates
    that the strategy produces expected performance metrics.

    Raises:
        AssertionError: If any performance metric deviates from expected values.
    """
    cerebro = bt.Cerebro()
    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(PercentRankStrategy)
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
    print("Percent Rank Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 3548, f"Expected bar_num=3548, got {strat.bar_num}"
    assert abs(final_value - 100302.26) < 0.01, f"Expected final_value=100302.26, got {final_value}"
    assert abs(sharpe_ratio - (0.8675517538455737)) < 1e-6, f"Expected sharpe_ratio=0.8675517538455737, got {sharpe_ratio}"
    assert abs(annual_return - (0.00020164856372564902)) < 1e-6, f"Expected annual_return=0.00020164856372564902, got {annual_return}"
    assert abs(max_drawdown - 0.11557448332367173) < 1e-6, f"Expected max_drawdown=0.11557448332367173, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Percent Rank Strategy Test")
    print("=" * 60)
    test_percent_rank_strategy()
