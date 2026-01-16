"""Test cases for BollReverser Bollinger Band reversal strategy.

This module tests a mean-reversion Bollinger Band strategy that trades
against breakouts. The strategy goes short when price breaks above the
upper band (betting on reversal from overbought) and goes long when price
breaks below the lower band (betting on reversal from oversold).

Data Source:
    - Shanghai stock data sh600000.csv

Strategy Logic:
    - Open short when price continuously exceeds upper band (overbought reversal)
    - Open long when price continuously falls below lower band (oversold reversal)
    - Close long position when price crosses above upper band
    - Close short position when price crosses below lower band

This is the opposite approach to the trend-following Boll strategy.

Reference:
    backtrader-example/strategies/boll_reverser.py

Example:
    >>> python tests/strategies/test_27_boll_reverser_strategy.py
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
    """Locate data file based on script directory to avoid relative path failures.

    This function searches for data files in multiple potential locations,
    making the test suite more robust to different execution contexts.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path: Absolute path to the data file.

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


class BollReverserStrategy(bt.Strategy):
    """BollReverser Bollinger Band reversal (mean-reversion) strategy.

    This strategy implements a mean-reversion trading system using Bollinger Bands.
    It trades against breakouts, betting that prices will reverse back toward
    the mean after becoming overbought or oversold.

    Strategy Rules (Reversal Approach):
        1. Entry signals:
           - Short: Close > top band for 2 consecutive bars (overbought)
           - Long: Close < bottom band for 2 consecutive bars (oversold)
        2. Exit signals:
           - Long exit: Close crosses above upper band (resistance)
           - Short exit: Close crosses below lower band (support)

    This is the opposite of the trend-following Boll strategy. Instead of
    trading with breakouts, it fades them and expects mean reversion.

    Attributes:
        params: Strategy parameters including:
            - period_boll (int): Bollinger Band period (default: 52).
        bar_num: Counter for total bars processed.
        buy_count: Counter for buy orders executed.
        sell_count: Counter for sell orders executed.
        sum_profit: Total profit/loss from all closed trades.
        win_count: Number of profitable trades.
        loss_count: Number of unprofitable trades.
        trade_count: Total number of completed trades.
        data0: Reference to the first data feed.
        boll: Bollinger Bands indicator with top, mid, and bot lines.

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(BollReverserStrategy, period_boll=52)
        >>> cerebro.run()
    """

    params = (
        ("period_boll", 52),
    )

    def log(self, txt, dt=None, force=False):
        """Log output function with timestamp.

        Args:
            txt: Text content to log.
            dt: Datetime for the log entry. Defaults to current data datetime.
            force: Whether to force output. If False, logging is skipped.
        """
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize the BollReverser strategy.

        Sets up tracking counters, data references, and the Bollinger Bands
        indicator for generating reversal signals.
        """
        # Record statistics
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

    def notify_trade(self, trade):
        """Handle trade completion notification.

        Updates win/loss counters and accumulates total profit/loss when
        a trade closes.

        Args:
            trade: Trade object containing trade information.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl

    def close_gt_up(self):
        """Check if closing price is continuously above upper band.

        Detects overbought condition where price has broken above the upper
        Bollinger Band for two consecutive bars, signaling a potential
        short entry (mean-reversion).

        Returns:
            bool: True if current and previous close are above upper band.
        """
        data = self.data0
        return data.close[0] > self.boll.top[0] and data.close[-1] > self.boll.top[-1]

    def close_lt_dn(self):
        """Check if closing price is continuously below lower band.

        Detects oversold condition where price has broken below the lower
        Bollinger Band for two consecutive bars, signaling a potential
        long entry (mean-reversion).

        Returns:
            bool: True if current and previous close are below lower band.
        """
        data = self.data0
        return data.close[0] < self.boll.bot[0] and data.close[-1] < self.boll.bot[-1]

    def close_across_top(self):
        """Check if price crosses above upper band.

        Detects when price crosses from below the upper band to above it.
        This signals an exit for long positions as price hits resistance
        at the upper band.

        Returns:
            bool: True if previous close was below and current close is above upper band.
        """
        data = self.data0
        return data.close[-1] < self.boll.top[-1] and data.close[0] > self.boll.top[0]

    def close_across_bot(self):
        """Check if price crosses below lower band.

        Detects when price crosses from above the lower band to below it.
        This signals an exit for short positions as price hits support
        at the lower band.

        Returns:
            bool: True if previous close was above and current close is below lower band.
        """
        data = self.data0
        return data.close[-1] > self.boll.bot[-1] and data.close[0] < self.boll.bot[0]

    def next(self):
        """Execute the core BollReverser strategy logic.

        This method implements the mean-reversion trading logic:

        1. Entry conditions (position.size == 0):
           - Short entry: close_gt_up() (overbought, expect reversal down)
           - Long entry: close_lt_dn() (oversold, expect reversal up)

        2. Exit conditions:
           - Long exit (position.size > 0): close_across_top() (price hits upper band)
           - Short exit (position.size < 0): close_across_bot() (price hits lower band)

        Position sizing:
           - Uses all available cash for new positions
           - size = int(cash / close_price)
        """
        self.bar_num += 1
        position = self.getposition()

        if position.size == 0:
            # No current position - look for entry opportunities
            if self.close_gt_up():
                # Overbought - open short position expecting reversal down
                size = int(self.broker.getcash() / self.data0.close[0])
                if size > 0:
                    self.sell(size=size)
                    self.sell_count += 1
            elif self.close_lt_dn():
                # Oversold - open long position expecting reversal up
                size = int(self.broker.getcash() / self.data0.close[0])
                if size > 0:
                    self.buy(size=size)
                    self.buy_count += 1
        elif position.size > 0:
            # Long position active - check exit condition
            if self.close_across_top():
                # Price crossed above upper band - close long position
                self.close()
                self.sell_count += 1
        elif position.size < 0:
            # Short position active - check exit condition
            if self.close_across_bot():
                # Price crossed below lower band - close short position
                self.close()
                self.buy_count += 1

    def stop(self):
        """Output statistics when strategy ends.

        Calculates and logs final statistics including total bars,
        order counts, win/loss ratio, and total profit/loss.
        """
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_boll_reverser_strategy():
    """Test the BollReverser Bollinger Band reversal strategy.

    This end-to-end test loads Shanghai stock data, runs the BollReverserStrategy
    backtest, and validates the results against expected performance metrics.

    Test Configuration:
        - Initial Capital: 100,000
        - Data: sh600000.csv from 2000-01-01 to 2022-12-31
        - Bollinger Period: 52 days (shorter than trend-following version)

    Expected Results:
        - bar_num: 5364 (total bars processed)
        - buy_count: 87 (buy orders executed)
        - sell_count: 47 (sell orders executed)
        - win_count: 28 (profitable trades)
        - loss_count: 19 (unprofitable trades)
        - total_trades: 48 (completed round-trips)
        - final_value: 19,875.22 (±0.01 tolerance)
        - sharpe_ratio: -0.072 (±1e-6 tolerance, negative as expected for losing strategy)
        - annual_return: -0.072 (±1e-6 tolerance)
        - max_drawdown: 3.98 (±1e-6 tolerance)

    Note:
        The negative returns demonstrate that mean-reversion on this particular
        stock with these parameters was not profitable. This is expected behavior
        for a reversal strategy in a trending market.

    Raises:
        AssertionError: If any performance metrics don't match expected values.
        FileNotFoundError: If required data file is missing.
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading Shanghai stock data...")
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

    cerebro.addstrategy(BollReverserStrategy, period_boll=52)

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
    print("BollReverser Bollinger Band reversal strategy backtest results:")
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
    assert strat.bar_num == 5364
    assert strat.buy_count == 87, f"Expected buy_count=87, got {strat.buy_count}"
    assert strat.sell_count == 47, f"Expected sell_count=47, got {strat.sell_count}"
    assert strat.win_count == 28, f"Expected win_count=28, got {strat.win_count}"
    assert strat.loss_count == 19, f"Expected loss_count=19, got {strat.loss_count}"
    assert total_trades == 48, f"Expected total_trades=48, got {total_trades}"
    assert abs(final_value - 19875.22) < 0.01, f"Expected final_value=19875.22, got {final_value}"
    assert abs(sharpe_ratio-0.21162837519058628)<1e-6, f"sharpe_ratio={sharpe_ratio} out of range"
    assert abs(annual_return - (-0.07243305202540544)) < 1e-6, f"Expected annual_return=-0.07243305202540544, got {annual_return}"
    assert abs(max_drawdown - 3.9763680700930992) < 1e-6, f"Expected max_drawdown=0.8679098802262411, got {max_drawdown}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("BollReverser Bollinger Band reversal strategy test")
    print("=" * 60)
    test_boll_reverser_strategy()
