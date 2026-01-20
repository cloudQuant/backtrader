#!/usr/bin/env python
"""Pivot Point Indicator Module - Support and resistance levels.

This module provides Pivot Point indicators for calculating support
and resistance levels from previous period price data.

Classes:
    PivotPoint: Standard pivot points with 2 support/resistance levels.
    FibonacciPivotPoint: Pivot points with Fibonacci-based levels.
    DemarkPivotPoint: Demark pivot point calculation.

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            # Calculate pivot points from resampled data (data1)
            self.pivot = bt.indicators.PivotPoint(self.data1)

        def next(self):
            # Buy when price breaks above resistance level 1
            if self.data.close[0] > self.pivot.r1[0]:
                self.buy()
            # Sell when price breaks below support level 1
            elif self.data.close[0] < self.pivot.s1[0]:
                self.sell()
"""

from . import Indicator


class PivotPoint(Indicator):
    """
    Defines a level of significance by taking into account the average of price
    bar components of the past period of a larger timeframe.
    For example, when
    operating with days, the values are taking from the already "past" month
    fixed prices.

    Example of using this indicator:

      data = btfeeds.ADataFeed(dataname=x, timeframe=bt.TimeFrame.Days)
      cerebro.adddata(data)
      cerebro.resampledata(data, timeframe=bt.TimeFrame.Months)

    In the ``__init__`` method of the strategy:

      pivotindicator = btind.PivotPoiont(self.data1) # the resampled data

    The indicator will try to automatically plo to the non-resampled data.
    To
    disable this behavior, use the following during construction:

      - _autoplot=False

    Note:

      The example shows *days* and *months*, but any combination of timeframes
      can be used.
      See the literature for recommended combinations

    Formula:
      - pivot = (h + l + c) / 3 # variants duplicate close or add open
      - support1 = 2.0 * pivot - high
      - support2 = pivot - (high - low)
      - resistance1 = 2.0 * pivot - low
      - resistance2 = pivot + (high - low)

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:pivot_points
      - https://en.wikipedia.org/wiki/Pivot_point_(technical_analysis)
    """

    lines = (
        "p",
        "s1",
        "s2",
        "r1",
        "r2",
    )
    plotinfo = dict(subplot=False)

    params = (
        ("open", False),  # add opening price to the pivot point
        ("close", False),  # use close twice in the calcs
        ("_autoplot", True),  # attempt to plot on real target data
    )

    def _plotinit(self):
        """Initialize plot settings for Pivot Point.

        Attempts to plot on the actual timeframe master data
        rather than the resampled data.
        """
        # Try to plot to the actual timeframe master
        if self.p._autoplot:
            if hasattr(self.data, "data"):
                self.plotinfo.plotmaster = self.data.data

    def __init__(self):
        """Initialize the Pivot Point indicator.

        Sets up coupler to follow real object if autoplot is enabled.
        """
        super().__init__()  # enable coopertive inheritance

        if self.p._autoplot:
            self.plotinfo.plot = False  # disable own plotting
            self()  # Coupler to follow a real object

    def next(self):
        """Calculate pivot point and support/resistance levels.

        Standard formula: p = (h + l + c) / 3
        Support/Resistance levels derived from pivot and high-low range.
        """
        o = self.data.open[0]
        h = self.data.high[0]
        low = self.data.low[0]
        c = self.data.close[0]

        if self.p.close:
            p = (h + low + 2.0 * c) / 4.0
        elif self.p.open:
            p = (h + low + c + o) / 4.0
        else:
            p = (h + low + c) / 3.0

        self.lines.p[0] = p
        self.lines.s1[0] = 2.0 * p - h
        self.lines.r1[0] = 2.0 * p - low
        self.lines.s2[0] = p - (h - low)
        self.lines.r2[0] = p + (h - low)

    def once(self, start, end):
        """Calculate pivot point levels in runonce mode.

        Computes pivot, support, and resistance levels across all bars.
        """
        o_array = self.data.open.array
        h_array = self.data.high.array
        l_array = self.data.low.array
        c_array = self.data.close.array
        p_array = self.lines.p.array
        s1_array = self.lines.s1.array
        s2_array = self.lines.s2.array
        r1_array = self.lines.r1.array
        r2_array = self.lines.r2.array

        for arr in [p_array, s1_array, s2_array, r1_array, r2_array]:
            while len(arr) < end:
                arr.append(0.0)

        use_close = self.p.close
        use_open = self.p.open

        for i in range(start, min(end, len(h_array), len(l_array), len(c_array))):
            o = o_array[i] if i < len(o_array) else 0.0
            h = h_array[i] if i < len(h_array) else 0.0
            low = l_array[i] if i < len(l_array) else 0.0
            c = c_array[i] if i < len(c_array) else 0.0

            if use_close:
                p = (h + low + 2.0 * c) / 4.0
            elif use_open:
                p = (h + low + c + o) / 4.0
            else:
                p = (h + low + c) / 3.0

            p_array[i] = p
            s1_array[i] = 2.0 * p - h
            r1_array[i] = 2.0 * p - low
            s2_array[i] = p - (h - low)
            r2_array[i] = p + (h - low)


class FibonacciPivotPoint(Indicator):
    """
    Defines a level of significance by taking into account the average of price
    bar components of the past period of a larger timeframe.
    For example, when
    operating with days, the values are taking from the already "past" month
    fixed prices.

    Fibonacci levels (configurable) are used to define the support/resistance levels

    Example of using this indicator:

      data = btfeeds.ADataFeed(dataname=x, timeframe=bt.TimeFrame.Days)
      cerebro.adddata(data)
      cerebro.resampledata(data, timeframe=bt.TimeFrame.Months)

    In the ``__init__`` method of the strategy:

      pivotindicator = btind.FibonacciPivotPoiont(self.data1) # the resampled data

    The indicator will try to automatically plo to the non-resampled data.
    To
    disable this behavior, use the following during construction:

      - _autoplot=False

    Note:

      The example shows *days* and *months*, but any combination of timeframes
      can be used.
      See the literature for recommended combinations

    Formula:
      - pivot = (h + l + c) / 3  # variants duplicate close or add open
      - support1 = p - level1 * (high - low)  # level1 0.382
      - support2 = p - level2 * (high - low)  # level2 0.618
      - support3 = p - level3 * (high - low)  # level3 1.000
      - resistance1 = p + level1 * (high - low)  # level1 0.382
      - resistance2 = p + level2 * (high - low)  # level2 0.618
      - resistance3 = p + level3 * (high - low)  # level3 1.000

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:pivot_points
    """

    lines = ("p", "s1", "s2", "s3", "r1", "r2", "r3")
    plotinfo = dict(subplot=False)
    params = (
        ("open", False),  # add opening price to the pivot point
        ("close", False),  # use close twice in the calcs
        ("_autoplot", True),  # attempt to plot on real target data
        ("level1", 0.382),
        ("level2", 0.618),
        ("level3", 1.0),
    )

    def _plotinit(self):
        """Initialize plot settings for Fibonacci Pivot Point.

        Attempts to plot on the actual timeframe master data
        rather than the resampled data.
        """
        # Try to plot to the actual timeframe master
        if self.p._autoplot:
            if hasattr(self.data, "data"):
                self.plotinfo.plotmaster = self.data.data

    def __init__(self):
        """Initialize the Fibonacci Pivot Point indicator.

        Sets up coupler to follow real object if autoplot is enabled.
        """
        super().__init__()

        if self.p._autoplot:
            self.plotinfo.plot = False  # disable own plotting
            self()  # Coupler to follow a real object

    def next(self):
        """Calculate Fibonacci pivot point and support/resistance levels.

        Uses Fibonacci ratios (0.382, 0.618, 1.0) to calculate
        support/resistance levels from pivot point.
        """
        o = self.data.open[0]
        h = self.data.high[0]
        low = self.data.low[0]
        c = self.data.close[0]

        if self.p.close:
            p = (h + low + 2.0 * c) / 4.0
        elif self.p.open:
            p = (h + low + c + o) / 4.0
        else:
            p = (h + low + c) / 3.0

        hl_range = h - low
        self.lines.p[0] = p
        self.lines.s1[0] = p - self.p.level1 * hl_range
        self.lines.s2[0] = p - self.p.level2 * hl_range
        self.lines.s3[0] = p - self.p.level3 * hl_range
        self.lines.r1[0] = p + self.p.level1 * hl_range
        self.lines.r2[0] = p + self.p.level2 * hl_range
        self.lines.r3[0] = p + self.p.level3 * hl_range

    def once(self, start, end):
        """Calculate Fibonacci pivot point levels in runonce mode.

        Computes pivot and Fibonacci-based support/resistance levels
        across all bars.
        """
        o_array = self.data.open.array
        h_array = self.data.high.array
        l_array = self.data.low.array
        c_array = self.data.close.array
        p_array = self.lines.p.array
        s1_array = self.lines.s1.array
        s2_array = self.lines.s2.array
        s3_array = self.lines.s3.array
        r1_array = self.lines.r1.array
        r2_array = self.lines.r2.array
        r3_array = self.lines.r3.array

        for arr in [p_array, s1_array, s2_array, s3_array, r1_array, r2_array, r3_array]:
            while len(arr) < end:
                arr.append(0.0)

        use_close = self.p.close
        use_open = self.p.open
        level1 = self.p.level1
        level2 = self.p.level2
        level3 = self.p.level3

        for i in range(start, min(end, len(h_array), len(l_array), len(c_array))):
            o = o_array[i] if i < len(o_array) else 0.0
            h = h_array[i] if i < len(h_array) else 0.0
            low = l_array[i] if i < len(l_array) else 0.0
            c = c_array[i] if i < len(c_array) else 0.0

            if use_close:
                p = (h + low + 2.0 * c) / 4.0
            elif use_open:
                p = (h + low + c + o) / 4.0
            else:
                p = (h + low + c) / 3.0

            hl_range = h - low
            p_array[i] = p
            s1_array[i] = p - level1 * hl_range
            s2_array[i] = p - level2 * hl_range
            s3_array[i] = p - level3 * hl_range
            r1_array[i] = p + level1 * hl_range
            r2_array[i] = p + level2 * hl_range
            r3_array[i] = p + level3 * hl_range


class DemarkPivotPoint(Indicator):
    """
    Defines a level of significance by taking into account the average of price
    bar components of the past period of a larger timeframe.
    For example, when
    operating with days, the values are taking from the already "past" month
    fixed prices.

    Example of using this indicator:

      data = btfeeds.ADataFeed(dataname=x, timeframe=bt.TimeFrame.Days)
      cerebro.adddata(data)
      cerebro.resampledata(data, timeframe=bt.TimeFrame.Months)

    In the ``__init__`` method of the strategy:

      pivotindicator = btind.DemarkPivotPoiont(self.data1) # the resampled data

    The indicator will try to automatically plo to the non-resampled data.
    To
    disable this behavior, use the following during construction:

      - _autoplot=False

    Note:

      The example shows *days* and *months*, but any combination of timeframes
      can be used.
      See the literature for recommended combinations

    Formula:
      - if close < open x = high + (2 x low) + close

      - If close > open x = (2 x high) + low + close

      - If Close == open x = high + low + (2 x close)

      - P = x / 4

      - Support1 = x / 2 - high
      - resistance1 = x / 2 - low

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:pivot_points
    """

    lines = (
        "p",
        "s1",
        "r1",
    )
    plotinfo = dict(subplot=False)
    params = (
        ("open", False),  # add opening price to the pivot point
        ("close", False),  # use close twice in the calcs
        ("_autoplot", True),  # attempt to plot on real target data
        ("level1", 0.382),
        ("level2", 0.618),
        ("level3", 1.0),
    )

    def _plotinit(self):
        """Initialize plot settings for Demark Pivot Point.

        Attempts to plot on the actual timeframe master data
        rather than the resampled data.
        """
        # Try to plot to the actual timeframe master
        if self.p._autoplot:
            if hasattr(self.data, "data"):
                self.plotinfo.plotmaster = self.data.data

    def __init__(self):
        """Initialize the Demark Pivot Point indicator.

        Sets up coupler to follow real object if autoplot is enabled.
        """
        super().__init__()

        if self.p._autoplot:
            self.plotinfo.plot = False  # disable own plotting
            self()  # Coupler to follow a real object

    def next(self):
        """Calculate Demark pivot point and support/resistance levels.

        Demark formula uses relationship between open and close
        to determine the calculation method.
        """
        h = self.data.high[0]
        low = self.data.low[0]
        o = self.data.open[0]
        c = self.data.close[0]

        if c < o:
            x = h + 2.0 * low + c
        elif c > o:
            x = 2.0 * h + low + c
        else:
            x = h + low + 2.0 * c

        self.lines.p[0] = x / 4.0
        self.lines.s1[0] = x / 2.0 - h
        self.lines.r1[0] = x / 2.0 - low

    def once(self, start, end):
        """Calculate Demark pivot point levels in runonce mode.

        Computes Demark-style pivot, support, and resistance levels
        across all bars.
        """
        o_array = self.data.open.array
        h_array = self.data.high.array
        l_array = self.data.low.array
        c_array = self.data.close.array
        p_array = self.lines.p.array
        s1_array = self.lines.s1.array
        r1_array = self.lines.r1.array

        for arr in [p_array, s1_array, r1_array]:
            while len(arr) < end:
                arr.append(0.0)

        for i in range(start, min(end, len(h_array), len(l_array), len(c_array), len(o_array))):
            o = o_array[i] if i < len(o_array) else 0.0
            h = h_array[i] if i < len(h_array) else 0.0
            low = l_array[i] if i < len(l_array) else 0.0
            c = c_array[i] if i < len(c_array) else 0.0

            if c < o:
                x = h + 2.0 * low + c
            elif c > o:
                x = 2.0 * h + low + c
            else:
                x = h + low + 2.0 * c

            p_array[i] = x / 4.0
            s1_array[i] = x / 2.0 - h
            r1_array[i] = x / 2.0 - low
