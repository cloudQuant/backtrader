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

import math
from datetime import date, datetime, timezone

from .. import feed
from ..dataseries import TimeFrame
from ..utils import date2num
from ..utils.py3 import integer_types, string_types

# Python 3.11+ has datetime.UTC, earlier versions use timezone.utc
UTC = timezone.utc
_INF = float("inf")
_NEG_INF = float("-inf")
_FLOAT = float
_OBJECT_SETATTR = object.__setattr__
_HOURS_PER_DAY = 24.0
_MINUTES_PER_DAY = 1440.0
_SECONDS_PER_DAY = 86400.0
_DAYS_BEFORE_MONTH = (0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
_DAYS_IN_MONTH = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _parse_ymd_compact(
    date_text,
    time_text=None,
    fallback_format="%Y%m%d",
    time_has_seconds=True,
):
    if len(date_text) == 8 and date_text.isdigit():
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
    if len(date_text) == 10 and date_text[4] == separator and date_text[7] == separator:
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

    if time_has_seconds and len(time_text) == 8 and time_text[2] == ":" and time_text[5] == ":":
        hour = int(time_text[0:2])
        minute = int(time_text[3:5])
        second = int(time_text[6:8])
        return datetime(year, month, day, hour, minute, second)

    return datetime.strptime(fallback_text, fallback_format)


def _parse_time_num(time_text, time_has_seconds):
    if not time_has_seconds and len(time_text) == 5 and time_text[2] == ":":
        return int(time_text[0:2]), int(time_text[3:5]), 0

    if time_has_seconds and len(time_text) == 8 and time_text[2] == ":" and time_text[5] == ":":
        return int(time_text[0:2]), int(time_text[3:5]), int(time_text[6:8])

    return None


def _ordinal_to_num(ordinal, hour=0, minute=0, second=0):
    return math.fsum(
        (
            float(ordinal),
            hour / _HOURS_PER_DAY,
            minute / _MINUTES_PER_DAY,
            second / _SECONDS_PER_DAY,
        )
    )


def _parse_ymd_compact_num(date_text, time_text=None, time_has_seconds=True):
    if len(date_text) != 8 or not date_text.isdigit():
        return None

    ordinal = date(
        int(date_text[0:4]),
        int(date_text[4:6]),
        int(date_text[6:8]),
    ).toordinal()
    if time_text is None:
        return float(ordinal)

    parsed_time = _parse_time_num(time_text, time_has_seconds)
    if parsed_time is None:
        return None

    return _ordinal_to_num(ordinal, *parsed_time)


def _parse_ymd_separated_num(date_text, time_text=None, separator="-", time_has_seconds=True):
    if not (len(date_text) == 10 and date_text[4] == separator and date_text[7] == separator):
        return None

    ordinal = date(
        int(date_text[0:4]),
        int(date_text[5:7]),
        int(date_text[8:10]),
    ).toordinal()
    if time_text is None:
        return float(ordinal)

    parsed_time = _parse_time_num(time_text, time_has_seconds)
    if parsed_time is None:
        return None

    return _ordinal_to_num(ordinal, *parsed_time)


def _parse_ymd_hms_num(date_text):
    if not (
        len(date_text) == 19
        and date_text[4] == "-"
        and date_text[7] == "-"
        and date_text[10] == " "
        and date_text[13] == ":"
        and date_text[16] == ":"
    ):
        return None

    ordinal = date(
        int(date_text[0:4]),
        int(date_text[5:7]),
        int(date_text[8:10]),
    ).toordinal()
    return _ordinal_to_num(
        ordinal,
        int(date_text[11:13]),
        int(date_text[14:16]),
        int(date_text[17:19]),
    )


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


def _build_datetime_num_parser(dtformat, tmformat, has_time):
    if has_time:
        if dtformat == "%Y%m%d" and tmformat in ("%H:%M", "%H:%M:%S"):
            return lambda date_text, time_text: _parse_ymd_compact_num(
                date_text,
                time_text,
                tmformat == "%H:%M:%S",
            )
        if dtformat == "%Y-%m-%d" and tmformat in ("%H:%M", "%H:%M:%S"):
            return lambda date_text, time_text: _parse_ymd_separated_num(
                date_text,
                time_text,
                "-",
                tmformat == "%H:%M:%S",
            )
        if dtformat == "%Y.%m.%d" and tmformat in ("%H:%M", "%H:%M:%S"):
            return lambda date_text, time_text: _parse_ymd_separated_num(
                date_text,
                time_text,
                ".",
                tmformat == "%H:%M:%S",
            )
        if dtformat == "%Y/%m/%d" and tmformat in ("%H:%M", "%H:%M:%S"):
            return lambda date_text, time_text: _parse_ymd_separated_num(
                date_text,
                time_text,
                "/",
                tmformat == "%H:%M:%S",
            )
        return None

    if dtformat == "%Y%m%d":
        return lambda date_text, _: _parse_ymd_compact_num(date_text)
    if dtformat == "%Y-%m-%d":
        return lambda date_text, _: _parse_ymd_separated_num(date_text)
    if dtformat == "%Y.%m.%d":
        return lambda date_text, _: _parse_ymd_separated_num(date_text, separator=".")
    if dtformat == "%Y/%m/%d":
        return lambda date_text, _: _parse_ymd_separated_num(date_text, separator="/")
    if dtformat == "%Y-%m-%d %H:%M:%S":
        return lambda date_text, _: _parse_ymd_hms_num(date_text)
    return None


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
        p = self.p
        self._datetime_idx = p.datetime
        self._time_idx = p.time
        self._timeframe = p.timeframe
        self._sessionend = p.sessionend
        self._datetime_line = self.lines.datetime
        self._nullvalue = p.nullvalue
        field_cache = []
        missing_field_cache = []
        direct_field_cache = []
        direct_missing_field_cache = []
        last_alias = self._getlinealias(0)
        for linefield in self.getlinealiases():
            if linefield == "datetime":
                continue

            csvidx = getattr(p, linefield)
            line = getattr(self.lines, linefield)
            tick_name = "tick_" + linefield
            is_last = linefield == last_alias
            if csvidx is None or csvidx < 0:
                value = float(p.nullvalue)
                if value in (_INF, _NEG_INF):
                    value = line._default_value
                missing_field_cache.append((line, value))
                direct_missing_field_cache.append((line, value, tick_name, is_last))
            else:
                field_cache.append((csvidx, line))
                direct_field_cache.append((csvidx, line, tick_name, is_last))
        self._field_cache = tuple(field_cache)
        self._missing_field_cache = tuple(missing_field_cache)
        self._direct_field_cache = tuple(direct_field_cache)
        self._direct_missing_field_cache = tuple(direct_missing_field_cache)
        # If string type, set self._dtstr to True, otherwise default is False
        self._dtstr = False
        if isinstance(p.dtformat, string_types):
            self._dtstr = True
            self._has_time = self._time_idx >= 0
            if self._has_time and p.dtformat == "%Y%m%d" and p.tmformat == "%H:%M:%S":
                self._dt_num_fast = 1
            elif self._has_time and p.dtformat == "%Y%m%d" and p.tmformat == "%H:%M":
                self._dt_num_fast = 2
            else:
                self._dt_num_fast = 0
            self._dtconvert = _build_datetime_parser(
                p.dtformat,
                p.tmformat,
                self._has_time,
            )
            self._dtconvert_num = _build_datetime_num_parser(
                p.dtformat,
                p.tmformat,
                self._has_time,
            )
        # If integer, set time conversion method based on different integer values
        elif isinstance(p.dtformat, integer_types):
            self._dtconvert_num = None
            self._dt_num_fast = 0
            idt = int(p.dtformat)
            if idt == 1:
                # self._dtconvert = lambda x: datetime.utcfromtimestamp(int(x))
                self._dtconvert = lambda x, _: datetime.fromtimestamp(int(x), UTC)
            elif idt == 2:
                # self._dtconvert = lambda x: datetime.utcfromtimestamp(float(x))
                self._dtconvert = lambda x, _: datetime.fromtimestamp(float(x), UTC)
        # If dtformat is callable, conversion method is itself
        else:  # assume callable
            dtformat = p.dtformat
            self._dtconvert = lambda x, _: dtformat(x)
            self._dtconvert_num = None
            self._dt_num_fast = 0

    def _runnext_direct_load_ready(self):
        """Return whether Cerebro can call load() directly in single-data runnext."""
        try:
            return object.__getattribute__(self, "_runnext_direct_load_ready_cache")
        except AttributeError:
            pass

        try:
            ready = (
                type(self) is GenericCSVData
                and self.f is not None
                and object.__getattribute__(self, "_tzinput") is None
                and object.__getattribute__(self, "fromdate") == _NEG_INF
                and object.__getattribute__(self, "todate") == _INF
                and not self._filters
                and not self._barstack
                and not self._barstash
                and not self.resampling
                and not self.replaying
                and not self._clone
            )
        except AttributeError:
            ready = False

        object.__setattr__(self, "_runnext_direct_load_ready_cache", ready)
        if ready:
            object.__setattr__(self, "_use_direct_csv_load", True)
            try:
                if self._runnext_direct_ymdhms_ohlcv_ready():
                    object.__setattr__(
                        self,
                        "_runnext_direct_load",
                        self._load_direct_ymdhms_ohlcv,
                    )
            except AttributeError:
                pass
        return ready

    def _runnext_direct_ymdhms_ohlcv_ready(self):
        """Return whether the narrow runnext CSV loader can be used."""
        try:
            return object.__getattribute__(self, "_runnext_direct_ymdhms_ohlcv_ready_cache")
        except AttributeError:
            pass

        p = self.p
        try:
            lines = (
                self.lines.open,
                self.lines.high,
                self.lines.low,
                self.lines.close,
                self.lines.volume,
                self.lines.openinterest,
                self.lines.datetime,
            )
            line0 = lines[0]
            line0_idx = line0._idx
            line0_lencount = line0.lencount
            ready = (
                type(self) is GenericCSVData
                and self.separator == ","
                and self._dt_num_fast == 1
                and self._timeframe < TimeFrame.Days
                and self._datetime_idx == 0
                and self._time_idx == 1
                and p.open == 2
                and p.high == 3
                and p.low == 4
                and p.close == 5
                and p.volume == 6
                and (p.openinterest is None or p.openinterest < 0)
                and all(line.mode != line.QBuffer and line._clock is None for line in lines)
                and all(not line.bindings for line in lines)
                and lines[1]._idx == line0_idx
                and lines[1].lencount == line0_lencount
                and lines[2]._idx == line0_idx
                and lines[2].lencount == line0_lencount
                and lines[3]._idx == line0_idx
                and lines[3].lencount == line0_lencount
                and lines[4]._idx == line0_idx
                and lines[4].lencount == line0_lencount
                and lines[5]._idx == line0_idx
                and lines[5].lencount == line0_lencount
                and lines[6]._idx == line0_idx
                and lines[6].lencount == line0_lencount
            )
        except AttributeError:
            ready = False
            lines = None

        object.__setattr__(self, "_runnext_direct_ymdhms_ohlcv_ready_cache", ready)
        if ready:
            object.__setattr__(self, "_fast_ymdhms_lines", lines)
            object.__setattr__(
                self,
                "_fast_ymdhms_appends",
                (
                    lines[0].array.append,
                    lines[1].array.append,
                    lines[2].array.append,
                    lines[3].array.append,
                    lines[4].array.append,
                    lines[5].array.append,
                    lines[6].array.append,
                ),
            )
            object.__setattr__(self, "_fast_ymdhms_ohlcv_lines", lines[:6])
            object.__setattr__(
                self,
                "_fast_ymdhms_ohlcv_appends",
                tuple(line.array.append for line in lines[:6]),
            )
            object.__setattr__(self, "_fast_ymdhms_datetime_append", lines[6].array.append)
            object.__setattr__(self, "_fast_ymdhms_readline", self.f.readline)
            object.__setattr__(self, "_fast_ymdhms_openinterest_default", lines[5]._default_value)
            object.__setattr__(self, "_fast_ymdhms_tick_dict", self.__dict__)
            object.__setattr__(self, "_load_forward_lines", lines)
            object.__setattr__(self, "_use_direct_ymdhms_load", True)
            object.__setattr__(self, "_fast_ymdhms_ohlcv_fields", True)
            object.__setattr__(self, "_direct_ymdhms_last_datefield", "")
            object.__setattr__(self, "_direct_ymdhms_last_ordinal", 0)
            object.__setattr__(self, "_direct_ymdhms_time_fractions", {})
        return ready

    def _load_direct_ymdhms_ohlcv(self, _float=_FLOAT, _inf=_INF, _neg_inf=_NEG_INF):
        """Load a standard YMD/HMS OHLCV CSV row for single-data runnext."""
        (
            open_line,
            high_line,
            low_line,
            close_line,
            volume_line,
            openinterest_line,
            datetime_line,
        ) = self._fast_ymdhms_lines
        (
            open_append,
            high_append,
            low_append,
            close_append,
            volume_append,
            openinterest_append,
            datetime_append,
        ) = self._fast_ymdhms_appends

        line = self._fast_ymdhms_readline()
        if not line:
            return False

        try:
            direct_layout = (
                line[8] == "," and line[17] == "," and line[11] == ":" and line[14] == ":"
            )
        except IndexError:
            direct_layout = False

        if not direct_layout:
            open_line._idx += 1
            open_line.lencount += 1
            open_append(open_line._default_value)
            high_line._idx += 1
            high_line.lencount += 1
            high_append(high_line._default_value)
            low_line._idx += 1
            low_line.lencount += 1
            low_append(low_line._default_value)
            close_line._idx += 1
            close_line.lencount += 1
            close_append(close_line._default_value)
            volume_line._idx += 1
            volume_line.lencount += 1
            volume_append(volume_line._default_value)
            openinterest_line._idx += 1
            openinterest_line.lencount += 1
            openinterest_append(openinterest_line._default_value)
            datetime_line._idx += 1
            datetime_line.lencount += 1
            datetime_append(datetime_line._default_value)
            loadret = self._loadline(line.rstrip("\n").split(self.separator))
            if not loadret:
                self.backwards(force=True)
                return loadret
            return True

        linetokens = line.split(",", 7)
        datefield = line[:8]
        if datefield == self._direct_ymdhms_last_datefield:
            ordinal = self._direct_ymdhms_last_ordinal
        else:
            year = int(line[0:4])
            month = int(line[4:6])
            day = int(line[6:8])
            year_minus_one = year - 1
            leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
            if (
                year < 1
                or month < 1
                or month > 12
                or day < 1
                or day > (_DAYS_IN_MONTH[month] + (1 if month == 2 and leap else 0))
            ):
                date(year, month, day).toordinal()
            ordinal = (
                year_minus_one * 365
                + year_minus_one // 4
                - year_minus_one // 100
                + year_minus_one // 400
                + _DAYS_BEFORE_MONTH[month]
                + day
            )
            if month > 2 and leap:
                ordinal += 1
            _OBJECT_SETATTR(self, "_direct_ymdhms_last_datefield", datefield)
            _OBJECT_SETATTR(self, "_direct_ymdhms_last_ordinal", ordinal)
        timefield = line[9:17]
        time_fractions = self._direct_ymdhms_time_fractions
        try:
            day_fraction = time_fractions[timefield]
        except KeyError:
            seconds = int(line[9:11]) * 3600 + int(line[12:14]) * 60 + int(line[15:17])
            day_fraction = seconds / _SECONDS_PER_DAY
            time_fractions[timefield] = day_fraction
        dtnum = ordinal + day_fraction

        nullvalue = self._nullvalue
        try:
            open_value = _float(linetokens[2])
            high_value = _float(linetokens[3])
            low_value = _float(linetokens[4])
            close_value = _float(linetokens[5])
            volume_value = _float(linetokens[6])
        except ValueError:
            open_value = _float(linetokens[2] or nullvalue)
            high_value = _float(linetokens[3] or nullvalue)
            low_value = _float(linetokens[4] or nullvalue)
            close_value = _float(linetokens[5] or nullvalue)
            volume_value = _float(linetokens[6] or nullvalue)
        if open_value in (_inf, _neg_inf):
            open_value = open_line._default_value
        if high_value in (_inf, _neg_inf):
            high_value = high_line._default_value
        if low_value in (_inf, _neg_inf):
            low_value = low_line._default_value
        if close_value in (_inf, _neg_inf):
            close_value = close_line._default_value
        if volume_value in (_inf, _neg_inf):
            volume_value = volume_line._default_value

        openinterest_value = self._fast_ymdhms_openinterest_default
        datetime_value = dtnum if dtnum >= 1.0 else 1.0
        next_idx = open_line._idx + 1
        next_lencount = open_line.lencount + 1
        open_line._idx = next_idx
        open_line.lencount = next_lencount
        open_append(open_value)
        high_line._idx = next_idx
        high_line.lencount = next_lencount
        high_append(high_value)
        low_line._idx = next_idx
        low_line.lencount = next_lencount
        low_append(low_value)
        close_line._idx = next_idx
        close_line.lencount = next_lencount
        close_append(close_value)
        volume_line._idx = next_idx
        volume_line.lencount = next_lencount
        volume_append(volume_value)
        openinterest_line._idx = next_idx
        openinterest_line.lencount = next_lencount
        openinterest_append(openinterest_value)
        datetime_line._idx = next_idx
        datetime_line.lencount = next_lencount
        datetime_append(datetime_value)

        tick_values = self._fast_ymdhms_tick_dict
        tick_values["tick_open"] = open_value
        tick_values["tick_high"] = high_value
        tick_values["tick_low"] = low_value
        tick_values["tick_close"] = close_value
        tick_values["tick_volume"] = volume_value
        tick_values["tick_openinterest"] = openinterest_value
        tick_values["tick_last"] = close_value
        tick_values["_tick_direct_filled"] = True
        return True

    def load(self):
        """Load one CSV bar through a narrow no-filter fast path."""
        try:
            use_direct_csv_load = object.__getattribute__(self, "_use_direct_csv_load")
        except AttributeError:
            use_direct_csv_load = (
                object.__getattribute__(self, "_tzinput") is None
                and object.__getattribute__(self, "fromdate") == _NEG_INF
                and object.__getattribute__(self, "todate") == _INF
                and not self._filters
                and not self._barstack
                and not self._barstash
            )
            object.__setattr__(self, "_use_direct_csv_load", use_direct_csv_load)

        if not use_direct_csv_load or self._filters or self._barstack or self._barstash:
            return super().load()

        try:
            forward_lines = self._load_forward_lines
        except AttributeError:
            try:
                lines = self.lines.lines
                if any(line.mode == line.QBuffer or line._clock is not None for line in lines):
                    self._load_forward_lines = None
                    forward_lines = None
                else:
                    forward_lines = tuple(lines)
                    self._load_forward_lines = forward_lines
            except AttributeError:
                self._load_forward_lines = None
                forward_lines = None

        if forward_lines is None:
            self.forward()
        else:
            for line in forward_lines:
                line._idx += 1
                line.lencount += 1
                line.array.append(line._default_value)

        f = self.f
        if f is None:
            self.backwards(force=True)
            return False

        line = f.readline()
        if not line:
            self.backwards(force=True)
            return False

        linetokens = None
        if forward_lines is not None:
            try:
                use_direct_ymdhms_load = object.__getattribute__(self, "_use_direct_ymdhms_load")
            except AttributeError:
                use_direct_ymdhms_load = (
                    type(self) is GenericCSVData
                    and self._dt_num_fast == 1
                    and self._timeframe < TimeFrame.Days
                    and not self._datetime_line.bindings
                    and all(not line.bindings for _, line, _, _ in self._direct_field_cache)
                    and all(not line.bindings for line, _, _, _ in self._direct_missing_field_cache)
                )
                object.__setattr__(self, "_use_direct_ymdhms_load", use_direct_ymdhms_load)

            if use_direct_ymdhms_load:
                linetokens = line.split(self.separator)
                dtfield = linetokens[self._datetime_idx]
                timefield = linetokens[self._time_idx]
                if (
                    dtfield[8:9] == ""
                    and timefield[8:9] == ""
                    and timefield[2:3] == ":"
                    and timefield[5:6] == ":"
                ):
                    try:
                        year = int(dtfield[0:4])
                        month = int(dtfield[4:6])
                        day = int(dtfield[6:8])
                        hour = int(timefield[0:2])
                        minute = int(timefield[3:5])
                        second = int(timefield[6:8])
                    except ValueError:
                        pass
                    else:
                        year_minus_one = year - 1
                        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                        if (
                            year < 1
                            or month < 1
                            or month > 12
                            or day < 1
                            or day > (_DAYS_IN_MONTH[month] + (1 if month == 2 and leap else 0))
                        ):
                            date(year, month, day).toordinal()
                        ordinal = (
                            year_minus_one * 365
                            + year_minus_one // 4
                            - year_minus_one // 100
                            + year_minus_one // 400
                            + _DAYS_BEFORE_MONTH[month]
                            + day
                        )
                        if month > 2 and leap:
                            ordinal += 1
                        dtnum = (
                            float(ordinal) + (hour * 3600 + minute * 60 + second) / _SECONDS_PER_DAY
                        )

                        line_datetime = self._datetime_line
                        datetime_idx = line_datetime._idx
                        if datetime_idx < 0:
                            line_datetime[0] = dtnum
                        else:
                            try:
                                line_datetime.array[datetime_idx] = dtnum if dtnum >= 1.0 else 1.0
                            except IndexError:
                                line_datetime[0] = dtnum

                        nullvalue = self._nullvalue
                        set_attr = object.__setattr__
                        try:
                            fast_ymdhms_ohlcv_fields = self._fast_ymdhms_ohlcv_fields
                        except AttributeError:
                            p = self.p
                            fast_ymdhms_ohlcv_fields = (
                                self.separator == ","
                                and self._datetime_idx == 0
                                and self._time_idx == 1
                                and p.open == 2
                                and p.high == 3
                                and p.low == 4
                                and p.close == 5
                                and p.volume == 6
                                and (p.openinterest is None or p.openinterest < 0)
                            )
                            object.__setattr__(
                                self,
                                "_fast_ymdhms_ohlcv_fields",
                                fast_ymdhms_ohlcv_fields,
                            )
                            if fast_ymdhms_ohlcv_fields:
                                object.__setattr__(
                                    self,
                                    "_fast_ymdhms_ohlcv_lines",
                                    (
                                        self.lines.open,
                                        self.lines.high,
                                        self.lines.low,
                                        self.lines.close,
                                        self.lines.volume,
                                        self.lines.openinterest,
                                    ),
                                )

                        if fast_ymdhms_ohlcv_fields:
                            try:
                                open_value = float(linetokens[2] or nullvalue)
                                high_value = float(linetokens[3] or nullvalue)
                                low_value = float(linetokens[4] or nullvalue)
                                close_value = float(linetokens[5] or nullvalue)
                                volume_value = float(linetokens[6] or nullvalue)
                            except (IndexError, ValueError, TypeError):
                                pass
                            else:
                                (
                                    open_line,
                                    high_line,
                                    low_line,
                                    close_line,
                                    volume_line,
                                    openinterest_line,
                                ) = self._fast_ymdhms_ohlcv_lines
                                if open_value in (_INF, _NEG_INF):
                                    open_value = open_line._default_value
                                if high_value in (_INF, _NEG_INF):
                                    high_value = high_line._default_value
                                if low_value in (_INF, _NEG_INF):
                                    low_value = low_line._default_value
                                if close_value in (_INF, _NEG_INF):
                                    close_value = close_line._default_value
                                if volume_value in (_INF, _NEG_INF):
                                    volume_value = volume_line._default_value

                                openinterest_value = openinterest_line._default_value
                                open_line.array[open_line._idx] = open_value
                                high_line.array[high_line._idx] = high_value
                                low_line.array[low_line._idx] = low_value
                                close_line.array[close_line._idx] = close_value
                                volume_line.array[volume_line._idx] = volume_value
                                openinterest_line.array[openinterest_line._idx] = openinterest_value
                                set_attr(self, "tick_open", open_value)
                                set_attr(self, "tick_high", high_value)
                                set_attr(self, "tick_low", low_value)
                                set_attr(self, "tick_close", close_value)
                                set_attr(self, "tick_volume", volume_value)
                                set_attr(self, "tick_openinterest", openinterest_value)
                                set_attr(self, "tick_last", close_value)
                                set_attr(self, "_tick_direct_filled", True)
                                return True

                        tick_last = None
                        for csvidx, field_line, tick_name, is_last in self._direct_field_cache:
                            csvfield = linetokens[csvidx]
                            if csvfield == "":
                                csvfield = nullvalue
                            value = float(csvfield)
                            if value in (_INF, _NEG_INF):
                                value = field_line._default_value

                            field_idx = field_line._idx
                            if field_idx < 0:
                                field_line[0] = value
                            else:
                                try:
                                    field_line.array[field_idx] = value
                                except IndexError:
                                    field_line[0] = value

                            set_attr(self, tick_name, value)
                            if is_last:
                                tick_last = value

                        for (
                            field_line,
                            value,
                            tick_name,
                            is_last,
                        ) in self._direct_missing_field_cache:
                            field_idx = field_line._idx
                            if field_idx < 0:
                                field_line[0] = value
                            else:
                                try:
                                    field_line.array[field_idx] = value
                                except IndexError:
                                    field_line[0] = value

                            set_attr(self, tick_name, value)
                            if is_last:
                                tick_last = value

                        if tick_last is None:
                            tick_last = self._datetime_line.array[datetime_idx]
                        set_attr(self, "tick_last", tick_last)
                        set_attr(self, "_tick_direct_filled", True)
                        return True

        linetokens = line.rstrip("\n").split(self.separator)
        loadret = self._loadline(linetokens)
        if not loadret:
            self.backwards(force=True)
            return loadret

        return True

    # After reading csv file line, split line's data into linetokens, then further processing
    def _loadline(self, linetokens):
        line_datetime = self._datetime_line

        # Datetime needs special treatment
        # First get specific date based on datetime order
        dtfield = linetokens[self._datetime_idx]
        timefield = linetokens[self._time_idx] if self._has_time else None

        dtnum = None
        if not self._tzinput and self._timeframe < TimeFrame.Days:
            dt_num_fast = self._dt_num_fast
            if dt_num_fast == 1:
                if (
                    dtfield[8:9] == ""
                    and timefield[8:9] == ""
                    and timefield[2:3] == ":"
                    and timefield[5:6] == ":"
                ):
                    try:
                        year = int(dtfield[0:4])
                        month = int(dtfield[4:6])
                        day = int(dtfield[6:8])
                        hour = int(timefield[0:2])
                        minute = int(timefield[3:5])
                        second = int(timefield[6:8])
                    except ValueError:
                        pass
                    else:
                        year_minus_one = year - 1
                        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                        if (
                            year < 1
                            or month < 1
                            or month > 12
                            or day < 1
                            or day > (_DAYS_IN_MONTH[month] + (1 if month == 2 and leap else 0))
                        ):
                            date(year, month, day).toordinal()
                        ordinal = (
                            year_minus_one * 365
                            + year_minus_one // 4
                            - year_minus_one // 100
                            + year_minus_one // 400
                            + _DAYS_BEFORE_MONTH[month]
                            + day
                        )
                        if month > 2 and leap:
                            ordinal += 1
                        seconds = hour * 3600 + minute * 60 + second
                        dtnum = float(ordinal) + seconds / _SECONDS_PER_DAY
            elif dt_num_fast == 2:
                if dtfield[8:9] == "" and timefield[5:6] == "" and timefield[2:3] == ":":
                    try:
                        year = int(dtfield[0:4])
                        month = int(dtfield[4:6])
                        day = int(dtfield[6:8])
                        hour = int(timefield[0:2])
                        minute = int(timefield[3:5])
                    except ValueError:
                        pass
                    else:
                        year_minus_one = year - 1
                        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                        if (
                            year < 1
                            or month < 1
                            or month > 12
                            or day < 1
                            or day > (_DAYS_IN_MONTH[month] + (1 if month == 2 and leap else 0))
                        ):
                            date(year, month, day).toordinal()
                        ordinal = (
                            year_minus_one * 365
                            + year_minus_one // 4
                            - year_minus_one // 100
                            + year_minus_one // 400
                            + _DAYS_BEFORE_MONTH[month]
                            + day
                        )
                        if month > 2 and leap:
                            ordinal += 1
                        seconds = hour * 3600 + minute * 60
                        dtnum = float(ordinal) + seconds / _SECONDS_PER_DAY
            else:
                dtconvert_num = self._dtconvert_num
                if dtconvert_num is not None:
                    dtnum = dtconvert_num(dtfield, timefield)

        if dtnum is None:
            dt = self._dtconvert(dtfield, timefield)

            # If trading interval is greater than or equal to day
            if self._timeframe >= TimeFrame.Days:
                # check if the expected end of session is larger than parsed
                # If _tzinput is True, need to localize date, otherwise date remains original
                if self._tzinput:
                    dtin = self._tzinput.localize(dt)  # pytz compatible-ized
                else:
                    dtin = dt
                # Use date2num to convert date to number
                dtnum = date2num(dtin)  # utc'ize
                # Combine date and sessionend, convert to number
                dteos = datetime.combine(dt.date(), self._sessionend)
                dteosnum = self.date2num(dteos)  # utc'ize
                # If number converted from combined sessionend date is greater than converted date number, use former number as time
                if dteosnum > dtnum:
                    dtnum = dteosnum
                # If not greater, if self._tzinput is True, directly convert dt to time, if not True, use original dtnum
                else:
                    # Avoid reconversion if already converted dtin == dt
                    dtnum = date2num(dt) if self._tzinput else dtnum
            # If trading cycle is less than day, convert time directly
            else:
                dtnum = date2num(dt)

        if line_datetime.bindings:
            line_datetime[0] = dtnum
        else:
            idx = line_datetime._idx
            if idx < 0:
                line_datetime[0] = dtnum
            else:
                try:
                    line_datetime.array[idx] = dtnum if dtnum >= 1.0 else 1.0
                except IndexError:
                    line_datetime[0] = dtnum

        if not self._tzinput and (dtnum < self.fromdate or dtnum > self.todate):
            return True

        # Process cached fields
        nullvalue = self._nullvalue
        for csvidx, line in self._field_cache:
            csvfield = linetokens[csvidx]
            if csvfield == "":
                csvfield = nullvalue
            value = float(csvfield)
            if value in (_INF, _NEG_INF):
                value = line._default_value

            if line.bindings:
                line[0] = value
                continue

            idx = line._idx
            if idx < 0:
                line[0] = value
                continue

            try:
                line.array[idx] = value
            except IndexError:
                line[0] = value

        for line, value in self._missing_field_cache:
            if line.bindings:
                line[0] = value
                continue

            idx = line._idx
            if idx < 0:
                line[0] = value
                continue

            try:
                line.array[idx] = value
            except IndexError:
                line[0] = value

        return True


class GenericCSV(feed.CSVFeedBase):
    """Generic CSV feed class.

    Wrapper class for GenericCSVData feed functionality.
    """

    DataCls = GenericCSVData
