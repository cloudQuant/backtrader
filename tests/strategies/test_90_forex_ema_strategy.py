#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Forex EMA 三均线策略

参考来源: backtrader-strategies/forexema.py
使用短期、中期、长期EMA的排列和交叉作为入场信号
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


class ForexEmaStrategy(bt.Strategy):
    """Forex EMA 三均线策略
    
    入场条件:
    - 多头: 短期EMA上穿中期EMA，且价格低点>长期EMA，且短期>中期>长期
    - 空头: 短期EMA下穿中期EMA，且价格高点<长期EMA，且短期<中期<长期
    
    出场条件:
    - 反向交叉信号
    """
    params = dict(
        stake=10,
        shortema=5,
        mediumema=20,
        longema=50,
    )

    def __init__(self):
        self.shortema = bt.indicators.ExponentialMovingAverage(
            self.data, period=self.p.shortema
        )
        self.mediumema = bt.indicators.ExponentialMovingAverage(
            self.data, period=self.p.mediumema
        )
        self.longema = bt.indicators.ExponentialMovingAverage(
            self.data, period=self.p.longema
        )
        
        self.shortemacrossover = bt.indicators.CrossOver(self.shortema, self.mediumema)
        
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
            # 多头入场条件
            if (self.shortemacrossover > 0 and 
                self.data.low[0] > self.longema[0] and 
                self.mediumema[0] > self.longema[0] and 
                self.shortema[0] > self.longema[0]):
                self.order = self.buy(size=self.p.stake)
            # 空头入场条件
            elif (self.shortemacrossover < 0 and 
                  self.data.high[0] < self.longema[0] and 
                  self.mediumema[0] < self.longema[0] and 
                  self.shortema[0] < self.longema[0]):
                self.order = self.sell(size=self.p.stake)
        else:
            # 平仓条件: 反向交叉
            if self.position.size > 0 and self.shortemacrossover < 0:
                self.order = self.close()
            elif self.position.size < 0 and self.shortemacrossover > 0:
                self.order = self.close()


def test_forex_ema_strategy():
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
    cerebro.addstrategy(ForexEmaStrategy)
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
    print("Forex EMA 三均线策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 1208, f"Expected bar_num=1208, got {strat.bar_num}"
    assert abs(final_value - 99898.69) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (-0.6859889019155611)) < 1e-6, f"Expected sharpe_ratio=-0.6859889019155611, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00020318349900697326)) < 1e-12, f"Expected annual_return=-0.00020318349900697326, got {annual_return}"
    assert abs(max_drawdown - 0.15891968567586484) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("Forex EMA 三均线策略测试")
    print("=" * 60)
    test_forex_ema_strategy()
