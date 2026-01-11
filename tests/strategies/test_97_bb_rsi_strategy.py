#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case for Bollinger Bands + RSI strategy.

This test implements a trading strategy that combines Bollinger Bands and
Relative Strength Index (RSI) to generate trading signals.

Reference: backtrader-strategies-compendium/strategies/BbAndRsi.py
Uses Bollinger Bands lower band + RSI oversold as buy signal.
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


class BbRsiStrategy(bt.Strategy):
    """Bollinger Bands + RSI strategy.

    This strategy generates buy signals when price is below the lower Bollinger
    Band and RSI is oversold, and sell signals when RSI is overbought or price
    exceeds the upper Bollinger Band.

    Entry conditions:
        - Long: RSI < 30 AND price < lower Bollinger Band

    Exit conditions:
        - RSI > 70 OR price > upper Bollinger Band

    Attributes:
        rsi: RSI indicator instance.
        bbands: Bollinger Bands indicator instance.
        order: Current pending order.
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
    """
    params = dict(
        stake=10,
        bb_period=20,
        bb_devfactor=2.0,
        rsi_period=14,
        rsi_oversold=30,
        rsi_overbought=70,
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data, period=self.p.rsi_period)
        self.bbands = bt.indicators.BollingerBands(
            self.data, period=self.p.bb_period, devfactor=self.p.bb_devfactor
        )
        
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Updates buy/sell counters when orders are completed and clears the
        pending order reference.

        Args:
            order: The order object with updated status.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        """Execute trading logic for each bar.

        Implements the Bollinger Bands + RSI strategy:
        - Buy when RSI is oversold and price is below lower band
        - Sell when RSI is overbought or price is above upper band
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # RSI oversold AND price below lower Bollinger Band
            if self.rsi[0] < self.p.rsi_oversold and self.data.close[0] < self.bbands.bot[0]:
                self.order = self.buy(size=self.p.stake)
        else:
            # RSI overbought OR price above upper Bollinger Band
            if self.rsi[0] > self.p.rsi_overbought or self.data.close[0] > self.bbands.top[0]:
                self.order = self.close()


def test_bb_rsi_strategy():
    """Test the Bollinger Bands + RSI strategy.

    This test function:
    1. Sets up a Cerebro backtesting engine
    2. Loads Oracle stock data from 2010-2014
    3. Runs the BbRsiStrategy with default parameters
    4. Validates performance metrics against expected values

    Raises:
        AssertionError: If any performance metric deviates from expected values.
    """
    cerebro = bt.Cerebro()
    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(BbRsiStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Bollinger Bands + RSI Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1238, f"Expected bar_num=1238, got {strat.bar_num}"
    assert abs(final_value - 100120.94) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (1.1614145060616812)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.0002423417652493005)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.033113065059066485) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Bollinger Bands + RSI Strategy Test")
    print("=" * 60)
    test_bb_rsi_strategy()
