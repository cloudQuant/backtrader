#!/usr/bin/env python
"""Calendar Days Filter Module - Calendar day filling.

This module provides the CalendarDays filter for adding missing
calendar days to trading day data.

Classes:
    CalendarDays: Fills missing calendar days.

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> data.addfilter(bt.filters.CalendarDays())
    >>> cerebro.adddata(data)
"""

from datetime import date, datetime, timedelta

from ..parameters import ParameterizedBase


class CalendarDays(ParameterizedBase):
    """
    Bar Filler to add missing calendar days to trading days

    Params:

      - fill_price (def: None):

        > 0: The given value to fill
        0 or None: Use the last known closing price
        -1: Use the midpoint of the last bar (High-Low average)

      - fill_vol (def: float('NaN')):

        Value to use to fill the missing volume

      - fill_oi (def: float('NaN')):

        Value to use to fill the missing Open Interest
    """

    params = (
        ("fill_price", None),
        ("fill_vol", float("NaN")),
        ("fill_oi", float("NaN")),
    )

    ONEDAY = timedelta(days=1)
    lastdt = date.max

    def __init__(self, data, **kwargs):
        """Initialize the CalendarDays filter.

        Args:
            data: The data feed to apply the filter to.
            **kwargs: Additional keyword arguments passed to parent class.
        """
        super().__init__(**kwargs)

    def __call__(self, data):
        """
        If the data has a gap larger than 1 day amongst bars, the missing bars
        are added to the stream.

        Params:
          - data: the data source to filter/process

        Returns:
          - False (always): this filter does not remove bars from the stream

        """
        dt = data.datetime.date()
        if (dt - self.lastdt) > self.ONEDAY:  # gap in place
            self._fillbars(data, dt, self.lastdt)

        self.lastdt = dt
        return False  # no bar has been removed from the stream

    def _fillbars(self, data, dt, lastdt):
        """
        Fills one by one bars as needed from time_start to time_end

        Invalidates the control dtime_prev if requested
        """
        tm = data.datetime.time(0)  # get time part

        # Same price for all bars
        if self.p.fill_price > 0:
            price = self.p.fill_price
        elif not self.p.fill_price:
            price = data.close[-1]
        elif self.p.fill_price == -1:
            price = (data.high[-1] + data.low[-1]) / 2.0

        while lastdt < dt:
            lastdt += self.ONEDAY

            # Prepare an array of the necessary size
            bar = [float("Nan")] * data.size()
            # Fill the datetime
            bar[data.DateTime] = data.date2num(datetime.combine(lastdt, tm))

            # Fill price fields
            for pricetype in [data.Open, data.High, data.Low, data.Close]:
                bar[pricetype] = price

            # Fill volume and open interest
            bar[data.Volume] = self.p.fill_vol
            bar[data.OpenInterest] = self.p.fill_oi

            # Fill extra lines the data feed may have defined beyond DateTime
            for i in range(data.DateTime + 1, data.size()):
                bar[i] = data.lines[i][0]

            # Add this constructed bar to the stack of the stream
            data._add2stack(bar)

        # Save to stack the bar that signaled the gap
        data._save2stack(erase=True)
