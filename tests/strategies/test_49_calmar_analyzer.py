#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Calmar Analyzer.

Reference: backtrader-master2/samples/calmar/calmar-test.py
Tests the Calmar ratio analyzer.

Calmar ratio = Annualized return / Maximum drawdown
Used to measure risk-adjusted returns of a strategy.
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


class CalmarTestStrategy(bt.Strategy):
    """Strategy for testing the Calmar analyzer."""

    params = (('p1', 15), ('p2', 50))

    def __init__(self):
        ma1 = bt.ind.SMA(period=self.p.p1)
        ma2 = bt.ind.SMA(period=self.p.p2)
        self.crossover = bt.ind.CrossOver(ma1, ma2)
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
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()


def test_calmar_analyzer():
    """Test the Calmar Analyzer."""
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("yhoo-1996-2014.txt")
    data = bt.feeds.YahooFinanceCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2010, 12, 31)
    )
    cerebro.adddata(data)

    cerebro.addstrategy(CalmarTestStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=100)

    # Add analyzers - calculate Sharpe ratio using daily timeframe
    cerebro.addanalyzer(bt.analyzers.Calmar, _name="calmar")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    calmar_analysis = strat.analyzers.calmar.get_analysis()
    # Calmar returns OrderedDict, keys are dates, values are Calmar ratios for that period
    if calmar_analysis:
        last_date = list(calmar_analysis.keys())[-1]
        calmar_ratio = calmar_analysis[last_date]
    else:
        calmar_ratio = None

    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    drawdown = strat.analyzers.drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Print results in standard format
    print("\n" + "=" * 50)
    print("Calmar Analyzer Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  calmar_ratio: {calmar_ratio}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assert test results
    assert strat.bar_num == 1460, f"Expected bar_num=1460, got {strat.bar_num}"
    assert abs(final_value - 98020.00) < 0.01, f"Expected final_value=98020.00, got {final_value}"
    assert abs(sharpe_ratio - (-0.4689333841227036)) < 1e-6, f"Expected sharpe_ratio=-0.4689333841227036, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0033319591262466032)) < 1e-6, f"Expected annual_return=-0.0033319591262466032, got {annual_return}"
    assert abs(max_drawdown - 3.2398371164458886) < 1e-6, f"Expected max_drawdown=3.2398371164458886, got {max_drawdown}"
    assert total_trades == 16, f"Expected total_trades=16, got {total_trades}"
    # Calmar ratio assertions
    assert calmar_ratio is not None, "Calmar ratio should not be None"
    assert abs(calmar_ratio - (-4.713556837089328e-05)) < 1e-6, f"Expected calmar_ratio=-4.713556837089328e-05, got {calmar_ratio}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Calmar Analyzer Test")
    print("=" * 60)
    test_calmar_analyzer()
