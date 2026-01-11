#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Data Replay - MACD Strategy

Reference source: test_58_data_replay.py
Tests the data replay functionality using MACD crossover strategy.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching in common locations.

    This function searches for a data file in multiple possible locations relative
    to the current test directory, including the current directory, parent directory,
    and 'datas' subdirectories.

    Args:
        filename: The name of the data file to locate.

    Returns:
        Path: The absolute path to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search locations.

    Examples:
        >>> path = resolve_data_path('2005-2006-day-001.txt')
        >>> print(path.exists())
        True
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


class ReplayMACDStrategy(bt.Strategy):
    """Strategy for testing data replay - MACD crossover.

    Strategy logic:
        - Buy when MACD line crosses above signal line
        - Sell and close position when MACD line crosses below signal line

    Attributes:
        macd: MACD indicator instance.
        crossover: CrossOver indicator for MACD and signal line.
        order: Current pending order.
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
    """
    params = (('fast_period', 12), ('slow_period', 26), ('signal_period', 9))

    def __init__(self):
        """Initialize the ReplayMACDStrategy with indicators and tracking variables.

        This method sets up the MACD indicator with configurable periods and
        initializes tracking variables for order management and statistics.

        The strategy uses:
        - MACD indicator for trend analysis
        - CrossOver indicator to detect signal line crossovers
        - Order tracking to prevent multiple simultaneous orders
        - Counters for buy/sell orders and processed bars
        """
        self.macd = bt.ind.MACD(
            period_me1=self.p.fast_period,
            period_me2=self.p.slow_period,
            period_signal=self.p.signal_period
        )
        self.crossover = bt.ind.CrossOver(self.macd.macd, self.macd.signal)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def log(self, txt, dt=None):
        """Log a message with timestamp for this strategy.

        This method prints log messages with an ISO-formatted timestamp, using
        the current bar's datetime if no timestamp is provided.

        Args:
            txt: The message text to log.
            dt: Optional datetime object for the log entry. If None, uses the
                current bar's datetime from the first data feed.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def notify_order(self, order):
        """Handle order status changes and update tracking variables.

        This method is called by the backtrader engine whenever an order's status
        changes. It logs order events and updates the buy/sell counters for
        completed orders.

        Args:
            order: The order object with updated status information.

        Order Statuses Handled:
            - Submitted: Order has been submitted to the broker.
            - Accepted: Order has been accepted by the broker.
            - Rejected: Order was rejected (insufficient funds, etc.).
            - Margin: Order requires margin (not enough cash).
            - Cancelled: Order was cancelled.
            - Partial: Order was partially filled.
            - Completed: Order was fully executed.

        Side Effects:
            - Updates self.buy_count when buy orders complete.
            - Updates self.sell_count when sell orders complete.
            - Sets self.order to None when order is no longer alive.
            - Logs all order status changes.
        """
        if not order.alive():
            self.order = None

        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Rejected:
            self.log(f"Rejected : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Margin:
            self.log(f"Margin : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Cancelled:
            self.log(f"Concelled : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Partial:
            self.log(f"Partial : order_ref:{order.ref}  data_name:{order.p.data._name}")

        if order.status == order.Completed:
            if order.isbuy():
                self.buy_count += 1
                self.log(
                    f" BUY : data_name:{order.p.data._name} price : {order.executed.price} , cost : {order.executed.value} , commission : {order.executed.comm}")

            else:  # Sell
                self.sell_count += 1
                self.log(
                    f" SELL : data_name:{order.p.data._name} price : {order.executed.price} , cost : {order.executed.value} , commission : {order.executed.comm}")

    def notify_trade(self, trade):
        """Handle trade lifecycle events and log trade statistics.

        This method is called by the backtrader engine when a trade's status
        changes. It logs profit/loss information when trades close and entry
        prices when trades are opened.

        Args:
            trade: The trade object with updated status information.

        Trade States Handled:
            - Open: Trade has been opened (position entered).
            - Closed: Trade has been closed (position exited).

        Side Effects:
            - Logs closed trades with symbol, gross profit, and net profit.
            - Logs opened trades with symbol and entry price.
        """
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))

        if trade.isopen:
            self.log('open symbol is : {} , price : {} '.format(
                trade.getdataname(), trade.price))

    def next(self):
        """Execute trading logic for each bar in the backtest.

        This method is called by the backtrader engine for each bar after all
        indicators have been calculated. It implements the MACD crossover strategy:
        - Buy when MACD crosses above the signal line
        - Sell and close position when MACD crosses below the signal line

        The method also logs detailed indicator values for debugging purposes,
        including MACD, signal line, and crossover values for each bar.

        Trading Logic:
            1. Check for pending orders and wait if one exists
            2. If crossover > 0 (MACD crosses above signal):
               - Close existing position if any
               - Open new long position
            3. If crossover < 0 (MACD crosses below signal):
               - Close existing position if any

        Side Effects:
            - Increments self.bar_num counter
            - Logs detailed indicator values for each bar
            - May create buy or close orders
            - Updates self.order with pending order reference
        """
        self.bar_num += 1
        # Print detailed MACD values for debugging in first 10 bars and key positions
        macd_val = self.macd.macd[0] if len(self.macd.macd) > 0 else 'N/A'
        signal_val = self.macd.signal[0] if len(self.macd.signal) > 0 else 'N/A'
        me1_val = self.macd.me1[0] if len(self.macd.me1) > 0 else 'N/A'
        me2_val = self.macd.me2[0] if len(self.macd.me2) > 0 else 'N/A'
        self.log(f"bar_num: {self.bar_num}, close: {self.data.close[0]}, len: {len(self.data)}, me1: {me1_val}, me2: {me2_val}, MACD: {macd_val}, signal: {signal_val}, crossover: {self.crossover[0]}")
        if self.order:
            return
        if self.crossover > 0:
            if self.position:
                self.order = self.close()
            self.order = self.buy()
        elif self.crossover < 0:
            if self.position:
                self.order = self.close()


def test_data_replay_macd():
    """Test Data Replay functionality with MACD strategy.

    This test validates the data replay feature by replaying daily data as weekly
    data and applying a MACD crossover strategy. The test verifies that the replay
    functionality correctly aggregates data and produces expected trading results.

    Raises:
        AssertionError: If any of the test assertions fail, including:
            - Number of bars processed
            - Final portfolio value
            - Sharpe ratio
            - Annual return
            - Maximum drawdown
            - Total number of trades
    """
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(100000.0)

    print("Loading data...")
    data_path = resolve_data_path("2005-2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(dataname=str(data_path))

    # Use replay functionality to replay daily data as weekly data
    cerebro.replaydata(
        data,
        timeframe=bt.TimeFrame.Weeks,
        compression=1
    )

    cerebro.addstrategy(ReplayMACDStrategy, fast_period=12, slow_period=26, signal_period=9)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # Add comprehensive analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe",
                        timeframe=bt.TimeFrame.Weeks, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    print("Starting backtest...")
    results = cerebro.run(preload=False)
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
    print("Data Replay MACD Strategy Backtest Results (Weekly):")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  total_trades: {total_trades}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # Assert test results
    assert strat.bar_num == 344, f"Expected bar_num=344, got {strat.bar_num}"
    assert abs(final_value - 106870.40) < 0.01, f"Expected final_value=107568.30, got {final_value}"
    assert abs(sharpe_ratio - 1.3228391876325063) < 1e-6, f"Expected sharpe_ratio=1.353877653906896, got {sharpe_ratio}"
    assert abs(annual_return - 0.033781408229031695) < 1e-6, f"Expected annual_return=0.03715138721403644, got {annual_return}"
    assert abs(max_drawdown - 1.6636055151304665) < 1e-6, f"Expected max_drawdown=1.6528018163884495, got {max_drawdown}"
    assert total_trades == 9, f"Expected total_trades=10, got {total_trades}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Data Replay MACD Strategy Test")
    print("=" * 60)
    test_data_replay_macd()
