#!/usr/bin/env python
"""
Test case for multi-data source simple moving average strategy.

This module tests a multi-asset moving average crossover strategy using convertible
bond data. The strategy implements a simple trend-following approach where positions
are taken when price crosses above or below a moving average.

Strategy Logic:
    - Buy signal: Price rises above 60-day moving average
    - Sell signal: Price falls below 60-day moving average
    - Equal weight allocation across all tradable convertible bonds
    - First data source serves as date alignment index (not traded)

Usage:
    Direct execution:
        python tests/strategies/test_04_simple_ma_multi_data.py

    Via pytest:
        pytest tests/strategies/test_04_simple_ma_multi_data.py -v

Example:
    >>> from tests.strategies.test_04_simple_ma_multi_data import run_strategy
    >>> cerebro, results, metrics = run_strategy(max_bonds=30)
    >>> print(f"Return: {metrics['return_rate']:.2f}%")
"""

import os
import warnings

import backtrader as bt
import pandas as pd

from backtrader.cerebro import Cerebro
from backtrader.feeds import PandasData
from backtrader.strategy import Strategy
import backtrader.indicators as btind

warnings.filterwarnings("ignore")

# Get data directory
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(CURRENT_DIR)
DATA_DIR = os.path.join(TESTS_DIR, "datas")


# ============================================================
# Data source definitions
# ============================================================


class ExtendPandasFeed(PandasData):
    """Extended Pandas data feed with convertible bond-specific fields.

    This data feed extends the standard PandasData to include additional
    fields specific to convertible bonds, allowing for more comprehensive
    analysis and strategy development.

    Lines:
        pure_bond_value: Pure bond value of the convertible bond
        convert_value: Conversion value of the bond
        pure_bond_premium_rate: Premium rate of pure bond value
        convert_premium_rate: Premium rate of conversion value

    Params:
        datetime: Column name or index for datetime values
        open: Column name or index for open prices
        high: Column name or index for high prices
        low: Column name or index for low prices
        close: Column name or index for close prices
        volume: Column name or index for volume data
        openinterest: Column name or index for open interest
        pure_bond_value: Column index for pure bond value (field 5)
        convert_value: Column index for conversion value (field 6)
        pure_bond_premium_rate: Column index for pure bond premium rate (field 7)
        convert_premium_rate: Column index for conversion premium rate (field 8)

    Note:
        Column indices 0-4 are reserved for standard OHLCV data.
        Convertible bond-specific fields start at index 5.
    """

    params = (
        ("datetime", None),
        ("open", 0),
        ("high", 1),
        ("low", 2),
        ("close", 3),
        ("volume", 4),
        ("openinterest", -1),
        ("pure_bond_value", 5),
        ("convert_value", 6),
        ("pure_bond_premium_rate", 7),
        ("convert_premium_rate", 8),
    )
    lines = ("pure_bond_value", "convert_value", "pure_bond_premium_rate", "convert_premium_rate")


# ============================================================
# Strategy definitions
# ============================================================


class SimpleMAMultiDataStrategy(bt.Strategy):
    """Multi-data source simple moving average crossover strategy.

    This strategy implements a trend-following approach using moving average
    crossovers across multiple convertible bonds simultaneously. It maintains
    equal weight positions across all tradable assets.

    Strategy Logic:
        1. Calculate 60-day simple moving average for each convertible bond
        2. Buy when price crosses above the moving average (uptrend signal)
        3. Sell when price crosses below the moving average (downtrend signal)
        4. Allocate equal portfolio weight to each tradable bond

    Data Source Handling:
        - First data source (index=0): Used for date alignment only, not traded
        - Data sources (index=1+): Individual convertible bonds for trading

    Position Management:
        - Tracks pending orders to prevent duplicate position entries
        - Cancels pending buy orders when sell signal is triggered
        - Trades in round lots of 10 shares (convertible bond convention)

    Attributes:
        bar_num (int): Counter for total bars processed
        buy_count (int): Total buy orders placed
        sell_count (int): Total sell orders placed
        stock_ma_dict (dict): Mapping of bond names to MA indicators
        position_dict (dict): Mapping of bond names to pending orders
        stock_dict (dict): Set of tradable bond names

    Params:
        period (int): Moving average period (default: 60 days)
        verbose (bool): Enable detailed logging output (default: False)
    """

    params = (
        ("period", 60),
        ("verbose", False),
    )

    def log(self, txt, dt=None):
        """Log strategy messages to console.

        Outputs formatted log messages when verbose mode is enabled.
        Messages include timestamp and custom text.

        Args:
            txt (str): Message text to log
            dt (datetime.datetime, optional): Datetime object for timestamp.
                If None, uses current bar's datetime from first data source.

        Note:
            Only outputs when self.p.verbose is True.
        """
        if self.p.verbose:
            dt = dt or self.datas[0].datetime.date(0)
            print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables.

        Sets up the moving average indicators for each convertible bond and
        initializes tracking dictionaries for positions and orders.

        Key initialization steps:
            1. Initialize counters for bars, buys, and sells
            2. Create SimpleMovingAverage indicator for each bond (skipping index)
            3. Attach indicators to strategy to ensure proper owner registration
            4. Initialize position tracking dictionaries

        Note:
            Indicators are attached via setattr() to trigger LineSeries.__setattr__,
            which corrects the _owner attribute from MinimalOwner to the current
            strategy and adds the indicator to strategy._lineiterators for proper
            updating during _next() calls.
        """
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

        # Create moving average indicators for each convertible bond (first data is index, not for trading)
        self.stock_ma_dict = {}
        for idx, data in enumerate(self.datas[1:], start=1):
            ma = btind.SimpleMovingAverage(data.close, period=self.p.period)
            # Key point: Attach indicator to strategy object to trigger LineSeries.__setattr__,
            # which corrects _owner from MinimalOwner to current strategy,
            # and adds it to strategy's _lineiterators so _next drives calculation.
            setattr(self, f"ma_{data._name}", ma)
            self.stock_ma_dict[data._name] = ma

        # Save orders for existing positions
        self.position_dict = {}
        # Stocks currently being traded
        self.stock_dict = {}

    def prenext(self):
        """Handle prenext phase by calling next().

        The prenext phase occurs before the minimum period requirement is met.
        This strategy bypasses the warm-up period by directly calling next()
        to begin processing immediately.

        Note:
            This allows the strategy to start trading before all indicators
            have enough data, which is handled by checking indicator length
            in the next() method.
        """
        self.next()

    def next(self):
        """Execute strategy logic for each bar.

        Main strategy execution method called for each bar. Implements the
        moving average crossover logic across all convertible bonds.

        Algorithm:
            1. Update bar counter and retrieve current date from index
            2. Calculate portfolio statistics (total value, available cash)
            3. Identify all tradable bonds for current date
            4. Calculate position size based on equal-weight allocation
            5. For each bond:
               - Check if moving average crossover signal exists
               - Execute sell order if price crosses below MA (close long)
               - Execute buy order if price crosses above MA (open long)
               - Handle pending order cancellation on signal reversal

        Position Sizing:
            - Allocates equal weight to all tradable bonds
            - Calculates size as: (total_value / num_bonds) / close_price
            - Rounds down to nearest multiple of 10 shares

        Signal Logic:
            - Buy: previous_close < previous_ma AND current_close > current_ma
            - Sell: previous_close > previous_ma AND current_close < current_ma

        Note:
            Skips bonds with insufficient data (less than period + 1 bars)
            or invalid moving average values (NaN, zero, or negative).
        """
        self.bar_num += 1

        # Current trading day
        current_date = self.datas[0].datetime.date(0).strftime("%Y-%m-%d")

        # Total value and cash
        total_value = self.broker.get_value()
        total_cash = self.broker.get_cash()

        # First data is index used for date alignment, not for trading
        # Loop through all convertible bonds to count tradable ones for the day
        for data in self.datas[1:]:
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            if current_date == data_date:
                stock_name = data._name
                if stock_name not in self.stock_dict:
                    self.stock_dict[stock_name] = 1

        total_target_stock_num = len(self.stock_dict)
        if total_target_stock_num == 0:
            return

        # Number of stocks currently holding
        total_holding_stock_num = len(self.position_dict)

        # Calculate available funds for each stock
        if total_holding_stock_num < total_target_stock_num:
            remaining = total_target_stock_num - total_holding_stock_num
            if remaining > 0:
                now_value = total_cash / remaining
                stock_value = total_value / total_target_stock_num
                now_value = min(now_value, stock_value)
            else:
                now_value = total_value / total_target_stock_num
        else:
            now_value = total_value / total_target_stock_num

        # Loop through convertible bonds and execute trading logic
        for data in self.datas[1:]:
            data_date = data.datetime.date(0).strftime("%Y-%m-%d")
            if current_date != data_date:
                continue

            # Moving average calculated using btind.SimpleMovingAverage
            ma_indicator = self.stock_ma_dict.get(data._name)
            if ma_indicator is None:
                continue

            # Indicator length insufficient, moving average not yet stable
            if len(ma_indicator) < self.p.period + 1:
                continue

            close = data.close[0]
            pre_close = data.close[-1]
            ma = ma_indicator[0]
            pre_ma = ma_indicator[-1]

            # Check if moving average is valid
            if ma <= 0 or pre_ma <= 0 or pd.isna(ma) or pd.isna(pre_ma):
                continue

            # Close long signal: price falls below moving average
            if pre_close > pre_ma and close < ma:
                if self.getposition(data).size > 0:
                    self.close(data)
                    self.sell_count += 1
                    if data._name in self.position_dict:
                        self.position_dict.pop(data._name)
                # Order placed but not yet filled
                if data._name in self.position_dict and self.getposition(data).size == 0:
                    order = self.position_dict[data._name]
                    self.cancel(order)
                    self.position_dict.pop(data._name)

            # Open long signal: price rises above moving average and no position
            if pre_close < pre_ma and close > ma:
                if self.getposition(data).size == 0 and data._name not in self.position_dict:
                    lots = now_value / data.close[0]
                    lots = int(lots / 10) * 10  # Convertible bonds traded in units of 10
                    if lots > 0:
                        order = self.buy(data, size=lots)
                        self.position_dict[data._name] = order
                        self.buy_count += 1

    def notify_order(self, order):
        """Handle order status updates.

        Called by the broker when an order's status changes. Logs order
        execution details and handles order status notifications.

        Args:
            order (backtrader.Order): Order object with updated status

        Order Statuses Handled:
            - Submitted: Order submitted to broker (no action)
            - Accepted: Order accepted by broker (no action)
            - Rejected: Order rejected (logs rejection)
            - Margin: Margin requirement not met (logs margin issue)
            - Cancelled: Order cancelled (logs cancellation)
            - Completed: Order filled (logs execution price and direction)

        Note:
            Uses self.log() which only outputs when verbose mode is enabled.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Rejected:
            self.log(f"Rejected: {order.p.data._name}")
        elif order.status == order.Margin:
            self.log(f"Margin: {order.p.data._name}")
        elif order.status == order.Cancelled:
            self.log(f"Cancelled: {order.p.data._name}")
        elif order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: {order.p.data._name} @ {order.executed.price:.2f}")
            else:
                self.log(f"SELL: {order.p.data._name} @ {order.executed.price:.2f}")

    def notify_trade(self, trade):
        """Handle trade lifecycle events.

        Called when a trade is opened or closed. Logs trade details
        including profit and loss information.

        Args:
            trade (backtrader.Trade): Trade object with status and P&L info

        Trade States Logged:
            - Open: Trade just opened with entry price
            - Closed: Trade closed with total and net P&L (after commissions)

        Output Format:
            - Open: "Trade opened: {bond_name} @ {price:.2f}"
            - Closed: "Trade closed: {bond_name}, PnL: {total:.2f}, Net: {net:.2f}"

        Note:
            Only logs when verbose mode is enabled via self.log().
        """
        if trade.isclosed:
            self.log(
                f"Trade closed: {trade.getdataname()}, PnL: {trade.pnl:.2f}, Net: {trade.pnlcomm:.2f}"
            )
        if trade.isopen:
            self.log(f"Trade opened: {trade.getdataname()} @ {trade.price:.2f}")

    def stop(self):
        """Print strategy completion statistics.

        Called after backtest completion. Outputs summary statistics
        including total bars processed and order counts.

        Outputs:
            - bar_num: Total number of bars processed
            - buy_count: Total number of buy orders placed
            - sell_count: Total number of sell orders placed

        Note:
            This output always occurs regardless of verbose setting.
        """
        print(
            f"Strategy ended: bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}"
        )


# ============================================================
# Data loading functions
# ============================================================


def load_index_data(csv_file):
    """Load index data from CSV file for date alignment.

    Reads a CSV file containing index data and processes it for use
    as the primary date alignment source in multi-data strategies.

    Args:
        csv_file (str): Path to CSV file containing index data

    Returns:
        pandas.DataFrame: Processed dataframe with datetime index
            - Index: Datetime values parsed from 'datetime' column
            - Columns: Float64 data columns (OHLCV format)
            - Rows: Cleaned data with NaN values dropped

    Processing Steps:
        1. Read CSV file
        2. Convert 'datetime' column to datetime objects
        3. Set datetime column as index
        4. Drop any rows with missing values
        5. Convert all columns to float dtype

    Example:
        >>> df = load_index_data('bond_index_000000.csv')
        >>> print(df.head())
    """
    df = pd.read_csv(csv_file)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    df = df.dropna()
    df = df.astype(float)
    return df


def load_bond_data_multi(csv_file, max_bonds=100):
    """Load multiple convertible bond data from merged CSV file.

    Reads a CSV file containing merged data for multiple convertible bonds
    and splits it into individual DataFrames by bond code. Filters bonds
    by minimum data length requirement.

    Args:
        csv_file (str): Path to merged convertible bond CSV file with columns:
            - BOND_CODE: Unique bond identifier
            - BOND_SYMBOL: Bond symbol/ticker
            - datetime: Date/time of data point
            - open, high, low, close: Price data
            - volume: Trading volume
            - pure_bond_value: Pure bond valuation
            - convert_value: Conversion value
            - pure_bond_premium_rate: Premium rate over pure bond value
            - convert_premium_rate: Premium rate over conversion value
        max_bonds (int, optional): Maximum number of bonds to load.
            Defaults to 100.

    Returns:
        dict: Dictionary mapping bond codes to DataFrames
            - Key: Bond code (string)
            - Value: DataFrame with datetime index and float64 columns

    Filtering:
        - Only includes bonds with at least 60 data points
        - Removes BOND_CODE and BOND_SYMBOL columns from output
        - Drops rows with missing values
        - Converts all columns to float dtype

    Example:
        >>> bonds = load_bond_data_multi('bond_merged_all_data.csv', max_bonds=30)
        >>> print(f"Loaded {len(bonds)} bonds")
        >>> print(f"Bond codes: {list(bonds.keys())}")
    """
    df = pd.read_csv(csv_file)
    df.columns = [
        "BOND_CODE",
        "BOND_SYMBOL",
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "pure_bond_value",
        "convert_value",
        "pure_bond_premium_rate",
        "convert_premium_rate",
    ]

    # Get unique convertible bond codes
    bond_codes = df["BOND_CODE"].unique()[:max_bonds]

    result = {}
    for code in bond_codes:
        bond_df = df[df["BOND_CODE"] == code].copy()
        bond_df["datetime"] = pd.to_datetime(bond_df["datetime"])
        bond_df = bond_df.set_index("datetime")
        bond_df = bond_df.drop(["BOND_CODE", "BOND_SYMBOL"], axis=1)
        bond_df = bond_df.dropna()
        bond_df = bond_df.astype(float)

        # Only keep convertible bonds with sufficient data (at least 60 trading days)
        if len(bond_df) >= 60:
            result[str(code)] = bond_df

    return result


# ============================================================
# Backtest execution functions
# ============================================================


def run_strategy(max_bonds=100, initial_cash=10000000.0, commission=0.0002, verbose=False):
    """Run multi-data source moving average strategy backtest.

    Creates and executes a complete backtest of the simple moving average
    crossover strategy across multiple convertible bonds with full
    performance analysis.

    Args:
        max_bonds (int, optional): Maximum number of convertible bonds to load.
            Defaults to 100.
        initial_cash (float, optional): Starting capital for the backtest.
            Defaults to 10,000,000.0.
        commission (float, optional): Commission rate as a decimal (e.g., 0.0002 = 0.02%).
            Defaults to 0.0002.
        verbose (bool, optional): Enable detailed strategy logging.
            Defaults to False.

    Returns:
        tuple: A tuple containing:
            - cerebro (backtrader.Cerebro): The cerebro engine instance
            - results (list): List of strategy instances from backtest
            - metrics (dict): Dictionary of performance metrics including:
                * bar_num (int): Total bars processed
                * buy_count (int): Total buy orders placed
                * sell_count (int): Total sell orders placed
                * final_value (float): Final portfolio value
                * total_profit (float): Absolute profit (final - initial)
                * return_rate (float): Percentage return
                * sharpe_ratio (float): Sharpe ratio
                * annual_return (float): Annualized return
                * max_drawdown (float): Maximum drawdown percentage
                * total_trades (int): Total completed trades
                * initial_cash (float): Initial capital
                * bonds_loaded (int): Number of bonds loaded

    Data Files Required:
        - DATA_DIR/bond_index_000000.csv: Index data for date alignment
        - DATA_DIR/bond_merged_all_data.csv: Merged convertible bond data

    Analyzers Added:
        - TotalValue: Portfolio value over time
        - SharpeRatio: Risk-adjusted return metric
        - Returns: Return statistics
        - DrawDown: Drawdown analysis
        - TradeAnalyzer: Trade statistics

    Example:
        >>> cerebro, results, metrics = run_strategy(
        ...     max_bonds=30,
        ...     initial_cash=1000000.0,
        ...     commission=0.0001,
        ...     verbose=True
        ... )
        >>> print(f"Return: {metrics['return_rate']:.2f}%")
        >>> print(f"Sharpe: {metrics['sharpe_ratio']:.4f}")
    """
    cerebro = bt.Cerebro()

    # Add strategy
    cerebro.addstrategy(SimpleMAMultiDataStrategy, period=60, verbose=verbose)

    # Load index data (used for date alignment)
    index_file = os.path.join(DATA_DIR, "bond_index_000000.csv")
    index_df = load_index_data(index_file)
    index_feed = ExtendPandasFeed(dataname=index_df)
    cerebro.adddata(index_feed, name="index")

    # Load convertible bond data
    bond_file = os.path.join(DATA_DIR, "bond_merged_all_data.csv")
    bond_data_dict = load_bond_data_multi(bond_file, max_bonds=max_bonds)

    print(f"Loaded {len(bond_data_dict)} convertible bond data files")

    for bond_code, bond_df in bond_data_dict.items():
        feed = ExtendPandasFeed(dataname=bond_df)
        cerebro.adddata(feed, name=bond_code)

    # Set initial capital and commission
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission, stocklike=True)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="total_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    # Run backtest
    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    final_value = cerebro.broker.getvalue()
    sharpe_analysis = strat.analyzers.sharpe.get_analysis()
    returns_analysis = strat.analyzers.returns.get_analysis()
    drawdown_analysis = strat.analyzers.drawdown.get_analysis()
    trades_analysis = strat.analyzers.trades.get_analysis()

    total_trades = trades_analysis.get("total", {}).get("total", 0)
    sharpe_ratio = sharpe_analysis.get("sharperatio")
    annual_return = returns_analysis.get("rnorm")
    max_drawdown = (
        drawdown_analysis["max"]["drawdown"] if drawdown_analysis["max"]["drawdown"] else 0
    )

    metrics = {
        "bar_num": strat.bar_num,
        "buy_count": strat.buy_count,
        "sell_count": strat.sell_count,
        "final_value": final_value,
        "total_profit": final_value - initial_cash,
        "return_rate": (final_value / initial_cash - 1) * 100,
        "sharpe_ratio": sharpe_ratio,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "total_trades": total_trades,
        "initial_cash": initial_cash,
        "bonds_loaded": len(bond_data_dict),
    }

    return cerebro, results, metrics


# ============================================================
# Test configuration
# ============================================================

_test_results = None


def get_test_results():
    """Get backtest results with caching for test efficiency.

    Retrieves or computes the backtest results for the multi-data moving
    average strategy. Results are cached after first execution to avoid
    redundant computation in multiple test calls.

    Returns:
        tuple: Cached backtest results from run_strategy():
            - cerebro (backtrader.Cerebro): Cerebro engine instance
            - results (list): Strategy instances from backtest
            - metrics (dict): Performance metrics dictionary

    Test Configuration:
        - max_bonds: 30 (limited for faster test execution)
        - initial_cash: 10,000,000.0
        - commission: 0.0002 (0.02%)
        - verbose: False (reduce output during testing)

    Note:
        Uses module-level _test_results variable for caching.
        Cache persists for the lifetime of the Python process.

    Example:
        >>> cerebro, results, metrics = get_test_results()
        >>> assert metrics['buy_count'] > 0
    """
    global _test_results
    if _test_results is None:
        _test_results = run_strategy(
            max_bonds=30, initial_cash=10000000.0, commission=0.0002, verbose=False
        )
    return _test_results


# ============================================================
# Pytest test functions
# ============================================================


def test_simple_ma_multi_data_strategy():
    """Test multi-data source moving average strategy execution and results.

    Pytest-compatible test function that validates the strategy backtest
    produces expected results. Ensures strategy logic is working correctly
    by comparing actual metrics against expected values.

    Test Validates:
        - Data loading: Correct number of bonds loaded (30)
        - Bar processing: Correct bar count (4434)
        - Trading activity: Buy and sell order counts
        - Trade execution: Total completed trades
        - Performance metrics: Sharpe ratio, max drawdown, final value

    Assertions:
        Integer metrics (exact match):
            - bonds_loaded == 30
            - bar_num == 4434
            - buy_count == 463
            - sell_count == 450
            - total_trades == 460

        Float metrics (approximate match):
            - sharpe_ratio ≈ 0.1920060395982071 (±1e-6)
            - max_drawdown ≈ 17.7630% (±0.01%)
            - final_value ≈ 14,535,803.03 (±1.0)

    Raises:
        AssertionError: If any metric does not match expected value

    Example:
        $ pytest tests/strategies/test_04_simple_ma_multi_data.py -v
        ===== test session starts =====
        tests/strategies/test_04_simple_ma_multi_data.py::test_simple_ma_multi_data_strategy PASSED
    """
    cerebro, results, metrics = get_test_results()

    # Print results
    print("\n" + "=" * 60)
    print("Backtest results:")
    print(f"  Bonds loaded: {metrics['bonds_loaded']}")
    print(f"  bar_num: {metrics['bar_num']}")
    print(f"  buy_count: {metrics['buy_count']}")
    print(f"  sell_count: {metrics['sell_count']}")
    print(f"  total_trades: {metrics['total_trades']}")
    print(f"  final_value: {metrics['final_value']:.2f}")
    print(f"  total_profit: {metrics['total_profit']:.2f}")
    print(f"  return_rate: {metrics['return_rate']:.4f}%")
    print(f"  sharpe_ratio: {metrics['sharpe_ratio']}")
    print(f"  annual_return: {metrics['annual_return']}")
    print(f"  max_drawdown: {metrics['max_drawdown']:.4f}%")
    print("=" * 60)

    # Assert test results
    # Integer values use exact comparison
    assert metrics["bonds_loaded"] == 30, f"Expected bonds_loaded=30, got {metrics['bonds_loaded']}"
    assert metrics["bar_num"] == 4434, f"Expected bar_num=4434, got {metrics['bar_num']}"
    assert metrics["buy_count"] == 463, f"Expected buy_count=463, got {metrics['buy_count']}"
    assert metrics["sell_count"] == 450, f"Expected sell_count=450, got {metrics['sell_count']}"
    assert metrics["total_trades"] == 460, f"Expected total_trades=460, got {metrics['total_trades']}"
    # Float values use approximate comparison (allow small errors)
    assert abs(metrics["sharpe_ratio"] - 0.1920060395982071) < 1e-6, f"Expected sharpe_ratio=0.1920060395982071, got {metrics['sharpe_ratio']}"
    assert abs(metrics["max_drawdown"] - 17.7630) < 0.01, f"Expected max_drawdown=17.7630%, got {metrics['max_drawdown']}"
    assert abs(metrics["final_value"] - 14535803.03) < 1.0, f"Expected final_value=14535803.03, got {metrics['final_value']}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Multi-data source simple moving average strategy test")
    print("=" * 60)
    test_simple_ma_multi_data_strategy()
