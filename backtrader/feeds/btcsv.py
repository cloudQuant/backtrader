#!/usr/bin/env python

from datetime import date, datetime, time

from .. import feed
from ..utils import date2num


# Parse a custom CSV data, mainly for testing.
class BacktraderCSVData(feed.CSVDataBase):
    """
    Parses a self-defined CSV Data used for testing.

    Specific parameters:

      - ``dataname``: The filename to parse or a file-like object
    """

    # Process each row of data
    def _loadline(self, linetokens):
        # Iterate through each row of data
        itoken = iter(linetokens)
        # Time processing
        dttxt = next(itoken)  # The Format is YYYY-MM-DD - skip char 4 and 7
        dt = date(int(dttxt[0:4]), int(dttxt[5:7]), int(dttxt[8:10]))
        # If there are 8 columns, time exists, second column is time, process time, if not 8 columns, no time, time uses sessionend
        if len(linetokens) == 8:
            tmtxt = next(itoken)  # Format if present HH:MM:SS, skip 3 and 6
            tm = time(int(tmtxt[0:2]), int(tmtxt[3:5]), int(tmtxt[6:8]))
        else:
            tm = self.p.sessionend  # end of the session parameter
        # Set each line separately
        self.lines.datetime[0] = date2num(datetime.combine(dt, tm))
        self.lines.open[0] = float(next(itoken))
        self.lines.high[0] = float(next(itoken))
        self.lines.low[0] = float(next(itoken))
        self.lines.close[0] = float(next(itoken))
        self.lines.volume[0] = float(next(itoken))
        self.lines.openinterest[0] = float(next(itoken))

        return True


class BacktraderCSV(feed.CSVFeedBase):
    # Class, DataCls is set to BacktraderCSVData class
    DataCls = BacktraderCSVData
