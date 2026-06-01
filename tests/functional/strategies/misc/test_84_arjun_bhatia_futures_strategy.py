#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Arjun Bhatia Futures Trading Strategy.

Reference: https://github.com/Backtesting/strategies
A futures trading strategy combining the Alligator indicator and SuperTrend indicator.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import backtrader as bt

import datetime
from pathlib import Path
import pytest

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching multiple possible locations.

    This function searches for a data file in several common locations relative
    to the current test file directory, making the test suite more portable across
    different project structures.

    Args:
        filename: Name of the data file to locate (e.g., 'orcl-1995-2014.txt').

    Returns:
        Path: Absolute path to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched locations.

    Search Order:
        1. Current test directory (tests/strategies/)
        2. Parent tests directory (tests/)
        3. Current test directory/datas (tests/strategies/datas/)
        4. Parent tests directory/datas (tests/datas/)
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


class ArjunBhatiaFuturesStrategy(bt.Strategy):
    """Arjun Bhatia Futures Trading Strategy.

    A trading strategy that combines the Alligator and SuperTrend indicators:
    - Buy when price is above Alligator jaw line and SuperTrend is bullish
    - Sell when price is below Alligator jaw line and SuperTrend is bearish
    - Use ATR to calculate stop loss and take profit levels

    Attributes:
        alligator: Alligator indicator instance.
        supertrend: SuperTrend indicator instance.
        atr: Average True Range indicator for risk management.
        entry_price: Price at which the current position was entered.
        stop_loss: Stop loss price for the current position.
        take_profit: Take profit price for the current position.
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
    """
    params = dict(
        stake=10,
        jaw_period=13,
        teeth_period=8,
        lips_period=5,
        supertrend_period=10,
        supertrend_multiplier=3.0,
        atr_sl_mult=2.0,
        atr_tp_mult=4.0,
    )

    def __init__(self):
        """Initialize the Arjun Bhatia Futures Trading Strategy.

        Sets up all required indicators and initializes tracking variables for
        order management and position monitoring.

        Indicators created:
        - Alligator: Trend identification using jaw, teeth, and lips lines
        - SuperTrend: Trend direction and volatility-based bands
        - ATR (14-period): For stop loss and take profit calculations

        Tracking variables initialized:
        - order: Current pending order (None if no pending order)
        - entry_price: Price at which current position was entered
        - stop_loss: Stop loss price level for risk management
        - take_profit: Take profit price level for profit taking
        - bar_num: Counter for total bars processed
        - buy_count: Counter for total buy orders executed
        - sell_count: Counter for total sell orders executed
        """
        self.dataclose = self.datas[0].close
        self.datahigh = self.datas[0].high
        self.datalow = self.datas[0].low

        self.alligator = bt.indicators.AlligatorIndicator(
            self.datas[0],
            jaw_period=self.p.jaw_period,
            teeth_period=self.p.teeth_period,
            lips_period=self.p.lips_period
        )

        self.supertrend = bt.indicators.SuperTrendIndicator(
            self.datas[0],
            period=self.p.supertrend_period,
            multiplier=self.p.supertrend_multiplier
        )

        self.atr = bt.indicators.ATR(self.datas[0], period=14)

        self.order = None
        self.entry_price = 0
        self.stop_loss = 0
        self.take_profit = 0

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and manage position tracking.

        Called by the backtrader engine when an order changes status. This method
        tracks completed orders and calculates risk management levels for new positions.

        For buy orders (long positions):
        - Increments buy_count
        - Records entry price from the executed order
        - Calculates stop loss using ATR: entry - (ATR * atr_sl_mult)
        - Calculates take profit using ATR: entry + (ATR * atr_tp_mult)

        For sell orders (short position exits):
        - Increments sell_count
        - No stop loss/take profit calculation (only long positions are traded)

        Args:
            order: The order object with updated status from the broker.

        Note:
            Pending orders (Submitted/Accepted) are ignored. Only Completed
            orders trigger position tracking updates.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.entry_price = order.executed.price
                self.stop_loss = self.entry_price - self.atr[0] * self.p.atr_sl_mult
                self.take_profit = self.entry_price + self.atr[0] * self.p.atr_tp_mult
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        """Execute the trading logic for each bar.

        This method is called for every bar in the data feed and implements
        the core strategy logic:

        Entry conditions (no position):
        - Price is above Alligator jaw line (bullish trend)
        - SuperTrend direction is bullish (direction == 1)
        - If both conditions met, execute a buy order

        Exit conditions (has position):
        - Stop loss hit: Low price <= stop_loss level
        - Take profit hit: High price >= take_profit level
        - Trend reversal: Either Alligator or SuperTrend turns bearish

        The strategy only takes long positions and uses ATR-based risk management
        to limit downside while capturing upside potential.
        """
        self.bar_num += 1

        if self.order:
            return

        is_alligator_bullish = self.dataclose[0] > self.alligator.jaw[0]
        is_supertrend_bullish = self.supertrend.direction[0] == 1

        if not self.position:
            # Long entry: Both Alligator and SuperTrend are bullish
            if is_alligator_bullish and is_supertrend_bullish:
                self.order = self.buy(size=self.p.stake)
        else:
            # Stop loss or take profit
            if self.datalow[0] <= self.stop_loss:
                self.order = self.close()
            elif self.datahigh[0] >= self.take_profit:
                self.order = self.close()
            # Or indicator reversal
            elif not is_alligator_bullish or not is_supertrend_bullish:
                self.order = self.close()


@pytest.mark.parametrize("runonce", [True, False])
def test_arjun_bhatia_futures_strategy(runonce):
    """Test the Arjun Bhatia Futures Trading Strategy.

    This test runs a backtest of the Arjun Bhatia strategy on historical data
    and verifies that key performance metrics match expected values.

    The test:
    1. Loads Oracle stock data from 2010-2014
    2. Runs the Arjun Bhatia strategy with default parameters
    3. Calculates performance metrics (Sharpe ratio, returns, drawdown)
    4. Asserts that results match expected values within tolerance

    Raises:
        AssertionError: If any performance metric falls outside expected tolerance.
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
    cerebro.addstrategy(ArjunBhatiaFuturesStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    results = cerebro.run(runonce=runonce)
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Arjun Bhatia Futures Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1243, f"Expected bar_num=1243, got {strat.bar_num}"
    assert abs(final_value - 100008.3) < 0.01, f"Expected final_value=100008.3, got {final_value}"
    assert abs(sharpe_ratio - (0.03545852568934664)) < 1e-6, f"Expected sharpe_ratio=0.03545852568934664, got {sharpe_ratio}"
    assert abs(annual_return - (1.6643997595262782e-05)) < 1e-6, f"Expected annual_return=1.6643997595262782e-05, got {annual_return}"
    assert abs(max_drawdown - 0.13555290823752497) < 1e-6, f"Expected max_drawdown=0.13555290823752497, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Arjun Bhatia Futures Strategy Test")
    print("=" * 60)
    test_arjun_bhatia_futures_strategy()
