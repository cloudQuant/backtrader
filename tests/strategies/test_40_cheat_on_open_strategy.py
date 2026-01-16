#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for Cheat On Open strategy functionality.

This module tests the cheat-on-open feature in backtrader, which allows orders
to be executed at the opening price of the next bar rather than the closing
price. This is particularly useful for simulating realistic order execution
where decisions are made after the close but executed at the next open.

Understanding Cheat On Open:
    By default, backtrader executes orders at the close of the current bar
    when the strategy's next() method is called. With cheat_on_open=True:
    - next() is called BEFORE the bar opens (with previous bar's data)
    - Orders can be executed at the OPEN of the current bar
    - Simulates overnight decisions and market-on-open orders

Key Benefits:
    - More realistic simulation of end-of-day analysis and next-day execution
    - Allows strategies based on after-close calculations
    - Prevents look-ahead bias in order execution
    - Better models real-world trading where decisions are made after close

Use Cases:
    - End-of-day strategies that execute at market open next day
    - Strategies analyzing closing patterns to trade next open
    - Gap trading strategies
    - Overnight holding strategies

Trade-offs:
    - Execution price uncertainty (open may differ from close)
    - Gap risk (overnight news can cause significant price changes)
    - Slippage may be higher at market open

Reference:
    backtrader-master2/samples/cheat-on-open/cheat-on-open.py

Example:
    Run the test directly::

        python test_40_cheat_on_open_strategy.py

    Or use pytest::

        pytest tests/strategies/test_40_cheat_on_open_strategy.py -v
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve data file path by searching in common locations.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Absolute path to the data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search locations.
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


class CheatOnOpenStrategy(bt.Strategy):
    """Dual moving average crossover strategy with cheat-on-open execution.

    This strategy implements a classic dual moving average crossover system and
    demonstrates the use of the cheat-on-open feature to execute orders at the
    opening price of the next bar instead of the closing price. This more
    realistically simulates end-of-day analysis and next-day trading decisions.

    Strategy Logic:
        The strategy uses two Simple Moving Averages (SMA) with different periods:
        - Short SMA (fast): Responds quickly to price changes
        - Long SMA (slow): Smooths out noise, shows overall trend

        Crossover signals:
        - Bullish crossover (short crosses above long): Buy signal
        - Bearish crossover (short crosses below long): Exit signal

    Cheat On Open Behavior:
        With cheat_on_open=True in Cerebro:
        - Strategy's next() method is called BEFORE the bar opens
        - Can access previous bar's indicators for decision making
        - Orders placed in next() execute at the CURRENT bar's open price
        - Simulates overnight decisions and market-on-open orders

    Parameters:
        periods (list): List of two integers specifying SMA periods.
            First element is fast SMA period (default: 10).
            Second element is slow SMA period (default: 30).
            Shorter fast period = more signals, more noise.
            Longer slow period = smoother trend, slower signals.

    Attributes:
        signal (bt.ind.CrossOver): Crossover indicator detecting when fast SMA
            crosses above/below slow SMA. Returns positive on bullish crossover,
            negative on bearish crossover.
        order (bt.Order): Reference to the currently pending order, or None.
        bar_num (int): Counter tracking total bars processed during backtest.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.
        win_count (int): Number of profitable closed trades.
        loss_count (int): Number of unprofitable closed trades.
        sum_profit (float): Total profit/loss across all closed trades.

    Example:
        >>> cerebro = bt.Cerebro(cheat_on_open=True)
        >>> cerebro.addstrategy(CheatOnOpenStrategy, periods=[10, 30])
        >>> results = cerebro.run()

    Note:
        The cheat-on-open feature is particularly useful for strategies that:
        - Analyze end-of-day data and trade next day
        - Want to avoid look-ahead bias in execution
        - Simulate realistic market-on-open order execution
    """

    params = dict(
        periods=[10, 30],
    )

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables.

        Creates the dual moving average system with a crossover signal detector.
        Also initializes all tracking variables for monitoring strategy performance.
        """
        # Create Simple Moving Averages for each period in params
        # Fast SMA (shorter period) reacts quickly to price changes
        # Slow SMA (longer period) shows overall trend direction
        mas = [bt.ind.SMA(period=x) for x in self.p.periods]

        # Create crossover signal detector
        # Returns: > 0 when fast SMA crosses above slow SMA (bullish)
        #          < 0 when fast SMA crosses below slow SMA (bearish)
        self.signal = bt.ind.CrossOver(*mas)

        # Initialize order tracking
        self.order = None

        # Initialize performance tracking variables
        self.bar_num = 0      # Total bars processed
        self.buy_count = 0    # Total buy orders executed
        self.sell_count = 0   # Total sell orders executed
        self.win_count = 0    # Number of winning trades
        self.loss_count = 0   # Number of losing trades
        self.sum_profit = 0.0 # Cumulative profit/loss

    def notify_order(self, order):
        """Handle order status updates and track executed orders.

        This method is called by the backtrader engine whenever an order's
        status changes. It updates buy/sell counters when orders complete.

        Args:
            order (bt.Order): The order object with updated status information.
                Possible statuses include: Submitted, Accepted, Completed,
                Canceled, Expired, Margin, Rejected.

        Note:
            Only completed orders are counted. The order reference is cleared
            after processing to allow new orders to be placed.
        """
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1
            self.order = None

    def notify_trade(self, trade):
        """Handle trade completion updates and calculate profit/loss.

        This method is called when a trade is closed (position fully exited).
        It tracks wins, losses, and cumulative profit to evaluate strategy
        performance.

        Args:
            trade (bt.Trade): The trade object with profit/loss information.
                Contains pnlcomm attribute (profit/loss including commission).

        Note:
            Trade is only considered closed when the entire position is exited.
            Partial closes don't trigger this notification.
        """
        if trade.isclosed:
            # Add trade profit/loss to cumulative total
            self.sum_profit += trade.pnlcomm

            # Track win/loss statistics
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        """Execute trading logic for each bar.

        With cheat_on_open=True, this method is called BEFORE the bar opens,
        allowing decisions based on previous bar's data to execute at the
        current bar's open price.

        Implements dual moving average crossover strategy:
        1. Check for pending orders and wait if one exists
        2. Exit long position when fast SMA crosses below slow SMA
        3. Enter long position when fast SMA crosses above slow SMA

        The strategy only takes long positions, aiming to capture uptrends
        identified by the bullish crossover of the moving averages.
        """
        self.bar_num += 1

        # Skip if order already pending - wait for it to complete
        if self.order is not None:
            return

        # Exit logic: Close position if bearish crossover (short < long)
        if self.position:
            if self.signal < 0:
                self.order = self.close()

        # Entry logic: Open position if bullish crossover (short > long)
        elif self.signal > 0:
            self.order = self.buy()

    def stop(self):
        """Print strategy performance summary after backtest completion.

        This method is called once at the end of the backtest. It calculates
        and displays win rate and final statistics to evaluate strategy
        performance.
        """
        # Calculate win rate (percentage of profitable trades)
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0

        # Display final performance summary
        print(f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
              f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
              f"wins={self.win_count}, losses={self.loss_count}, "
              f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}")


def test_cheat_on_open_strategy():
    """Test the Cheat On Open strategy backtest execution and performance.

    This test validates the cheat_on_open functionality by running a complete
    backtest with dual moving average crossover strategy. The key aspect being
    tested is that orders execute at the opening price rather than closing price,
    which should produce specific, consistent performance metrics.

    Test Procedure:
        1. Initialize Cerebro with cheat_on_open=True enabled
        2. Set initial capital to $100,000
        3. Load historical daily data (2005-2006)
        4. Add CheatOnOpenStrategy with default SMA periods [10, 30]
        5. Set fixed position size of 10 shares per trade
        6. Attach performance analyzers
        7. Execute backtest and validate results

    Expected Results:
        - Total bars processed: 482
        - Final portfolio value: ~104966.80
        - Sharpe Ratio: ~11.65 (very high due to specific data period)
        - Annual Return: ~2.41%
        - Maximum Drawdown: ~3.43%

    The cheat-on-open feature should produce results distinct from regular
    execution because orders fill at open prices rather than close prices,
    affecting entry and exit prices for all trades.

    Raises:
        AssertionError: If any performance metric deviates from expected
            values within specified tolerance levels.

    Note:
        Tolerance levels: 0.01 for final_value (accounting for rounding),
        1e-6 for all other metrics (high precision for comparison).
    """
    # Initialize Cerebro with cheat_on_open enabled
    # This allows orders to execute at opening prices instead of closing prices
    cerebro = bt.Cerebro(stdstats=True, cheat_on_open=True)
    cerebro.broker.setcash(100000.0)

    # Load historical daily price data
    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        fromdate=datetime.datetime(2005, 1, 1),
        todate=datetime.datetime(2006, 12, 31)
    )
    cerebro.adddata(data, name="DATA")

    # Add strategy with default parameters
    cerebro.addstrategy(CheatOnOpenStrategy)

    # Set fixed position size (10 shares per trade)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # Attach performance analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    # Run backtest
    print("Running backtest...")
    results = cerebro.run()
    strat = results[0]

    # Extract performance metrics
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Display results
    print("=" * 50)
    print("Cheat On Open Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  total_trades: {total_trades}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Validate results against expected values
    # These specific values confirm cheat_on_open is working correctly
    assert strat.bar_num == 482, f"Expected bar_num=482, got {strat.bar_num}"
    assert abs(final_value - 104966.8) < 0.01, f"Expected final_value=104966.80, got {final_value}"
    assert abs(sharpe_ratio - (11.647332609673429)) < 1e-6, f"Expected sharpe_ratio=11.647, got {sharpe_ratio}"
    assert abs(annual_return - (0.024145144571516192)) < 1e-6, f"Expected annual_return=0.0241, got {annual_return}"
    assert abs(max_drawdown - 3.430658473286522) < 1e-6, f"Expected max_drawdown=3.431, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Cheat On Open Strategy Test")
    print("=" * 60)
    test_cheat_on_open_strategy()
