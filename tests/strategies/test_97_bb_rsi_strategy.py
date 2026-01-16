#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Bollinger Bands + RSI Strategy Test Module.

This module tests the BbRsi (Bollinger Bands + Relative Strength Index) strategy,
which combines mean-reversion signals from Bollinger Bands with momentum
confirmation from RSI to generate trading signals.

Strategy Overview:
    This is a mean-reversion strategy that buys when price is oversold (below
    lower Bollinger Band AND RSI < 30) and sells when price is overbought (above
    upper Bollinger Band OR RSI > 70). The strategy only takes long positions.

Entry Logic:
    - Buy when: RSI < rsi_oversold (default 30) AND close < lower Bollinger Band
    - This identifies oversold conditions with price support

Exit Logic:
    - Sell when: RSI > rsi_overbought (default 70) OR close > upper Bollinger Band
    - This exits on overbought conditions or price resistance

Test Data:
    - Symbol: Oracle Corporation (ORCL)
    - Period: 2010-01-01 to 2014-12-31
    - Data source: orcl-1995-2014.txt CSV file

Reference:
    backtrader-strategies-compendium/strategies/BbAndRsi.py

Example:
    >>> test_bb_rsi_strategy()
    Bollinger Bands + RSI Strategy Backtest Results:
    ...
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files by searching multiple directory paths.

    Searches for data files in several common locations relative to the
    current script directory, avoiding relative path failures when tests
    are run from different working directories.

    Search order:
        1. Same directory as script
        2. Parent directory
        3. datas/ subdirectory of script directory
        4. datas/ subdirectory of parent directory

    Args:
        filename (str): Name of the data file to locate (e.g., "orcl-1995-2014.txt").

    Returns:
        Path: Absolute Path object pointing to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any search path.

    Example:
        >>> path = resolve_data_path("orcl-1995-2014.txt")
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


class BbRsiStrategy(bt.Strategy):
    """Bollinger Bands + RSI mean-reversion strategy.

    This strategy implements a classic mean-reversion approach combining two
    complementary technical indicators:
    - Bollinger Bands: Identify price extremes relative to recent volatility
    - RSI: Identify momentum extremes (overbought/oversold conditions)

    Strategy Logic:
        Long-only mean reversion that buys on oversold conditions and exits
        on overbought conditions or price returning to the mean.

    Entry Conditions (Long):
        - RSI < rsi_oversold (default 30): Indicates oversold momentum
        - Close < lower Bollinger Band: Indicates price below statistical range
        - Both conditions must be true simultaneously (AND logic)

    Exit Conditions:
        - RSI > rsi_overbought (default 70): Indicates overbought momentum
        - Close > upper Bollinger Band: Indicates price above statistical range
        - Either condition triggers exit (OR logic)

    Position Management:
        - Fixed position size: stake parameter (default 10 shares/contracts)
        - Only one position at a time (long-only)
        - No pyramiding or partial exits

    Attributes:
        rsi (bt.indicators.RSI): RSI indicator with configurable period.
        bbands (bt.indicators.BollingerBands): Bollinger Bands indicator with
            configurable period and deviation factor.
        order (bt.Order | None): Reference to pending order, or None if no order.
        bar_num (int): Counter for number of bars processed.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.

    Parameters:
        stake (int): Fixed position size for each trade (default: 10).
        bb_period (int): Bollinger Bands period in bars (default: 20).
        bb_devfactor (float): Standard deviation multiplier for bands (default: 2.0).
        rsi_period (int): RSI calculation period in bars (default: 14).
        rsi_oversold (float): RSI threshold for oversold condition (default: 30).
        rsi_overbought (float): RSI threshold for overbought condition (default: 70).

    Note:
        This strategy uses simple OR logic for exits, meaning positions will
        be closed as soon as either RSI becomes overbought OR price exceeds
        the upper band. This can lead to early exits during strong trends.
    """
    params = dict(
        stake=10,              # Fixed position size (shares/contracts per trade)
        bb_period=20,          # Bollinger Bands lookback period
        bb_devfactor=2.0,      # Standard deviation multiplier (2.0 = 2 sigma)
        rsi_period=14,         # RSI calculation period
        rsi_oversold=30,       # RSI threshold for buy signal (oversold)
        rsi_overbought=70,     # RSI threshold for sell signal (overbought)
    )

    def __init__(self):
        """Initialize the BbRsi strategy.

        Creates indicators and initializes tracking variables for orders
        and trade statistics.
        """
        # Create RSI indicator for momentum analysis
        self.rsi = bt.indicators.RSI(self.data, period=self.p.rsi_period)
        # Create Bollinger Bands for volatility-based price range
        self.bbands = bt.indicators.BollingerBands(
            self.data, period=self.p.bb_period, devfactor=self.p.bb_devfactor
        )

        # Initialize tracking variables
        self.order = None      # Track pending order
        self.bar_num = 0       # Count bars processed
        self.buy_count = 0     # Count buy orders executed
        self.sell_count = 0    # Count sell orders executed

    def notify_order(self, order):
        """Handle order status updates.

        Called by backtrader when order status changes. Updates buy/sell counters
        when orders are completed and clears the pending order reference to allow
        new orders to be placed.

        Args:
            order (bt.Order): The order object with updated status. Contains
                            information about execution price, status, etc.

        Note:
            - Ignores Submitted and Accepted statuses (order still pending)
            - Only processes Completed orders to update statistics
            - Always clears self.order reference to allow new orders
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

        Implements the core Bollinger Bands + RSI mean-reversion strategy.

        Flow:
            1. Increment bar counter
            2. Check if pending order exists - if so, wait for execution
            3. If no position: Check entry conditions (oversold)
            4. If has position: Check exit conditions (overbought)

        Entry Logic:
            - Buy when RSI < rsi_oversold AND close < lower Bollinger Band
            - Fixed position size: stake parameter

        Exit Logic:
            - Sell when RSI > rsi_overbought OR close > upper Bollinger Band
            - Closes entire position (no partial exits)

        Raises:
            None: All exceptions handled by backtrader framework.
        """
        self.bar_num += 1

        # Only proceed if no pending order
        if self.order:
            return

        if not self.position:
            # ENTRY LOGIC: No position, look for buy opportunity
            # Buy when both oversold conditions are met
            if self.rsi[0] < self.p.rsi_oversold and self.data.close[0] < self.bbands.bot[0]:
                self.order = self.buy(size=self.p.stake)
        else:
            # EXIT LOGIC: Have position, look for exit signal
            # Exit when either overbought condition is met (OR logic)
            if self.rsi[0] > self.p.rsi_overbought or self.data.close[0] > self.bbands.top[0]:
                self.order = self.close()


def test_bb_rsi_strategy():
    """Test the Bollinger Bands + RSI mean-reversion strategy.

    This test validates the BbRsiStrategy implementation by running a historical
    backtest on Oracle stock data and verifying performance metrics match
    expected values.

    Test Process:
        1. Create Cerebro backtesting engine
        2. Load Oracle (ORCL) stock data from 2010-2014
        3. Add BbRsiStrategy with default parameters
        4. Set initial capital to 100,000
        5. Configure commission (0.1% per trade)
        6. Attach performance analyzers (Sharpe, Returns, DrawDown)
        7. Run backtest
        8. Validate results against expected values

    Expected Results:
        - bar_num: 1238
        - final_value: 100120.94 (slight profit over 5 years)
        - sharpe_ratio: 1.1614145060616812
        - annual_return: 0.0002423417652493005 (~0.024% annualized)
        - max_drawdown: 0.033113065059066485 (~3.3%)

    Interpretation:
        The strategy shows minimal returns during this 5-year period, suggesting
        that the simple mean-reversion approach may not be effective for this
        stock/time period without optimization. Low drawdown indicates low risk.

    Raises:
        AssertionError: If any performance metric deviates from expected value.
        FileNotFoundError: If orcl-1995-2014.txt data file cannot be located.

    Note:
        Test uses strict tolerance (1e-6) for most metrics, 0.01 for final_value
        to account for floating-point precision differences.
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
    cerebro.addstrategy(BbRsiStrategy)
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

    # Display results
    print("=" * 50)
    print("Bollinger Bands + RSI Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assert expected values with specified tolerances
    assert strat.bar_num == 1238, f"Expected bar_num=1238, got {strat.bar_num}"
    assert abs(final_value - 100120.94) < 0.01, f"Expected final_value=100000.0, got {final_value}"
    assert abs(sharpe_ratio - (1.1614145060616812)) < 1e-6, f"Expected sharpe_ratio=0.0, got {sharpe_ratio}"
    assert abs(annual_return - (0.0002423417652493005)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.033113065059066485) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Bollinger Bands + RSI Strategy Test")
    print("=" * 60)
    test_bb_rsi_strategy()
