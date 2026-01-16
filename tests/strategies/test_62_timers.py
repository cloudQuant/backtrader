#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test case: Timers

Reference source: backtrader-master2/samples/timers/scheduled.py
Tests strategy timer functionality using a dual moving average crossover strategy
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching in common locations.

    This function searches for a data file in multiple standard locations
    relative to the test directory, including the current directory, parent
    directory, and 'datas' subdirectories.

    Args:
        filename (str): The name of the data file to locate.

    Returns:
        Path: The absolute path to the first found matching file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths.

    Example:
        >>> path = resolve_data_path("2005-2006-day-001.txt")
        >>> print(path)
        /path/to/tests/strategies/datas/2005-2006-day-001.txt
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


class TimerStrategy(bt.Strategy):
    """Timer strategy - Dual moving average crossover.

    Strategy logic:
        - Buy when the fast line crosses above the slow line
        - Sell and close position when the fast line crosses below the slow line
        - Simultaneously test timer functionality
    """
    params = dict(
        when=bt.timer.SESSION_START,
        timer=True,
        fast_period=10,
        slow_period=30,
    )

    def __init__(self):
        """Initialize the TimerStrategy with indicators and tracking variables.

        This method sets up the dual moving average crossover indicators,
        optionally adds a timer based on strategy parameters, and initializes
        counters for tracking strategy execution.

        The strategy uses two Simple Moving Averages (SMA):
        - Fast SMA: Shorter period for tracking recent price movements
        - Slow SMA: Longer period for tracking overall trend

        A crossover indicator detects when the fast line crosses above or
        below the slow line, generating trading signals.

        Additional tracking variables:
        - bar_num: Total number of bars processed
        - timer_count: Number of timer events triggered
        - buy_count: Total buy orders executed
        - sell_count: Total sell orders executed
        - order: Reference to the current pending order
        """
        self.fast_ma = bt.ind.SMA(period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)

        if self.p.timer:
            self.add_timer(when=self.p.when)

        self.bar_num = 0
        self.timer_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.order = None

    def notify_order(self, order):
        """Handle order status updates and track executed trades.

        This callback method is invoked by the backtrader engine whenever
        an order's status changes. It clears the order reference when the
        order is no longer alive and tracks the number of completed buy
        and sell orders.

        Args:
            order (bt.Order): The order object with updated status information.

        Order States Handled:
            - When order is not alive (completed, canceled, or expired):
              Clears self.order to allow new orders to be placed
            - When order status is Completed:
              Increments buy_count if the order was a buy order
              Increments sell_count if the order was a sell order
        """
        if not order.alive():
            self.order = None
        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
            else:
                self.sell_count += 1

    def next(self):
        """Execute the main strategy logic on each bar.

        This method is called by the backtrader engine for each new data bar.
        It implements a dual moving average crossover trading strategy with
        the following logic:

        Trading Rules:
            1. Increment bar counter for each new bar processed
            2. Skip trading if there's a pending order
            3. Bullish crossover (fast > slow):
               - Close any existing position
               - Open a new long position (buy)
            4. Bearish crossover (fast < slow):
               - Close any existing position
               - No short selling (strategy only goes long)

        The crossover indicator values:
            - > 0: Fast line has crossed above slow line (bullish signal)
            - < 0: Fast line has crossed below slow line (bearish signal)
            - = 0: No crossover (neutral)
        """
        self.bar_num += 1
        if self.order:
            return
        if self.crossover > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()

    def notify_timer(self, timer, when, *args, **kwargs):
        """Handle timer events and track timer notifications.

        This callback method is invoked by the backtrader engine when a timer
        added via add_timer() is triggered. The timer can be configured to fire
        at specific times during trading sessions (e.g., session start, session end,
        or at specific intervals).

        Args:
            timer (bt.Timer): The timer object that triggered this callback.
            when: The timing information indicating when the timer fired.
                Format depends on the timer configuration (e.g., SESSION_START).
            *args: Additional positional arguments passed from the timer.
            **kwargs: Additional keyword arguments passed from the timer.

        Note:
            This implementation simply increments the timer_count variable to
            verify that timers are functioning correctly. In a production strategy,
            this method could be used to perform periodic tasks such as:
            - Rebalancing portfolios at specific times
            - Checking market conditions
            - Adjusting position sizes
            - Logging or monitoring activities
        """
        self.timer_count += 1


def test_timers():
    """Test the timer functionality in backtrader strategies.

    This test function validates that the timer system works correctly by:
    1. Loading historical price data for 2005-2006
    2. Running a dual moving average crossover strategy with timers enabled
    3. Verifying that timer events are triggered at the expected frequency
    4. Checking that the strategy executes trades correctly
    5. Analyzing performance metrics (Sharpe ratio, returns, drawdown)

    Test Configuration:
        - Initial Cash: 100,000
        - Strategy: TimerStrategy with fast_period=10, slow_period=30
        - Sizer: FixedSize with stake=10 shares per trade
        - Timer: Enabled at SESSION_START
        - Data: Daily timeframe with session hours 9:00-17:30

    Expected Results:
        - bar_num: 482 (total data bars processed)
        - timer_count: 512 (timer events triggered)
        - buy_count: Number of buy orders executed
        - sell_count: Number of sell orders executed
        - total_trades: 9 (completed round-trip trades)
        - sharpe_ratio: ~0.721 (annualized)
        - annual_return: ~0.024 (2.4%)
        - max_drawdown: ~3.43%
        - final_value: ~104,966.80

    Raises:
        AssertionError: If any of the expected values don't match within
            the specified tolerance.

    Example:
        >>> test_timers()
        ==================================================
        Timers Test
        ==================================================
        Loading data...
        Starting backtest...
        [... output ...]
        All tests passed!
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=str(data_path),
        timeframe=bt.TimeFrame.Days,
        compression=1,
        sessionstart=datetime.time(9, 0),
        sessionend=datetime.time(17, 30),
    )
    cerebro.adddata(data)

    cerebro.addstrategy(TimerStrategy, timer=True, fast_period=10, slow_period=30)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # Add complete analyzers - calculate Sharpe ratio using daily timeframe
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Days, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analysis results
    sharpe = strat.analyzers.sharpe.get_analysis()
    ret = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()

    sharpe_ratio = sharpe.get('sharperatio', None)
    annual_return = ret.get('rnorm', 0)
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    total_trades = trades.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    # Print results in standard format
    print("\n" + "=" * 50)
    print("Timers Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  timer_count: {strat.timer_count}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assert test results
    assert strat.bar_num == 482, f"Expected bar_num=482, got {strat.bar_num}"
    assert strat.timer_count == 512, f"Expected timer_count=512, got {strat.timer_count}"
    assert abs(final_value - 104966.80) < 0.01, f"Expected final_value=104966.80, got {final_value}"
    assert abs(sharpe_ratio - 0.7210685207398165) < 1e-6, f"Expected sharpe_ratio=0.7210685207398165, got {sharpe_ratio}"
    assert abs(annual_return - 0.024145144571516192) < 1e-6, f"Expected annual_return=0.024145144571516192, got {annual_return}"
    assert abs(max_drawdown - 3.430658473286522) < 1e-6, f"Expected max_drawdown=3.430658473286522, got {max_drawdown}"
    assert total_trades == 9, f"Expected total_trades=9, got {total_trades}"

    print("\nAll tests passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Timers Test")
    print("=" * 60)
    test_timers()
