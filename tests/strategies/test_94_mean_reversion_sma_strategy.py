#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Mean Reversion SMA Strategy Test Module.

This module implements and tests a mean reversion strategy based on Simple Moving
Average (SMA). The strategy buys when the price drops below the SMA by a
specified percentage threshold and sells when the price returns to the SMA.

Reference: backtrader-strategies-compendium/strategies/MeanReversion.py

Example:
    To run the test::

        python test_94_mean_reversion_sma_strategy.py
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import math
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
    """Resolve the absolute path to a test data file.

    Searches for data files in multiple possible locations relative to the
    test directory, including the current directory, parent directory,
    and 'datas' subdirectories.

    Args:
        filename (str): The name of the data file to locate.

    Returns:
        Path: The absolute path to the found data file.

    Raises:
        FileNotFoundError: If the data file cannot be found in any of the
            search locations.

    Example:
        >>> path = resolve_data_path("orcl-1995-2014.txt")
        >>> print(path)
        /path/to/tests/strategies/datas/orcl-1995-2014.txt
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


class MeanReversionSmaStrategy(bt.Strategy):
    """A mean reversion trading strategy based on Simple Moving Average (SMA).

    This strategy implements a mean reversion approach by identifying when prices
    deviate significantly from their SMA. It enters long positions when the price
    drops below the SMA by a specified percentage threshold (dip_size) and exits
    when the price returns to the SMA level.

    Entry Conditions:
        - Buy when price drops below SMA by more than dip_size percentage.

    Exit Conditions:
        - Sell when price returns to or above SMA.

    Attributes:
        sma (bt.indicators.SMA): The Simple Moving Average indicator.
        order (bt.Order): The current pending order, or None if no order is pending.
        bar_num (int): Counter tracking the number of bars processed.
        buy_count (int): Total number of buy orders executed.
        sell_count (int): Total number of sell orders executed.

    Args:
        period (int): The period for the SMA calculation. Default is 20.
        order_percentage (float): The percentage of available cash to use per
            trade. Default is 0.95 (95%).
        dip_size (float): The percentage drop below SMA required to trigger a
            buy signal. Default is 0.025 (2.5%).

    Example:
        >>> cerebro = bt.Cerebro()
        >>> cerebro.addstrategy(MeanReversionSmaStrategy, period=20, dip_size=0.03)
    """
    params = dict(
        period=20,
        order_percentage=0.95,
        dip_size=0.025,
    )

    def __init__(self):
        """Initialize the MeanReversionSmaStrategy.

        Sets up the SMA indicator and initializes tracking variables for orders
        and trade statistics.
        """
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def log(self, txt, dt=None):
        """Log a message with timestamp for strategy monitoring.

        Args:
            txt (str): The message text to log.
            dt (datetime.datetime, optional): The datetime to use for the log
                entry. If None, uses the current bar's datetime.
        """
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def notify_order(self, order):
        """Handle order status updates and logging.

        Called by the backtrader engine when an order changes status. Logs
        order completion, rejection, cancellation, and other status changes.
        Updates buy/sell counters when orders are completed.

        Args:
            order (bt.Order): The order object with updated status.
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
        """Handle trade lifecycle events (open/close).

        Called by the backtrader engine when a trade is opened or closed.
        Logs profit/loss information when trades close.

        Args:
            trade (bt.Trade): The trade object with updated status.
        """
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))
            # self.trade_list.append([self.datas[0].datetime.date(0),trade.getdataname(),trade.pnl,trade.pnlcomm])

        if trade.isopen:
            self.log('open symbol is : {} , price : {} '.format(
                trade.getdataname(), trade.price))

    def next(self):
        """Execute trading logic for each bar.

        This method is called by the backtrader engine for each bar. Implements
        the mean reversion strategy logic:
        1. If no position exists, check if price has dropped below SMA by
           dip_size percentage and buy if so.
        2. If a position exists, close it when price returns to SMA level.
        """
        self.bar_num += 1

        if self.order:
            return

        if not self.position:
            # Price drops below SMA by more than dip_size percentage
            dip_ratio = (self.data.close[0] / self.sma[0]) - 1
            if dip_ratio <= -self.p.dip_size:
                amount = self.p.order_percentage * self.broker.cash
                size = math.floor(amount / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            # Price returns to SMA
            if self.data.close[0] >= self.sma[0]:
                self.order = self.close()


def test_mean_reversion_sma_strategy():
    """Test the Mean Reversion SMA strategy with historical data.

    This test function validates the MeanReversionSmaStrategy implementation by:
        1. Loading historical Oracle stock data from 2010-2014
        2. Running the strategy with default parameters (period=20, dip_size=0.025)
        3. Calculating performance metrics (Sharpe ratio, annual return, drawdown)
        4. Validating results against expected values with tight tolerances

    The test uses:
        - Initial cash: $100,000
        - Commission: 0.1% per trade
        - Data range: 2010-01-01 to 2014-12-31
        - Expected final value: $172,375.61 (72.4% return)

    Raises:
        AssertionError: If any of the performance metrics don't match expected
            values within specified tolerances. Final value tolerance is 0.01,
            all other metrics tolerance is 1e-6.
        FileNotFoundError: If the Oracle data file cannot be located.

    Example:
        >>> test_mean_reversion_sma_strategy()
        ==================================================
        Mean Reversion SMA Strategy Backtest Results:
          bar_num: 1238
          buy_count: 42
          sell_count: 42
          sharpe_ratio: 1.2716817661545428
          annual_return: 0.11534195315155864
          max_drawdown: 18.967205229875198
          final_value: 172375.61
        ==================================================

        Test passed!
    """
    cerebro = bt.Cerebro()
    data_path = resolve_data_path("orcl-1995-2014.txt")
    data = bt.feeds.GenericCSVData(
        dataname=str(data_path),
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2014, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(MeanReversionSmaStrategy)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    results = cerebro.run()
    strat = results[0]
    sharpe_ratio = strat.analyzers.sharpe.get_analysis().get('sharperatio', None)
    annual_return = strat.analyzers.returns.get_analysis().get('rnorm', 0)
    max_drawdown = strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    final_value = cerebro.broker.getvalue()

    print("=" * 50)
    print("Mean Reversion SMA Strategy Backtest Results:")
    print(f"  bar_num: {strat.bar_num}")
    print(f"  buy_count: {strat.buy_count}")
    print(f"  sell_count: {strat.sell_count}")
    print(f"  sharpe_ratio: {sharpe_ratio}")
    print(f"  annual_return: {annual_return}")
    print(f"  max_drawdown: {max_drawdown}")
    print(f"  final_value: {final_value:.2f}")
    print("=" * 50)

    # final_value tolerance: 0.01, other metrics tolerance: 1e-6
    assert strat.bar_num == 1238, f"Expected bar_num=1238, got {strat.bar_num}"
    assert abs(final_value - 172375.61) < 0.01, f"Expected final_value=172375.61, got {final_value}"
    assert abs(sharpe_ratio - (1.2716817661545428)) < 1e-6, f"Expected sharpe_ratio=1.2716817661545428, got {sharpe_ratio}"
    assert abs(annual_return - (0.11534195315155864)) < 1e-6, f"Expected annual_return=0.11534195315155864, got {annual_return}"
    assert abs(max_drawdown - 18.967205229875198) < 1e-6, f"Expected max_drawdown=18.967205229875198, got {max_drawdown}"

    print("\nTest passed!")



if __name__ == "__main__":
    print("=" * 60)
    print("Mean Reversion SMA Strategy Test")
    print("=" * 60)
    test_mean_reversion_sma_strategy()
