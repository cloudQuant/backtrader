#!/usr/bin/env python
"""Sharpe Ratio Analyzer Module - Sharpe ratio calculation.

This module provides the SharpeRatio analyzer for calculating the Sharpe
ratio of a strategy using a risk-free asset.

Classes:
    SharpeRatio: Analyzer that calculates Sharpe ratio.
    SharpeRatio_Annual: Annualized Sharpe ratio analyzer.

Example:
    >>> cerebro = bt.Cerebro()
    >>> cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    >>> results = cerebro.run()
    >>> print(results[0].analyzers.sharpe.get_analysis())
"""
import math

from ..analyzer import Analyzer
from ..dataseries import TimeFrame
from ..mathsupport import average, standarddev
from ..utils.py3 import itervalues
from .annualreturn import AnnualReturn
from .timereturn import TimeReturn


class SharpeRatio(Analyzer):
    # Relatively speaking, backtrader's Sharpe ratio calculation method is quite complex, considering many parameters
    """This analyzer calculates the SharpeRatio of a strategy using a risk-free
    asset, which is simply an interest rate

    See also:

      - https://en.wikipedia.org/wiki/Sharpe_ratio

    Params:

      - ``timeframe``: (default: ``TimeFrame.Years``) # Trading period

      - ``compression`` (default: ``1``) # Specific trading period

        Only used for sub-day timeframes to, for example, work on an hourly
        timeframe by specifying "TimeFrame.Minutes" and 60 as compression

      - ``riskfreerate`` (default: 0.01 -> 1%) # Risk-free rate used for Sharpe ratio calculation

        Expressed in annual terms (see ``convertrate`` below)

      - ``convertrate`` (default: ``True``) # Whether to convert risk-free rate from annual to monthly, weekly, daily, no intraday support

        Convert the ``riskfreerate`` from annual to monthly, weekly or daily
        rate. Sub-day conversions are not supported

      - ``factor`` (default: ``None``) # If not specified, will convert according to specified date, 1 year = 12 months = 52 weeks = 252 trading days

        If ``None``, the conversion factor for the risk-free rate from *annual*
        to the chosen timeframe will be chosen from a predefined table

          Days: 252, Weeks: 52, Months: 12, Years: 1

        Else the specified value will be used

      - ``annualize`` (default: ``False``) # If set to True, will convert to annualized return

        If ``convertrate`` is `True`, the *SharpeRatio* will be delivered in
        the ``timeframe`` of choice.

        On most occasions, the SharpeRatio is delivered in annualized form.
        Convert the ``riskfreerate`` from annual to monthly, weekly or daily
        rate. Sub-day conversions are not supported

      - ``stddev_sample`` (default: ``False``) # Whether to subtract 1 when calculating standard deviation

        If this is set to ``True`` the *standard deviation* will be calculated
        decreasing the denominator in the mean by ``1``. This is used when
        calculating the *standard deviation* if it's considered that not all
        samples are used for the calculation. This is known as the *Bessels'
        correction*

      - ``daysfactor`` (default: ``None``) # Legacy code

        Old naming for ``factor``. If set to anything else than ``None`` and
        the ``timeframe`` is ``TimeFrame.Days`` it will be assumed this is old
        code and the value will be used

      - ``legacyannual`` (default: ``False``) # Only applies to years, use annualized return analyzer

        Use the ``AnnualReturn`` return analyzer, which as the name implies
        only works for years

      - ``fund`` (default: ``None``) # Net asset mode or fund mode, by default will auto-detect

        If `None`, the actual mode of the broker (fundmode - True/False) will
        be autodetected to decide if the returns are based on the total net
        asset value or on the fund value. See ``set_fundmode`` in the broker
        documentation

        Set it to ``True`` or ``False`` for a specific behavior

    Methods:

      - Get_analysis

        Returns a dictionary with key "sharperatio" holding the ratio

    """

    # Default parameters
    params = (
        ("timeframe", TimeFrame.Years),
        ("compression", 1),
        ("riskfreerate", 0.01),
        ("factor", None),
        ("convertrate", True),
        ("annualize", False),
        ("stddev_sample", False),
        # old behavior
        ("daysfactor", None),
        ("legacyannual", False),
        ("fund", None),
    )
    # Default date conversion
    RATEFACTORS = {
        TimeFrame.Days: 252,
        TimeFrame.Weeks: 52,
        TimeFrame.Months: 12,
        TimeFrame.Years: 1,
    }

    def __init__(self, *args, **kwargs):
        # CRITICAL FIX: Call super().__init__() first to initialize self.p
        super().__init__(*args, **kwargs)
        # If using years, get annualized return, otherwise get daily return
        if self.p.legacyannual:
            self.anret = AnnualReturn()
        else:
            self.timereturn = TimeReturn(
                timeframe=self.p.timeframe, compression=self.p.compression, fund=self.p.fund
            )

    def stop(self):
        super().stop()
        # Calculate returns and Sharpe ratio in annual units
        if self.p.legacyannual:
            rate = self.p.riskfreerate
            retavg = average([r - rate for r in self.anret.rets])
            retdev = standarddev(self.anret.rets)
            # TODO: change self.ratio to ratio
            # self.ratio = retavg / retdev
            ratio = retavg / retdev
        # If not calculating returns and Sharpe ratio in annual units
        else:
            # Get the returns from the subanalyzer
            # Get daily returns
            returns = list(itervalues(self.timereturn.get_analysis()))
            # Risk-free rate
            rate = self.p.riskfreerate  #
            # Date defaults to None
            factor = None

            # Hack to identify old code
            # Get specific factor date, if daily period and daysfactor is not None, set factor = daysfactor
            if self.p.timeframe == TimeFrame.Days and self.p.daysfactor is not None:
                factor = self.p.daysfactor
            # Otherwise, if factor parameter is not None, equal to factor parameter value, otherwise find from defined factors based on trading period
            # By default, factor should be 252
            else:
                if self.p.factor is not None:
                    factor = self.p.factor  # user specified factor
                elif self.p.timeframe in self.RATEFACTORS:
                    # Get the conversion factor from the default table
                    factor = self.RATEFACTORS[self.p.timeframe]
            # If factor is not None, need to convert annual risk-free rate to daily risk-free rate by default, if using daily period
            if factor is not None:
                # A factor was found

                if self.p.convertrate:
                    # Standard: downgrade annual returns to a timeframe factor
                    rate = pow(1.0 + rate, 1.0 / factor) - 1.0
                else:
                    # Else upgrade returns to yearly returns
                    returns = [pow(1.0 + x, factor) - 1.0 for x in returns]
            # Number of trading days
            lrets = len(returns) - self.p.stddev_sample
            # Check if the ratio can be calculated
            if lrets:
                # Get the excess returns - arithmetic mean - original sharpe
                # Calculate daily excess returns
                ret_free = [r - rate for r in returns]
                # Calculate average of daily excess returns
                ret_free_avg = average(ret_free)
                # Calculate standard deviation of daily excess returns
                retdev = standarddev(ret_free, avgx=ret_free_avg, bessel=self.p.stddev_sample)
                # ret_avg = average(returns)
                # retdev = standarddev(returns, avgx=ret_avg,bessel=self.p.stddev_sample)

                try:
                    # Calculate Sharpe ratio
                    ratio = ret_free_avg / retdev
                    # If factor is not None, annual risk-free rate was converted to daily, and need to calculate annualized Sharpe ratio
                    if factor is not None and self.p.convertrate and self.p.annualize:
                        # Convert Sharpe ratio from daily to annual
                        ratio = math.sqrt(factor) * ratio
                except (ValueError, TypeError, ZeroDivisionError):
                    ratio = None
            else:
                # no returns or stddev_sample was active and 1 return
                ratio = None
            # TODO: self.ratio is not used here, just use ratio for assignment, can also improve speed
            # self.ratio = ratio
        # Save Sharpe ratio
        self.rets["sharperatio"] = ratio


class SharpeRatioA(SharpeRatio):
    """Extension of the SharpeRatio which returns the Sharpe Ratio directly in
    annualized form

    The following param has been changed from `SharpeRatio`

      - ``annualize`` (default: ``True``)

    """

    # Calculate annualized Sharpe ratio
    params = (("annualize", True),)
