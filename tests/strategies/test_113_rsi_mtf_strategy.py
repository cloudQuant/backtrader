#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test case: RSI MTF (Multiple Time Frame) Strategy.

This module tests the RSI Multiple Time Frame (MTF) strategy implementation.
The strategy uses a combination of long and short period RSI indicators
to determine optimal entry and exit timing for trading decisions.

Reference: backtrader-strategies-compendium/strategies/RsiMtf.py

The strategy logic:
    - Entry: When long period RSI shows strength (>50) AND short period
      RSI shows strong momentum (>70), indicating potential uptrend
    - Exit: When short period RSI declines below 35, indicating momentum
      loss and potential reversal

Example:
    To run the test directly:
        python tests/strategies/test_113_rsi_mtf_strategy.py

    To run with pytest:
        pytest tests/strategies/test_113_rsi_mtf_strategy.py -v
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching common locations.

    This function searches for data files in several standard locations
    relative to the test directory, making tests more portable across
    different directory structures.

    Args:
        filename (str): The name of the data file to locate.

    Returns:
        Path: The absolute path to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of
            the search paths.

    Search Locations:
        1. Current test directory: tests/strategies/{filename}
        2. Parent test directory: tests/{filename}
        3. Test datas directory: tests/strategies/datas/{filename}
        4. Parent datas directory: tests/datas/{filename}
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


class RsiMtfStrategy(bt.Strategy):
    """RSI MTF (Multiple Time Frame) Strategy.

    This strategy implements a multi-timeframe approach using RSI indicators
    with different periods to identify trading opportunities. By combining
    a long-period RSI (trend filter) with a short-period RSI (momentum
    trigger), the strategy aims to enter trades when both trend and momentum
    align and exit when momentum reverses.

    Strategy Logic:
        Entry (Long):
            - Long period RSI > buy_rsi_long (default 50): Indicates
              bullish trend strength
            - Short period RSI > buy_rsi_short (default 70): Indicates
              strong short-term momentum
            - Both conditions must be true simultaneously

        Exit:
            - Short period RSI < sell_rsi_short (default 35): Indicates
              momentum loss and potential reversal

    Attributes:
        rsi_long (bt.indicators.RSI): Long period RSI indicator for trend
            identification. Default period is 14 bars.
        rsi_short (bt.indicators.RSI): Short period RSI indicator for
            momentum detection. Default period is 3 bars.
        order (bt.Order): Current pending order. Used to track order status
            and prevent duplicate orders.
        bar_num (int): Counter tracking the number of bars processed during
            the backtest.
        buy_count (int): Total number of buy orders executed during the
            strategy run.
        sell_count (int): Total number of sell orders executed during the
            strategy run.

    Parameters:
        stake (int): Number of shares/contracts per trade. Default is 10.
        period_long (int): Period for long-term RSI. Default is 14.
        period_short (int): Period for short-term RSI. Default is 3.
        buy_rsi_long (float): RSI level for long-term trend confirmation.
            Default is 50.
        buy_rsi_short (float): RSI level for short-term momentum trigger.
            Default is 70.
        sell_rsi_short (float): RSI level for exit signal. Default is 35.
    """
    params = dict(
        stake=10,
        period_long=14,
        period_short=3,
        buy_rsi_long=50,
        buy_rsi_short=70,
        sell_rsi_short=35,
    )

    def __init__(self):
        """Initialize the RSI MTF strategy.

        Sets up the RSI indicators with long and short periods and initializes
        tracking variables for orders and statistics.

        The initialization creates:
            - Long period RSI: Used for trend identification
            - Short period RSI: Used for momentum signals
            - Order tracking: Prevents duplicate orders
            - Counters: For buy/sell orders and bars processed
        """
        self.rsi_long = bt.indicators.RSI(self.data, period=self.p.period_long)
        self.rsi_short = bt.indicators.RSI(self.data, period=self.p.period_short)

        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status notifications.

        This method is called by the backtrader engine when an order's status
        changes. It updates the buy/sell counters and clears the pending order
        reference when the order is completed.

        Args:
            order (bt.Order): The order object containing status updates and
                execution details.

        Order Status Handling:
            - Submitted/Acpected: Order pending execution, no action taken
            - Completed: Order executed, increment buy/sell counter
            - Other statuses: Clear the order reference
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

        This method is called for each bar of data during the backtest.
        It implements the RSI MTF strategy by checking entry and exit conditions.

        Entry Logic:
            - Only enter when not currently in a position
            - Requires both RSI conditions to be met:
                * Long period RSI > buy_rsi_long (default 50)
                * Short period RSI > buy_rsi_short (default 70)
            - Executes a buy order for stake shares

        Exit Logic:
            - Only exit when currently in a position
            - Triggered when short period RSI < sell_rsi_short (default 35)
            - Closes the entire position

        Risk Management:
            - Checks for pending orders before placing new ones
            - Maintains self.order to prevent duplicate orders
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Entry: Long period RSI strong AND Short period RSI strong
            if self.rsi_long[0] > self.p.buy_rsi_long and self.rsi_short[0] > self.p.buy_rsi_short:
                self.order = self.buy(size=self.p.stake)
        else:
            # Exit: Short period RSI declines
            if self.rsi_short[0] < self.p.sell_rsi_short:
                self.order = self.close()


def test_rsi_mtf_strategy():
    """Test the RSI MTF strategy implementation.

    This test function validates the RSI Multiple Time Frame strategy by
    running a complete backtest on historical Oracle stock data and verifying
    that the results match expected performance metrics.

    Test Procedure:
        1. Load historical Oracle stock data (orcl-1995-2014.txt)
        2. Configure a Cerebro engine with the RSI MTF strategy
        3. Set initial capital to $100,000 and commission to 0.1%
        4. Add performance analyzers (Sharpe Ratio, Returns, Drawdown)
        5. Run the backtest from 2010-01-01 to 2014-12-31
        6. Collect and validate performance metrics

    Expected Results:
        - bar_num: 1243 (number of bars processed)
        - final_value: ~99944.33 (ending portfolio value)
        - sharpe_ratio: ~-0.2931 (risk-adjusted return)
        - annual_return: ~-0.011% (normalized annual return)
        - max_drawdown: ~14.51% (maximum peak-to-trough decline)

    Raises:
        AssertionError: If any performance metric does not match expected
            values within specified tolerance. Tolerances are 0.01 for
            final_value and 1e-6 for other metrics.

    Side Effects:
        Prints test results including bar count, buy/sell counts, and
        performance metrics to stdout.
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
    cerebro.addstrategy(RsiMtfStrategy)
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
    print("RSI MTF (Multiple Time Frame) Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assertions - Using precise assertions
    # final_value tolerance: 0.01, other indicators tolerance: 1e-6
    assert strat.bar_num == 1243, f"Expected bar_num=1243, got {strat.bar_num}"
    assert abs(final_value - 99944.33) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (-0.2930928685297336)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (-0.00011163604936501658)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.14506963091824412) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("RSI MTF (Multiple Time Frame) Strategy Test")
    print("=" * 60)
    test_rsi_mtf_strategy()
