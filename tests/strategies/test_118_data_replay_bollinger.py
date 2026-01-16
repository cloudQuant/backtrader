#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test Case: Data Replay - Bollinger Bands Strategy.

This module tests the data replay functionality using a Bollinger Bands
breakout strategy.

Reference: test_58_data_replay.py
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
    relative to the current test file directory. It checks the current
    directory, parent directory, and 'datas' subdirectories.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path: The absolute path to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            searched locations.
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


class ReplayBollingerStrategy(bt.Strategy):
    """Test data replay strategy with Bollinger Bands breakout.

    Strategy logic:
        - Buy when price breaks above the upper band
        - Sell and close position when price falls below the middle band
    """
    params = (('period', 20), ('devfactor', 2.0))

    def __init__(self):
        """Initialize the ReplayBollingerStrategy.

        Sets up the Bollinger Bands indicator and initializes tracking
        variables for orders, bars, and trade counts.
        """
        self.boll = bt.ind.BollingerBands(period=self.p.period, devfactor=self.p.devfactor)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def log(self, txt, dt=None):
        """Log strategy messages with timestamp.

        Args:
            txt: The message text to log.
            dt: Optional datetime object for the log entry. If None, uses the
                current bar's datetime from the first data feed.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def notify_order(self, order):
        """Handle order status changes and updates.

        Called by the backtrader engine when an order's status changes.
        Logs order events and updates the buy/sell counters.

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
        """Handle trade lifecycle events.

        Called when a trade is opened or closed. Logs the trade status,
        profit/loss information, and price details.

        Args:
            trade: The trade object with updated status and P&L information.
        """
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))

        if trade.isopen:
            self.log('open symbol is : {} , price : {} '.format(
                trade.getdataname(), trade.price))

    def next(self):
        """Execute trading logic for each bar.

        This method is called by the backtrader engine for each bar of data.
        Implements the Bollinger Bands breakout strategy:
        - Buy when price breaks above the upper band (no existing position)
        - Close position when price falls below the middle band (existing position)

        Only one order is allowed at a time to prevent over-trading.
        """
        self.bar_num += 1
        if self.order:
            return

        # Buy when price breaks above the upper band
        if self.data.close[0] > self.boll.top[0]:
            if not self.position:
                self.order = self.buy()
        # Sell when price falls below the middle band
        elif self.data.close[0] < self.boll.mid[0]:
            if self.position:
                self.order = self.close()


def test_data_replay_bollinger():
    """Test Data Replay with Bollinger Bands strategy.

    This test function:
        - Loads daily price data
        - Replays the data as weekly timeframe
        - Executes a Bollinger Bands breakout strategy
        - Validates the backtest results against expected values
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

    cerebro.addstrategy(ReplayBollingerStrategy, period=20, devfactor=2.0)
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
    print("Data Replay Bollinger Bands Strategy Backtest Results (Weekly):")
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
    assert strat.bar_num == 419, f"Expected bar_num=419, got {strat.bar_num}"
    assert abs(final_value - 103822.30) < 0.01, f"Expected final_value=103822.30, got {final_value}"
    assert abs(sharpe_ratio - 0.717232637621499) < 1e-6, f"Expected sharpe_ratio=0.717232637621499, got {sharpe_ratio}"
    assert abs(annual_return - 0.01893228430548803) < 1e-6, f"Expected annual_return=0.01893228430548803, got {annual_return}"
    assert abs(max_drawdown - 1.9767203338832484) < 1e-6, f"Expected max_drawdown=1.9767203338832484, got {max_drawdown}"
    assert total_trades == 2, f"Expected total_trades=2, got {total_trades}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Data Replay Bollinger Bands Strategy Test")
    print("=" * 60)
    test_data_replay_bollinger()
