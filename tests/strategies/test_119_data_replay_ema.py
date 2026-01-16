#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Data Replay - EMA Dual Moving Average Strategy

Reference: test_58_data_replay.py
Tests data replay functionality using an EMA dual moving average crossover strategy.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching in common locations.

    This function searches for a data file in multiple possible locations
    relative to the test file directory, including the current directory,
    parent directory, and 'datas' subdirectories.

    Args:
        filename: The name of the data file to locate.

    Returns:
        Path: The resolved path to the data file.

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


class ReplayEMAStrategy(bt.Strategy):
    """Strategy for testing data replay - EMA dual moving average crossover.

    Strategy logic:
    - Buy when fast EMA crosses above slow EMA
    - Sell and close position when fast EMA crosses below slow EMA
    """
    params = (('fast_period', 12), ('slow_period', 26))

    def __init__(self):
        """Initialize the EMA crossover strategy with indicators and tracking variables.

        Sets up the exponential moving averages, crossover indicator, and
        initializes counters for tracking strategy execution.
        """
        self.fast_ema = bt.ind.EMA(period=self.p.fast_period)
        self.slow_ema = bt.ind.EMA(period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ema, self.slow_ema)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def log(self, txt, dt=None):
        """Log strategy messages with timestamps.

        Args:
            txt: The message text to log.
            dt: Optional datetime object. If not provided, uses the current
                bar's datetime from the first data feed.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def notify_order(self, order):
        """Handle order status updates and log order execution details.

        Called by the backtrader engine when an order changes status. Logs
        order events including rejections, cancellations, partial fills, and
        completed executions. Tracks buy and sell order counts.

        Args:
            order: The order object with updated status information.
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
        """Handle trade status updates and log trade performance metrics.

        Called by the backtrader engine when a trade changes status. Logs
        profit/loss information when trades are closed and entry prices when
        trades are opened.

        Args:
            trade: The trade object with updated status information.
        """
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))

        if trade.isopen:
            self.log('open symbol is : {} , price : {} '.format(
                trade.getdataname(), trade.price))

    def next(self):
        """Execute trading logic for each bar.

        Implements the EMA crossover strategy:
        - When fast EMA crosses above slow EMA (crossover > 0): close any existing
          position and open a new long position
        - When fast EMA crosses below slow EMA (crossover < 0): close any
          existing position

        Only one order is allowed at a time. The bar counter is incremented
        on each call for test verification purposes.
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


def test_data_replay_ema():
    """Test data replay functionality using EMA dual moving average strategy.

    This test validates that backtrader's data replay feature works correctly
    by replaying daily data as weekly bars and applying an EMA crossover
    strategy. The test:

    1. Loads daily price data from a CSV file
    2. Replays the data at weekly timeframe using cerebro.replaydata()
    3. Runs an EMA(12,26) crossover strategy
    4. Collects performance metrics (Sharpe ratio, returns, drawdown, trades)
    5. Asserts that results match expected values

    The replay feature compresses multiple bars into a single bar with
    aggregated data (open, high, low, close, volume), allowing strategies
    to be tested at different timeframes than the original data.

    Raises:
        AssertionError: If any of the test assertions fail, including:
            - Incorrect bar count
            - Final portfolio value mismatch
            - Sharpe ratio deviation
            - Annual return deviation
            - Maximum drawdown deviation
            - Incorrect trade count
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

    cerebro.addstrategy(ReplayEMAStrategy, fast_period=12, slow_period=26)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # Add complete analyzers
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
    print("Data Replay EMA Strategy Backtest Results (Weekly):")
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
    assert strat.bar_num == 384, f"Expected bar_num=384, got {strat.bar_num}"
    assert abs(final_value - 104553.50) < 0.01, f"Expected final_value=104553.50, got {final_value}"
    assert abs(sharpe_ratio - 0.8871126960270267) < 1e-6, f"Expected sharpe_ratio=0.8871126960270267, got {sharpe_ratio}"
    assert abs(annual_return - 0.022514058583059444) < 1e-6, f"Expected annual_return=0.022514058583059444, got {annual_return}"
    assert abs(max_drawdown - 1.7853002550428876) < 1e-6, f"Expected max_drawdown=1.7853002550428876, got {max_drawdown}"
    assert total_trades == 9, f"Expected total_trades=9, got {total_trades}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Data Replay EMA Strategy Test")
    print("=" * 60)
    test_data_replay_ema()
