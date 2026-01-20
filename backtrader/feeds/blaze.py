#!/usr/bin/env python
"""Blaze Data Feed Module - Blaze data interface.

This module provides the BlazeData feed for interfacing with Blaze
Data objects for out-of-core analytics.

Classes:
    BlazeData: Blaze Data object feed.

Example:
    >>> import blaze as bz
    >>> data = bz.Data('data.csv')
    >>> feed = bt.feeds.BlazeData(dataname=data)
    >>> cerebro.adddata(feed)
"""

from ..feed import DataBase
from ..utils import date2num


# This class is for backtrader to interface with Blaze data
# blaze introduction: https://blaze.readthedocs.io/en/latest/index.html
class BlazeData(DataBase):
    """
    Support for `Blaze <blaze.pydata.org>`_ ``Data`` objects.

    Only numeric indices to columns are supported.

    Note:

      - The ``dataname`` parameter is a blaze ``Data`` object

      - A negative value in any of the parameters for the Data lines
        indicates it's not present in the DataFrame
        it is
    """

    # Parameters
    params = (
        # datetime must be present
        ("datetime", 0),
        # pass -1 for any of the following to indicate absence
        ("open", 1),
        ("high", 2),
        ("low", 3),
        ("close", 4),
        ("volume", 5),
        ("openinterest", 6),
    )

    # Column names
    datafields = ["datetime", "open", "high", "low", "close", "volume", "openinterest"]

    def __init__(self):
        """Initialize the Blaze data feed.

        Sets up internal row iterator.
        """
        self._rows = None

    def start(self):
        """Start the Blaze data feed.

        Initializes the row iterator from the dataname.
        """
        super().start()

        # reset the iterator on each start
        self._rows = iter(self.p.dataname)

    # Load data
    def _load(self):
        # Try to get next row data, if doesn't exist, raise error, return False, indicating data loading finished
        try:
            row = next(self._rows)
        except StopIteration:
            return False

        # Set the standard datafields - except for datetime
        # Set other data except time, similar to CSV operations
        for datafield in self.datafields[1:]:
            # get the column index
            colidx = getattr(self.params, datafield)

            if colidx < 0:
                # column not present -- skip
                continue

            # get the line to be set
            line = getattr(self.lines, datafield)
            line[0] = row[colidx]

        # datetime - assumed blaze always serves a native datetime.datetime
        # Process time part, this operation is much simpler compared to CSV part, efficiency should also be higher, theoretically faster than CSV
        # Get index of first column of data
        colidx = getattr(self.params, self.datafields[0])
        # Get time data
        dt = row[colidx]
        # Convert time to number
        dtnum = date2num(dt)

        # get the line to be set
        # Get the line for this column, then add data
        line = getattr(self.lines, self.datafields[0])
        line[0] = dtnum

        # Done ... return
        return True
