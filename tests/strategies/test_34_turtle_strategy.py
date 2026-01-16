#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test module for Turtle trading strategy.

This module implements and tests a classic Turtle trading strategy based on
price breakout and trend following principles. The Turtle Trading is one of
the most famous trend-following strategies, developed by Richard Dennis and
William Eckhardt in 1983.

The strategy implemented here:
    - Uses moving average as a trend filter (bull/bear market regime)
    - Buys when price breaks out above N-day high during bull market
    - Uses trailing stop loss to protect profits
    - Exits when the trend reverses (price breaks below long-term MA)

Reference:
    Original implementation from weekend-backtrader/strategy/turtle.py and main.py

Example:
    Run the test directly:
        python tests/strategies/test_34_turtle_strategy.py

    Or run with pytest:
        pytest tests/strategies/test_34_turtle_strategy.py -v
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
    """Locate data files by searching multiple potential directory paths.

    This function searches for data files in several common locations relative
    to the script's directory, avoiding issues with relative path failures when
    the test is run from different working directories.

    Args:
        filename (str): The name of the data file to locate (e.g., 'sh600000.csv').

    Returns:
        Path: The absolute path to the located data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched directories.

    Search Paths:
        1. <script_directory>/<filename>
        2. <script_parent_directory>/<filename>
        3. <script_directory>/datas/<filename>
        4. <script_parent_directory>/datas/<filename>
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


class TurtleStrategy(bt.Strategy):
    """Turtle trading strategy implementation.

    This strategy is based on the classic Turtle Trading system, a trend-following
    approach that buys breakouts in the direction of the long-term trend. It uses
    a dual moving average system to identify market regime (bull/bear) and price
    rate of change to detect breakouts.

    Trading Logic:
        1. Enter long when:
           - Price is above long-term MA (bull market regime)
           - Price rate of change exceeds threshold (breakout detection)

        2. Exit position when:
           - Price falls below long-term MA (trend reversal)
           - Trailing stop loss is hit

        3. Risk management:
           - Trailing stop loss protects profits during favorable moves
           - Stop loss is cancelled when position is closed

    Attributes:
        order (bt.Order or None): Reference to the current pending order.
        stop_order (bt.Order or None): Reference to the trailing stop loss order.
        buyprice (float or None): Execution price of the most recent buy order.
        buycomm (float or None): Commission paid on the most recent buy order.
        sma (bt.indicators.SimpleMovingAverage): Short-term moving average for trend confirmation.
        sma_regime (bt.indicators.SimpleMovingAverage): Long-term moving average for regime filter.
        bar_num (int): Total number of bars processed.
        buy_count (int): Number of buy orders executed.
        sell_count (int): Number of sell orders executed.
        win_count (int): Number of profitable trades closed.
        loss_count (int): Number of unprofitable trades closed.
        sum_profit (float): Total profit/loss across all closed trades (including commissions).

    Parameters:
        maperiod (int): Period for the short-term moving average. Default is 15.
        breakout_period_days (int): Lookback period for calculating price rate of change.
            Originally 100 days in classic turtle strategy, adjusted to 20 for test data.
        price_rate_of_change_perc (float): Threshold for price rate of change to trigger
            entry (e.g., 0.1 = 10% breakout). Default is 0.1.
        regime_filter_ma_period (int): Period for long-term moving average used as
            trend filter. Default is 200.
        trailing_stop_loss_perc (float): Trailing stop loss percentage (e.g., 0.1 = 10%).
            Default is 0.1.

    Note:
        The classic Turtle Trading system uses a 20-day breakout for entry and
        10-day low for exit. This implementation simplifies the approach using
        price rate of change and a long-term moving average filter.
    """
    params = (
        ('maperiod', 15),
        ('breakout_period_days', 20),  # Breakout period, originally 100, adjusted to 20 for data
        ('price_rate_of_change_perc', 0.1),  # Price rate of change threshold
        ('regime_filter_ma_period', 200),  # Trend filter MA period
        ('trailing_stop_loss_perc', 0.1),  # Trailing stop loss percentage
    )

    def __init__(self):
        """Initialize the Turtle trading strategy.

        Sets up the strategy's state variables, indicators, and tracking
        mechanisms for orders and trades.
        """
        self.order = None
        self.stop_order = None
        self.buyprice = None
        self.buycomm = None

        # Moving average indicators
        self.sma = bt.indicators.SimpleMovingAverage(
            self.datas[0],
            period=self.params.maperiod
        )
        self.sma_regime = bt.indicators.SimpleMovingAverage(
            self.datas[0],
            period=self.params.regime_filter_ma_period
        )

        # Statistical variables
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.sum_profit = 0.0

    def _is_bull_regime(self):
        """Determine if currently in a bull market trend."""
        return self.data.close[0] > self.sma_regime[0]

    def notify_order(self, order):
        """Handle order status updates.

        This method is called by Backtrader whenever an order's status changes.
        It tracks buy/sell order execution and records execution prices and
        commissions.

        Args:
            order (bt.Order): The order object with updated status.

        Order Status Handling:
            - Submitted/Acpected: No action, order is pending execution
            - Completed: Record buy/sell count, price, and commission
            - Canceled/Margin/Rejected: Order failed, no action taken
        """
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_count += 1
                self.buyprice = order.executed.price
                self.buycomm = order.executed.comm
            else:
                self.sell_count += 1

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            pass

        self.order = None

    def notify_trade(self, trade):
        """Handle trade completion notifications.

        This method is called when a trade is closed. It updates the strategy's
        performance statistics including total profit, win count, and loss count.

        Args:
            trade (bt.Trade): The completed trade object containing profit/loss
                information in the `pnlcomm` attribute (profit/loss including
                commissions).

        Statistics Updated:
            - sum_profit: Cumulative profit/loss across all trades
            - win_count: Number of profitable trades (pnlcomm > 0)
            - loss_count: Number of unprofitable trades (pnlcomm <= 0)
        """
        if trade.isclosed:
            self.sum_profit += trade.pnlcomm
            if trade.pnlcomm > 0:
                self.win_count += 1
            else:
                self.loss_count += 1

    def next(self):
        """Execute the strategy's trading logic for each bar.

        This method is called for each new bar of data. It implements the
        Turtle trading strategy's entry and exit logic:
        - Entry: Long position when in bull regime AND price rate of change exceeds threshold
        - Exit: Close position when trend reverses (bear regime)
        - Risk Management: Trailing stop loss to protect profits

        The method also manages order state and ensures only one active order
        at a time (excluding the trailing stop).
        """
        self.bar_num += 1

        if self.order:
            return

        # Calculate price rate of change
        if len(self.data) <= self.params.breakout_period_days:
            return

        past_price = self.data.close[-self.params.breakout_period_days]
        yesterdays_price = self.data.close[-1]

        if yesterdays_price == 0 or past_price == 0:
            return

        rate_of_change = (yesterdays_price - past_price) / yesterdays_price

        if not self.position:
            # Entry conditions: bull market trend + price breakout
            if self._is_bull_regime() and rate_of_change > self.params.price_rate_of_change_perc:
                self.order = self.buy()
                # Set trailing stop loss
                self.stop_order = self.sell(
                    exectype=bt.Order.StopTrail,
                    trailpercent=self.params.trailing_stop_loss_perc
                )
        else:
            # Exit condition: break below trend line
            if not self._is_bull_regime():
                self.order = self.close()
                if self.stop_order and self.stop_order.alive():
                    self.cancel(self.stop_order)

    def stop(self):
        """Output final trading statistics when backtesting completes.

        This method is called once when the backtesting run finishes. It prints
        a summary of the strategy's performance including trade counts,
        win/loss statistics, win rate, and total profit.

        The output includes:
            - End date of the backtest
            - Total bars processed
            - Number of buy and sell orders executed
            - Win and loss counts
            - Win rate percentage
            - Total profit/loss
        """
        win_rate = (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0
        print(
            f"{self.data.datetime.datetime(0)}, bar_num={self.bar_num}, "
            f"buy_count={self.buy_count}, sell_count={self.sell_count}, "
            f"wins={self.win_count}, losses={self.loss_count}, "
            f"win_rate={win_rate:.2f}%, profit={self.sum_profit:.2f}"
        )


def test_turtle_strategy():
    """Run a complete backtest of the Turtle trading strategy.

    This test function:
        1. Loads historical stock data (Shanghai 600000)
        2. Configures a Cerebro backtesting engine
        3. Adds the Turtle strategy with specific parameters
        4. Runs the backtest from 2000-2022
        5. Validates results against expected values

    The test uses Shanghai stock data (SH600000) from 2000-2022 with a
    starting capital of 100,000 and 0.1% commission per trade.

    Raises:
        FileNotFoundError: If the data file 'sh600000.csv' cannot be located.
        AssertionError: If any of the backtest metrics don't match expected values.

    Expected Results:
        - bar_num: 5216 (total bars processed)
        - buy_count: 46 (buy orders executed)
        - sell_count: 46 (sell orders executed)
        - win_count: 17 (profitable trades)
        - loss_count: 29 (unprofitable trades)
        - total_trades: 46
        - final_value: ~100008.96 (ending portfolio value)
        - sharpe_ratio: ~-248.20 (negative due to poor risk-adjusted returns)
        - annual_return: ~0.0 (near-zero returns)
        - max_drawdown: ~2.45%
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.001)

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

    cerebro.addstrategy(
        TurtleStrategy,
        maperiod=15,
        breakout_period_days=20,
        price_rate_of_change_perc=0.1,
        regime_filter_ma_period=200,
        trailing_stop_loss_perc=0.1
    )

    cerebro.addanalyzer(bt.analyzers.TotalValue, _name="my_value")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="my_sharpe")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="my_returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="my_drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="my_trade")

    print("Starting backtest...")
    results = cerebro.run()
    strat = results[0]

    # Get analyzer results
    sharpe_ratio = strat.analyzers.my_sharpe.get_analysis().get('sharperatio', None)
    returns = strat.analyzers.my_returns.get_analysis()
    annual_return = returns.get('rnorm', 0)
    drawdown = strat.analyzers.my_drawdown.get_analysis()
    max_drawdown = drawdown.get('max', {}).get('drawdown', 0)
    trade_analysis = strat.analyzers.my_trade.get_analysis()
    total_trades = trade_analysis.get('total', {}).get('total', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Turtle trading strategy backtest results:")
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

    # Assertions - using precise assertions
    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 5216, f"Expected bar_num=5216, got {strat.bar_num}"
    assert strat.buy_count == 46, f"Expected buy_count=46, got {strat.buy_count}"
    assert strat.sell_count == 46, f"Expected sell_count=46, got {strat.sell_count}"
    assert strat.win_count == 17, f"Expected win_count=17, got {strat.win_count}"
    assert strat.loss_count == 29, f"Expected loss_count=29, got {strat.loss_count}"
    assert total_trades == 46, f"Expected total_trades=46, got {total_trades}"
    assert abs(final_value - 100008.96) < 0.01, f"Expected final_value=100008.96, got {final_value}"
    assert abs(sharpe_ratio - (-248.19599467327285)) < 1e-6, f"Expected sharpe_ratio=-248.19599467327285, got {sharpe_ratio}"
    assert abs(annual_return - (4.1691151679622e-06)) < 1e-6, f"Expected annual_return=0.0, got {annual_return}"
    assert abs(max_drawdown - 0.02450295600930705) < 1e-6, f"Expected max_drawdown=0.0, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Turtle trading strategy test")
    print("=" * 60)
    test_turtle_strategy()
