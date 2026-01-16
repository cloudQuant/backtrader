#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for Parabolic SAR (Stop and Reverse) indicator strategy.

This module implements and tests a trading strategy based on the Parabolic SAR
indicator, which is a technical analysis method used to determine trend direction
and potential reversals. The Parabolic SAR was developed by J. Welles Wilder Jr.
and is particularly useful in trending markets.

Reference:
    strategies_backtrader/SAR (STOP AND REVERSE) METHOD.ipynb

The Parabolic SAR indicator:
    - Uses a series of dots placed above or below price bars
    - Dots below price indicate bullish trend (long position)
    - Dots above price indicate bearish trend (short position)
    - When dots flip from below to above, it generates a sell signal
    - When dots flip from above to below, it generates a buy signal
    - The acceleration factor (af) increases as the trend continues
    - Provides trailing stop-loss levels that adjust dynamically

Example:
    Run the test directly::

        python test_106_parabolic_sar_strategy.py

    Or use pytest::

        pytest tests/strategies/test_106_parabolic_sar_strategy.py -v
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the full path to a data file by searching common locations.

    This function attempts to locate a data file by searching in several
    common directories relative to the current test file location. This
    allows tests to run from different locations while still finding data.

    Args:
        filename: Name of the data file to locate (e.g., 'orcl-1995-2014.txt').

    Returns:
        Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths. The error message includes the filename being searched.

    Search Order:
        1. Current directory (tests/strategies/)
        2. Parent directory (tests/)
        3. datas/ subdirectory of current directory
        4. datas/ subdirectory of parent directory

    Example:
        >>> path = resolve_data_path('orcl-1995-2014.txt')
        >>> print(path)
        /path/to/backtrader/tests/datas/orcl-1995-2014.txt
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


class ParabolicSarStrategy(bt.Strategy):
    """Parabolic SAR (Stop and Reverse) indicator-based trading strategy.

    This strategy implements a trend-following system using the Parabolic SAR
    indicator. The Parabolic SAR is particularly effective in trending markets
    as it provides clear entry and exit signals while also functioning as a
    trailing stop-loss mechanism.

    Trading Logic:
        The strategy uses crossover signals between price and SAR:
        - When price crosses ABOVE SAR from below: Enter long position
        - When price crosses BELOW SAR from above: Exit long position

    Entry Conditions:
        - No current position exists
        - Price closes above the SAR line (bullish signal)

    Exit Conditions:
        - Currently in long position
        - Price closes below the SAR line (bearish signal/reversal)

    Parameters:
        stake (int): Number of shares/units per trade (default: 10).
        af (float): Initial acceleration factor for SAR calculation (default: 0.02).
            The acceleration factor determines how quickly the SAR moves toward price.
            Typical values range from 0.02 to 0.03.
        afmax (float): Maximum acceleration factor (default: 0.2).
            The AF increases each time a new high is made (in uptrend) until it
            reaches this maximum value.

    Attributes:
        sar (bt.indicators.ParabolicSAR): The Parabolic SAR indicator instance
            providing the SAR values for trend identification.
        crossover (bt.indicators.CrossOver): Indicator detecting when price
            crosses above/below the SAR line. Returns positive on bullish
            crossover, negative on bearish crossover.
        order (bt.Order): Reference to the currently pending order. None if
            no order is pending.
        bar_num (int): Counter tracking the total number of bars processed
            during the backtest.
        buy_count (int): Total number of buy orders executed during the
            backtest period.
        sell_count (int): Total number of sell orders executed during the
            backtest period.

    Note:
        The Parabolic SAR is most effective in strong trending markets and
        can produce false signals in ranging or choppy markets. Consider
        combining with other indicators for filtering signals in sideways markets.

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(ParabolicSarStrategy, stake=100, af=0.022, afmax=0.2)
        >>> results = cerebro.run()
    """
    params = dict(
        stake=10,
        af=0.02,
        afmax=0.2,
    )

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables.

        Sets up the Parabolic SAR indicator with the specified parameters,
        creates a crossover detector, and initializes all tracking variables
        for monitoring strategy performance.
        """
        # Initialize Parabolic SAR indicator with acceleration factor parameters
        # af: Starting acceleration factor, increases during trend
        # afmax: Maximum acceleration factor cap
        self.sar = bt.indicators.ParabolicSAR(
            self.data, af=self.p.af, afmax=self.p.afmax
        )

        # Create crossover indicator to detect when price crosses SAR
        # Returns: > 0 when price crosses above SAR (bullish)
        #          < 0 when price crosses below SAR (bearish)
        self.crossover = bt.indicators.CrossOver(self.data.close, self.sar)

        # Initialize tracking variables
        self.order = None  # Reference to pending order
        self.bar_num = 0   # Total bars processed
        self.buy_count = 0  # Total buy orders executed
        self.sell_count = 0  # Total sell orders executed

    def notify_order(self, order):
        """Handle order status updates and track executed orders.

        This method is called by the backtrader engine whenever an order's
        status changes. It updates the buy/sell counters when orders are
        completed and clears the order reference.

        Args:
            order (bt.Order): The order object with updated status information.
                Possible statuses include: Submitted, Accepted, Completed,
                Canceled, Expired, Margin, Rejected.

        Note:
            - Orders in Submitted or Accepted status are still pending
            - Only Completed orders are counted in buy/sell statistics
            - The order reference is cleared after processing to allow new orders
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
        """Execute trading logic on each bar.

        This method is called for every bar of data after all indicators
        have been calculated. It implements the core Parabolic SAR strategy:
        1. Check for pending orders and wait if one exists
        2. Generate buy signal when price crosses above SAR
        3. Generate exit signal when price crosses below SAR

        The strategy only takes long positions, using the SAR as both
        entry signal generator and trailing stop-loss.
        """
        self.bar_num += 1

        # Wait for pending order to complete before placing new orders
        if self.order:
            return

        if not self.position:
            # No current position - look for entry signal
            # Price crosses above SAR indicates potential uptrend start
            if self.crossover[0] > 0:
                # Enter long position with specified stake size
                self.order = self.buy(size=self.p.stake)
        else:
            # Currently in position - look for exit signal
            # Price crosses below SAR indicates trend reversal
            if self.crossover[0] < 0:
                # Close entire position
                self.order = self.close()


def test_parabolic_sar_strategy():
    """Test the Parabolic SAR strategy implementation and performance.

    This test function validates the ParabolicSarStrategy by running a complete
    backtest on historical Oracle Corporation stock data from 2010-2014. It
    verifies that the strategy produces consistent results with expected
    performance metrics.

    Test Procedure:
        1. Initialize Cerebro backtesting engine
        2. Load historical Oracle stock data (2010-2014)
        3. Configure broker with initial capital and commission structure
        4. Add ParabolicSarStrategy with default parameters (af=0.02, afmax=0.2)
        5. Attach performance analyzers (Sharpe Ratio, Returns, Drawdown)
        6. Execute backtest and collect results
        7. Validate metrics against expected values

    Expected Results:
        - Total bars processed: 1255
        - Final portfolio value: ~100044.47
        - Sharpe Ratio: ~0.1577
        - Annual Return: ~0.0000891
        - Maximum Drawdown: ~14.47%

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
    cerebro.addstrategy(ParabolicSarStrategy)

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
    print("Parabolic SAR Strategy Backtest Results:")
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
    assert strat.bar_num == 1255, f"Expected bar_num=1255, got {strat.bar_num}"
    assert abs(final_value - 100044.47) < 0.01, f"Expected final_value=100044.47, got {final_value}"
    assert abs(sharpe_ratio - (0.15768877971108886)) < 1e-6, f"Expected sharpe_ratio=0.1577, got {sharpe_ratio}"
    assert abs(annual_return - (8.914473921766317e-05)) < 1e-6, f"Expected annual_return=8.91e-05, got {annual_return}"
    assert abs(max_drawdown - 0.1446509264396303) < 1e-6, f"Expected max_drawdown=0.1447, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Parabolic SAR Strategy Test")
    print("=" * 60)
    test_parabolic_sar_strategy()
