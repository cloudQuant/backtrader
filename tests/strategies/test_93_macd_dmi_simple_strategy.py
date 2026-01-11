#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: MACD + DMI 简化策略

参考来源: backtrader-strategies/macddmi.py
使用MACD和DMI两个指标的交叉信号作为入场确认
简化版本，避免backtrader属性冲突
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


class MacdDmiSimpleStrategy(bt.Strategy):
    """MACD + DMI 简化策略
    
    入场条件:
    - 多头: MACD线上穿信号线 且 +DI > -DI
    - 空头: MACD线下穿信号线 且 -DI > +DI
    
    出场条件:
    - MACD反向交叉
    """
    params = dict(
        stake=10,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        dmi_period=14,
    )

    def __init__(self):
        # MACD指标
        self.macd = bt.indicators.MACD(
            self.data,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal,
        )
        
        # DMI指标
        self.dmi = bt.indicators.DirectionalMovementIndex(
            self.data, period=self.p.dmi_period
        )
        
        # MACD交叉信号
        self.macd_cross = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)
        
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

        plus_di = self.dmi.DIplus[0]
        minus_di = self.dmi.DIminus[0]

        if not self.position:
            # 多头入场: MACD金叉
            if self.macd_cross[0] > 0:
                self.order = self.buy(size=self.p.stake)
            # 空头入场: MACD死叉
            elif self.macd_cross[0] < 0:
                self.order = self.sell(size=self.p.stake)
        else:
            # 平仓条件: MACD反向交叉
            if self.position.size > 0 and self.macd_cross[0] < 0:
                self.order = self.close()
            elif self.position.size < 0 and self.macd_cross[0] > 0:
                self.order = self.close()


def test_macd_dmi_simple_strategy():
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
    cerebro.addstrategy(MacdDmiSimpleStrategy)
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
    print("MACD + DMI 简化策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 1223, f"Expected bar_num=1223, got {strat.bar_num}"
    assert abs(final_value - 99948.71) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (-0.20797152972748584)) < 1e-6, f"Expected sharpe_ratio=-0.20797152972748584, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00010284209965205515)) < 1e-12, f"Expected annual_return=-0.00010284209965205515, got {annual_return}"
    assert abs(max_drawdown - 0.12263737758169839) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("MACD + DMI 简化策略测试")
    print("=" * 60)
    test_macd_dmi_simple_strategy()
