#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test module for SuperTrend Indicator Strategy.

This module tests a trading strategy based on the SuperTrend indicator, which
is a trend-following indicator that uses Average True Range (ATR) to calculate
upper and lower bands. The indicator identifies trend direction and generates
trading signals when price breaks through these bands.

Reference:
    https://github.com/Backtrader1.0/strategies/supertrend.py

Test Coverage:
    - SuperTrend indicator calculation and trend detection
    - Strategy entry/exit logic based on trend line breaks
    - Performance metrics validation (Sharpe ratio, returns, drawdown)

Example:
    Run the test directly:
        python tests/strategies/test_88_supertrend_indicator_strategy.py

    Or run via pytest:
        pytest tests/strategies/test_88_supertrend_indicator_strategy.py -v
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the absolute path to a test data file.

    This function searches for data files in multiple common locations
    relative to the test directory, making the tests more portable
    across different directory structures.

    Args:
        filename: Name of the data file to locate (e.g., 'orcl-1995-2014.txt').

    Returns:
        Path object pointing to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths.

    Search Paths:
        1. Current test directory (BASE_DIR)
        2. Parent directory of tests (BASE_DIR.parent)
        3. 'datas' subdirectory of current test directory
        4. 'datas' subdirectory of parent directory

    Example:
        >>> path = resolve_data_path('orcl-1995-2014.txt')
        >>> print(path)
        /path/to/tests/strategies/datas/orcl-1995-2014.txt
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


class SuperTrendIndicator(bt.Indicator):
    """SuperTrend trend-following indicator.

    The SuperTrend indicator is a trend-following indicator that uses the
    Average True Range (ATR) to calculate upper and lower bands around price.
    It determines the current trend direction and provides a dynamic support/
    resistance line that adjusts based on volatility.

    The indicator is calculated as follows:
        1. Calculate basic upper and lower bands using HL2 +/- (multiplier * ATR)
        2. Modify the bands to only change when price crosses them
        3. Determine trend based on price position relative to previous bands
        4. Return the appropriate band as the SuperTrend line

    Lines:
        st: The SuperTrend line (acts as dynamic support/resistance)
        final_up: Modified upper band
        final_dn: Modified lower band
        trend: Current trend direction (1 for uptrend, -1 for downtrend)

    Params:
        period: ATR calculation period (default: 20)
        multiplier: ATR multiplier for band width (default: 3.0)

    Interpretation:
        - When price is above the SuperTrend line, the trend is up (bullish)
        - When price is below the SuperTrend line, the trend is down (bearish)
        - The line acts as trailing stop-loss level
    """
    lines = ('st', 'final_up', 'final_dn', 'trend')
    params = dict(period=20, multiplier=3.0)

    def __init__(self):
        """Initialize the SuperTrend indicator.

        Sets up the internal calculations:
            - ATR indicator for volatility measurement
            - Basic upper and lower bands based on HL2 +/- (multiplier * ATR)
            - Minimum period requirement (period + 1 bars needed)

        The basic bands are calculated as:
            basic_up = hl2 + (multiplier * ATR)
            basic_dn = hl2 - (multiplier * ATR)

        where hl2 = (high + low) / 2
        """
        self.atr = bt.indicators.ATR(self.data, period=self.p.period)
        hl2 = (self.data.high + self.data.low) / 2.0
        self.basic_up = hl2 + self.p.multiplier * self.atr
        self.basic_dn = hl2 - self.p.multiplier * self.atr
        self.addminperiod(self.p.period + 1)

    def next(self):
        """Calculate the SuperTrend indicator values for the current bar.

        This method is called for each bar in the data series and performs
        the following calculations:

        1. **Initialization (first bar)**: Set final bands to basic bands,
           initialize trend to uptrend (1), and set SuperTrend line to lower band

        2. **Band Modification**: Update final upper/lower bands using special logic:
           - Upper band decreases if basic_up < previous final_up OR previous close > previous final_up
           - Lower band increases if basic_dn > previous final_dn OR previous close < previous final_dn
           - Otherwise, carry forward the previous band value

        3. **Trend Detection**: Determine trend direction:
           - Uptrend (1) if current close > previous final upper band
           - Downtrend (-1) if current close < previous final lower band
           - Keep previous trend if neither condition is met

        4. **SuperTrend Line**: Set to final lower band in uptrend, final upper band in downtrend

        The band modification ensures the bands only change when price breaks through them,
        creating a trailing effect that follows the trend.
        """
        if len(self) == self.p.period + 1:
            self.final_up[0] = self.basic_up[0]
            self.final_dn[0] = self.basic_dn[0]
            self.trend[0] = 1
            self.st[0] = self.basic_dn[0]
            return

        prev_fu = self.final_up[-1]
        prev_fd = self.final_dn[-1]

        # Update upper band
        if self.basic_up[0] < prev_fu or self.data.close[-1] > prev_fu:
            self.final_up[0] = self.basic_up[0]
        else:
            self.final_up[0] = prev_fu

        # Update lower band
        if self.basic_dn[0] > prev_fd or self.data.close[-1] < prev_fd:
            self.final_dn[0] = self.basic_dn[0]
        else:
            self.final_dn[0] = prev_fd

        # Determine trend direction
        if self.data.close[0] > self.final_up[-1]:
            self.trend[0] = 1
        elif self.data.close[0] < self.final_dn[-1]:
            self.trend[0] = -1
        else:
            self.trend[0] = self.trend[-1]

        # Set SuperTrend line
        self.st[0] = self.final_dn[0] if self.trend[0] > 0 else self.final_up[0]


class SuperTrendIndicatorStrategy(bt.Strategy):
    """Trading strategy based on SuperTrend indicator signals.

    This strategy implements a trend-following approach using the SuperTrend
    indicator to generate entry and exit signals. It goes long when price breaks
    above the SuperTrend line (indicating start of uptrend) and exits long
    positions when price breaks below the line (indicating trend reversal).

    Trading Logic:
        - Long Entry: When price crosses above SuperTrend line from below
        - Long Exit: When price crosses below SuperTrend line from above
        - Position Sizing: Fixed stake size per trade

    The strategy tracks the relationship between price and the SuperTrend line
    on each bar to detect crossovers. It only maintains long positions, closing
    and entering new long positions when the trend turns bullish.

    Params:
        stake: Number of shares/contracts per trade (default: 10)
        st_period: SuperTrend ATR period (default: 20)
        st_mult: SuperTrend multiplier for band width (default: 3.0)

    Attributes:
        dataclose: Reference to close prices of the data feed
        st: SuperTrend indicator instance
        atr: Average True Range indicator (14-period)
        order: Current pending order (None if no pending order)
        prev_up: Whether price was above SuperTrend on previous bar
        bar_num: Counter for number of bars processed
        buy_count: Number of buy orders executed
        sell_count: Number of sell orders executed
    """
    params = dict(
        stake=10,
        st_period=20,
        st_mult=3.0,
    )

    def __init__(self):
        """Initialize the SuperTrend strategy.

        Sets up indicators and tracking variables:
            - SuperTrend indicator with configured parameters
            - ATR(14) for additional volatility analysis
            - Order management and trade counting variables
            - Previous price-position state for crossover detection
        """
        self.dataclose = self.datas[0].close

        # SuperTrend indicator
        self.st = SuperTrendIndicator(
            self.data,
            period=self.p.st_period,
            multiplier=self.p.st_mult
        )

        # ATR
        self.atr = bt.indicators.ATR(self.data, period=14)

        self.order = None
        self.prev_up = None  # price > st on previous bar

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates.

        This callback method is invoked when an order's status changes.
        It updates trade counters for completed orders and clears the
        pending order reference.

        Args:
            order: The Order object whose status has changed.

        Order Status Handling:
            - Submitted/Accepted: Ignore, still waiting for execution
            - Completed: Increment buy_count or sell_count based on order type
            - Other: Clear order reference

        The order reference is cleared after processing to allow new orders
        to be placed in subsequent bars.
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

        This method is called on every bar of the data feed and implements
        the core trading strategy:

        1. Track bar progression
        2. Skip if there's a pending order
        3. Detect price vs SuperTrend line crossover
        4. Generate entry/exit signals based on crossover

        Trading Rules:
            - No action if there's a pending order
            - Initialize prev_up on first bar (no trading)
            - **Bullish Crossover** (price crosses above ST from below):
                - Enter long if flat
                - Close short position if short
            - **Bearish Crossover** (price crosses below ST from above):
                - Close long position if long
            - Update prev_up for next bar's crossover detection

        The strategy only goes long (no short selling), using the SuperTrend
        line as a trailing stop-loss that follows the trend.
        """
        self.bar_num += 1

        if self.order:
            return

        price = float(self.data.close[0])
        st_val = float(self.st.st[0])
        up_now = price > st_val

        if self.prev_up is None:
            self.prev_up = up_now
            return

        # Long entry: Price breaks above ST line from below
        if up_now and not self.prev_up:
            if not self.position:
                self.order = self.buy(size=self.p.stake)
            elif self.position.size < 0:
                self.order = self.close()

        # Short exit: Price breaks below ST line from above
        elif not up_now and self.prev_up:
            if self.position.size > 0:
                self.order = self.close()

        self.prev_up = up_now


def test_supertrend_indicator_strategy():
    """Test the SuperTrend indicator strategy.

    This test function:
        1. Loads Oracle stock price data (2010-2014)
        2. Runs the SuperTrend strategy with default parameters
        3. Collects performance metrics (Sharpe ratio, returns, drawdown)
        4. Validates results against expected values

    Test Configuration:
        - Data: Oracle (ORCL) daily prices from 2010-01-01 to 2014-12-31
        - Initial Capital: $100,000
        - Position Size: 10 shares per trade
        - Commission: 0.1% per trade
        - SuperTrend: period=20, multiplier=3.0
        - ATR: 14-period

    Expected Results:
        - bar_num: 1237 bars processed
        - final_value: $99,977.89 (small loss)
        - sharpe_ratio: -0.0916 (negative risk-adjusted return)
        - annual_return: -0.0044% (small annual loss)
        - max_drawdown: 16.62%

    Raises:
        AssertionError: If any metric does not match expected value within tolerance.

    Note:
        Tolerance levels: final_value (0.01), other metrics (1e-6)
        The negative results suggest this simple SuperTrend strategy
        underperforms on this particular dataset and timeframe.
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
    cerebro.addstrategy(SuperTrendIndicatorStrategy)
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
    print("SuperTrend Indicator Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1237, f"Expected bar_num=1237, got {strat.bar_num}"
    assert abs(final_value - 99977.89) < 0.01, f"Expected final_value=99977.89, got {final_value}"
    assert abs(sharpe_ratio - (-0.09158071580164015)) < 1e-6, f"Expected sharpe_ratio=-0.09158071580164015, got {sharpe_ratio}"
    assert abs(annual_return - (-4.432414175552991e-05)) < 1e-6, f"Expected annual_return=-4.432414175552991e-05, got {annual_return}"
    assert abs(max_drawdown - 0.16618133797700763) < 1e-6, f"Expected max_drawdown=0.16618133797700763, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("SuperTrend Indicator Strategy Test")
    print("=" * 60)
    test_supertrend_indicator_strategy()
