"""ETF Rotation Strategy Test Case.

This module tests an ETF rotation strategy that rotates between SSE 50 ETF and
ChiNext ETF based on momentum indicators. The strategy uses moving average
ratios to determine which ETF shows stronger momentum and allocates capital
accordingly.

Data Sources:
    - SSE 50 ETF: Large-cap stock ETF (SSE50_ETF.csv)
    - ChiNext ETF: Small-cap growth ETF (ChiNext_ETF.csv)

Strategy Logic:
    The strategy calculates the ratio of current price to moving average for
    both ETFs. When one ETF shows stronger momentum (higher ratio), capital
    is allocated to that ETF. When both ETFs are below their moving averages,
    all positions are closed.

Example:
    >>> python tests/strategies/test_18_etf_rotation_strategy.py
"""

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import pandas as pd
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files based on script directory to avoid relative path failures.

    This function searches for data files in multiple potential locations,
    making the test suite more robust to different execution contexts. It checks
    various standard directories and respects the BACKTRADER_DATA_DIR environment
    variable.

    Args:
        filename: Name of the data file to locate (e.g., 'SSE50_ETF.csv').

    Returns:
        Path object pointing to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched locations.

    Search Order:
        1. tests/strategies/datas/filename
        2. tests/datas/filename
        3. tests/strategies/filename
        4. tests/filename
        5. $BACKTRADER_DATA_DIR/filename (if environment variable is set)
    """
    repo_root = BASE_DIR.parent.parent
    search_paths = [
        BASE_DIR / "datas" / filename,
        repo_root / "tests" / "datas" / filename,
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
    ]

    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    for candidate in search_paths:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"Data file not found: {filename}")


class EtfRotationStrategy(bt.Strategy):
    """ETF Rotation Strategy based on moving average ratio.

    This strategy rotates between two ETFs (SSE 50 ETF and ChiNext ETF) based on
    their momentum relative to their moving averages. The strategy follows these
    rules:

    1. Calculate the ratio of current price to moving average for both ETFs
    2. If both ETFs are below their moving averages, close all positions
    3. If one or both ETFs are above their moving averages:
       - Allocate capital to the ETF with the higher price/MA ratio
       - Switch positions if the currently held ETF underperforms

    Attributes:
        author: Strategy author identifier ('yunjinqi').
        params: Strategy parameters including:
            - ma_period (int): Period for moving average calculation (default: 20).
        bar_num: Counter for the number of bars processed.
        buy_count: Counter for total buy orders executed.
        sell_count: Counter for total sell orders executed.
        sz_ma: Simple moving average for SSE 50 ETF.
        cy_ma: Simple moving average for ChiNext ETF.
        sz_pos: Current position size for SSE 50 ETF.
        cy_pos: Current position size for ChiNext ETF.

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(EtfRotationStrategy, ma_period=20)
        >>> cerebro.run()
    """

    # Strategy author
    author = 'yunjinqi'
    # Strategy parameters
    params = (("ma_period", 20),)

    def log(self, txt, dt=None):
        """Log strategy information with timestamp.

        Outputs formatted log messages with ISO format timestamps. If no
        datetime is provided, uses the current bar's timestamp from the
        first data feed.

        Args:
            txt: Text message to log.
            dt: Optional datetime object for the log entry. If None, uses
                the current bar's datetime from datas[0].
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def __init__(self):
        """Initialize the ETF rotation strategy.

        Sets up counters for tracking bars and trades, and calculates moving
        averages for both ETFs. The moving averages are used to determine
        momentum signals for rotation decisions.

        Attributes initialized:
            bar_num: Counter for total bars processed.
            buy_count: Counter for buy orders executed.
            sell_count: Counter for sell orders executed.
            sz_ma: SMA(period=params.ma_period) for SSE 50 ETF close price.
            cy_ma: SMA(period=params.ma_period) for ChiNext ETF close price.
        """
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        # Calculate moving averages for both ETFs
        self.sz_ma = bt.indicators.SMA(self.datas[0].close, period=self.p.ma_period)
        self.cy_ma = bt.indicators.SMA(self.datas[1].close, period=self.p.ma_period)

    def prenext(self):
        """Handle prenext phase by calling next().

        This method is called during the initial period when not enough bars
        have been processed to satisfy the minimum period requirements. Since
        futures/ETF data can have mismatched trading dates, we manually call
        next() to ensure the strategy logic runs on every bar.

        This allows the strategy to execute trades even during the warmup period
        when some indicators may not yet have valid values.
        """
        # Call next function in each prenext to handle data with mismatched dates
        self.next()

    def next(self):
        """Execute the core ETF rotation strategy logic.

        This method is called on each bar (or in prenext) and implements the
        rotation strategy:

        1. Get current prices and positions for both ETFs
        2. Check if both ETFs are below their moving averages:
           - Close all positions if true (exit signal)
        3. If at least one ETF is above its moving average:
           - Calculate momentum ratio (close/MA) for both ETFs
           - Allocate to the ETF with higher momentum ratio
           - Switch positions if needed

        Position Management:
            - Uses 95% of available capital for new positions
            - Closes existing position before switching to the other ETF
            - Does nothing if already holding the optimal ETF

        Raises:
            None. Errors in order execution are handled by notify_order().
        """
        self.bar_num += 1
        # Data for the two ETFs
        sz_data = self.datas[0]
        cy_data = self.datas[1]
        # Calculate current positions
        self.sz_pos = self.getposition(sz_data).size
        self.cy_pos = self.getposition(cy_data).size
        # Get current prices for both
        sz_close = sz_data.close[0]
        cy_close = cy_data.close[0]

        # If both ETFs are below moving averages, close all positions
        if sz_close < self.sz_ma[0] and cy_close < self.cy_ma[0]:
            if self.sz_pos > 0:
                self.close(sz_data)
            if self.cy_pos > 0:
                self.close(cy_data)

        # If at least one ETF is above its moving average
        if sz_close > self.sz_ma[0] or cy_close > self.cy_ma[0]:
            # If SSE 50 momentum indicator is larger
            if sz_close / self.sz_ma[0] > cy_close / self.cy_ma[0]:

                # If currently has no position, buy SSE 50 ETF directly
                if self.sz_pos == 0 and self.cy_pos == 0:
                    # Get account value
                    total_value = self.broker.get_value()
                    # Calculate buy quantity
                    lots = int(0.95 * total_value / sz_close)
                    # Buy
                    self.buy(sz_data, size=lots)
                    self.buy_count += 1

                # If currently not holding sz but holding cy, close ChiNext position and buy sz
                if self.sz_pos == 0 and self.cy_pos > 0:
                    # Close ChiNext ETF position
                    self.close(cy_data)
                    self.sell_count += 1
                    # Get account value
                    total_value = self.broker.get_value()
                    # Calculate buy quantity
                    lots = int(0.95 * total_value / sz_close)
                    # Buy
                    self.buy(sz_data, size=lots)
                    self.buy_count += 1

                # If already holding sz, ignore
                if self.sz_pos > 0:
                    pass

            # If ChiNext momentum indicator is larger
            if sz_close / self.sz_ma[0] < cy_close / self.cy_ma[0]:
                # If currently has no position, buy ChiNext ETF directly
                if self.sz_pos == 0 and self.cy_pos == 0:
                    # Get account value
                    total_value = self.broker.get_value()
                    # Calculate buy quantity
                    lots = int(0.95 * total_value / cy_close)
                    # Buy
                    self.buy(cy_data, size=lots)
                    self.buy_count += 1

                # If currently not holding cy but holding sz, close SSE 50 position and buy cy
                if self.sz_pos > 0 and self.cy_pos == 0:
                    # Close SSE 50 ETF position
                    self.close(sz_data)
                    self.sell_count += 1
                    # Get account value
                    total_value = self.broker.get_value()
                    # Calculate buy quantity
                    lots = int(0.95 * total_value / cy_close)
                    # Buy
                    self.buy(cy_data, size=lots)
                    self.buy_count += 1

                # If already holding cy, ignore
                if self.cy_pos > 0:
                    pass

    def notify_order(self, order):
        """Handle order status changes and log order events.

        This callback method is invoked by the broker whenever an order's
        status changes. It logs various order events including rejection,
        margin calls, cancellations, partial fills, and completions.

        Args:
            order: The Order object whose status has changed.

        Order Statuses Handled:
            - Submitted: Order has been submitted to the broker
            - Accepted: Order has been accepted by the broker
            - Rejected: Order was rejected (logs rejection with order ref and data name)
            - Margin: Order triggered a margin call (logs margin event)
            - Cancelled: Order was cancelled (logs cancellation with order ref)
            - Partial: Order was partially filled (logs partial fill event)
            - Completed: Order was fully filled (logs execution details for buy/sell)
        """
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Rejected:
            self.log(f"Rejected : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Margin:
            self.log(f"Margin : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Cancelled:
            self.log(f"Concelled : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Partial:
            self.log(f"Partial : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f" BUY : data_name:{order.p.data._name} price : {order.executed.price} , cost : {order.executed.value} , commission : {order.executed.comm}")

            else:  # Sell
                self.log(f" SELL : data_name:{order.p.data._name} price : {order.executed.price} , cost : {order.executed.value} , commission : {order.executed.comm}")

    def notify_trade(self, trade):
        """Handle trade lifecycle events and log trade information.

        This callback is invoked when a trade opens or closes. A trade represents
        a completed round-trip (entry and exit) for a position. This method logs
        the trade details including profit/loss for closed trades.

        Args:
            trade: The Trade object that has changed state.

        Trade States Handled:
            - Closed: Trade is complete (logs symbol, total profit, net profit)
            - Open: Trade is active (logs symbol and entry price)
        """
        # Output information when a trade ends
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}' .format(
                            trade.getdataname(), trade.pnl, trade.pnlcomm))

        if trade.isopen:
            self.log('open symbol is : {} , price : {} ' .format(
                            trade.getdataname(), trade.price))

    def stop(self):
        """Log final strategy statistics when backtest completes.

        This method is called once at the end of the backtest to output
        summary statistics including the total number of bars processed
        and the count of buy/sell orders executed.

        Outputs:
            Log message with format: "bar_num=X, buy_count=Y, sell_count=Z"
        """
        self.log(f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}")


def load_etf_data(filename: str) -> pd.DataFrame:
    """Load ETF data from CSV file and prepare for backtrader.

    This function reads ETF price data from a CSV file with two columns
    (date and closing price), then augments it with the additional columns
    required by backtrader (open, high, low, volume, openinterest).

    The input CSV format should be:
    - Skip 1 header row
    - Column 0: Date (FSRQ format or similar)
    - Column 1: Closing price

    Since only closing prices are available, open/high/low are set to the
    close value, and volume/openinterest are set to dummy values.

    Args:
        filename: Name of the CSV file to load (e.g., 'SSE50_ETF.csv').
            The file is located using resolve_data_path().

    Returns:
        DataFrame with datetime index and columns:
            - open: Opening price (equal to close)
            - high: Highest price (equal to close)
            - low: Lowest price (equal to close)
            - close: Closing price (from input data)
            - volume: Trading volume (dummy value: 1000000)
            - openinterest: Open interest (dummy value: 1000000)

    Raises:
        FileNotFoundError: If the data file cannot be located.
        ValueError: If the CSV file format is invalid.
    """
    df = pd.read_csv(resolve_data_path(filename), skiprows=1, header=None)
    df.columns = ['datetime', 'close']
    df['open'] = df['close']
    df['high'] = df['close']
    df['low'] = df['close']
    df['volume'] = 1000000
    df['openinterest'] = 1000000
    df.index = pd.to_datetime(df['datetime'])
    df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.astype('float')
    return df


def test_etf_rotation_strategy():
    """Test ETF rotation strategy with historical data.

    This end-to-end test loads historical data for SSE 50 ETF and ChiNext ETF,
    runs the EtfRotationStrategy backtest, and validates the results against
    expected performance metrics.

    Test Configuration:
        - Initial Capital: 50,000
        - Commission: 0.02% (0.0002)
        - MA Period: 20 days
        - Data: SSE 50 ETF and ChiNext ETF from 2011-09-20 onwards
        - Start date: 2011-09-20 (filtered after loading)

    Assertions:
        - bar_num == 2600 (total bars processed)
        - buy_count > 0 (at least one buy order)
        - sell_count > 0 (at least one sell order)
        - total_trades > 0 (at least one completed trade)
        - sharpe_ratio ≈ 0.54 (±0.5 tolerance for platform differences)
        - annual_return ≈ 0.16 (±0.02 tolerance)
        - max_drawdown ≈ 0.32 (±0.05 tolerance)
        - final_value ≈ 235,146 (±5,000 tolerance)

    Raises:
        AssertionError: If any of the performance assertions fail.
        FileNotFoundError: If required data files are missing.
    """
    cerebro = bt.Cerebro(stdstats=True)

    # Load SSE 50 ETF data (SSE 50 ETF - Shanghai Stock Exchange 50 Index ETF)
    print("Loading SSE 50 ETF data...")
    df1 = load_etf_data("SSE50_ETF.csv")
    df1 = df1[df1.index >= pd.to_datetime("2011-09-20")]
    print(f"SSE 50 ETF data range: {df1.index[0]} to {df1.index[-1]}, total {len(df1)} records")
    feed1 = bt.feeds.PandasDirectData(dataname=df1)
    cerebro.adddata(feed1, name="sz")

    # Load ChiNext ETF data (ChiNext ETF - Chinese Growth Enterprise Market Index ETF)
    print("Loading ChiNext ETF data...")
    df2 = load_etf_data("ChiNext_ETF.csv")
    print(f"ChiNext ETF data range: {df2.index[0]} to {df2.index[-1]}, total {len(df2)} records")
    feed2 = bt.feeds.PandasDirectData(dataname=df2)
    cerebro.adddata(feed2, name="cy")

    # Set initial capital and commission
    cerebro.broker.setcash(50000.0)
    cerebro.broker.setcommission(commission=0.0002, stocklike=True)

    # Add strategy
    cerebro.addstrategy(EtfRotationStrategy, ma_period=20)

    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    # Run backtest
    print("\nStarting backtest...")
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
    print("ETF Rotation Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value}")
    print("=" * 50)

    # Assert test results - using exact assertions
    # final_value tolerance: 0.01, other indicators tolerance: 1e-6
    assert strat.bar_num == 2600, f"Expected bar_num=2600, got {strat.bar_num}"
    assert strat.buy_count == 266, f"Expected buy_count > 0, got {strat.buy_count}"
    assert strat.sell_count == 129, f"Expected sell_count > 0, got {strat.sell_count}"
    assert total_trades == 265, f"Expected total_trades > 0, got {total_trades}"
    # Note: sharpe_ratio may vary slightly due to platform differences, using looser tolerance
    assert abs(sharpe_ratio - 0.5429576897026931) < 1e-6, f"Expected sharpe_ratio around 0.54, got {sharpe_ratio}"
    assert abs(annual_return - 0.16189795444232807) < 1e-6, f"Expected annual_return=0.16, got {annual_return}"
    assert abs(max_drawdown - 0.3202798124215756) < 1e-6, f"Expected max_drawdown=0.32, got {max_drawdown}"
    assert abs(final_value - 235146.28691140004) < 0.01, f"Expected final_value=235146, got {final_value}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("ETF Rotation Strategy Test")
    print("=" * 60)
    test_etf_rotation_strategy()
