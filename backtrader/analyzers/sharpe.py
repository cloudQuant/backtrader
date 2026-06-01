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
from ..mathsupport import average, is_finite_real, standarddev
from ..metabase import OwnerContext
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
        """Initialize the SharpeRatio analyzer.

        Sets up the return analyzer based on the legacyannual parameter.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments for analyzer parameters.
        """
        # CRITICAL FIX: Call super().__init__() first to initialize self.p
        super().__init__(*args, **kwargs)
        # If using years, get annualized return, otherwise get daily return
        # Use OwnerContext so child analyzers can find this as their parent
        if self.p.legacyannual:
            with OwnerContext.set_owner(self):
                self.anret = AnnualReturn()
        else:
            with OwnerContext.set_owner(self):
                self.timereturn = TimeReturn(
                    timeframe=self.p.timeframe, compression=self.p.compression, fund=self.p.fund
                )

    def stop(self):
        """Calculate and store the Sharpe ratio when analysis ends.

        Performs the following calculations:
        1. Retrieves returns from the sub-analyzer
        2. Converts risk-free rate if needed
        3. Calculates excess returns
        4. Computes the Sharpe ratio
        5. Optionally annualizes the result
        """
        super().stop()
        # Calculate returns and Sharpe ratio in annual units
        if self.p.legacyannual:
            ratio = self._legacy_annual_ratio()
        else:
            ratio = self._timeframe_ratio()
        # Save Sharpe ratio
        self.rets["sharperatio"] = ratio

    def _legacy_annual_ratio(self):
        """Sharpe ratio using the legacy AnnualReturn sub-analyzer path."""
        rate = self.p.riskfreerate
        try:
            retavg = average([r - rate for r in self.anret.rets])
            retdev = standarddev(self.anret.rets)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
        if not is_finite_real(retavg) or not is_finite_real(retdev):
            return None
        try:
            ratio = retavg / retdev
            return ratio if is_finite_real(ratio) else None
        except (ValueError, TypeError, ZeroDivisionError):
            return None

    def _resolve_factor(self):
        """Resolve the annualization factor for the configured timeframe/params."""
        if self.p.timeframe == TimeFrame.Days and self.p.daysfactor is not None:
            return self.p.daysfactor
        if self.p.factor is not None:
            return self.p.factor  # user specified factor
        if self.p.timeframe in self.RATEFACTORS:
            # Get the conversion factor from the default table
            return self.RATEFACTORS[self.p.timeframe]
        return None

    def _timeframe_ratio(self):
        """Sharpe ratio using the TimeReturn sub-analyzer with optional annualization."""
        # Get the returns from the subanalyzer (daily returns)
        returns = list(itervalues(self.timereturn.get_analysis()))
        # Risk-free rate
        rate = self.p.riskfreerate
        factor = self._resolve_factor()

        # Convert either the rate (down to the timeframe) or the returns (up to
        # yearly) depending on convertrate, when a factor is available.
        if factor is not None:
            converted = self._convert_rate_returns(rate, returns, factor)
            if converted is None:
                return None
            rate, returns = converted

        if not is_finite_real(rate) or any(not is_finite_real(ret) for ret in returns):
            return None

        # Number of trading days
        lrets = len(returns) - self.p.stddev_sample
        # Check if the ratio can be calculated
        if not lrets:
            # no returns or stddev_sample was active and 1 return
            return None

        # Get the excess returns - arithmetic mean - original sharpe
        ret_free = [r - rate for r in returns]
        ret_free_avg = average(ret_free)
        retdev = standarddev(ret_free, avgx=ret_free_avg, bessel=self.p.stddev_sample)

        if not is_finite_real(ret_free_avg) or not is_finite_real(retdev):
            return None
        try:
            # Calculate Sharpe ratio
            ratio = ret_free_avg / retdev
            # Annualize if requested (rate was converted down to the timeframe)
            if factor is not None and self.p.convertrate and self.p.annualize:
                ratio = math.sqrt(factor) * ratio
            return ratio if is_finite_real(ratio) else None
        except (ValueError, TypeError, ZeroDivisionError):
            return None

    def _convert_rate_returns(self, rate, returns, factor):
        """Apply the timeframe ``factor`` to either the risk-free rate or the
        returns series (per ``convertrate``).

        Returns the ``(rate, returns)`` pair on success, or ``None`` when the
        conversion is not representable (mirrors the original inline
        ValueError-guarded behavior). Extracted from ``_timeframe_ratio``;
        behavior unchanged.
        """
        try:
            if not is_finite_real(factor) or factor <= 0 or not is_finite_real(rate):
                raise ValueError()
            if self.p.convertrate:
                # Standard: downgrade annual returns to a timeframe factor
                if 1.0 + rate < 0:
                    raise ValueError()
                rate = pow(1.0 + rate, 1.0 / factor) - 1.0
                if isinstance(rate, complex) or not math.isfinite(rate):
                    raise ValueError()
            else:
                # Else upgrade returns to yearly returns
                returns = [pow(1.0 + x, factor) - 1.0 for x in returns]
                if any(isinstance(x, complex) or not math.isfinite(x) for x in returns):
                    raise ValueError()
        except (ValueError, TypeError, ZeroDivisionError, OverflowError):
            return None
        return rate, returns

        # Number of trading days
        lrets = len(returns) - self.p.stddev_sample
        # Check if the ratio can be calculated
        if not lrets:
            # no returns or stddev_sample was active and 1 return
            return None

        # Get the excess returns - arithmetic mean - original sharpe
        ret_free = [r - rate for r in returns]
        ret_free_avg = average(ret_free)
        retdev = standarddev(ret_free, avgx=ret_free_avg, bessel=self.p.stddev_sample)

        if not is_finite_real(ret_free_avg) or not is_finite_real(retdev):
            return None
        try:
            # Calculate Sharpe ratio
            ratio = ret_free_avg / retdev
            # Annualize if requested (rate was converted down to the timeframe)
            if factor is not None and self.p.convertrate and self.p.annualize:
                ratio = math.sqrt(factor) * ratio
            return ratio if is_finite_real(ratio) else None
        except (ValueError, TypeError, ZeroDivisionError):
            return None


class SharpeRatioA(SharpeRatio):
    """Extension of the SharpeRatio which returns the Sharpe Ratio directly in
    annualized form

    The following param has been changed from `SharpeRatio`

      - ``annualize`` (default: ``True``)

    """

    # Calculate annualized Sharpe ratio
    params = (("annualize", True),)
