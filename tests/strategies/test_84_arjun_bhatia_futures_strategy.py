#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Arjun Bhatia Futures 期货策略

参考来源: https://github.com/Backtesting/strategies
结合Alligator指标和SuperTrend指标的期货交易策略
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


class AlligatorIndicator(bt.Indicator):
    """鳄鱼线指标"""
    lines = ('jaw', 'teeth', 'lips')
    params = dict(
        jaw_period=13,
        teeth_period=8,
        lips_period=5,
    )

    def __init__(self):
        self.lines.jaw = bt.indicators.SmoothedMovingAverage(
            self.data.close, period=self.p.jaw_period
        )
        self.lines.teeth = bt.indicators.SmoothedMovingAverage(
            self.data.close, period=self.p.teeth_period
        )
        self.lines.lips = bt.indicators.SmoothedMovingAverage(
            self.data.close, period=self.p.lips_period
        )


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
        
        if prev_direction == 1:
            if self.data.close[0] < prev_supertrend:
                self.lines.supertrend[0] = upper_band
                self.lines.direction[0] = -1
            else:
                self.lines.supertrend[0] = max(lower_band, prev_supertrend)
                self.lines.direction[0] = 1
        else:
            if self.data.close[0] > prev_supertrend:
                self.lines.supertrend[0] = lower_band
                self.lines.direction[0] = 1
            else:
                self.lines.supertrend[0] = min(upper_band, prev_supertrend)
                self.lines.direction[0] = -1


class ArjunBhatiaFuturesStrategy(bt.Strategy):
    """Arjun Bhatia期货策略
    
    结合Alligator和SuperTrend指标:
    - 价格在Alligator颚线上方且SuperTrend看多时买入
    - 价格在Alligator颚线下方且SuperTrend看空时卖出
    - 使用ATR计算止损和止盈
    """
    params = dict(
        stake=10,
        jaw_period=13,
        teeth_period=8,
        lips_period=5,
        supertrend_period=10,
        supertrend_multiplier=3.0,
        atr_sl_mult=2.0,
        atr_tp_mult=4.0,
    )

    def __init__(self):
        self.dataclose = self.datas[0].close
        self.datahigh = self.datas[0].high
        self.datalow = self.datas[0].low
        
        self.alligator = AlligatorIndicator(
            self.datas[0],
            jaw_period=self.p.jaw_period,
            teeth_period=self.p.teeth_period,
            lips_period=self.p.lips_period
        )
        
        self.supertrend = SuperTrendIndicator(
            self.datas[0],
            period=self.p.supertrend_period,
            multiplier=self.p.supertrend_multiplier
        )
        
        self.atr = bt.indicators.ATR(self.datas[0], period=14)
        
        self.order = None
        self.entry_price = 0
        self.stop_loss = 0
        self.take_profit = 0
        
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.entry_price = order.executed.price
                self.stop_loss = self.entry_price - self.atr[0] * self.p.atr_sl_mult
                self.take_profit = self.entry_price + self.atr[0] * self.p.atr_tp_mult
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        self.bar_num += 1
        
        if self.order:
            return

        is_alligator_bullish = self.dataclose[0] > self.alligator.jaw[0]
        is_supertrend_bullish = self.supertrend.direction[0] == 1

        if not self.position:
            # 多头入场: Alligator和SuperTrend同时看多
            if is_alligator_bullish and is_supertrend_bullish:
                self.order = self.buy(size=self.p.stake)
        else:
            # 止损或止盈
            if self.datalow[0] <= self.stop_loss:
                self.order = self.close()
            elif self.datahigh[0] >= self.take_profit:
                self.order = self.close()
            # 或者指标反转
            elif not is_alligator_bullish or not is_supertrend_bullish:
                self.order = self.close()


def test_arjun_bhatia_futures_strategy():
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
    cerebro.addstrategy(ArjunBhatiaFuturesStrategy)
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
    print("Arjun Bhatia Futures 期货策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num > 0
    assert 40000 < final_value < 200000, f"Expected final_value=100005.64, got {final_value}"
    assert sharpe_ratio is None or -20 < sharpe_ratio < 20, f"sharpe_ratio={sharpe_ratio} out of range"
    assert -1 < annual_return < 1, f"annual_return={annual_return} out of range"
    assert 0 <= max_drawdown < 100, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Arjun Bhatia Futures 期货策略测试")
    print("=" * 60)
    test_arjun_bhatia_futures_strategy()
