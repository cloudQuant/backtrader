#!/usr/bin/env python


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class SampleStrategy1(bt.Strategy):
    params = (
        ("period", 15),
        ("printlog", False),
    )

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.order = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"BUY EXECUTED, Price: {order.executed.price:.2f}")
            else:
                self.log(f"SELL EXECUTED, Price: {order.executed.price:.2f}")
        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"TRADE PROFIT, GROSS {trade.pnl:.2f}, NET {trade.pnlcomm:.2f}")

    def log(self, txt):
        if self.p.printlog:
            dt = self.datas[0].datetime.date(0)
            # print(f'{dt.isoformat()}, {txt}')  # Removed for performance
            pass

    def next(self):
        if self.order:
            return

        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.order = self.buy()
        else:
            if self.data.close[0] < self.sma[0]:
                self.order = self.sell()


def test_strategy_basic(main=False):
    """Test basic strategy functionality"""
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(SampleStrategy1, printlog=main)
    cerebro.broker.setcash(10000.0)

    if main:
        # print(f'Starting Portfolio Value: {cerebro.broker.getvalue():.2f}')  # Removed for performance
        pass

    results = cerebro.run()

    # Verify strategy ran successfully
    assert len(results) > 0
    strat = results[0]
    assert len(strat) > 0  # Processed bars

    final_value = cerebro.broker.getvalue()
    if main:
        # print(f'Final Portfolio Value: {final_value:.2f}')  # Removed for performance
        pass

    # Verify broker value is valid
    assert final_value > 0
    # Verify value changed (either profit or loss)
    assert final_value != 10000.0 or len(strat) == 0  # Changed unless no bars


def test_strategy_multiple_datas(main=False):
    """Test strategy with multiple data feeds"""
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))

    # Add two data feeds
    for datafile in ["2006-day-001.txt", "2006-day-002.txt"]:
        datapath = os.path.join(modpath, "../datas", datafile)
        data = bt.feeds.BacktraderCSVData(
            dataname=datapath,
            fromdate=datetime.datetime(2006, 1, 1),
            todate=datetime.datetime(2006, 12, 31),
        )
        cerebro.adddata(data)

    cerebro.addstrategy(SampleStrategy1)
    results = cerebro.run()

    # Verify strategy handled multiple data feeds
    assert len(results) > 0
    strat = results[0]
    assert len(strat.datas) == 2  # Should have 2 data feeds

    if main:
        print("Strategy with multiple datas test passed")
        print(f"Processed {len(strat)} bars with {len(strat.datas)} data feeds")


def test_strategy_optimization(main=False):
    """Test strategy optimization"""
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.optstrategy(SampleStrategy1, period=range(10, 20, 5))

    results = cerebro.run()

    if main:
        print(f"Optimization tested {len(results)} parameter combinations")

    assert len(results) > 1


if __name__ == "__main__":
    test_strategy_basic(main=True)
    test_strategy_multiple_datas(main=True)
    test_strategy_optimization(main=True)
