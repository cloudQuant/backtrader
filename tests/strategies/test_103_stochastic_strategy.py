#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Stochastic oscillator strategy.

Uses KD stochastic indicator crossovers and overbought/oversold levels to determine entry timing.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching common directories.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the found data file.

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


class StochasticStrategy(bt.Strategy):
    """Stochastic oscillator strategy.

    Entry conditions:
    - Long: K line crosses above D line and in oversold zone (K < 20)

    Exit conditions:
    - K line crosses below D line and in overbought zone (K > 80)
    """
    params = dict(
        stake=10,
        period=14,
        period_dfast=3,
        oversold=20,
        overbought=80,
    )

    def __init__(self):
        """Initialize strategy indicators and state variables."""
        self.stoch = bt.indicators.Stochastic(
            self.data,
            period=self.p.period,
            period_dfast=self.p.period_dfast,
        )
        self.crossover = bt.indicators.CrossOver(self.stoch.percK, self.stoch.percD)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object that was updated.
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
        """Execute trading logic for each bar."""
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # K crosses above D and in oversold zone
            if self.crossover[0] > 0 and self.stoch.percK[0] < self.p.oversold:
                self.order = self.buy(size=self.p.stake)
        else:
            # K crosses below D and in overbought zone
            if self.crossover[0] < 0 and self.stoch.percK[0] > self.p.overbought:
                self.order = self.close()


def test_stochastic_strategy():
    """Test the Stochastic oscillator strategy.

    This test validates that the Stochastic-based strategy correctly
    identifies overbought/oversold conditions and produces expected
    backtest results.

    Raises:
        AssertionError: If any of the expected values do not match the
            actual results within the specified tolerance.
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
    cerebro.addstrategy(StochasticStrategy)
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
    print("Stochastic oscillator strategy backtest results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assertions - using precise assertions
    # final_value tolerance: 0.01, other indicators tolerance: 1e-6
    assert strat.bar_num == 1239, f"Expected bar_num=1239, got {strat.bar_num}"
    assert abs(final_value - 100219.02) < 0.01, f"Expected final_value=100219.02, got {final_value}"
    assert abs(sharpe_ratio - (0.6920676725735596)) < 1e-6, f"Expected sharpe_ratio=0.6920676725735596, got {sharpe_ratio}"
    assert abs(annual_return - (0.00043870134135070356)) < 1e-6, f"Expected annual_return=0.00043870134135070356, got {annual_return}"
    assert abs(max_drawdown - 0.08496694553344107) < 1e-6, f"Expected max_drawdown=0.08496694553344107, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Stochastic Oscillator Strategy Test")
    print("=" * 60)
    test_stochastic_strategy()
