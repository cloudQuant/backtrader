#!/usr/bin/env python
"""Generic CSV Data Feed Module - CSV file parsing.

This module provides the GenericCSVData feed for parsing CSV files
with customizable column mappings for backtesting.

Classes:
    GenericCSVData: Parses CSV files with configurable column mappings.

Example:
    >>> data = bt.feeds.GenericCSVData(
    ...     dataname='data.csv',
    ...     datetime=0,
    ...     open=1,
    ...     high=2,
    ...     low=3,
    ...     close=4,
    ...     volume=5
    ... )
    >>> cerebro.adddata(data)
"""
from datetime import UTC, datetime

from .. import feed
from ..dataseries import TimeFrame
from ..utils import date2num
from ..utils.py3 import integer_types, string_types


class GenericCSVData(feed.CSVDataBase):
    """Parses a CSV file according to the order and field presence defined by the
    parameters

    Specific parameters (or specific meaning):

      - ``dataname``: The filename to parse or a file-like object

      - The lines parameters (datetime, open, high ...) take numeric values

        A value of -1 indicates absence of that field in the CSV source

      - If ``time`` is present (parameter time >=0), the source contains
        separated fields for date and time, which will be combined

      - ``nullvalue``

        Value that will be used if a value which should be there is missing
        (the CSV field is empty)

      - ``dtformat``: Format used to parse the datetime CSV field. See the
        python strptime/strftime documentation for the format.

        If a numeric value is specified, it will be interpreted as follows

          - ``1``: The value is a Unix timestamp of a type ``int`` representing
            the number of seconds since Jan 1st, 1970

          - ``2``: The value is a Unix timestamp of a type ``float``

        If a **callable** is passed

          - It will accept a string and return a `datetime.datetime` python
            instance

      - ``tmformat``: Format used to parse the time CSV field if "present"
        (the default for the "time" CSV field is not to be present)

    """

    # Common parameters for csv data
    params = (
        ("nullvalue", float("NaN")),
        ("dtformat", "%Y-%m-%d %H:%M:%S"),
        ("tmformat", "%H:%M:%S"),
        ("datetime", 0),
        ("time", -1),
        ("open", 1),
        ("high", 2),
        ("low", 3),
        ("close", 4),
        ("volume", 5),
        ("openinterest", 6),
    )

    def __init__(self, *args, **kwargs):
        """Initialize the Generic CSV data feed.

        Args:
            *args: Positional arguments for data feed configuration.
            **kwargs: Keyword arguments for data feed configuration.
        """
        super().__init__(*args, **kwargs)
        self._dtconvert = None
        self._dtstr = None

    def start(self):
        """Start the Generic CSV data feed.

        Sets up datetime conversion based on dtformat parameter.
        """
        super().start()
        # If string type, set self._dtstr to True, otherwise default is False
        self._dtstr = False
        if isinstance(self.p.dtformat, string_types):
            self._dtstr = True
        # If integer, set time conversion method based on different integer values
        elif isinstance(self.p.dtformat, integer_types):
            idt = int(self.p.dtformat)
            if idt == 1:
                # self._dtconvert = lambda x: datetime.utcfromtimestamp(int(x))
                self._dtconvert = lambda x: datetime.fromtimestamp(int(x), UTC)
            elif idt == 2:
                # self._dtconvert = lambda x: datetime.utcfromtimestamp(float(x))
                self._dtconvert = lambda x: datetime.fromtimestamp(float(x), UTC)
        # If dtformat is callable, conversion method is itself
        else:  # assume callable
            self._dtconvert = self.p.dtformat

    # After reading csv file line, split line's data into linetokens, then further processing
    def _loadline(self, linetokens):
        # Datetime needs special treatment
        # First get specific date based on datetime order
        dtfield = linetokens[self.p.datetime]
        # If time is string format
        if self._dtstr:
            # Specific time format
            dtformat = self.p.dtformat
            # If there's time column, combine date and time together
            if self.p.time >= 0:
                # add time value and format if it's in a separate field
                dtfield += "T" + linetokens[self.p.time]
                dtformat += "T" + self.p.tmformat
            # Then convert string time to datetime format time
            dt = datetime.strptime(dtfield, dtformat)
        # If not string, call time conversion function _dtconvert set in start
        else:
            dt = self._dtconvert(dtfield)
        # If trading interval is greater than or equal to day
        if self.p.timeframe >= TimeFrame.Days:
            # check if the expected end of session is larger than parsed
            # If _tzinput is True, need to localize date, otherwise date remains original
            if self._tzinput:
                dtin = self._tzinput.localize(dt)  # pytz compatible-ized
            else:
                dtin = dt
            # Use date2num to convert date to number
            dtnum = date2num(dtin)  # utc'ize
            # Combine date and sessionend, convert to number
            dteos = datetime.combine(dt.date(), self.p.sessionend)
            dteosnum = self.date2num(dteos)  # utc'ize
            # If number converted from combined sessionend date is greater than converted date number, use former number as time
            if dteosnum > dtnum:
                self.lines.datetime[0] = dteosnum
            # If not greater, if self._tzinput is True, directly convert dt to time, if not True, use original dtnum
            else:
                # Avoid reconversion if already converted dtin == dt
                self.l.datetime[0] = date2num(dt) if self._tzinput else dtnum
        # If trading cycle is less than day, convert time directly
        else:
            self.lines.datetime[0] = date2num(dt)

        # The rest of the fields can be done with the same procedure
        # Remaining data can be processed using same method, loop through columns that are not datetime
        for linefield in (x for x in self.getlinealiases() if x != "datetime"):
            # Get the index created from the passed params
            # Get index of this column name
            csvidx = getattr(self.p, linefield)
            # If this column's index is None or less than 0, data is empty, set to NAN
            if csvidx is None or csvidx < 0:
                # the field will not be present, assignt the "nullvalue"
                csvfield = self.p.nullvalue
            # Otherwise get directly from linetokens
            else:
                # get it from the token
                csvfield = linetokens[csvidx]
            # If retrieved data is empty string, set data to NAN
            if csvfield == "":
                # if empty ... assign the "nullvalue"
                csvfield = self.p.nullvalue
            # Get line corresponding to this column, then set value, don't quite understand why use two float to convert one value, temporarily consider it inefficient, fix it
            # get the corresponding line reference and set the value
            line = getattr(self.lines, linefield)
            # line[0] = float(float(csvfield))  # backtrader built-in
            line[0] = float(csvfield)

        return True


class GenericCSV(feed.CSVFeedBase):
    """Generic CSV feed class.

    Wrapper class for GenericCSVData feed functionality.
    """

    DataCls = GenericCSVData
