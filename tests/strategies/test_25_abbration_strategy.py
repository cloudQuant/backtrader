"""Test module for the Abbration Bollinger Band breakout strategy.

This module contains a test suite for the Bollinger Band breakout strategy,
which trades on price breakouts from Bollinger Bands. The strategy is tested
using historical Shanghai stock data (sh600000.csv) from 2000-2022.

The test module includes:
- AbbrationStrategy: A strategy class implementing Bollinger Band breakout logic
- test_abbration_strategy(): A test function that runs a full backtest

Strategy Overview:
    - Opens long positions when price breaks above the upper Bollinger Band
    - Opens short positions when price breaks below the lower Bollinger Band
    - Closes positions when price returns to the middle Bollinger Band

Reference:
    backtrader-example/strategies/abbration.py
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
    """Locate a data file by searching multiple possible directory paths.

    This function searches for data files in several predefined locations
    to avoid relative path issues when running tests from different working
    directories. It supports an environment variable for custom data directory
    configuration.

    Args:
        filename: Name of the data file to locate (e.g., 'sh600000.csv').

    Returns:
        Path object pointing to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search paths.

    Search Paths:
        1. Current test directory (tests/strategies/)
        2. Parent directory (tests/)
        3. Grandparent directory (project root)
        4. tests/datas/ directory
        5. Custom directory from BACKTRADER_DATA_DIR environment variable
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


class AbbrationStrategy(bt.Strategy):
    """Bollinger Band breakout trading strategy.

    This strategy implements a mean-reversion trading approach using Bollinger Bands.
    It enters positions when price breaks out of the bands and exits when price
    returns to the mean (middle band).

    Trading Logic:
        - Long Entry: Price breaks above upper Bollinger Band (crosses from below)
        - Short Entry: Price breaks below lower Bollinger Band (crosses from above)
        - Exit: Price crosses back through the middle Bollinger Band

    Attributes:
        bar_num (int): Total number of bars processed during backtest.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.
        sum_profit (float): Cumulative profit/loss from all completed trades.
        win_count (int): Number of profitable trades.
        loss_count (int): Number of unprofitable trades.
        data0 (object): Reference to the primary data feed (self.datas[0]).
        boll_indicator (bt.indicators.BollingerBands): Bollinger Bands indicator.
        marketposition (int): Current market position (0=flat, 1=long, -1=short).

    Parameters:
        boll_period (int): Period for Bollinger Band calculation. Default is 200.
        boll_mult (float): Standard deviation multiplier for bands. Default is 2.0.
    """

    params = (
        ("boll_period", 200),
        ("boll_mult", 2),
    )

    def log(self, txt, dt=None, force=False):
        """Log messages with optional timestamp.

        Args:
            txt: Text message to log.
            dt: Optional datetime for the log entry. If None, uses current bar's datetime.
            force: If True, always log. If False, suppress logging (default).
        """
        if not force:
            return
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize the strategy with indicators and tracking variables.

        Sets up:
            - Statistical tracking variables (bar count, trade counts, P&L)
            - Data feed references
            - Bollinger Band indicator
            - Market position state
        """
        # Record statistical data
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.sum_profit = 0.0
        self.win_count = 0
        self.loss_count = 0

        # Get data reference - standard access through datas list
        self.data0 = self.datas[0]

        # Calculate Bollinger Band indicator
        self.boll_indicator = bt.indicators.BollingerBands(
            self.data0, period=self.p.boll_period, devfactor=self.p.boll_mult
        )

        # Save trading state
        self.marketposition = 0

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        Called by backtrader when a trade is closed. Updates win/loss statistics
        and cumulative profit tracking.

        Args:
            trade: Trade object containing information about the completed trade.
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

        Called by backtrader when order status changes. Logs executed orders
        and order status changes (canceled, margin, rejected).

        Args:
            order: Order object containing status and execution information.
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

        Implements the core strategy logic:
            1. Increment bar counter
            2. Check for long entry: price breaks above upper band from below
            3. Check for short entry: price breaks below lower band from above
            4. Check for long exit: price crosses below middle band from above
            5. Check for short exit: price crosses above middle band from below

        Entry conditions require a breakout (previous bar outside, current bar outside)
        to avoid entering on false breakouts.
        """
        self.bar_num += 1

        data = self.data0
        top = self.boll_indicator.top
        bot = self.boll_indicator.bot
        mid = self.boll_indicator.mid

        # Open long: Price breaks above upper band from below
        if self.marketposition == 0 and data.close[0] > top[0] and data.close[-1] < top[-1]:
            size = int(self.broker.getcash() / data.close[0])
            if size > 0:
                self.buy(data, size=size)
                self.marketposition = 1
                self.buy_count += 1

        # Open short: Price breaks below lower band from above
        if self.marketposition == 0 and data.close[0] < bot[0] and data.close[-1] > bot[-1]:
            size = int(self.broker.getcash() / data.close[0])
            if size > 0:
                self.sell(data, size=size)
                self.marketposition = -1
                self.sell_count += 1

        # Close long: Price crosses below middle band from above
        if self.marketposition == 1 and data.close[0] < mid[0] and data.close[-1] > mid[-1]:
            self.close()
            self.marketposition = 0
            self.sell_count += 1

        # Close short: Price crosses above middle band from below
        if self.marketposition == -1 and data.close[0] > mid[0] and data.close[-1] < mid[-1]:
            self.close()
            self.marketposition = 0
            self.buy_count += 1

    def stop(self):
        """Output final statistics when backtest completes.

        Called by backtrader after all bars have been processed.
        Calculates and logs:
            - Total bars processed
            - Buy/sell order counts
            - Win/loss trade counts
            - Win rate percentage
            - Total profit/loss
        """
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_abbration_strategy():
    """Test the Abbration Bollinger Band breakout strategy.

    This test function performs a complete backtest of the AbbrationStrategy
    using historical Shanghai stock data (SH600000) from 2000-2022. It validates
    strategy performance against expected metrics.

    Test Setup:
        - Initial capital: 100,000
        - Data: Shanghai stock sh600000.csv (2000-2022)
        - Bollinger Period: 200
        - Bollinger Multiplier: 2.0

    Expected Results (Assertions):
        - bar_num: 5216
        - buy_count: 19
        - sell_count: 20
        - win_count: 9
        - loss_count: 6
        - total_trades: 16
        - final_value: 423,916.71
        - sharpe_ratio: 0.2701748176643007
        - annual_return: 0.06952761581010602
        - max_drawdown: 0.46515816375898594

    Raises:
        AssertionError: If any of the expected values do not match within tolerance.
        FileNotFoundError: If the data file cannot be located.
    """
    # Create cerebro
    cerebro = bt.Cerebro(stdstats=True)

    # Set initial capital
    cerebro.broker.setcash(100000.0)

    # Load data (datas[0])
    print("Loading Shanghai stock data...")
    data_path = resolve_data_path("sh600000.csv")
    df = pd.read_csv(data_path)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.sort_values('datetime')  # Sort in chronological order
    df = df.set_index('datetime')
    df = df[(df.index >= '2000-01-01') & (df.index <= '2022-12-31')]
    df = df[df['close'] > 0]  # Filter invalid data

    # Reorder columns to match PandandasData default format
    df = df[['open', 'high', 'low', 'close', 'volume']]

    data_feed = bt.feeds.PandasData(
        dataname=df,
        datetime=None,  # Use index as date
        open=0,
        high=1,
        low=2,
        close=3,
        volume=4,
        openinterest=-1,
    )
    cerebro.adddata(data_feed, name="SH600000")

    # Add strategy
    cerebro.addstrategy(
        AbbrationStrategy,
        boll_period=200,
        boll_mult=2,
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
    print("Abbration Bollinger Band breakout strategy backtest results:")
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
    assert strat.bar_num == 5216, f"Expected bar_num=5216, got {strat.bar_num}"
    assert strat.buy_count == 19, f"Expected buy_count=19, got {strat.buy_count}"
    assert strat.sell_count == 20, f"Expected sell_count=20, got {strat.sell_count}"
    assert strat.win_count == 9, f"Expected win_count=9, got {strat.win_count}"
    assert strat.loss_count == 6, f"Expected loss_count=6, got {strat.loss_count}"
    assert total_trades == 16, f"Expected total_trades=16, got {total_trades}"
    assert abs(final_value - 423916.71) < 0.01, f"Expected final_value=423916.71, got {final_value}"
    assert abs(sharpe_ratio - 0.2701748176643007) < 1e-6, f"Expected sharpe_ratio=0.2701748176643007, got {sharpe_ratio}"
    assert abs(annual_return - (0.06952761581010602)) < 1e-6, f"Expected annual_return=0.06952761581010602, got {annual_return}"
    assert abs(max_drawdown - 0.46515816375898594) < 1e-6, f"Expected max_drawdown=0.46515816375898594, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Abbration Bollinger Band breakout strategy test")
    print("=" * 60)
    test_abbration_strategy()
