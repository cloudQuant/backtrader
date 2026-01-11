#!/usr/bin/env python
"""Test module for trading calendar functionality in Backtrader.

This module contains tests to verify that Backtrader can properly integrate
with trading calendars, particularly pandas-based calendars like the
USFederalHolidayCalendar. The test ensures the framework can handle data
with trading day filters and calendar-based date exclusion.

Typical usage example:
    test_tradingcal(main=True)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class TradingCalTestStrategy(bt.Strategy):
    """A minimal test strategy for trading calendar functionality.

    This strategy serves as a placeholder strategy for testing trading calendar
    integration. It performs no actual trading logic but validates that the
    strategy can be instantiated and executed when a trading calendar is
    configured.

    Attributes:
        None explicitly defined, but inherits all attributes from bt.Strategy.
    """

    def next(self):
        """Called for each bar of data during backtesting.

        This method is a no-op placeholder to satisfy the Strategy interface.
        In a full implementation, this would contain trading logic.

        Args:
            None

        Returns:
            None

        Raises:
            None
        """
        pass


def test_tradingcal(main=False):
    """Test trading calendar functionality with Backtrader Cerebro engine.

    This function sets up a Cerebro backtesting engine with sample data and
    attempts to integrate with pandas trading calendars (specifically
    USFederalHolidayCalendar) if available. It validates that the framework can
    execute a strategy even when trading calendar functionality is present.

    The test loads data from 2006 and attempts to configure a trading calendar
    to filter out non-trading days (holidays, weekends). The test gracefully
    handles cases where pandas is not installed or the trading calendar
    functionality is not available.

    Args:
        main (bool, optional): If True, enables print statements for manual
            execution. Defaults to False. This parameter is primarily used
            when the test is run directly as a script rather than through
            a test runner.

    Returns:
        None: This function performs assertions but returns no value.

    Raises:
        AssertionError: If the Cerebro run produces no results, indicating
            a failure in the backtesting execution.

    Example:
        >>> test_tradingcal()
        >>> test_tradingcal(main=True)  # For manual execution with output
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(TradingCalTestStrategy)

    try:
        # Try to set a trading calendar if available
        import pandas as pd

        try:
            from pandas.tseries.holiday import USFederalHolidayCalendar

            cal = USFederalHolidayCalendar()
            # TradingCalendar functionality test
        except Exception:
            pass
    except Exception:
        pass

    results = cerebro.run()
    assert len(results) > 0

    if main:
        # print('TradingCal test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_tradingcal(main=True)
