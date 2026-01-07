#!/usr/bin/env python
"""Data Feed Module - Financial data feed implementations.

This module provides the base classes and implementations for data feeds
in backtrader. Data feeds are the source of price/volume data for strategies
and indicators.

Key Classes:
    AbstractDataBase: Base class for all data feeds with core functionality.
    DataBase: Full-featured data feed with replay/resample support.
    CSVDataBase: Base class for CSV file data feeds.
    FeedBase: Base for live/real-time data feeds.

Data feeds provide:
    - OHLCV (Open, High, Low, Close, Volume) data
    - Timeline management and session handling
    - Replay and resampling capabilities
    - Live data support for trading

Example:
    Creating a custom data feed:
    >>> class MyDataFeed(CSVDataBase):
    ...     params = (('dataname', 'data.csv'),)
"""
import collections
import datetime
import inspect
import os.path

from . import dataseries
from .dataseries import SimpleFilterWrapper, TimeFrame
from .resamplerfilter import Replayer, Resampler
from .tradingcal import PandasMarketCalendar
from .utils import date2num, num2date, time2num, tzparse
from .utils.date import Localizer
from .utils.py3 import range, string_types, zip


# Refactor: Remove metaclass, use normal class and initialization method
class AbstractDataBase(dataseries.OHLCDateTime):
    """Base class for all data feed implementations.

    Provides the core functionality for data feeds including:
    - Data loading and preprocessing
    - Timeline management
    - Session handling
    - Live data support
    - Notification system for data status changes

    States:
        CONNECTED, DISCONNECTED, CONNBROKEN, DELAYED, LIVE,
        NOTSUBSCRIBED, NOTSUPPORTED_TF, UNKNOWN

    Params:
        dataname: Data source identifier (filename, URL, etc.).
        name: Display name for the data feed.
        compression: Timeframe compression factor.
        timeframe: TimeFrame period (Days, Minutes, etc.).
        fromdate: Start date for data filtering.
        todate: End date for data filtering.
        sessionstart: Session start time.
        sessionend: Session end time.
        filters: List of data filters to apply.
        tz: Output timezone.
        tzinput: Input timezone.
        qcheck: Timeout in seconds for live event checking.
        calendar: Trading calendar to use.

    Example:
        >>> data = AbstractDataBase(dataname='data.csv')
        >>> cerebro.adddata(data)
    """

    # Class-level registry dictionary, replacing metaclass _indcol functionality
    _registry = {}

    # Parameter initialization settings - use _params_tuple to save original definition
    _params_tuple = (
        ("dataname", None),
        ("name", ""),
        ("compression", 1),
        ("timeframe", TimeFrame.Days),
        ("fromdate", None),
        ("todate", None),
        ("sessionstart", None),
        ("sessionend", None),
        ("filters", []),
        ("tz", None),
        ("tzinput", None),
        ("qcheck", 0.0),  # timeout in seconds (float) to check for events
        ("calendar", None),
    )

    # Keep original params definition for compatibility with metaclass system
    params = _params_tuple

    # Eight different states of data
    (
        CONNECTED,
        DISCONNECTED,
        CONNBROKEN,
        DELAYED,
        LIVE,
        NOTSUBSCRIBED,
        NOTSUPPORTED_TF,
        UNKNOWN,
    ) = range(8)

    # Notification names
    _NOTIFNAMES = [
        "CONNECTED",
        "DISCONNECTED",
        "CONNBROKEN",
        "DELAYED",
        "LIVE",
        "NOTSUBSCRIBED",
        "NOTSUPPORTED_TIMEFRAME",
        "UNKNOWN",
    ]

    def __init__(self, *args, **kwargs):
        # Execute the original metaclass dopreinit functionality
        self._init_preinit(*args, **kwargs)

        # Call parent class initialization
        super().__init__(*args, **kwargs)

        # Execute the original metaclass dopostinit functionality
        self._init_postinit(*args, **kwargs)

        # CRITICAL FIX: Mark all lines as belonging to a data feed
        # This must be done AFTER _init_postinit to ensure lines are fully initialized
        # This allows LineSeries.__getitem__ and LineBuffer.__getitem__ to correctly
        # raise IndexError when accessing out-of-range indices
        # This is essential for expire_order_close() to detect insufficient data
        if hasattr(self, "lines") and self.lines is not None:
            try:
                for line in self.lines:
                    if hasattr(line, "__dict__"):
                        line._is_data_feed_line = True
            except Exception:
                pass

        # CRITICAL FIX: Also explicitly mark the datetime line
        # The datetime line might be accessed separately (e.g., self.datas[0].datetime)
        # and needs to raise IndexError when accessing out of bounds
        if hasattr(self, "datetime") and self.datetime is not None:
            try:
                if hasattr(self.datetime, "__dict__"):
                    self.datetime._is_data_feed_line = True
            except Exception:
                pass

        # Original content from __init__
        self._env = None
        self._barstash = None
        self._barstack = None
        self._laststatus = None

    def _init_preinit(self, *args, **kwargs):
        """Replace the original MetaAbstractDataBase.dopreinit"""
        # Find the owner and store it
        self._feed = self._find_feed_owner()
        # Initialize a queue to store notifications from cerebro
        self.notifs = collections.deque()  # store notifications for cerebro
        # Get _dataname value from parameters
        self._dataname = getattr(self.p, "dataname", None)
        # Default _name attribute is empty
        self._name = ""

    def _init_postinit(self, *args, **kwargs):
        """Replace the original MetaAbstractDataBase.dopostinit"""
        # Debug: check parameter state at the beginning
        # print(f"_init_postinit start: self.p.dataname = {getattr(self.p, 'dataname', 'NO_P_ATTR')}")
        # print(f"_init_postinit kwargs: {kwargs}")

        # Either set by subclass or the parameter or use the dataname (ticker)
        # Reset _name attribute, if _name is not empty, keep it; if empty, set it to name parameter value
        self._name = self._name or getattr(self.p, "name", "")
        # If _name attribute value is still empty and dataname parameter value is string, set _name to dataname value
        if not self._name and isinstance(getattr(self.p, "dataname", None), string_types):
            self._name = self.p.dataname
        # _compression value equals the compression parameter value
        self._compression = getattr(self.p, "compression", 1)
        # _timeframe value equals the timeframe parameter value
        self._timeframe = getattr(self.p, "timeframe", TimeFrame.Days)

        # Only set sessionstart/sessionend defaults if they weren't explicitly passed
        # If start time is datetime format, equals specific time from sessionstart; if None, equals minimum time
        sessionstart = getattr(self.p, "sessionstart", None)
        if isinstance(sessionstart, datetime.datetime):
            self.p.sessionstart = sessionstart.time()
        elif sessionstart is None:
            # CRITICAL FIX: Always set default if None (kwargs check was unreliable)
            self.p.sessionstart = datetime.time.min

        # If end time is datetime format, equals specific time from sessionend; if None, equals 23:59:59.999990
        sessionend = getattr(self.p, "sessionend", None)
        if isinstance(sessionend, datetime.datetime):
            self.p.sessionend = sessionend.time()
        elif sessionend is None:
            # CRITICAL FIX: Always set default if None (kwargs check was unreliable)
            # remove 9 to avoid precision rounding errors
            self.p.sessionend = datetime.time(23, 59, 59, 999990)

        # Debug: check parameter state after modification
        # print(f"_init_postinit end: self.p.dataname = {getattr(self.p, 'dataname', 'NO_P_ATTR')}")

        # If start date is date format and has no hour attribute, add sessionstart time to convert start date to date+time format
        fromdate = getattr(self.p, "fromdate", None)
        if isinstance(fromdate, datetime.date):
            # push it to the end of the day, or else intraday
            # values before the end of the day would be gone
            if not hasattr(fromdate, "hour"):
                self.p.fromdate = datetime.datetime.combine(fromdate, self.p.sessionstart)

        # If end date is date format and has no hour attribute, add sessionend time to convert start date to date+time format
        todate = getattr(self.p, "todate", None)
        if isinstance(todate, datetime.date):
            # push it to the end of the day, or else intraday
            # values before the end of the day would be gone
            if not hasattr(todate, "hour"):
                self.p.todate = datetime.datetime.combine(todate, self.p.sessionend)

        # Set _barstack and _barstash as queues for filter operations
        self._barstack = collections.deque()  # for filter operations
        self._barstash = collections.deque()  # for filter operations
        # Set _filters and _ffilters as empty lists
        self._filters = list()
        self._ffilters = list()

        # Iterate through filters in parameters, first check if it's a class; if class, instantiate first; if instance has last attribute, add filter to _ffilters
        # If not a class, directly add filter to _filters
        filters = getattr(self.p, "filters", [])
        for fp in filters:
            if inspect.isclass(fp):
                fp = fp(self)
                if hasattr(fp, "last"):
                    self._ffilters.append((fp, [], {}))

            self._filters.append((fp, [], {}))

    def _find_feed_owner(self):
        """Replace the original metabase.findowner functionality"""
        import sys

        # Simplified owner lookup logic, find FeedBase instance in actual call stack
        for frame_level in range(2, 10):  # Limit search depth
            try:
                frame = sys._getframe(frame_level)
                self_obj = frame.f_locals.get("self", None)
                if self_obj is not None and hasattr(self_obj, "__class__"):
                    # Check if it's a FeedBase instance (using string check here to avoid circular import)
                    if "FeedBase" in str(type(self_obj)):
                        return self_obj
                obj = frame.f_locals.get("_obj", None)
                if obj is not None and hasattr(obj, "__class__"):
                    if "FeedBase" in str(type(obj)):
                        return obj
            except ValueError:
                break
        return None

    @classmethod
    def _getstatusname(cls, status):
        return cls._NOTIFNAMES[status]

    # Initialize the following variables, may be used in live trading
    _compensate = None
    _feed = None
    _store = None

    _clone = False
    _qcheck = 0.0

    # Time offset
    _tmoffset = datetime.timedelta()

    # Set to non 0 if resampling/replaying
    # Whether resampling or replaying, if not, set to 0
    resampling = 0
    replaying = 0

    # Whether started
    _started = False

    def _start_finish(self):
        # A live feed (for example) may have learnt something about the
        # timezones after the start, and that's why the date/time related
        # parameters are converted at this late stage
        # Get the output timezone (if any)
        # Get specific timezone
        self._tz = self._gettz()
        # Lines have already been created, set the tz
        # Set specific timezone for time
        self.lines.datetime._settz(self._tz)

        # This should probably be also called from an override-able method
        # Localize input timezone
        self._tzinput = Localizer(self._gettzinput())

        # Convert user input times to the output timezone (or min/max)
        # Convert user input start and end times to specific numbers; if None, start time is negative infinity, end time is positive infinity
        # If specific time, use date2num to convert to specific number
        if self.p.fromdate is None:
            self.fromdate = float("-inf")
        else:
            self.fromdate = self.date2num(self.p.fromdate)

        if self.p.todate is None:
            self.todate = float("inf")
        else:
            self.todate = self.date2num(self.p.todate)

        # FIXME: These two are never used and could be removed
        # These two are not used and can be deleted
        self.sessionstart = time2num(self.p.sessionstart)
        self.sessionend = time2num(self.p.sessionend)

        # Get calendar from parameters; if calendar is None, look for _tradingcal in local environment; if string, use PandasMarketCalendar
        self._calendar = cal = self.p.calendar
        if cal is None:
            self._calendar = self._env._tradingcal if self._env else None
        elif isinstance(cal, string_types):
            self._calendar = PandasMarketCalendar(calendar=cal)
        # Start state
        self._started = True

    def _start(self):
        self.start()
        # If not in start state yet, initialize first, then enter start state
        if not self._started:
            self._start_finish()

    def _timeoffset(self):
        # Time offset
        return self._tmoffset

    # Return next trading day end time in datetime format and numeric format
    def _getnexteos(self):
        """Returns the next eos using a trading calendar if available"""
        if self._clone:
            return self.data._getnexteos()

        if not len(self):
            return datetime.datetime.min, 0.0

        dt = self.lines.datetime[0]
        dtime = num2date(dt)
        if self._calendar is None:
            nexteos = datetime.datetime.combine(dtime, self.p.sessionend)
            nextdteos = self.date2num(nexteos)  # locl'ed -> utc-like
            nexteos = num2date(nextdteos)  # utc
            while dtime > nexteos:
                nexteos += datetime.timedelta(days=1)  # already utc-like

            nextdteos = date2num(nexteos)  # -> utc-like

        else:
            # returns times in utc
            _, nexteos = self._calendar.schedule(dtime, self._tz)
            nextdteos = date2num(nexteos)  # nextos is already utc

        return nexteos, nextdteos

    # Parse tzinput and return
    def _gettzinput(self):
        """Can be overriden by classes to return a timezone for input"""
        return tzparse(self.p.tzinput)

    # Parse tz and return
    def _gettz(self):
        """To be overriden by subclasses which may auto-calculate the
        timezone"""
        return tzparse(self.p.tz)

    # Convert time to number; if timezone info is not None, localize time first, then convert
    def date2num(self, dt):
        if self._tz is not None:
            return date2num(self._tz.localize(dt))

        return date2num(dt)

    # Convert number to date+time
    def num2date(self, dt=None, tz=None, naive=True):
        if dt is None:
            return num2date(self.lines.datetime[0], tz or self._tz, naive)

        return num2date(dt, tz or self._tz, naive)

    # Whether has live data; default is False; if has live data, needs override
    def haslivedata(self):
        return False  # must be overriden for those that can

    # Wait interval when resampling live data
    def do_qcheck(self, onoff, qlapse):
        # if onoff is True, the data will wait p.qcheck for incoming live data
        # on its queue.
        qwait = self.p.qcheck if onoff else 0.0
        qwait = max(0.0, qwait - qlapse)
        self._qcheck = qwait

    # Whether is live data; default is False; if True, cerebro will not use preload and runonce, because live data needs
    # to be fetched tick by tick or bar by bar
    def islive(self):
        """If this returns True, ``Cerebro`` will deactivate ``preload`` and
        ``runonce`` because a live data source must be fetched tick by tick (or
        bar by bar)"""
        return False

    # If latest status differs from current status, need to add info to notifs to update latest status
    def put_notification(self, status, *args, **kwargs):
        """Add arguments to notification queue"""
        if self._laststatus != status:
            self.notifs.append((status, args, kwargs))
            self._laststatus = status

    # Get notification info, save to notifs and return as result
    def get_notifications(self):
        """Return the pending "store" notifications"""
        # The background thread could keep on adding notifications. The None
        # mark allows to identify which is the last notification to deliver
        # Add a None, when None is retrieved, it means the queue is empty and all info has been retrieved
        self.notifs.append(None)  # put a mark
        notifs = list()
        while True:
            notif = self.notifs.popleft()
            if notif is None:  # mark is reached
                break
            notifs.append(notif)

        return notifs

    # Get feed
    def getfeed(self):
        return self._feed

    # Amount of cached data
    def qbuffer(self, savemem=0, replaying=False):
        extrasize = self.resampling or replaying
        for line in self.lines:
            line.qbuffer(savemem=savemem, extrasize=extrasize)

    # Start, reset _barstack and _barstash
    def start(self):
        self._barstack = collections.deque()
        self._barstash = collections.deque()
        self._laststatus = self.CONNECTED

    # End
    def stop(self):
        pass

    # Clone data
    def clone(self, **kwargs):
        return DataClone(dataname=self, **kwargs)

    # Copy data and give it a different name
    def copyas(self, _dataname, **kwargs):
        d = DataClone(dataname=self, **kwargs)
        d._dataname = _dataname
        d._name = _dataname
        return d

    # Set environment
    def setenvironment(self, env):
        """Keep a reference to the environment"""
        self._env = env

    # Get environment
    def getenvironment(self):
        return self._env

    # Add simple filter
    def addfilter_simple(self, f, *args, **kwargs):
        fp = SimpleFilterWrapper(self, f, *args, **kwargs)
        self._filters.append((fp, fp.args, fp.kwargs))

    # Add filter
    def addfilter(self, p, *args, **kwargs):
        if inspect.isclass(p):
            pobj = p(self, *args, **kwargs)
            self._filters.append((pobj, [], {}))

            if hasattr(pobj, "last"):
                self._ffilters.append((pobj, [], {}))

        else:
            self._filters.append((p, args, kwargs))

    # Compensate
    def compensate(self, other):
        """Call it to let the broker know that actions on this asset will
        compensate open positions in another"""

        self._compensate = other

    # Set tick_+name attribute to None for non-datetime names, mainly used when synthesizing low-frequency data from high-frequency data
    def _tick_nullify(self):
        # These are the updating prices in case the new bar is "updated"
        # and the length doesn't change like if a replay is happening or
        # a real-time data feed is in use and 1-minute bars are being
        # constructed with 5-second updates
        for lalias in self.getlinealiases():
            if lalias != "datetime":
                setattr(self, "tick_" + lalias, None)

        self.tick_last = None

    # If tick_xxx related attribute value is None, need to consider using bar data to fill
    def _tick_fill(self, force=False):
        # If nothing filled the tick_xxx attributes, the bar is the tick
        alias0 = self._getlinealias(0)
        if force or getattr(self, "tick_" + alias0, None) is None:
            for lalias in self.getlinealiases():
                if lalias != "datetime":
                    setattr(self, "tick_" + lalias, getattr(self.lines, lalias)[0])

            self.tick_last = getattr(self.lines, alias0)[0]

    # Get time of next bar
    def advance_peek(self):
        try:
            if len(self) < self.buflen():
                # CRITICAL FIX: Check if datetime[1] is valid before returning
                try:
                    next_dt = self.lines.datetime[1]
                    # If next_dt is 0 or invalid, return inf
                    if next_dt is None or next_dt <= 0:
                        return float("inf")
                    return next_dt
                except (IndexError, KeyError):
                    # If accessing datetime[1] fails, we're at the end
                    return float("inf")
            return float("inf")  # max date else
        except Exception:
            return float("inf")

    # Move data forward by size
    def advance(self, size=1, datamaster=None, ticks=True):
        if ticks:
            self._tick_nullify()

        # Need intercepting this call to support datas with
        # different lengths (timeframes)
        self.lines.advance(size)

        if datamaster is not None:
            if len(self) > self.buflen():
                # if no bar can be delivered, fill with an empty bar
                self.rewind()
                self.lines.forward()
                return

            if self.lines.datetime[0] > datamaster.lines.datetime[0]:
                self.lines.rewind()
            else:
                if ticks:
                    self._tick_fill()
        elif len(self) < self.buflen():
            # a resampler may have advance us past the last point
            if ticks:
                self._tick_fill()

    # What happens on data when next is called
    def next(self, datamaster=None, ticks=True):
        # If data length is greater than cached data length, if it's ticks data, call _tick_nullify to generate tick_xxx attributes, then call load to try getting next bar; if ret is empty
        # return ret. If master data is None, if it's ticks data, need to call _tick_fill.
        # If own length is less than cached data length, move forward
        # print("AbstractDataBase next function is being called")
        if len(self) >= self.buflen():
            if ticks:
                self._tick_nullify()

            # not preloaded - request next bar
            ret = self.load()
            # if ret is not None:
            #     print(f"AbstractDataBase next ret = {ret}")
            if not ret:
                # if the load cannot produce bars - forward the result
                return ret

            if datamaster is None:
                # bar is there and no master ... return load's result
                if ticks:
                    self._tick_fill()
                return ret
        else:
            self.advance(ticks=ticks)
        # If master data is not None, if current data time is greater than master data time, need to adjust backward;
        # If current data time is not greater than master data time and data is ticks data, need to fill current data
        # If master data is None and data is ticks data, need to fill current day data
        # a bar is "loaded" or was preloaded - index has been moved to it
        if datamaster is not None:
            # there is a time reference to check against
            if self.lines.datetime[0] > datamaster.lines.datetime[0]:
                # can't deliver new bar, too early, go back
                self.rewind()
                return False
            else:
                if ticks:
                    self._tick_fill()

        else:
            if ticks:
                self._tick_fill()

        # tell the world there is a bar (either the new or the previous
        # Indicate current bar exists
        return True

    # Preload data
    def preload(self):
        # Load data
        while self.load():
            pass

        self._last()
        self.home()

    # Last chance to use filters
    def _last(self, datamaster=None):
        # A last chance for filters to deliver something

        ret = 0
        for ff, fargs, fkwargs in self._ffilters:
            ret += ff.last(self, *fargs, **fkwargs)

        doticks = False
        if datamaster is not None and self._barstack:
            doticks = True

        while self._fromstack(forward=True):
            # consume bar(s) produced by "last"s - adding room
            pass

        if doticks:
            self._tick_fill()

        return bool(ret)

    # Check if verification is needed
    def _check(self, forcedata=None):
        for ff, fargs, fkwargs in self._filters:
            if not hasattr(ff, "check"):
                continue
            ff.check(self, _forcedata=forcedata, *fargs, **fkwargs)

    # Load data
    def load(self):
        while True:
            # move a data pointer forward for new bar
            # Move data pointer forward by one
            self.forward()

            # If data has been retrieved from self._barstack and saved to line, directly return True
            if self._fromstack():  # bar is available
                return True
            # If data cannot be retrieved from self._barstash, run the following code
            if not self._fromstack(stash=True):
                # _load() returns False, following code must run, but seems unnecessary to call this function or check following result, these two statements seem redundant
                ###  Cannot be 100% certain for now, will review after code comments are completed    #fix
                _loadret = self._load()
                if not _loadret:  # no bar use force to make sure in exactbars
                    # the pointer is undone this covers especially (but not
                    # uniquely) the case in which the last bar has been seen
                    # and a backwards would ruin pointer accounting in the
                    # "stop" method of the strategy
                    self.backwards(force=True)  # undo data pointer

                    # Return the actual returned value which may be None to
                    # signal no bar is available, but the data feed is not
                    # done. False means game over
                    return _loadret

            # If bar was not retrieved from self._barstack but bar was retrieved from self._barstash, need to process bar
            # Get a reference to current loaded time
            # Get current time
            dt = self.lines.datetime[0]

            # A bar has been loaded, adapt the time
            # If timezone processing is needed for input time, convert number to time, localize time, convert time to number, update current time
            if self._tzinput:
                # Input has been converted at face value, but it's not UTC in
                # the input stream
                dtime = num2date(dt)  # get it in a naive datetime
                # localize it
                dtime = self._tzinput.localize(dtime)  # pytz compatible-ized
                self.lines.datetime[0] = dt = date2num(dtime)  # keep UTC val

            # Check standard date from/to filters
            # If current time is less than start time, move backward to discard bar and continue
            if dt < self.fromdate:
                # discard loaded bar and carry on
                self.backwards()
                continue
            # If time is greater than end time, move backward and undo data pointer, then break
            if dt > self.todate:
                # discard loaded bar and break out
                self.backwards(force=True)
                break

            # Pass through filters
            # Iterate through each filter
            retff = False
            for ff, fargs, fkwargs in self._filters:
                # previous filter may have put things onto the stack
                # If self._barstack is not empty
                if self._barstack:
                    # Perform self._barstack number of _fromstack function calls, call filter ff
                    for i in range(len(self._barstack)):
                        self._fromstack(forward=True)
                        retff = ff(self, *fargs, **fkwargs)
                # If self._barstack is empty, call filter once
                else:
                    retff = ff(self, *fargs, **fkwargs)
                # If retff is True, break out of filter loop
                if retff:  # bar removed from systemn
                    break  # out of the inner loop
            # If True, continue
            if retff:  # bar removed from system - loop to get new bar
                continue  # in the greater loop

            # Checks let the bar through ... notify it
            return True
        # End loop, return False, no more bars or reached end date
        # Out of the loop ... no more bars or past todate
        return False

    # Function that returns False
    def _load(self):
        return False

    # Add bar data to self._barstack or self._barstash
    def _add2stack(self, bar, stash=False):
        """Saves given bar (list of values) to the stack for later retrieval"""
        if not stash:
            self._barstack.append(bar)
        else:
            self._barstash.append(bar)

    # Get bar data and save to self._barstack or self._barstash, provides parameter to delete bar
    def _save2stack(self, erase=False, force=False, stash=False):
        """Saves current bar to the bar stack for later retrieval

        Parameter ``erase`` determines removal from the data stream
        """

        bar = [line[0] for line in self.itersize()]
        if not stash:
            self._barstack.append(bar)
        else:
            self._barstash.append(bar)

        if erase:  # remove bar if requested
            self.backwards(force=force)

    # This comment has issues, this function is used to update bar data to specific lines
    def _updatebar(self, bar, forward=False, ago=0):
        """Load a value from the stack onto the lines to form the new bar

        Returns True if values are present, False otherwise
        """
        if forward:
            self.forward()

        for line, val in zip(self.itersize(), bar):
            line[0 + ago] = val

    # Get data from self._barstack or self._barstash, then save to line; if successful return True, if not return False
    def _fromstack(self, forward=False, stash=False):
        """Load a value from the stack onto the lines to form the new bar

        Returns True if values are present, False otherwise
        """
        # When stash is False, coll equals self._barstack, otherwise it's self._barstash
        coll = self._barstack if not stash else self._barstash
        # If coll has data
        if coll:
            # If forward is True, call forward
            if forward:
                self.forward()
            # Add data to line
            for line, val in zip(self.itersize(), coll.popleft()):
                line[0] = val

            return True

        return False

    # Add resample filter
    def resample(self, **kwargs):
        self.addfilter(Resampler, **kwargs)

    # Add replay filter
    def replay(self, **kwargs):
        self.addfilter(Replayer, **kwargs)

    @classmethod
    def _gettuple(cls):
        """For compatibility, provide _gettuple method"""
        return cls._params_tuple if hasattr(cls, "_params_tuple") else cls.params


# DataBase class, directly inherits from abstract DataBase
class DataBase(AbstractDataBase):
    pass


# Refactor: Remove MetaParams metaclass, use normal parameter processing
class FeedBase:
    # Parameter processing, originally merged parameters automatically via metaclass, now manual processing
    def __init__(self, **kwargs):
        # Manually set parameters, replacing original metaclass functionality
        self.p = self._create_params(**kwargs)
        self.datas = list()

    def _create_params(self, **kwargs):
        """Manually create parameter object, replacing metaclass parameter processing"""

        # Create a simple parameter object
        class Params:
            def _getitems(self):
                """Simulate original _getitems method"""
                # OPTIMIZED: Use __dict__ instead of dir() for better performance
                items = []
                for attr_name, value in self.__dict__.items():
                    if not attr_name.startswith("_") and not callable(value):
                        items.append((attr_name, value))
                return items

        params_obj = Params()

        # Get default parameters from DataBase
        if hasattr(DataBase, "params"):
            base_params = DataBase.params
            if isinstance(base_params, (tuple, list)):
                for param_tuple in base_params:
                    if isinstance(param_tuple, (tuple, list)) and len(param_tuple) >= 2:
                        param_name, param_default = param_tuple[0], param_tuple[1]
                        setattr(params_obj, param_name, kwargs.get(param_name, param_default))

        # Set other passed parameters
        for key, value in kwargs.items():
            if not hasattr(params_obj, key):
                setattr(params_obj, key, value)

        return params_obj

    # Data start
    def start(self):
        for data in self.datas:
            data.start()

    # Data end
    def stop(self):
        for data in self.datas:
            data.stop()

    # Get data based on dataname and add data to self.datas
    def getdata(self, dataname, name=None, **kwargs):
        # Merge parameters
        final_kwargs = {}
        if hasattr(self.p, "_getitems"):
            for pname, pvalue in self.p._getitems():
                final_kwargs[pname] = pvalue
        elif hasattr(self.p, "__dict__"):
            final_kwargs.update(self.p.__dict__)

        final_kwargs.update(kwargs)
        final_kwargs["dataname"] = dataname

        data = self._getdata(**final_kwargs)
        data._name = name
        self.datas.append(data)
        return data

    def _getdata(self, dataname, **kwargs):
        # Set keyword arguments
        final_kwargs = {}
        if hasattr(self.p, "_getitems"):
            for pname, pvalue in self.p._getitems():
                final_kwargs[pname] = pvalue
        elif hasattr(self.p, "__dict__"):
            final_kwargs.update(self.p.__dict__)

        final_kwargs.update(kwargs)
        final_kwargs["dataname"] = dataname
        return self.DataCls(**final_kwargs)


# Refactor: Remove MetaCSVDataBase metaclass, use normal initialization method
class CSVDataBase(DataBase):
    """
    Base class for classes implementing CSV DataFeeds

    The class takes care of opening the file, reading the lines and
    tokenizing them.

    Subclasses do only need to override:

      - _loadline(tokens)

    The return value of ``_loadline`` (True/False) will be the return value
    of ``_load`` which has been overriden by this base class
    """

    # Data defaults to None
    f = None
    # Set specific parameters, merge parent class parameters - use _params_tuple to save original definition
    _params_tuple = (
        ("headers", True),
        ("separator", ","),
    )

    # Keep original params definition for compatibility with metaclass system
    params = _params_tuple

    # Get data and simple processing
    def __init__(self, *args, **kwargs):
        # Execute original metaclass MetaCSVDataBase.dopostinit functionality
        self._csv_postinit(**kwargs)

        # Call parent class initialization
        super().__init__(*args, **kwargs)

        self.separator = None

    def _csv_postinit(self, **kwargs):
        """Replace original MetaCSVDataBase.dopostinit"""
        # If parameter has no name and _name attribute is empty, get specific name from data file name
        # Use existing parameter system
        dataname = getattr(self, "p", None) and getattr(self.p, "dataname", None)
        if not dataname:
            dataname = kwargs.get("dataname", "")
        name = getattr(self, "p", None) and getattr(self.p, "name", None)
        if not name:
            name = kwargs.get("name", "")

        if not name and not getattr(self, "_name", ""):
            if isinstance(dataname, string_types):
                self._name, _ = os.path.splitext(os.path.basename(dataname))

    def start(self):
        super().start()
        # If data is None
        if self.f is None:
            # If dataname parameter has readline attribute, it means dataname is a data source, directly set f to data in parameter
            if hasattr(self.p.dataname, "readline"):
                self.f = self.p.dataname
            # If no readline attribute, it means dataname is a path, open file based on path to get data
            else:
                # Let an exception propagate to let the caller know
                self.f = open(self.p.dataname)
        # If there are headers, read a line and skip headers
        if self.p.headers:
            self.f.readline()  # skip the headers
        # Separator for each line of data
        self.separator = self.p.separator

    # Stop
    def stop(self):
        super().stop()
        # If data file is not None, close file and set to None
        if self.f is not None:
            self.f.close()
            self.f = None

    # Preload data
    def preload(self):
        # Load data
        while self.load():
            pass
        # Settings after load is finished
        self._last()
        self.home()

        # preloaded - no need to keep the object around - breaks multip in 3.x
        # Close data file and set to None
        self.f.close()
        self.f = None

    # Load a line of data
    def _load(self):
        # If data file is None, return False; if line cannot be read, return False; process line, call _loadline to load
        if self.f is None:
            return False

        # Let an exception propagate to let the caller know
        line = self.f.readline()

        if not line:
            return False

        line = line.rstrip("\n")
        linetokens = line.split(self.separator)
        return self._loadline(linetokens)

    # Get next line of data
    def _getnextline(self):
        # This function is very similar to previous one, just previous one gets linetokens with additional _loadline call
        if self.f is None:
            return None

        # Let an exception propagate to let the caller know
        line = self.f.readline()

        if not line:
            return None

        line = line.rstrip("\n")
        linetokens = line.split(self.separator)
        return linetokens


class CSVFeedBase(FeedBase):
    # Set parameters
    def __init__(self, basepath="", **kwargs):
        self.basepath = basepath
        # Merge CSVDataBase parameters
        csv_params = {}
        if hasattr(CSVDataBase, "params"):
            csv_base_params = CSVDataBase.params
            if isinstance(csv_base_params, (tuple, list)):
                for param_tuple in csv_base_params:
                    if isinstance(param_tuple, (tuple, list)) and len(param_tuple) >= 2:
                        param_name, param_default = param_tuple[0], param_tuple[1]
                        csv_params[param_name] = kwargs.get(param_name, param_default)

        kwargs.update(csv_params)
        super().__init__(**kwargs)

    # Get data
    def _getdata(self, dataname, **kwargs):
        final_kwargs = {}
        if hasattr(self.p, "_getitems"):
            for pname, pvalue in self.p._getitems():
                final_kwargs[pname] = pvalue
        elif hasattr(self.p, "__dict__"):
            final_kwargs.update(self.p.__dict__)

        final_kwargs.update(kwargs)
        return self.DataCls(dataname=self.basepath + dataname, **final_kwargs)


# Data clone
class DataClone(AbstractDataBase):
    # Set _clone attribute to True
    _clone = True

    # Initialize, data equals dataname parameter value, _datename equals data's _dataname attribute value
    # Then copy date, time, trading interval, compression parameters
    def __init__(self, *args, **kwargs):
        # CRITICAL FIX: Initialize these attributes BEFORE calling super().__init__
        # to ensure they exist when parent class methods access them
        self._dlen = None
        self._preloading = None

        # Get dataname and set it as self.data
        dataname = kwargs.get("dataname")
        if dataname is None:
            raise ValueError("DataClone requires 'dataname' parameter")

        # CRITICAL FIX: Store data reference using object.__setattr__ to bypass
        # any custom __setattr__ that might interfere
        object.__setattr__(self, "data", dataname)
        self._dataname = getattr(self.data, "_dataname", None)

        # Copy date/session parameters from source data
        if hasattr(self.data, "p"):
            kwargs.setdefault("fromdate", getattr(self.data.p, "fromdate", None))
            kwargs.setdefault("todate", getattr(self.data.p, "todate", None))
            kwargs.setdefault("sessionstart", getattr(self.data.p, "sessionstart", None))
            kwargs.setdefault("sessionend", getattr(self.data.p, "sessionend", None))
            kwargs.setdefault("timeframe", getattr(self.data.p, "timeframe", None))
            kwargs.setdefault("compression", getattr(self.data.p, "compression", None))

        super().__init__(*args, **kwargs)

        # CRITICAL FIX: Ensure self.data is still set after parent init
        # Re-set it to be safe, in case parent class __init__ cleared attributes
        if not hasattr(self, "data") or object.__getattribute__(self, "data") is None:
            object.__setattr__(self, "data", dataname)

    def _start(self):
        # redefine to copy data bits from guest data
        self.start()

        # Copy tz infos
        if hasattr(self.data, "_tz"):
            self._tz = self.data._tz
            self.lines.datetime._settz(self._tz)

        if hasattr(self.data, "_calendar"):
            self._calendar = self.data._calendar

        # guest data have already converted input
        self._tzinput = None  # no need to further converr

        # Copy dates/session infos
        if hasattr(self.data, "fromdate"):
            self.fromdate = self.data.fromdate
        if hasattr(self.data, "todate"):
            self.todate = self.data.todate

        # FIXME: if removed from guest, remove here too
        if hasattr(self.data, "sessionstart"):
            self.sessionstart = self.data.sessionstart
        if hasattr(self.data, "sessionend"):
            self.sessionend = self.data.sessionend

    # Start
    def start(self):
        super().start()
        self._dlen = 0
        self._preloading = False

    # Preload data
    def preload(self):
        self._preloading = True
        super().preload()
        if hasattr(self.data, "home"):
            self.data.home()  # preloading data was pushed forward
        self._preloading = False

    # Load data
    def _load(self):
        # assumption: the data is in the system
        # copy the lines
        # If preparing to preload, run following code to copy specific data bit by bit
        if self._preloading:
            # data is preloaded, we are preloading too, can move
            # forward until have full bar or a data source is exhausted
            # Move data forward
            if hasattr(self.data, "advance"):
                self.data.advance()
            # If current data is greater than data buffer length, return False
            if len(self.data) > self.data.buflen():
                return False
            # If current data length is not greater than buffered data length, set line data to dline data
            for line, dline in zip(self.lines, self.data.lines):
                line[0] = dline[0]
            # Return True after successful setting
            return True

        # Not preloading
        # This syntax is not very efficient, changing to len(self.data)<=self._dlen might save one comparison
        if len(self.data) <= self._dlen:
            # if not (len(self.data) > self._dlen): # backtrader built-in
            # Data not beyond last seen bar
            return False

        # Increase data length by 1
        self._dlen += 1

        # Set line data to dline data
        for line, dline in zip(self.lines, self.data.lines):
            line[0] = dline[0]

        return True

    # Move forward by size
    def advance(self, size=1, datamaster=None, ticks=True):
        self._dlen += size
        super().advance(size, datamaster, ticks=ticks)
