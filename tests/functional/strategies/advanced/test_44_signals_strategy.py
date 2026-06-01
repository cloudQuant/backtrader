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

Data Used:
    Daily OHLCV bars from ``2005-2006-day-001.txt`` loaded via
    ``bt.feeds.BacktraderCSVData``. Only the 2005-01-01 to 2006-12-31 window
    is used (single data feed named ``DATA``, daily timeframe, no resampling).
    The test is parametrized over ``runonce=True`` and ``runonce=False`` so the
    vectorized and event-driven engines are both exercised on the same data.

Strategy Principle:
    This is a declarative, signal-driven trend-following setup rather than a
    full ``Strategy`` subclass. The ``bt.indicators.SMACloseSignal`` indicator emits
    ``price - SMA(period)``; a positive value means price trades above its
    moving average (bullish) and a negative value means below (bearish). Wired
    through ``cerebro.add_signal(bt.SIGNAL_LONG, ...)``, a positive signal opens
    a long position and a non-positive signal exits it, with position size
    driven by the signal magnitude. Risk control relies solely on the signal
    sign flipping; no explicit stop loss is used.

Strategy Logic:
    1. ``resolve_data_path`` locates the CSV data file across candidate
       directories.
    2. ``bt.indicators.SMACloseSignal.__init__`` defines the single ``signal`` line as the
       price minus its ``period``-length bt.indicators.SMA.
    3. ``test_signals_strategy`` builds cerebro with $50,000 cash, adds the long
       signal with a 30-period SMA, attaches Sharpe/Returns/DrawDown/Trade
       analyzers, runs the backtest, and extracts the metrics.
    4. The test asserts that total trades, final value, Sharpe ratio, annual
       return, and max drawdown match the recorded expectations.

Example:
    Run the test directly::

        python test_44_signals_strategy.py

    Or use pytest::

        pytest tests/strategies/test_44_signals_strategy.py -v
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import backtrader as bt

import datetime
from pathlib import Path
import pytest

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
        BASE_DIR.parent.parent.parent / filename,
        BASE_DIR / "datas" / filename,
        BASE_DIR.parent.parent.parent / "datas" / filename,
    ]
    for p in search_paths:
        if p.exists():
            return p
    raise FileNotFoundError(f"Cannot find data file: {filename}")

@pytest.mark.parametrize("runonce", [True, False])
def test_signals_strategy(runonce):
    """Test the signal-based strategy functionality using cerebro.add_signal.

    This test validates the signal-based approach to trading strategies by
    using cerebro.add_signal() with the bt.indicators.SMACloseSignal indicator. Unlike
    traditional Strategy classes, this declarative approach uses indicator
    values to drive trading decisions directly.

    Test Procedure:
        1. Initialize Cerebro backtesting engine
        2. Set initial capital to $50,000
        3. Load historical daily data (2005-2006)
        4. Add long signal using bt.indicators.SMACloseSignal with 30-period SMA
        5. Attach performance analyzers
        6. Execute backtest and validate signal-based trading

    Signal Logic:
        The bt.indicators.SMACloseSignal calculates: signal = price - SMA(30)
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
    # bt.indicators.SMACloseSignal: Custom indicator calculating price - SMA(30)
    # period=30: Use 30-period SMA for signal calculation
    cerebro.add_signal(bt.SIGNAL_LONG, bt.indicators.SMACloseSignal, period=30)

    # Attach performance analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    # Run backtest
    print("Starting backtest...")
    results = cerebro.run(runonce=runonce)
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
