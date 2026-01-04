#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试用例: Optimization 参数优化

参考来源: backtrader-master2/samples/optimization/optimization.py
测试策略参数优化功能，返回夏普率最大的参数组合
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


class OptimizeStrategy(bt.Strategy):
    """用于参数优化的策略"""
    params = (
        ('smaperiod', 15),
        ('macdperiod1', 12),
        ('macdperiod2', 26),
        ('macdperiod3', 9),
    )

    def __init__(self):
        self.sma = bt.ind.SMA(period=self.p.smaperiod)
        self.macd = bt.ind.MACD(
            period_me1=self.p.macdperiod1,
            period_me2=self.p.macdperiod2,
            period_signal=self.p.macdperiod3
        )
        self.crossover = bt.ind.CrossOver(self.macd.macd, self.macd.signal)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        if not order.alive():
            self.order = None
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def next(self):
        self.bar_num += 1
        if self.order:
            return
        if self.crossover > 0:
            if not self.position:
                self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()


def run_optimization():
    """运行参数优化，返回所有结果"""
    cerebro = bt.Cerebro(maxcpus=1)
    cerebro.broker.setcash(100000.0)

    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    # 使用小范围参数优化以加快测试速度
    cerebro.optstrategy(
        OptimizeStrategy,
        smaperiod=range(10, 13),  # 3个值: 10, 11, 12
        macdperiod1=[12],
        macdperiod2=[26],
        macdperiod3=[9],
    )

    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)

    results = cerebro.run()
    return results


def run_best_strategy(best_params):
    """使用最佳参数运行完整回测"""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    # 使用最佳参数
    cerebro.addstrategy(OptimizeStrategy, **best_params)

    # 添加完整分析器
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    results = cerebro.run()
    strat = results[0]

    # 获取分析结果
    ret = strat.analyzers.returns.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    return {
        'strat': strat,
        'bar_num': strat.bar_num,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'sharpe_ratio': sharpe.get('sharperatio', None),
        'annual_return': ret.get('rnorm', 0),
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'total_trades': trades.get('total', {}).get('total', 0),
        'final_value': cerebro.broker.getvalue(),
    }


def test_optimization():
    """测试 Optimization 参数优化"""
    print("正在加载数据...")
    print("开始运行优化...")
    results = run_optimization()

    # 收集所有参数组合的结果
    all_results = []
    for stratrun in results:
        for strat in stratrun:
            params = strat.p._getkwargs()
            ret = strat.analyzers.returns.get_analysis()
            sharpe = strat.analyzers.sharpe.get_analysis()

            sharpe_ratio = sharpe.get('sharperatio', None)
            annual_return = ret.get('rnorm', 0)

            all_results.append({
                'smaperiod': params.get('smaperiod'),
                'sharpe_ratio': sharpe_ratio,
                'annual_return': annual_return,
            })

    # 打印所有优化结果
    print("\n" + "=" * 50)
    print("参数优化结果:")
    for r in all_results:
        print(f"  smaperiod={r['smaperiod']}: sharpe_ratio={r['sharpe_ratio']}, annual_return={r['annual_return']}")
    print(f"  优化组合数: {len(all_results)}")
    print("=" * 50)

    # 找到夏普率最大的参数组合
    best_result = max(all_results, key=lambda x: x['sharpe_ratio'] or -999)
    best_params = {'smaperiod': best_result['smaperiod']}

    print(f"\n最佳参数组合: {best_params}")
    print(f"  夏普率: {best_result['sharpe_ratio']}")
    print(f"  年化收益: {best_result['annual_return']}")

    # 使用最佳参数运行完整回测
    print("\n使用最佳参数运行完整回测...")
    best_metrics = run_best_strategy(best_params)

    # 打印最佳策略的完整指标
    print("\n" + "=" * 50)
    print("最佳策略回测结果:")
    print(f"  params: smaperiod={best_params['smaperiod']}")
    print(f"  bar_num: {best_metrics['bar_num']}")
    print(f"  buy_count: {best_metrics['buy_count']}")
    print(f"  sell_count: {best_metrics['sell_count']}")
    print(f"  total_trades: {best_metrics['total_trades']}")
    print(f"  sharpe_ratio: {best_metrics['sharpe_ratio']}")
    print(f"  annual_return: {best_metrics['annual_return']}")
    print(f"  max_drawdown: {best_metrics['max_drawdown']}")
    print(f"  final_value: {best_metrics['final_value']:.2f}")
    print("=" * 50)

    # 断言测试结果
    assert len(all_results) == 3, f"Expected 3 optimization runs, got {len(all_results)}"

    # 验证最佳策略指标
    assert best_metrics['bar_num'] == 221, f"Expected bar_num=221, got {best_metrics['bar_num']}"
    assert abs(best_metrics['final_value'] - 100150.06) < 0.01, f"Expected final_value=100150.06, got {best_metrics['final_value']}"
    assert abs(best_metrics['sharpe_ratio'] - 0.4979380802957602) < 1e-6, f"Expected sharpe_ratio=0.4979380802957602, got {best_metrics['sharpe_ratio']}"
    assert abs(best_metrics['annual_return'] - 0.0014829327989227066) < 1e-6, f"Expected annual_return=0.0014829327989227066, got {best_metrics['annual_return']}"
    assert abs(best_metrics['max_drawdown'] - 0.2686681581344764) < 1e-6, f"Expected max_drawdown=0.2686681581344764, got {best_metrics['max_drawdown']}"
    assert best_metrics['total_trades'] == 10, f"Expected total_trades=10, got {best_metrics['total_trades']}"

    # 验证最佳参数是 smaperiod=10
    assert best_params['smaperiod'] == 10, f"Expected best smaperiod=10, got {best_params['smaperiod']}"

    print("\n测试通过!")


if __name__ == "__main__":
    print("=" * 60)
    print("Optimization 参数优化测试")
    print("=" * 60)
    test_optimization()
