#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: BB_ADX Bollinger Bands + ADX mean reversion strategy

Reference source: backtrader-backtests/BollBand and ADX/BB_ADX.py
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
    """Locate data files based on the script directory to avoid relative path reading failures.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the search paths.
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


class BBADXStrategy(bt.Strategy):
    """Mean Reversion trading strategy that utilizes Bollinger Bands for signals and ADX for locating and avoiding trends"""

    params = (
        ('BB_MA', 20),
        ('BB_SD', 2),
        ('ADX_Period', 14),
        ('ADX_Max', 40),
    )

    def __init__(self):
        """Initializes all variables to be used in this strategy"""
        self.order = None
        self.stopprice = None
        self.closepos = None
        self.adx = bt.indicators.AverageDirectionalMovementIndex(self.data, period=self.params.ADX_Period)
        self.bb = bt.indicators.BollingerBands(self.data, period=self.params.BB_MA, devfactor=self.params.BB_SD)

        # Statistics variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0
        self.entry_price = 0.0

    def notify_order(self, order):
        """Run on every next iteration. Checks order status and logs accordingly"""
        if order.status in [order.Submitted, order.Accepted]:
            return
        elif order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.entry_price = order.executed.price
            if order.issell():
                self.sell_count += 1
                if self.position.size == 0:
                    # Calculate profit/loss when closing position
                    pass
        elif order.status in [order.Rejected, order.Margin]:
            pass

        self.order = None

    def notify_trade(self, trade):
        """Run on every next iteration. Logs data on every trade when closed."""
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        """Runs for every candlestick. Checks conditions to enter and exit trades."""
        self.bar_num += 1

        if self.order:
            return

        if self.position.size == 0:
            if self.adx[0] < self.params.ADX_Max:
                if (self.data.close[-1] > self.bb.lines.top[-1]) and (self.data.close[0] <= self.bb.lines.top[0]):
                    self.order = self.sell()
                    self.stopprice = self.bb.lines.top[0]
                    self.closepos = self.buy(exectype=bt.Order.Stop, price=self.stopprice)

                elif (self.data.close[-1] < self.bb.lines.bot[-1]) and (self.data.close[0] >= self.bb.lines.bot[0]):
                    self.order = self.buy()
                    self.stopprice = self.bb.lines.bot[0]
                    self.closepos = self.sell(exectype=bt.Order.Stop, price=self.stopprice)

        elif self.position.size > 0:
            if (self.data.close[-1] < self.bb.lines.mid[-1]) and (self.data.close[0] >= self.bb.lines.mid[0]):
                self.closepos = self.close()
        elif self.position.size < 0:
            if (self.data.close[-1] > self.bb.lines.mid[-1]) and (self.data.close[0] <= self.bb.lines.mid[0]):
                self.closepos = self.close()

    def stop(self):
        """Output statistical information."""
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(
            f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
            f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, "
            f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}"
        )


def test_bb_adx_strategy():
    """Test BB_ADX Bollinger Bands + ADX mean reversion strategy.

    This test function creates a cerebro instance, loads Shanghai stock data,
    and runs backtesting with the BBADXStrategy. It then verifies the results
    against expected values using assertions.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading Shanghai stock data...")
    data_path = resolve_data_path("sh600000.csv")
    df = pd.read_csv(data_path)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime')
    df = df.set_index('datetime')
    df = df[(df.index >= '2000-01-01') & (df.index <= '2022-12-31')]
    df = df[df['close'] > 0]

    df = df[['open', 'high', 'low', 'close', 'volume']]

    data_feed = bt.feeds.PandasData(
        dataname=df,
        datetime=None,
        open=0,
        high=1,
        low=2,
        close=3,
        volume=4,
        openinterest=-1,
    )
    cerebro.adddata(data_feed, name="SH600000")

    cerebro.addstrategy(BBADXStrategy, BB_MA=20, BB_SD=2, ADX_Period=14, ADX_Max=40)

    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("Starting backtesting...")
    results = cerebro.run()
    strat = results[0]

    # Get analyzer results
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("BB_ADX Bollinger Bands + ADX mean reversion strategy backtest results:")
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

    # Assertions - ensure strategy runs correctly
    assert strat.bar_num == 5388, f"Expected bar_num=5388, got {strat.bar_num}"
    assert strat.buy_count == 296, f"Expected buy_count=296, got {strat.buy_count}"
    assert strat.sell_count == 295, f"Expected sell_count=295, got {strat.sell_count}"
    assert strat.win_count == 59, f"Expected win_count=59, got {strat.win_count}"
    assert strat.loss_count == 234, f"Expected loss_count=234, got {strat.loss_count}"
    assert total_trades == 293, f"Expected total_trades=293, got {total_trades}"
    assert abs(final_value - 99971.15) < 0.01, f"Expected final_value=99971.15, got {final_value}"
    assert abs(sharpe_ratio - (-317.95948928473916)) < 1e-6, f"Expected sharpe_ratio=-317.95948928473916, got {sharpe_ratio}"
    assert abs(annual_return - (-1.3426746125718879e-05)) < 1e-9, f"Expected annual_return=-1.3426746125718879e-05, got {annual_return}"
    assert abs(max_drawdown - 0.037680134320528774) < 1e-6, f"Expected max_drawdown=0.037680134320528774, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("BB_ADX Bollinger Bands + ADX mean reversion strategy test")
    print("=" * 60)
    test_bb_adx_strategy()
