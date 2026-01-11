"""Fear & Greed Sentiment Indicator Strategy Test Case.

This module implements and tests a sentiment-driven trading strategy that uses
the Fear & Greed index to make buy/sell decisions on SPY (S&P 500 ETF).

The strategy is based on the contrarian investing principle:
- Buy when the market shows extreme fear (Fear & Greed index < 10)
- Sell when the market shows extreme greed (Fear & Greed index > 94)

The module includes:
- SPYFearGreedData: Custom data feed for loading SPY price data with sentiment indicators
- FearGreedStrategy: The main strategy implementation
- test_fear_greed_strategy(): Test function that runs the backtest

Reference: https://github.com/cloudQuant/sentiment-fear-and-greed.git
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files by searching multiple possible directory locations.

    This function searches for data files in several predefined locations
    relative to the test file directory, avoiding issues with relative paths
    when the test is run from different working directories.

    Args:
        filename (str): The name of the data file to locate.

    Returns:
        Path: The absolute path to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search locations.

    Search Locations:
        1. Current test directory (tests/strategies/)
        2. Parent directory (tests/)
        3. Grandparent directory (project root)
        4. tests/datas/ subdirectory
        5. BACKTRADER_DATA_DIR environment variable path (if set)
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


class SPYFearGreedData(bt.feeds.GenericCSVData):
    """Custom data feed for loading SPY price data with Fear & Greed sentiment indicators.

    This data feed extends GenericCSVData to load SPY (S&P 500 ETF) historical price
    data along with three additional sentiment indicators:
    - Put/Call Ratio: Options market sentiment indicator
    - Fear & Greed Index: Market sentiment indicator (0-100 scale)
    - VIX: CBOE Volatility Index

    The CSV file must contain columns in the following order:
    Date, Open, High, Low, Close, Adj Close, Volume, Put Call, Fear Greed, VIX

    Attributes:
        lines (tuple): Additional data lines beyond standard OHLCV:
            - put_call: Put/Call ratio from options market
            - fear_greed: Fear & Greed sentiment index (0=extreme fear, 100=extreme greed)
            - vix: CBOE Volatility Index value

    Example:
        >>> data = SPYFearGreedData(
        ...     dataname="spy-put-call-fear-greed-vix.csv",
        ...     fromdate=datetime(2011, 1, 1),
        ...     todate=datetime(2021, 12, 31)
        ... )
        >>> cerebro.adddata(data, name="SPY")
    """
    lines = ('put_call', 'fear_greed', 'vix')

    params = (
        ('dtformat', '%Y-%m-%d'),
        ('datetime', 0),
        ('open', 1),
        ('high', 2),
        ('low', 3),
        ('close', 4),
        ('volume', 6),
        ('openinterest', -1),
        ('put_call', 7),
        ('fear_greed', 8),
        ('vix', 9),
    )


class FearGreedStrategy(bt.Strategy):
    """A contrarian trading strategy based on the Fear & Greed sentiment index.

    This strategy implements a mean-reversion approach by trading against
    extreme market sentiment:
    - Buys SPY when the Fear & Greed index indicates extreme fear (< 10)
    - Sells SPY when the Fear & Greed index indicates extreme greed (> 94)

    The underlying hypothesis is that periods of extreme fear represent
    buying opportunities (markets are oversold), while periods of extreme
    greed represent selling opportunities (markets are overbought).

    Attributes:
        params (tuple): Strategy parameters:
            - fear_threshold (int): Fear level below which to buy (default: 10)
            - greed_threshold (int): Greed level above which to sell (default: 94)
        bar_num (int): Counter for the number of bars processed.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.
        sum_profit (float): Cumulative profit/loss from all closed trades.
        win_count (int): Number of profitable trades.
        loss_count (int): Number of unprofitable trades.
        data0 (Data feed): Reference to the primary data feed (SPY + indicators).
        fear_greed (Line): Reference to the Fear & Greed index data line.
        close (Line): Reference to the closing price data line.

    Example:
        >>> cerebro.addstrategy(
        ...     FearGreedStrategy,
        ...     fear_threshold=10,
        ...     greed_threshold=94
        ... )
    """

    params = (
        ("fear_threshold", 10),   # Fear threshold, buy when below this value
        ("greed_threshold", 94),  # Greed threshold, sell when above this value
    )

    def log(self, txt, dt=None, force=False):
        """Log strategy messages with timestamp.

        Args:
            txt (str): The message text to log.
            dt (datetime, optional): The datetime to use for the timestamp.
                If None, uses the current bar's datetime. Defaults to None.
            force (bool, optional): If True, always log the message.
                If False, suppress logging. Defaults to False.

        Returns:
            None
        """
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize the strategy and set up data references.

        Initializes tracking variables for performance statistics and
        establishes references to the data feed lines needed for
        trading logic.

        Attributes Initialized:
            bar_num (int): Set to 0. Tracks the number of bars processed.
            buy_count (int): Set to 0. Counts buy orders executed.
            sell_count (int): Set to 0. Counts sell orders executed.
            sum_profit (float): Set to 0.0. Accumulates total profit/loss.
            win_count (int): Set to 0. Counts profitable trades.
            loss_count (int): Set to 0. Counts unprofitable trades.
            data0 (Data feed): Reference to self.datas[0], the primary data feed.
            fear_greed (Line): Reference to the Fear & Greed index line.
            close (Line): Reference to the closing price line.
        """
        # Record statistics
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0

        # Get data references - access via datas list for consistency
        self.data0 = self.datas[0]
        self.fear_greed = self.data0.fear_greed
        self.close = self.data0.close

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Called by Backtrader when a trade is closed. Updates the strategy's
        performance statistics by tracking wins, losses, and cumulative profit.

        Args:
            trade (backtrader.Trade): The completed trade object containing
                profit/loss information via trade.pnl and trade.pnlcomm.

        Returns:
            None

        Notes:
            - Only processes closed trades (trade.isclosed == True)
            - Gross profit (trade.pnl) is used for win/loss classification
            - Both gross and net profit (after commissions) are logged
        """
        if not trade.isclosed:
            return
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl
        self.log(f"Trade completed: Gross profit={trade.pnl:.2f}, Net profit={trade.pnlcomm:.2f}, Cumulative={self.sum_profit:.2f}")

    def notify_order(self, order):
        """Handle order status change notifications.

        Called by Backtrader when an order's status changes. Logs order
        execution details and any order failures.

        Args:
            order (backtrader.Order): The order object with updated status.

        Returns:
            None

        Notes:
            - Ignores Submitted and Accepted status (order still pending)
            - Logs execution price and size for Completed orders
            - Logs status for Canceled, Margin, or Rejected orders
        """
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"Buy executed: Price={order.executed.price:.2f}, Size={order.executed.size}")
            else:
                self.log(f"Sell executed: Price={order.executed.price:.2f}, Size={order.executed.size}")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order status: {order.Status[order.status]}")

    def next(self):
        """Execute trading logic for each bar.

        This method is called by Backtrader for each new bar of data.
        Implements the core strategy logic:
        1. Buy when Fear & Greed index falls below fear_threshold (extreme fear)
        2. Sell when Fear & Greed index rises above greed_threshold (extreme greed)

        Returns:
            None

        Notes:
            - Only buys if not already in a position
            - Only sells if currently holding a position
            - Position size is calculated based on available cash
            - Uses full position size when selling (closes entire position)
        """
        self.bar_num += 1

        # Calculate buyable quantity
        size = int(self.broker.getcash() / self.close[0])

        # Buy when extremely fearful
        if self.fear_greed[0] < self.p.fear_threshold and not self.position:
            if size > 0:
                self.buy(size=size)
                self.buy_count += 1

        # Sell when extremely greedy
        if self.fear_greed[0] > self.p.greed_threshold and self.position.size > 0:
            self.sell(size=self.position.size)
            self.sell_count += 1

    def stop(self):
        """Output final statistics when the strategy execution completes.

        Called by Backtrader after all data has been processed. Calculates
        and logs the final performance statistics including total trades,
        win rate, and cumulative profit.

        Returns:
            None

        Outputs:
            A formatted log message containing:
            - bar_num: Total number of bars processed
            - buy_count: Total buy orders executed
            - sell_count: Total sell orders executed
            - wins: Number of profitable trades
            - losses: Number of unprofitable trades
            - win_rate: Percentage of profitable trades (0-100)
            - profit: Total cumulative profit/loss
        """
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_fear_greed_strategy():
    """Test the Fear & Greed Sentiment Indicator Strategy with backtesting.

    This function performs a comprehensive backtest of the FearGreedStrategy
    using historical SPY data with Fear & Greed sentiment indicators from
    2011-2021. It validates the strategy's performance against expected
    values to ensure correct implementation.

    The test:
    1. Loads SPY price data with sentiment indicators (Put/Call, Fear & Greed, VIX)
    2. Runs the FearGreedStrategy with fear_threshold=10, greed_threshold=94
    3. Analyzes performance using Sharpe Ratio, Returns, DrawDown, and TradeAnalyzer
    4. Asserts that results match expected values

    Raises:
        AssertionError: If any of the performance metrics don't match expected values.
        FileNotFoundError: If the required data file cannot be located.

    Expected Results:
        - bar_num: 2445 bars processed
        - buy_count: 6 buy orders executed
        - sell_count: 2 sell orders executed
        - win_count: 2 profitable trades
        - loss_count: 0 unprofitable trades
        - total_trades: 3 completed trades
        - sharpe_ratio: 0.8915453296028274
        - annual_return: 0.11230697705249652 (11.23%)
        - max_drawdown: 0.2428350846476322 (24.28%)
        - final_value: $280,859.60 (starting from $100,000)
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Set initial capital
    cerebro.broker.setcash(100000.0)

    # Load data (datas[0])
    print("Loading SPY + Fear & Greed data...")
    data_path = resolve_data_path("spy-put-call-fear-greed-vix.csv")
    data_feed = SPYFearGreedData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2011, 1, 1),
        todate=datetime.datetime(2021, 12, 31),
    )
    cerebro.adddata(data_feed, name="SPY")

    # Add strategy
    cerebro.addstrategy(
        FearGreedStrategy,
        fear_threshold=10,
        greed_threshold=94,
    )

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
    drawdown_info = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown_info["max"]["drawdown"] / 100 if drawdown_info["max"]["drawdown"] else 0
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    # Print results
    print("\n" + "=" * 50)
    print("Fear & Greed Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  win_count: {strat.win_count}")
    print(f"  loss_count: {strat.loss_count}")
    print(f"  sum_profit: {strat.sum_profit:.2f}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assertions - ensure strategy runs correctly
    assert strat.bar_num == 2445, f"Expected bar_num=2445, got {strat.bar_num}"
    assert strat.buy_count == 6, f"Expected buy_count=6, got {strat.buy_count}"
    assert strat.sell_count == 2, f"Expected sell_count=2, got {strat.sell_count}"
    assert strat.win_count == 2, f"Expected win_count=2, got {strat.win_count}"
    assert strat.loss_count == 0, f"Expected loss_count=0, got {strat.loss_count}"
    assert total_trades == 3, f"Expected total_trades=3, got {total_trades}"
    assert abs(sharpe_ratio - 0.8915453296028274) < 1e-6, f"Expected sharpe_ratio=0.8915453296028274, got {sharpe_ratio}"
    assert abs(annual_return - (0.11230697705249652)) < 1e-6, f"Expected annual_return=0.11230697705249652, got {annual_return}"
    assert abs(max_drawdown - 0.2428350846476322) < 1e-6, f"Expected max_drawdown=0.2428350846476322, got {max_drawdown}"
    assert abs(final_value - 280859.6) < 0.01, f"Expected final_value=280859.60, got {final_value}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Fear & Greed Sentiment Indicator Strategy Test")
    print("=" * 60)
    test_fear_greed_strategy()
