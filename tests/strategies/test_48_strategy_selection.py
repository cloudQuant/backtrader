#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case for Strategy Selection.

Reference: backtrader-master2/samples/strategy-selection/strategy-selection.py
Demonstrates how to select different strategies at runtime.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching in common locations.

    This function searches for a data file in several standard locations
    relative to the test directory, including the current directory,
    parent directory, and 'datas' subdirectories.

    Args:
        filename: The name of the data file to locate.

    Returns:
        The resolved Path object pointing to the data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of
            the search paths.
    """
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


class StrategyA(bt.Strategy):
    """Strategy A: Dual Moving Average Crossover.

    This strategy generates buy/sell signals when two simple moving
    averages cross each other.
    """
    params = (('p1', 10), ('p2', 30))

    def __init__(self):
        """Initialize the StrategyA indicators and state variables.

        Sets up two Simple Moving Average (SMA) indicators with periods
        defined by p1 and p2 parameters, and creates a crossover indicator
        to detect when the fast SMA crosses the slow SMA. Also initializes
        tracking variables for orders, bars, and trade counts.
        """
        sma1 = bt.ind.SMA(period=self.p.p1)
        sma2 = bt.ind.SMA(period=self.p.p2)
        self.crossover = bt.ind.CrossOver(sma1, sma2)
        self.order = None

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track completed trades.

        Updates the buy/sell counters when orders are completed and
        clears the order reference when the order is no longer alive.

        Args:
            order: The order object with status information.
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        if not order.alive():
            self.order = None

    def next(self):
        """Execute trading logic for each bar.

        Implements the dual moving average crossover strategy:
        - Buy when fast SMA crosses above slow SMA
        - Sell (close position) when fast SMA crosses below slow SMA
        - Only one active order at a time
        """
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


class StrategyB(bt.Strategy):
    """Strategy B: Price and Moving Average Crossover.

    This strategy generates buy/sell signals when the price crosses
    above or below a simple moving average.
    """
    params = (('period', 10),)

    def __init__(self):
        """Initialize the StrategyB indicators and state variables.

        Sets up a Simple Moving Average (SMA) indicator with the period
        defined by the 'period' parameter, and creates a crossover indicator
        to detect when the price crosses above or below the SMA. Also
        initializes tracking variables for orders, bars, and trade counts.
        """
        sma = bt.ind.SMA(period=self.p.period)
        self.crossover = bt.ind.CrossOver(self.data.close, sma)
        self.order = None

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track completed trades.

        Updates the buy/sell counters when orders are completed and
        clears the order reference when the order is no longer alive.

        Args:
            order: The order object with status information.
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        if not order.alive():
            self.order = None

    def next(self):
        """Execute trading logic for each bar.

        Implements the price and moving average crossover strategy:
        - Buy when price crosses above the SMA
        - Sell (close position) when price crosses below the SMA
        - Only one active order at a time
        """
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


def run_strategy_with_analyzer(strategy_class, data_path, strategy_name):
    """Run a single strategy with analyzers and return results.

    Args:
        strategy_class: The strategy class to run.
        data_path: Path to the data file for backtesting.
        strategy_name: Name of the strategy for display purposes.

    Returns:
        A dictionary containing strategy performance metrics including
        bar_num, buy_count, sell_count, sharpe_ratio, annual_return,
        max_drawdown, total_trades, and final_value.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))
    cerebro.adddata(data)
    cerebro.addstrategy(strategy_class)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # Add analyzers - calculate Sharpe ratio using daily timeframe
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Print results in standard format
    print("=" * 50)
    print(f"{strategy_name} Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    return {
        'strat': strat,
        'bar_num': strat.bar_num,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'sharpe_ratio': sharpe_ratio,
        'annual_return': annual_return,
        'max_drawdown': max_drawdown,
        'total_trades': total_trades,
        'final_value': final_value,
    }


def test_strategy_selection():
    """Test Strategy Selection.

    Tests two different strategies (StrategyA and StrategyB) and verifies
    their performance metrics match expected values.
    """
    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")

    # Test StrategyA
    print("\n--- Testing StrategyA ---")
    result_a = run_strategy_with_analyzer(StrategyA, data_path, "StrategyA")

    # Test StrategyB
    print("\n--- Testing StrategyB ---")
    result_b = run_strategy_with_analyzer(StrategyB, data_path, "StrategyB")

    # Assert test results
    assert result_a['bar_num'] == 482, f"Expected bar_num=482, got {result_a['bar_num']}"
    assert abs(result_a['final_value'] - 104966.80) < 0.01, f"Expected final_value=104966.80, got {result_a['final_value']}"
    assert abs(result_a['sharpe_ratio'] - 0.7210685207398165) < 1e-6, f"Expected sharpe=0.7210685207398165, got {result_a['sharpe_ratio']}"
    assert abs(result_a['annual_return'] - 0.024145144571516192) < 1e-6, f"Expected annual=0.024145144571516192, got {result_a['annual_return']}"
    assert abs(result_a['max_drawdown'] - 3.430658473286522) < 1e-6, f"Expected maxdd=3.430658473286522, got {result_a['max_drawdown']}"
    assert result_a['total_trades'] == 9, f"Expected total_trades=9, got {result_a['total_trades']}"

    assert result_b['bar_num'] == 502, f"Expected bar_num=502, got {result_b['bar_num']}"
    assert abs(result_b['final_value'] - 105258.30) < 0.01, f"Expected final_value=105258.30, got {result_b['final_value']}"
    assert abs(result_b['sharpe_ratio'] - 0.8804632119159153) < 1e-6, f"Expected sharpe=0.8804632119159153, got {result_b['sharpe_ratio']}"
    assert abs(result_b['annual_return'] - 0.025543999840699848) < 1e-6, f"Expected annual=0.025543999840699848, got {result_b['annual_return']}"
    assert abs(result_b['max_drawdown'] - 3.474930243071327) < 1e-6, f"Expected maxdd=3.474930243071327, got {result_b['max_drawdown']}"
    assert result_b['total_trades'] == 43, f"Expected total_trades=43, got {result_b['total_trades']}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Strategy Selection Test")
    print("=" * 60)
    test_strategy_selection()
