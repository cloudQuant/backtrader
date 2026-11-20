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
    class MyStrategy(bt.Strategy):
        def __init__(self):
            # Calculate OLS regression slope and intercept between two data feeds
            self.ols = bt.indicators.OLS_Slope_InterceptN(self.data0, self.data1, period=30)

            # Calculate OLS transformation (spread, zscore)
            self.ols_trans = bt.indicators.OLS_TransformationN(self.data0, self.data1, period=30)

        def next(self):
            # Trade based on zscore of the spread
            if self.ols_trans.zscore[0] > 2:
                # Spread is too high - short data0, long data1
                self.sell(data=self.data0)
                self.buy(data=self.data1)
            elif self.ols_trans.zscore[0] < -2:
                # Spread is too low - long data0, short data1
                self.buy(data=self.data0)
                self.sell(data=self.data1)
"""

import math

from . import PeriodN

# Lazy import statsmodels to avoid slow import at module load time
# statsmodels is a heavy library that adds 20+ seconds to import time
# It will be imported when the indicators are actually used


def _get_statsmodels():
    """Lazy import statsmodels.api."""
    import statsmodels.api as sm

    return sm


def _get_coint():
    """Lazy import statsmodels coint function."""
    from statsmodels.tsa.stattools import coint

    return coint


def _get_numpy():
    """Lazy import NumPy with an indicator-specific dependency error."""
    try:
        import numpy as np
    except ImportError as exc:
        raise ImportError("OLS_BetaN requires NumPy for least-squares regression") from exc

    return np


def _fit_ols_beta(np, y, x, period):
    """Fit ``y`` on ``x`` with an intercept, failing closed on bad windows."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)

    if y.size != period or x.size != period or not np.isfinite(y).all() or not np.isfinite(x).all():
        return float("nan")

    design = np.column_stack((x, np.ones_like(x)))
    try:
        coefficients, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    except np.linalg.LinAlgError:
        return float("nan")

    beta = coefficients[0]
    return beta if rank == 2 and np.isfinite(beta) else float("nan")


def _source_line_and_datetime(source, label):
    """Return an input's value line and a provable source datetime line."""
    try:
        source_line = source.lines[0]
    except (AttributeError, IndexError, TypeError) as exc:
        raise ValueError("OLS_BetaN requires line inputs with datetime clocks") from exc

    try:
        datetime_line = source.lines.datetime
    except (AttributeError, IndexError, TypeError):
        datetime_line = None

    if datetime_line is None:
        clock = getattr(source, "_clock", None)
        if clock is None or clock.__class__.__name__ == "MinimalClock":
            # LineActions and line-series wrappers may expose their source clock
            # through Backtrader's clock resolver after scheduling is set up.
            try:
                from ..lineiterator import _line_like_source_clock

                clock = _line_like_source_clock(source)
            except (ImportError, AttributeError, TypeError):
                clock = None

        try:
            datetime_line = clock.lines.datetime
        except (AttributeError, IndexError, TypeError):
            datetime_line = None

    if datetime_line is None or not all(hasattr(datetime_line, attr) for attr in ("array", "get")):
        raise ValueError("OLS_BetaN cannot prove a datetime clock for {} input".format(label))

    return source_line, datetime_line


def _finite_datetime(value, label):
    """Normalize Backtrader's numeric datetime and reject invalid clock rows."""
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("OLS_BetaN requires finite {} datetimes".format(label)) from exc

    if not math.isfinite(value):
        raise ValueError("OLS_BetaN requires finite {} datetimes".format(label))

    return value


def _validate_ordered_datetimes(values, label):
    """Validate a complete batch clock before using any value windows."""
    normalized = [_finite_datetime(value, label) for value in values]
    if any(current <= previous for previous, current in zip(normalized, normalized[1:])):
        raise ValueError("OLS_BetaN requires strictly increasing input datetimes")
    return normalized


def _validate_matching_window(y_dates, x_dates, period):
    """Fail unless a y/x window has a one-to-one datetime pairing."""
    if len(y_dates) != period or len(x_dates) != period:
        raise ValueError("OLS_BetaN cannot prove matching input datetime windows")

    y_dates = [_finite_datetime(value, "data0") for value in y_dates]
    x_dates = [_finite_datetime(value, "data1") for value in x_dates]
    if y_dates != x_dates:
        raise ValueError("OLS_BetaN requires matching input datetimes")

    if any(current <= previous for previous, current in zip(y_dates, y_dates[1:])):
        raise ValueError("OLS_BetaN requires strictly increasing input datetimes")


def _validate_streaming_clock_progress(indicator, datetime_line, slot, label):
    """Validate only newly observed clock rows, once each, during ``next``."""
    states = indicator._ols_beta_clock_state
    state = states[slot]
    if state["line"] is not None and state["line"] is not datetime_line:
        raise ValueError("OLS_BetaN source clock changed; create a new indicator")
    state["line"] = datetime_line

    count = len(datetime_line)
    previous_count = state["count"]
    if count < previous_count:
        raise ValueError("OLS_BetaN source clock reset; create a new indicator")

    new_count = count - previous_count
    if new_count:
        try:
            new_values = datetime_line.get(size=new_count)
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError("OLS_BetaN cannot prove complete datetime history") from exc
        if len(new_values) != new_count:
            raise ValueError("OLS_BetaN cannot prove complete datetime history")

        previous_datetime = state["last_datetime"]
        for value in new_values:
            current_datetime = _finite_datetime(value, label)
            if previous_datetime is not None and current_datetime <= previous_datetime:
                raise ValueError(
                    "OLS_BetaN requires strictly increasing {} datetimes".format(label)
                )
            previous_datetime = current_datetime

        state["count"] = count
        state["last_datetime"] = previous_datetime
    elif count:
        current_datetime = _finite_datetime(datetime_line[0], label)
        if current_datetime != state["last_datetime"]:
            raise ValueError("OLS_BetaN cannot prove a stable current datetime")


__all__ = ["OLS_Slope_InterceptN", "OLS_TransformationN", "OLS_BetaN", "CointN"]


class OLS_Slope_InterceptN(PeriodN):
    """
    Calculates a linear regression using ``statsmodel.OLS`` (Ordinary least
    squares) of data1 on data0

    Uses ``pandas`` and ``statsmodels``
    """

    _mindatas = 2  # ensure at least 2 data feeds are passed

    lines = (
        "slope",
        "intercept",
    )
    params = (("period", 10),)

    def next(self):
        """Calculate OLS slope and intercept for the current bar.

        Uses statsmodels OLS to perform linear regression.
        """
        import pandas as pd

        sm = _get_statsmodels()
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
                arr.append(float("nan"))

        # Calculate spread
        for i in range(
            start, min(end, len(slope_array), len(intercept_array), len(d0_array), len(d1_array))
        ):
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
    Calculates the regression slope of data0 on data1 using least squares.

    The regression includes an intercept, matching the former ``pandas.ols``
    default. It intentionally fails closed: any non-finite input or a
    rank-deficient window produces a NaN beta instead of dropping rows or
    accepting a pseudo-inverse coefficient. Exactly two inputs are required,
    and their clocks must be provably strictly increasing with matching
    datetimes in each rolling window; an unresolvable or mismatched clock
    raises ``ValueError``.
    """

    _mindatas = 2  # exact input count is checked below

    lines = ("beta",)
    params = (("period", 10),)

    def __init__(self):
        """Require exactly two inputs to avoid silently ignoring extra feeds."""
        if len(self.datas) != 2:
            raise ValueError("OLS_BetaN requires exactly two data inputs")
        super().__init__()
        self._reset_clock_state()

    def _reset_clock_state(self):
        """Forget incremental clock-validation state for a new line run."""
        self._ols_beta_clock_state = [
            {"line": None, "count": 0, "last_datetime": None},
            {"line": None, "count": 0, "last_datetime": None},
        ]

    def reset(self):
        """Reset output lines while retaining validated source clock cursors.

        Cerebro does not rerun an already completed vectorized ``once`` pass;
        resetting during that run clears its precomputed output without
        scheduling a replacement calculation. If a source clock also resets
        or changes, bounded buffers may have discarded needed history, so this
        indicator fails closed; create a new indicator for the new clock run.
        """
        super().reset()

    def next(self):
        """Calculate beta via OLS regression for the current bar.

        Fits data0 as the response and data1 as the predictor, including a
        constant column for the intercept.
        """
        period = self.p.period
        y_line, y_datetime = _source_line_and_datetime(self.data0, "data0")
        x_line, x_datetime = _source_line_and_datetime(self.data1, "data1")
        _validate_streaming_clock_progress(self, y_datetime, 0, "data0")
        _validate_streaming_clock_progress(self, x_datetime, 1, "data1")

        y_count = len(y_line)
        x_count = len(x_line)
        if y_line._idx != y_datetime._idx or x_line._idx != x_datetime._idx:
            raise ValueError("OLS_BetaN cannot prove input line datetime alignment")

        available = min(y_count, x_count, period)
        if available == 0:
            if y_count == 0 and x_count == 0:
                self.lines.beta[0] = float("nan")
                return
            raise ValueError("OLS_BetaN cannot prove matching input datetime windows")

        if y_count < period or x_count < period:
            _validate_matching_window(
                y_datetime.get(size=available),
                x_datetime.get(size=available),
                available,
            )
            self.lines.beta[0] = float("nan")
            return

        y_end = y_line._idx + 1
        x_end = x_line._idx + 1
        y_start = y_end - period
        x_start = x_end - period
        y_dates = y_datetime.get(size=period)
        x_dates = x_datetime.get(size=period)
        _validate_matching_window(y_dates, x_dates, period)

        # Read numeric values only after the current source clock windows match.
        y = [y_line.array[index] for index in range(y_start, y_end)]
        x = [x_line.array[index] for index in range(x_start, x_end)]
        np = _get_numpy()
        self.lines.beta[0] = _fit_ols_beta(np, y, x, period)

    def once(self, start, end):
        """Calculate rolling beta values from the precomputed input arrays."""
        if len(self.datas) != 2:
            raise ValueError("OLS_BetaN requires exactly two data inputs")

        period = self.p.period
        y_line, y_datetime = _source_line_and_datetime(self.data0, "data0")
        x_line, x_datetime = _source_line_and_datetime(self.data1, "data1")
        y_datetime_values = _validate_ordered_datetimes(y_datetime.array, "data0")
        x_datetime_values = _validate_ordered_datetimes(x_datetime.array, "data1")

        # The indicator clock follows data0. Find data1's own current index
        # by the exact timestamp; never use data0's array index to slice data1.
        x_index_by_datetime = {value: index for index, value in enumerate(x_datetime_values)}
        y_array = y_line.array
        x_array = x_line.array
        if len(y_datetime_values) != len(y_array) or len(x_datetime_values) != len(x_array):
            raise ValueError("OLS_BetaN cannot prove input line datetime alignment")

        beta_array = self.lines.beta.array
        while len(beta_array) < end:
            beta_array.append(float("nan"))

        np = None
        for index in range(start, min(end, len(y_array))):
            if index < period - 1:
                beta_array[index] = float("nan")
                continue

            current_datetime = y_datetime_values[index]
            try:
                x_index = x_index_by_datetime[current_datetime]
            except KeyError as exc:
                raise ValueError("OLS_BetaN requires matching input datetimes") from exc

            window_start = index - period + 1
            x_window_start = x_index - period + 1
            if x_window_start < 0:
                raise ValueError("OLS_BetaN cannot prove matching input datetime windows")

            _validate_matching_window(
                y_datetime_values[window_start : index + 1],
                x_datetime_values[x_window_start : x_index + 1],
                period,
            )

            if np is None:
                np = _get_numpy()
            beta_array[index] = _fit_ols_beta(
                np,
                y_array[window_start : index + 1],
                x_array[x_window_start : x_index + 1],
                period,
            )


class CointN(PeriodN):
    """
    Calculates the score (coint_t) and pvalue for a given ``period`` for the
    data feeds

    Uses ``pandas`` and ``statsmodels`` (for ``coint``)
    """

    _mindatas = 2  # ensure at least 2 data feeds are passed

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
        import pandas as pd

        coint = _get_coint()
        x, y = (pd.Series(d.get(size=self.p.period)) for d in self.datas)
        score, pvalue, _ = coint(x, y, trend=self.p.trend)
        self.lines.score[0] = score
        self.lines.pvalue[0] = pvalue
