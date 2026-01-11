#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test Case: Mean Reversion SMA Strategy

Reference: backtrader-strategies-compendium/strategies/MeanReversion.py
Buy when price drops below SMA by a certain percentage, sell when it returns to SMA.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import datetime
import math
from pathlib import Path
import backtrader as bt

BASE_DIR = Path(__file__).resolve().parent


def resolve_data_path(filename: str) -> Path:
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
    """Mean Reversion SMA Strategy.

    Entry Conditions:
        - Buy when price drops below SMA by more than dip_size percentage.

    Exit Conditions:
        - Sell when price returns above SMA.
    """
    params = dict(
        period=20,
        order_percentage=0.95,
        dip_size=0.025,
    )

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0

    def log(self, txt, dt=None):
        """Logging function for this strategy."""
        dt = dt or bt.num2date(self.datas[0].datetime[0])
        print('{}, {}'.format(dt.isoformat(), txt))

    def notify_order(self, order):
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
        """Log information when a trade is closed or opened."""
        if trade.isclosed:
            self.log('closed symbol is : {} , total_profit : {} , net_profit : {}'.format(
                trade.getdataname(), trade.pnl, trade.pnlcomm))
            # self.trade_list.append([self.datas[0].datetime.date(0),trade.getdataname(),trade.pnl,trade.pnlcomm])

        if trade.isopen:
            self.log('open symbol is : {} , price : {} '.format(
                trade.getdataname(), trade.price))

    def next(self):
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
    """Test the Mean Reversion SMA strategy.

    This test:
        1. Loads historical Oracle stock data from 2010-2014
        2. Runs the Mean Reversion SMA strategy with default parameters
        3. Validates performance metrics against expected values

    Raises:
        AssertionError: If any of the performance metrics don't match expected values.
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
