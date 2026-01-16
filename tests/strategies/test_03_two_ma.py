"""Test case for dual moving average strategy.

This module tests a dual moving average crossover strategy using convertible bond
data (113013.csv). The strategy buys when the short-term moving average crosses
above the long-term moving average (golden cross) and sells when the short-term
moving average crosses below the long-term moving average (death cross).

The test includes:
- Loading convertible bond data with extended fields (pure_bond_value, convert_value, etc.)
- Running a backtest with the TwoMAStrategy
- Verifying performance metrics (Sharpe ratio, annual return, max drawdown, etc.)
- Asserting expected trade counts and final portfolio value
"""

import datetime
import os
from pathlib import Path

import numpy as np
import pandas as pd

import backtrader as bt
from backtrader.cerebro import Cerebro
from backtrader.strategy import Strategy
from backtrader.feeds import PandasData

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files by searching multiple common directory locations.

    This function searches for data files in a predefined set of locations to avoid
    issues with relative path resolution. It checks the current directory, parent
    directories, common data folders, and an optional environment variable path.

    Args:
        filename (str): Name of the data file to locate (e.g., '113013.csv').

    Returns:
        Path: Absolute path to the first matching data file found.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the searched
            locations. The error message includes all paths that were searched.

    Search Order:
        1. Current directory (tests/strategies/)
        2. Parent tests directory
        3. Repository root directory
        4. examples/ subdirectory
        5. tests/datas/ subdirectory
        6. Directory specified by BACKTRADER_DATA_DIR environment variable
        7. Direct relative path as fallback
    """
    search_paths = []

    # 1. Current directory (tests/strategies)
    search_paths.append(BASE_DIR / filename)

    # 2. tests directory and project root directory
    search_paths.append(BASE_DIR.parent / filename)
    repo_root = BASE_DIR.parent.parent
    search_paths.append(repo_root / filename)

    # 3. Common data directories (examples, tests/datas)
    search_paths.append(repo_root / "examples" / filename)
    search_paths.append(repo_root / "tests" / "datas" / filename)

    # 4. Directory specified by environment variable BACKTRADER_DATA_DIR
    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    fallback = Path(filename)
    if fallback.exists():
        return fallback

    searched = " , ".join(str(path) for path in search_paths + [fallback.resolve()])
    raise FileNotFoundError(f"Data file not found: {filename}. Tried paths: {searched}")


class ExtendPandasFeed(PandasData):
    """Extended Pandas data source with convertible bond specific fields.

    This class extends the standard PandasData feed to support convertible bond
    data with additional fields beyond standard OHLCV data. It maps DataFrame
    columns to backtrader data lines for use in backtesting convertible bond
    strategies.

    DataFrame Structure (after set_index):
        Index:
            datetime (DatetimeIndex): Timestamp for each data bar
        Columns:
            0: open (float): Opening price
            1: high (float): Highest price
            2: low (float): Lowest price
            3: close (float): Closing price
            4: volume (float): Trading volume
            5: pure_bond_value (float): Pure bond value (investment value)
            6: convert_value (float): Conversion value
            7: pure_bond_premium_rate (float): Pure bond premium rate
            8: convert_premium_rate (float): Conversion premium rate

    Attributes:
        params (tuple): Parameter definitions mapping DataFrame columns to lines.
        lines (tuple): Extended data lines for convertible bond fields.

    Example:
        >>> df = pd.read_csv('bond.csv')
        >>> df = df.set_index('datetime')
        >>> feed = ExtendPandasFeed(dataname=df)
        >>> cerebro.adddata(feed, name='bond')
    """

    params = (
        ("datetime", None),  # datetime is the index, not a data column
        ("open", 0),  # Column 1 -> index 0
        ("high", 1),  # Column 2 -> index 1
        ("low", 2),  # Column 3 -> index 2
        ("close", 3),  # Column 4 -> index 3
        ("volume", 4),  # Column 5 -> index 4
        ("openinterest", -1),  # This column does not exist
        ("pure_bond_value", 5),  # Column 6 -> index 5
        ("convert_value", 6),  # Column 7 -> index 6
        ("pure_bond_premium_rate", 7),  # Column 8 -> index 7
        ("convert_premium_rate", 8),  # Column 9 -> index 8
    )

    # Define extended data lines
    lines = ("pure_bond_value", "convert_value", "pure_bond_premium_rate", "convert_premium_rate")


class TwoMAStrategy(bt.Strategy):
    """Dual moving average crossover strategy.

    This strategy implements a classic moving average crossover trading system:
    - Golden cross: Buy signal when short-term MA crosses above long-term MA
    - Death cross: Sell signal when short-term MA crosses below long-term MA

    The strategy uses full position sizing (90% of available cash) for each
    trade and closes the entire position when a sell signal is generated.

    Attributes:
        params (tuple): Strategy parameters including short_period and long_period.
        short_ma (Indicator): Short-term simple moving average.
        long_ma (Indicator): Long-term simple moving average.
        crossover (Indicator): Crossover indicator (+1 for golden cross, -1 for death cross).
        bar_num (int): Counter for number of bars processed.
        buy_count (int): Counter for number of buy orders executed.
        sell_count (int): Counter for number of sell orders executed.

    Parameters:
        short_period (int): Period for short-term moving average (default: 5).
        long_period (int): Period for long-term moving average (default: 20).
    """

    params = (
        ("short_period", 5),
        ("long_period", 20),
    )

    def log(self, txt, dt=None):
        """Log strategy information with timestamp.

        This method prints log messages with an optional timestamp. If no
        datetime is provided, it attempts to extract the timestamp from the
        current data bar.

        Args:
            txt (str): Text message to log.
            dt (datetime, optional): Datetime object to include in the log.
                If None, extracts datetime from current data bar.
        """
        if dt is None:
            try:
                dt_val = self.datas[0].datetime[0]
                if dt_val > 0:
                    dt = bt.num2date(dt_val)
                else:
                    dt = None
            except (IndexError, ValueError):
                dt = None

        if dt:
            print("{}, {}".format(dt.isoformat(), txt))
        else:
            print("%s" % txt)

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables.

        This method sets up the moving average indicators, crossover signal,
        and initializes counters for tracking trading activity.
        """
        # Calculate moving average indicators
        self.short_ma = bt.indicators.SimpleMovingAverage(
            self.datas[0].close, period=self.p.short_period
        )
        self.long_ma = bt.indicators.SimpleMovingAverage(
            self.datas[0].close, period=self.p.long_period
        )

        # Record crossover signal
        self.crossover = bt.indicators.CrossOver(self.short_ma, self.long_ma)

        # Record bar count
        self.bar_num = 0

        # Record trade counts
        self.buy_count = 0
        self.sell_count = 0

    def next(self):
        """Execute trading logic for each bar.

        This method is called for each data bar in the backtest. It implements
        the dual moving average crossover strategy:
        1. Buy when golden cross occurs (crossover > 0) and no position exists
        2. Sell when death cross occurs (crossover < 0) and position exists

        Position sizing uses 90% of available cash for each buy order.
        """
        self.bar_num += 1

        # If no position and golden cross occurs (short MA crosses above long MA), buy
        if not self.position:
            if self.crossover > 0:
                # Buy using 90% of current cash
                cash = self.broker.get_cash()
                price = self.datas[0].close[0]
                size = int(cash * 0.9 / price)
                if size > 0:
                    self.buy(size=size)
                    self.buy_count += 1
        else:
            # If holding position and death cross occurs (short MA crosses below long MA), sell
            if self.crossover < 0:
                self.close()
                self.sell_count += 1

    def stop(self):
        """Log final statistics when backtest completes.

        This method is called at the end of the backtest to print a summary
        of trading activity including total bars processed and trade counts.
        """
        self.log(
            f"bar_num = {self.bar_num}, buy_count = {self.buy_count}, sell_count = {self.sell_count}"
        )

    def notify_order(self, order):
        """Handle order status changes.

        This method is called when an order's status changes. It logs completed
        orders with execution price and size.

        Args:
            order (Order): The order object with updated status.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY: Price={order.executed.price:.2f}, Size={order.executed.size:.2f}")
            else:
                self.log(f"SELL: Price={order.executed.price:.2f}, Size={order.executed.size:.2f}")

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        This method is called when a trade is closed. It logs the profit
        or loss for the completed trade.

        Args:
            trade (Trade): The trade object with profit/loss information.
        """
        if trade.isclosed:
            self.log(f"Trade completed: Gross profit={trade.pnl:.2f}, Net profit={trade.pnlcomm:.2f}")


def load_bond_data(filename: str = "113013.csv") -> pd.DataFrame:
    """Load and preprocess convertible bond data from CSV file.

    This function reads a CSV file containing convertible bond data, renames
    columns to standard names, sets the datetime index, and removes unnecessary
    columns. It also handles data type conversion and removes null values.

    Expected CSV Columns (before renaming):
        symbol, bond_symbol, datetime, open, high, low, close, volume,
        pure_bond_value, convert_value, pure_bond_premium_rate,
        convert_premium_rate

    Args:
        filename (str, optional): Name of the CSV file to load. Defaults to
            '113013.csv'.

    Returns:
        pd.DataFrame: Preprocessed DataFrame with datetime index and the
            following columns: open, high, low, close, volume, pure_bond_value,
            convert_value, pure_bond_premium_rate, convert_premium_rate.

    Raises:
        FileNotFoundError: If the data file cannot be found (raised by
            resolve_data_path).
    """
    df = pd.read_csv(resolve_data_path(filename))
    df.columns = [
        "symbol",
        "bond_symbol",
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
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    df = df.drop(["symbol", "bond_symbol"], axis=1)
    df = df.dropna()
    df = df.astype("float")
    return df


def test_two_ma_strategy():
    """Test the dual moving average strategy with convertible bond data.

    This function sets up and runs a complete backtest of the TwoMAStrategy
    using convertible bond data (113013.csv). It:

    1. Creates a Cerebro engine and adds the TwoMAStrategy with default parameters
    2. Loads and adds convertible bond data
    3. Sets commission rates and initial capital
    4. Adds performance analyzers (Sharpe ratio, returns, drawdown, trade analysis)
    5. Runs the backtest
    6. Prints performance metrics
    7. Asserts expected results to validate strategy behavior

    Expected Test Values:
        - bar_num: 1424
        - buy_count: 52
        - sell_count: 51
        - total_trades: 51
        - sharpe_ratio: -0.4876104524755018
        - annual_return: -0.02770615921670656
        - max_drawdown: 0.23265126671771275
        - final_value: 85129.07932299998

    Raises:
        AssertionError: If any of the expected values do not match within tolerance.
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Add strategy
    cerebro.addstrategy(TwoMAStrategy, short_period=5, long_period=20)

    # Load data
    print("Loading bond data...")
    df = load_bond_data("113013.csv")
    print(f"Data range: {df.index[0]} to {df.index[-1]}, total {len(df)} records")

    # Add data
    feed = ExtendPandasFeed(dataname=df)
    cerebro.adddata(feed, name="113013")

    # Set commission
    cerebro.broker.setcommission(commission=0.001)

    # Set initial cash
    cerebro.broker.setcash(100000.0)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    # Run backtest
    print("Starting backtest...")
    results = cerebro.run()

    # Get results
    strat = results[0]
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get("sharperatio")
    annual_return = strat.analyzers.my_returns.get_analysis().get("rnorm")
    max_drawdown = strat.analyzers.my_drawdown.get_analysis()["max"]["drawdown"] / 100
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    # Print results
    print("\n" + "=" * 50)
    print("Backtest Results:")
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
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1424, f"Expected bar_num=1424, got {strat.bar_num}"
    assert strat.buy_count == 52, f"Expected buy_count=52, got {strat.buy_count}"
    assert strat.sell_count == 51, f"Expected sell_count=51, got {strat.sell_count}"
    assert total_trades == 51, f"Expected total_trades=51, got {total_trades}"
    assert abs(sharpe_ratio - (-0.4876104524755018)) < 1e-6, f"Expected sharpe_ratio=-0.4876104524755018, got {sharpe_ratio}"
    assert abs(annual_return - (-0.02770615921670656)) < 1e-6, f"Expected annual_return=-0.02770615921670656, got {annual_return}"
    assert abs(max_drawdown - 0.23265126671771275) < 1e-6, f"Expected max_drawdown=0.23265126671771275, got {max_drawdown}"
    assert abs(final_value - 85129.07932299998) < 0.01, f"Expected final_value=85129.07932299998, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Dual Moving Average Strategy Test")
    print("=" * 60)
    test_two_ma_strategy()
