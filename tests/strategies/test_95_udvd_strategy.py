#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: UDVD (Upper/Lower Shadow Difference) Strategy.

Reference: Time_Series_Backtesting/有效策略库/UDVD策略1.0.py
Uses the difference between upper and lower shadows to determine trend direction.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
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


class UdvdStrategy(bt.Strategy):
    """UDVD (Upper/Lower Shadow Difference) Strategy (Simplified Version).

    Uses the relationship between price and opening price to determine trend.

    Entry Conditions:
    - Long: Close price > Open price (bullish candle)

    Exit Conditions:
    - Close price < Open price (bearish candle)

    Attributes:
        order: Current pending order.
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.

    Args:
        stake: Number of shares/contracts per trade. Defaults to 10.
        period: Period for SMA calculation. Defaults to 3.
    """
    params = dict(
        stake=10,
        period=3,
    )

    def __init__(self):
        # Calculate bullish/bearish candle signal
        self.candle_body = self.data.close - self.data.open
        self.signal = bt.indicators.SMA(self.candle_body, period=self.p.period)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Signal is positive (overall bullish)
            if self.signal[0] > 0:
                self.order = self.buy(size=self.p.stake)
        else:
            # Signal is negative
            if self.signal[0] <= 0:
                self.order = self.close()


def test_udvd_strategy():
    """Test the UDVD strategy with historical data.

    This function runs a backtest of the UDVD strategy using Oracle stock data
    from 2010-2014 and verifies that the performance metrics match expected values.

    Raises:
        AssertionError: If any of the performance metrics do not match expected values.
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
    cerebro.addstrategy(UdvdStrategy)
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
    print("UDVD Upper/Lower Shadow Difference Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1255, f"Expected bar_num=1255, got {strat.bar_num}"
    assert abs(final_value - 99939.44) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (-0.21533281426868578)) < 1e-6, f"Expected sharpe_ratio=-0.21533281426868578, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0001214372697148802)) < 1e-12, f"Expected annual_return=-0.0001214372697148802, got {annual_return}"
    assert abs(max_drawdown - 0.20019346669376056) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("UDVD Upper/Lower Shadow Difference Strategy Test")
    print("=" * 60)
    test_udvd_strategy()
