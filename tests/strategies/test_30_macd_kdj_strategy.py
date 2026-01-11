"""Test cases for MACD+KDJ combined strategy.

This module tests the MACD+KDJ combined strategy using Shanghai Stock Exchange
data (sh600000.csv).

Features:
    - Loads local data files using GenericCSVData
    - Accesses data via self.datas[0] convention

Reference:
    backtrader-example/strategies/macdkdj.py
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

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the found data file.

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


class KDJ(bt.Indicator):
    """KDJ (Stochastic) Technical Indicator.

    The KDJ indicator is a momentum oscillator that compares a specific closing
    price of a security to a range of its prices over a certain period of time.
    It consists of three lines: K, D, and J, where K and D are similar to the
    Stochastic oscillator, and J is a derivative line.

    The indicator is calculated using the StochasticFull indicator as the base,
    with J calculated as: J = 3*K - 2*D.

    Refactoring Note:
        Uses the next() method instead of line binding (self.l.K = self.kd.percD)
        because line binding has idx synchronization issues in the current
        architecture.

    Attributes:
        lines: Tuple containing ('K', 'D', 'J') - the three output lines.
        params: Tuple containing configuration parameters:
            - period (int): Lookback period for Stochastic calculation (default: 9).
            - period_dfast (int): Fast %D smoothing period (default: 3).
            - period_dslow (int): Slow %D smoothing period (default: 3).
        kd (StochasticFull): Internal StochasticFull indicator instance.
    """

    lines = ('K', 'D', 'J')

    params = (
        ('period', 9),
        ('period_dfast', 3),
        ('period_dslow', 3),
    )

    def __init__(self):
        """Initialize the KDJ indicator with a StochasticFull base.

        Creates a StochasticFull indicator with the configured parameters
        to serve as the foundation for K, D, and J line calculations.
        """
        self.kd = bt.indicators.StochasticFull(
            self.data,
            period=self.p.period,
            period_dfast=self.p.period_dfast,
            period_dslow=self.p.period_dslow,
        )

    def next(self):
        """Calculate KDJ values for the current bar.

        Updates the K, D, and J lines based on the underlying StochasticFull
        indicator values. The J line is derived from K and D using the
        formula: J = 3*K - 2*D.
        """
        self.l.K[0] = self.kd.percD[0]
        self.l.D[0] = self.kd.percDSlow[0]
        self.l.J[0] = self.l.K[0] * 3 - self.l.D[0] * 2


class MACDKDJStrategy(bt.Strategy):
    """Combined MACD and KDJ trading strategy.

    This strategy uses MACD (Moving Average Convergence Divergence) for trend
    following and KDJ (Stochastic) for entry/exit timing signals.

    Strategy Logic:
        * MACD golden cross (MACD line crosses above signal line) -> Buy signal
        * KDJ death cross (K line crosses below D line) -> Sell signal
        * MACD golden cross closes existing short positions
        * KDJ death cross closes existing long positions

    Entry Rules:
        * When flat (no position):
            - Enter long on MACD golden cross
            - Enter short on KDJ death cross

    Exit Rules:
        * When long: Exit on KDJ death cross
        * When short: Exit on MACD golden cross

    Data Usage:
        * datas[0]: Stock price data (OHLCV)

    Attributes:
        params: Tuple containing strategy parameters:
            - macd_fast_period (int): MACD fast EMA period (default: 12).
            - macd_slow_period (int): MACD slow EMA period (default: 26).
            - macd_signal_period (int): MACD signal line period (default: 9).
            - kdj_fast_period (int): KDJ Stochastic period (default: 9).
            - kdj_slow_period (int): KDJ smoothing period (default: 3).
        bar_num (int): Counter for number of bars processed.
        buy_count (int): Number of buy orders executed.
        sell_count (int): Number of sell orders executed.
        sum_profit (float): Total profit/loss from all closed trades.
        win_count (int): Number of profitable trades.
        loss_count (int): Number of unprofitable trades.
        trade_count (int): Total number of completed trades.
        data0 (Data feed): Reference to the primary data feed.
        macd (MACD): MACD indicator instance.
        kdj (KDJ): KDJ indicator instance.
        marketposition (int): Current market position (-1=short, 0=flat, 1=long).
    """

    params = (
        ('macd_fast_period', 12),
        ('macd_slow_period', 26),
        ('macd_signal_period', 9),
        ('kdj_fast_period', 9),
        ('kdj_slow_period', 3),
    )

    def log(self, txt, dt=None, force=False):
        """Logging utility for strategy output.

        Args:
            txt (str): Text message to log.
            dt (datetime, optional): Datetime object for the log entry.
                Defaults to current bar's datetime.
            force (bool): If True, force output; otherwise suppress logging.
        """
        if not force:
            return
        dt = dt or self.datas[0].datetime.datetime(0)
        print(f"{dt.isoformat()}, {txt}")

    def __init__(self):
        """Initialize the MACD+KDJ strategy.

        Sets up statistical tracking variables, initializes MACD and KDJ
        indicators, and establishes the data feed reference.
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

        # MACD indicator
        self.macd = bt.indicators.MACD(
            self.data0,
            period_me1=self.p.macd_fast_period,
            period_me2=self.p.macd_slow_period,
            period_signal=self.p.macd_signal_period
        )
        # KDJ indicator
        self.kdj = KDJ(
            self.data0,
            period=self.p.kdj_fast_period,
            period_dfast=self.p.kdj_slow_period,
            period_dslow=self.p.kdj_slow_period
        )

        # Trading status
        self.marketposition = 0

    def notify_trade(self, trade):
        """Callback when a trade is completed.

        Updates trade statistics including win/loss count and total profit/loss
        when a trade is closed.

        Args:
            trade (Trade): Trade object containing information about the
                completed trade, including PnL and status.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnl > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.sum_profit += trade.pnl

    def next(self):
        """Execute trading logic for each bar.

        Implements the core strategy logic by checking for MACD golden cross
        and KDJ death cross conditions, then executing trades based on the
        current market position.

        Trading Logic:
            1. Detect MACD golden cross (MACD crosses above signal line)
            2. Detect KDJ death cross (K crosses below D)
            3. Execute entry/exit based on current position:
               * Flat: Enter on appropriate signal
               * Short: Exit on MACD golden cross
               * Long: Exit on KDJ death cross
        """
        self.bar_num += 1
        data = self.data0

        # MACD golden cross condition
        macd_golden_cross = (self.macd.macd[0] > self.macd.signal[0] and
                            self.macd.macd[-1] < self.macd.signal[-1])
        # KDJ death cross condition
        kdj_death_cross = (self.kdj.K[0] < self.kdj.D[0] and
                          self.kdj.K[-1] > self.kdj.D[-1])

        if self.marketposition == 0:
            # MACD golden cross buy signal
            if macd_golden_cross:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.buy(size=size)
                    self.marketposition = 1
                    self.buy_count += 1
            # KDJ death cross sell signal
            elif kdj_death_cross:
                size = int(self.broker.getcash() / data.close[0])
                if size > 0:
                    self.sell(size=size)
                    self.marketposition = -1
                    self.sell_count += 1
        elif self.marketposition == -1:
            # Short position: MACD golden cross to close
            if macd_golden_cross:
                self.close()
                self.marketposition = 0
                self.buy_count += 1
        elif self.marketposition == 1:
            # Long position: KDJ death cross to close
            if kdj_death_cross:
                self.close()
                self.marketposition = 0
                self.sell_count += 1

    def stop(self):
        """Output statistics when strategy execution stops.

        Calculates and logs final performance metrics including total bars
        processed, trade counts, win rate, and total profit/loss.
        """
        total_trades = self.win_count + self.loss_count
        win_rate = (self.win_count / total_trades * 100) if total_trades > 0 else 0
        self.log(
            f"bar_num={self.bar_num}, buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}",
            force=True
        )


def test_macd_kdj_strategy():
    """Test the MACD+KDJ combined trading strategy.

    This test function:
        1. Loads Shanghai Stock Exchange data (sh600000.csv)
        2. Configures a Cerebro backtesting engine with initial capital of 100,000
        3. Adds the MACDKDJStrategy with standard indicator parameters
        4. Attaches performance analyzers (Sharpe Ratio, Returns, Drawdown, Trade Analyzer)
        5. Runs the backtest and validates results against expected values

    Expected Results:
        * bar_num: 5382 (number of bars processed)
        * buy_count: 215 (number of buy orders)
        * sell_count: 216 (number of sell orders)
        * total_trades: 212 (completed round-trip trades)
        * final_value: 5870.49 (final portfolio value)
        * sharpe_ratio: -0.12656086550315188 (risk-adjusted return)
        * annual_return: -0.12361020751082702 (annualized return)
        * max_drawdown: 0.9863327709363255 (maximum drawdown percentage)

    Raises:
        AssertionError: If any of the expected backtest results do not match
            the actual results within the specified tolerance.
        FileNotFoundError: If the required data file (sh600000.csv) cannot
            be located by the resolve_data_path function.
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

    cerebro.addstrategy(
        MACDKDJStrategy,
        macd_fast_period=12,
        macd_slow_period=26,
        macd_signal_period=9,
        kdj_fast_period=9,
        kdj_slow_period=3,
    )

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
    print("MACD+KDJ Strategy Backtest Results:")
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

    assert strat.bar_num == 5382, f"Expected bar_num=5382, got {strat.bar_num}"
    assert strat.buy_count == 215, f"Expected buy_count=215, got {strat.buy_count}"
    assert strat.sell_count == 216, f"Expected sell_count=216, got {strat.sell_count}"
    assert total_trades == 212, f"Expected total_trades=212, got {total_trades}"
    assert abs(final_value - 5870.49) < 0.01, f"Expected final_value=5870.49, got {final_value}"
    assert abs(sharpe_ratio - (-0.12656086550315188)) < 1e-6, f"Expected sharpe_ratio=-0.12656086550315188, got {sharpe_ratio}"
    assert abs(annual_return - (-0.12361020751082702)) < 1e-6, f"Expected annual_return=-0.12361020751082702, got {annual_return}"
    assert abs(max_drawdown - 0.9863327709363255) < 1e-6, f"Expected max_drawdown=0.9863327709363255, got {max_drawdown}"

    print("\nAll tests passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("MACD+KDJ Strategy Test")
    print("=" * 60)
    test_macd_kdj_strategy()
