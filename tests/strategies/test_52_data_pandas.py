#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Data Pandas 数据加载

参考来源: backtrader-master2/samples/data-pandas/data-pandas.py
测试从Pandas DataFrame加载数据
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import pandas as pd
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


class PandasTestStrategy(bt.Strategy):
    """测试Pandas数据加载的策略"""
    def __init__(self):
        self.bar_num = 0

    def next(self):
        self.bar_num += 1

    def stop(self):
        print(f"PandasTest: bar_num={self.bar_num}")


def test_data_pandas():
    """测试 Data Pandas 数据加载"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    
    # 读取CSV到DataFrame
    dataframe = pd.read_csv(
        str(data_path),
        header=0,
        parse_dates=True,
        index_col=0,
    )
    
    print(f"DataFrame shape: {dataframe.shape}")
    
    # 使用PandasData加载
    data = bt.feeds.PandasData(dataname=dataframe, nocase=True)
    cerebro.adddata(data)

    cerebro.addstrategy(PandasTestStrategy)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

    print("开始运行回测...")
    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Data Pandas 数据加载回测结果:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.bar_num > 0
    assert 40000 < final_value < 200000, f"Expected final_value=100000.00, got {final_value}"
    assert sharpe_ratio is None or -20 < sharpe_ratio < 20, f"sharpe_ratio={sharpe_ratio} out of range"
    assert -1 < annual_return < 1, f"annual_return={annual_return} out of range"
    assert 0 <= max_drawdown < 100, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Data Pandas 数据加载测试")
    print("=" * 60)
    test_data_pandas()
