#!/usr/bin/env python
"""Day Steps Filter Module - Bar replay simulation.

This module provides the BarReplayerOpen filter for splitting bars
to simulate replay behavior.

Classes:
    BarReplayerOpen: Splits bars into open and OHLC parts.

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> data.addfilter(bt.filters.BarReplayerOpen())
    >>> cerebro.adddata(data)
"""


class BarReplayerOpen:
    """
    This filters splits a bar in two parts:

      - ``Open``: the opening price of the bar will be used to deliver an
        initial price bar in which the four components (OHLC) are equal

        The volume/openinterest fields are zero for this initial bar

      - ``OHLC``: the original bar is delivered complete with the original
        ``volume``/``openinterest``

    The split simulates a replay without the need to use the *replay* filter.
    """

    def __init__(self, data):
        """Initialize the BarReplayerOpen filter.

        Args:
            data: The data feed to apply the filter to.
                  The filter sets resampling=1 and replaying=True on the data.
        """
        self.pendingbar = None
        data.resampling = 1
        data.replaying = True

    def __call__(self, data):
        """Process the data feed to split bars into open and OHLC parts.

        This method is called for each bar in the data feed. It splits the bar
        into two parts - an initial bar with only the open price (OHLC=Open)
        and the original OHLC bar. This simulates intraday replay behavior.

        Args:
            data: The data feed containing the bar to process.

        Returns:
            bool: True if the length of the stream was changed,
                  False if it remained unchanged.
        """
        ret = True

        # Make a copy of the new bar and remove it from stream
        newbar = [data.lines[i][0] for i in range(data.size())]
        data.backwards()  # remove the copied bar from stream

        openbar = newbar[:]  # Make an open only bar
        o = newbar[data.Open]
        for field_idx in [data.High, data.Low, data.Close]:
            openbar[field_idx] = o

        # Nullify Volume/OpenInteres at the open
        openbar[data.Volume] = 0.0
        openbar[data.OpenInterest] = 0.0

        # Overwrite the new data bar with our pending data - except start point
        if self.pendingbar is not None:
            data._updatebar(self.pendingbar)
            ret = False

        self.pendingbar = newbar  # update the pending bar to the new bar
        data._add2stack(openbar)  # Add the openbar to the stack for processing

        return ret  # the length of the stream was not changed

    def last(self, data):
        """Called when the data is no longer producing bars
        Can be called multiple times. It has the chance to (for example)
        produce extra bars"""
        if self.pendingbar is not None:
            data.backwards()  # remove delivered open bar
            data._add2stack(self.pendingbar)  # add remaining
            self.pendingbar = None  # No further action
            return True  # something delivered

        return False  # nothing delivered here


# Alias
DayStepsFilter = BarReplayerOpen
