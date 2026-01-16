"""Test cases for BOLLKDJ Bollinger Bands + KDJ strategy.

This module tests a technical analysis strategy that combines Bollinger Bands and KDJ
indicators to generate trading signals for Shanghai stock data (sh600000.csv). The strategy
uses GenericCSVData to load local data files and accesses data through self.datas[0].

Strategy Overview:
    The BOLLKDJ strategy generates buy/sell signals based on:
    - Bollinger Bands crossover signals (price crossing upper/lower bands)
    - KDJ indicator golden cross (bullish) and death cross (bearish) signals
    - Combined signals for entry and exit decisions
    - Stop-loss mechanism based on price difference threshold

Reference:
    backtrader-example/strategies/bollkdj.py

Example:
    >>> test_boll_kdj_strategy()
    BOLLKDJ Bollinger Bands + KDJ Strategy Test
    Loading Shanghai stock data...
    Starting backtest...
    ...
    Test passed!
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
    """Locate data files by searching multiple potential directories.

    This function searches for data files in several common locations relative
    to the script's directory and an optional environment variable. This prevents
    failures due to relative path issues when running tests from different locations.

    Args:
        filename (str): The name of the data file to locate (e.g., 'sh600000.csv').

    Returns:
        Path: The absolute path to the first matching data file found.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the search paths.
            The error message includes the filename that was not found.

    Search Paths (in order):
        1. Current directory: BASE_DIR / filename
        2. Parent directory: BASE_DIR.parent / filename
        3. Grandparent directory: BASE_DIR.parent.parent / filename
        4. Tests data directory: BASE_DIR.parent.parent / "tests" / "datas" / filename
        5. Environment variable: Path from BACKTRADER_DATA_DIR env var / filename

    Example:
        >>> path = resolve_data_path('sh600000.csv')
        >>> print(path)
        /path/to/backtrader/tests/datas/sh600000.csv
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


class KDJ(bt.Indicator):
    """KDJ (Stochastic) technical indicator.

    The KDJ indicator is a momentum oscillator that consists of three lines:
    - K line: The fast stochastic line
    - D line: The smoothed K line (signal line)
    - J line: A derivative of K and D (J = 3*K - 2*D) that is more sensitive

    This implementation uses the StochasticFull indicator as the underlying
    calculation and extracts the K, D, and J values.

    Attributes:
        kd (bt.indicators.StochasticFull): The underlying StochasticFull indicator
            that provides the K and D values. J is calculated from K and D.

    Note:
        This implementation uses the next() method instead of line binding
        (self.l.K = self.kd.percD) because line binding has index synchronization
        issues in the current architecture after metaclass removal.

    Example:
        >>> kdj = KDJ(data, period=9, period_dfast=3, period_dslow=3)
        >>> # Access values in next():
        >>> print(f"K={kdj.K[0]}, D={kdj.D[0]}, J={kdj.J[0]}")
    """
    lines = ('K', 'D', 'J')

    params = (
        ('period', 9),
        ('period_dfast', 3),
        ('period_dslow', 3),
    )

    def __init__(self):
        """Initialize the KDJ indicator.

        Creates a StochasticFull indicator with the specified parameters.
        The K, D, and J values are calculated in the next() method rather than
        using line binding to avoid index synchronization issues.
        """
        self.kd = bt.indicators.StochasticFull(
            self.data,
            period=self.p.period,
            period_dfast=self.p.period_dfast,
            period_dslow=self.p.period_dslow,
        )

    def next(self):
        """Calculate KDJ values for the current bar.

        Updates the K, D, and J lines based on the StochasticFull indicator values.
        J is calculated as: J = 3*K - 2*D, which makes it more sensitive to
        price movements than K or D alone.

        Note:
            This method is called automatically by backtrader for each bar.
            The values are assigned directly to avoid line binding issues.
        """
        self.l.K[0] = self.kd.percD[0]
        self.l.D[0] = self.kd.percDSlow[0]
        self.l.J[0] = self.l.K[0] * 3 - self.l.D[0] * 2


class BOLLKDJStrategy(bt.Strategy):
    """Bollinger Bands + KDJ combination trading strategy.

    This strategy combines Bollinger Bands and KDJ indicators to generate
    trading signals based on trend and momentum conditions. It uses a
    dual-signal approach where both indicators must agree for entry/exit.

    Strategy Logic:
        Buy Signal:
            - Price crosses below Bollinger lower band (oversold condition)
            - KDJ golden cross at low level (K crosses above D, all lines <= 25)

        Sell Signal:
            - Price crosses above Bollinger upper band (overbought condition)
            - KDJ death cross at high level (K crosses below D, all lines >= 75)

        Exit Conditions:
            - Stop loss: Price moves against position by price_diff amount
            - Reverse signal: Opposite buy/sell signal is generated

    Attributes:
        bar_num (int): Counter for the number of bars processed.
        buy_count (int): Number of buy orders executed.
        sell_count (int): Number of sell orders executed.
        sum_profit (float): Total profit/loss from all completed trades.
        win_count (int): Number of profitable trades.
        loss_count (int): Number of unprofitable trades.
        trade_count (int): Total number of completed trades.
        data0 (bt.DataBase): Reference to the primary data feed.
        boll (bt.indicators.BollingerBands): Bollinger Bands indicator.
        kdj (KDJ): Custom KDJ indicator instance.
        marketposition (int): Current market position: 0=flat, 1=long, -1=short.
        position_price (float): Entry price of the current position.
        boll_signal (int): Bollinger Bands signal: 1=buy, -1=sell, 0=none.
        kdj_signal (int): KDJ signal: 1=buy, -1=sell, 0=none.

    Parameters:
        boll_period (int): Period for Bollinger Bands calculation. Default is 53.
        boll_mult (float): Standard deviation multiplier for Bollinger Bands. Default is 2.
        kdj_period (int): Period for KDJ calculation. Default is 9.
        kdj_ma1 (int): Fast period for KDJ D line. Default is 3.
        kdj_ma2 (int): Slow period for KDJ D line. Default is 3.
        price_diff (float): Stop loss price difference threshold. Default is 0.5.

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(BOLLKDJStrategy, boll_period=53, kdj_period=9)
        >>> cerebro.run()
    """

    params = (
        ("boll_period", 53),
        ("boll_mult", 2),
        ("kdj_period", 9),
        ("kdj_ma1", 3),
        ("kdj_ma2", 3),
        ("price_diff", 0.5),  # Stop loss price difference
    )

    def log(self, txt, dt=None, force=False):
        """Log a message with timestamp.

        This is a utility method for logging strategy events. By default,
        logging is disabled unless force=True to avoid excessive output.

        Args:
            txt (str): The message text to log.
            dt (datetime.datetime, optional): The datetime to use for the timestamp.
                If None, uses the current bar's datetime from datas[0].
            force (bool, optional): If True, force logging even when disabled.
                Default is False (no logging).

        Note:
            This method is primarily used for debugging. Most log calls
            have force=False, so they don't produce output unless explicitly enabled.
        """
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize the BOLLKDJ strategy.

        Sets up trading statistics, indicators, and signal tracking variables.
        Creates Bollinger Bands and KDJ indicators for signal generation.
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

        # Bollinger Bands indicator
        self.boll = bt.indicators.BollingerBands(
            self.data0, period=self.p.boll_period, devfactor=self.p.boll_mult
        )
        # KDJ indicator
        self.kdj = KDJ(
            self.data0, period=self.p.kdj_period,
            period_dfast=self.p.kdj_ma1, period_dslow=self.p.kdj_ma2
        )

        # Trading state
        self.marketposition = 0
        self.position_price = 0

        # Signals
        self.boll_signal = 0
        self.kdj_signal = 0

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        This method is called by backtrader when a trade is closed.
        Updates win/loss statistics and cumulative profit.

        Args:
            trade (bt.Trade): The completed trade object containing PnL information.

        Note:
            Only processes closed trades (trade.isclosed == True).
            Open trades are ignored until they are closed.
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
        """Handle order status change notifications.

        This method is called by backtrader when an order's status changes.
        Records the execution price for stop-loss calculations.

        Args:
            order (bt.Order): The order object with updated status information.

        Note:
            Only processes completed orders. The execution price is stored
            in position_price for use in stop-loss calculations.
        """
        if order.status == order.Completed:
            self.position_price = order.executed.price

    def up_across(self):
        """Check if price crosses above the upper Bollinger Band.

        Returns:
            bool: True if the previous close was below the upper band and the
                current close is above the upper band, False otherwise.

        Note:
            This indicates a breakout above the overbought level, which
            generates a potential sell signal when combined with KDJ death cross.
        """
        data = self.data0
        return data.close[-1] < self.boll.top[-1] and data.close[0] > self.boll.top[0]

    def dn_across(self):
        """Check if price crosses below the lower Bollinger Band.

        Returns:
            bool: True if the previous close was above the lower band and the
                current close is below the lower band, False otherwise.

        Note:
            This indicates a breakdown below the oversold level, which
            generates a potential buy signal when combined with KDJ golden cross.
        """
        data = self.data0
        return data.close[-1] > self.boll.bot[-1] and data.close[0] < self.boll.bot[0]

    def check_boll_signal(self):
        """Check for Bollinger Band crossover signals.

        Updates the boll_signal attribute based on price crossovers:
        - Sets boll_signal = 1 when price crosses below lower band (buy signal)
        - Sets boll_signal = -1 when price crosses above upper band (sell signal)
        - Leaves boll_signal unchanged otherwise

        Note:
            This method only sets the signal; it doesn't reset it to 0.
            Signal resetting is handled in the next() method after execution.
        """
        if self.up_across():
            self.boll_signal = -1  # Sell signal
        elif self.dn_across():
            self.boll_signal = 1   # Buy signal

    def check_kdj_signal(self):
        """Check for KDJ golden cross and death cross signals.

        Updates the kdj_signal attribute based on KDJ line crossovers:
        - Sets kdj_signal = 1 for golden cross at low level (J crosses above D, all <= 25)
        - Sets kdj_signal = -1 for death cross at high level (J crosses below D, all >= 75)
        - Leaves kdj_signal unchanged otherwise

        Note:
            Golden cross at low level indicates oversold condition with upward momentum.
            Death cross at high level indicates overbought condition with downward momentum.
        """
        condition1 = self.kdj.J[-1] - self.kdj.D[-1]
        condition2 = self.kdj.J[0] - self.kdj.D[0]
        # Golden cross at low level
        if condition1 < 0 and condition2 > 0 and (self.kdj.K[0] <= 25 and self.kdj.D[0] <= 25 and self.kdj.J[0] <= 25):
            self.kdj_signal = 1
        # Death cross at high level
        elif condition1 > 0 and condition2 < 0 and (self.kdj.K[0] >= 75 and self.kdj.D[0] >= 75 and self.kdj.J[0] >= 75):
            self.kdj_signal = -1

    def next(self):
        """Execute strategy logic for each bar.

        This method is called by backtrader for each bar in the data series.
        Implements the complete trading logic:
        1. Updates bar counter
        2. Checks for Bollinger Band and KDJ signals
        3. Executes trades based on current position and signals:
           - If flat: Enter long on buy signal, enter short on sell signal
           - If short: Exit on stop loss or buy signal
           - If long: Exit on stop loss or sell signal

        Trading Rules:
            Entry:
                - Long: Both boll_signal > 0 and kdj_signal > 0
                - Short: Both boll_signal < 0 and kdj_signal < 0
            Exit:
                - Stop loss: Price moves against position by price_diff
                - Reverse: Opposite signal combination generated

        Note:
            Position size is calculated as all available cash divided by current price.
            Signals are reset to 0 after being acted upon.
        """
        self.bar_num += 1

        # Check signals
        self.check_boll_signal()
        self.check_kdj_signal()

        data = self.data0

        # No position
        if self.marketposition == 0:
            # Buy condition
            if self.boll_signal > 0 and self.kdj_signal > 0:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.buy(data, size=size)
                    self.marketposition = 1
                    self.buy_count += 1
                self.boll_signal = 0
                self.kdj_signal = 0
            # Sell condition
            elif self.boll_signal < 0 and self.kdj_signal < 0:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.sell(data, size=size)
                    self.marketposition = -1
                    self.sell_count += 1
                self.boll_signal = 0
                self.kdj_signal = 0
        # Short position
        elif self.marketposition == -1:
            # Stop loss
            if self.position_price > 0 and (data.close[0] - self.position_price > self.p.price_diff):
                self.close()
                self.marketposition = 0
                self.position_price = 0
                self.boll_signal = 0
                self.kdj_signal = 0
                self.buy_count += 1
            # Close on reverse signal
            elif self.boll_signal > 0 and self.kdj_signal > 0:
                self.close()
                self.marketposition = 0
                self.position_price = 0
                self.boll_signal = 0
                self.kdj_signal = 0
                self.buy_count += 1
        # Long position
        elif self.marketposition == 1:
            # Stop loss
            if self.position_price - data.close[0] > self.p.price_diff:
                self.close()
                self.marketposition = 0
                self.position_price = 0
                self.boll_signal = 0
                self.kdj_signal = 0
                self.sell_count += 1
            # Close on reverse signal
            elif self.boll_signal < 0 and self.kdj_signal < 0:
                self.close()
                self.marketposition = 0
                self.position_price = 0
                self.boll_signal = 0
                self.kdj_signal = 0
                self.sell_count += 1

    def stop(self):
        """Output performance statistics when the strategy completes.

        This method is called by backtrader at the end of the backtest.
        Logs comprehensive statistics including trade counts, win rate,
        and total profit.

        Statistics Logged:
            - bar_num: Total number of bars processed
            - buy_count: Number of buy orders executed
            - sell_count: Number of sell orders executed
            - wins: Number of profitable trades
            - losses: Number of unprofitable trades
            - win_rate: Percentage of winning trades (0-100)
            - profit: Total profit/loss from all trades

        Note:
            Win rate is calculated as (win_count / (win_count + loss_count)) * 100.
            If no trades were made, win_rate is 0.
        """
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_boll_kdj_strategy():
    """Run a backtest of the BOLLKDJ strategy and verify results.

    This test function:
    1. Creates a Cerebro engine with initial capital of 100,000
    2. Loads Shanghai stock data (sh600000.csv) from 2000-2022
    3. Adds the BOLLKDJ strategy with default parameters
    4. Runs the backtest with analyzers for performance metrics
    5. Asserts that results match expected values

    Expected Results:
        - bar_num: 5363 bars processed
        - buy_count: 82 buy orders executed
        - sell_count: 81 sell orders executed
        - total_trades: 66 completed trades
        - final_value: 75609.19 (ending portfolio value)
        - sharpe_ratio: -0.08347216120029895 (risk-adjusted return)
        - annual_return: -0.012927216297173407 (-1.29% annual return)
        - max_drawdown: 0.6605349686435283 (66.05% maximum drawdown)

    Raises:
        AssertionError: If any of the expected values don't match actual results.
            Each assertion includes a descriptive message showing expected vs actual.

    Side Effects:
        - Prints test progress and results to stdout
        - Prints backtest statistics in a formatted table

    Example:
        >>> test_boll_kdj_strategy()
        Loading Shanghai stock data...
        Starting backtest...
        ==================================================
        BOLLKDJ Bollinger Bands + KDJ Strategy Backtest Results:
          bar_num: 5363
          buy_count: 82
          ...
        Test passed!
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

    cerebro.addstrategy(BOLLKDJStrategy, boll_period=53, kdj_period=9, price_diff=0.5)

    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade_analyzer")

    print("Starting backtest...")
    results = cerebro.run()

    strat = results[0]
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get("sharperatio")
    annual_return = strat.analyzers.my_returns.get_analysis().get("rnorm")
    drawdown_info = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown_info["max"]["drawdown"] / 100 if drawdown_info["max"]["drawdown"] else 0
    trade_analysis = strat.analyzers.my_trade_analyzer.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("total", 0)
    final_value = cerebro.broker.getvalue()

    print("\n" + "=" * 50)
    print("BOLLKDJ Bollinger Bands + KDJ Strategy Backtest Results:")
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

    assert strat.bar_num == 5363, f"Expected bar_num=5363, got {strat.bar_num}"
    assert strat.buy_count == 82, f"Expected buy_count=82, got {strat.buy_count}"
    assert strat.sell_count == 81, f"Expected sell_count=81, got {strat.sell_count}"
    assert total_trades == 66, f"Expected total_trades=66, got {total_trades}"
    assert abs(final_value - 75609.19) < 0.01, f"Expected final_value=75609.19, got {final_value}"
    assert abs(sharpe_ratio - (-0.08347216120029895)) < 1e-6, f"Expected sharpe_ratio=-0.08347216120029895, got {sharpe_ratio}"
    assert abs(annual_return - (-0.012927216297173407)) < 1e-6, f"Expected annual_return=-0.012927216297173407, got {annual_return}"
    assert abs(max_drawdown - 0.6605349686435283) < 1e-6, f"Expected max_drawdown=0.6605349686435283, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("BOLLKDJ Bollinger Bands + KDJ Strategy Test")
    print("=" * 60)
    test_boll_kdj_strategy()
