#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Up Down Candles Strategy

Reference: https://github.com/backtrader-stuff/strategies
Mean reversion strategy based on candlestick strength and returns
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching in common locations.

    Args:
        filename: The name of the data file to locate.

    Returns:
        Path: The absolute path to the first matching data file found.

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


class UpDownCandleStrength(bt.Indicator):
    """Up Down Candle Strength Indicator.

    Calculates the ratio of up/down candles over a period.
    """
    lines = ('strength',)
    params = dict(period=20,)

    def __init__(self):
        self.addminperiod(self.p.period)

    def next(self):
        up_count = 0
        down_count = 0
        for i in range(self.p.period):
            if self.data.close[-i] > self.data.open[-i]:
                up_count += 1
            elif self.data.close[-i] < self.data.open[-i]:
                down_count += 1
        
        total = up_count + down_count
        if total == 0:
            self.lines.strength[0] = 0.5
        else:
            self.lines.strength[0] = up_count / total


class PercentReturnsPeriod(bt.Indicator):
    """Period Percentage Returns Indicator."""
    lines = ('returns',)
    params = dict(period=40,)

    def __init__(self):
        self.addminperiod(self.p.period)

    def next(self):
        if self.data.close[-self.p.period] != 0:
            self.lines.returns[0] = (self.data.close[0] - self.data.close[-self.p.period]) / self.data.close[-self.p.period]
        else:
            self.lines.returns[0] = 0


class UpDownCandlesStrategy(bt.Strategy):
    """Up Down Candles Strategy.

    This strategy implements mean reversion based on candlestick patterns:
    - Calculates candlestick strength and period returns
    - Goes short when returns are positive and exceed threshold (mean reversion)
    - Goes long when returns are negative and exceed threshold (mean reversion)
    """
    params = dict(
        stake=10,
        strength_period=20,
        returns_period=40,
        returns_threshold=0.01,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        
        self.strength = UpDownCandleStrength(
            self.datas[0],
            period=self.p.strength_period
        )
        
        self.returns = PercentReturnsPeriod(
            self.datas[0],
            period=self.p.returns_period
        )
        
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
            
        returns = self.returns[0]
        
        if abs(returns) < self.p.returns_threshold:
            return

        if not self.position:
            # Mean reversion: short when overbought, long when oversold
            if returns < -self.p.returns_threshold:
                self.order = self.buy(size=self.p.stake)
            elif returns > self.p.returns_threshold:
                self.order = self.sell(size=self.p.stake)
        else:
            # Close position when returns revert to within threshold
            if self.position.size > 0 and returns > 0:
                self.order = self.close()
            elif self.position.size < 0 and returns < 0:
                self.order = self.close()


def test_up_down_candles_strategy():
    """Test the Up Down Candles strategy.

    This test function:
    1. Loads historical price data from a CSV file
    2. Runs the UpDownCandlesStrategy with default parameters
    3. Validates backtest results against expected values

    Raises:
        AssertionError: If any of the backtest metrics do not match expected values
            within the specified tolerance.
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
    cerebro.addstrategy(UpDownCandlesStrategy)
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
    print("Up Down Candles Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1218, f"Expected bar_num=1218, got {strat.bar_num}"
    assert abs(final_value - 99976.91) < 0.01, f"Expected final_value=99976.91, got {final_value}"
    assert abs(sharpe_ratio - (-0.11438879840513524)) < 1e-6, f"Expected sharpe_ratio=-0.11438879840513524, got {sharpe_ratio}"
    assert abs(annual_return - (-4.629057819258505e-05)) < 1e-12, f"Expected annual_return=-4.629057819258505e-05, got {annual_return}"
    assert abs(max_drawdown - 0.13256895983198377) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Up Down Candles Strategy Test")
    print("=" * 60)
    test_up_down_candles_strategy()
