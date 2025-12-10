#!/usr/bin/env python


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class BrokerTestStrategy(bt.Strategy):
    def __init__(self):
        self.order = None

    def next(self):
        if not self.position:
            self.order = self.buy()
        elif len(self) > 50:
            self.order = self.close()


def test_broker_basic(main=False):
    """Test basic broker functionality"""
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(BrokerTestStrategy)

    # Test broker cash and value
    cerebro.broker.setcash(100000.0)
    if main:
        # print('Starting Cash: %.2f' % cerebro.broker.getcash())  # Removed for performance
        pass
        print("Starting Value: %.2f" % cerebro.broker.getvalue())

    assert cerebro.broker.getcash() == 100000.0
    assert cerebro.broker.getvalue() == 100000.0

    cerebro.run()

    if main:
        # print('Final Cash: %.2f' % cerebro.broker.getcash())  # Removed for performance
        pass
        print("Final Value: %.2f" % cerebro.broker.getvalue())

    # Verify broker state after run
    assert cerebro.broker.getvalue() > 0


def test_broker_commission(main=False):
    """Test broker commission settings"""
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(BrokerTestStrategy)
    cerebro.broker.setcommission(commission=0.001)

    results = cerebro.run()

    # Verify broker with commission worked
    assert len(results) > 0
    assert results[0].broker.getvalue() > 0

    if main:
        # print('Broker with commission test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_broker_basic(main=True)
    test_broker_commission(main=True)
