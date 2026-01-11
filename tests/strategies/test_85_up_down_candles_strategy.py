#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Up Down Candles 上下蜡烛图策略

参考来源: https://github.com/backtrader-stuff/strategies
基于蜡烛图强度和收益率的均值回归策略
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


class UpDownCandleStrength(bt.Indicator):
    """上下蜡烛图强度指标
    
    计算一段时间内上涨/下跌蜡烛的比例
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
    """周期收益率指标"""
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
    """上下蜡烛图策略
    
    - 计算蜡烛图强度和周期收益率
    - 收益率为正且超过阈值时做空（均值回归）
    - 收益率为负且超过阈值时做多（均值回归）
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
            # 均值回归: 涨多了做空，跌多了做多
            if returns < -self.p.returns_threshold:
                self.order = self.buy(size=self.p.stake)
            elif returns > self.p.returns_threshold:
                self.order = self.sell(size=self.p.stake)
        else:
            # 收益率回归到阈值内时平仓
            if self.position.size > 0 and returns > 0:
                self.order = self.close()
            elif self.position.size < 0 and returns < 0:
                self.order = self.close()


def test_up_down_candles_strategy():
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
    print("Up Down Candles 上下蜡烛图策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 1218, f"Expected bar_num=1218, got {strat.bar_num}"
    assert abs(final_value - 99976.91) < 0.01, f"Expected final_value=99976.91, got {final_value}"
    assert abs(sharpe_ratio - (-0.11438879840513524)) < 1e-6, f"Expected sharpe_ratio=-0.11438879840513524, got {sharpe_ratio}"
    assert abs(annual_return - (-4.629057819258505e-05)) < 1e-12, f"Expected annual_return=-4.629057819258505e-05, got {annual_return}"
    assert abs(max_drawdown - 0.13256895983198377) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("Up Down Candles 上下蜡烛图策略测试")
    print("=" * 60)
    test_up_down_candles_strategy()
