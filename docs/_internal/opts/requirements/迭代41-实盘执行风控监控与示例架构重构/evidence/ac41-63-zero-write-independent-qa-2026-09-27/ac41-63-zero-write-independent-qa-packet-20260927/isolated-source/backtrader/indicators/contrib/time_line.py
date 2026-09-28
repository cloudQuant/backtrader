#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from backtrader.utils.dateintern import num2date

from .. import Indicator

__all__ = [
    "TimeLine",
]


class TimeLine(Indicator):
    """Time average price line indicator

    Calculate the cumulative average of the day's closing prices as the time average price line
    """

    lines = ("day_avg_price",)
    params = (("day_end_time", (15, 0, 0)),)

    def __init__(self):
        """Initialize the TimeLine indicator.

        Creates an empty list to store closing prices for the current day.
        The cumulative average of these prices will be calculated as the
        time average price line.
        """
        self.day_close_price_list = []

    def next(self):
        """Calculate the time average price for the current bar.

        This method is called for each bar in the data series. It:
        1. Appends the current bar's close price to the day's price list
        2. Calculates the cumulative average of all prices in the list
        3. Resets the price list at the end of the trading day

        The time average price line is useful for intraday strategies as it
        represents the average entry price of all market participants throughout
        the day.
        """
        self.day_close_price_list.append(self.data.close[0])
        self.lines.day_avg_price[0] = sum(self.day_close_price_list) / len(
            self.day_close_price_list
        )

        self.current_datetime = num2date(self.data.datetime[0])
        self.current_hour = self.current_datetime.hour
        self.current_minute = self.current_datetime.minute
        day_end_hour, day_end_minute, _ = self.p.day_end_time
        if self.current_hour == day_end_hour and self.current_minute == day_end_minute:
            self.day_close_price_list = []
