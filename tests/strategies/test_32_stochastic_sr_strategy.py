#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case: Stochastic SR (Stochastic Support/Resistance) strategy.

Reference: backtrader-backtests/StochasticSR/Stochastic_SR_Backtest.py
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
    """Resolve data file path based on script directory to avoid relative path failures.

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


class StochasticSRStrategy(bt.Strategy):
    """Trading strategy that utilizes the Stochastic Oscillator indicator for oversold/overbought entry points,
    and previous support/resistance via Donchian Channels as well as a max loss in pips for risk levels."""

    params = (
        ('period', 14),
        ('pfast', 3),
        ('pslow', 3),
        ('upperLimit', 80),
        ('lowerLimit', 20),
        ('stop_pips', 0.5),  # Stop loss in points adjusted for stock prices
    )

    def __init__(self):
        """Initializes variables required for the strategy implementation."""
        self.order = None
        self.donchian_stop_price = None
        self.price = None
        self.stop_price = None
        self.stop_donchian = None

        self.stochastic = bt.indicators.Stochastic(
            self.data, 
            period=self.params.period, 
            period_dfast=self.params.pfast, 
            period_dslow=self.params.pslow,
            upperband=self.params.upperLimit, 
            lowerband=self.params.lowerLimit
        )

        # Statistics variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_trade(self, trade):
        """Run on every next iteration, logs the P/L with and without commission whenever a trade is closed."""
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def notify_order(self, order):
        """Run on every next iteration, logs the order execution status."""
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.price = order.executed.price
            elif order.issell():
                self.sell_count += 1
                self.price = order.executed.price
        elif order.status in [order.Rejected, order.Margin]:
            pass

        self.order = None

    def next(self):
        """Checks to see if Stochastic Oscillator, position, and order conditions meet the entry or exit conditions."""
        self.bar_num += 1

        if self.order:
            return

        if self.position.size == 0:
            # When stochastic crosses back below 80, enter short position.
            if self.stochastic.lines.percD[-1] >= 80 and self.stochastic.lines.percD[0] <= 80:
                self.donchian_stop_price = max(self.data.high.get(size=self.params.period))
                self.order = self.sell()
                self.stop_price = self.buy(exectype=bt.Order.Stop, price=self.data.close[0] + self.params.stop_pips, oco=self.stop_donchian)
                self.stop_donchian = self.buy(exectype=bt.Order.Stop, price=self.donchian_stop_price, oco=self.stop_price)
            # when stochastic crosses back above 20, enter long position.
            elif self.stochastic.lines.percD[-1] <= 20 and self.stochastic.lines.percD[0] >= 20:
                self.donchian_stop_price = min(self.data.low.get(size=self.params.period))
                self.order = self.buy()
                self.stop_price = self.sell(exectype=bt.Order.Stop, price=self.data.close[0] - self.params.stop_pips, oco=self.stop_donchian)
                self.stop_donchian = self.sell(exectype=bt.Order.Stop, price=self.donchian_stop_price, oco=self.stop_price)

        if self.position.size > 0:
            # When stochastic is above 70, close out of long position
            if self.stochastic.lines.percD[0] >= 70:
                self.close(oco=self.stop_price)
        if self.position.size < 0:
            # When stochastic is below 30, close out of short position
            if self.stochastic.lines.percD[0] <= 30:
                self.close(oco=self.stop_price)

    def stop(self):
        """Output statistics information when the strategy stops."""
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(
            f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
            f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, "
            f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}"
        )


def test_stochastic_sr_strategy():
    """Test the Stochastic SR (Stochastic Support/Resistance) strategy.

    This test function:
    1. Loads Shanghai Stock Exchange data (SH600000)
    2. Runs the Stochastic SR strategy with specified parameters
    3. Analyzes performance using various analyzers (Sharpe, Returns, DrawDown, Trade)
    4. Validates results against expected values
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading Shanghai Stock Exchange data...")
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

    cerebro.addstrategy(StochasticSRStrategy, period=14, pfast=3, pslow=3, upperLimit=80, lowerLimit=20, stop_pips=0.5)

    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("Starting backtest...")
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
    print("Stochastic SR Strategy Backtest Results:")
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

    # Assertions - Ensure the strategy runs correctly
    assert strat.bar_num == 5398, f"Expected bar_num=5398, got {strat.bar_num}"
    assert strat.buy_count == 309, f"Expected buy_count=309, got {strat.buy_count}"
    assert strat.sell_count == 309, f"Expected sell_count=309, got {strat.sell_count}"
    assert strat.win_count == 112, f"Expected win_count=112, got {strat.win_count}"
    assert strat.loss_count == 197, f"Expected loss_count=197, got {strat.loss_count}"
    assert total_trades == 309, f"Expected total_trades=309, got {total_trades}"
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert abs(final_value - 99989.23) < 0.01, f"Expected final_value=99989.23, got {final_value}"
    assert abs(sharpe_ratio - (-493.17567594903824)) < 1e-6, f"Expected sharpe_ratio=-493.17567594903824, got {sharpe_ratio}"
    assert abs(annual_return - (-5.012334920267567e-06)) < 1e-10, f"Expected annual_return=-5.012334920267567e-06, got {annual_return}"
    assert abs(max_drawdown - 0.02176998911502407) < 1e-6, f"Expected max_drawdown=0.02176998911502407, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Stochastic SR Strategy Test")
    print("=" * 60)
    test_stochastic_sr_strategy()
