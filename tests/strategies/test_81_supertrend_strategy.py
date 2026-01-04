#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Supertrend 超级趋势策略

参考来源: https://github.com/Backtesting/strategies
基于ATR的超级趋势指标策略
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


class SuperTrendIndicator(bt.Indicator):
    """超级趋势指标"""
    lines = ('supertrend', 'direction')
    params = dict(
        period=10,
        multiplier=3.0,
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.period)
        self.hl2 = (self.data.high + self.data.low) / 2.0

    def next(self):
        if len(self) < self.p.period + 1:
            self.lines.supertrend[0] = self.hl2[0]
            self.lines.direction[0] = 1
            return
            
        atr = self.atr[0]
        hl2 = self.hl2[0]
        
        upper_band = hl2 + self.p.multiplier * atr
        lower_band = hl2 - self.p.multiplier * atr
        
        prev_supertrend = self.lines.supertrend[-1]
        prev_direction = self.lines.direction[-1]
        
        # 上升趋势
        if prev_direction == 1:
            if self.data.close[0] < prev_supertrend:
                self.lines.supertrend[0] = upper_band
                self.lines.direction[0] = -1
            else:
                self.lines.supertrend[0] = max(lower_band, prev_supertrend)
                self.lines.direction[0] = 1
        # 下降趋势
        else:
            if self.data.close[0] > prev_supertrend:
                self.lines.supertrend[0] = lower_band
                self.lines.direction[0] = 1
            else:
                self.lines.supertrend[0] = min(upper_band, prev_supertrend)
                self.lines.direction[0] = -1


class SuperTrendStrategy(bt.Strategy):
    """超级趋势策略
    
    - 价格突破超级趋势线向上时买入
    - 价格跌破超级趋势线时卖出
    """
    params = dict(
        stake=10,
        period=10,
        multiplier=3.0,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.supertrend = SuperTrendIndicator(
            self.datas[0], 
            period=self.p.period, 
            multiplier=self.p.multiplier
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

        # 趋势转为上升时买入
        if not self.position:
            if self.supertrend.direction[0] == 1 and self.supertrend.direction[-1] == -1:
                self.order = self.buy(size=self.p.stake)
        else:
            # 趋势转为下降时卖出
            if self.supertrend.direction[0] == -1:
                self.order = self.sell(size=self.p.stake)


def test_supertrend_strategy():
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
    cerebro.addstrategy(SuperTrendStrategy)
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
    print("SuperTrend 超级趋势策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num == 1247, f"Expected bar_num=1247, got {strat.bar_num}"
    assert abs(final_value - 99999.23) < 0.01, f"Expected final_value=99999.23, got {final_value}"
    assert abs(sharpe_ratio - (-0.003753826957851812)) < 1e-6, f"Expected sharpe_ratio=-0.003753826957851812, got {sharpe_ratio}"
    assert abs(annual_return - (-1.5389488753206686e-06)) < 1e-6, f"Expected annual_return=-1.5389488753206686e-06, got {annual_return}"
    assert abs(max_drawdown - 0.11218870744432227) < 1e-6, f"Expected max_drawdown=0.11218870744432227, got {max_drawdown}"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("SuperTrend 超级趋势策略测试")
    print("=" * 60)
    test_supertrend_strategy()
