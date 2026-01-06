#!/usr/bin/env python
import datetime as _datetime
import inspect

from .lineseries import LineSeries
from .utils import AutoOrderedDict, OrderedDict, date2num
from .utils.py3 import range


class TimeFrame:
    # Add 9 attributes to TimeFrame class for distinguishing trading periods
    (Ticks, MicroSeconds, Seconds, Minutes, Days, Weeks, Months, Years, NoTimeFrame) = range(1, 10)
    # Add a names attribute
    Names = [
        "",
        "Ticks",
        "MicroSeconds",
        "Seconds",
        "Minutes",
        "Days",
        "Weeks",
        "Months",
        "Years",
        "NoTimeFrame",
    ]

    names = Names  # support old naming convention

    # Class method to get Timeframe period type
    @classmethod
    def getname(cls, tframe, compression=None):  # backtrader built-in
        # The default parameter setting for compression is not actually reasonable here,
        # if the default parameter is passed directly, an error will occur in the comparison below
        # Modify the default parameter to 1 or add judgment for compression,
        # I feel changing it to 1 might be more appropriate
        # @classmethod
        # def getname(cls, tframe, compression=1):
        tname = cls.Names[tframe]
        if compression > 1 or tname == cls.Names[-1]:
            return tname  # for plural or 'NoTimeFrame' return plain entry

        # return singular if compression is 1
        # If compression is 1, return a singular trading period
        return cls.Names[tframe][:-1]

    # Class method to get trading period name value
    @classmethod
    def TFrame(cls, name):
        return getattr(cls, name)

    # Class method to return trading period name based on trading period value
    @classmethod
    def TName(cls, tframe):
        return cls.Names[tframe]


class DataSeries(LineSeries):
    # Set plotinfo related values
    plotinfo = dict(plot=True, plotind=True, plotylimited=True)

    # Set dataseries _name attribute, usually can use data._name directly in strategy to get specific data value
    _name = ""
    # todo Try to add a name attribute, same as _name, to facilitate using data.name to access data, avoiding pycharm warning about accessing private variables
    name = _name
    # Set _compression attribute, default is 1, meaning trading period is singular, such as 1 second, 1 minute, 1 day, 1 week, etc.
    _compression = 1
    # Set _timeframe attribute, default is Days
    _timeframe = TimeFrame.Days

    # Set 7 common attributes for dataseries and their values
    Close, Low, High, Open, Volume, OpenInterest, DateTime = range(7)
    # Line order in dataseries
    LineOrder = [DateTime, Open, High, Low, Close, Volume, OpenInterest]

    # Get header variable names of dataseries
    def getwriterheaders(self):
        headers = [self._name, "len"]

        for lo in self.LineOrder:
            headers.append(self._getlinealias(lo))

        morelines = self.getlinealiases()[len(self.LineOrder) :]
        headers.extend(morelines)

        return headers

    # Get values
    def getwritervalues(self):
        length = len(self)
        values = [self._name, length]

        if length:
            values.append(self.datetime.datetime(0))
            for line in self.LineOrder[1:]:
                values.append(self.lines[line][0])
            for i in range(len(self.LineOrder), self.lines.size()):
                values.append(self.lines[i][0])
        else:
            values.extend([""] * self.lines.size())  # no values yet

        return values

    # Get written information
    def getwriterinfo(self):
        # returns dictionary with information
        info = OrderedDict()
        info["Name"] = self._name
        info["Timeframe"] = TimeFrame.TName(self._timeframe)
        info["Compression"] = self._compression

        return info

    def get_name(self):
        return self._name


class OHLC(DataSeries):
    # Inherit from DataSeries, lines exclude datetime leaving only 6
    lines = (
        "close",
        "low",
        "high",
        "open",
        "volume",
        "openinterest",
    )


class OHLCDateTime(OHLC):
    # Inherit from DataSeries, lines only keep datetime
    lines = (("datetime"),)


class SimpleFilterWrapper:
    """Wrapper for filters added via .addfilter to turn them
    into processors.

    Filters are callables which

      - Take `data` as an argument
      - Return False if the current bar has not triggered the filter
      - Return True if the current bar must be filtered

    The wrapper takes the return value and executes the bar removal
    if needed to be
    """

    # This is a class for adding filters, which can perform certain operations on data according to filter needs, such as removal
    # This filter is usually a class or a function
    def __init__(self, data, ffilter, *args, **kwargs):
        if inspect.isclass(ffilter):
            ffilter = ffilter(data, *args, **kwargs)
            args = []
            kwargs = {}

        self.ffilter = ffilter
        self.args = args
        self.kwargs = kwargs

    def __call__(self, data):
        if self.ffilter(data, *self.args, **self.kwargs):
            data.backwards()
            return True

        return False


class _Bar(AutoOrderedDict):
    """
    This class is a placeholder for the values of the standard lines in a
    DataBase class (from OHLCDateTime)

    It inherits from AutoOrderedDict to be able to easily return the values as
    an iterable and address the keys as attributes

    Order of definition is important and must match that of the lines
    definition in DataBase (which directly inherits from OHLCDateTime)
    """

    # This bar is a placeholder for DataBase with standard lines, commonly used to combine small period candlesticks into large period candlesticks
    replaying = False

    # Without - 1 ... converting back to time will not work
    # Need another -1 to support timezones which may move the time forward
    MAXDATE = date2num(_datetime.datetime.max) - 2

    def __init__(self, maxdate=False):
        super().__init__()
        # todo Uncommenting these lines will cause an error, need to check the reason
        # self.datetime = None
        # self.openinterest = None
        # self.volume = None
        # self.open = None
        # self.high = None
        # self.low = None
        # self.close = None
        self.bstart(maxdate=maxdate)

    def bstart(self, maxdate=False):
        """Initializes a bar to the default not-updated vaues"""
        # Initialize before starting
        # Order is important: defined in DataSeries/OHLC/OHLCDateTime
        self.close = float("NaN")
        self.low = float("inf")
        self.high = float("-inf")
        self.open = float("NaN")
        self.volume = 0.0
        self.openinterest = 0.0
        self.datetime = self.MAXDATE if maxdate else None

    def isopen(self):
        # Check if already updated
        """Returns if a bar has already been updated

        Uses the fact that NaN is the value which is not equal to itself
        and ``open`` is initialized to NaN
        """
        o = self.open
        return o == o  # False if NaN, True in other cases

    def bupdate(self, data, reopen=False):
        # Update specific bar
        """Updates a bar with the values from data

        Returns True if the update was the 1st on a bar (just opened)

        Returns False otherwise
        """
        if reopen:
            self.bstart()

        self.datetime = data.datetime[0]

        self.high = max(self.high, data.high[0])
        self.low = min(self.low, data.low[0])
        self.close = data.close[0]

        self.volume += data.volume[0]
        self.openinterest = data.openinterest[0]

        o = self.open
        if reopen or not o == o:
            self.open = data.open[0]
            return True  # just opened the bar

        return False
