"""Test cases for Keltner Channel multi-contract futures strategy.

This module tests the Keltner Channel breakout strategy using rebar futures
multi-contract data. The strategy implements a trend-following approach with
automatic contract rollover logic.

Strategy Overview:
    - Uses Keltner Channel breakout as entry signals
    - Upper rail breakout with uptrend: long signal
    - Lower rail breakout with downtrend: short signal
    - Automatically rolls over positions to the dominant contract
    - Closes positions when price crosses back through the middle line

Data Requirements:
    - Rebar futures multi-contract data in 'rb/' directory
    - Required columns: datetime, open, high, low, close, volume, openinterest
    - Index data file: rb99.csv (continuous contract)
    - Individual contract files: rbYYYYM.csv (e.g., rb2020F.csv)

Key Features:
    - Keltner Channel: SMA +/- (ATR * multiplier)
    - Dominant contract selection based on open interest
    - Automatic rollover when dominant contract changes
    - Support for multiple futures contracts simultaneously

Test Assertions:
    - Processes exactly 5540 bars
    - Executes multiple buy and sell trades
    - Specific performance metrics (sharpe ratio, annual return, max drawdown, final value)

Usage:
    Run as standalone script::

        python tests/strategies/test_08_kelter_strategy.py

    Or use pytest::

        pytest tests/strategies/test_08_kelter_strategy.py -v
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
    """Locate data files based on script directory to avoid relative path failures.

    This function searches for data files in several predefined locations to ensure
    tests work regardless of the current working directory.

    Args:
        filename: Name of the data file or directory to locate.

    Returns:
        Path object pointing to the first found data file or directory.

    Raises:
        FileNotFoundError: If the data file or directory cannot be found.
    """
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR.parent.parent / filename,
        BASE_DIR.parent.parent / "tests" / "datas" / filename,
    ]

    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"Data file not found: {filename}")


class KeltnerStrategy(bt.Strategy):
    """Keltner Channel multi-contract futures strategy.

    This strategy implements a trend-following approach using Keltner Channel
    breakouts as entry signals and automatic contract rollover for futures trading.

    Entry Logic:
        - Long entry: Price closes above upper line AND middle line is rising
        - Short entry: Price closes below lower line AND middle line is falling
        - Only enters when not already in a position

    Exit Logic:
        - Close long when price closes below middle line
        - Close short when price closes above middle line

    Rollover Logic:
        - Identifies dominant contract (highest open interest) at each bar
        - Automatically closes old contract position and opens new contract position
        - Maintains position size and direction during rollover

    Indicators:
        - Middle line: SMA of typical price (HLC/3), default 110-period
        - ATR: Average True Range, default 110-period
        - Upper line: Middle line + (ATR * multiplier), default 3x ATR
        - Lower line: Middle line - (ATR * multiplier), default 3x ATR

    Attributes:
        author: Strategy author identifier.
        params: Strategy parameters (avg_period, atr_multi).
        bar_num: Counter for total bars processed.
        current_date: Current bar's datetime.
        buy_count: Counter for buy orders executed (entries + long rollovers).
        sell_count: Counter for sell orders executed (entries + short rollovers).
        middle_price: Calculated typical price (HLC/3).
        middle_line: SMA of typical price.
        atr: Average True Range indicator.
        upper_line: Upper Keltner Channel rail.
        lower_line: Lower Keltner Channel rail.
        holding_contract_name: Name of the contract currently held.

    Example:
        >>> cerebro.addstrategy(KeltnerStrategy, avg_period=110, atr_multi=3)
    """

    author = 'yunjinqi'
    params = (
        ("avg_period", 110),
        ("atr_multi", 3),
    )

    def log(self, txt, dt=None):
        """Log strategy information with timestamp.

        Args:
            txt (str): The message to log.
            dt (datetime.datetime, optional): The datetime to use for the log entry.
                If None, uses the current bar's datetime from the first data feed.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        """Initialize the Keltner Channel strategy.

        Sets up instance variables and calculates Keltner Channel indicators:
        - Middle line: SMA of typical price (HLC/3)
        - Upper line: Middle line + (ATR * multiplier)
        - Lower line: Middle line - (ATR * multiplier)

        Typical Price Calculation:
            typical_price = (high + low + close) / 3

        Keltner Channel Formula:
            middle_line = SMA(typical_price, avg_period)
            upper_line = middle_line + (ATR * atr_multi)
            lower_line = middle_line - (ATR * atr_multi)
        """
        # Initialize tracking variables
        self.bar_num = 0
        self.current_date = None
        self.buy_count = 0
        self.sell_count = 0

        # Calculate Keltner Channel indicators
        # Typical price (HLC/3) provides a more accurate representation of price
        self.middle_price = (self.datas[0].high + self.datas[0].low + self.datas[0].close) / 3
        self.middle_line = bt.indicators.SMA(self.middle_price, period=self.p.avg_period)
        self.atr = bt.indicators.AverageTrueRange(self.datas[0], period=self.p.avg_period)
        self.upper_line = self.middle_line + self.atr * self.p.atr_multi
        self.lower_line = self.middle_line - self.atr * self.p.atr_multi

        # Track which contract is currently being held
        self.holding_contract_name = None

    def prenext(self):
        """Handle pre-next phase for futures data.

        Futures data has thousands of bars with each futures contract having different
        trading dates, so the strategy won't naturally enter the next phase.
        This method calls the next function in each prenext to ensure continuous processing.

        Note:
            This is necessary because futures contracts have disjoint date ranges.
            The prenext phase occurs when there isn't enough data yet for all indicators
            to be valid. By calling next() here, we ensure the strategy processes all
            bars even when contracts have different trading periods.
        """
        self.next()

    def next(self):
        """Execute trading logic for each bar.

        Implements the following trading rules:
        1. Close existing positions when price crosses back through middle line
        2. Open long position on upper rail breakout with uptrend
        3. Open short position on lower rail breakout with downtrend
        4. Handle contract rollover when dominant contract changes

        Execution Flow:
            1. Update bar counter and current date
            2. Check if existing position should be closed (price crosses middle line)
            3. Check for new entry signals (upper/lower rail breakouts)
            4. Check for rollover opportunities (dominant contract changes)

        Position Management:
            - Only one position (long or short) at a time
            - Position size is always 1 contract
            - Position is tracked by holding_contract_name

        Rollover Logic:
            - Dominant contract = contract with highest open interest at current bar
            - Rollover occurs when dominant contract changes
            - Old position is closed and new position is opened with same size/direction
        """
        # Each time it runs, increment bar_num and update trading date
        self.current_date = bt.num2date(self.datas[0].datetime[0])
        self.bar_num += 1
        data = self.datas[0]

        # Open positions, close existing positions first

        # Close long position if price crosses below middle line
        if self.holding_contract_name is not None and self.getpositionbyname(self.holding_contract_name).size > 0 and data.close[0] < self.middle_line[0]:
            data = self.getdatabyname(self.holding_contract_name)
            self.close(data)
            self.sell_count += 1
            self.holding_contract_name = None

        # Close short position if price crosses above middle line
        if self.holding_contract_name is not None and self.getpositionbyname(self.holding_contract_name).size < 0 and data.close[0] > self.middle_line[0]:
            data = self.getdatabyname(self.holding_contract_name)
            self.close(data)
            self.buy_count += 1
            self.holding_contract_name = None

        # Open long position on upper rail breakout with rising middle line
        if self.holding_contract_name is None and data.close[-1] < self.upper_line[-1] and data.close[0] > self.upper_line[0] and self.middle_line[0] > self.middle_line[-1]:
            dominant_contract = self.get_dominant_contract()
            if dominant_contract is not None:
                next_data = self.getdatabyname(dominant_contract)
                self.buy(next_data, size=1)
                self.buy_count += 1
                self.holding_contract_name = dominant_contract

        # Open short position on lower rail breakout with falling middle line
        if self.holding_contract_name is None and data.close[-1] > self.lower_line[-1] and data.close[0] < self.lower_line[0] and self.middle_line[0] < self.middle_line[-1]:
            dominant_contract = self.get_dominant_contract()
            if dominant_contract is not None:
                next_data = self.getdatabyname(dominant_contract)
                self.sell(next_data, size=1)
                self.sell_count += 1
                self.holding_contract_name = dominant_contract

        # Rollover to next contract if dominant contract changes
        if self.holding_contract_name is not None:
            dominant_contract = self.get_dominant_contract()
            # If a new dominant contract appears, start rollover
            if dominant_contract is not None and dominant_contract != self.holding_contract_name:
                # Next dominant contract
                next_data = self.getdatabyname(dominant_contract)
                # Current contract position size and data
                size = self.getpositionbyname(self.holding_contract_name).size
                data = self.getdatabyname(self.holding_contract_name)
                # Close old position
                self.close(data)
                # Open new position with same size and direction
                if size > 0:
                    self.buy(next_data, size=abs(size))
                if size < 0:
                    self.sell(next_data, size=abs(size))
                self.holding_contract_name = dominant_contract

    def get_dominant_contract(self):
        """Select the contract with the largest open interest as the dominant contract.

        This method iterates through all data feeds (except the index) and finds
        the contract with the highest open interest for the current bar.

        Returns:
            str or None: The name of the dominant contract data, or None if no
                contract has data for the current date.

        Note:
            The index data (self.datas[0]) is excluded from dominance calculation.
            Only contracts trading on the current date are considered.
        """
        target_datas = []
        for data in self.datas[1:]:
            try:
                data_date = bt.num2date(data.datetime[0])
                if self.current_date == data_date:
                    target_datas.append([data._name, data.openinterest[0]])
            except:
                pass

        if not target_datas:
            return None

        # Sort by open interest and return the contract with highest open interest
        target_datas = sorted(target_datas, key=lambda x: x[1])
        return target_datas[-1][0]

    def notify_order(self, order):
        """Handle order status updates.

        This method is called when an order changes status. It logs the execution
        of buy and sell orders for monitoring and debugging.

        Args:
            order: The order object with updated status.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: data_name:{order.p.data._name} price:{order.executed.price:.2f}")
            else:
                self.log(f"SELL: data_name:{order.p.data._name} price:{order.executed.price:.2f}")

    def notify_trade(self, trade):
        """Handle trade status updates.

        This method is called when a trade changes status. It logs the opening
        and closing of trades with their profit/loss information.

        Args:
            trade: The trade object with updated status.
        """
        # Output information when a trade is completed
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))
        if trade.isopen:
            self.log('open symbol is : {} , price : {}'.format(
                trade.getdataname(), trade.price))

    def stop(self):
        """Log final statistics when backtesting completes.

        Outputs the total number of bars processed and buy/sell counts for
        strategy evaluation.
        """
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


class RbPandasFeed(bt.feeds.PandasData):
    """Pandas data feed for rebar futures data.

    This custom data feed maps DataFrame columns to backtrader data fields
    for loading rebar (steel reinforcement bar) futures data from pandas DataFrames.

    The rebar futures data contains OHLCV data plus open interest, which is
    used for determining the dominant contract in rollover logic.

    DataFrame Column Mapping:
        - datetime: Index (not a column)
        - Column 0 (index 0): open
        - Column 1 (index 1): high
        - Column 2 (index 2): low
        - Column 3 (index 3): close
        - Column 4 (index 4): volume
        - Column 5 (index 5): openinterest

    Attributes:
        params: Tuple defining column mappings from DataFrame to data lines.

    Example:
        >>> df = pd.read_csv('rb2020F.csv', parse_dates=['datetime'])
        >>> df = df.set_index('datetime')
        >>> feed = RbPandasFeed(dataname=df)
        >>> cerebro.adddata(feed, name='rb2020F')
    """
    params = (
        ('datetime', None),  # datetime is index, not a column
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


def load_rb_multi_data(data_dir: str = "rb") -> dict:
    """Load rebar futures multi-contract data.

    This function loads all rebar futures contract data files from the specified
    directory. It maintains the original data loading logic including date range
    filtering and file ordering.

    The function ensures rb99.csv (continuous contract) is loaded first and
    sorts other contracts consistently across platforms.

    Args:
        data_dir: Directory name containing the contract data files.
            Defaults to "rb".

    Returns:
        dict: Dictionary mapping contract names (without .csv extension) to
            DataFrames containing the contract data.

    Data Preprocessing:
        - Filters data to date range: 2019-01-01 to 2020-12-31
        - Only keeps columns: datetime, open, high, low, close, volume, openinterest
        - Sets datetime as the index
        - Skips empty files or files with no data in the date range

    File Ordering:
        1. rb99.csv is always first (continuous contract index)
        2. Other contracts are sorted alphabetically (case-insensitive for Windows)

    Raises:
        FileNotFoundError: If the data directory cannot be found.

    Example:
        >>> datas = load_rb_multi_data("rb")
        >>> print(f"Loaded {len(datas)} contracts")
        Loaded 15 contracts
    """
    data_kwargs = dict(
        fromdate=datetime.datetime(2019, 1, 1),  # Shorten date range to speed up testing
        todate=datetime.datetime(2020, 12, 31),
    )

    data_path = resolve_data_path(data_dir)
    file_list = os.listdir(data_path)

    # Sort file list for consistent ordering across platforms (Windows vs macOS)
    file_list = sorted(file_list, key=lambda x: x.lower())

    # Ensure rb99.csv is placed first as index data (case-insensitive for Windows)
    rb99_file = None
    for f in file_list:
        if f.lower() == "rb99.csv":
            rb99_file = f
            break
    if rb99_file:
        file_list.remove(rb99_file)
        file_list = [rb99_file] + file_list

    datas = {}
    for file in file_list:
        if not file.endswith('.csv'):
            continue
        name = file[:-4]
        df = pd.read_csv(data_path / file)
        # Only keep these columns from the data
        df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
        # Modify column names and set index
        df.index = pd.to_datetime(df['datetime'])
        df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
        df = df[(df.index <= data_kwargs['todate']) & (df.index >= data_kwargs['fromdate'])]
        if len(df) == 0:
            continue
        datas[name] = df

    return datas


def test_keltner_strategy():
    """Test Keltner Channel multi-contract futures strategy.

    This test performs a complete backtest using rebar futures multi-contract data.
    It validates strategy behavior and performance metrics against expected values.

    Test Configuration:
        - Initial cash: 50,000
        - Commission: 0.02% per trade
        - Margin: 10%
        - Multiplier: 10 (rebar futures contract size)
        - Date range: 2019-01-01 to 2020-12-31
        - Keltner Channel period: 110
        - ATR multiplier: 3

    Expected Results:
        - Bars processed: 5540
        - Multiple buy and sell trades executed
        - Sharpe ratio: -0.7248889123130405
        - Annual return: -0.16%
        - Max drawdown: 18.56%
        - Final portfolio value: 49,847.09

    Analyzers Added:
        - TotalValue: Tracks portfolio value over time
        - SharpeRatio: Calculates risk-adjusted return metric
        - Returns: Calculates annualized return
        - DrawDown: Tracks maximum drawdown from peak
        - TradeAnalyzer: Provides detailed trade statistics

    Raises:
        AssertionError: If any performance metric deviates from expected values.
        FileNotFoundError: If required data files cannot be located.

    Note:
        The test uses precise assertions to ensure strategy behavior remains
        consistent across different platforms and data versions.
    """
    # Create cerebro engine
    cerebro = bt.Cerebro(stdstats=True)

    # Load multi-contract data
    print("Loading rebar futures multi-contract data...")
    datas = load_rb_multi_data("rb")
    print(f"Loaded {len(datas)} contract data files")

    # Load data using RbPandasFeed and set commission info
    for name, df in datas.items():
        feed = RbPandasFeed(dataname=df)
        cerebro.adddata(feed, name=name)
        # Set contract trading information
        comm = ComminfoFuturesPercent(commission=0.0002, margin=0.1, mult=10)
        cerebro.broker.addcommissioninfo(comm, name=name)

    cerebro.broker.setcash(50000.0)

    # Add strategy
    cerebro.addstrategy(KeltnerStrategy)

    # Add performance analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    # Run backtest
    print("Starting backtest...")
    results = cerebro.run()

    # Get results from first strategy instance
    strat = results[0]
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get("sharperatio")
    annual_return = strat.analyzers.my_returns.get_analysis().get("rnorm")
    max_drawdown = strat.analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    # Print results
    print("\n" + "=" * 50)
    print("Keltner Channel Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # Assert test results - using precise assertions
    # Tolerance: 1e-6 for most metrics, 0.01 for final_value
    assert strat.bar_num == 5540, f"Expected bar_num=5540, got {strat.bar_num}"
    assert strat.buy_count > 0, f"Expected buy_count > 0, got {strat.buy_count}"
    assert strat.sell_count > 0, f"Expected sell_count > 0, got {strat.sell_count}"
    assert total_trades > 0, f"Expected total_trades > 0, got {total_trades}"
    # Note: sharpe_ratio may vary slightly due to platform differences, using precise tolerance
    assert abs(sharpe_ratio - (-0.7248889123130405)) < 1e-6, f"Expected sharpe_ratio=-0.7248889123130405, got {sharpe_ratio}"
    assert abs(annual_return - (-0.0015868610268626382)) < 1e-6, f"Expected annual_return=-0.0015868610268626382, got {annual_return}"
    assert abs(max_drawdown - 0.1856158167743111) < 1e-6, f"Expected max_drawdown=0.1856158167743111, got {max_drawdown}"
    assert abs(final_value - 49847.09399999999) < 0.01, f"Expected final_value=49847.09399999999, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Keltner Channel Multi-Contract Futures Strategy Test")
    print("=" * 60)
    test_keltner_strategy()
