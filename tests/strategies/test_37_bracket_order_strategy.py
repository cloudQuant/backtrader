#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Bracket Order Strategy

Reference: backtrader-master2/samples/bracket/bracket.py
Trading using bracket orders (main order + stop loss + take profit)
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
    """Locate data files based on the script directory.

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


class BracketOrderStrategy(bt.Strategy):
    """Bracket Order Strategy.

    Enters using limit orders when moving averages cross over, while
    simultaneously setting stop loss and take profit orders.
    """
    params = dict(
        p1=5,
        p2=15,
        limit=0.005,
        limdays=3,
        limdays2=1000,
        hold=10,
    )

    def __init__(self):
        """Initialize the Bracket Order Strategy.

        Sets up the technical indicators and tracking variables for the strategy.
        Creates two simple moving averages (SMA) and a crossover indicator to
        generate entry signals. Also initializes tracking variables for order
        references, position holding, and performance statistics.
        """
        ma1 = bt.ind.SMA(period=self.p.p1)
        ma2 = bt.ind.SMA(period=self.p.p2)
        self.cross = bt.ind.CrossOver(ma1, ma2)
        self.orefs = list()
        self.holdstart = 0

        # Statistics variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        """Handle order status notifications.

        Tracks completed orders by incrementing buy/sell counters and updating
        the hold start time. Also removes order references from the active order
        list when orders are no longer alive (completed, cancelled, or expired).

        Args:
            order: The order object that has changed status.
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
            self.holdstart = len(self)

        if not order.alive() and order.ref in self.orefs:
            self.orefs.remove(order.ref)

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Updates performance statistics when a trade is closed, including
        total profit/loss, win count, and loss count based on the trade's
        net profit (pnlcomm).

        Args:
            trade: The trade object that has been closed.
        """
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        """Execute trading logic for each bar.

        This method is called for each bar in the data series. It implements
        the bracket order strategy logic:
        1. Skips if there are active orders pending
        2. When not in a position and the fast SMA crosses above the slow SMA,
           creates a bracket order with:
           - Main limit buy order (p1) at current price * (1 - limit)
           - Stop loss sell order (p2) at p1 - 2% of close price
           - Take profit sell order (p3) at p1 + 2% of close price

        The bracket orders are transmitted together as a group, with the stop
        loss and take profit orders as children of the main limit order.
        """
        self.bar_num += 1

        if self.orefs:
            return

        if not self.position:
            if self.cross > 0.0:
                close = self.data.close[0]
                p1 = close * (1.0 - self.p.limit)
                p2 = p1 - 0.02 * close
                p3 = p1 + 0.02 * close

                valid1 = datetime.timedelta(self.p.limdays)
                valid2 = valid3 = datetime.timedelta(self.p.limdays2)

                o1 = self.buy(
                    exectype=bt.Order.Limit,
                    price=p1,
                    valid=valid1,
                    transmit=False
                )

                o2 = self.sell(
                    exectype=bt.Order.Stop,
                    price=p2,
                    valid=valid2,
                    parent=o1,
                    transmit=False
                )

                o3 = self.sell(
                    exectype=bt.Order.Limit,
                    price=p3,
                    valid=valid3,
                    parent=o1,
                    transmit=True
                )

                self.orefs = [o1.ref, o2.ref, o3.ref]

    def stop(self):
        """Print final performance statistics when backtesting completes.

        Calculates and displays the win rate along with other performance
        metrics including total bars processed, buy/sell counts, win/loss
        counts, and total profit/loss.
        """
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(
            f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
            f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, "
            f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}"
        )


def test_bracket_order_strategy():
    """Test the Bracket Order Strategy implementation and performance.

    This test function:
    1. Sets up a Cerebro backtesting engine with initial capital of 100,000
    2. Loads daily price data from 2005-2006
    3. Runs the BracketOrderStrategy with fixed position sizing (10 shares)
    4. Collects performance metrics via analyzers (Sharpe Ratio, Returns, DrawDown, TradeAnalyzer)
    5. Validates the results against expected values

    Expected results:
    - 497 total bars processed
    - 8 buy orders and 8 sell orders executed
    - 4 winning trades and 4 losing trades (50% win rate)
    - Final portfolio value: 99,875.56
    - Sharpe ratio: -1.4294780971098613
    - Annual return: -0.06127%
    - Maximum drawdown: 2.57%

    Raises:
        AssertionError: If any of the performance metrics don't match expected values.
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

    cerebro.addstrategy(BracketOrderStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

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
    print("Bracket Order Strategy Backtest Results:")
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
    assert strat.buy_count == 8, f"Expected buy_count=8, got {strat.buy_count}"
    assert strat.sell_count == 8, f"Expected sell_count=8, got {strat.sell_count}"
    assert strat.win_count == 4, f"Expected win_count=4, got {strat.win_count}"
    assert strat.loss_count == 4, f"Expected loss_count=4, got {strat.loss_count}"
    assert total_trades == 8, f"Expected total_trades=8, got {total_trades}"
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert abs(final_value - 99875.56) < 0.01, f"Expected final_value=99875.56, got {final_value}"
    assert abs(sharpe_ratio - (-1.4294780971098613)) < 1e-6, f"Expected sharpe_ratio=-1.4294780971098613, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00061268161526827)) < 1e-6, f"Expected annual_return=-0.00061268161526827, got {annual_return}"
    assert abs(max_drawdown - 2.5691583906006734) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Bracket Order Strategy Test")
    print("=" * 60)
    test_bracket_order_strategy()
