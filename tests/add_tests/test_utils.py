#!/usr/bin/env python


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt
from backtrader.utils import AutoDict, AutoOrderedDict, date2num, num2date


def test_date_conversion(main=False):
    """Test date conversion utilities"""

    # Test date2num and num2date
    test_date = datetime.datetime(2006, 1, 1)
    num_date = date2num(test_date)
    converted_back = num2date(num_date)

    if main:
        # print(f'Original date: {test_date}')  # Removed for performance
        pass
        print(f"Converted to num: {num_date}")
        print(f"Converted back: {converted_back}")

    assert converted_back.year == test_date.year
    assert converted_back.month == test_date.month
    assert converted_back.day == test_date.day

    if main:
        # print('Date conversion test passed')  # Removed for performance
        pass


def test_autodict(main=False):
    """Test AutoDict and AutoOrderedDict"""

    # Test AutoDict
    ad = AutoDict()
    ad.level1.level2.level3 = "value"

    assert ad.level1.level2.level3 == "value"

    # Test AutoOrderedDict
    aod = AutoOrderedDict()
    aod.key1.key2 = "test_value"

    assert aod.key1.key2 == "test_value"

    if main:
        # print('AutoDict test passed')  # Removed for performance
        pass
        print("AutoOrderedDict test passed")


def test_utils_integration(main=False):
    """Test utils in strategy context"""

    class UtilsStrategy(bt.Strategy):
        def __init__(self):
            self.order_count = 0

        def next(self):
            # Use date conversion in strategy
            dt_num = self.data.datetime[0]
            dt = num2date(dt_num)

            # Verify conversion works
            assert dt is not None
            assert isinstance(dt, datetime.datetime)

            if not self.position and len(self) == 10:
                self.buy()

    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(UtilsStrategy)
    cerebro.run()

    if main:
        # print('Utils integration test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_date_conversion(main=True)
    test_autodict(main=True)
    test_utils_integration(main=True)
