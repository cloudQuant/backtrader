#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: TD Sequential strategy.

Reference: https://github.com/mk99999/TD-seq
Trading based on Tom DeMark's TD Sequential indicator.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on the script directory.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the located data file.

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


class TDSequentialStrategy(bt.Strategy):
    """TD Sequential strategy.

    Based on Tom DeMark's TD Sequential indicator.
    - Setup: Compare closing prices of 9 consecutive candlesticks with
      the closing price 4 periods earlier.
    - Countdown: Begins counting down after Setup completion.

    Attributes:
        dataprimary: Primary data feed.
        dataclose: Close price series.
        order: Current pending order.
        buyTrig: Buy trigger flag.
        sellTrig: Sell trigger flag.
        tdsl: TD sequence long counter.
        tdss: TD sequence short counter.
        buySetup: Buy setup active flag.
        sellSetup: Sell setup active flag.
        buyCountdown: Buy countdown counter.
        sellCountdown: Sell countdown counter.
        buyVal: Buy comparison value.
        sellVal: Sell comparison value.
        buySig: Buy signal flag.
        idealBuySig: Ideal buy signal flag.
        sellSig: Sell signal flag.
        idealSellSig: Ideal sell signal flag.
        buy_nine: Buy setup reached 9 flag.
        sell_nine: Sell setup reached 9 flag.
        buy_high: Highest price during buy setup.
        buy_low: Lowest price during buy setup.
        sell_high: Highest price during sell setup.
        sell_low: Lowest price during sell setup.
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
        setup_buy_count: Number of buy setups completed.
        setup_sell_count: Number of sell setups completed.
    """
    params = dict(
        candles_past_to_compare=4,
        cancel_1=True,
        cancel_2=True,
        cancel_3=2,
        recycle_12=True,
        aggressive_countdown=False,
        cancel_1618=True,
    )

    def __init__(self):
        """Initialize the TD Sequential strategy.

        Sets up all necessary state variables for tracking TD Sequential
        setup and countdown phases, including buy/sell triggers, counters,
        price levels, and trading statistics.
        """
        self.dataprimary = self.datas[0]
        self.dataclose = self.dataprimary.close

        self.order = None
        self.buyTrig = False
        self.sellTrig = False

        self.tdsl = 0  # TD sequence long
        self.tdss = 0  # TD sequence short
        self.buySetup = False
        self.sellSetup = False
        self.buyCountdown = 0
        self.sellCountdown = 0
        self.buyVal = 0
        self.sellVal = 0

        self.buySig = False
        self.idealBuySig = False
        self.sellSig = False
        self.idealSellSig = False

        self.buy_nine = False
        self.sell_nine = False

        self.buy_high = 999999
        self.buy_low = 0
        self.sell_high = 999999
        self.sell_low = 0

        # Statistical variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.setup_buy_count = 0
        self.setup_sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        Tracks completed buy and sell orders, updating the respective
        counters when orders are filled.

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

    def reset_on_cancel_1(self):
        """Reset all setup and countdown state variables.

        Called when cancel_1 condition is triggered, which occurs when
        price moves beyond the high/low of the current setup phase.
        Resets both buy and sell setups, countdowns, and price levels.
        """
        self.buySetup = False
        self.sellSetup = False
        self.buyCountdown = 0
        self.sellCountdown = 0
        self.buy_high = 999999
        self.buy_low = 0
        self.sell_high = 999999
        self.sell_low = 0

    def reset_setup(self, buy_or_sell):
        """Reset setup trigger and counter for buy or sell direction.

        Args:
            buy_or_sell: Either "B" for buy setup or "S" for sell setup.
        """
        if buy_or_sell == "B":
            self.buyTrig = False
            self.tdsl = 0
        elif buy_or_sell == "S":
            self.sellTrig = False
            self.tdss = 0

    def reset_countdown(self, buy_or_sell, count):
        """Reset countdown phase and initialize setup for buy or sell direction.

        Transitions from setup phase to countdown phase when setup completes.
        Records high/low prices during the setup and generates trading signals.

        Args:
            buy_or_sell: Either "B" for buy countdown or "S" for sell countdown.
            count: The number of bars in the completed setup (typically 9).
        """
        if buy_or_sell == "B":
            self.buySig = ((self.dataprimary.low[0] < self.dataprimary.low[-3]) and
                          (self.dataprimary.low[0] < self.dataprimary.low[-2])) or \
                         ((self.dataprimary.low[-1] < self.dataprimary.low[-2]) and
                          (self.dataprimary.low[-1] < self.dataprimary.low[-3]))
            if self.tdsl == 9:
                self.buy_nine = True
                self.setup_buy_count += 1
            self.reset_setup(buy_or_sell)
            self.buySetup = True
            if self.p.cancel_2:
                self.sellSetup = False
                self.sellCountdown = 0
            self.buyCountdown = 0
            self.buy_high = max(self.dataprimary.high[n] for n in range(-(count-1), 0))
            self.buy_low = min(self.dataprimary.low[n] for n in range(-(count-1), 0))

        if buy_or_sell == "S":
            self.sellSig = ((self.dataprimary.high[0] > self.dataprimary.high[-2]) and
                           (self.dataprimary.high[0] > self.dataprimary.high[-3])) or \
                          ((self.dataprimary.high[-1] > self.dataprimary.high[-3]) and
                           (self.dataprimary.high[-1] > self.dataprimary.high[-2]))
            if self.tdss == 9:
                self.sell_nine = True
                self.setup_sell_count += 1
            self.reset_setup(buy_or_sell)
            self.sellSetup = True
            if self.p.cancel_2:
                self.buySetup = False
                self.buyCountdown = 0
            self.sellCountdown = 0
            self.sell_high = max(self.dataprimary.high[n] for n in range(-(count-1), 0))
            self.sell_low = min(self.dataprimary.low[n] for n in range(-(count-1), 0))

    def next(self):
        """Execute the main strategy logic for each bar.

        Implements the TD Sequential algorithm:
        1. Detect buy/sell triggers based on price comparisons
        2. Track setup progression (count consecutive bars)
        3. Transition to countdown phase when setup reaches 9
        4. Generate buy/sell signals when countdown completes
        5. Handle cancellation conditions

        The method compares current close price with price from
        candles_past_to_compare periods ago to identify setup initiation.
        """
        self.bar_num += 1
        self.buySig = False
        self.sellSig = False
        self.idealBuySig = False
        self.idealSellSig = False
        self.buy_nine = False
        self.sell_nine = False

        if len(self.dataclose) > self.p.candles_past_to_compare:
            # Buy trigger
            if (self.dataclose[0] < self.dataclose[-self.p.candles_past_to_compare] and
                self.dataclose[-1] > self.dataclose[-(self.p.candles_past_to_compare + 1)]):
                self.buyTrig = True
                self.sellTrig = False
                self.tdsl = 0
                self.tdss = 0

            # Sell trigger
            elif (self.dataclose[0] > self.dataclose[-self.p.candles_past_to_compare] and
                  self.dataclose[-1] < self.dataclose[-(self.p.candles_past_to_compare + 1)]):
                self.sellTrig = True
                self.buyTrig = False
                self.tdss = 0
                self.tdsl = 0

            # Buy setup numbering
            if self.dataclose[0] < self.dataclose[-self.p.candles_past_to_compare] and self.buyTrig:
                self.tdsl += 1

            # Sell setup numbering
            elif self.dataclose[0] > self.dataclose[-self.p.candles_past_to_compare] and self.sellTrig:
                self.tdss += 1

            # Buy setup reaches 9
            if self.tdsl == 9:
                if self.buySetup is True:
                    if (self.p.recycle_12 is False) or (self.p.cancel_3 == 0):
                        pass
                else:
                    self.reset_countdown("B", self.tdsl)

            # Sell setup reaches 9
            if self.tdss == 9:
                if self.sellSetup is True:
                    if (self.p.recycle_12 is False) or (self.p.cancel_3 == 0):
                        pass
                else:
                    self.reset_countdown("S", self.tdss)

            # Cancel setup 1
            if self.p.cancel_1 and self.buySetup and (self.buy_high < self.dataprimary.low[0]):
                self.reset_on_cancel_1()
            elif self.p.cancel_1 and self.sellSetup and (self.sell_low > self.dataprimary.high[0]):
                self.reset_on_cancel_1()

            countdown_compare = self.dataprimary.low[0] if self.p.aggressive_countdown else self.dataprimary.close[0]

            # Buy countdown
            if self.buySetup:
                if countdown_compare <= self.dataprimary.low[-2]:
                    self.buyCountdown += 1
                    if self.buyCountdown > 13:
                        self.buyCountdown = 13
                if self.buyCountdown == 8:
                    self.buyVal = countdown_compare
                elif self.buyCountdown == 13:
                    if self.dataprimary.low[0] <= self.buyVal:
                        self.idealBuySig = True
                        # Generate buy signal
                        if not self.position:
                            self.buy(size=10)
                        self.buySetup = False
                        self.buyCountdown = 0

            # Sell countdown
            if self.sellSetup:
                if countdown_compare >= self.dataprimary.high[-2]:
                    self.sellCountdown += 1
                    if self.sellCountdown > 13:
                        self.sellCountdown = 13
                if self.sellCountdown == 8:
                    self.sellVal = countdown_compare
                elif self.sellCountdown == 13:
                    if self.dataprimary.high[0] >= self.sellVal:
                        self.idealSellSig = True
                        # Generate sell signal
                        if self.position:
                            self.close()
                        self.sellSetup = False
                        self.sellCountdown = 0

    def stop(self):
        """Called when the backtest is finished.

        Currently a no-op placeholder. Can be used to perform cleanup
        or final analysis at the end of the backtest.
        """
        pass


def test_td_sequential_strategy():
    """Test TD Sequential strategy.

    This test function validates the TD Sequential strategy implementation
    by running a backtest on Oracle stock data from 2010-2014.

    Raises:
        AssertionError: If any of the expected backtest metrics do not match
            the expected values within the specified tolerance.
    """
    cerebro = bt.Cerebro()

    # Use existing data file
    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(TDSequentialStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("TD Sequential Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  setup_buy_count: {strat.setup_buy_count}")
    print(f"  setup_sell_count: {strat.setup_sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1257, f"Expected bar_num=1257, got {strat.bar_num}"
    assert abs(final_value - 100002.91) < 0.01, f"Expected final_value=100002.91, got {final_value}"
    assert abs(sharpe_ratio - (0.022949645759068132)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (5.826805806698434e-06)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.08176597127582681) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("TD Sequential Strategy Test")
    print("=" * 60)
    test_td_sequential_strategy()
