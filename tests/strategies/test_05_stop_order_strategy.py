"""Stop Loss Order Strategy Test Case.

This module tests the stop loss order functionality using convertible bond index
data (bond_index_000000.csv). It demonstrates a complete trading strategy that
uses moving average crossovers for entry signals and automatic stop loss orders
for risk management.

Strategy Overview:
    - Uses dual moving average crossover (5-day and 20-day) to generate buy signals
    - Automatically places stop loss sell orders after each buy execution
    - Stop loss price is set to 3% below the buy price
    - Monitors for death cross signals to manually close positions before stop loss
    - Tracks and reports trade statistics

Data Requirements:
    - Convertible bond index data file: bond_index_000000.csv
    - Required columns: datetime, open, high, low, close, volume
    - Optional columns: pure_bond_value, convert_value, pure_bond_premium_rate,
      convert_premium_rate

Test Assertions:
    - Processes exactly 4414 bars
    - Executes 4 buy orders
    - Executes 1 manual sell order (death cross exit)
    - Triggers 3 stop loss orders
    - Total of 5 completed trades
    - Specific performance metrics (sharpe ratio, annual return, max drawdown, final value)

Usage:
    Run as standalone script::

        python tests/strategies/test_05_stop_order_strategy.py

    Or use pytest::

        pytest tests/strategies/test_05_stop_order_strategy.py -v
"""

import backtrader as bt
import datetime
import os
from pathlib import Path

import numpy as np
import pandas as pd

from backtrader.cerebro import Cerebro
from backtrader.strategy import Strategy
from backtrader.feeds import PandasData

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files by searching multiple possible directory paths.

    This function searches for data files in several predefined locations to avoid
    failures due to relative path issues when running tests from different directories.
    The search is performed in order, returning the first existing file found.

    Search Order:
        1. Current directory (tests/strategies/)
        2. Parent tests directory
        3. Repository root directory
        4. examples/ subdirectory
        5. tests/datas/ subdirectory
        6. Directory specified by BACKTRADER_DATA_DIR environment variable
        7. Original filename as relative path (fallback)

    Args:
        filename: Name of the data file to locate (e.g., 'bond_index_000000.csv').

    Returns:
        Path object pointing to the first found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the search paths.
            The error message includes all paths that were searched.

    Example:
        >>> path = resolve_data_path('bond_index_000000.csv')
        >>> print(path)
        /path/to/backtrader/tests/datas/bond_index_000000.csv
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

    # Try each path in order
    for candidate in search_paths:
        if candidate.exists():
            return candidate

    # Fallback to original filename
    fallback = Path(filename)
    if fallback.exists():
        return fallback

    # No file found - raise helpful error
    searched = " , ".join(str(path) for path in search_paths + [fallback.resolve()])
    raise FileNotFoundError(f"Data file not found: {filename}. Tried paths: {searched}")


class ExtendPandasFeed(PandasData):
    """Extended Pandas data source with convertible bond specific fields.

    This custom data feed extends the standard PandasData to include additional
    fields specific to convertible bond analysis. It maps DataFrame columns to
    backtrader data lines for loading convertible bond index data.

    DataFrame Structure (after set_index):
        - Index: datetime (converted to datetime objects)
        - Column 0: open (opening price)
        - Column 1: high (highest price)
        - Column 2: low (lowest price)
        - Column 3: close (closing price)
        - Column 4: volume (trading volume)
        - Column 5: pure_bond_value (pure bond valuation)
        - Column 6: convert_value (conversion value)
        - Column 7: pure_bond_premium_rate (premium over pure bond value)
        - Column 8: convert_premium_rate (premium over conversion value)

    Attributes:
        params: Tuple defining column mappings from DataFrame to data lines.
        lines: Tuple defining custom data lines beyond standard OHLCV.

    Example:
        >>> df = pd.read_csv('bond_index.csv', parse_dates=['datetime'])
        >>> df = df.set_index('datetime')
        >>> feed = ExtendPandasFeed(dataname=df)
        >>> cerebro.adddata(feed)
    """

    params = (
        ("datetime", None),  # datetime is index, not a data column
        ("open", 0),  # Column 1 -> index 0
        ("high", 1),  # Column 2 -> index 1
        ("low", 2),  # Column 3 -> index 2
        ("close", 3),  # Column 4 -> index 3
        ("volume", 4),  # Column 5 -> index 4
        ("openinterest", -1),  # Column does not exist
        ("pure_bond_value", 5),  # Column 6 -> index 5
        ("convert_value", 6),  # Column 7 -> index 6
        ("pure_bond_premium_rate", 7),  # Column 8 -> index 7
        ("convert_premium_rate", 8),  # Column 9 -> index 8
    )

    # Define extended data lines for convertible bond specific fields
    lines = ("pure_bond_value", "convert_value", "pure_bond_premium_rate", "convert_premium_rate")


class StopOrderStrategy(bt.Strategy):
    """Stop Loss Order Strategy with Moving Average Crossover.

    This strategy implements a trend-following approach with automatic risk management:

    Entry Logic:
        - Golden cross (short MA crosses above long MA) triggers buy signal
        - Uses 90% of available cash for each trade
        - Only enters when no position is held

    Exit Logic:
        - Death cross (short MA crosses below long MA) triggers manual sell
        - Stop loss orders automatically trigger at 3% below buy price
        - Stop loss orders are placed immediately after each buy execution

    Risk Management:
        - Stop loss percentage: 3% (configurable via stop_loss_pct parameter)
        - Stop loss price: buy_price * (1 - stop_loss_pct)
        - Automatic stop loss placement on every buy

    Indicators:
        - Short SMA: Default 5-period simple moving average
        - Long SMA: Default 20-period simple moving average
        - Crossover: Detects golden cross (positive) and death cross (negative)

    Attributes:
        params: Strategy parameters (short_period, long_period, stop_loss_pct)
        bar_num: Counter for number of bars processed
        buy_count: Counter for buy orders executed
        sell_count: Counter for manual sell orders (death cross exits)
        stop_count: Counter for stop loss orders triggered
        order: Reference to pending main order
        stop_order: Reference to active stop loss order
        buy_price: Price at which the most recent buy was executed

    Example:
        >>> cerebro.addstrategy(StopOrderStrategy,
        ...                    short_period=5,
        ...                    long_period=20,
        ...                    stop_loss_pct=0.03)
    """

    params = (
        ("short_period", 5),
        ("long_period", 20),
        ("stop_loss_pct", 0.03),  # 3% stop loss
    )

    def log(self, txt, dt=None, force=False):
        """Log strategy information with optional timestamp.

        This method provides logging functionality for the strategy, allowing
        formatted output with timestamps. By default, logging is disabled unless
        force=True is specified to avoid excessive output during backtesting.

        Args:
            txt: Text message to log.
            dt: Optional datetime object for the log entry. If None, attempts to
                extract datetime from the current data bar using self.datas[0].datetime[0].
            force: If True, output the log message. If False (default), suppress
                all log output regardless of other arguments.

        Note:
            When dt is None, the method attempts to get the datetime from
            self.datas[0].datetime[0]. If this fails (e.g., no data available),
            no timestamp is printed.

        Example:
            >>> self.log("Buy executed", force=True)
            2020-01-01T00:00:00, Buy executed
        """
        if not force:
            return  # Default: no log output

        # Extract datetime from data if not provided
        if dt is None:
            try:
                dt_val = self.datas[0].datetime[0]
                if dt_val > 0:
                    dt = bt.num2date(dt_val)
                else:
                    dt = None
            except (IndexError, ValueError):
                dt = None

        # Print log with or without timestamp
        if dt:
            print("{}, {}".format(dt.isoformat(), txt))
        else:
            print("%s" % txt)

    def __init__(self):
        """Initialize the StopOrderStrategy with indicators and tracking variables.

        Sets up the dual moving average system for generating trade signals and
        initializes tracking variables for order management and trade statistics.

        Indicators Created:
            - short_ma: Fast simple moving average (default 5-period)
            - long_ma: Slow simple moving average (default 20-period)
            - crossover: Indicator that is positive on golden cross, negative on death cross

        Tracking Variables:
            - bar_num: Counts total bars processed
            - buy_count: Counts buy orders executed
            - sell_count: Counts manual sell orders (death cross exits)
            - stop_count: Counts stop loss orders triggered
            - order: Reference to pending main order (buy/sell)
            - stop_order: Reference to active stop loss order
            - buy_price: Price of most recent buy execution

        Note:
            The crossover indicator is calculated as: short_ma - long_ma
            - crossover > 0: short MA is above long MA (uptrend)
            - crossover < 0: short MA is below long MA (downtrend)
            - crossover crosses from negative to positive: golden cross (buy signal)
            - crossover crosses from positive to negative: death cross (sell signal)
        """
        # Calculate moving average indicators
        self.short_ma = bt.indicators.SimpleMovingAverage(
            self.datas[0].close, period=self.p.short_period
        )
        self.long_ma = bt.indicators.SimpleMovingAverage(
            self.datas[0].close, period=self.p.long_period
        )

        # Crossover indicator: positive = golden cross, negative = death cross
        self.crossover = bt.indicators.CrossOver(self.short_ma, self.long_ma)

        # Initialize tracking counters
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.stop_count = 0  # Stop loss trigger count

        # Save order references
        self.order = None
        self.stop_order = None
        self.buy_price = None

    def next(self):
        """Execute trading logic for each bar.

        This method is called for each bar in the data feed and implements the
        core trading logic:

        Execution Flow:
            1. Increment bar counter for statistics
            2. If pending main order exists, wait for it to complete
            3. If stop loss order is active:
               - Monitor for death cross signal
               - If death cross detected, cancel stop loss and manually close position
            4. If no position exists and golden cross appears:
               - Calculate position size (90% of available cash)
               - Execute buy order
               - Stop loss will be placed in notify_order() after execution

        Position Size Calculation:
            - Uses 90% of available cash (conservative approach)
            - Size = floor((cash * 0.9) / current_price)
            - Ensures some cash remains for fees and potential losses

        Stop Loss Logic:
            - Stop loss order is created in notify_order() after buy executes
            - Stop loss price = buy_price * (1 - stop_loss_pct)
            - Stop loss order type is bt.Order.Stop (market order when stop price hit)

        Note:
            The strategy ensures only one active order at a time. If a stop loss
            order is pending, no new entries are allowed until the position is closed.
        """
        self.bar_num += 1

        # If there are pending orders, wait for completion
        if self.order:
            return

        # If there is a stop loss order waiting, handle death cross exit
        if self.stop_order:
            # Check if death cross appears, need to actively close position
            if self.crossover < 0:
                # Cancel stop loss order before manual close
                self.cancel(self.stop_order)
                self.stop_order = None
                # Close position manually
                self.order = self.close()
                self.sell_count += 1
            return

        # If no position and golden cross appears, execute buy
        if not self.position:
            if self.crossover > 0:
                # Use 90% of current funds to buy
                cash = self.broker.get_cash()
                price = self.datas[0].close[0]
                size = int(cash * 0.9 / price)
                if size > 0:
                    self.order = self.buy(size=size)
                    self.buy_count += 1

    def stop(self):
        """Log final strategy statistics when backtesting completes.

        This method is called at the end of the backtest and outputs a summary
        of trading activity including:
        - Total number of bars processed
        - Number of buy orders executed
        - Number of manual sell orders (death cross exits)
        - Number of stop loss orders triggered

        The statistics help evaluate strategy behavior and performance.
        """
        self.log(
            f"bar_num = {self.bar_num}, buy_count = {self.buy_count}, sell_count = {self.sell_count}, stop_count = {self.stop_count}",
            force=True,
        )

    def notify_order(self, order):
        """Handle order status changes and manage stop loss orders.

        This method is called when an order changes status. It implements the
        stop loss logic by automatically creating stop loss orders after each
        successful buy execution.

        Order Handling:
            - Submitted/Accepted: No action, wait for completion
            - Completed (Buy): Record buy price and create stop loss order
            - Completed (Sell): Record sell and check if it was stop loss
            - Canceled/Margin/Rejected: Log the error

        Stop Loss Creation:
            - Triggered immediately after buy order completes
            - Stop price = buy_price * (1 - stop_loss_pct)
            - Order type = bt.Order.Stop (becomes market order when stop price hit)
            - Size = same as buy size (closes full position)

        Args:
            order: The Order object that changed status. Contains information about
                order type, status, execution price, size, etc.

        Note:
            The stop_count is incremented separately from sell_count to distinguish
            between manual exits (death cross) and automatic stop loss triggers.
        """
        # Ignore submitted/accepted orders
        if order.status in [order.Submitted, order.Accepted]:
            return

        # Handle completed orders
        if order.status == order.Completed:
            if order.isbuy():
                # Log buy execution
                self.log(
                    f"Buy executed: Price={order.executed.price:.2f}, Size={order.executed.size:.0f}",
                    force=True,
                )
                self.buy_price = order.executed.price

                # After successful buy, set stop loss order
                stop_price = self.buy_price * (1 - self.p.stop_loss_pct)
                self.log(f"Set stop loss order: Stop price={stop_price:.2f}", force=True)
                self.stop_order = self.sell(
                    size=order.executed.size, exectype=bt.Order.Stop, price=stop_price
                )
            else:
                # Log sell execution
                self.log(
                    f"Sell executed: Price={order.executed.price:.2f}, Size={abs(order.executed.size):.0f}",
                    force=True,
                )
                self.buy_price = None

                # Check if this is a stop loss order trigger
                if order == self.stop_order:
                    self.stop_count += 1
                    self.log("Stop loss order triggered!", force=True)
                    self.stop_order = None

        # Handle failed orders
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order canceled/insufficient margin/rejected: {order.status}", force=True)

        # Reset order status if not the stop loss order
        if self.stop_order is None or order.ref != self.stop_order.ref:
            self.order = None

    def notify_trade(self, trade):
        """Handle trade completion notifications and log profit/loss.

        This method is called when a trade is closed (both entry and exit
        orders have been executed). It logs the gross profit (before commissions)
        and net profit (after commissions) for the completed trade.

        Trade Metrics:
            - trade.pnl: Gross profit/loss (before commissions)
            - trade.pnlcomm: Net profit/loss (after commissions)
            - trade.isclosed: True if trade is completely closed

        Args:
            trade: The Trade object that was closed. Contains information about
                entry price, exit price, size, profit/loss, commission, etc.

        Note:
            This method only processes trades that are completely closed
            (trade.isclosed is True). Partial trades or open positions are ignored.
        """
        if trade.isclosed:
            self.log(
                f"Trade completed: Gross profit={trade.pnl:.2f}, Net profit={trade.pnlcomm:.2f}",
                force=True,
            )


def load_index_data(filename: str = "bond_index_000000.csv") -> pd.DataFrame:
    """Load and preprocess convertible bond index data from CSV file.

    This function loads the convertible bond index data, performs data cleaning,
    and ensures proper types for backtesting. The data is expected to contain
    OHLCV data plus optional convertible bond specific fields.

    Data Preprocessing:
        1. Convert 'datetime' column to datetime objects
        2. Set datetime as the DataFrame index
        3. Drop rows with missing values (dropna)
        4. Convert all data to float type

    Args:
        filename: Name of the CSV file containing convertible bond index data.
            Defaults to 'bond_index_000000.csv'. The file location is resolved
            using the resolve_data_path() function.

    Returns:
        DataFrame with datetime index and the following columns:
        - open: Opening price
        - high: Highest price
        - low: Lowest price
        - close: Closing price
        - volume: Trading volume
        - pure_bond_value: Pure bond value (optional)
        - convert_value: Conversion value (optional)
        - pure_bond_premium_rate: Pure bond premium rate (optional)
        - convert_premium_rate: Conversion premium rate (optional)

    Raises:
        FileNotFoundError: If the specified data file cannot be found.

    Example:
        >>> df = load_index_data('bond_index_000000.csv')
        >>> print(df.head())
                      open    high     low   close  volume
        datetime
        2020-01-01  100.5  101.2   99.8   100.9    5000
    """
    df = pd.read_csv(resolve_data_path(filename))
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime")
    df = df.dropna()
    df = df.astype("float")
    return df


def test_stop_order_strategy():
    """Test stop loss order strategy with convertible bond index data.

    This test function runs a complete backtest of the StopOrderStrategy using
    historical convertible bond index data (bond_index_000000.csv). It verifies
    strategy behavior and performance metrics against expected values.

    Test Configuration:
        - Initial cash: 100,000
        - Commission: 0.1% per trade
        - Short MA period: 5 bars
        - Long MA period: 20 bars
        - Stop loss percentage: 3%

    Expected Results:
        - Bars processed: 4414
        - Buy orders: 4
        - Manual sells (death cross): 1
        - Stop loss triggers: 3
        - Total trades: 5
        - Sharpe ratio: -0.11532400124757156
        - Annual return: -2.59%
        - Max drawdown: 75.24%
        - Final portfolio value: 62,969.16

    Analyzers Added:
        - TotalValue: Tracks portfolio value over time
        - SharpeRatio: Calculates risk-adjusted return metric
        - Returns: Calculates annualized return
        - DrawDown: Tracks maximum drawdown from peak
        - TradeAnalyzer: Provides detailed trade statistics

    Raises:
        AssertionError: If any of the expected values do not match within
            the specified tolerance (1e-6 for most metrics, 0.01 for final_value).
        FileNotFoundError: If the data file 'bond_index_000000.csv' cannot be found.

    Note:
        The test uses exact value assertions to ensure strategy behavior remains
        consistent. If the data file or strategy logic changes, these expected
        values may need to be updated.
    """
    # Create cerebro engine
    cerebro = bt.Cerebro(stdstats=True)

    # Add strategy with parameters
    cerebro.addstrategy(StopOrderStrategy, short_period=5, long_period=20, stop_loss_pct=0.03)

    # Load data
    print("Loading convertible bond index data...")
    df = load_index_data("bond_index_000000.csv")
    print(f"Data range: {df.index[0]} to {df.index[-1]}, total {len(df)} records")

    # Add data feed
    feed = ExtendPandasFeed(dataname=df)
    cerebro.adddata(feed, name="bond_index")

    # Set commission
    cerebro.broker.setcommission(commission=0.001)

    # Set initial cash
    cerebro.broker.setcash(100000.0)

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
    print("Backtest results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  stop_count: {strat.stop_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # Assert test results (exact values)
    # Tolerance: 1e-6 for most metrics, 0.01 for final_value
    assert strat.bar_num == 4414, f"Expected bar_num=4414, got {strat.bar_num}"
    assert strat.buy_count == 4, f"Expected buy_count=4, got {strat.buy_count}"
    assert strat.sell_count == 1, f"Expected sell_count=1, got {strat.sell_count}"
    assert strat.stop_count == 3, f"Expected stop_count=3, got {strat.stop_count}"
    assert total_trades == 5, f"Expected total_trades=5, got {total_trades}"
    assert abs(sharpe_ratio - (-0.11532400124757156)) < 1e-6, f"Expected sharpe_ratio=-0.11532400124757156, got {sharpe_ratio}"
    assert abs(annual_return - (-0.02594445655033843)) < 1e-6, f"Expected annual_return=-0.02594445655033843, got {annual_return}"
    assert abs(max_drawdown - 0.75241098463008) < 1e-6, f"Expected max_drawdown=0.75241098463008, got {max_drawdown}"
    assert abs(final_value - 62969.156504940926) < 0.01, f"Expected final_value=62969.156504940926, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Stop Loss Order Strategy Test")
    print("=" * 60)
    test_stop_order_strategy()
