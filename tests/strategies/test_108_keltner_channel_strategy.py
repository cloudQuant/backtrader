#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for Keltner Channel trading strategy.

This module implements and tests a trading strategy based on the Keltner Channel
indicator, a volatility-based technical analysis tool developed by Chester Keltner
in 1960 and later modified by Linda Raschke. The channel consists of three lines:
a middle line (typically an EMA) and upper/lower bands based on Average True Range (ATR).

Keltner Channel Overview:
    - Middle Line: Exponential Moving Average (EMA) of price
    - Upper Band: EMA + (ATR × multiplier)
    - Lower Band: EMA - (ATR × multiplier)
    - Bands expand and contract based on volatility (ATR)

Trading Application:
    - Price above upper band: Strong bullish momentum (potential breakout)
    - Price below lower band: Strong bearish momentum (potential breakdown)
    - Price between bands: Normal trading range
    - Band width indicates volatility: Wide bands = high volatility, narrow = low

Unlike Bollinger Bands which use standard deviation, Keltner Channels use ATR,
making them more responsive to price changes and gap moves. The indicator is
particularly effective for:
    - Trend following strategies (breakout trades)
    - Identifying overbought/oversold conditions
    - Setting trailing stop-loss levels
    - Measuring market volatility

Example:
    Run the test directly::

        python test_108_keltner_channel_strategy.py

    Or use pytest::

        pytest tests/strategies/test_108_keltner_channel_strategy.py -v
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


class KeltnerChannelIndicator(bt.Indicator):
    """Keltner Channel volatility-based indicator.

    The Keltner Channel is a technical analysis indicator that consists of
    three lines designed to capture price volatility and trend direction.
    Unlike Bollinger Bands which use standard deviation, Keltner Channels
    use the Average True Range (ATR) to determine band width, making them
    more responsive to price gaps and limit moves.

    Construction:
        - Middle Line (mid): Exponential Moving Average (EMA) of close prices
        - Upper Band (top): EMA + (ATR × multiplier)
        - Lower Band (bot): EMA - (ATR × multiplier)

    Interpretation:
        - Price above upper band: Strong bullish momentum, potential breakout
        - Price below lower band: Strong bearish momentum, potential breakdown
        - Price between bands: Trading within normal volatility range
        - Expanding bands: Increasing volatility
        - Contracting bands: Decreasing volatility (potential squeeze)

    Lines:
        mid: Middle line (Exponential Moving Average). Serves as the baseline
            for the channel and represents the average price over the period.
        top: Upper band (mid + atr_mult * ATR). Acts as dynamic resistance
            and breakout level for long entries.
        bot: Lower band (mid - atr_mult * ATR). Acts as dynamic support
            and breakdown level for short entries.

    Parameters:
        period (int): Period for the EMA middle line calculation (default: 20).
            Shorter periods make the channel more responsive to price changes.
        atr_mult (float): Multiplier for ATR band width (default: 2.0).
            Higher values create wider bands, fewer signals.
            Lower values create narrower bands, more signals.
        atr_period (int): Period for ATR calculation (default: 14).
            Measures market volatility over this lookback period.

    Example:
        >>> # Create Keltner Channel with custom parameters
        >>> kc = KeltnerChannelIndicator(self.data, period=20, atr_mult=2.5)
        >>> # Access channel values
        >>> print(f"Upper: {kc.top[0]}, Mid: {kc.mid[0]}, Lower: {kc.bot[0]}")

    Note:
        The Keltner Channel is particularly effective in trending markets
        and for identifying breakout opportunities. Consider combining with
        other indicators for confirmation in ranging markets.
    """
    lines = ('mid', 'top', 'bot')
    params = dict(period=20, atr_mult=2.0, atr_period=14)

    def __init__(self):
        """Initialize Keltner Channel indicator calculations.

        Creates the three lines of the Keltner Channel:
        1. Middle line as EMA of closing prices
        2. ATR to measure volatility
        3. Upper and lower bands by adding/subtracting ATR multiple from EMA
        """
        # Calculate middle line as EMA of closing prices
        # This serves as the baseline for the channel
        self.l.mid = bt.indicators.EMA(self.data.close, period=self.p.period)

        # Calculate Average True Range to measure volatility
        # ATR captures price movement including gaps and limit moves
        atr = bt.indicators.ATR(self.data, period=self.p.atr_period)

        # Calculate upper and lower bands
        # Upper band: EMA + (ATR × multiplier) - dynamic resistance
        # Lower band: EMA - (ATR × multiplier) - dynamic support
        self.l.top = self.l.mid + self.p.atr_mult * atr
        self.l.bot = self.l.mid - self.p.atr_mult * atr


class KeltnerChannelStrategy(bt.Strategy):
    """Keltner Channel breakout trading strategy.

    This strategy implements a trend-following system based on Keltner Channel
    breakouts. It takes long positions when price breaks above the upper band,
    indicating strong bullish momentum and the start of a potential uptrend.
    Positions are closed when price falls back below the middle line (EMA),
    suggesting the trend has weakened or reversed.

    Trading Logic:
        The strategy captures breakout moves by entering when price shows
        sufficient strength to break through the upper Keltner Channel band.
        This breakout often precedes significant uptrends as it indicates
        buying pressure strong enough to overcome normal volatility ranges.

    Entry Conditions:
        - No current position exists
        - Price closes above the upper Keltner Channel band
        - This indicates strong bullish momentum and potential trend start

    Exit Conditions:
        - Currently in long position
        - Price closes below the middle line (EMA)
        - This suggests trend weakening or reversal

    Parameters:
        stake (int): Number of shares/units per trade (default: 10).
            Controls position sizing and risk per trade.
        period (int): Period for the EMA middle line (default: 20).
            Shorter periods create more responsive channels, more signals.
        atr_mult (float): Multiplier for ATR band width (default: 2.0).
            Higher values create wider bands, requiring stronger moves for breakout.
            Lower values create narrower bands, generating more signals.

    Attributes:
        kc (KeltnerChannelIndicator): The Keltner Channel indicator instance
            providing the upper, middle, and lower band values.
        order (bt.Order): Reference to the currently pending order, or None
            if no order is pending.
        bar_num (int): Counter tracking the total number of bars processed
            during the backtest.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(KeltnerChannelStrategy, stake=100, period=20, atr_mult=2.5)
        >>> results = cerebro.run()

    Note:
        This strategy performs best in markets with clear trending behavior
        and can experience whipsaws in ranging or choppy markets. Consider
        adding filters like ADX for trend strength or volume confirmation
        to reduce false breakouts.
    """
    params = dict(
        stake=10,
        period=20,
        atr_mult=2.0,
    )

    def __init__(self):
        """Initialize the strategy and set up indicators.

        Creates the Keltner Channel indicator with specified parameters
        and initializes all tracking variables for monitoring strategy
        performance and order status.
        """
        # Initialize Keltner Channel indicator
        # Uses specified period for EMA and multiplier for band width
        self.kc = KeltnerChannelIndicator(
            self.data, period=self.p.period, atr_mult=self.p.atr_mult
        )

        # Initialize tracking variables
        self.order = None  # Reference to pending order
        self.bar_num = 0   # Total bars processed
        self.buy_count = 0  # Total buy orders executed
        self.sell_count = 0  # Total sell orders executed

    def notify_order(self, order):
        """Handle order status updates.

        This method is called by the backtrader engine whenever an order's
        status changes. It updates the buy/sell counters when orders are
        completed and clears the order reference to allow new orders.

        Args:
            order (bt.Order): The order object with updated status information.
                Possible statuses include: Submitted, Accepted, Completed,
                Canceled, Expired, Margin, Rejected.

        Note:
            - Orders in Submitted or Accepted status are still pending execution
            - Only Completed orders increment buy/sell counters
            - Order reference is cleared after processing to enable new orders
        """
        # Ignore orders still waiting to be executed
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        # Track completed orders
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

        # Clear order reference to allow new orders
        self.order = None

    def next(self):
        """Execute trading logic for each bar.

        This method is called for every bar of data after all indicators
        have been calculated. It implements the core Keltner Channel strategy:
        1. Check for pending orders and wait if one exists
        2. Generate buy signal when price breaks above upper band
        3. Generate exit signal when price falls below middle band

        The strategy only takes long positions, aiming to capture bullish
        breakouts and trends. The middle band (EMA) serves as a trailing
        stop-loss level once in a position.
        """
        self.bar_num += 1

        # Wait for pending order to complete before placing new orders
        if self.order:
            return

        if not self.position:
            # No current position - look for breakout entry signal
            # Price breaks above upper band indicates strong bullish momentum
            if self.data.close[0] > self.kc.top[0]:
                # Enter long position with specified stake size
                self.order = self.buy(size=self.p.stake)
        else:
            # Currently in position - look for exit signal
            # Price falls below middle band suggests trend weakening
            if self.data.close[0] < self.kc.mid[0]:
                # Close entire position
                self.order = self.close()


def test_keltner_channel_strategy():
    """Test the Keltner Channel strategy backtest execution and performance.

    This test function validates the KeltnerChannelStrategy by running a complete
    backtest on historical Oracle Corporation stock data from 2010-2014. It
    verifies that the strategy produces consistent results with expected
    performance metrics, ensuring the indicator calculation and trading logic
    work correctly.

    Test Procedure:
        1. Initialize Cerebro backtesting engine
        2. Load historical Oracle stock data (2010-2014)
        3. Configure broker with initial capital and commission structure
        4. Add KeltnerChannelStrategy with default parameters (period=20, atr_mult=2.0)
        5. Attach performance analyzers (Sharpe Ratio, Returns, Drawdown)
        6. Execute backtest and collect results
        7. Validate metrics against expected values

    Expected Results:
        - Total bars processed: 1238
        - Final portfolio value: ~100039.51
        - Sharpe Ratio: ~0.2796
        - Annual Return: ~0.0000792
        - Maximum Drawdown: ~5.50%

    Raises:
        AssertionError: If any performance metric does not match expected
            values within specified tolerance levels.

    Note:
        Tolerance levels: 0.01 for final_value (accounting for rounding),
        1e-6 for all other metrics (high precision for comparison).
    """
    # Initialize Cerebro backtesting engine
    cerebro = bt.Cerebro()

    # Load historical Oracle stock data
    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    cerebro.adddata(data)

    # Add strategy with default parameters
    cerebro.addstrategy(KeltnerChannelStrategy)

    # Configure broker settings
    cerebro.broker.setcash(100000)  # Initial capital: $100,000
    cerebro.broker.setcommission(commission=0.001)  # 0.1% commission per trade

    # Attach performance analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    # Run backtest
    results = cerebro.run()
    strat = results[0]

    # Extract performance metrics
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    # Display results
    print("=" * 50)
    print("Keltner Channel Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Validate results against expected values
    # Using precise assertions with tolerance levels
    assert strat.bar_num == 1238, f"Expected bar_num=1238, got {strat.bar_num}"
    assert abs(final_value - 100039.51) < 0.01, f"Expected final_value=100039.51, got {final_value}"
    assert abs(sharpe_ratio - (0.2795635163868808)) < 1e-6, f"Expected sharpe_ratio=0.2796, got {sharpe_ratio}"
    assert abs(annual_return - (7.919528281735741e-05)) < 1e-6, f"Expected annual_return=7.92e-05, got {annual_return}"
    assert abs(max_drawdown - 0.05497965839460319) < 1e-6, f"Expected max_drawdown=0.0550, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Keltner Channel Strategy Test")
    print("=" * 60)
    test_keltner_channel_strategy()
