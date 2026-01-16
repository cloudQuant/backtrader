#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Keltner Channel strategy.

Uses Keltner Channel breakout to determine trend.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching in common locations.

    This function searches for a data file in multiple possible locations
    relative to the test directory, including the current directory, parent
    directory, and 'datas' subdirectories.

    Args:
        filename: The name of the data file to locate.

    Returns:
        The resolved Path object pointing to the data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched locations.
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


class KeltnerChannelIndicator(bt.Indicator):
    """Keltner Channel indicator.

    Calculates the Keltner Channel, which consists of a middle line (EMA),
    an upper band, and a lower band based on Average True Range (ATR).
    """
    lines = ('mid', 'top', 'bot')
    params = dict(period=20, atr_mult=2.0, atr_period=14)

    def __init__(self):
        """Initialize the Keltner Channel indicator.

        Calculates the middle line as an Exponential Moving Average (EMA) and
        the upper/lower bands by adding/subtracting a multiple of the Average
        True Range (ATR) to/from the middle line.
        """
        self.l.mid = bt.indicators.EMA(self.data.close, period=self.p.period)
        atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.l.top = self.l.mid + self.p.atr_mult * atr
        self.l.bot = self.l.mid - self.p.atr_mult * atr


class KeltnerChannelStrategy(bt.Strategy):
    """Keltner Channel strategy.

    Entry conditions:
        - Long: Price breaks above upper band

    Exit conditions:
        - Price falls below middle band
    """
    params = dict(
        stake=10,
        period=20,
        atr_mult=2.0,
    )

    def __init__(self):
        """Initialize the Keltner Channel strategy.

        Sets up the Keltner Channel indicator and initializes tracking variables
        for orders, bar count, and trade statistics.
        """
        self.kc = KeltnerChannelIndicator(
            self.data, period=self.p.period, atr_mult=self.p.atr_mult
        )

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order notifications and update trade statistics.

        Args:
            order: The order object with status information.
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

        Implements the Keltner Channel breakout strategy:
        - Long entry when price breaks above the upper band
        - Exit when price falls below the middle band
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Price breaks above upper band
            if self.data.close[0] > self.kc.top[0]:
                self.order = self.buy(size=self.p.stake)
        else:
            # Price falls below middle band
            if self.data.close[0] < self.kc.mid[0]:
                self.order = self.close()


def test_keltner_channel_strategy():
    """Test the Keltner Channel strategy.

    This test runs a backtest of the Keltner Channel strategy on Oracle
    stock data from 2010-2014, validating various performance metrics
    including Sharpe ratio, returns, drawdown, and trade statistics.

    Raises:
        AssertionError: If any of the expected backtest results do not
            match within the specified tolerance.
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
    cerebro.addstrategy(KeltnerChannelStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Keltner Channel strategy backtest results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assertions - Using precise assertions
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1238, f"Expected bar_num=1238, got {strat.bar_num}"
    assert abs(final_value - 100039.51) < 0.01, f"Expected final_value=100039.51, got {final_value}"
    assert abs(sharpe_ratio - 0.2795635163868808) < 1e-6, f"Expected sharpe_ratio=0.2795635163868808, got {sharpe_ratio}"
    assert abs(annual_return - (7.919528281735741e-05)) < 1e-6, f"Expected annual_return=7.919528281735741e-05, got {annual_return}"
    assert abs(max_drawdown - 0.05497965839460319) < 1e-6, f"Expected max_drawdown=0.05497965839460319, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Keltner Channel strategy test")
    print("=" * 60)
    test_keltner_channel_strategy()
