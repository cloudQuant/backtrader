#!/usr/bin/env python
"""Plot Formatters Module - Custom formatters for matplotlib plots.

This module provides custom formatters for matplotlib charts used in backtrader
plotting, including volume formatters and date formatters that work with
backtrader's internal date representation.

Classes:
    MyVolFormatter: Custom formatter for volume axis with K/M/B suffixes.
    MyDateFormatter: Custom formatter for date axis.

Functions:
    patch_locator: Patch date locator with custom date limits.
    patch_formatter: Patch date formatter with custom date handling.
    getlocator: Create and patch date locator and formatter.

Example:
    >>> from backtrader.plot.formatters import MyVolFormatter, MyDateFormatter
    >>> vol_fmt = MyVolFormatter(volmax=1000000)
    >>> date_fmt = MyDateFormatter(dates, fmt='%Y-%m-%d')
"""

import matplotlib.dates as mdates
import matplotlib.ticker as mplticker

from ..utils import num2date


class MyVolFormatter(mplticker.Formatter):
    """Custom formatter for volume axis labels with magnitude suffixes.

    This formatter formats volume values with appropriate suffixes (K, M, B, T, P)
    based on the maximum volume value. For example, volumes in the thousands
    will be displayed with 'K' suffix, millions with 'M' suffix, etc.

    Attributes:
        Suffixes: List of suffixes for different magnitudes.

    Example:
        >>> formatter = MyVolFormatter(volmax=1500000)
        >>> label = formatter(1000000, 0)
        >>> print(label)
        1M
    """

    Suffixes = ["", "K", "M", "G", "T", "P"]

    def __init__(self, volmax):
        """Initialize the volume formatter.

        Args:
            volmax: Maximum volume value to be displayed. This determines
                the appropriate suffix and divisor for formatting.
        """
        self.volmax = volmax
        magnitude = 0
        self.divisor = 1.0
        while abs(volmax / self.divisor) >= 1000:
            magnitude += 1
            self.divisor *= 1000.0

        self.suffix = self.Suffixes[magnitude]

    def __call__(self, y, pos=0):
        """Return the label for time x at position pos"""

        if y > self.volmax * 1.20:
            return ""

        y = int(y / self.divisor)
        return "%d%s" % (y, self.suffix)


class MyDateFormatter(mplticker.Formatter):
    """Custom formatter for date axis labels.

    This formatter formats dates using backtrader's internal date representation
    and displays them with the specified format string. It handles index-based
    date lookups and ensures valid index bounds.

    Example:
        >>> formatter = MyDateFormatter(dates, fmt='%Y-%m-%d')
        >>> label = formatter(100, 0)
        >>> print(label)
        2020-01-15
    """

    def __init__(self, dates, fmt="%Y-%m-%d"):
        """Initialize the date formatter.

        Args:
            dates: Array or sequence of dates in backtrader's internal format.
            fmt: strftime-compatible format string for date display.
                Defaults to '%Y-%m-%d'.
        """
        self.dates = dates
        self.lendates = len(dates)
        self.fmt = fmt

    def __call__(self, x, pos=0):
        """Return the label for time x at position pos"""
        ind = int(round(x))
        if ind >= self.lendates:
            ind = self.lendates - 1

        if ind < 0:
            ind = 0

        return num2date(self.dates[ind]).strftime(self.fmt)


def patch_locator(locator, xdates):
    """Patch a date locator with custom date limit conversion methods.

    This function patches the locator's datalim_to_dt and viewlim_to_dt methods
    to work with backtrader's internal date array (xdates) instead of using
    matplotlib's default date conversion.

    Args:
        locator: matplotlib date locator instance to patch.
        xdates: Array of dates in backtrader's internal format.
    """
    def _patched_datalim_to_dt(self):
        dmin, dmax = self.axis.get_data_interval()

        # proxy access to xdates
        dmin, dmax = xdates[int(dmin)], xdates[min(int(dmax), len(xdates) - 1)]

        a, b = num2date(dmin, self.tz), num2date(dmax, self.tz)
        return a, b

    def _patched_viewlim_to_dt(self):
        vmin, vmax = self.axis.get_view_interval()

        # proxy access to xdates
        vmin, vmax = xdates[int(vmin)], xdates[min(int(vmax), len(xdates) - 1)]
        a, b = num2date(vmin, self.tz), num2date(vmax, self.tz)
        return a, b

    # patch the instance with a bound method
    bound_datalim = _patched_datalim_to_dt.__get__(locator, locator.__class__)
    locator.datalim_to_dt = bound_datalim

    # patch the instance with a bound method
    bound_viewlim = _patched_viewlim_to_dt.__get__(locator, locator.__class__)
    locator.viewlim_to_dt = bound_viewlim


def patch_formatter(formatter, xdates):
    """Patch a date formatter with custom date formatting logic.

    This function patches the formatter's __call__ method to work with
    backtrader's internal date array (xdates) for index-based date lookups.

    Args:
        formatter: matplotlib date formatter instance to patch.
        xdates: Array of dates in backtrader's internal format.
    """
    def newcall(self, x, pos=0):
        if False and x < 0:
            raise ValueError(
                "DateFormatter found a value of x=0, which is "
                "an illegal date.  This usually occurs because "
                "you have not informed the axis that it is "
                "plotting dates, e.g., with ax.xaxis_date()"
            )

        x = xdates[int(x)]
        dt = num2date(x, self.tz)
        return self.strftime(dt, self.fmt)

    bound_call = newcall.__get__(formatter, formatter.__class__)
    formatter.__call__ = bound_call


def getlocator(xdates, numticks=5, tz=None):
    """Create a patched date locator and formatter for backtrader plots.

    This function creates matplotlib date locator and formatter instances
    patched to work with backtrader's internal date representation.

    Args:
        xdates: Array of dates in backtrader's internal format.
        numticks: Target number of ticks on the axis. Defaults to 5.
        tz: Timezone for date conversion. Defaults to None (local timezone).

    Returns:
        A tuple of (locator, formatter) where:
            - locator: Patched matplotlib date locator instance.
            - formatter: Patched matplotlib date formatter instance.
    """
    span = xdates[-1] - xdates[0]

    locator, formatter = mdates.date_ticker_factory(span=span, tz=tz, numticks=numticks)

    patch_locator(locator, xdates)
    patch_formatter(formatter, xdates)
    return locator, formatter
