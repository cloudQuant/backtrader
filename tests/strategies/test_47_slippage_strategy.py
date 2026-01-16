#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test suite for slippage simulation strategy.

This module tests the impact of slippage on trading performance. Slippage
occurs when there's a difference between the expected price of a trade and
the price at which the trade is actually executed. This is particularly
important for backtesting as it affects the realism of the simulation.

Reference:
    Based on: backtrader-master2/samples/slippage/slippage.py

Example:
    To run the test::

        python test_47_slippage_strategy.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the full path to a data file by searching common locations.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any search path.
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


class SlippageStrategy(bt.Strategy):
    """Simple Moving Average (SMA) crossover strategy for slippage testing.

    This strategy uses two SMA indicators with different periods to generate
    crossover signals. It is specifically designed to test the impact of
    slippage on trading performance.

    Trading Logic:
        - Go long when fast SMA crosses above slow SMA
        - Close position when fast SMA crosses below slow SMA

    Attributes:
        signal: Crossover indicator (+1 for bullish, -1 for bearish).
        order: Current pending order.
        bar_num: Counter for processed bars.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
        win_count: Number of profitable trades.
        loss_count: Number of unprofitable trades.
        sum_profit: Total profit/loss from all closed trades.
    """
    params = (
        ('p1', 10),
        ('p2', 30),
    )

    def __init__(self):
        """Initialize the strategy with SMA indicators and tracking variables."""
        sma1 = bt.ind.SMA(period=self.p.p1)
        sma2 = bt.ind.SMA(period=self.p.p2)
        self.signal = bt.ind.CrossOver(sma1, sma2)
        self.order = None

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def notify_order(self, order):
        """Handle order status updates and track completed orders.

        Args:
            order: The order object with updated status.
        """
        if order.status == bt.Order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        if not order.alive():
            self.order = None

    def notify_trade(self, trade):
        """Track trade results when a trade is closed.

        Args:
            trade: The completed trade object.
        """
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        """Execute trading logic for each bar.

        Implements SMA crossover strategy:
        1. Check for pending orders
        2. Enter long when fast SMA crosses above slow SMA
        3. Close position when fast SMA crosses below slow SMA
        """
        self.bar_num += 1

        if self.order:
            return

        if self.signal > 0:
            # Bullish crossover: close existing position and go long
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.signal < 0:
            # Bearish crossover: close existing position
            if self.position:
                self.order = self.close()

    def stop(self):
        """Print final statistics when the strategy stops.

        Displays win rate and total profit/loss for the backtest period.
        """
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
              f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
              f"wins={self.win_count}, losses={self.loss_count}, "
              f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}")


def test_slippage_strategy():
    """Test SMA crossover strategy with 1% slippage applied.

    This test demonstrates how slippage affects trading performance by
    running an SMA crossover strategy with a 1% percentage-based slippage
    model.

    The test:
    1. Sets up a Cerebro backtest engine
    2. Configures 1% slippage on all trades
    3. Loads 2005-2006 daily price data
    4. Runs the SMA crossover strategy
    5. Validates performance metrics

    Raises:
        AssertionError: If any performance metric does not match expected value.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(50000.0)
    cerebro.broker.set_slippage_perc(0.01)  # 1% slippage on all trades

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="DATA")

    cerebro.addstrategy(SlippageStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("Running backtest...")
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
    print("Slippage Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Validate results against expected values
    # Tolerance: 0.01 for final_value, 1e-6 for other metrics
    assert strat.bar_num == 482, f"Expected bar_num=482, got {strat.bar_num}"
    assert abs(final_value - 52702.98) < 0.01, f"Expected final_value=52702.98, got {final_value}"
    assert abs(sharpe_ratio - (7.146238384824227)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.026251880915366368)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 7.696752586616294) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Slippage Strategy Test")
    print("=" * 60)
    test_slippage_strategy()
