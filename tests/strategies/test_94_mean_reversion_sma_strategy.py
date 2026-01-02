#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Mean Reversion SMA 均值回归策略

参考来源: backtrader-strategies-compendium/strategies/MeanReversion.py
当价格跌破SMA一定比例时买入，回归SMA时卖出
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import math
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


class MeanReversionSmaStrategy(bt.Strategy):
    """均值回归SMA策略
    
    入场条件:
    - 价格跌破SMA超过dip_size比例时买入
    
    出场条件:
    - 价格回归到SMA以上时卖出
    """
    params = dict(
        period=20,
        order_percentage=0.95,
        dip_size=0.025,
    )

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
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
            # 价格跌破SMA超过dip_size比例
            dip_ratio = (self.data.close[0] / self.sma[0]) - 1
            if dip_ratio <= -self.p.dip_size:
                amount = self.p.order_percentage * self.broker.cash
                size = math.floor(amount / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            # 价格回归SMA
            if self.data.close[0] >= self.sma[0]:
                self.order = self.close()


def test_mean_reversion_sma_strategy():
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
    cerebro.addstrategy(MeanReversionSmaStrategy)
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
    print("Mean Reversion SMA 均值回归策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num > 0
    assert 90000 < final_value < 200000, f"final_value={final_value} out of range"
    assert sharpe_ratio is None or -20 < sharpe_ratio < 20, f"sharpe_ratio={sharpe_ratio} out of range"
    assert -1 < annual_return < 1, f"annual_return={annual_return} out of range"
    assert 0 <= max_drawdown < 100, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Mean Reversion SMA 均值回归策略测试")
    print("=" * 60)
    test_mean_reversion_sma_strategy()
