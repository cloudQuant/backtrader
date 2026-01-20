#!/usr/bin/env python
"""Annual Return Analyzer Module - Annual return calculation.

This module provides the AnnualReturn analyzer for calculating
year-by-year returns of a strategy.

Classes:
    AnnualReturn: Analyzer that calculates annual returns.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='annret')
    >>> results = cerebro.run()
    >>> print(results[0].analyzers.annret.get_analysis())
"""

from collections import OrderedDict

from ..analyzer import Analyzer
from ..utils.date import num2date
from ..utils.py3 import range


# Calculate annual returns. The algorithm implementation is somewhat complex, so a pandas-based version MyAnnualReturn was written later with much simpler logic
class AnnualReturn(Analyzer):
    """
    This analyzer calculates the AnnualReturns by looking at the beginning
    and end of the year

    Params:

      - (None)

    Member Attributes:

      - ``rets``: list of calculated annual returns

      - ``ret``: dictionary (key: year) of annual returns

    **get_analysis**:

      - Returns a dictionary of annual returns (key: year)
    """

    def __init__(self):
        """Initialize the AnnualReturn analyzer.

        Initializes cache lists for storing dates and values during backtesting.
        """
        super().__init__()
        # Cache data
        self._dt_cache = []
        self._value_cache = []

    def next(self):
        """Cache current date and account value on each bar.

        Stores the current datetime and portfolio value for later
        annual return calculation.
        """
        # Cache current date and account value each time next is called
        dt_val = self.data.datetime[0]
        value_val = self.strategy.broker.getvalue()
        self._dt_cache.append(dt_val)
        self._value_cache.append(value_val)

    def stop(self):
        """Calculate annual returns from cached data.

        Iterates through cached date-value pairs to calculate returns
        for each calendar year. Stores results in self.rets (list) and
        self.ret (dictionary keyed by year).
        """
        # Must have stats.broker
        # Current year
        cur_year = -1
        # Start value
        value_start = 0.0
        # todo This value is not used, commented out
        # value_cur = 0.0   # Current value
        # End value
        value_end = 0.0
        # Save return data
        # todo Directly setting in PyCharm will warn about setting attribute values outside __init__, use hasattr and setattr to set specific attribute values
        # self.rets = list()  #
        # self.ret = OrderedDict()
        setattr(self, "rets", list())
        setattr(self, "ret", OrderedDict())

        # Calculate using cached data
        for i in range(len(self._dt_cache)):
            dt_val = self._dt_cache[i]
            value_cur = self._value_cache[i]

            # Convert date
            try:
                dt = num2date(dt_val)
            except Exception:
                continue

            # If the year at index i is greater than current year, if current year > 0, calculate return and save to self.ret, and start value equals end value
            # When years are not equal, it indicates current i is a new year
            if dt.year > cur_year:
                if cur_year >= 0:
                    if value_start != 0:
                        annual_ret = (value_end / value_start) - 1.0
                    else:
                        annual_ret = 0.0
                    self.rets.append(annual_ret)
                    self.ret[cur_year] = annual_ret

                    # changing between real years, use last value as new start
                    value_start = value_end
                else:
                    # No value set whatsoever, use the currently loaded value
                    value_start = value_cur

                cur_year = dt.year

            # No matter what, the last value is always the last loaded value
            value_end = value_cur
        # If current year hasn't ended and return hasn't been calculated, calculate at the end even if less than a full year
        if cur_year not in self.ret:
            # finish calculating pending data
            if value_start != 0:
                annual_ret = (value_end / value_start) - 1.0
            else:
                annual_ret = 0.0
            self.rets.append(annual_ret)
            self.ret[cur_year] = annual_ret

    def get_analysis(self):
        """Return the annual return analysis results.

        Returns:
            OrderedDict: Dictionary mapping years to their annual returns.
        """
        return self.ret


class MyAnnualReturn(Analyzer):
    """
    This analyzer calculates the AnnualReturns by looking at the beginning
    and end of the year

    Params:

      - (None)

    Member Attributes:

      - ``rets``: list of calculated annual returns

      - ``ret``: dictionary (key: year) of annual returns

    **get_analysis**:

      - Returns a dictionary of annual returns (key: year)
    """

    def stop(self):
        """Calculate annual returns using pandas.

        Uses pandas DataFrame operations to group data by year and
        calculate annual returns based on beginning and ending values
        for each year.

        Note:
            This method requires pandas to be installed.
        """
        # Container for saving data - dictionary
        if not hasattr(self, "ret"):
            setattr(self, "ret", OrderedDict())
        # Get data time and convert to date
        dt_list = self.data.datetime.get(0, size=len(self.data))
        dt_list = [num2date(i) for i in dt_list]
        # Get account assets
        value_list = self.strategy.stats.broker.value.get(0, size=len(self.data))
        # Convert to pandas format
        import pandas as pd

        df = pd.DataFrame([dt_list, value_list]).T
        df.columns = ["datetime", "value"]
        df["pre_value"] = df["value"].shift(1)
        # Calculate simple returns for each year
        df["year"] = [i.year for i in df["datetime"]]
        for year, data in df.groupby("year"):
            begin_value = list(data["pre_value"])[0]
            end_value = list(data["value"])[-1]
            annual_return = (end_value / begin_value) - 1
            self.ret[year] = annual_return

    def get_analysis(self):
        """Return the annual return analysis results.

        Returns:
            OrderedDict: Dictionary mapping years to their annual returns.
        """
        return self.ret
