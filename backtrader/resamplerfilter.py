#!/usr/bin/env python
"""Resampler and Filter Module - Data resampling and replay functionality.

This module provides classes for resampling data to different timeframes
and replaying data at compressed timeframes. It includes the base
resampler and replayer classes along with specific implementations for
different time periods.

Key Classes:
    Resampler: Base class for resampling data to different timeframes.
    Replayer: Base class for replaying data with session information.
    DTFaker: Provides fake datetime for live/real-time data feeds.

Example:
    Resampling daily data to weekly:
    >>> data = bt.feeds.GenericCSVData(dataname='daily.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.resampledata(data, timeframe=bt.TimeFrame.Weeks)
"""

from datetime import datetime, timedelta, timezone

from .dataseries import TimeFrame, _Bar
from .parameters import ParameterizedBase
from .utils.date import date2num, num2date

# Python 3.11+ has datetime.UTC, earlier versions use timezone.utc
UTC = timezone.utc


# This class is only used in the _checkbarover function
# chkdata = DTFaker(data, forcedata) if fromcheck else data
class DTFaker:
    """Provides fake datetime for data sources that need periodic checks.

    This class is used for real-time data feeds that return None from _load
    to indicate that a check of the resampler and/or notification queue
    is needed. It provides the current time in both UTC and localized formats.

    Attributes:
        data: The underlying data source.
        _dt: UTC-like time as numeric value.
        _dtime: Localized datetime.
        sessionend: Trading day end time.

    Example:
        >>> faker = DTFaker(data)
        >>> print(faker.datetime())  # Current localized time
    """

    # This will only be used for data sources which at some point in time
    # return None from _load to indicate that a check of the resampler and/or
    # notification queue is needed
    # This is meant (at least initially) for real-time feeds, because those are
    # the ones in need of events like the ones described above.
    # These data sources should also be producing ``utc`` time directly because
    # the real-time feed is (more often than not) timestamped and utc provides
    # a universal reference,
    # That's why below the timestamp is chosen in UTC and passed directly to
    # date2num to avoid localization.But it is extracted from data.num2date
    # to ensure the returned datetime object is localized according to the
    # expected output by the user (local timezone or any specified)

    # Initialize
    def __init__(self, data, forcedata=None):
        """Initialize the DTFaker with current time.

        Args:
            data: The underlying data source.
            forcedata: Optional data source to force time from.
        """
        # Data
        self.data = data

        # Aliases
        self.datetime = self
        self.p = self

        # If forcedata is None
        if forcedata is None:
            # Get current utc time and add data time offset
            _dtime = datetime.now(UTC) + data._timeoffset()
            # Convert calculated utc time to number
            self._dt = dt = date2num(_dtime)  # utc-like time
            # Convert numeric time to localized time format
            self._dtime = data.num2date(dt)  # localized time
        # If forcedata is not None
        else:
            # Get corresponding time from forcedata's datetime column as utc time
            self._dt = forcedata.datetime[0]  # utc-like time
            # Get local time directly from forcedata
            self._dtime = forcedata.datetime.datetime()  # localized time
        # Trading day end time
        self.sessionend = data.p.sessionend

    # Length
    def __len__(self):
        return len(self.data)

    # Return localized date and time when called
    def __call__(self, idx=0):
        """Return the localized datetime.

        Args:
            idx: Index (ignored, for compatibility).

        Returns:
            Localized datetime object.
        """
        return self._dtime  # simulates data.datetime.datetime()

    # datetime returns localized date and time
    def datetime(self, idx=0):
        """Return the localized datetime.

        Args:
            idx: Index (ignored, for compatibility).

        Returns:
            Localized datetime object.
        """
        return self._dtime

    # Return localized date
    def date(self, idx=0):
        """Return the localized date.

        Args:
            idx: Index (ignored, for compatibility).

        Returns:
            Date object.
        """
        return self._dtime.date()

    # Return localized time
    def time(self, idx=0):
        """Return the localized time.

        Args:
            idx: Index (ignored, for compatibility).

        Returns:
            Time object.
        """
        return self._dtime.time()

    # Return data calendar
    @property
    def _calendar(self):
        return self.data._calendar

    # If idx=0, return utc numeric time, otherwise return -inf
    def __getitem__(self, idx):
        return self._dt if idx == 0 else float("-inf")

    # Convert number to date and time
    def num2date(self, *args, **kwargs):
        """Convert numeric time to datetime.

        Delegates to the underlying data source's num2date method.

        Returns:
            Datetime object.
        """
        return self.data.num2date(*args, **kwargs)

    # Convert date and time to number
    def date2num(self, *args, **kwargs):
        """Convert datetime to numeric time.

        Delegates to the underlying data source's date2num method.

        Returns:
            Float representing the datetime.
        """
        return self.data.date2num(*args, **kwargs)

    # Get trading day end time
    def _getnexteos(self):
        return self.data._getnexteos()


# Base class for resampler
class _BaseResampler(ParameterizedBase):
    # Parameters
    params = (
        ("bar2edge", True),
        ("adjbartime", True),
        ("rightedge", True),
        ("boundoff", 0),
        ("timeframe", TimeFrame.Days),
        ("compression", 1),
        ("takelate", True),
        ("sessionend", True),
    )

    # Initialize
    def __init__(self, data, **kwargs):
        """Initialize the base resampler.

        Sets up the resampling configuration based on timeframe and
        compression parameters, and modifies the data source accordingly.

        Args:
            data: The data source to resample.
            **kwargs: Additional parameters for the resampler.
        """
        super().__init__(**kwargs)
        # If timeframe is less than day but greater than tick, subdays is True, subdays represents intraday timeframe
        self.subdays = TimeFrame.Ticks < self.p.timeframe < TimeFrame.Days
        # If timeframe is less than week, subweeks is True
        self.subweeks = self.p.timeframe < TimeFrame.Weeks
        # If not subdays, and data timeframe equals parameter timeframe, and parameter compression divided by data compression remainder is 0, componly is True
        self.componly = (
            not self.subdays
            and data._timeframe == self.p.timeframe
            and not (self.p.compression % data._compression)
        )
        # Create an object to save bar data
        self.bar = _Bar(maxdate=True)  # bar holder
        # Number of bars produced, used to control compression count
        self.compcount = 0  # count of produced bars to control compression
        # Whether it is the first bar
        self._firstbar = True
        # If bar2edge, adjbartime, subweeks are all True, doadjusttime is True
        self.doadjusttime = self.p.bar2edge and self.p.adjbartime and self.subweeks
        # The end time of this trading day
        self._nexteos = None

        # Modify data information according to own parameters
        # During initialization, modify data attributes based on parameters
        # Data resampling is 1
        data.resampling = 1
        # replaying equals replaying
        data.replaying = self.replaying
        # Data timeframe equals parameter timeframe
        data._timeframe = self.p.timeframe
        # Data compression equals parameter compression
        data._compression = self.p.compression

        self.data = data

    # How to handle late-arriving data, if not subdays return False, if data length > 1 and current time <= previous time return True
    def _latedata(self, data):
        # new data at position 0, still untouched from stream
        if not self.subdays:
            return False

        # Time already delivered
        return len(data) > 1 and data.datetime[0] <= data.datetime[-1]

    # Whether to check if bar is over
    def _checkbarover(self, data, fromcheck=False, forcedata=None):
        # Data to check, if fromcheck is True, use DTFaker to generate instance, otherwise use data
        chkdata = DTFaker(data, forcedata) if fromcheck else data
        # Whether finished
        isover = False
        # If not componly and _barover(chkdata) is False, return False
        if not self.componly and not self._barover(chkdata):
            return isover
        # If intraday and bar2edge is True, return True
        if self.subdays and self.p.bar2edge:
            isover = True
        # If fromcheck is False
        elif not fromcheck:  # fromcheck doesn't increase compcount
            # compcount+1
            self.compcount += 1
            # If compcount divided by compression equals 0, return True
            if not (self.compcount % self.p.compression):
                # boundary crossed and enough bars for compression ... proceed
                isover = True

        return isover

    # Determine if data has finished
    def _barover(self, data):
        # Timeframe
        tframe = self.p.timeframe
        # If timeframe equals tick, return bar.isopen()
        if tframe == TimeFrame.Ticks:
            # Ticks is already the lowest level
            return self.bar.isopen()
        # If timeframe is less than day, call _barover_subdays(data)
        elif tframe < TimeFrame.Days:
            return self._barover_subdays(data)
        # If timeframe equals day, call _barover_days(data)
        elif tframe == TimeFrame.Days:
            return self._barover_days(data)
        # If timeframe equals week, call _barover_weeks(data)
        elif tframe == TimeFrame.Weeks:
            return self._barover_weeks(data)
        # If timeframe equals month, call _barover_months(data)
        elif tframe == TimeFrame.Months:
            return self._barover_months(data)
        # If timeframe equals year, call _barover_years(data)
        elif tframe == TimeFrame.Years:
            return self._barover_years(data)

    # Set session end time
    def _eosset(self):
        if self._nexteos is None:
            self._nexteos, self._nextdteos = self.data._getnexteos()
            return

    # Check session end time
    def _eoscheck(self, data, seteos=True, exact=False):
        # If seteos is True, directly call _eosset to calculate session end time
        if seteos:
            self._eosset()
        # Compare current data time with session end time
        equal = data.datetime[0] == self._nextdteos
        grter = data.datetime[0] > self._nextdteos
        # If exact is True, ret equals equal,
        # Otherwise, if grter is True, if bar.isopen() is True and bar.datetime < next end time, ret equals True
        # Otherwise, ret equals equal
        if exact:
            ret = equal
        else:
            # if the compared data goes over the endofsession
            # make sure the resampled bar is open and has something before that
            # end of the session, It could be a weekend and nothing was delivered
            # until Monday
            if grter:
                ret = self.bar.isopen() and self.bar.datetime <= self._nextdteos
            else:
                ret = equal
        # If ret is True, _lasteos equals _nexteos, _lastdteos equals _nextdteos
        # And set _nexteos and _nextdteos to None and -inf respectively
        if ret:
            self._lasteos = self._nexteos
            self._lastdteos = self._nextdteos
            self._nexteos = None
            self._nextdteos = float("-inf")

        return ret

    # Check days
    def _barover_days(self, data):
        return self._eoscheck(data)

    # Check weeks
    def _barover_weeks(self, data):
        # If data's _calendar is None
        if self.data._calendar is None:
            # Get specific year, week number and day from date
            year, week, _ = data.num2date(self.bar.datetime).date().isocalendar()
            # Get bar's week number
            yearweek = year * 100 + week
            # Get data's year, week number and day, and get data's week number
            baryear, barweek, _ = data.datetime.date().isocalendar()
            bar_yearweek = baryear * 100 + barweek
            # If data's week number is greater than bar's week number, return True, otherwise return False
            return bar_yearweek > yearweek
        # If data's _calendar is not None, call last_weekday
        else:
            return data._calendar.last_weekday(data.datetime.date())

    # Check months
    def _barover_months(self, data):
        dt = data.num2date(self.bar.datetime).date()
        yearmonth = dt.year * 100 + dt.month

        bardt = data.datetime.datetime()
        bar_yearmonth = bardt.year * 100 + bardt.month

        return bar_yearmonth > yearmonth

    # Check years
    def _barover_years(self, data):
        return data.datetime.datetime().year > data.num2date(self.bar.datetime).year

    # Get time point
    def _gettmpoint(self, tm):
        """
            Returns the point of time intraday for a given time according to the
        timeframe

          - Ex 1: 00:05:00 in minutes -> point = 5
          - Ex 2: 00:05:20 in seconds -> point = 5 * 60 + 20 = 320
        """
        # Minute point
        point = tm.hour * 60 + tm.minute
        # Remaining point
        restpoint = 0
        # If timeframe is less than minutes
        if self.p.timeframe < TimeFrame.Minutes:
            # Second point
            point = point * 60 + tm.second
            # If timeframe is less than seconds
            if self.p.timeframe < TimeFrame.Seconds:
                # Convert point to microseconds
                point = point * 1e6 + tm.microsecond
            # If timeframe is not less than seconds, remaining point is microseconds
            else:
                restpoint = tm.microsecond
        # If timeframe is not less than minutes, remaining point is seconds and microseconds
        else:
            restpoint = tm.second + tm.microsecond
        # Add boundoff to point
        point += self.p.boundoff

        return point, restpoint

    # Intraday bar over
    def _barover_subdays(self, data):
        # If _eoscheck(data) returns True, then function returns True
        if self._eoscheck(data):
            return True
        # If data time is less than bar time, return False
        if data.datetime[0] < self.bar.datetime:
            return False

        # Get time objects for the comparisons - in utc-like format
        # Get bar and data time
        tm = num2date(self.bar.datetime).time()
        bartm = num2date(data.datetime[0]).time()
        # Get self.bar's time point and data's time point respectively
        point, _ = self._gettmpoint(tm)
        barpoint, _ = self._gettmpoint(bartm)
        # Set ret to False
        ret = False
        # If data's time point is less than bar's time point, return False
        # If data's time point is greater than bar's time point, further analyze
        if barpoint > point:
            # The data bar has surpassed the internal bar
            # If bar2edge is False, return True
            if not self.p.bar2edge:
                # Compression done on a simple bar basis (like days)
                ret = True
            # If compression is 1, return True
            elif self.p.compression == 1:
                # no bar compression requested -> internal bar done
                ret = True
            # If bar2edge is True and compression is not 1, calculate remainder of dividing points by compression
            # If data's point remainder is greater than bar's point remainder, return True
            else:
                point_comp = point // self.p.compression
                barpoint_comp = barpoint // self.p.compression

                # Went over boundary including compression
                if barpoint_comp > point_comp:
                    ret = True

        return ret

    # Check whether to submit currently stored bar when data hasn't moved forward
    def check(self, data, _forcedata=None):
        """Called to check if the current stored bar has to be delivered in
        spite of the data not having moved forward. If no ticks from a live
        feed come in, a 5-second resampled bar could be delivered 20 seconds
        later. When this method is called the wall clock (incl data time
        offset) is called to check if the time has gone so far as to have to
        deliver the already stored data
        """
        if not self.bar.isopen():
            return

        return self(data, fromcheck=True, forcedata=_forcedata)

    # Determine if data is about to form a bar
    def _dataonedge(self, data):
        # If subweek is False, if data._calendar is None, return False and True
        if not self.subweeks:
            if data._calendar is None:
                return False, True  # nothing can be done
            # Timeframe
            tframe = self.p.timeframe
            # Set ret to False
            ret = False
            # If timeframe equals week, call last_weekday to check
            # If timeframe equals month, call last_monthday to check
            # If timeframe equals year, call last_yearday to check
            if tframe == TimeFrame.Weeks:  # Ticks is already the lowest
                ret = data._calendar.last_weekday(data.datetime.date())
            elif tframe == TimeFrame.Months:
                ret = data._calendar.last_monthday(data.datetime.date())
            elif tframe == TimeFrame.Years:
                ret = data._calendar.last_yearday(data.datetime.date())
            # If ret is True
            if ret:
                # Data must be consumed but compression may not be met yet
                # Prevent barcheckover from being called because it could again
                # increase compcount
                # Set docheckover to False
                docheckover = False
                # compcount+1
                self.compcount += 1
                # If compcount divided by compression remainder equals 0, return True, otherwise return False
                ret = not (self.compcount % self.p.compression)
            # If ret equals False, docheckover equals True
            else:
                docheckover = True
            # Return ret, docheckover
            return ret, docheckover
        # _eoscheck check, return two True
        if self._eoscheck(data, exact=True):
            return True, True
        # If intraday
        if self.subdays:
            # Get data's point and remaining point
            point, prest = self._gettmpoint(data.datetime.time())
            # If remaining point is not 0, return False and True
            if prest:
                return False, True  # cannot be on boundary, subunits present

            # Pass through compression to get boundary and rest over boundary
            # Calculate boundary and remaining boundary
            bound, brest = divmod(point, self.p.compression)

            # if no extra and decomp bound is point
            # If divmod result remainder is 0, return two True
            return brest == 0 and point == (bound * self.p.compression), True

        # Code overriden by eoscheck
        # This code will not run
        if False and self.p.sessionend:
            # Days scenario - get datetime to compare in output timezone
            # because p.sessionend is expected in output timezone
            bdtime = data.datetime.datetime()
            bsend = datetime.combine(bdtime.date(), data.p.sessionend)
            return bdtime == bsend
        # If none of above reached return, return False, True
        return False, True  # subweeks, not subdays and not sessionend

    # Calculate adjusted time
    def _calcadjtime(self, greater=False):
        if self._nexteos is None:
            # Session has been exceeded - end of session is the mark
            return self._lastdteos  # utc-like

        dt = self.data.num2date(self.bar.datetime)

        # Get current time
        tm = dt.time()
        # Get the point of the day in the time frame unit (ex: minute 200)
        point, _ = self._gettmpoint(tm)

        # Apply compression to update the point position (comp 5 -> 200 // 5)
        # point = (point // self.p.compression)
        point = point // self.p.compression

        # If rightedge (end of boundary is activated) add it unless recursing
        point += self.p.rightedge

        # Restore point to the timeframe units by de-applying compression
        point *= self.p.compression

        # Get hours, minutes, seconds and microseconds
        extradays = 0
        if self.p.timeframe == TimeFrame.Minutes:
            ph, pm = divmod(point, 60)
            ps = 0
            pus = 0
        elif self.p.timeframe == TimeFrame.Seconds:
            ph, pm = divmod(point, 60 * 60)
            pm, ps = divmod(pm, 60)
            pus = 0
        elif self.p.timeframe <= TimeFrame.MicroSeconds:
            ph, pm = divmod(point, 60 * 60 * 1e6)
            pm, psec = divmod(pm, 60 * 1e6)
            ps, pus = divmod(psec, 1e6)
        elif self.p.timeframe == TimeFrame.Days:
            # last resort
            eost = self._nexteos.time()
            ph = eost.hour
            pm = eost.minute
            ps = eost.second
            pus = eost.microsecond

        if ph > 23:  # went over midnight:
            extradays = ph // 24
            ph %= 24

        # Replace intraday parts with the calculated ones and update it
        dt = dt.replace(hour=int(ph), minute=int(pm), second=int(ps), microsecond=int(pus))
        if extradays:
            dt += timedelta(days=extradays)
        dtnum = self.data.date2num(dt)
        return dtnum

    # Adjust bar time
    def _adjusttime(self, greater=False, forcedata=None):
        """
        Adjusts the time of calculated bar (from the underlying data source) by
        using the timeframe to the appropriate boundary, with compression taken
        into account

        Depending on param ``rightedge`` uses the starting boundary or the
        ending one
        """

        dtnum = self._calcadjtime(greater=greater)
        if greater and dtnum <= self.bar.datetime:
            return False

        self.bar.datetime = dtnum
        return True


# Resample small period data to form large period data
class Resampler(_BaseResampler):
    """This class resamples data of a given timeframe to a larger timeframe.

    Params

      - Bar2edge (default: True)

        Resamples using time boundaries as the target.For example, with a
        "ticks -> 5 seconds" the resulting 5-seconds bars will be aligned to
        xx:00, xx:05, xx:10 ...

        # When resampling, use time boundary as target, for example if ticks data wants to resample to 5 seconds, bars will be formed at xx:00, xx:05, xx:10

      - Adjbartime (default: True)

        Use the time at the boundary to adjust the time of the delivered
        resampled bar instead of the last seen timestamp. If resampling to "5
        seconds" the time of the bar will be adjusted, for example, to hh:mm:05
        even if the last seen timestamp was hh:mm:04.33

        :note::

           Time will only be adjusted if "bar2edge" is True. It wouldn't make
           sense to adjust the time if the bar has not been aligned to a
           boundary
        # Adjust the last bar's final time, when bar2edge is True, use the final boundary as the last bar's time

      - Rightedge (default: True)

        Use the right edge of the time boundaries to set the time.

        If False and compressing to 5 seconds, the time of a resampled bar for
        seconds between hh:mm:00 and hh:mm:04 will be hh:mm:00 (the starting
        boundary

        If True, the used boundary for the time will be hh:mm:05 (the ending
        boundary)
        # Whether to use the right time boundary, for example if time boundary is hh:mm:00:hh:mm:05, if set to True, will use hh:mm:05
        # Set to False, will use hh:mm:00
    """

    # Parameters
    params = (
        ("bar2edge", True),
        ("adjbartime", True),
        ("rightedge", True),
    )

    replaying = False

    # Called when data no longer produces bars, can be called multiple times, has chance to produce extra bars when must deliver bar
    def last(self, data):
        """Called when the data is no longer producing bars

        Can be called multiple times. It has the chance to (for example)
        produce extra bars which may still be accumulated and have to be
        delivered
        """
        if self.bar.isopen():
            if self.doadjusttime:
                self._adjusttime()

            data._add2stack(self.bar.lvalues())
            self.bar.bstart(maxdate=True)  # close the bar to avoid dups
            return True

        return False

    # Used when calling resampler
    def __call__(self, data, fromcheck=False, forcedata=None):
        """Called for each set of values produced by the data source"""
        consumed = False
        onedge = False
        docheckover = True
        if not fromcheck:
            if self._latedata(data):
                if not self.p.takelate:
                    data.backwards()
                    return True  # get a new bar

                self.bar.bupdate(data)  # update new or existing bar
                # push time beyond reference
                self.bar.datetime = data.datetime[-1] + 0.000001
                data.backwards()  # remove used bar
                return True

            if self.componly:  # only if not subdays
                # Get a session ref before rewinding
                _, self._lastdteos = self.data._getnexteos()
                consumed = True

            else:
                onedge, docheckover = self._dataonedge(data)  # for subdays
                consumed = onedge

        if consumed:
            self.bar.bupdate(data)  # update new or existing bar
            data.backwards()  # remove used bar

        # if self.bar.isopen and (onedge or (docheckover and checkbarover))
        cond = self.bar.isopen()
        if cond:  # original is and, the 2nd term must also be true
            if not onedge:  # onedge true is sufficient
                if docheckover:
                    cond = self._checkbarover(data, fromcheck=fromcheck, forcedata=forcedata)
        if cond:
            dodeliver = False
            if forcedata is not None:
                # check our delivery time is not larger than that of forcedata
                tframe = self.p.timeframe
                if tframe == TimeFrame.Ticks:  # Ticks is already the lowest
                    dodeliver = True
                elif tframe == TimeFrame.Minutes:
                    dtnum = self._calcadjtime(greater=True)
                    dodeliver = dtnum <= forcedata.datetime[0]
                elif tframe == TimeFrame.Days:
                    dtnum = self._calcadjtime(greater=True)
                    dodeliver = dtnum <= forcedata.datetime[0]
            else:
                dodeliver = True

            if dodeliver:
                if not onedge and self.doadjusttime:
                    self._adjusttime(greater=True, forcedata=forcedata)

                data._add2stack(self.bar.lvalues())
                self.bar.bstart(maxdate=True)  # bar delivered -> restart

        if not fromcheck:
            if not consumed:
                self.bar.bupdate(data)  # update new or existing bar
                data.backwards()  # remove used bar

        return True


# Replayer class
class Replayer(_BaseResampler):
    """This class replays data of a given timeframe to a larger timeframe.

    It simulates the action of the market by slowly building up (for ex.) a
    daily bar from tick/seconds/minutes data

    Only when the bar is complete will the "length" of the data be changed
    effectively delivering a closed bar

    Params

      - Bar2edge (default: True)

        Replays using time boundaries as the target of the closed bar.For
        example, with a "ticks -> 5 seconds" the resulting 5-second bars will
        be aligned to xx:00, xx:05, xx:10 ...

      - Adjbartime (default: False)

        Use the time at the boundary to adjust the time of the delivered
        resampled bar instead of the last seen timestamp. If resampling to "5
        seconds" the time of the bar will be adjusted, for example, to hh:mm:05
        even if the last seen timestamp was hh:mm:04.33

        *Note*

           Time will only be adjusted if "bar2edge" is True. It wouldn't make
           sense to adjust the time if the bar has not been aligned to a
           boundary

        *Note* if this parameter is True, an extra tick with the *adjusted*
                  time will be introduced at the end of the *replayed* bar

      - Rightedge (default: True)

        Use the right edge of the time boundaries to set the time.

        If False and compressing to 5 seconds, the time of a resampled bar for
        seconds between hh:mm:00 and hh:mm:04 will be hh:mm:00 (the starting
        boundary

        If True, the used boundary for the time will be hh:mm:05 (the ending
        boundary)
    """

    params = (
        ("bar2edge", True),
        ("adjbartime", False),
        ("rightedge", True),
    )

    replaying = True

    # Run when calling class
    def __call__(self, data, fromcheck=False, forcedata=None):
        """Process the data for replaying.

        Manages bar replaying with session information and time alignment.

        Args:
            data: The data source to replay.
            fromcheck: Whether this is being called from a periodic check.
            forcedata: Optional data source to force timing from.

        Returns:
            bool: True if a new bar was generated, False otherwise.
        """
        # Consume
        consumed = False
        # At bar generation time point
        onedge = False
        # Late-arriving data
        takinglate = False
        # Whether to check bar end
        docheckover = True
        # If fromcheck is False
        if not fromcheck:
            # Call _latedata to see how to handle late data, if returns True
            if self._latedata(data):
                # If takelate is False, generate a new bar
                if not self.p.takelate:
                    data.backwards(force=True)
                    return True  # get a new bar
                # Set these two parameters
                consumed = True
                takinglate = True
            # If not intraday
            elif self.componly:  # only if not subdays
                consumed = True

            else:
                # Call _dataonedge to determine if at bar generation time and if bar is over
                onedge, docheckover = self._dataonedge(data)  # for subdays
                consumed = onedge

            data._tick_fill(force=True)  # update
        # If consumed is True, update data, if takinglate is True, set a new time for bar
        if consumed:
            self.bar.bupdate(data)
            if takinglate:
                self.bar.datetime = data.datetime[-1] + 0.000001

        # if onedge or (checkbarover and self._checkbarover)
        cond = onedge
        # If currently not at bar generation time point, if check is needed, need to check if bar is over
        if not cond:  # original is or, if true, it would suffice
            if docheckover:
                cond = self._checkbarover(data, fromcheck=fromcheck)
        # If check result returns True
        if cond:
            # If not exactly at bar generation time and need to adjust time
            if not onedge and self.doadjusttime:  # insert tick with adjtime
                adjusted = self._adjusttime(greater=True)
                # If adjustment is needed, adjust time and update bar
                if adjusted:
                    ago = 0 if (consumed or fromcheck) else -1
                    # Update to the point right before the new data
                    data._updatebar(self.bar.lvalues(), forward=False, ago=ago)
                # If no check needed
                if not fromcheck:
                    # If not in consume mode, use _save2stack to save data
                    if not consumed:
                        # Reopen bar with real new data and save data to queue
                        self.bar.bupdate(data, reopen=True)
                        # erase is True, but the tick will not be seen below
                        # and therefore no need to mark as 1st
                        data._save2stack(erase=True, force=True)
                    # If in consume mode, data starts, next bar is first bar
                    else:
                        self.bar.bstart(maxdate=True)
                        self._firstbar = True  # next is first
                # If check is needed
                else:  # from check
                    # fromcheck or consumed have forced delivery, reopen
                    self.bar.bstart(maxdate=True)
                    self._firstbar = True  # next is first
                    if adjusted:
                        # after adjusting need to redeliver if this was a check
                        data._save2stack(erase=True, force=True)
            # If no check needed
            elif not fromcheck:
                if not consumed:
                    # Data already "forwarded" and we replay to new bar
                    # No need to go backwards.reopen the internal cache
                    self.bar.bupdate(data, reopen=True)
                else:
                    # compression only, used data to update bar, hence remove
                    # from stream, update existing data, reopen bar
                    if not self._firstbar:  # only discard data if not firstbar
                        data.backwards(force=True)
                    data._updatebar(self.bar.lvalues(), forward=False, ago=0)
                    self.bar.bstart(maxdate=True)
                    self._firstbar = True  # make sure the next tick moves forward
        # If no check needed
        elif not fromcheck:
            # not over, update, remove new entry, deliver
            if not consumed:
                self.bar.bupdate(data)

            if not self._firstbar:  # only discard data if not firstbar
                data.backwards(force=True)

            data._updatebar(self.bar.lvalues(), forward=False, ago=0)
            self._firstbar = False

        return False  # the system can process the existing bar


class ResamplerTicks(Resampler):
    """Resampler for tick-level data."""

    params = (("timeframe", TimeFrame.Ticks),)


class ResamplerSeconds(Resampler):
    """Resampler for seconds-level data."""

    params = (("timeframe", TimeFrame.Seconds),)


class ResamplerMinutes(Resampler):
    """Resampler for minute-level data."""

    params = (("timeframe", TimeFrame.Minutes),)


class ResamplerDaily(Resampler):
    """Resampler for daily data."""

    params = (("timeframe", TimeFrame.Days),)


class ResamplerWeekly(Resampler):
    """Resampler for weekly data."""

    params = (("timeframe", TimeFrame.Weeks),)


class ResamplerMonthly(Resampler):
    """Resampler for monthly data."""

    params = (("timeframe", TimeFrame.Months),)


class ResamplerYearly(Resampler):
    """Resampler for yearly data."""

    params = (("timeframe", TimeFrame.Years),)


class ReplayerTicks(Replayer):
    """Replayer for tick-level data."""

    params = (("timeframe", TimeFrame.Ticks),)


class ReplayerSeconds(Replayer):
    """Replayer for seconds-level data."""

    params = (("timeframe", TimeFrame.Seconds),)


class ReplayerMinutes(Replayer):
    """Replayer for minute-level data."""

    params = (("timeframe", TimeFrame.Minutes),)


class ReplayerDaily(Replayer):
    """Replayer for daily data."""

    params = (("timeframe", TimeFrame.Days),)


class ReplayerWeekly(Replayer):
    """Replayer for weekly data."""

    params = (("timeframe", TimeFrame.Weeks),)


class ReplayerMonthly(Replayer):
    """Replayer for monthly data."""

    params = (("timeframe", TimeFrame.Months),)
