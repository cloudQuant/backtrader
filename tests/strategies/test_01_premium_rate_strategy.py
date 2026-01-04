#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
可转债溢价率均线交叉策略测试

使用转股溢价率计算移动平均线，短期均线上穿长期均线时买入，
下穿时卖出平仓。
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt
from backtrader.comminfo import ComminfoFuturesPercent

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """根据脚本所在目录定位数据文件，避免相对路径读取失败"""
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR.parent / "datas" / filename,
    ]

    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"未找到数据文件: {filename}")


class ExtendPandasFeed(bt.feeds.PandasData):
    """扩展的Pandas数据源，添加可转债特有的字段

    DataFrame结构（set_index后）：
    - 索引：datetime
    - 列0：open, 列1：high, 列2：low, 列3：close, 列4：volume
    - 列5：pure_bond_value, 列6：convert_value
    - 列7：pure_bond_premium_rate, 列8：convert_premium_rate
    """

    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', -1),
        ('pure_bond_value', 5),
        ('convert_value', 6),
        ('pure_bond_premium_rate', 7),
        ('convert_premium_rate', 8)
    )

    lines = ('pure_bond_value', 'convert_value',
             'pure_bond_premium_rate', 'convert_premium_rate')


class PremiumRateCrossoverStrategy(bt.Strategy):
    """转股溢价率均线交叉策略

    策略逻辑：
    - 使用转股溢价率（convert_premium_rate）计算移动平均线
    - 短期均线（默认10日）上穿长期均线（默认60日）时买入
    - 短期均线下穿长期均线时卖出平仓
    """

    params = (
        ('short_period', 10),
        ('long_period', 60),
    )

    def __init__(self):
        self.premium_rate = self.datas[0].convert_premium_rate
        self.sma_short = bt.indicators.SimpleMovingAverage(
            self.premium_rate, period=self.p.short_period
        )
        self.sma_long = bt.indicators.SimpleMovingAverage(
            self.premium_rate, period=self.p.long_period
        )
        self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
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
            if self.crossover > 0:
                cash = self.broker.getcash()
                size = int((cash * 0.95) / self.datas[0].close[0])
                self.order = self.buy(size=size)
        else:
            if self.crossover < 0:
                self.order = self.close()


def load_bond_data(csv_file: str) -> pd.DataFrame:
    """加载可转债数据

    Args:
        csv_file: CSV文件路径

    Returns:
        处理后的DataFrame
    """
    df = pd.read_csv(csv_file)
    df.columns = ['BOND_CODE', 'BOND_SYMBOL', 'datetime', 'open', 'high', 'low',
                  'close', 'volume', 'pure_bond_value', 'convert_value',
                  'pure_bond_premium_rate', 'convert_premium_rate']

    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime')
    df = df.drop(['BOND_CODE', 'BOND_SYMBOL'], axis=1)
    df = df.dropna()
    df = df.astype(float)

    return df


def test_premium_rate_strategy():
    """测试可转债溢价率均线交叉策略

    使用113013.csv数据进行回测，验证策略指标是否符合预期
    """
    cerebro = bt.Cerebro()

    # 加载数据
    print("正在加载可转债数据...")
    data_path = resolve_data_path("113013.csv")
    df = load_bond_data(str(data_path))
    print(f"数据范围: {df.index[0]} 至 {df.index[-1]}, 共 {len(df)} 条")

    data = ExtendPandasFeed(dataname=df)
    cerebro.adddata(data)

    # 设置初始资金和手续费
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0003)

    # 添加策略
    cerebro.addstrategy(PremiumRateCrossoverStrategy)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # 运行回测
    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]

    # 获取分析结果
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio')
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm100')
    max_drawdown = strat.analyzers.drawdown.get_analysis()['max']['drawdown']
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # 打印结果
    print("\n" + "=" * 50)
    print("可转债溢价率均线交叉策略回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # 断言测试结果（基于113013.csv完整数据）
    assert strat.bar_num == 1384, f"Expected bar_num=1384, got {strat.bar_num}"
    assert abs(final_value - 104275.87) < 0.01, \
        f"Expected final_value=104275.87, got {final_value}"
    assert sharpe_ratio is not None, "夏普比率不应为None"
    assert abs(sharpe_ratio - 0.11457095300469224) < 1e-6, \
        f"Expected sharpe_ratio=0.11457095300469224, got {sharpe_ratio}"
    assert abs(annual_return - 0.733367887488441) < 1e-6, \
        f"Expected annual_return=0.733367887488441, got {annual_return}"
    assert abs(max_drawdown - 17.413029757464745) < 1e-6, \
        f"Expected max_drawdown=17.413, got {max_drawdown}"
    assert total_trades == 21, f"Expected total_trades=21, got {total_trades}"

    print("\n所有测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("可转债溢价率均线交叉策略测试")
    print("=" * 60)
    test_premium_rate_strategy()
