#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: MACD + RSI + BB Multi-Indicator Strategy

Reference: backtrader_NUPL_strategy/hope/Hope_bbands.py
A multi-confirmation strategy combining MACD, RSI, and Bollinger Bands
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching in common directories.

    Searches for a data file in several possible locations relative to the
    test file directory. This allows tests to find data files regardless of
    how the tests are run.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the first existing match.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths.

    Search order:
        1. BASE_DIR / filename
        2. BASE_DIR.parent / filename
        3. BASE_DIR / "datas" / filename
        4. BASE_DIR.parent / "datas" / filename
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


class MacdRsiBbStrategy(bt.Strategy):
    """MACD + RSI + BB Multi-Indicator Strategy.

    Entry conditions:
    - Long: Price breaks above lower Bollinger Band and RSI < 35

    Exit conditions:
    - Price breaks above upper Bollinger Band and RSI > 65
    """
    params = dict(
        stake=10,
        bb_period=20,
        bb_dev=2.0,
        rsi_period=14,
        rsi_oversold=35,
        rsi_overbought=65,
    )

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables.

        Creates the following indicators:
        - Bollinger Bands: For identifying price extremes and volatility
        - RSI: For identifying overbought/oversold conditions
        - MACD: For trend confirmation (calculated but not used in current logic)

        Also initializes tracking variables for order management and trade
        statistics.
        """
        self.bbands = bt.indicators.BollingerBands(
            self.data, period=self.p.bb_period, devfactor=self.p.bb_dev
        )
        self.rsi = bt.indicators.RSI(self.data, period=self.p.rsi_period)
        self.macd = bt.indicators.MACD(self.data)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track trade statistics.

        Called by the backtrader engine when an order's status changes.
        Tracks the number of buy and sell orders that complete successfully.

        Args:
            order: The order object with updated status information.
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

        This method is called by the backtrader engine for each new bar
        of data. It implements the following logic:

        Long entry (when not in position):
        - Previous close was below lower Bollinger Band
        - Current close crosses back above lower Bollinger Band
        - RSI is oversold (below threshold)

        Exit (when in position):
        - Current close is above upper Bollinger Band
        - RSI is overbought (above threshold)
        """
        self.bar_num += 1

        if self.order:
            return

        if len(self) < 2:
            return

        if not self.position:
            # Price recovers from below lower band and RSI is oversold
            if (self.data.close[-1] < self.bbands.bot[-1] and
                self.data.close[0] > self.bbands.bot[0] and
                self.rsi[0] < self.p.rsi_oversold):
                self.order = self.buy(size=self.p.stake)
        else:
            # Price touches upper band and RSI is overbought
            if self.data.close[0] > self.bbands.top[0] and self.rsi[0] > self.p.rsi_overbought:
                self.order = self.close()


def test_macd_rsi_bb_strategy():
    """Test the MACD + RSI + Bollinger Bands multi-indicator strategy.

    This test function:
    1. Loads Oracle stock data from 2010-2014
    2. Runs the MacdRsiBbStrategy with default parameters
    3. Verifies performance metrics match expected values

    The strategy uses a mean-reversion approach, buying when price recovers
    from below the lower Bollinger Band with oversold RSI, and selling when
    price reaches the upper Bollinger Band with overbought RSI.

    Expected results:
    - bar_num: 1224
    - final_value: ~100170.29 (slight profit from 100000 start)
    - sharpe_ratio: ~1.17
    - annual_return: ~0.034%
    - max_drawdown: ~2.92%

    Raises:
        AssertionError: If any of the performance metrics don't match
            expected values within tolerance.
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
    cerebro.addstrategy(MacdRsiBbStrategy)
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
    print("MACD + RSI + BB Multi-Indicator Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assertions - using precise assertions
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1224, f"Expected bar_num=1224, got {strat.bar_num}"
    assert abs(final_value - 100170.29) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (1.17015947201324)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.0003411510229375079)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.029197450472779395) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("MACD + RSI + BB Multi-Indicator Strategy Test")
    print("=" * 60)
    test_macd_rsi_bb_strategy()
