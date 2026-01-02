#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Pairs Trading 配对交易策略

参考来源: https://github.com/arikaufman/algorithmicTrading
基于OLS变换和Z-Score进行配对交易
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt
import backtrader.indicators as btind
import math

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """根据脚本所在目录定位数据文件"""
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


class PairsTradingStrategy(bt.Strategy):
    """配对交易策略
    
    使用OLS变换计算两个资产之间的Z-Score
    当Z-Score超过上限时做空价差，当Z-Score低于下限时做多价差
    """
    params = dict(
        period=20,
        stake=10,
        qty1=0,
        qty2=0,
        upper=2.5,
        lower=-2.5,
        up_medium=0.5,
        low_medium=-0.5,
        status=0,
        portfolio_value=100000,
        stop_loss=3.0
    )

    def log(self, txt, dt=None):
        dt = dt or self.data.datetime[0]

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

        elif order.status in [order.Expired, order.Canceled, order.Margin]:
            pass

        self.orderid = None

    def __init__(self):
        self.orderid = None
        self.qty1 = self.p.qty1
        self.qty2 = self.p.qty2
        self.upper_limit = self.p.upper
        self.lower_limit = self.p.lower
        self.up_medium = self.p.up_medium
        self.low_medium = self.p.low_medium
        self.status = self.p.status
        self.portfolio_value = self.p.portfolio_value
        self.stop_loss = self.p.stop_loss

        # 统计变量
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

        self.sma1 = bt.indicators.SimpleMovingAverage(self.datas[0], period=50)
        self.sma2 = bt.indicators.SimpleMovingAverage(self.datas[1], period=50)
        
        # OLS变换计算Z-Score
        self.transform = btind.OLS_TransformationN(self.data0, self.data1,
                                                   period=self.p.period)
        self.zscore = self.transform.zscore

    def next(self):
        self.bar_num += 1
        x = 0
        y = 0
        if self.orderid:
            return

        # SHORT条件: zscore超过上限
        if (self.zscore[0] > self.upper_limit) and (self.status != 1):
            deviationOffSMA1 = math.fabs((self.data0.close[0]/self.sma1[0])-1)
            deviationOffSMA2 = math.fabs((self.data1.close[0]/self.sma2[0])-1)
            value1 = 0.6 * self.portfolio_value
            value2 = 0.4 * self.portfolio_value
            if deviationOffSMA1 > deviationOffSMA2:
                x = int(value1 / (self.data0.close))
                y = int(value2 / (self.data1.close))
            else:
                x = int(value2 / (self.data0.close))
                y = int(value1 / (self.data1.close))

            self.sell(data=self.data0, size=(x + self.qty1))
            self.buy(data=self.data1, size=(y + self.qty2))

            self.qty1 = x
            self.qty2 = y
            self.status = 1

        # LONG条件: zscore低于下限
        elif (self.zscore[0] < self.lower_limit) and (self.status != 2):
            deviationOffSMA1 = math.fabs((self.data0.close[0]/self.sma1[0])-1)
            deviationOffSMA2 = math.fabs((self.data1.close[0]/self.sma2[0])-1)
            value1 = 0.6 * self.portfolio_value
            value2 = 0.4 * self.portfolio_value
            if deviationOffSMA1 > deviationOffSMA2:
                x = int(value1 / (self.data0.close))
                y = int(value2 / (self.data1.close))
            else:
                x = int(value2 / (self.data0.close))
                y = int(value1 / (self.data1.close))

            self.buy(data=self.data0, size=(x + self.qty1))
            self.sell(data=self.data1, size=(y + self.qty2))

            self.qty1 = x
            self.qty2 = y
            self.status = 2

        # 平仓条件: zscore回归到均值附近
        elif ((self.zscore[0] < self.up_medium and self.zscore[0] > self.low_medium)):
            self.close(self.data0)
            self.close(self.data1)

    def stop(self):
        pass


def test_pairs_trading_strategy():
    """测试配对交易策略"""
    cerebro = bt.Cerebro()

    # 加载Visa数据
    data_path_v = resolve_data_path("V.csv")
    df_v = pd.read_csv(data_path_v, parse_dates=['Date'], index_col='Date')
    df_v = df_v[['Open', 'High', 'Low', 'Close', 'Volume']]
    df_v.columns = ['open', 'high', 'low', 'close', 'volume']
    
    # 加载Mastercard数据
    data_path_ma = resolve_data_path("MA.csv")
    df_ma = pd.read_csv(data_path_ma, parse_dates=['Date'], index_col='Date')
    df_ma = df_ma[['Open', 'High', 'Low', 'Close', 'Volume']]
    df_ma.columns = ['open', 'high', 'low', 'close', 'volume']

    # 对齐日期范围
    common_dates = df_v.index.intersection(df_ma.index)
    df_v = df_v.loc[common_dates]
    df_ma = df_ma.loc[common_dates]

    # 只使用部分数据以加快测试
    df_v = df_v.iloc[:500]
    df_ma = df_ma.iloc[:500]

    data_v = bt.feeds.PandasData(dataname=df_v, name='V')
    data_ma = bt.feeds.PandasData(dataname=df_ma, name='MA')

    cerebro.adddata(data_v)
    cerebro.adddata(data_ma)

    cerebro.addstrategy(PairsTradingStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    # 获取分析结果
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Pairs Trading 配对交易策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num > 0, "bar_num should be greater than 0"
    assert 40000 < final_value < 200000, f"Expected final_value=99699.43, got {final_value}"
    assert abs(sharpe_ratio - (-0.3156462969633222)) < 1e-6, f"Expected sharpe_ratio=-0.3156462969633222, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0015160238352949257)) < 1e-6, f"Expected annual_return=-0.0015160238352949257, got {annual_return}"
    assert 0 <= max_drawdown < 100, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Pairs Trading 配对交易策略测试")
    print("=" * 60)
    test_pairs_trading_strategy()
