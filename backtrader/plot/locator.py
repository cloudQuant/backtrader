#!/usr/bin/env python

"""
Redefine/Override matplotlib locators to make them work with index base x-axis
which can be converted from/to dates
"""

import datetime
import traceback
import warnings

import numpy as np
from dateutil.relativedelta import relativedelta
from matplotlib.dates import (
    HOURS_PER_DAY,
    MIN_PER_HOUR,
    MONTHS_PER_YEAR,
)
from matplotlib.dates import AutoDateFormatter as ADFormatter
from matplotlib.dates import AutoDateLocator as ADLocator
from matplotlib.dates import (
    MicrosecondLocator,
)
from matplotlib.dates import RRuleLocator as RRLocator
from matplotlib.dates import (
    num2date,
    rrulewrapper,
)


def _idx2dt(idx, dates, tz):
    """Convert an index to a datetime object.

    Args:
        idx: Index value or datetime.date object.
        dates: Array of date values.
        tz: Timezone to use for conversion.

    Returns:
        datetime.datetime: The corresponding datetime object.
    """
    if isinstance(idx, datetime.date):
        return idx

    ldates = len(dates)

    idx = int(round(idx))
    if idx >= ldates:
        idx = ldates - 1
    if idx < 0:
        idx = 0

    return num2date(dates[idx], tz)


class RRuleLocator(RRLocator):
    """Locator for date-based ticks using rrules.

    This locator extends matplotlib's RRuleLocator to work with index-based
    x-axis that can be converted from/to dates. It handles the conversion
    between data indices and datetime objects.

    Attributes:
        _dates: Array of date values for index conversion.
    """

    def __init__(self, dates, o, tz=None):
        """Initialize the RRuleLocator.

        Args:
            dates: Array of date values for index conversion.
            o: RRule object defining the tick frequency and rules.
            tz: Timezone to use for datetime conversion. Defaults to None.
        """
        self._dates = dates
        super().__init__(o, tz)

    def datalim_to_dt(self):
        """Convert an axis data interval to datetime objects.

        Returns:
            tuple: A pair of datetime objects representing the data limits.
        """
        dmin, dmax = self.axis.get_data_interval()
        if dmin > dmax:
            dmin, dmax = dmax, dmin

        return (_idx2dt(dmin, self._dates, self.tz), _idx2dt(dmax, self._dates, self.tz))

    def viewlim_to_dt(self):
        """Convert the view interval to datetime objects.

        Returns:
            tuple: A pair of datetime objects representing the view limits.
        """
        vmin, vmax = self.axis.get_view_interval()
        if vmin > vmax:
            vmin, vmax = vmax, vmin

        return (_idx2dt(vmin, self._dates, self.tz), _idx2dt(vmax, self._dates, self.tz))

    def tick_values(self, vmin, vmax):
        """Return the tick values for the given range.

        Args:
            vmin: Minimum value of the range.
            vmax: Maximum value of the range.

        Returns:
            list: List of indices corresponding to tick positions.
        """
        import bisect

        dtnums = super().tick_values(vmin, vmax)
        return [bisect.bisect_left(self._dates, x) for x in dtnums]


class AutoDateLocator(ADLocator):
    """Locator for automatic date-based tick positioning.

    This locator extends matplotlib's AutoDateLocator to work with index-based
    x-axis that can be converted from/to dates. It automatically selects the
    appropriate tick frequency based on the date range.

    Attributes:
        _dates: Array of date values for index conversion.
    """

    def __init__(self, dates, *args, **kwargs):
        """Initialize the AutoDateLocator.

        Args:
            dates: Array of date values for index conversion.
            *args: Additional positional arguments passed to parent class.
            **kwargs: Additional keyword arguments passed to parent class.
        """
        self._dates = dates
        super().__init__(*args, **kwargs)

    def datalim_to_dt(self):
        """Convert an axis data interval to datetime objects.

        Returns:
            tuple: A pair of datetime objects representing the data limits.
        """
        dmin, dmax = self.axis.get_data_interval()
        if dmin > dmax:
            dmin, dmax = dmax, dmin

        return (_idx2dt(dmin, self._dates, self.tz), _idx2dt(dmax, self._dates, self.tz))

    def viewlim_to_dt(self):
        """Convert the view interval to datetime objects.

        Returns:
            tuple: A pair of datetime objects representing the view limits.
        """
        vmin, vmax = self.axis.get_view_interval()
        if vmin > vmax:
            vmin, vmax = vmax, vmin

        return (_idx2dt(vmin, self._dates, self.tz), _idx2dt(vmax, self._dates, self.tz))

    def tick_values(self, vmin, vmax):
        """Return the tick values for the given range.

        Args:
            vmin: Minimum value of the range.
            vmax: Maximum value of the range.

        Returns:
            list: List of indices corresponding to tick positions.
        """
        import bisect

        dtnums = super().tick_values(vmin, vmax)
        return [bisect.bisect_left(self._dates, x) for x in dtnums]

    def get_locator(self, dmin, dmax):
        """Pick the best locator based on a distance.

        Args:
            dmin: Minimum datetime value.
            dmax: Maximum datetime value.

        Returns:
            matplotlib.ticker.Locator: The appropriate locator for the date range.
        """
        delta = relativedelta(dmax, dmin)
        tdelta = dmax - dmin

        # take absolute difference
        if dmin > dmax:
            delta = -delta
            tdelta = -tdelta

        # The following uses a mix of calls to relativedelta and timedelta
        # methods because there is incomplete overlap in the functionality of
        # these similar functions, and it's best to avoid doing our own math
        # whenever possible.
        numYears = float(delta.years)
        numMonths = (numYears * MONTHS_PER_YEAR) + delta.months
        numDays = tdelta.days  # Avoids estimates of days/month, days/year
        numHours = (numDays * HOURS_PER_DAY) + delta.hours
        numMinutes = (numHours * MIN_PER_HOUR) + delta.minutes
        numSeconds = np.floor(tdelta.total_seconds())
        numMicroseconds = np.floor(tdelta.total_seconds() * 1e6)

        nums = [numYears, numMonths, numDays, numHours, numMinutes, numSeconds, numMicroseconds]

        use_rrule_locator = [True] * 6 + [False]

        # Default setting of bymonth, etc. to pass to rrule
        # [unused (for year), bymonth, bymonthday, byhour, byminute,
        #  bysecond, unused (for microseconds)]
        byranges = [None, 1, 1, 0, 0, 0, None]

        usemicro = False  # use as a flag to avoid raising an exception

        # Loop over all the frequencies and try to find one that gives at
        # least a minticks tick positions.  Once this is found, look for
        # an interval from a list specific to that frequency that gives no
        # more than maxticks tick positions. Also, set up some ranges
        # (bymonth, etc.) as appropriate to be passed to rrulewrapper.
        for i, (freq, num) in enumerate(zip(self._freqs, nums)):
            # If this particular frequency doesn't give enough ticks, continue
            if num < self.minticks:
                # Since we're not using this particular frequency, set
                # the corresponding by_ to None so the rrule can act as
                # appropriate
                byranges[i] = None
                continue

            # Find the first available interval that doesn't give too many
            # ticks
            for interval in self.intervald[freq]:
                if num <= interval * (self.maxticks[freq] - 1):
                    break
            else:
                # We went through the whole loop without breaking, default to
                # the last interval in the list and raise a warning
                warnings.warn(
                    "AutoDateLocator was unable to pick an "
                    "appropriate interval for this date range. "
                    "It may be necessary to add an interval value "
                    "to the AutoDateLocator's intervald dictionary."
                    " Defaulting to {}.".format(interval)
                )

            # Set some parameters as appropriate
            self._freq = freq

            if self._byranges[i] and self.interval_multiples:
                byranges[i] = self._byranges[i][::interval]
                interval = 1
            else:
                byranges[i] = self._byranges[i]

            # We found what frequency to use
            break
        else:
            if False:
                raise ValueError("No sensible date limit could be found in the AutoDateLocator.")
            else:
                usemicro = True

        if not usemicro and use_rrule_locator[i]:
            _, bymonth, bymonthday, byhour, byminute, bysecond, _ = byranges

            rrule = rrulewrapper(
                self._freq,
                interval=interval,
                dtstart=dmin,
                until=dmax,
                bymonth=bymonth,
                bymonthday=bymonthday,
                byhour=byhour,
                byminute=byminute,
                bysecond=bysecond,
            )

            locator = RRuleLocator(self._dates, rrule, self.tz)
        else:
            if usemicro:
                interval = 1  # not set because the for else: was met
            locator = MicrosecondLocator(interval, tz=self.tz)

        locator.set_axis(self.axis)
        # print(dir(locator))
        try:
            # try for matplotlib < 3.6.0
            locator.set_view_interval(*self.axis.get_view_interval())
            locator.set_data_interval(*self.axis.get_data_interval())
        except Exception as e:
            traceback.format_exception(e)
            try:
                # try for matplotlib >= 3.6.0
                self.axis.set_view_interval(*self.axis.get_view_interval())
                self.axis.set_data_interval(*self.axis.get_data_interval())
                locator.set_axis(self.axis)
            except Exception as e:
                traceback.format_exception(e)
        return locator


class AutoDateFormatter(ADFormatter):
    """Formatter for automatic date-based tick labels.

    This formatter extends matplotlib's AutoDateFormatter to work with
    index-based x-axis that can be converted from/to dates. It automatically
    formats date labels based on the tick frequency.

    Attributes:
        _dates: Array of date values for index conversion.
    """

    def __init__(self, dates, locator, tz=None, defaultfmt="%Y-%m-%d"):
        """Initialize the AutoDateFormatter.

        Args:
            dates: Array of date values for index conversion.
            locator: The locator instance to use for tick positioning.
            tz: Timezone to use for datetime conversion. Defaults to None.
            defaultfmt: Default format string for dates. Defaults to "%Y-%m-%d".
        """
        self._dates = dates
        super().__init__(locator, tz, defaultfmt)

    def __call__(self, x, pos=None):
        """Return the label for time x at position pos.

        Args:
            x: The index value to convert to a date label.
            pos: The position of the tick. Defaults to None.

        Returns:
            str: The formatted date label.
        """
        x = int(round(x))
        ldates = len(self._dates)
        if x >= ldates:
            x = ldates - 1

        if x < 0:
            x = 0

        return super()
