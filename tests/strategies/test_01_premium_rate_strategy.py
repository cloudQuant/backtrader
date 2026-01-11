#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Convertible bond premium rate moving average crossover strategy test.

This module tests a trading strategy that uses convertible bond conversion
premium rates to generate trading signals. The strategy calculates moving
averages on the conversion premium rate and executes trades based on
crossover signals.

Key Features:
    - Uses ExtendPandasFeed to load convertible bond data with custom fields
    - Implements PremiumRateCrossoverStrategy for dual moving average signals
    - Tests strategy performance using 113013.csv convertible bond data
    - Validates backtest results including Sharpe ratio, returns, and drawdown

Trading Logic:
    - Buy signal: Short-term MA crosses above long-term MA
    - Sell signal: Short-term MA crosses below long-term MA (close position)
    - Position sizing: 95% of available cash per trade
    - Commission: 0.03% per trade

Example:
    >>> from tests.strategies.test_01_premium_rate_strategy import test_premium_rate_strategy
    >>> test_premium_rate_strategy()
    Loading convertible bond data...
    Data range: 2020-01-02 00:00:00 to 2025-06-18 00:00:00, total 1384 records
    Starting backtest...
    ...
    All tests passed!
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt
from backtrader.comminfo import ComminfoFuturesPercent

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on the script directory to avoid relative path failures.

    This function searches for data files in multiple predefined locations,
    including the script directory, parent directory, and an optional
    environment-specified data directory. This makes tests more robust
    when run from different working directories.

    Args:
        filename (str): Name of the data file to locate (e.g., "113013.csv").

    Returns:
        Path: Absolute path to the located data file as a pathlib.Path object.

    Raises:
        FileNotFoundError: If the data file cannot be found in any search path.
            The error message includes the filename being searched for.

    Search Paths:
        1. Script directory: tests/strategies/{filename}
        2. Parent directory: tests/{filename}
        3. Datas directory: tests/datas/{filename}
        4. Environment directory: {BACKTRADER_DATA_DIR}/{filename} (if set)

    Example:
        >>> resolve_data_path("113013.csv")
        PosixPath('/path/to/backtrader/tests/strategies/113013.csv')
    """
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR.parent / "datas" / filename,
    ]

    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"Data file not found: {filename}")


class ExtendPandasFeed(bt.feeds.PandasData):
    """Extended Pandas data feed with convertible bond-specific fields.

    This custom data feed extends the standard Backtrader PandasData feed
    to support convertible bond data with additional fields for pure bond
    value, conversion value, and their respective premium rates.

    The feed maps DataFrame columns to Backtrader lines, enabling the
    strategy to access convertible bond-specific metrics during backtesting.

    Attributes:
        params (tuple): Parameter definitions specifying column indices in the
            input DataFrame. Maps standard OHLCV columns and custom bond fields.
        lines (tuple): Line definitions for data access in strategies.
            Includes pure_bond_value, convert_value, pure_bond_premium_rate,
            and convert_premium_rate.

    DataFrame Structure (after set_index):
        - Index: datetime (DateTimeIndex)
        - Column 0: open (float)
        - Column 1: high (float)
        - Column 2: low (float)
        - Column 3: close (float)
        - Column 4: volume (float)
        - Column 5: pure_bond_value (float) - Pure bond value
        - Column 6: convert_value (float) - Conversion value
        - Column 7: pure_bond_premium_rate (float) - Pure bond premium rate
        - Column 8: convert_premium_rate (float) - Conversion premium rate

    Example:
        >>> df = load_bond_data("113013.csv")
        >>> data = ExtendPandasFeed(dataname=df)
        >>> cerebro.adddata(data)
    """

    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', -1),
        ('pure_bond_value', 5),
        ('convert_value', 6),
        ('pure_bond_premium_rate', 7),
        ('convert_premium_rate', 8)
    )

    lines = ('pure_bond_value', 'convert_value',
             'pure_bond_premium_rate', 'convert_premium_rate')


class PremiumRateCrossoverStrategy(bt.Strategy):
    """Conversion premium rate moving average crossover strategy.

    This strategy implements a dual moving average crossover system using
    convertible bond conversion premium rates as the underlying data series.
    It generates buy signals when the short-term moving average crosses above
    the long-term moving average, and exit signals when the opposite crossover
    occurs.

    The strategy is designed specifically for convertible bond trading, where
    the conversion premium rate reflects the theoretical arbitrage profit
    potential from converting the bond to underlying shares.

    Attributes:
        premium_rate (LineSingle): The conversion premium rate data line from
            the first data feed.
        sma_short (SimpleMovingAverage): Short-term moving average indicator
            (default 10-period).
        sma_long (SimpleMovingAverage): Long-term moving average indicator
            (default 60-period).
        crossover (CrossOver): Crossover indicator that generates +1 when
            short MA crosses above long MA, and -1 for opposite crossover.
        order (Order): Reference to the current pending order, or None if
            no order is pending.
        bar_num (int): Counter tracking the total number of bars processed.
        buy_count (int): Counter tracking the total number of buy orders
            executed.
        sell_count (int): Counter tracking the total number of sell orders
            executed.

    Strategy Logic:
        1. Calculate short-term and long-term moving averages of the
           conversion premium rate
        2. Generate buy signal when short MA crosses above long MA
        3. Generate exit signal when short MA crosses below long MA
        4. Use 95% of available cash for position sizing on entry
        5. Only hold one position at a time (long-only)

    Parameters:
        short_period (int): Period for the short-term moving average.
            Default is 10.
        long_period (int): Period for the long-term moving average.
            Default is 60.

    Example:
        >>> cerebro.addstrategy(PremiumRateCrossoverStrategy,
        ...                    short_period=10, long_period=60)
    """

    params = (
        ('short_period', 10),
        ('long_period', 60),
    )

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables.

        Sets up the conversion premium rate data source, calculates moving
        averages, initializes the crossover indicator, and creates counters
        for tracking order execution and bar processing.

        Attributes Initialized:
            self.premium_rate (LineSingle): References the convert_premium_rate
                line from the first data feed.
            self.sma_short (SimpleMovingAverage): Short-period SMA calculated
                on the premium rate.
            self.sma_long (SimpleMovingAverage): Long-period SMA calculated
                on the premium rate.
            self.crossover (CrossOver): Indicator tracking crossover events
                between short and long MAs.
            self.order (None): Initialized to None, will hold pending orders.
            self.bar_num (int): Initialized to 0, incremented each bar.
            self.buy_count (int): Initialized to 0, incremented on buy fills.
            self.sell_count (int): Initialized to 0, incremented on sell fills.
        """
        self.premium_rate = self.datas[0].convert_premium_rate
        self.sma_short = bt.indicators.SimpleMovingAverage(
            self.premium_rate, period=self.p.short_period
        )
        self.sma_long = bt.indicators.SimpleMovingAverage(
            self.premium_rate, period=self.p.long_period
        )
        self.crossover = bt.indicators.CrossOver(self.sma_short, self.sma_long)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def notify_order(self, order):
        """Handle order status updates and track execution counts.

        This method is called by Backtrader whenever an order's status changes.
        It filters out intermediate statuses (Submitted, Accepted) and only
        processes Completed orders to update buy/sell counters.

        Args:
            order (Order): The order object with updated status information.
                Contains status codes and execution details.

        Order Statuses:
            - Submitted: Order has been submitted to the broker (ignored)
            - Accepted: Order has been accepted by the broker (ignored)
            - Completed: Order has been fully or partially filled (processed)

        Side Effects:
            - Increments self.buy_count when a buy order is completed
            - Increments self.sell_count when a sell order is completed
            - Sets self.order to None to allow new order generation
        """
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
        self.order = None

    def next(self):
        """Execute trading logic on each bar.

        This method is called by Backtrader for each new bar of data.
        It implements the core strategy logic: checking for crossovers,
        managing position entry and exit, and tracking bar count.

        Trading Logic:
            1. Increment bar counter for each bar processed
            2. Skip trading if a pending order exists
            3. If no position: Enter long when crossover > 0 (short MA above long MA)
            4. If has position: Exit when crossover < 0 (short MA below long MA)

        Position Sizing:
            - Uses 95% of available cash for entry orders
            - Calculates size based on current close price
            - Rounds down to integer number of shares/bonds

        Side Effects:
            - Increments self.bar_num on each call
            - Creates buy orders when entry signals are triggered
            - Creates close orders when exit signals are triggered
            - Stores order reference in self.order to prevent duplicate orders
        """
        self.bar_num += 1
        if self.order:
            return

        if not self.position:
            if self.crossover > 0:
                cash = self.broker.getcash()
                size = int((cash * 0.95) / self.datas[0].close[0])
                self.order = self.buy(size=size)
        else:
            if self.crossover < 0:
                self.order = self.close()


def load_bond_data(csv_file: str) -> pd.DataFrame:
    """Load convertible bond data from CSV file and prepare for Backtrader.

    This function reads a CSV file containing convertible bond data, performs
    data cleaning and transformations, and returns a DataFrame ready to be
    used with ExtendPandasFeed.

    The CSV file is expected to have the following columns:
        - BOND_CODE: Bond code identifier (dropped)
        - BOND_SYMBOL: Bond symbol (dropped)
        - datetime: Date/time of the bar (becomes index)
        - open, high, low, close: OHLC price data
        - volume: Trading volume
        - pure_bond_value: Pure bond valuation
        - convert_value: Conversion value
        - pure_bond_premium_rate: Pure bond premium rate
        - convert_premium_rate: Conversion premium rate

    Args:
        csv_file (str): Path to the CSV file containing convertible bond data.

    Returns:
        pd.DataFrame: Processed DataFrame with:
            - DateTimeIndex converted to datetime objects
            - BOND_CODE and BOND_SYMBOL columns removed
            - All values converted to float type
            - Rows with missing values dropped (dropna)
            - Columns ordered for ExtendPandasFeed mapping

    Raises:
        FileNotFoundError: If the CSV file does not exist at the specified path.
        KeyError: If required columns are missing from the CSV file.
        ValueError: If data cannot be converted to float type.

    Example:
        >>> df = load_bond_data("113013.csv")
        >>> print(df.head())
                        open   high    low  close  volume  ...
        datetime
        2020-01-02  100.5  101.2  100.1  101.0    5000  ...
    """
    df = pd.read_csv(csv_file)
    df.columns = ['BOND_CODE', 'BOND_SYMBOL', 'datetime', 'open', 'high', 'low',
                  'close', 'volume', 'pure_bond_value', 'convert_value',
                  'pure_bond_premium_rate', 'convert_premium_rate']

    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime')
    df = df.drop(['BOND_CODE', 'BOND_SYMBOL'], axis=1)
    df = df.dropna()
    df = df.astype(float)

    return df


def test_premium_rate_strategy():
    """Test convertible bond premium rate moving average crossover strategy.

    This end-to-end test validates the PremiumRateCrossoverStrategy by running
    a backtest on historical convertible bond data (113013.csv) and verifying
    that key performance metrics match expected values.

    The test:
        1. Loads and processes convertible bond data
        2. Sets up a Cerebro backtest engine with custom data feed
        3. Configures initial capital (100,000) and commission (0.03%)
        4. Adds the PremiumRateCrossoverStrategy
        5. Runs the backtest and collects performance metrics
        6. Asserts that metrics match expected values within tolerance

    Expected Results (based on 113013.csv data):
        - bar_num: 1384 bars processed
        - final_value: 104,275.87 portfolio value
        - sharpe_ratio: 0.11457 (annualized)
        - annual_return: 0.733% (normalized annual return)
        - max_drawdown: 17.41% maximum drawdown
        - total_trades: 21 trades executed

    Raises:
        AssertionError: If any performance metric deviates from expected values
            beyond the specified tolerance. Tolerances are set at 1e-6 for
            floating-point comparisons.
        FileNotFoundError: If the 113013.csv data file cannot be located.

    Side Effects:
        - Prints progress messages to stdout during execution
        - Prints backtest results summary after completion

    Example:
        >>> test_premium_rate_strategy()
        ============================================================
        Convertible Bond Premium Rate Crossover Strategy Test
        ============================================================
        Loading convertible bond data...
        Data range: 2020-01-02 00:00:00 to 2025-06-18 00:00:00, total 1384 records
        Starting backtest...
        ...
        All tests passed!
    """
    cerebro = bt.Cerebro()

    # Load data
    print("Loading convertible bond data...")
    data_path = resolve_data_path("113013.csv")
    df = load_bond_data(str(data_path))
    print(f"Data range: {df.index[0]} to {df.index[-1]}, total {len(df)} records")

    data = ExtendPandasFeed(dataname=df)
    cerebro.adddata(data)

    # Set initial capital and commission
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0003)

    # Add strategy
    cerebro.addstrategy(PremiumRateCrossoverStrategy)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    # Run backtest
    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio')
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm100')
    max_drawdown = strat.analyzers.drawdown.get_analysis()['max']['drawdown']
    trade_analysis = strat.analyzers.trades.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Print results
    print("\n" + "=" * 50)
    print("Convertible Bond Premium Rate Crossover Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # Assert test results (based on complete 113013.csv data)
    assert strat.bar_num == 1384, f"Expected bar_num=1384, got {strat.bar_num}"
    assert abs(final_value - 104275.87) < 0.01, \
        f"Expected final_value=104275.87, got {final_value}"
    assert sharpe_ratio is not None, "Sharpe ratio should not be None"
    assert abs(sharpe_ratio - 0.11457095300469224) < 1e-6, \
        f"Expected sharpe_ratio=0.11457095300469224, got {sharpe_ratio}"
    assert abs(annual_return - 0.733367887488441) < 1e-6, \
        f"Expected annual_return=0.733367887488441, got {annual_return}"
    assert abs(max_drawdown - 17.413029757464745) < 1e-6, \
        f"Expected max_drawdown=17.413, got {max_drawdown}"
    assert total_trades == 21, f"Expected total_trades=21, got {total_trades}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Convertible Bond Premium Rate Crossover Strategy Test")
    print("=" * 60)
    test_premium_rate_strategy()
