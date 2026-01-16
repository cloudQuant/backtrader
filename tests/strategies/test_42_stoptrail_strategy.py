#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: StopTrail trailing stop strategy.

Reference: backtrader-master2/samples/stoptrail/trail.py
Uses trailing stop orders to protect profits.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the full path to a data file by searching common directories.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths.
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


class StopTrailStrategy(bt.Strategy):
    """Trailing stop strategy.

    Buys when moving averages cross over (golden cross) and uses trailing
    stop orders to protect profits.
    """
    params = dict(
        p1=5,
        p2=20,
        trailpercent=0.02,
    )

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables."""
        ma1 = bt.ind.SMA(period=self.p.p1)
        ma2 = bt.ind.SMA(period=self.p.p2)
        self.crossover = bt.ind.CrossOver(ma1, ma2)
        self.order = None
        self.stop_order = None

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        """Handle order status updates.

        Args:
            order: The order object with status update.
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        if not order.alive():
            if order == self.order:
                self.order = None
            elif order == self.stop_order:
                self.stop_order = None

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Args:
            trade: The trade object that was closed.
        """
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple moving average crossover strategy:
        - Buy when short MA crosses above long MA (golden cross)
        - Sell when short MA crosses below long MA (death cross)
        """
        self.bar_num += 1

        # Buy signal: short-term MA crosses above long-term MA
        if not self.position:
            if self.crossover > 0:  # Golden cross
                self.order = self.buy()
        # Sell signal: short-term MA crosses below long-term MA
        elif self.crossover < 0:  # Death cross
            self.order = self.close()

    def stop(self):
        """Print strategy performance summary when backtesting ends."""
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
              f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
              f"wins={self.win_count}, losses={self.loss_count}, "
              f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}")


def test_stoptrail_strategy():
    """Test the StopTrail trailing stop strategy.

    Runs a backtest using historical price data and verifies that:
    - The strategy executes the expected number of trades
    - Performance metrics match expected values
    - Final portfolio value is correct

    Raises:
        AssertionError: If any of the expected values do not match within
            the specified tolerance.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="DATA")

    cerebro.addstrategy(StopTrailStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("StopTrail Trailing Stop Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Tolerance for final_value: 0.01, tolerance for other metrics: 1e-6
    assert strat.bar_num == 492, f"Expected bar_num=492, got {strat.bar_num}"
    assert strat.buy_count == 12, f"Expected buy_count=12, got {strat.buy_count}"
    assert strat.sell_count == 11, f"Expected sell_count=11, got {strat.sell_count}"
    assert total_trades == 12, f"Expected total_trades=12, got {total_trades}"
    assert abs(sharpe_ratio - 1.1907318477311835) < 1e-6, f"Expected sharpe_ratio=1.1907318477311835, got {sharpe_ratio}"
    assert abs(annual_return - 0.02521785636583261) < 1e-6, f"Expected annual_return=0.02521785636583261, got {annual_return}"
    assert abs(max_drawdown - 3.2630429367196996) < 1e-6, f"Expected max_drawdown=3.2630429367196996, got {max_drawdown}"
    assert abs(final_value - 105190.30) < 0.01, f"Expected final_value=105190.30, got {final_value}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("StopTrail Trailing Stop Strategy Test")
    print("=" * 60)
    test_stoptrail_strategy()
