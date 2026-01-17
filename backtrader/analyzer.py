#!/usr/bin/env python
"""Analyzer Module - Strategy performance analysis framework.

This module provides the base classes for analyzers that calculate and
report performance metrics for trading strategies. Analyzers can track
trades, returns, drawdowns, Sharpe ratios, and other statistics.

Key Classes:
    Analyzer: Base class for all analyzers.
    TimeFrameAnalyzerBase: Base for time-frame aware analyzers.

Analyzers receive notifications from the strategy during backtesting:
    - notify_trade: Called when a trade is completed
    - notify_order: Called when an order status changes
    - notify_cashvalue: Called when cash/value changes
    - notify_fund: Called when fund data changes

Example:
    Creating a custom analyzer:
    >>> class MyAnalyzer(Analyzer):
    ...     def __init__(self):
    ...         super().__init__()
    ...         self.trades = 0
    ...
    ...     def notify_trade(self, trade):
    ...         if trade.isclosed:
    ...             self.trades += 1
    ...
    ...     def get_analysis(self):
    ...         return {'trade_count': self.trades}
"""
import calendar
import datetime
import pprint as pp
from collections import OrderedDict

from .dataseries import TimeFrame
from .metabase import findowner
from .observer import Observer
from .parameters import ParameterizedBase
from .strategy import Strategy
from .utils.py3 import MAXINT


# Analyzer class - refactored to not use metaclass
class Analyzer(ParameterizedBase):
    """Analyzer base class. All analyzers are subclass of this one

    An Analyzer instance operates in the frame of a strategy and provides an
    analysis for that strategy.

    # Analyzer class, all analyzers are base classes of this class. An analyzer operates within the strategy framework and provides analysis of strategy execution

    Automagically set member attributes:

      - ``self.strategy`` (giving access to the *strategy* and anything
        accessible from it)

        # Access to strategy instance

      - ``self.datas[x]`` giving access to the array of data feeds present in
        the the system, which could also be accessed via the strategy reference

      - ``self.data``, giving access to ``self.datas[0]``

      - ``self.dataX`` -> ``self.datas[X]``

      - ``self.dataX_Y`` -> ``self.datas[X].lines[Y]``

      - ``self.dataX_name`` -> ``self.datas[X].name``

      - ``self.data_name`` -> ``self.datas[0].name``

      - ``self.data_Y`` -> ``self.datas[0].lines[Y]``

      # Methods to access data

    This is not a *Lines* object, but the methods and operation follow the same
    design

      - ``__init__`` during instantiation and initial setup

      - ``start`` / ``stop`` to signal the begin and end of operations

      - ``prenext`` / ``nextstart`` / ``next`` family of methods that follow
        the calls made to the same methods in the strategy

      - ``notify_trade`` / ``notify_order`` / ``notify_cashvalue`` /
        ``notify_fund`` which receive the same notifications as the equivalent
        methods of the strategy

    The mode of operation is open and no pattern is preferred. As such the
    analysis can be generated with the ``next`` calls, at the end of operations
    during ``stop`` and even with a single method like ``notify_trade``

    The important thing is to override ``get_analysis`` to return a *dict-like*
    object containing the results of the analysis (the actual format is
    implementation dependent)

    # Below are not line objects, but methods and operation design are similar to strategy. The most important thing is to override get_analysis,
    # to return a dict-like object to store analysis results

    """

    # Save results to csv
    csv = True

    def __init__(self, *args, **kwargs):
        """
        Initialize Analyzer with basic functionality.

        Note: __new__ removed - _children initialization moved here.
        """
        # Initialize children list (moved from __new__)
        self._children = list()

        # Initialize parent first
        super().__init__(*args, **kwargs)

        # findowner is used to find _obj's parent, Strategy instance, returns None if not found
        self.strategy = strategy = findowner(self, Strategy)
        # findowner is used to find _obj's parent, belonging to Analyzer instance, returns None if not found
        self._parent = findowner(self, Analyzer)
        # Register with a master observer if created inside one
        # findowner is used to find _obj's parent, but belonging to Observer instance, returns None if not found
        masterobs = findowner(self, Observer)
        # If there is obs, register analyzer to obs
        if masterobs is not None:
            masterobs._register_analyzer(self)
        # analyzer's data
        self.datas = strategy.datas if strategy is not None else []

        # For each data add aliases: for first data: data and data0
        # If analyzer's data is not None
        if self.datas:
            # analyzer's data is the first data
            self.data = data = self.datas[0]
            # For each line in data
            for line_index, line in enumerate(data.lines):
                # Get line name
                linealias = data._getlinealias(line_index)
                # If line name is not None, set attribute
                if linealias:
                    setattr(self, "data_%s" % linealias, line)
                # Set line name based on index
                setattr(self, "data_%d" % line_index, line)
            # Loop through data, set different names for data, can be accessed via data_d
            for d, data in enumerate(self.datas):
                setattr(self, "data%d" % d, data)
                # Set specific attribute names for different data, can access line via attribute name
                for line_index, line in enumerate(data.lines):
                    linealias = data._getlinealias(line_index)
                    if linealias:
                        setattr(self, "data%d_%s" % (d, linealias), line)
                    setattr(self, "data%d_%d" % (d, line_index), line)

        # Call create_analysis method
        self.create_analysis()

        # Handle parent registration (previously in dopostinit)
        if self._parent is not None:
            self._parent._register(self)

    # When getting analyzer's length, actually returns strategy's length
    def __len__(self):
        """Support for invoking ``len`` on analyzers by actually returning the
        current length of the strategy the analyzer operates on"""
        return len(self.strategy)

    # Add a child to self._children
    def _register(self, child):
        self._children.append(child)

    # Call _prenext, for each child, call _prenext
    def _prenext(self):
        for child in self._children:
            child._prenext()
        # Call prenext
        self.prenext()

    # Notify cash and value
    # PERFORMANCE OPTIMIZATION: Cache children check, called 3.1M+ times
    def _notify_cashvalue(self, cash, value):
        children = self._children
        if children:
            for child in children:
                child._notify_cashvalue(cash, value)
        self.notify_cashvalue(cash, value)

    # Notify cash, value, fundvalue, shares
    # PERFORMANCE OPTIMIZATION: Cache children check, called 3.1M+ times
    def _notify_fund(self, cash, value, fundvalue, shares):
        children = self._children
        if children:
            for child in children:
                child._notify_fund(cash, value, fundvalue, shares)
        self.notify_fund(cash, value, fundvalue, shares)

    # Notify trade
    def _notify_trade(self, trade):
        for child in self._children:
            child._notify_trade(trade)

        self.notify_trade(trade)

    # Notify order
    def _notify_order(self, order):
        for child in self._children:
            child._notify_order(order)

        self.notify_order(order)

    # Call _nextstart
    def _nextstart(self):
        for child in self._children:
            child._nextstart()

        self.nextstart()

    # Call _next
    def _next(self):
        for child in self._children:
            child._next()

        self.next()

    # _start, call _start for all children
    def _start(self):
        for child in self._children:
            child._start()

        self.start()

    # _stop, call _stop for all children
    def _stop(self):
        for child in self._children:
            child._stop()

        self.stop()

    # Notify cash, value
    def notify_cashvalue(self, cash, value):
        """Notify the analyzer of cash and value changes.

        Args:
            cash: Current available cash.
            value: Current portfolio value.

        Note:
            Override this method to react to cash/value changes.
        """
        pass

    # Notify fund
    def notify_fund(self, cash, value, fundvalue, shares):
        """Notify the analyzer of fund-related changes.

        Args:
            cash: Current available cash.
            value: Current portfolio value.
            fundvalue: Current fund value.
            shares: Number of fund shares.

        Note:
            Override this method to react to fund changes.
        """
        pass

    # Notify order, can be overridden in subclasses
    def notify_order(self, order):
        """Notify the analyzer of an order status change.

        Args:
            order: The order that was updated.

        Note:
            Override this method to track order status.
        """
        pass

    # Notify trade, can be overridden in subclasses
    def notify_trade(self, trade):
        """Notify the analyzer of a trade status change.

        Args:
            trade: The trade that was updated.

        Note:
            Override this method to track trade status.
        """
        pass

    # next, can be overridden in subclasses
    def next(self):
        """Called on each bar after minimum period is reached.

        Note:
            Override this method to implement per-bar analysis logic.
        """
        pass

    # prenext, if equal to next, override prenext in subclasses,
    # generally, prenext needs to do the same calculation as next or pass
    def prenext(self):
        """Called on each bar before minimum period is reached.

        By default calls next(). Override if different behavior is needed.
        """
        # prenext and next until a minimum period of total_lines has been
        # reached
        # By default call next, unless prenext is specially overridden in subclass, otherwise prenext calls next
        self.next()

    # nextstart, generally overridden by subclasses, or call next
    def nextstart(self):
        """Called once when minimum period is first reached.

        By default calls next(). Override if different behavior is needed.
        """
        # Called once when the minimum period for all lines has been meet
        # It's default behavior is to call next
        # By default call next
        self.next()

    # start, can be overridden in subclasses
    def start(self):
        """Called at the start of the backtest.

        Note:
            Override this method to initialize analyzer state.
        """
        pass

    # stop, can be overridden in subclasses
    def stop(self):
        """Called at the end of the backtest.

        Note:
            Override this method to perform final calculations.
        """
        pass

    # Create analysis, override in subclasses
    def create_analysis(self):
        """Create the analysis results container.

        Creates the rets OrderedDict that will hold analysis results.
        Override this method to customize the results structure.
        """
        # create a dict placeholder for the analysis
        # Create a dict placeholder for analysis results
        # self.rets can be accessed via get_analysis
        self.rets = OrderedDict()

    # Get analysis
    def get_analysis(self):
        """Returns a *dict-like* object with the results of the analysis

        The keys and format of analysis results in the dictionary is
        implementation dependent.

        It is not even enforced that the result is a *dict-like object*, just
        the convention

        The default implementation returns the default OrderedDict ``rets``
        created by the default ``create_analysis`` method

        # Return dict-like result analysis, specific format depends on implementation
        """
        return self.rets

    # Print analysis
    def print(self, *args, **kwargs):
        """Prints the results returned by ``get_analysis`` via a standard
        ``print`` call"""
        # print analysis, print analysis results by calling, this content can be accessed via get_analysis
        print(self.get_analysis())

    # Pretty print analysis
    def pprint(self, *args, **kwargs):
        """Prints the results returned by ``get_analysis`` via a pretty print
        call"""
        # pretty print analysis, similar to above
        pp.pprint(self.get_analysis(), *args, **kwargs)


# TimeFrameAnalyzerBase class - refactored to not use metaclass
class TimeFrameAnalyzerBase(Analyzer):
    """Base class for time-frame aware analyzers.

    This analyzer base operates on a specific timeframe (daily, weekly,
    monthly, etc.) and calls on_dt_over() when the timeframe changes.

    Params:
        timeframe: TimeFrame to use (None = use data's timeframe).
        compression: Compression factor (None = use data's compression).
        _doprenext: Whether to call prenext (default: True).

    Methods:
        on_dt_over(): Override to handle timeframe changes.
    """

    # Parameters
    params = (
        ("timeframe", None),
        ("compression", None),
        ("_doprenext", True),
    )

    def __init__(self, *args, **kwargs):
        """Initialize with functionality previously in MetaTimeFrameAnalyzerBase"""
        super().__init__(*args, **kwargs)

        # Hack to support original method name - add on_dt_over_orig if on_dt_over_orig exists
        if hasattr(self, "on_dt_over_orig") and not hasattr(self, "on_dt_over"):
            self.on_dt_over = self.on_dt_over_orig

    def _start(self):
        # Override to add specific attributes
        # Set trading period, e.g., minutes
        # Set trading period - use data's timeframe if not specified
        self.timeframe = self.p.timeframe or self.data._timeframe
        # Set compression - use data's compression if not specified
        self.compression = self.p.compression or self.data._compression
        # CRITICAL FIX: Initialize dtcmp with datetime.min to match master branch behavior
        # This ensures first _dt_over() call detects a change and counts correctly
        self.dtcmp, self.dtkey = self._get_dt_cmpkey(datetime.datetime.min)
        super()._start()

    def _prenext(self):
        # Match master branch: call children, check _dt_over, then prenext
        for child in self._children:
            child._prenext()

        if self._dt_over():
            self.on_dt_over()

        if self.p._doprenext:
            self.prenext()

    def _nextstart(self):
        # Match master branch: call children, check _dt_over or not doprenext, then nextstart
        for child in self._children:
            child._nextstart()

        if self._dt_over() or not self.p._doprenext:
            self.on_dt_over()

        self.nextstart()

    def _next(self):
        # Match master branch: call children, check _dt_over, then next
        for child in self._children:
            child._next()

        if self._dt_over():
            self.on_dt_over()

        self.next()

    # This method generally needs to be overridden in subclasses
    def on_dt_over(self):
        """Called when the timeframe period changes.

        This method is called when the datetime crosses into a new
        period of the configured timeframe (e.g., new week, new month).

        Note:
            Override this method to implement period-based analysis logic.
        """
        pass

    # CRITICAL FIX: Match master branch - return boolean and update dtcmp atomically
    def _dt_over(self):
        # If trading period equals NoTimeFrame, dtcmp equals maximum integer, dtkey equals maximum time
        if self.timeframe == TimeFrame.NoTimeFrame:
            dtcmp, dtkey = MAXINT, datetime.datetime.max
        else:
            # Get current datetime from strategy
            dt = self.strategy.datetime.datetime()
            dtcmp, dtkey = self._get_dt_cmpkey(dt)

        # If dtcmp is None, or dtcmp is greater than self.dtcmp
        if self.dtcmp is None or dtcmp > self.dtcmp:
            # Set dtkey, dtkey1, dtcmp, dtcmp1 return True
            self.dtkey, self.dtkey1 = dtkey, self.dtkey
            self.dtcmp, self.dtcmp1 = dtcmp, self.dtcmp
            return True
        # Return False
        return False

    # Get dtcmp, dtkey
    def _get_dt_cmpkey(self, dt):
        # If current trading period has NoTimeFrame, return two Nones
        if self.timeframe == TimeFrame.NoTimeFrame:
            return None, None
        # If current trading period is years
        if self.timeframe == TimeFrame.Years:
            dtcmp = dt.year
            dtkey = datetime.date(dt.year, 12, 31)
        # If trading period is months
        elif self.timeframe == TimeFrame.Months:
            dtcmp = dt.year * 100 + dt.month
            # Get last day
            _, lastday = calendar.monthrange(dt.year, dt.month)
            # Get last day of each month
            dtkey = datetime.datetime(dt.year, dt.month, lastday)
        # If trading period is weeks
        elif self.timeframe == TimeFrame.Weeks:
            # Return year, week number and weekday for date
            isoyear, isoweek, isoweekday = dt.isocalendar()
            dtcmp = isoyear * 1000 + isoweek
            # Weekend
            sunday = dt + datetime.timedelta(days=7 - isoweekday)
            # Get last day of each week
            dtkey = datetime.datetime(sunday.year, sunday.month, sunday.day)
        # If trading period is days, calculate specific dtcmp, dtkey
        elif self.timeframe == TimeFrame.Days:
            dtcmp = dt.year * 10000 + dt.month * 100 + dt.day
            dtkey = datetime.datetime(dt.year, dt.month, dt.day)
        # If trading period is less than days, call _get_subday_cmpkey to get
        else:
            dtcmp, dtkey = self._get_subday_cmpkey(dt)

        return dtcmp, dtkey

    # If trading period is less than days
    def _get_subday_cmpkey(self, dt):
        # Calculate intraday position
        # Calculate current number of minutes
        point = dt.hour * 60 + dt.minute
        # If current trading period is less than minutes, convert point to seconds
        if self.timeframe < TimeFrame.Minutes:
            point = point * 60 + dt.second
        # If current trading period is less than seconds, convert point to microseconds
        if self.timeframe < TimeFrame.Seconds:
            point = point * 1e6 + dt.microsecond

        # Apply compression to update point position (comp 5 -> 200 // 5)
        # Calculate current point based on number of periods
        point = point // self.compression

        # Move to next boundary
        # Move to next
        point += 1

        # Restore point to the timeframe units by de-applying compression
        # Calculate end position of next point
        point *= self.compression

        # Get hours, minutes, seconds and microseconds
        # If trading period equals minutes, get ph, pm
        if self.timeframe == TimeFrame.Minutes:
            ph, pm = divmod(point, 60)
            ps = 0
            pus = 0
        # If trading period equals seconds, get ph, pm, ps
        elif self.timeframe == TimeFrame.Seconds:
            ph, pm = divmod(point, 60 * 60)
            pm, ps = divmod(pm, 60)
            pus = 0
        # If microseconds, get ph, pm, ps, pus
        elif self.timeframe == TimeFrame.MicroSeconds:
            ph, pm = divmod(point, 60 * 60 * 1e6)
            pm, psec = divmod(pm, 60 * 1e6)
            ps, pus = divmod(psec, 1e6)
        # Whether it's the next day
        extradays = 0
        #  If hour is greater than 23, divide, calculate if it's the next day
        if ph > 23:  # went over midnight:
            extradays = ph // 24
            ph %= 24

        # moving 1 minor unit to the left to be in the boundary
        # Time to adjust
        tadjust = datetime.timedelta(
            minutes=self.timeframe == TimeFrame.Minutes,
            seconds=self.timeframe == TimeFrame.Seconds,
            microseconds=self.timeframe == TimeFrame.MicroSeconds,
        )

        # Add extra day if present
        # If next day is True, adjust time to next day
        if extradays:
            dt += datetime.timedelta(days=extradays)

        # Replace intraday parts with the calculated ones and update it
        # Calculate dtcmp
        dtcmp = dt.replace(hour=int(ph), minute=int(pm), second=int(ps), microsecond=int(pus))
        # Adjust dtcmp
        dtcmp -= tadjust
        # dtkey equals dtcmp
        dtkey = dtcmp

        return dtcmp, dtkey
