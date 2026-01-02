#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Data Replay 数据回放

参考来源: backtrader-master2/samples/data-replay/data-replay.py
测试数据回放功能
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


class ReplayTestStrategy(bt.Strategy):
    """测试数据回放的策略"""
    params = (('period', 10),)

    def __init__(self):
        self.sma = bt.ind.SMA(self.data, period=self.p.period)
        self.counter = 0

    def next(self):
        self.counter += 1

    def stop(self):
        print(f"ReplayTest: counter={self.counter}")


def test_data_replay():
    """测试 Data Replay 数据回放"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("正在加载数据...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))

    # 使用回放功能，将日线回放为周线
    cerebro.replaydata(
        data,
        timeframe=bt.TimeFrame.Weeks,
        compression=1
    )

    cerebro.addstrategy(ReplayTestStrategy, period=5)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

    print("开始运行回测...")
    results = cerebro.run(preload=False)
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Data Replay 数据回放回测结果:")
    print(f"  counter: {strat.counter}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    assert strat.counter > 0
    assert 40000 < final_value < 200000, f"Expected final_value=100000.00, got {final_value}"
    assert sharpe_ratio is None or -20 < sharpe_ratio < 20, f"sharpe_ratio={sharpe_ratio} out of range"
    assert -1 < annual_return < 1, f"annual_return={annual_return} out of range"
    assert 0 <= max_drawdown < 100, f"max_drawdown={max_drawdown} out of range"

    print("\n测试通过!")
    return strat


if __name__ == "__main__":
    print("=" * 60)
    print("Data Replay 数据回放测试")
    print("=" * 60)
    test_data_replay()
