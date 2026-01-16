"""Bollinger Band Strategy Test Case.

This module tests a trend-following Bollinger Band strategy that trades
breakouts from the Bollinger Bands. The strategy goes long when price
breaks above the upper band and goes short when price breaks below the
lower band.

Data Source:
    - Shanghai Stock Exchange data sh600000.csv

Strategy Logic:
    - Open long when closing price exceeds upper band for 2 consecutive bars
    - Open short when closing price falls below lower band for 2 consecutive bars
    - Close position when price crosses the middle band (moving average)
    - Includes stop-loss protection at price_diff threshold

Reference:
    backtrader-example/strategies/boll.py

Example:
    >>> python tests/strategies/test_26_boll_strategy.py
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
    """Locate data files based on the script directory to avoid relative path failures.

    This function searches for data files in multiple potential locations,
    making the test suite more robust to different execution contexts.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any search path.
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


class BollStrategy(bt.Strategy):
    """Bollinger Band trend-following strategy.

    This strategy implements a breakout trading system using Bollinger Bands.
    It trades in the direction of the breakout when price moves outside the
    bands for two consecutive bars, and exits when price returns to the
    middle band (moving average).

    Strategy Rules:
        1. Entry signals:
           - Long: Close > top band for 2 consecutive bars
           - Short: Close < bottom band for 2 consecutive bars
        2. Exit signals:
           - Long: Close crosses below middle band
           - Short: Close crosses above middle band
        3. Risk management:
           - Stop loss at price_diff from entry price

    Attributes:
        params: Strategy parameters including:
            - period_boll (int): Bollinger Band period (default: 245).
            - price_diff (float): Stop loss price difference (default: 0.5).
        bar_num: Counter for total bars processed.
        buy_count: Counter for buy orders executed.
        sell_count: Counter for sell orders executed.
        sum_profit: Total profit/loss from all closed trades.
        win_count: Number of profitable trades.
        loss_count: Number of unprofitable trades.
        trade_count: Total number of completed trades.
        data0: Reference to the first data feed.
        boll: Bollinger Bands indicator.
        marketposition: Current position state (0=flat, 1=long, -1=short).
        position_price: Entry price of current position.

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(BollStrategy, period_boll=245, price_diff=0.5)
        >>> cerebro.run()
    """

    params = (
        ("period_boll", 245),
        ("price_diff", 0.5),  # Stop loss price difference
    )

    def log(self, txt, dt=None, force=False):
        """Log strategy information with timestamp.

        Args:
            txt: Text message to log.
            dt: Optional datetime for the log entry. Uses current bar if None.
            force: If False, logging is skipped. Used to control output verbosity.
        """
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize the Bollinger Band strategy.

        Sets up tracking counters, data references, and the Bollinger Bands
        indicator. The indicator provides top (upper band), mid (middle band/SMA),
        and bot (lower band) lines for trading signals.
        """
        # Record statistical data
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0
        self.trade_count = 0

        # Get data reference
        self.data0 = self.datas[0]

        # Bollinger Band indicator
        self.boll = bt.indicators.BollingerBands(self.data0, period=self.p.period_boll)

        # Trading status
        self.marketposition = 0  # 0=flat, 1=long, -1=short
        self.position_price = 0

    def notify_trade(self, trade):
        """Handle trade completion and update statistics.

        This callback is invoked when a trade closes. It updates win/loss
        counters and accumulates total profit/loss.

        Args:
            trade: The Trade object that has closed.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl

    def notify_order(self, order):
        """Handle order status changes and track entry price.

        This callback is invoked when an order status changes. It tracks
        the execution price for stop-loss calculations.

        Args:
            order: The Order object whose status has changed.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            # Track execution price for stop-loss calculations
            self.position_price = order.executed.price

    def close_gt_up(self):
        """Check if closing price is continuously above upper band.

        Verifies that the current and previous bars both closed above
        the upper Bollinger Band, indicating a strong breakout.

        Returns:
            bool: True if close[0] > top and close[-1] > top[-1].
        """
        data = self.data0
        return data.close[0] > self.boll.top[0] and data.close[-1] > self.boll.top[-1]

    def close_lt_dn(self):
        """Check if closing price is continuously below lower band.

        Verifies that the current and previous bars both closed below
        the lower Bollinger Band, indicating a strong breakdown.

        Returns:
            bool: True if close[0] < bot and close[-1] < bot[-1].
        """
        data = self.data0
        return data.close[0] < self.boll.bot[0] and data.close[-1] < self.boll.bot[-1]

    def down_across_mid(self):
        """Check if price is crossing middle band downward.

        Detects when price crosses from above the middle band to below it,
        signaling a potential exit for long positions.

        Returns:
            bool: True if close[-1] > mid[-1] and close[0] < mid[0].
        """
        data = self.data0
        return data.close[-1] > self.boll.mid[-1] and data.close[0] < self.boll.mid[0]

    def up_across_mid(self):
        """Check if price is crossing middle band upward.

        Detects when price crosses from below the middle band to above it,
        signaling a potential exit for short positions.

        Returns:
            bool: True if close[-1] < mid[-1] and close[0] > mid[0].
        """
        data = self.data0
        return data.close[-1] < self.boll.mid[-1] and data.close[0] > self.boll.mid[0]

    def next(self):
        """Execute the core Bollinger Band strategy logic.

        This method implements the complete trading logic:

        1. Entry conditions (when marketposition == 0):
           - Long entry: close_gt_up() (price breaks above upper band)
           - Short entry: close_lt_dn() (price breaks below lower band)

        2. Exit conditions for long positions (marketposition > 0):
           - Stop loss: position_price - close > price_diff
           - Normal exit: down_across_mid() (price crosses below middle band)

        3. Exit conditions for short positions (marketposition < 0):
           - Stop loss: close - position_price > price_diff
           - Normal exit: up_across_mid() (price crosses above middle band)

        Position sizing:
           - Uses all available cash for new positions
           - size = int(cash / close_price)
        """
        self.bar_num += 1
        data = self.data0

        # Open position logic - no current position
        if self.marketposition == 0:
            if self.close_gt_up():
                # Breakout above upper band - open long position
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.buy(data, size=size)
                    self.marketposition = 1
                    self.buy_count += 1
            elif self.close_lt_dn():
                # Breakdown below lower band - open short position
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.sell(data, size=size)
                    self.marketposition = -1
                    self.sell_count += 1

        # Long position management
        elif self.marketposition > 0:
            # Check stop loss - close below entry by price_diff
            if self.position_price - data.close[0] > self.p.price_diff:
                self.close()
                self.marketposition = 0
                self.sell_count += 1
            # Check normal exit - price crosses below middle band
            elif self.down_across_mid():
                self.close()
                self.marketposition = 0
                self.sell_count += 1

        # Short position management
        elif self.marketposition < 0:
            # Check stop loss - close above entry by price_diff
            if data.close[0] - self.position_price > self.p.price_diff:
                self.close()
                self.marketposition = 0
                self.buy_count += 1
            # Check normal exit - price crosses above middle band
            elif self.up_across_mid():
                self.close()
                self.marketposition = 0
                self.buy_count += 1

    def stop(self):
        """Log final statistics when the backtest completes.

        Outputs summary statistics including total bars, order counts,
        win/loss ratio, and total profit/loss.
        """
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_boll_strategy():
    """Test Bollinger Band strategy with historical data.

    This end-to-end test loads Shanghai stock data, runs the BollStrategy
    backtest, and validates the results against expected performance metrics.

    Test Configuration:
        - Initial Capital: 100,000
        - Data: sh600000.csv from 2000-01-01 to 2022-12-31
        - Bollinger Period: 245 days
        - Stop Loss: 0.5 price units

    Expected Results:
        - bar_num: 5171 (total bars processed)
        - buy_count: 23 (buy orders executed)
        - sell_count: 24 (sell orders executed)
        - win_count: 6 (profitable trades)
        - loss_count: 13 (unprofitable trades)
        - total_trades: 20 (completed round-trips)
        - final_value: 325,630.39 (±0.01 tolerance)
        - sharpe_ratio: 0.235 (±1e-6 tolerance)
        - annual_return: 0.056 (±1e-6 tolerance)
        - max_drawdown: 0.457 (±1e-6 tolerance)

    Raises:
        AssertionError: If any performance metrics don't match expected values.
        FileNotFoundError: If required data file is missing.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading Shanghai Stock Exchange data...")
    data_path = resolve_data_path("sh600000.csv")
    df = pd.read_csv(data_path)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime')
    df = df.set_index('datetime')
    df = df[(df.index >= '2000-01-01') & (df.index <= '2022-12-31')]
    df = df[df['close'] > 0]

    df = df[['open', 'high', 'low', 'close', 'volume']]

    data_feed = bt.feeds.PandasData(
        dataname=df,
        datetime=None,
        open=0,
        high=1,
        low=2,
        close=3,
        volume=4,
        openinterest=-1,
    )
    cerebro.adddata(data_feed, name="SH600000")

    cerebro.addstrategy(BollStrategy, period_boll=245, price_diff=0.5)

    # Add performance analyzers
    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

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

    # Print results
    print("\n" + "=" * 50)
    print("Bollinger Band Strategy Backtest Results:")
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

    # Assert exact values match expected
    assert strat.bar_num == 5171, f"Expected bar_num=5171, got {strat.bar_num}"
    assert strat.buy_count == 23, f"Expected buy_count=23, got {strat.buy_count}"
    assert strat.sell_count == 24, f"Expected sell_count=24, got {strat.sell_count}"
    assert strat.win_count == 6, f"Expected win_count=6, got {strat.win_count}"
    assert strat.loss_count == 13, f"Expected loss_count=13, got {strat.loss_count}"
    assert total_trades == 20, f"Expected total_trades=20, got {total_trades}"
    assert abs(final_value - 325630.39) < 0.01, f"Expected final_value=325630.39, got {final_value}"
    assert abs(sharpe_ratio - 0.23478555305294077) < 1e-6, f"Expected sharpe_ratio=0.23478555305294077, got {sharpe_ratio}"
    assert abs(annual_return - (0.05647903475651481)) < 1e-6, f"Expected annual_return=0.05647903475651481, got {annual_return}"
    assert abs(max_drawdown - 0.45736836540827375) < 1e-6, f"Expected max_drawdown=0.45736836540827375, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Bollinger Band Strategy Test")
    print("=" * 60)
    test_boll_strategy()
