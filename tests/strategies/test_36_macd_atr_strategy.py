#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: MACD ATR Strategy

Reference: backtrader-master2/samples/macd-settings/macd-settings.py
Based on MACD crossover and SMA direction filtering, using ATR dynamic stop loss.
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


class MACDATRStrategy(bt.Strategy):
    """MACD ATR Strategy.

    Entry condition: MACD line crosses above signal line AND SMA direction is
        downward (counter-trend entry).
    Exit condition: Price falls below ATR dynamic stop loss price.

    Attributes:
        macd: MACD indicator instance.
        mcross: CrossOver indicator for MACD and signal line.
        atr: ATR indicator instance.
        sma: SMA indicator instance.
        smadir: SMA direction indicator.
        order: Current pending order.
        pstop: Current stop loss price.
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
        win_count: Number of profitable trades.
        loss_count: Number of losing trades.
        sum_profit: Total profit/loss from all closed trades.
    """
    params = (
        ('macd1', 12),
        ('macd2', 26),
        ('macdsig', 9),
        ('atrperiod', 14),
        ('atrdist', 3.0),
        ('smaperiod', 30),
        ('dirperiod', 10),
    )

    def __init__(self):
        """Initialize the MACD ATR strategy.

        Sets up the technical indicators used for trading signals and initializes
        the tracking variables for orders, trades, and statistics.

        The strategy uses:
        - MACD (Moving Average Convergence Divergence) for trend momentum
        - CrossOver of MACD and signal line for entry signals
        - ATR (Average True Range) for dynamic stop loss calculation
        - SMA (Simple Moving Average) for trend direction filtering
        """
        self.macd = bt.indicators.MACD(
            self.data,
            period_me1=self.p.macd1,
            period_me2=self.p.macd2,
            period_signal=self.p.macdsig
        )
        self.mcross = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atrperiod)
        self.sma = bt.indicators.SMA(self.data, period=self.p.smaperiod)
        self.smadir = self.sma - self.sma(-self.p.dirperiod)

        self.order = None
        self.pstop = 0

        # Statistical variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        """Handle order status updates.

        Updates the buy/sell order counters when orders are completed and
        clears the pending order reference when the order is no longer alive.

        Args:
            order: The order object with status information.
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        if not order.alive():
            self.order = None

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Updates profit/loss statistics and win/loss counters when a trade is closed.

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

        This method is called for each bar in the data feed and implements the
        core strategy logic:

        Entry conditions:
        - MACD line crosses above signal line (bullish signal)
        - SMA direction is negative (counter-trend entry)

        Exit conditions:
        - Close price falls below the ATR-based trailing stop loss

        The stop loss is dynamically adjusted based on ATR to track price movement.
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            if self.mcross[0] > 0.0 and self.smadir < 0.0:
                self.order = self.buy()
                pdist = self.atr[0] * self.p.atrdist
                self.pstop = self.data.close[0] - pdist
        else:
            pclose = self.data.close[0]
            pstop = self.pstop

            if pclose < pstop:
                self.order = self.close()
            else:
                pdist = self.atr[0] * self.p.atrdist
                self.pstop = max(pstop, pclose - pdist)

    def stop(self):
        """Print final strategy statistics when backtesting completes.

        Calculates and displays the win rate and total profit/loss along with
        trading statistics including number of bars processed, buy/sell counts,
        and win/loss counts.
        """
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(
            f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
            f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, "
            f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}"
        )


def test_macd_atr_strategy():
    """Test the MACD ATR strategy.

    This function runs a backtest of the MACD ATR strategy on Yahoo stock data
    from 2005-2014 and verifies the results match expected values.

    Raises:
        AssertionError: If any of the backtest metrics do not match expected values.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(50000.0)

    print("Loading data...")
    data_path = resolve_data_path("yhoo-1996-2014.txt")
    data = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2014, 12, 31)
    )
    cerebro.adddata(data, name="YHOO")

    cerebro.addstrategy(MACDATRStrategy)

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
    print("MACD ATR Strategy Backtest Results:")
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

    assert strat.bar_num == 2477, f"Expected bar_num=2477, got {strat.bar_num}"
    assert strat.buy_count == 46, f"Expected buy_count=46, got {strat.buy_count}"
    assert strat.sell_count == 45, f"Expected sell_count=45, got {strat.sell_count}"
    assert strat.win_count == 17, f"Expected win_count=17, got {strat.win_count}"
    assert strat.loss_count == 28, f"Expected loss_count=28, got {strat.loss_count}"
    assert total_trades == 46, f"Expected total_trades=46, got {total_trades}"
    assert abs(final_value - 49993.58) < 0.01, f"Expected final_value=49993.58, got {final_value}"
    assert abs(sharpe_ratio - (-66.34914054216533)) < 1e-6, f"Expected sharpe_ratio=-66.34914054216533, got {sharpe_ratio}"
    assert abs(annual_return - (-1.2861156358361e-05)) < 1e-9, f"Expected annual_return=-1.2861156358361e-05, got {annual_return}"
    assert abs(max_drawdown - 0.07560831095513623) < 1e-6, f"Expected max_drawdown=0.07560831095513623, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("MACD ATR Strategy Test")
    print("=" * 60)
    test_macd_atr_strategy()
