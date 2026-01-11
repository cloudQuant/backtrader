#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Data Replay

Reference: backtrader-master2/samples/data-replay/data-replay.py
Tests the data replay functionality using a dual moving average crossover strategy.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the path to a data file by searching in common locations.

    This function searches for a data file in multiple standard locations
    relative to the test file directory, including the current directory,
    parent directory, and 'datas' subdirectories.

    Args:
        filename: Name of the data file to locate.

    Returns:
        Path object pointing to the found data file.

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


class ReplayMAStrategy(bt.Strategy):
    """Strategy for testing data replay - dual moving average crossover.

    Strategy logic:
        - Buy when the fast line crosses above the slow line
        - Sell and close position when the fast line crosses below the slow line

    Attributes:
        fast_ma: Fast moving average indicator.
        slow_ma: Slow moving average indicator.
        crossover: Crossover indicator between fast and slow MAs.
        order: Current pending order.
        bar_num: Number of bars processed.
        buy_count: Number of buy orders executed.
        sell_count: Number of sell orders executed.
    """
    params = (('fast_period', 5), ('slow_period', 15))

    def __init__(self):
        """Initialize the ReplayMAStrategy with indicators and tracking variables.

        Sets up the fast and slow moving average indicators, the crossover
        indicator, and initializes tracking variables for orders and bar counts.
        """
        self.fast_ma = bt.ind.SMA(period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def log(self, txt, dt=None):
        """Logging function for this strategy.

        Args:
            txt: Text message to log.
            dt: Datetime object. If None, uses current data datetime.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def notify_order(self, order):
        """Handle order notifications and track order status changes.

        This method is called by the broker when an order status changes.
        It logs order execution details and updates the buy/sell counters
        when orders are completed.

        Args:
            order: The order object that triggered the notification.
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
        """Handle trade notifications and log trade information.

        This method is called when a trade is opened or closed. It logs
        the profit/loss information for closed trades and price information
        for newly opened trades.

        Args:
            trade: The trade object that triggered the notification.
        """
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))
            # self.trade_list.append([self.datas[0].datetime.date(0),trade.getdataname(),trade.pnl,trade.pnlcomm])

        if trade.isopen:
            self.log('open symbol is : {} , price : {} '.format(
                trade.getdataname(), trade.price))

    def next(self):
        """Execute the trading strategy logic for each bar.

        This method is called for each bar of data. It implements the dual
        moving average crossover strategy:
        - When fast MA crosses above slow MA (crossover > 0): close existing
          position and buy
        - When fast MA crosses below slow MA (crossover < 0): close position

        Only one order is allowed at a time to avoid overlapping positions.
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


def test_data_replay():
    """Test Data Replay functionality.

    This function tests the data replay feature by replaying daily data as weekly
    data and running a dual moving average crossover strategy.

    Raises:
        AssertionError: If any of the test assertions fail.
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

    cerebro.addstrategy(ReplayMAStrategy, fast_period=5, slow_period=15)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    # Add complete analyzers - calculate Sharpe ratio using weekly timeframe
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
    print("Data Replay Backtest Results (Weekly):")
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
    assert strat.bar_num == 439, f"Expected bar_num=439, got {strat.bar_num}"
    assert abs(final_value - 108263.90) < 0.01, f"Expected final_value=108263.90, got {final_value}"
    assert abs(sharpe_ratio - 1.17880670695321) < 1e-6, f"Expected sharpe_ratio=1.17880670695321, got {sharpe_ratio}"
    assert abs(annual_return - 0.04049939932707298) < 1e-6, f"Expected annual_return=0.04049939932707298, got {annual_return}"
    assert abs(max_drawdown - 2.668267546216064) < 1e-6, f"Expected max_drawdown=2.668267546216064, got {max_drawdown}"
    assert total_trades == 13, f"Expected total_trades=13, got {total_trades}"

    print("\nTest passed!")


if __name__ == "__main__":
    print("=" * 60)
    print("Data Replay Test")
    print("=" * 60)
    test_data_replay()
