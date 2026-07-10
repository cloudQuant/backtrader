#!/usr/bin/env python
"""Backtrader CSV Data Feed Module - Test CSV format.

This module provides the BacktraderCSVData feed for parsing
a custom CSV format used for testing.

Classes:
    BacktraderCSVData: Parses backtrader test CSV format.

Example:
    >>> data = bt.feeds.BacktraderCSVData(dataname='test.csv')
    >>> cerebro.adddata(data)
"""

import math
from datetime import date

from .. import feed

_HOURS_PER_DAY = 24.0
_MINUTES_PER_DAY = 1440.0
_SECONDS_PER_DAY = 86400.0
_MICROSECONDS_PER_DAY = 86400000000.0
_INF = float("inf")
_NEG_INF = float("-inf")


def _set_current_value(line, value):
    """Set the current line slot, falling back when binding propagation is needed."""
    if value in (_INF, _NEG_INF):
        value = line._default_value

    if line.bindings:
        line[0] = value
        return

    idx = line._idx
    if idx < 0:
        line[0] = value
        return

    try:
        line.array[idx] = value
    except IndexError:
        line[0] = value


class BacktraderCSVData(feed.CSVDataBase):
    """
    Parses a self-defined CSV Data used for testing.

    Specific parameters:

      - ``dataname``: The filename to parse or a file-like object
    """

    def _loadline(self, linetokens):
        """Parse a line from the CSV file.

        Args:
            linetokens: List of tokenized CSV values.

        Returns:
            True if line was successfully parsed.
        """
        try:
            (
                line_datetime,
                line_open,
                line_high,
                line_low,
                line_close,
                line_volume,
                line_openinterest,
            ) = self._btcsv_line_refs
        except AttributeError:
            lines = self.lines
            line_datetime = lines.datetime
            line_open = lines.open
            line_high = lines.high
            line_low = lines.low
            line_close = lines.close
            line_volume = lines.volume
            line_openinterest = lines.openinterest
            self._btcsv_line_refs = (
                line_datetime,
                line_open,
                line_high,
                line_low,
                line_close,
                line_volume,
                line_openinterest,
            )

        # Date processing
        dttxt = linetokens[0]  # The Format is YYYY-MM-DD - skip char 4 and 7
        year = int(dttxt[0:4])
        month = int(dttxt[5:7])
        day = int(dttxt[8:10])
        dtnum = float(date(year, month, day).toordinal())
        # If there are 8 columns, time exists, second column is time, process time, if not 8 columns, no time, time uses sessionend
        if len(linetokens) == 8:
            tmtxt = linetokens[1]  # Format if present HH:MM:SS, skip 3 and 6
            dtnum = math.fsum(
                (
                    dtnum,
                    int(tmtxt[0:2]) / _HOURS_PER_DAY,
                    int(tmtxt[3:5]) / _MINUTES_PER_DAY,
                    int(tmtxt[6:8]) / _SECONDS_PER_DAY,
                    0.0,
                )
            )
            offset = 2
        else:
            tm = self.p.sessionend  # end of the session parameter
            dtnum = math.fsum(
                (
                    dtnum,
                    tm.hour / _HOURS_PER_DAY,
                    tm.minute / _MINUTES_PER_DAY,
                    tm.second / _SECONDS_PER_DAY,
                    tm.microsecond / _MICROSECONDS_PER_DAY,
                )
            )
            offset = 1
        open_value = float(linetokens[offset])
        high_value = float(linetokens[offset + 1])
        low_value = float(linetokens[offset + 2])
        close_value = float(linetokens[offset + 3])
        volume_value = float(linetokens[offset + 4])
        openinterest_value = float(linetokens[offset + 5])

        idx_datetime = line_datetime._idx
        idx_open = line_open._idx
        idx_high = line_high._idx
        idx_low = line_low._idx
        idx_close = line_close._idx
        idx_volume = line_volume._idx
        idx_openinterest = line_openinterest._idx
        if (
            idx_datetime >= 0
            and idx_open >= 0
            and idx_high >= 0
            and idx_low >= 0
            and idx_close >= 0
            and idx_volume >= 0
            and idx_openinterest >= 0
            and not line_datetime.bindings
            and not line_open.bindings
            and not line_high.bindings
            and not line_low.bindings
            and not line_close.bindings
            and not line_volume.bindings
            and not line_openinterest.bindings
        ):
            if open_value in (_INF, _NEG_INF):
                open_value = line_open._default_value
            if high_value in (_INF, _NEG_INF):
                high_value = line_high._default_value
            if low_value in (_INF, _NEG_INF):
                low_value = line_low._default_value
            if close_value in (_INF, _NEG_INF):
                close_value = line_close._default_value
            if volume_value in (_INF, _NEG_INF):
                volume_value = line_volume._default_value
            if openinterest_value in (_INF, _NEG_INF):
                openinterest_value = line_openinterest._default_value

            try:
                line_datetime.array[idx_datetime] = dtnum
                line_open.array[idx_open] = open_value
                line_high.array[idx_high] = high_value
                line_low.array[idx_low] = low_value
                line_close.array[idx_close] = close_value
                line_volume.array[idx_volume] = volume_value
                line_openinterest.array[idx_openinterest] = openinterest_value
                return True
            except IndexError:
                pass

        # Fallback preserves binding propagation and LineBuffer boundary handling.
        set_current = _set_current_value
        set_current(line_datetime, dtnum)
        set_current(line_open, open_value)
        set_current(line_high, high_value)
        set_current(line_low, low_value)
        set_current(line_close, close_value)
        set_current(line_volume, volume_value)
        set_current(line_openinterest, openinterest_value)

        return True


class BacktraderCSV(feed.CSVFeedBase):
    """Backtrader CSV feed class.

    Wrapper class for BacktraderCSVData feed functionality.
    """

    DataCls = BacktraderCSVData
