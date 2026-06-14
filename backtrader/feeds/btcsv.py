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
        # Set each line separately
        line_datetime[0] = dtnum
        line_open[0] = float(linetokens[offset])
        line_high[0] = float(linetokens[offset + 1])
        line_low[0] = float(linetokens[offset + 2])
        line_close[0] = float(linetokens[offset + 3])
        line_volume[0] = float(linetokens[offset + 4])
        line_openinterest[0] = float(linetokens[offset + 5])

        return True


class BacktraderCSV(feed.CSVFeedBase):
    """Backtrader CSV feed class.

    Wrapper class for BacktraderCSVData feed functionality.
    """

    DataCls = BacktraderCSVData
