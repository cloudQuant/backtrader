#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test cases for parameter optimization.

Reference: backtrader-master2/samples/optimization/optimization.py
Tests strategy parameter optimization functionality, returns the parameter
combination with the maximum Sharpe ratio.
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
    """Strategy for parameter optimization."""
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
    """Run parameter optimization and return all results."""
    cerebro = bt.Cerebro(maxcpus=1)
    cerebro.broker.setcash(100000.0)

    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    # Use small parameter range to speed up testing
    cerebro.optstrategy(
        OptimizeStrategy,
        smaperiod=range(10, 13),  # 3 values: 10, 11, 12
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
    """Run complete backtest using the best parameters.

    Args:
        best_params: Dictionary containing the optimal parameter values.

    Returns:
        Dictionary containing strategy metrics including Sharpe ratio,
        annual return, max drawdown, and final portfolio value.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data)

    # Use the best parameters
    cerebro.addstrategy(OptimizeStrategy, **best_params)

    # Add complete analyzers
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    results = cerebro.run()
    strat = results[0]

    # Get analysis results
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
    """Test Optimization parameter optimization.

    Tests strategy parameter optimization by running multiple backtests
    with different parameter combinations and selecting the one with
    the highest Sharpe ratio.
    """
    print("Loading data...")
    print("Starting optimization...")
    results = run_optimization()

    # Collect results from all parameter combinations
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

    # Print all optimization results
    print("\n" + "=" * 50)
    print("Parameter optimization results:")
    for r in all_results:
        print(f"  smaperiod={r['smaperiod']}: sharpe_ratio={r['sharpe_ratio']}, annual_return={r['annual_return']}")
    print(f"  Number of combinations: {len(all_results)}")
    print("=" * 50)

    # Find parameter combination with maximum Sharpe ratio
    best_result = max(all_results, key=lambda x: x['sharpe_ratio'] or -999)
    best_params = {'smaperiod': best_result['smaperiod']}

    print(f"\nBest parameter combination: {best_params}")
    print(f"  Sharpe ratio: {best_result['sharpe_ratio']}")
    print(f"  Annual return: {best_result['annual_return']}")

    # Run complete backtest with best parameters
    print("\nRunning complete backtest with best parameters...")
    best_metrics = run_best_strategy(best_params)

    # Print complete metrics for best strategy
    print("\n" + "=" * 50)
    print("Best strategy backtest results:")
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

    # Assert test results
    assert len(all_results) == 3, f"Expected 3 optimization runs, got {len(all_results)}"

    # Verify best strategy metrics
    assert best_metrics['bar_num'] == 221, f"Expected bar_num=221, got {best_metrics['bar_num']}"
    assert abs(best_metrics['final_value'] - 100150.06) < 0.01, f"Expected final_value=100150.06, got {best_metrics['final_value']}"
    assert abs(best_metrics['sharpe_ratio'] - 0.4979380802957602) < 1e-6, f"Expected sharpe_ratio=0.4979380802957602, got {best_metrics['sharpe_ratio']}"
    assert abs(best_metrics['annual_return'] - 0.0014829327989227066) < 1e-6, f"Expected annual_return=0.0014829327989227066, got {best_metrics['annual_return']}"
    assert abs(best_metrics['max_drawdown'] - 0.2686681581344764) < 1e-6, f"Expected max_drawdown=0.2686681581344764, got {best_metrics['max_drawdown']}"
    assert best_metrics['total_trades'] == 10, f"Expected total_trades=10, got {best_metrics['total_trades']}"

    # Verify best parameter is smaperiod=10
    assert best_params['smaperiod'] == 10, f"Expected best smaperiod=10, got {best_params['smaperiod']}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Optimization Parameter Optimization Test")
    print("=" * 60)
    test_optimization()
