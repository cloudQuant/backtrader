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

from datetime import datetime, timezone

from .. import feed
from ..dataseries import TimeFrame
from ..utils import date2num
from ..utils.py3 import integer_types, string_types

# Python 3.11+ has datetime.UTC, earlier versions use timezone.utc
UTC = timezone.utc


def _parse_ymd_compact(
    date_text,
    time_text=None,
    fallback_format="%Y%m%d",
    time_has_seconds=True,
):
    if (
        len(date_text) == 8
        and date_text.isdigit()
    ):
        year = int(date_text[0:4])
        month = int(date_text[4:6])
        day = int(date_text[6:8])
        if time_text is None:
            return datetime(year, month, day)
        return _parse_time(
            year,
            month,
            day,
            time_text,
            date_text + "T" + time_text,
            fallback_format,
            time_has_seconds,
        )

    if time_text is None:
        return datetime.strptime(date_text, fallback_format)
    return datetime.strptime(date_text + "T" + time_text, fallback_format)


def _parse_ymd_separated(
    date_text,
    time_text=None,
    separator="-",
    fallback_format="%Y-%m-%d",
    time_has_seconds=True,
):
    if (
        len(date_text) == 10
        and date_text[4] == separator
        and date_text[7] == separator
    ):
        year = int(date_text[0:4])
        month = int(date_text[5:7])
        day = int(date_text[8:10])
        if time_text is None:
            return datetime(year, month, day)
        return _parse_time(
            year,
            month,
            day,
            time_text,
            date_text + "T" + time_text,
            fallback_format,
            time_has_seconds,
        )

    if time_text is None:
        return datetime.strptime(date_text, fallback_format)
    return datetime.strptime(date_text + "T" + time_text, fallback_format)


def _parse_ymd_hms(date_text):
    if (
        len(date_text) == 19
        and date_text[4] == "-"
        and date_text[7] == "-"
        and date_text[10] == " "
        and date_text[13] == ":"
        and date_text[16] == ":"
    ):
        return datetime(
            int(date_text[0:4]),
            int(date_text[5:7]),
            int(date_text[8:10]),
            int(date_text[11:13]),
            int(date_text[14:16]),
            int(date_text[17:19]),
        )
    return datetime.strptime(date_text, "%Y-%m-%d %H:%M:%S")


def _parse_time(
    year,
    month,
    day,
    time_text,
    fallback_text,
    fallback_format,
    time_has_seconds,
):
    if not time_has_seconds and len(time_text) == 5 and time_text[2] == ":":
        return datetime(
            year,
            month,
            day,
            int(time_text[0:2]),
            int(time_text[3:5]),
        )

    if (
        time_has_seconds
        and len(time_text) == 8
        and time_text[2] == ":"
        and time_text[5] == ":"
    ):
        hour = int(time_text[0:2])
        minute = int(time_text[3:5])
        second = int(time_text[6:8])
        return datetime(year, month, day, hour, minute, second)

    return datetime.strptime(fallback_text, fallback_format)


def _build_datetime_parser(dtformat, tmformat, has_time):
    if has_time:
        fallback_format = dtformat + "T" + tmformat
        if dtformat == "%Y%m%d" and tmformat in ("%H:%M", "%H:%M:%S"):
            return lambda date_text, time_text: _parse_ymd_compact(
                date_text,
                time_text,
                fallback_format,
                tmformat == "%H:%M:%S",
            )
        if dtformat == "%Y-%m-%d" and tmformat in ("%H:%M", "%H:%M:%S"):
            return lambda date_text, time_text: _parse_ymd_separated(
                date_text,
                time_text,
                "-",
                fallback_format,
                tmformat == "%H:%M:%S",
            )
        if dtformat == "%Y.%m.%d" and tmformat in ("%H:%M", "%H:%M:%S"):
            return lambda date_text, time_text: _parse_ymd_separated(
                date_text,
                time_text,
                ".",
                fallback_format,
                tmformat == "%H:%M:%S",
            )
        if dtformat == "%Y/%m/%d" and tmformat in ("%H:%M", "%H:%M:%S"):
            return lambda date_text, time_text: _parse_ymd_separated(
                date_text,
                time_text,
                "/",
                fallback_format,
                tmformat == "%H:%M:%S",
            )
        return lambda date_text, time_text: datetime.strptime(
            date_text + "T" + time_text,
            fallback_format,
        )

    if dtformat == "%Y%m%d":
        return lambda date_text, _: _parse_ymd_compact(date_text)
    if dtformat == "%Y-%m-%d":
        return lambda date_text, _: _parse_ymd_separated(date_text)
    if dtformat == "%Y.%m.%d":
        return lambda date_text, _: _parse_ymd_separated(
            date_text,
            separator=".",
            fallback_format="%Y.%m.%d",
        )
    if dtformat == "%Y/%m/%d":
        return lambda date_text, _: _parse_ymd_separated(
            date_text,
            separator="/",
            fallback_format="%Y/%m/%d",
        )
    if dtformat == "%Y-%m-%d %H:%M:%S":
        return lambda date_text, _: _parse_ymd_hms(date_text)
    return lambda date_text, _: datetime.strptime(date_text, dtformat)


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
        self._has_time = None

    def start(self):
        """Start the Generic CSV data feed.

        Sets up datetime conversion based on dtformat parameter.
        """
        super().start()
        # If string type, set self._dtstr to True, otherwise default is False
        self._dtstr = False
        if isinstance(self.p.dtformat, string_types):
            self._dtstr = True
            self._has_time = self.p.time >= 0
            self._dtconvert = _build_datetime_parser(
                self.p.dtformat,
                self.p.tmformat,
                self._has_time,
            )
        # If integer, set time conversion method based on different integer values
        elif isinstance(self.p.dtformat, integer_types):
            idt = int(self.p.dtformat)
            if idt == 1:
                # self._dtconvert = lambda x: datetime.utcfromtimestamp(int(x))
                self._dtconvert = lambda x, _: datetime.fromtimestamp(int(x), UTC)
            elif idt == 2:
                # self._dtconvert = lambda x: datetime.utcfromtimestamp(float(x))
                self._dtconvert = lambda x, _: datetime.fromtimestamp(float(x), UTC)
        # If dtformat is callable, conversion method is itself
        else:  # assume callable
            self._dtconvert = lambda x, _: self.p.dtformat(x)

    # After reading csv file line, split line's data into linetokens, then further processing
    def _loadline(self, linetokens):
        # Datetime needs special treatment
        # First get specific date based on datetime order
        dtfield = linetokens[self.p.datetime]
        timefield = linetokens[self.p.time] if self._has_time else None
        dt = self._dtconvert(dtfield, timefield)

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
                dtnum = dteosnum
            # If not greater, if self._tzinput is True, directly convert dt to time, if not True, use original dtnum
            else:
                # Avoid reconversion if already converted dtin == dt
                dtnum = date2num(dt) if self._tzinput else dtnum
            self.lines.datetime[0] = dtnum
        # If trading cycle is less than day, convert time directly
        else:
            dtnum = date2num(dt)
            self.lines.datetime[0] = dtnum

        if not self._tzinput and (dtnum < self.fromdate or dtnum > self.todate):
            return True

        # PERFORMANCE OPTIMIZATION: Cache field mappings on first call
        # Avoids repeated getattr calls (619K+ calls to _loadline)
        field_cache = getattr(self, "_field_cache", None)
        if field_cache is None:
            field_cache = []
            p = self.p
            lines = self.lines
            nullvalue = p.nullvalue
            for linefield in self.getlinealiases():
                if linefield != "datetime":
                    csvidx = getattr(p, linefield)
                    line = getattr(lines, linefield)
                    field_cache.append((csvidx, line, nullvalue))
            self._field_cache = field_cache
            self._nullvalue = nullvalue

        # Process cached fields
        nullvalue = self._nullvalue
        for csvidx, line, _ in field_cache:
            if csvidx is None or csvidx < 0:
                csvfield = nullvalue
            else:
                csvfield = linetokens[csvidx]
                if csvfield == "":
                    csvfield = nullvalue
            line[0] = float(csvfield)

        return True


class GenericCSV(feed.CSVFeedBase):
    """Generic CSV feed class.

    Wrapper class for GenericCSVData feed functionality.
    """

    DataCls = GenericCSVData
