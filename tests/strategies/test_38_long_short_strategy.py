#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Long Short Strategy

Reference: backtrader-master2/samples/analyzer-annualreturn/analyzer-annualreturn.py
A long-short strategy based on price and SMA crossover.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data file based on the script directory.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths.
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


class LongShortStrategy(bt.Strategy):
    """Long Short Strategy.

    This strategy goes long when price crosses above SMA, and goes short
    when price crosses below SMA.

    Attributes:
        orderid: ID of the current pending order.
        signal: Crossover signal indicator.
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
        win_count: Number of profitable trades.
        loss_count: Number of losing trades.
        sum_profit: Total profit/loss from all closed trades.
    """
    params = dict(
        period=15,
        stake=1,
        onlylong=False,
    )

    def __init__(self):
        """Initialize the Long Short Strategy.

        Sets up the Simple Moving Average (SMA) indicator and crossover
        signal to detect when price crosses above or below the SMA.
        Initializes all tracking variables for trade statistics.
        """
        self.orderid = None
        sma = bt.ind.SMA(self.data, period=self.p.period)
        self.signal = bt.ind.CrossOver(self.data.close, sma)

        # Statistics variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        """Handle order status updates.

        Called by the broker when an order changes status. Tracks completed
        buy and sell orders for statistics.

        Args:
            order: The order object with updated status information.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

        elif order.status in [order.Expired, order.Canceled, order.Margin]:
            pass

        self.orderid = None

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Called when a trade is closed. Updates profit/loss statistics
        and win/loss counters.

        Args:
            trade: The closed trade object containing profit/loss information.
        """
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        """Execute trading logic for each bar.

        Called on every bar update. Implements the long-short strategy:
        - Go long when price crosses above SMA
        - Go short when price crosses below SMA (if not in long-only mode)
        - Close existing positions before opening new ones

        The strategy ensures only one order is pending at a time.
        """
        self.bar_num += 1

        if self.orderid:
            return

        if self.signal > 0.0:
            if self.position:
                self.close()
            self.buy(size=self.p.stake)

        elif self.signal < 0.0:
            if self.position:
                self.close()
            if not self.p.onlylong:
                self.sell(size=self.p.stake)

    def stop(self):
        """Called when the backtest is finished.

        Prints final statistics including bar count, trade counts,
        win/loss ratio, and total profit/loss.

        The win rate is calculated as: (wins / total trades) * 100
        """
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(
            f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
            f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, "
            f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}"
        )


def test_long_short_strategy():
    """Test the Long Short Strategy.

    This test function runs a backtest of the LongShortStrategy with
    historical price data and verifies that the strategy produces
    expected results including trade counts, win/loss ratios, and
    performance metrics.

    Raises:
        AssertionError: If any of the expected values do not match the
            actual results within the specified tolerance.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="DATA")

    cerebro.addstrategy(LongShortStrategy, period=15, stake=10, onlylong=False)

    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")
    cerebro.addanalyzer(bt.analyzers.SQN, _name="my_sqn")

    print("Starting backtest...")
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
    print("Long Short Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  win_count: {strat.win_count}")
    print(f"  loss_count: {strat.loss_count}")
    print(f"  sum_profit: {strat.sum_profit:.2f}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num == 497, f"Expected bar_num=497, got {strat.bar_num}"
    assert strat.buy_count == 57, f"Expected buy_count=57, got {strat.buy_count}"
    assert strat.sell_count == 56, f"Expected sell_count=56, got {strat.sell_count}"
    assert strat.win_count == 17, f"Expected win_count=17, got {strat.win_count}"
    assert strat.loss_count == 39, f"Expected loss_count=39, got {strat.loss_count}"
    assert total_trades == 57, f"Expected total_trades=57, got {total_trades}"
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert abs(final_value - 102093.5) < 0.01, f"Expected final_value=102093.50, got {final_value}"
    assert abs(sharpe_ratio - (0.10840186537088062)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.010249743255163991)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 3.1589101255944287) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Long Short Strategy Test")
    print("=" * 60)
    test_long_short_strategy()
