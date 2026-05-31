#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case for Order Close (execution at closing price).

Reference: backtrader-master2/samples/order-close/close-daily.py
Tests order execution at the closing price of each bar.

Data Used:
    Daily OHLC bars from ``2005-2006-day-001.txt`` (the standard backtrader
    sample file in BacktraderCSVData format), located via resolve_data_path and
    consumed in full as a single daily feed with end-of-session bars enabled.

Strategy Principle:
    A minimal SMA crossover used to exercise the Order.Close execution type,
    where orders fill at the bar's closing price rather than the next bar's open.
    A simple moving average defines the trend; a price-over-SMA cross is treated
    as a bullish entry and the reverse cross as the exit. The focus is verifying
    deterministic close-price fills, not the predictive value of the signal.

Strategy Logic:
    OrderCloseStrategy builds an SMA and a CrossOver of close versus the SMA.
    Each bar it skips while an order is pending, then — while flat — submits a
    buy with exectype=Order.Close on a bullish crossover, or — while long —
    submits a close with exectype=Order.Close on a bearish crossover.
    notify_order counts completed buys/sells and clears the order reference; stop
    prints final counters. The parametrized test enables seteosbar, runs both
    runonce=True and runonce=False, and asserts bar count, final value, Sharpe,
    annual return, and max drawdown against expected values.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt
import pytest

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching common locations.

    Args:
        filename: Name of the data file to find

    Returns:
        Path object pointing to the data file

    Raises:
        FileNotFoundError: If data file cannot be found in any search path
    """
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent.parent.parent / filename,
        BASE_DIR / "datas" / filename,
        BASE_DIR.parent.parent.parent / "datas" / filename,
    ]
    for p in search_paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"Cannot find data file: {filename}")


class OrderCloseStrategy(bt.Strategy):
    """Strategy that executes orders at closing price.

    This strategy uses SMA crossover signals and executes orders
    at the close of each bar using bt.Order.Close execution type.

    Attributes:
        params: Strategy parameters (period for SMA)
        crossover: CrossOver indicator tracking price vs SMA
        order: Current pending order
        bar_num: Counter for processed bars
        buy_count: Counter for executed buy orders
        sell_count: Counter for executed sell orders
    """
    params = (('period', 15),)

    def __init__(self):
        """Initialize strategy with indicators and counters."""
        sma = bt.ind.SMA(period=self.p.period)
        self.crossover = bt.ind.CrossOver(self.data.close, sma)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status changes.

        Args:
            order: The order object with updated status
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
            self.order = None

    def next(self):
        """Execute trading logic for each bar.

        Buy on bullish crossover, close position on bearish crossover.
        All orders are executed at closing price.
        """
        self.bar_num += 1
        if self.order:
            return  # Wait for pending order to complete

        if not self.position:
            if self.crossover > 0:
                # Execute buy order at closing price
                self.order = self.buy(exectype=bt.Order.Close)
        else:
            if self.crossover < 0:
                # Execute close order at closing price
                self.order = self.close(exectype=bt.Order.Close)

    def stop(self):
        """Print strategy statistics after backtest completion."""
        print(f"OrderClose: bar_num={self.bar_num}, buy={self.buy_count}, sell={self.sell_count}")


@pytest.mark.parametrize("runonce", [True, False])
def test_order_close(runonce):
    """Test Order Close execution at closing price.

    This test verifies that orders are correctly executed at the
    closing price of each bar and validates expected performance metrics.

    Raises:
        AssertionError: If any metric does not match expected values
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.seteosbar(True)  # End of session bar

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))
    cerebro.adddata(data)

    cerebro.addstrategy(OrderCloseStrategy, period=15)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

    print("Running backtest...")
    results = cerebro.run(runonce=runonce)
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Order Close Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Validate results - final_value tolerance: 0.01, others: 1e-6
    assert strat.bar_num == 497, f"Expected bar_num=497, got {strat.bar_num}"
    assert abs(final_value - 102995.5) < 0.01, f"Expected final_value=102995.50, got {final_value}"
    assert abs(sharpe_ratio - (0.3210201519350739)) < 1e-6, f"Expected sharpe_ratio=0.3210201519350739, got {sharpe_ratio}"
    assert abs(annual_return - (0.014632998393384895)) < 1e-6, f"Expected annual_return=0.014632998393384895, got {annual_return}"
    assert abs(max_drawdown - 4.113455968673918) < 1e-6, f"Expected max_drawdown=4.113455968673918, got {max_drawdown}"

    print("\nTest passed!")




if __name__ == "__main__":
    print("=" * 60)
    print("Order Close Test")
    print("=" * 60)
    test_order_close()
