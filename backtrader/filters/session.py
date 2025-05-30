#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from datetime import datetime, timedelta

from backtrader import TimeFrame
from .. import metabase


class SessionFiller(metaclass=metabase.MetaParams):
    """
    Bar Filler for a Data Source inside the declared session start/end times.

    The fill bars are constructed using the declared Data Source ``timeframe``
    and ``compression`` (used to calculate the intervening missing times)

    Params:

      - Fill_price (def: None):

        If None is passed, the closing price of the previous bar will be
        used.
        To end up with a bar which, for example, takes time, but it is not
        displayed in a plot ... use float('Nan')

      - Fill_vol (def: float('NaN')):

        Value to use to fill the missing volume

      - Fill_oi (def: float('NaN')):

        Value to use to fill the missing Open Interest

      - Skip_first_fill (def: True):

        Upon seeing the 1st valid bar do not fill from the sessionstart up to
        that bar
    """

    params = (
        ("fill_price", None),
        ("fill_vol", float("NaN")),
        ("fill_oi", float("NaN")),
        ("skip_first_fill", True),
    )

    MAXDATE = datetime.max

    # Minimum delta unit in between bars
    _tdeltas = {
        TimeFrame.Minutes: timedelta(seconds=60),
        TimeFrame.Seconds: timedelta(seconds=1),
        TimeFrame.MicroSeconds: timedelta(microseconds=1),
    }

    def __init__(self, data):
        # Calculate and save timedelta for timeframe
        self._tdframe = self._tdeltas[data._timeframe]
        self._tdunit = self._tdeltas[data._timeframe] * data._compression

        self.seenbar = False  # control if at least one bar has been seen
        self.sessend = self.MAXDATE  # maxdate is the control for session bar

    def __call__(self, data):
        """
        Params:
          - data: the data source to filter/process

        Returns:
          - False (always) because this filter does not remove bars from the
        stream

        The logic (starting with a session end control flag of MAXDATE)

          - If new bar is over session end (never true for 1st bar)

            Fill up to the session end.
            Reset sessionend to MAXDATE & fall through

          - If the session end is flagged as MAXDATE

            Recalculate session limits and check whether the bar is within them

            If so, fill up and record the last seen tim

          - Else ... the incoming bar is in the session, fill up to it
        """
        # Get time of current (from a data source) bar
        ret = False

        dtime_cur = data.datetime.datetime()

        if dtime_cur > self.sessend:
            # bar over session end - fill up and invalidate
            # Do not put current bar in stack to let it be evaluated below
            # Fill up to endsession + the smallest unit of timeframe
            ret = self._fillbars(data, self.dtime_prev, self.sessend + self._tdframe, tostack=False)
            self.sessend = self.MAXDATE

        # Fall through from previous check ... the bar which is over the
        # session could already be in a new session and within the limits
        if self.sessend == self.MAXDATE:
            # No bar seen yet or one went over the previous session limit
            ddate = dtime_cur.date()
            sessstart = datetime.combine(ddate, data.p.sessionstart)
            self.sessend = sessend = datetime.combine(ddate, data.p.sessionend)

            if sessstart <= dtime_cur <= sessend:
                # 1st bar from session in the session - fill from session start
                if self.seenbar or not self.p.skip_first_fill:
                    ret = self._fillbars(data, sessstart - self._tdunit, dtime_cur)

            self.seenbar = True
            self.dtime_prev = dtime_cur

        else:
            # Seen a previous bar, and this is in the session - fill up to it
            ret = self._fillbars(data, self.dtime_prev, dtime_cur)
            self.dtime_prev = dtime_cur

        return ret

    def _fillbars(self, data, time_start, time_end, tostack=True):
        """
        Fills one by one bars as needed from time_start to time_end

        Invalidates the control dtime_prev if requested
        """
        # Control flag - bars added to the stack
        dirty = 0

        time_start += self._tdunit
        while time_start < time_end:
            dirty += self._fillbar(data, time_start)
            time_start += self._tdunit

        if dirty and tostack:
            data._save2stack(erase=True)

        return bool(dirty) or not tostack

    def _fillbar(self, data, dtime):
        # Prepare an array of the necessary size
        bar = [float("Nan")] * data.size()

        # Fill datetime
        bar[data.DateTime] = data.date2num(dtime)

        # Fill the prices
        price = self.p.fill_price or data.close[-1]
        for pricetype in [data.Open, data.High, data.Low, data.Close]:
            bar[pricetype] = price

        # Fill volume and open interest
        bar[data.Volume] = self.p.fill_vol
        bar[data.OpenInterest] = self.p.fill_oi

        # Fill extra lines the data feed may have defined beyond DateTime
        for i in range(data.DateTime + 1, data.size()):
            bar[i] = data.lines[i][0]

        # Add to the stack of bars to save
        data._add2stack(bar)

        return True


class SessionFilterSimple(metaclass=metabase.MetaParams):
    """
    This class can be applied to a data source as a filter and will filter out
    intraday bars which fall outside the regular session times (ie: pre/post
    market data)

    This is a "simple" filter and must NOT manage the stack of the data (passed
    during init and __call__)

    It needs no "last" method because it has nothing to deliver

    Bar Management will be done by the SimpleFilterWrapper class made which is
    added durint the DataBase.addfilter_simple call
    """

    def __init__(self, data):
        pass

    def __call__(self, data):
        """
        Return Values:

          - False: nothing to filter
          - True: filter current bar (because it's not in the session times)
        """
        # Both ends of the comparison are in the session
        return not (data.p.sessionstart <= data.datetime.time(0) <= data.p.sessionend)


class SessionFilter(metaclass=metabase.MetaParams):
    """
    This class can be applied to a data source as a filter and will filter out
    intraday bars which fall outside the regular session times (ie: pre/post
    market data)

    This is a "non-simple" filter and must manage the stack of the data (passed
    during init and __call__)

    It needs no "last" method because it has nothing to deliver
    """

    def __init__(self, data):
        pass

    def __call__(self, data):
        """
        Return Values:

          - False: data stream was not touched
          - True: data stream was manipulated (bar outside session times and
          - removed)
        """
        if data.p.sessionstart <= data.datetime.time(0) <= data.p.sessionend:
            # Both ends of the comparison are in the session
            return False  # say the stream is untouched

        # bar outside the regular session times
        data.backwards()  # remove bar from data stack
        return True  # the signal the data was manipulated
