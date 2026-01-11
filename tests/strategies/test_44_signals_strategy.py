#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for signal-based trading strategy using cerebro.add_signal.

This module tests the signal functionality in backtrader, which provides an
alternative way to implement trading strategies without writing a full Strategy
class. Instead, signals are defined as indicators that return positive/negative
values, and cerebro.add_signal() is used to add long/short signals.

Understanding Signal-Based Strategies:
    Unlike traditional strategy classes that define next() methods with explicit
    buy/sell logic, signal-based strategies use indicator values to drive
    trading decisions. The signal indicator's value determines position sizing:
    - Positive signal: Long position (size proportional to signal value)
    - Negative signal: Short position (size proportional to signal value)
    - Zero signal: No position

Key Benefits:
    - Simplified strategy implementation for indicator-based systems
    - No need to write full Strategy class for simple logic
    - Declarative approach: define signals, let backtrader handle execution
    - Easier to test and prototype indicator combinations

Signal Types:
    - SIGNAL_LONG: Take long position when signal is positive
    - SIGNAL_LONGSHORT: Take long or short based on signal sign
    - SIGNAL_SHORT: Take short position when signal is negative
    - SIGNAL_LONGEXIT: Exit long when signal becomes negative

Use Cases:
    - Simple indicator-based strategies (e.g., price above SMA = long)
    - Factor-based strategies combining multiple signals
    - Rapid prototyping of trading ideas
    - Portfolio construction using signal scores

Signal vs Strategy:
    Signal-based approaches are best for:
    * Simple, indicator-driven rules
    * Portfolio-level signal aggregation
    * When you want declarative rather than imperative code

    Strategy classes are better for:
    * Complex multi-stage logic
    * State-dependent trading rules
    * Advanced order management (OCO, brackets, etc.)
    * Custom position sizing logic

Reference:
    backtrader-master2/samples/signals-strategy/signals-strategy.py

Example:
    Run the test directly::

        python test_44_signals_strategy.py

    Or use pytest::

        pytest tests/strategies/test_44_signals_strategy.py -v
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching common directories.

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


class SMACloseSignal(bt.Indicator):
    """Simple Moving Average (SMA) close price signal indicator.

    This indicator calculates the difference between the current price and
    its Simple Moving Average (SMA). The resulting signal can be used with
    cerebro.add_signal() to implement trend-following strategies.

    Signal Calculation:
        signal = price - SMA(period)

    Signal Interpretation:
        - Positive signal (> 0): Price is above SMA (bullish)
        - Negative signal (< 0): Price is below SMA (bearish)
        - Signal magnitude: Distance from SMA (strength of trend)

    Trading Logic:
        When used with SIGNAL_LONG:
        - Signal > 0: Take long position (price above average = uptrend)
        - Signal < 0: Exit position (price below average = downtrend)

        The actual position size is proportional to the signal value,
        meaning stronger trends (larger signal) result in larger positions.

    Lines:
        signal: The calculated signal value (price - SMA).

    Parameters:
        period (int): Period for the SMA calculation (default: 30).
            Longer periods produce smoother signals with fewer crossovers.
            Shorter periods produce more responsive signals with more noise.

    Example:
        >>> # Add SMA-based long signal to cerebro
        >>> cerebro.add_signal(bt.SIGNAL_LONG, SMACloseSignal, period=30)
        >>>
        >>> # Signal is positive when price > 30-period SMA
        >>> # Results in long position during uptrends

    Note:
        This is a simple trend-following signal. It performs well in
        trending markets but can whipsaw in ranging markets. Consider
        adding filters or combining with other signals for better results.
    """

    lines = ('signal',)
    params = (('period', 30),)

    def __init__(self):
        """Calculate the SMA signal indicator.

        The signal is calculated as the difference between the current
        price and its Simple Moving Average. This provides a measure
        of whether price is above or below its average value.

        Signal = price - SMA(period)

        A positive signal indicates price is trading above the moving
        average (bullish), while negative indicates below (bearish).
        """
        # Calculate signal as price minus SMA
        # Positive when price above SMA (bullish trend)
        # Negative when price below SMA (bearish trend)
        # Magnitude indicates distance from average (trend strength)
        self.lines.signal = self.data - bt.indicators.SMA(period=self.p.period)


def test_signals_strategy():
    """Test the signal-based strategy functionality using cerebro.add_signal.

    This test validates the signal-based approach to trading strategies by
    using cerebro.add_signal() with the SMACloseSignal indicator. Unlike
    traditional Strategy classes, this declarative approach uses indicator
    values to drive trading decisions directly.

    Test Procedure:
        1. Initialize Cerebro backtesting engine
        2. Set initial capital to $50,000
        3. Load historical daily data (2005-2006)
        4. Add long signal using SMACloseSignal with 30-period SMA
        5. Attach performance analyzers
        6. Execute backtest and validate signal-based trading

    Signal Logic:
        The SMACloseSignal calculates: signal = price - SMA(30)
        - Signal > 0: Price above SMA → Take long position
        - Signal < 0: Price below SMA → Exit position

        Position sizing is proportional to signal strength (distance from SMA),
        meaning the strategy holds larger positions when price is further above
        the moving average.

    Expected Results:
        - Total trades: 21 (entry/exit pairs from SMA crossovers)
        - Final portfolio value: ~50607.58 (small profit)
        - Sharpe Ratio: ~-12.58 (negative due to specific signal behavior)
        - Annual Return: ~0.596% (small positive return)
        - Maximum Drawdown: ~64.01%

    Signal-Based vs Traditional Strategy:
        This test demonstrates that signal-based strategies can produce
        equivalent results to traditional Strategy classes but with
        simpler, more declarative code. The approach is particularly
        useful for:
        - Rapid prototyping of indicator-based ideas
        - Factor-based portfolio construction
        - Simple trend-following systems

    Raises:
        AssertionError: If any performance metric deviates from expected
            values within specified tolerance levels.

    Note:
        Tolerance levels: 0.01 for final_value (accounting for rounding),
        1e-6 for all other metrics (high precision for comparison).
    """
    # Initialize Cerebro backtesting engine
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(50000.0)

    # Load historical daily price data
    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="DATA")

    # Add signal-based strategy using cerebro.add_signal
    # SIGNAL_LONG: Take long position when signal is positive
    # SMACloseSignal: Custom indicator calculating price - SMA(30)
    # period=30: Use 30-period SMA for signal calculation
    cerebro.add_signal(bt.SIGNAL_LONG, SMACloseSignal, period=30)

    # Attach performance analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    # Run backtest
    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Extract performance metrics
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Display results
    print("=" * 50)
    print("Signals Strategy Backtest Results:")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Validate results against expected values
    # These values confirm the signal-based approach is working correctly
    assert total_trades == 21, f"Expected total_trades=21, got {total_trades}"
    assert abs(final_value - 50607.58) < 0.01, f"Expected final_value=50607.58, got {final_value}"
    assert abs(sharpe_ratio - (-12.583680955595796)) < 1e-6, f"Expected sharpe_ratio=-12.58, got {sharpe_ratio}"
    assert abs(annual_return - 0.005962524308781271) < 1e-6, f"Expected annual_return=0.00596, got {annual_return}"
    assert abs(max_drawdown - 0.6401411217499897) < 1e-6, f"Expected max_drawdown=0.6401, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Signals Strategy Test")
    print("=" * 60)
    test_signals_strategy()
