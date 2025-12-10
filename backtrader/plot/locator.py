#!/usr/bin/env python

"""
Redefine/Override matplotlib locators to make them work with index base x-axis
which can be converted from/to dates
"""

import datetime

from matplotlib.dates import AutoDateLocator as ADLocator
from matplotlib.dates import RRuleLocator as RRLocator
from matplotlib.dates import AutoDateFormatter as ADFormatter

from matplotlib.dates import (
    HOURS_PER_DAY,
    MIN_PER_HOUR,
    MONTHS_PER_YEAR,
    num2date,
    rrulewrapper,
    MicrosecondLocator,
)

from dateutil.relativedelta import relativedelta
import numpy as np
import warnings
import traceback


def _idx2dt(idx, dates, tz):
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
    def __init__(self, dates, o, tz=None):
        self._dates = dates
        super().__init__(o, tz)

    def datalim_to_dt(self):
        """
        Convert an axis data interval to datetime objects.
        """
        dmin, dmax = self.axis.get_data_interval()
        if dmin > dmax:
            dmin, dmax = dmax, dmin

        return (_idx2dt(dmin, self._dates, self.tz), _idx2dt(dmax, self._dates, self.tz))

    def viewlim_to_dt(self):
        """
        Converts the view interval to datetime objects.
        """
        vmin, vmax = self.axis.get_view_interval()
        if vmin > vmax:
            vmin, vmax = vmax, vmin

        return (_idx2dt(vmin, self._dates, self.tz), _idx2dt(vmax, self._dates, self.tz))

    def tick_values(self, vmin, vmax):
        import bisect

        dtnums = super().tick_values(vmin, vmax)
        return [bisect.bisect_left(self._dates, x) for x in dtnums]


class AutoDateLocator(ADLocator):
    def __init__(self, dates, *args, **kwargs):
        self._dates = dates
        super().__init__(*args, **kwargs)

    def datalim_to_dt(self):
        """
        Convert an axis data interval to datetime objects.
        """
        dmin, dmax = self.axis.get_data_interval()
        if dmin > dmax:
            dmin, dmax = dmax, dmin

        return (_idx2dt(dmin, self._dates, self.tz), _idx2dt(dmax, self._dates, self.tz))

    def viewlim_to_dt(self):
        """
        Converts the view interval to datetime objects.
        """
        vmin, vmax = self.axis.get_view_interval()
        if vmin > vmax:
            vmin, vmax = vmax, vmin

        return (_idx2dt(vmin, self._dates, self.tz), _idx2dt(vmax, self._dates, self.tz))

    def tick_values(self, vmin, vmax):
        import bisect

        dtnums = super().tick_values(vmin, vmax)
        return [bisect.bisect_left(self._dates, x) for x in dtnums]

    def get_locator(self, dmin, dmax):
        """Pick the best locator based on a distance."""
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
    def __init__(self, dates, locator, tz=None, defaultfmt="%Y-%m-%d"):
        self._dates = dates
        super().__init__(locator, tz, defaultfmt)

    def __call__(self, x, pos=None):
        """Return the label for time x at position pos"""
        x = int(round(x))
        ldates = len(self._dates)
        if x >= ldates:
            x = ldates - 1

        if x < 0:
            x = 0

        ix = self._dates[x]

        return super()
