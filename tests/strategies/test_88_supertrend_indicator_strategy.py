#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: SuperTrend Indicator 超级趋势指标策略

参考来源: https://github.com/Backtrader1.0/strategies/supertrend.py
使用带有trend line的SuperTrend指标进行交易
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
    """SuperTrend指标
    
    计算上轨和下轨，根据价格与轨道的关系确定趋势方向
    """
    lines = ('st', 'final_up', 'final_dn', 'trend')
    params = dict(period=20, multiplier=3.0)

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.period)
        hl2 = (self.data.high + self.data.low) / 2.0
        self.basic_up = hl2 + self.p.multiplier * self.atr
        self.basic_dn = hl2 - self.p.multiplier * self.atr
        self.addminperiod(self.p.period + 1)

    def next(self):
        if len(self) == self.p.period + 1:
            self.final_up[0] = self.basic_up[0]
            self.final_dn[0] = self.basic_dn[0]
            self.trend[0] = 1
            self.st[0] = self.basic_dn[0]
            return

        prev_fu = self.final_up[-1]
        prev_fd = self.final_dn[-1]

        # 更新上轨
        if self.basic_up[0] < prev_fu or self.data.close[-1] > prev_fu:
            self.final_up[0] = self.basic_up[0]
        else:
            self.final_up[0] = prev_fu

        # 更新下轨
        if self.basic_dn[0] > prev_fd or self.data.close[-1] < prev_fd:
            self.final_dn[0] = self.basic_dn[0]
        else:
            self.final_dn[0] = prev_fd

        # 确定趋势方向
        if self.data.close[0] > self.final_up[-1]:
            self.trend[0] = 1
        elif self.data.close[0] < self.final_dn[-1]:
            self.trend[0] = -1
        else:
            self.trend[0] = self.trend[-1]

        # 设置SuperTrend线
        self.st[0] = self.final_dn[0] if self.trend[0] > 0 else self.final_up[0]


class SuperTrendIndicatorStrategy(bt.Strategy):
    """SuperTrend指标策略
    
    入场条件:
    - 多头: 价格从下方突破SuperTrend线
    - 空头: 价格从上方跌破SuperTrend线
    """
    params = dict(
        stake=10,
        st_period=20,
        st_mult=3.0,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        
        # SuperTrend指标
        self.st = SuperTrendIndicator(
            self.data,
            period=self.p.st_period,
            multiplier=self.p.st_mult
        )
        
        # ATR
        self.atr = bt.indicators.ATR(self.data, period=14)
        
        self.order = None
        self.prev_up = None  # price > st on previous bar
        
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

        price = float(self.data.close[0])
        st_val = float(self.st.st[0])
        up_now = price > st_val

        if self.prev_up is None:
            self.prev_up = up_now
            return

        # 多头入场: 价格从下方突破ST线
        if up_now and not self.prev_up:
            if not self.position:
                self.order = self.buy(size=self.p.stake)
            elif self.position.size < 0:
                self.order = self.close()

        # 空头/平仓: 价格从上方跌破ST线
        elif not up_now and self.prev_up:
            if self.position.size > 0:
                self.order = self.close()

        self.prev_up = up_now


def test_supertrend_indicator_strategy():
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
    cerebro.addstrategy(SuperTrendIndicatorStrategy)
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
    print("SuperTrend Indicator 超级趋势指标策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 1237, f"Expected bar_num=1237, got {strat.bar_num}"
    assert abs(final_value - 99977.89) < 0.01, f"Expected final_value=99977.89, got {final_value}"
    assert abs(sharpe_ratio - (-0.09158071580164015)) < 1e-6, f"Expected sharpe_ratio=-0.09158071580164015, got {sharpe_ratio}"
    assert abs(annual_return - (-4.432414175552991e-05)) < 1e-6, f"Expected annual_return=-4.432414175552991e-05, got {annual_return}"
    assert abs(max_drawdown - 0.16618133797700763) < 1e-6, f"Expected max_drawdown=0.16618133797700763, got {max_drawdown}"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("SuperTrend Indicator 超级趋势指标策略测试")
    print("=" * 60)
    test_supertrend_indicator_strategy()
