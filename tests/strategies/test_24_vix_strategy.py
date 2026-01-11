"""VIX Volatility Index Strategy Test Cases.

This module contains test cases for a sentiment-driven trading strategy that uses
the CBOE Volatility Index (VIX) as a market fear/greed indicator. The strategy
trades SPY (SPDR S&P 500 ETF) based on VIX levels.

The strategy logic:
- Buy when VIX > 35 (extreme market fear, contrarian buy signal)
- Sell when VIX < 10 (extreme market calm, exit signal)

This module demonstrates:
- Loading custom CSV data with multiple fields using GenericCSVData
- Implementing a volatility-based trading strategy
- Using sentiment indicators (VIX) for market timing
- Comprehensive performance analysis with multiple analyzers

Reference:
    https://github.com/cloudQuant/sentiment-fear-and-greed.git

Example:
    Run the test directly to execute the backtest::

        python tests/strategies/test_24_vix_strategy.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files by searching multiple possible directory paths.

    This function searches for data files in several common locations to avoid
    failures due to relative path issues. It checks the script directory, parent
    directories, and an optional environment variable.

    Args:
        filename (str): The name of the data file to locate.

    Returns:
        Path: Absolute path to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths.

    Note:
        Search paths (in order):
        1. Current script directory
        2. Parent directory
        3. Grandparent directory
        4. tests/datas/ subdirectory
        5. Directory specified by BACKTRADER_DATA_DIR environment variable (if set)
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


class SPYVixData(bt.feeds.GenericCSVData):
    """Custom data feed for SPY price data with VIX and sentiment indicators.

    This data feed extends GenericCSVData to load SPY (SPDR S&P 500 ETF) price
    data along with additional sentiment indicators including Put/Call ratio,
    Fear & Greed index, and the CBOE Volatility Index (VIX).

    CSV Format:
        The expected CSV file should have the following columns:
        Date, Open, High, Low, Close, Adj Close, Volume, Put Call, Fear Greed, VIX

    Attributes:
        put_call (Line): Put/Call ratio indicator for market sentiment analysis.
        fear_greed (Line): Fear & Greed index measuring market sentiment.
        vix (Line): CBOE Volatility Index value for each bar.

    Parameters:
        dtformat (str): Date format string for parsing CSV dates (default: '%Y-%m-%d').
        datetime (int): Column index for datetime field (default: 0).
        open (int): Column index for open price (default: 1).
        high (int): Column index for high price (default: 2).
        low (int): Column index for low price (default: 3).
        close (int): Column index for close price (default: 4).
        volume (int): Column index for volume (default: 6).
        openinterest (int): Column index for open interest (default: -1, not used).
        put_call (int): Column index for Put/Call ratio (default: 7).
        fear_greed (int): Column index for Fear & Greed index (default: 8).
        vix (int): Column index for VIX value (default: 9).
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


class VIXStrategy(bt.Strategy):
    """Volatility-based trading strategy using the VIX index.

    This strategy implements a contrarian approach to trading SPY based on the
    CBOE Volatility Index (VIX). The VIX is a fear gauge that measures expected
    market volatility over the next 30 days. The strategy takes long positions
    when the VIX spikes (extreme fear) and exits when the VIX drops to low levels
    (extreme complacency).

    Strategy Logic:
        - Entry: Buy when VIX > 35 (extreme market fear indicates oversold conditions)
        - Exit: Sell when VIX < 10 (extreme calm indicates overbought conditions)

    This is a mean-reversion strategy based on the principle that periods of
    extreme fear are often followed by market recoveries, while periods of
    extreme complacency may precede market pullbacks.

    Attributes:
        bar_num (int): Counter for the number of bars processed.
        buy_count (int): Number of buy orders executed.
        sell_count (int): Number of sell orders executed.
        sum_profit (float): Cumulative profit/loss from all closed trades.
        win_count (int): Number of profitable trades.
        loss_count (int): Number of unprofitable trades.
        data0 (Data): Reference to the primary data feed (SPY).
        vix (Line): Reference to the VIX values from the data feed.
        close (Line): Reference to the closing prices from the data feed.

    Parameters:
        high_threshold (float): VIX level above which to enter long positions
            (default: 35). This represents extreme market fear.
        low_threshold (float): VIX level below which to exit positions
            (default: 10). This represents extreme market calm.
    """

    params = (
        ("high_threshold", 35),  # High threshold: buy above this level (fear)
        ("low_threshold", 10),   # Low threshold: sell below this level (calm)
    )

    def log(self, txt, dt=None, force=False):
        """Log strategy messages with timestamp.

        This method provides controlled logging output. By default, logging is
        disabled unless the force parameter is True, which allows selective
        output of important messages.

        Args:
            txt (str): The message text to log.
            dt (datetime, optional): The datetime to use for the log entry.
                If None, uses the current bar's datetime. Defaults to None.
            force (bool, optional): If True, output the log message; otherwise,
                suppress output. Defaults to False.
        """
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize the VIX strategy.

        Sets up data references and initializes tracking variables for strategy
        statistics including trade counts, profit tracking, and win/loss records.
        """
        # Record statistics
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0

        # Get data references - access via datas list following best practices
        self.data0 = self.datas[0]
        self.vix = self.data0.vix
        self.close = self.data0.close

    def notify_trade(self, trade):
        """Handle trade completion events.

        This method is called by Backtrader when a trade is closed. It updates
        the strategy's statistics by tracking wins, losses, and cumulative profit.

        Args:
            trade (Trade): The trade object that has been closed. Contains
                information about profit/loss, commission, and trade details.

        Note:
            Only processes closed trades (trade.isclosed == True). Open trades
            are ignored.
        """
        if not trade.isclosed:
            return
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl
        self.log(f"Trade completed: gross_profit={trade.pnl:.2f}, net_profit={trade.pnlcomm:.2f}, cumulative={self.sum_profit:.2f}")

    def notify_order(self, order):
        """Handle order status change events.

        This method is called by Backtrader when an order's status changes.
        It logs executed orders and orders that were canceled, rejected, or
        had margin issues.

        Args:
            order (Order): The order object whose status has changed.

        Note:
            Ignores Submitted and Accepted status updates to reduce log noise.
            Only logs Completed, Canceled, Margin, and Rejected orders.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"BUY EXECUTED: price={order.executed.price:.2f}, size={order.executed.size}")
            else:
                self.log(f"SELL EXECUTED: price={order.executed.price:.2f}, size={order.executed.size}")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"ORDER STATUS: {order.Status[order.status]}")

    def next(self):
        """Execute trading logic for each bar.

        This method is called by Backtrader for each bar of data. It implements
        the core strategy logic:
        1. Calculate the maximum position size based on available cash
        2. Enter long position when VIX > high_threshold (market fear)
        3. Exit position when VIX < low_threshold (market calm)

        Note:
            - Only enters long positions when not already in a position
            - Only exits when currently holding a position
            - Position size is calculated as: floor(available_cash / close_price)
        """
        self.bar_num += 1

        # Calculate buyable quantity
        size = int(self.broker.getcash() / self.close[0])

        # Buy when VIX is high (market fear)
        if self.vix[0] > self.p.high_threshold and not self.position:
            if size > 0:
                self.buy(size=size)
                self.buy_count += 1

        # Sell when VIX is low (market calm)
        if self.vix[0] < self.p.low_threshold and self.position.size > 0:
            self.sell(size=self.position.size)
            self.sell_count += 1

    def stop(self):
        """Output strategy statistics when backtest completes.

        This method is called by Backtrader at the end of the backtest. It
        calculates and logs comprehensive performance statistics including
        total bars processed, trade counts, win rate, and cumulative profit.

        Note:
            Win rate is calculated as: (win_count / total_trades) * 100
            where total_trades = win_count + loss_count
        """
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_vix_strategy():
    """Run backtest for the VIX volatility index strategy.

    This test function executes a comprehensive backtest of the VIX-based trading
    strategy using historical SPY and VIX data from 2011-2021. It verifies that
    the strategy executes correctly and produces expected performance metrics.

    The test:
    1. Loads SPY price data with VIX indicators from CSV
    2. Configures the strategy with buy/sell thresholds (VIX > 35, VIX < 10)
    3. Adds performance analyzers (Sharpe Ratio, Returns, Drawdown, Trade Analysis)
    4. Runs the backtest with $100,000 initial capital
    5. Validates results against expected values

    Raises:
        AssertionError: If any of the performance metrics don't match expected values.
        FileNotFoundError: If the required data file cannot be located.

    Note:
        Expected test values (based on 2011-2021 data):
        - Bars processed: 2445
        - Buy signals: 3
        - Sell signals: 1
        - Winning trades: 1
        - Losing trades: 0
        - Total trades: 2
        - Sharpe Ratio: ~0.918
        - Annual Return: ~10.4%
        - Max Drawdown: ~33.7%
        - Final Portfolio Value: $261,273.50
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Set initial cash
    cerebro.broker.setcash(100000.0)

    # Load data (datas[0])
    print("Loading SPY + VIX data...")
    data_path = resolve_data_path("spy-put-call-fear-greed-vix.csv")
    data_feed = SPYVixData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2011, 1, 1),
        todate=datetime.datetime(2021, 12, 31),
    )
    cerebro.adddata(data_feed, name="SPY")

    # Add strategy
    cerebro.addstrategy(
        VIXStrategy,
        high_threshold=35,
        low_threshold=10,
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
    print("VIX Volatility Index Strategy Backtest Results:")
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
    assert strat.buy_count == 3, f"Expected buy_count=3, got {strat.buy_count}"
    assert strat.sell_count == 1, f"Expected sell_count=1, got {strat.sell_count}"
    assert strat.win_count == 1, f"Expected win_count=1, got {strat.win_count}"
    assert strat.loss_count == 0, f"Expected loss_count=0, got {strat.loss_count}"
    assert total_trades == 2, f"Expected total_trades=2, got {total_trades}"
    assert abs(sharpe_ratio - 0.918186863324403) < 1e-6, f"Expected sharpe_ratio=0.918186863324403, got {sharpe_ratio}"
    assert abs(annual_return - (0.1040505783834931)) < 1e-6, f"Expected annual_return=0.1040505783834931, got {annual_return}"
    assert abs(max_drawdown - 0.3367517000981378) < 1e-6, f"Expected max_drawdown=0.3367517000981378, got {max_drawdown}"
    assert abs(final_value - 261273.5) < 0.01, f"Expected final_value=261273.50, got {final_value}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("VIX Volatility Index Strategy Test")
    print("=" * 60)
    test_vix_strategy()
