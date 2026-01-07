#!/usr/bin/env python
"""OLS Indicator Module - Ordinary least squares regression.

This module provides indicators using OLS (Ordinary Least Squares)
regression for statistical analysis.

Classes:
    OLS_Slope_InterceptN: Calculates slope and intercept via OLS.
    OLS_TransformationN: Calculates OLS transformed values.
    OLS_BetaN: Calculates beta via OLS.
    CointN: Tests for cointegration between series.

Example:
    >>> data1 = bt.feeds.GenericCSVData(dataname='data1.csv')
    >>> data2 = bt.feeds.GenericCSVData(dataname='data2.csv')
    >>> cerebro.adddata(data1)
    >>> cerebro.adddata(data2)
    >>> ols = bt.indicators.OLS_Slope_InterceptN(data1, data2, period=30)
"""
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint

from . import SMA, PeriodN, StdDev

__all__ = ["OLS_Slope_InterceptN", "OLS_TransformationN", "OLS_BetaN", "CointN"]
class OLS_Slope_InterceptN(PeriodN):
    """
    Calculates a linear regression using ``statsmodel.OLS`` (Ordinary least
    squares) of data1 on data0

    Uses ``pandas`` and ``statsmodels``
    """

    _mindatas = 2  # ensure at least 2 data feeds are passed

    packages = (
        ("pandas", "pd"),
        ("statsmodels.api", "sm"),
    )
    lines = (
        "slope",
        "intercept",
    )
    params = (("period", 10),)

    def next(self):
        """Calculate OLS slope and intercept for the current bar.

        Uses statsmodels OLS to perform linear regression.
        """
        p0 = pd.Series(self.data0.get(size=self.p.period))
        p1 = pd.Series(self.data1.get(size=self.p.period))
        p1 = sm.add_constant(p1)
        intercept, slope = sm.OLS(p0, p1).fit().params

        self.lines.slope[0] = slope
        self.lines.intercept[0] = intercept


class OLS_TransformationN(PeriodN):
    """
    Calculates the ``zscore`` for data0 and data1. Although it doesn't directly
    use any external package, it relies on ``OLS_SlopeInterceptN`` which uses
    ``pandas`` and ``statsmodels``
    """

    _mindatas = 2  # ensure at least 2 data feeds are passed
    lines = (
        "spread",
        "spread_mean",
        "spread_std",
        "zscore",
    )
    params = (("period", 10),)

    def __init__(self):
        """Initialize the OLS Transformation indicator.

        Creates OLS slope-intercept indicator for transformation calculations.
        """
        super().__init__()
        self.slint = OLS_Slope_InterceptN(*self.datas)

    def next(self):
        """Calculate OLS transformation values for the current bar.

        Computes spread, mean, std, and zscore based on OLS regression.
        """
        slope = self.slint.slope[0]
        intercept = self.slint.intercept[0]
        spread = self.data0[0] - (slope * self.data1[0] + intercept)
        self.lines.spread[0] = spread
        
        # Calculate spread_mean (SMA of spread)
        period = self.p.period
        spread_sum = spread
        for i in range(1, period):
            spread_sum += self.lines.spread[-i]
        spread_mean = spread_sum / period
        self.lines.spread_mean[0] = spread_mean
        
        # Calculate spread_std (StdDev of spread)
        var_sum = (spread - spread_mean) ** 2
        for i in range(1, period):
            var_sum += (self.lines.spread[-i] - spread_mean) ** 2
        spread_std = (var_sum / period) ** 0.5
        self.lines.spread_std[0] = spread_std
        
        # Calculate zscore
        if spread_std != 0:
            self.lines.zscore[0] = (spread - spread_mean) / spread_std
        else:
            self.lines.zscore[0] = 0.0

    def once(self, start, end):
        """Calculate OLS transformation in runonce mode.

        Computes spread, mean, std, and zscore values across all bars.
        """
        import math
        slope_array = self.slint.lines.slope.array
        intercept_array = self.slint.lines.intercept.array
        d0_array = self.data0.array
        d1_array = self.data1.array
        spread_array = self.lines.spread.array
        mean_array = self.lines.spread_mean.array
        std_array = self.lines.spread_std.array
        zscore_array = self.lines.zscore.array
        period = self.p.period
        
        for arr in [spread_array, mean_array, std_array, zscore_array]:
            while len(arr) < end:
                arr.append(0.0)
        
        # Calculate spread
        for i in range(start, min(end, len(slope_array), len(intercept_array), len(d0_array), len(d1_array))):
            slope = slope_array[i] if i < len(slope_array) else 0.0
            intercept = intercept_array[i] if i < len(intercept_array) else 0.0
            d0 = d0_array[i] if i < len(d0_array) else 0.0
            d1 = d1_array[i] if i < len(d1_array) else 0.0
            spread_array[i] = d0 - (slope * d1 + intercept)
        
        # Calculate spread_mean, spread_std, zscore
        for i in range(start, min(end, len(spread_array))):
            if i < period - 1:
                mean_array[i] = float("nan")
                std_array[i] = float("nan")
                zscore_array[i] = float("nan")
            else:
                spread_sum = 0.0
                for j in range(period):
                    idx = i - j
                    if idx >= 0 and idx < len(spread_array):
                        spread_sum += spread_array[idx]
                spread_mean = spread_sum / period
                mean_array[i] = spread_mean
                
                var_sum = 0.0
                for j in range(period):
                    idx = i - j
                    if idx >= 0 and idx < len(spread_array):
                        var_sum += (spread_array[idx] - spread_mean) ** 2
                spread_std = (var_sum / period) ** 0.5
                std_array[i] = spread_std
                
                spread = spread_array[i]
                if spread_std != 0:
                    zscore_array[i] = (spread - spread_mean) / spread_std
                else:
                    zscore_array[i] = 0.0


class OLS_BetaN(PeriodN):
    """
    Calculates a regression of data1 on data0 using ``pandas.ols``

    Uses ``pandas``
    """

    _mindatas = 2  # ensure at least 2 data feeds are passed

    packages = (("pandas", "pd"),)

    lines = ("beta",)
    params = (("period", 10),)

    def next(self):
        """Calculate beta via OLS regression for the current bar.

        Uses pandas OLS to calculate regression beta.
        """
        y, x = (pd.Series(d.get(size=self.p.period)) for d in self.datas)
        r_beta = pd.ols(y=y, x=x, window_type="full_sample")
        self.lines.beta[0] = r_beta.beta["x"]


class CointN(PeriodN):
    """
    Calculates the score (coint_t) and pvalue for a given ``period`` for the
    data feeds

    Uses ``pandas`` and ``statsmodels`` (for ``coint``)
    """

    _mindatas = 2  # ensure at least 2 data feeds are passed

    packages = (("pandas", "pd"),)  # import pandas as pd
    frompackages = (("statsmodels.tsa.stattools", "coint"),)  # from st... import coint

    lines = (
        "score",
        "pvalue",
    )
    params = (
        ("period", 10),
        ("trend", "c"),  # see statsmodel.tsa.statttools
    )

    def next(self):
        """Calculate cointegration test for the current period.

        Uses statsmodels coint function to test for cointegration.
        """
        x, y = (pd.Series(d.get(size=self.p.period)) for d in self.datas)
        score, pvalue, _ = coint(x, y, trend=self.p.trend)
        self.lines.score[0] = score
        self.lines.pvalue[0] = pvalue
