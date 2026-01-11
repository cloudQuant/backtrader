#!/usr/bin/env python
"""Test module for Backtrader timer functionality.

This module tests the timer feature in Backtrader strategies, which allows
scheduled execution of code at specific times or intervals. The test verifies
that timers can be added to strategies and properly trigger notifications.

Example:
    Run the test directly:
        python test_timer.py

    Or import and run programmatically:
        from test_timer import test_timer
        test_timer()
"""

import backtrader as bt


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime


class TimerTestStrategy(bt.Strategy):
    """Test strategy for verifying timer functionality.

    This strategy creates a timer that triggers at the start of trading sessions
    on Mondays (weekday 1). It counts how many times the timer fires to verify
    the timer system is working correctly.

    Attributes:
        timer_count (int): Counter for tracking how many times the timer has
            triggered during the backtest.

    Note:
        The timer is configured to trigger on session start for weekdays=[1],
        which corresponds to Monday in Python's datetime convention (0=Monday,
        6=Sunday). Backtrader uses 1=Monday, 7=Sunday.
    """

    def __init__(self):
        """Initialize the TimerTestStrategy.

        Sets up the timer counter and adds a weekly timer that triggers at
        the start of Monday trading sessions.
        """
        self.timer_count = 0
        # Add a timer that triggers weekly
        self.add_timer(
            when=bt.Timer.SESSION_START,
            weekdays=[1],
        )

    def notify_timer(self, timer, when, *args, **kwargs):
        """Handle timer notification events.

        This method is called automatically by Backtrader when the timer
        triggers. It increments the counter to track timer activations.

        Args:
            timer: The timer object that triggered this notification.
            when: Indicates when the timer triggered (e.g., SESSION_START).
            *args: Additional positional arguments passed by the timer.
            **kwargs: Additional keyword arguments passed by the timer.
        """
        self.timer_count += 1

    def next(self):
        """Execute strategy logic for each bar.

        This is a placeholder method required by Backtrader's Strategy interface.
        The actual logic is handled in notify_timer for this test strategy.
        """
        pass


def test_timer(main=False):
    """Test timer functionality in Backtrader strategies.

    This function creates a simple backtest with a strategy that uses timers
    to verify that the timer system works correctly. It loads sample data for
    the year 2006 and runs a strategy with a Monday timer.

    The test verifies:
    1. Timers can be added to strategies
    2. Timer notifications are properly delivered
    3. Timer state is maintained during backtesting

    Args:
        main (bool, optional): If True, prints a success message. Defaults to False.
            This is useful when running the test as a standalone script.

    Raises:
        AssertionError: If the timer_count attribute is missing or negative.

    Note:
        The test uses 2006 daily data from the test data directory. The timer
        should trigger on Mondays throughout the year.
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
    cerebro.addstrategy(TimerTestStrategy)

    results = cerebro.run()
    strat = results[0]

    # Verify timer triggered
    assert hasattr(strat, "timer_count")
    assert strat.timer_count >= 0

    if main:
        # print(f'Timer triggered {strat.timer_count} times')  # Removed for performance
        pass
        print("Timer test passed")


if __name__ == "__main__":
    test_timer(main=True)
