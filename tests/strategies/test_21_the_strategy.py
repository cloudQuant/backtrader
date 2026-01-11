#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""EMA Dual Moving Average Crossover Strategy Test Module.

This module tests an EMA (Exponential Moving Average) dual moving average
crossover strategy using multi-period data (5-minute and daily timeframes).

The strategy uses two EMAs with different periods:
- Fast EMA (period 80): More responsive to recent price changes
- Slow EMA (period 200): Smoother, less responsive to noise

Trading signals are generated when the EMAs cross:
- Golden cross (fast EMA crosses above slow EMA): Buy signal
- Death cross (fast EMA crosses below slow EMA): Sell signal

The module includes:
    - EmaCrossStrategy: Multi-period EMA crossover strategy implementation
    - test_ema_cross_strategy(): Test function with historical data validation

Multi-Period Data Usage:
    - datas[0]: 5-minute bar data (primary timeframe for trading)
    - datas[1]: Daily bar data (used for date synchronization filtering)
"""

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import os
from pathlib import Path

import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Locate data files by searching multiple directory paths.

    This function makes the test suite more robust by searching for data files
    in several common locations relative to the test directory. This allows
    tests to run correctly regardless of the current working directory.

    Search paths (in order):
        1. Current test directory
        2. Parent directory
        3. Grandparent directory
        4. tests/datas/ subdirectory
        5. BACKTRADER_DATA_DIR environment variable (if set)

    Args:
        filename: Name of the data file to locate (e.g., "2006-min-005.txt").

    Returns:
        Path object pointing to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched locations.

    Example:
        >>> path = resolve_data_path("2006-min-005.txt")
        >>> data = bt.feeds.GenericCSVData(dataname=str(path))
    """
    search_paths = [
        BASE_DIR / filename,
        BASE_DIR.parent / filename,
        BASE_DIR.parent.parent / filename,
        BASE_DIR.parent.parent / "tests" / "datas" / filename,
    ]

    # Check environment variable for additional data directory
    data_dir = os.environ.get("BACKTRADER_DATA_DIR")
    if data_dir:
        search_paths.append(Path(data_dir) / filename)

    # Return first existing path
    for candidate in search_paths:
        if candidate.exists():
            return candidate

    # File not found in any location
    raise FileNotFoundError(f"Data file not found: {filename}")


class EmaCrossStrategy(bt.Strategy):
    """EMA dual moving average crossover strategy with multi-period support.

    This strategy implements a classic dual moving average crossover system using
    Exponential Moving Averages (EMAs). It trades on crossovers between a fast
    EMA and a slow EMA, while using daily data for date synchronization filtering.

    Strategy Parameters:
        fast_period (int): Period for the fast EMA. Default is 80.
        slow_period (int): Period for the slow EMA. Default is 200.
        short_size (int): Position size for short trades. Default is 2.
        long_size (int): Position size for long trades. Default is 1.

    Trading Logic:
        Entry Signals (when no position is held):
            - Death cross: Fast EMA crosses below slow EMA -> Open short position
            - Golden cross: Fast EMA crosses above slow EMA -> Open long position

        Exit Signals (when position is held):
            - Short position exits on golden cross
            - Long position exits on death cross

    Data Feeds:
        The strategy uses multi-period data:
        - datas[0] (self.minute_data): 5-minute bar data for signal generation
        - datas[1] (self.daily_data): Daily data for date synchronization

    Attributes:
        bar_num (int): Counter for total bars processed.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.
        sum_profit (float): Cumulative profit/loss from all closed trades.
        win_count (int): Number of profitable trades.
        loss_count (int): Number of unprofitable trades.
        minute_data (bt.DataBase): Reference to 5-minute data feed.
        daily_data (bt.DataBase): Reference to daily data feed (optional).
        fast_ema (bt.indicators.EMA): Fast exponential moving average indicator.
        slow_ema (bt.indicators.EMA): Slow exponential moving average indicator.
        ema_cross (bt.indicators.CrossOver): Crossover signal indicator.
        sma_day (bt.indicators.SMA): Daily SMA (if daily data exists).

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(EmaCrossStrategy,
        ...                     fast_period=80,
        ...                     slow_period=200,
        ...                     short_size=2,
        ...                     long_size=1)
        >>> results = cerebro.run()
    """

    params = (
        ("fast_period", 80),
        ("slow_period", 200),
        ("short_size", 2),
        ("long_size", 1),
    )

    def log(self, txt, dt=None, force=False):
        """Log strategy messages with timestamp.

        Args:
            txt (str): Message text to log.
            dt (datetime, optional): DateTime for the log entry. If None,
                uses current bar's datetime.
            force (bool): If True, always log. If False, logging is disabled
                by default (must be explicitly enabled).
        """
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize strategy indicators and state variables.

        Sets up:
        1. Statistics tracking variables (bar counts, trade counts, profit/loss)
        2. Data feed references for multi-period access
        3. Technical indicators (EMAs, crossover, SMA)
        """
        # Initialize statistics tracking
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0

        # Get data references - standard access through datas list
        self.minute_data = self.datas[0]  # 5-minute data (primary)
        self.daily_data = self.datas[1] if len(self.datas) > 1 else None  # Daily data (filter)

        # Calculate EMA indicators on minute data
        self.fast_ema = bt.ind.EMA(self.minute_data, period=self.p.fast_period)
        self.slow_ema = bt.ind.EMA(self.minute_data, period=self.p.slow_period)
        self.ema_cross = bt.indicators.CrossOver(self.fast_ema, self.slow_ema)

        # If daily data exists, calculate SMA on daily data for filtering
        if self.daily_data is not None:
            self.sma_day = bt.ind.SMA(self.daily_data, period=6)

    def notify_trade(self, trade):
        """Handle trade completion events and update statistics.

        Called when a trade is closed. Updates win/loss counts and
        cumulative profit tracking.

        Args:
            trade (bt.Trade): The trade object that completed.

        Note:
            Only processes closed trades (trade.isclosed == True).
        """
        if not trade.isclosed:
            return

        # Update win/loss statistics
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1

        # Track cumulative profit
        self.sum_profit += trade.pnl
        self.log(
            f"Trade completed: Gross profit={trade.pnl:.2f}, "
            f"Net profit={trade.pnlcomm:.2f}, Cumulative={self.sum_profit:.2f}"
        )

    def notify_order(self, order):
        """Handle order status updates and log executions.

        Called when an order's status changes. Logs executed orders and
        reports any order issues (canceled, margin, rejected).

        Args:
            order (bt.Order): The order object with updated status.

        Note:
            Does not process orders in Submitted or Accepted states as they
            are still pending execution.
        """
        # Skip pending orders
        if order.status in [order.Submitted, order.Accepted]:
            return

        # Log completed orders
        if order.status == order.Completed:
            if order.isbuy():
                self.log(
                    f"Buy executed: Price={order.executed.price:.2f}, "
                    f"Size={order.executed.size}"
                )
            else:
                self.log(
                    f"Sell executed: Price={order.executed.price:.2f}, "
                    f"Size={order.executed.size}"
                )
        # Log order issues
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"Order status: {order.Status[order.status]}")

    def next(self):
        """Execute trading logic for each bar.

        Implements the core strategy logic:
        1. Track bar count
        2. Get EMA crossover signals from recent history (last 80 bars)
        3. Check date synchronization between minute and daily data
        4. Generate entry/exit signals based on crossover and date sync

        Entry Logic (no position):
            - Death cross (sum of signals = -1): Open short position
            - Golden cross (sum of signals = 1): Open long position

        Exit Logic (has position):
            - Short position closes on golden cross
            - Long position closes on death cross

        Note:
            Date synchronization ensures we only trade when both data feeds
            have data for the same date, preventing mismatches.
        """
        self.bar_num += 1

        # Get EMA crossover signal history (last 80 bars)
        # CrossOver returns 1 for golden cross, -1 for death cross, 0 otherwise
        crosslist = [i for i in self.ema_cross.get(size=80) if i == 1 or i == -1]

        # Check date synchronization (if daily data exists)
        # Only trade when both data feeds have data for the same date
        date_synced = True
        if self.daily_data is not None:
            date_synced = (
                self.minute_data.datetime.date(0) == self.daily_data.datetime.date(0)
            )

        # Opening position logic (no current position)
        if not self.position and date_synced:
            # Sum of crossover signals indicates overall trend direction
            if len(crosslist) > 0:
                signal_sum = sum(crosslist)

                # Death cross signal - open short position
                if signal_sum == -1:
                    self.sell(data=self.minute_data, size=self.p.short_size)
                    self.sell_count += 1
                # Golden cross signal - open long position
                elif signal_sum == 1:
                    self.buy(data=self.minute_data, size=self.p.long_size)
                    self.buy_count += 1

        # Closing position logic (has position)
        elif self.position and date_synced:
            signal_sum = sum(crosslist) if len(crosslist) > 0 else 0

            # When holding short position, close on golden cross
            if self.position.size < 0 and signal_sum == 1:
                self.close()
                self.buy_count += 1
            # When holding long position, close on death cross
            elif self.position.size > 0 and signal_sum == -1:
                self.close()
                self.sell_count += 1

    def stop(self):
        """Output final statistics when strategy completes.

        Called after all data has been processed. Prints summary of
        strategy performance including total bars, trade counts,
        win/loss statistics, and total profit/loss.
        """
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0

        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, "
            f"sell_count={self.sell_count}, wins={self.win_count}, "
            f"losses={self.loss_count}, win_rate={win_rate:.2f}%, "
            f"profit={self.sum_profit:.2f}",
            force=True
        )


def test_ema_cross_strategy():
    """Test EMA dual moving average crossover strategy with historical data.

    This test function:
    1. Creates a Cerebro backtest engine
    2. Loads 5-minute and daily historical data for 2006
    3. Configures the EMA crossover strategy with default parameters
    4. Runs the backtest with initial capital of $100,000
    5. Validates performance metrics against expected values

    Data:
        - Minute data: 2006-min-005.txt (5-minute bars, 2006 year)
        - Daily data: 2006-day-001.txt (daily bars, 2006 year)

    Strategy Parameters:
        - fast_period: 80
        - slow_period: 200
        - short_size: 2
        - long_size: 1

    Expected Results:
        - bar_num: 1780 (number of 5-minute bars processed)
        - final_value: ~99981.71 (ending portfolio value)
        - total_trades: 2 (number of completed trades)
        - max_drawdown: ~0.0012 (maximum drawdown as percentage)
        - annual_return: ~-7.63e-08 (annualized return rate)

    Raises:
        AssertionError: If any expected values do not match actual results
            within specified tolerance.

    Note:
        The Sharpe ratio is calculated using daily timeframe to avoid
        issues with RATEFACTORS for minute data.
    """
    # Create cerebro engine with standard statistics
    cerebro = bt.Cerebro(stdstats=True)

    # Set initial capital and commission settings
    cerebro.broker.setcash(100000.0)
    cerebro.broker.set_coc(True)  # Cheat On Close - execute at close price

    # Load 5-minute data (datas[0])
    print("Loading minute data...")
    minute_data_path = resolve_data_path("2006-min-005.txt")
    minute_data = bt.feeds.GenericCSVData(
        dataname=str(minute_data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
        dtformat="%Y-%m-%d",
        tmformat="%H:%M:%S",
        datetime=0,
        time=1,
        open=2,
        high=3,
        low=4,
        close=5,
        volume=6,
        openinterest=7,
        timeframe=bt.TimeFrame.Minutes,
        compression=5,  # 5-minute bars
    )
    cerebro.adddata(minute_data, name="minute")

    # Load daily data (datas[1])
    print("Loading daily data...")
    daily_data_path = resolve_data_path("2006-day-001.txt")
    daily_data = bt.feeds.GenericCSVData(
        dataname=str(daily_data_path),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
        dtformat="%Y-%m-%d",
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=6,
        timeframe=bt.TimeFrame.Days,
    )
    cerebro.adddata(daily_data, name="daily")

    # Add strategy with parameters
    cerebro.addstrategy(
        EmaCrossStrategy,
        fast_period=80,
        slow_period=200,
        short_size=2,
        long_size=1,
    )

    # Add performance analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    # Use daily timeframe for Sharpe ratio to avoid RATEFACTORS issues with minute data
    cerebro.addanalyzer(
        bt.analyzers.SharpeRatio,
        _name="my_sharpe",
        timeframe=bt.TimeFrame.Days,
        annualize=True,
        riskfreerate=0.0
    )
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
    max_drawdown = (
        drawdown_info["max"]["drawdown"] / 100
        if drawdown_info["max"]["drawdown"]
        else 0
    )
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    # Print results
    print("\n" + "=" * 50)
    print("EMA Dual Moving Average Crossover Strategy Backtest Results:")
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
    assert strat.bar_num == 1780, f"Expected bar_num=1780, got {strat.bar_num}"
    assert abs(final_value - 99981.71) < 0.01, f"Expected final_value=99981.71, got {final_value}"
    assert total_trades == 2, f"Expected total_trades=2, got {total_trades}"
    assert (
        abs(max_drawdown - 0.0012456157963720896) < 1e-6
    ), f"Expected max_drawdown=0.0012456157963720896, got {max_drawdown}"
    assert (
        abs(annual_return - (-7.631068888840081e-08)) < 1e-6
    ), f"Expected annual_return=-7.631068888840081e-08, got {annual_return}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("EMA Dual Moving Average Crossover Strategy Test")
    print("=" * 60)
    test_ema_cross_strategy()
