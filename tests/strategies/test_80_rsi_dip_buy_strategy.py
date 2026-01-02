#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: RSI Dip Buy RSI逢低买入策略

参考来源: https://github.com/Backtesting/strategies
RSI上穿50时买入，RSI下穿或止盈止损时卖出
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


class RSIDipBuyStrategy(bt.Strategy):
    """RSI逢低买入策略
    
    - RSI从下方上穿50时买入
    - RSI回落到45以下或触及止盈/止损时卖出
    """
    params = dict(
        stake=10,
        rsi_period=10,
        rsi_buy=50,
        rsi_sell=45,
        stop_loss=0.005,
        take_profit=0.005,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.order = None
        self.buy_price = 0
        
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.buy_price = order.executed.price
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        self.bar_num += 1
        if self.order:
            return

        if not self.position:
            # RSI从下方上穿50时买入
            if self.rsi[-1] <= self.p.rsi_buy and self.rsi[0] > self.p.rsi_buy:
                self.order = self.buy(size=self.p.stake)
        else:
            # 止损、止盈或RSI回落时卖出
            stop_loss_hit = self.dataclose[0] < self.buy_price * (1 - self.p.stop_loss)
            take_profit_hit = self.dataclose[0] > self.buy_price * (1 + self.p.take_profit)
            rsi_exit = self.rsi[0] < self.p.rsi_sell
            
            if stop_loss_hit or take_profit_hit or rsi_exit:
                self.order = self.sell(size=self.p.stake)


def test_rsi_dip_buy_strategy():
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
    cerebro.addstrategy(RSIDipBuyStrategy)
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
    print("RSI Dip Buy RSI逢低买入策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num > 0
    assert 40000 < final_value < 200000, f"Expected final_value=99893.93, got {final_value}"
    assert abs(sharpe_ratio - (-0.6332718772573606)) < 1e-6, f"Expected sharpe_ratio=-0.6332718772573606, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00021274294674960664)) < 1e-9, f"Expected annual_return=-0.00021274294674960664, got {annual_return}"
    assert 0 <= max_drawdown < 100, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("RSI Dip Buy RSI逢低买入策略测试")
    print("=" * 60)
    test_rsi_dip_buy_strategy()
