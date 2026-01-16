"""Test cases for Put/Call ratio sentiment strategy.

This module implements and tests a sentiment-driven trading strategy that uses
the Put/Call ratio as a market sentiment indicator. The strategy is based on
the contrarian trading principle that extreme market sentiment often precedes
reversals.

The module contains:
- SPYPutCallData: Custom data feed for loading SPY price data with Put/Call ratio
- PutCallStrategy: Trading strategy implementing sentiment-based logic
- test_put_call_strategy: Test function validating strategy behavior

Strategy Logic:
- High Put/Call ratio (> 1.0) indicates market fear -> Buy signal (contrarian)
- Low Put/Call ratio (< 0.45) indicates market greed -> Sell signal

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
    """Locate data files by searching multiple potential directory locations.

    This function searches for data files in several predefined locations to
    avoid relative path issues when running tests from different directories.
    It checks the current directory, parent directories, and an optional
    environment variable-specified directory.

    Args:
        filename: Name of the data file to locate (e.g., 'spy-put-call-fear-greed-vix.csv').

    Returns:
        Path object pointing to the first matching data file found.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the search paths.

    Search Paths (in order):
        1. BASE_DIR / filename (current test directory)
        2. BASE_DIR.parent / filename (parent directory)
        3. BASE_DIR.parent.parent / filename (grandparent directory)
        4. BASE_DIR.parent.parent / "tests" / "datas" / filename
        5. Path(BACKTRADER_DATA_DIR) / filename (if env var is set)
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


class SPYPutCallData(bt.feeds.GenericCSVData):
    """Custom data feed for loading SPY price data with sentiment indicators.

    This class extends GenericCSVData to load SPY (SPDR S&P 500 ETF) price data
    along with market sentiment indicators including the Put/Call ratio,
    Fear & Greed index, and VIX volatility index.

    CSV Format Requirements:
        Date,Open,High,Low,Close,Adj Close,Volume,Put Call,Fear Greed,VIX

    Attributes:
        lines: Additional data lines beyond standard OHLCV:
            - put_call: Put/Call ratio indicating market sentiment
            - fear_greed: Fear & Greed index value
            - vix: CBOE Volatility Index value

    Parameters:
        dtformat: Date format string (default: '%Y-%m-%d').
        datetime: Column index for date/time (default: 0).
        open: Column index for open price (default: 1).
        high: Column index for high price (default: 2).
        low: Column index for low price (default: 3).
        close: Column index for close price (default: 4).
        volume: Column index for volume (default: 6).
        openinterest: Column index for open interest (default: -1, unused).
        put_call: Column index for Put/Call ratio (default: 7).
        fear_greed: Column index for Fear & Greed index (default: 8).
        vix: Column index for VIX value (default: 9).
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


class PutCallStrategy(bt.Strategy):
    """Contrarian sentiment strategy based on Put/Call ratio.

    This strategy implements a contrarian trading approach using the Put/Call
    ratio as a market sentiment indicator. The Put/Call ratio measures the
    trading volume of put options versus call options and is used as a gauge
    of market sentiment:

    - High ratio (> 1.0): Indicates fear, more puts being bought -> Buy signal
    - Low ratio (< 0.45): Indicates greed/optimism, more calls being bought -> Sell signal

    The strategy assumes that extreme sentiment precedes market reversals,
    allowing for contrarian positioning when the crowd is overly bearish
    or bullish.

    Attributes:
        bar_num: Counter for the number of bars processed.
        buy_count: Counter for total buy orders executed.
        sell_count: Counter for total sell orders executed.
        sum_profit: Cumulative profit/loss from all closed trades.
        win_count: Number of profitable trades.
        loss_count: Number of unprofitable trades.
        data0: Reference to the primary data feed (SPY + indicators).
        put_call: Reference to the Put/Call ratio data line.
        close: Reference to the close price data line.

    Parameters:
        high_threshold: Put/Call ratio threshold for buy signals (default: 1.0).
            When ratio exceeds this value, market is considered fearful.
        low_threshold: Put/Call ratio threshold for sell signals (default: 0.45).
            When ratio falls below this value, market is considered greedy.

    Data Requirements:
        datas[0]: Must contain SPY price data with Put/Call ratio line.
            Accessible via self.data0.put_call and self.data0.close.

    Trading Logic:
        - Entry: Buy when Put/Call ratio > high_threshold and not in position
        - Exit: Sell entire position when Put/Call ratio < low_threshold
        - Position sizing: Use all available cash (full investment)
    """

    params = (
        ("high_threshold", 1.0),   # High threshold, buy above this value (fear)
        ("low_threshold", 0.45),   # Low threshold, sell below this value (greed)
    )

    def log(self, txt, dt=None, force=False):
        """Log strategy messages with timestamp.

        Args:
            txt: Message text to log.
            dt: Optional datetime for the log entry. If None, uses current bar's datetime.
            force: If True, always log. If False, suppress logging (default: False).

        Returns:
            None
        """
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize strategy attributes and data references.

        Sets up tracking variables for trade statistics and creates convenient
        references to the data feed's lines for easier access in the strategy logic.
        """
        # Initialize statistics counters
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0

        # Create data references for easier access
        self.data0 = self.datas[0]
        self.put_call = self.data0.put_call
        self.close = self.data0.close

    def notify_trade(self, trade):
        """Handle trade completion events and update statistics.

        Called by Backtrader when a trade is closed. Updates win/loss counters
        and cumulative profit based on the trade's P&L.

        Args:
            trade: Trade object containing information about the completed trade.

        Returns:
            None

        Notes:
            - Only processes closed trades (trade.isclosed == True)
            - Updates win_count if trade.pnl > 0, otherwise updates loss_count
            - Logs trade details including gross P&L, net P&L, and cumulative profit
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
        """Handle order status changes and log execution details.

        Called by Backtrader when an order's status changes. Logs order execution
        details for filled orders and warnings for failed orders.

        Args:
            order: Order object containing status and execution information.

        Returns:
            None

        Notes:
            - Ignores Submitted and Accepted status (order pending)
            - Logs execution price and size for Completed orders
            - Logs warnings for Canceled, Margin, or Rejected orders
        """
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.log(f"Buy executed: price={order.executed.price:.2f}, size={order.executed.size}")
            else:
                self.log(f"Sell executed: price={order.executed.price:.2f}, size={order.executed.size}")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order status: {order.Status[order.status]}")

    def next(self):
        """Execute trading logic for each bar.

        This method is called by Backtrader for each new bar. Implements the
        core strategy logic:
        1. Calculates position size based on available cash
        2. Generates buy signal when Put/Call ratio exceeds high_threshold (fear)
        3. Generates sell signal when Put/Call ratio falls below low_threshold (greed)

        Returns:
            None

        Trading Rules:
            - Buy: Put/Call ratio > high_threshold AND no current position
            - Sell: Put/Call ratio < low_threshold AND currently holding position
            - Position sizing: Full cash investment (size = cash / close_price)
        """
        self.bar_num += 1

        # Calculate position size based on available cash
        size = int(self.broker.getcash() / self.close[0])

        # Buy signal: High Put/Call ratio indicates market fear (contrarian buy)
        if self.put_call[0] > self.p.high_threshold and not self.position:
            if size > 0:
                self.buy(size=size)
                self.buy_count += 1

        # Sell signal: Low Put/Call ratio indicates market greed (contrarian sell)
        if self.put_call[0] < self.p.low_threshold and self.position.size > 0:
            self.sell(size=self.position.size)
            self.sell_count += 1

    def stop(self):
        """Calculate and log final strategy performance statistics.

        Called by Backtrader when the backtest completes. Computes and displays
        comprehensive statistics including trade counts, win rate, and total profit.

        Returns:
            None

        Statistics Logged:
            - bar_num: Total number of bars processed
            - buy_count: Total buy orders executed
            - sell_count: Total sell orders executed
            - win_count: Number of profitable trades
            - loss_count: Number of unprofitable trades
            - win_rate: Percentage of profitable trades (wins / total trades * 100)
            - sum_profit: Cumulative profit/loss from all trades
        """
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_put_call_strategy():
    """Run comprehensive backtest of Put/Call ratio sentiment strategy.

    This test function validates the PutCallStrategy implementation by running
    a backtest on historical SPY data from 2011-2021. It verifies that the
    strategy correctly interprets sentiment signals and produces expected results.

    Test Setup:
        - Initial capital: $100,000
        - Data period: 2011-01-01 to 2021-12-31
        - Strategy parameters: high_threshold=1.0, low_threshold=0.45
        - Data source: SPY with Put/Call ratio, Fear & Greed, and VIX

    Expected Results:
        - 2,445 bars processed
        - 6 buy orders, 3 sell orders
        - 3 winning trades, 0 losing trades
        - 100% win rate, $140,069.35 profit
        - Sharpe ratio: ~0.827
        - Annual return: ~9.45%
        - Max drawdown: ~24.77%

    Raises:
        AssertionError: If any of the expected results don't match actual values.
        FileNotFoundError: If the required data file cannot be located.

    Returns:
        None
    """
    # Create cerebro engine
    cerebro = bt.Cerebro(stdstats=True)

    # Set initial capital
    cerebro.broker.setcash(100000.0)

    # Load SPY + Put/Call ratio data
    print("Loading SPY + Put/Call data...")
    data_path = resolve_data_path("spy-put-call-fear-greed-vix.csv")
    data_feed = SPYPutCallData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2011, 1, 1),
        todate=datetime.datetime(2021, 12, 31),
    )
    cerebro.adddata(data_feed, name="SPY")

    # Add strategy with default parameters
    cerebro.addstrategy(
        PutCallStrategy,
        high_threshold=1.0,
        low_threshold=0.45,
    )

    # Add performance analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    # Run backtest
    print("Starting backtest...")
    results = cerebro.run()

    # Extract results
    strat = results[0]
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get("sharperatio")
    annual_return = strat.analyzers.my_returns.get_analysis().get("rnorm")
    drawdown_info = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown_info["max"]["drawdown"] / 100 if drawdown_info["max"]["drawdown"] else 0
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    # Print results summary
    print("\n" + "=" * 50)
    print("Put/Call Ratio Strategy Backtest Results:")
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

    # Validate results against expected values
    assert strat.bar_num == 2445, f"Expected bar_num=2445, got {strat.bar_num}"
    assert strat.buy_count == 6, f"Expected buy_count=6, got {strat.buy_count}"
    assert strat.sell_count == 3, f"Expected sell_count=3, got {strat.sell_count}"
    assert strat.win_count == 3, f"Expected win_count=3, got {strat.win_count}"
    assert strat.loss_count == 0, f"Expected loss_count=0, got {strat.loss_count}"
    assert total_trades == 3, f"Expected total_trades=3, got {total_trades}"
    assert abs(sharpe_ratio - 0.8266766851573092) < 1e-6, f"Expected sharpe_ratio=0.8266766851573092, got {sharpe_ratio}"
    assert abs(annual_return - (0.09446114583761168)) < 1e-6, f"Expected annual_return=0.09446114583761168, got {annual_return}"
    assert abs(max_drawdown - 0.24769723055528914) < 1e-6, f"Expected max_drawdown=0.24769723055528914, got {max_drawdown}"
    assert abs(final_value - 240069.35) < 0.01, f"Expected final_value=240069.35, got {final_value}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Put/Call Ratio Strategy Test")
    print("=" * 60)
    test_put_call_strategy()
