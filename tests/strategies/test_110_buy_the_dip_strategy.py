#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Buy The Dip 逢低买入策略

参考来源: backtrader-strategies-compendium/strategies/BuyTheDip.py
连续下跌后买入，持有N天后卖出
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


class BuyTheDipStrategy(bt.Strategy):
    """Buy The Dip 逢低买入策略
    
    入场条件:
    - 连续3天下跌
    
    出场条件:
    - 持有N天后卖出
    """
    params = dict(
        stake=10,
        hold_days=5,
        consecutive_down=3,
    )

    def __init__(self):
        self.order = None
        self.bar_executed = 0
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
            self.bar_executed = len(self)
        self.order = None

    def next(self):
        self.bar_num += 1
        
        if self.order:
            return
        
        if len(self) < self.p.consecutive_down + 1:
            return
        
        if not self.position:
            # 检查连续下跌
            all_down = True
            for i in range(self.p.consecutive_down):
                if self.data.close[-i] >= self.data.close[-i-1]:
                    all_down = False
                    break
            
            if all_down:
                self.order = self.buy(size=self.p.stake)
        else:
            # 持有N天后卖出
            if len(self) >= self.bar_executed + self.p.hold_days:
                self.order = self.close()


def test_buy_the_dip_strategy():
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
    cerebro.addstrategy(BuyTheDipStrategy)
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
    print("Buy The Dip 逢低买入策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # 断言 - 使用精确断言
    # final_value 容差: 0.01, 其他指标容差: 1e-6
    assert strat.bar_num == 1257, f"Expected bar_num=1257, got {strat.bar_num}"
    assert abs(final_value - 100151.25) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (1.0281051590758732)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.0003030289116772613)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.049493103885201756) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\n测试通过!")



if __name__ == "__main__":
    print("=" * 60)
    print("Buy The Dip 逢低买入策略测试")
    print("=" * 60)
    test_buy_the_dip_strategy()
