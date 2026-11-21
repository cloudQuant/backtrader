#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math
import numbers

from ...linebuffer import _reject_factor_infinity
from .. import Indicator

__all__ = [
    "SafeADX",
    "SafeAMA",
]


def _checked(line, value):
    """Reject float infinity in strict factors without altering ordinary results."""
    if type(value) is float and math.isinf(value):
        _reject_factor_infinity(line, value)
    return value


class SafeADX(Indicator):
    """ADX indicator implementation without division by zero pitfalls."""

    lines = ("adx",)
    params = (("period", 14),)

    def __init__(self):
        """Set minimum lookback period."""
        self.addminperiod(self.p.period + 3)

    def next(self):
        """Compute safe directional movement and ADX-like intensity."""
        pdm_vals = []
        mdm_vals = []
        tr_vals = []
        for idx in range(self.p.period):
            high0 = float(self.data.high[-idx])
            high1 = float(self.data.high[-idx - 1])
            low0 = float(self.data.low[-idx])
            low1 = float(self.data.low[-idx - 1])
            close1 = float(self.data.close[-idx - 1])
            missing = False
            for value in (high0, high1, low0, low1, close1):
                if math.isnan(value):
                    missing = True
                else:
                    _checked(self.lines.adx, value)
            if missing:
                self.lines.adx[0] = float("nan")
                return
            up_move = _checked(self.lines.adx, high0 - high1)
            down_move = _checked(self.lines.adx, low1 - low0)
            pdm = up_move if up_move > down_move and up_move > 0 else 0.0
            mdm = down_move if down_move > up_move and down_move > 0 else 0.0
            tr = max(
                _checked(self.lines.adx, high0 - low0),
                abs(_checked(self.lines.adx, high0 - close1)),
                abs(_checked(self.lines.adx, low0 - close1)),
            )
            pdm_vals.append(pdm)
            mdm_vals.append(mdm)
            tr_vals.append(tr)
        tr_sum = _checked(self.lines.adx, sum(tr_vals))
        if tr_sum <= 1e-12:
            self.lines.adx[0] = 0.0
            return
        pdi = _checked(self.lines.adx, _checked(self.lines.adx, 100.0 * sum(pdm_vals)) / tr_sum)
        mdi = _checked(self.lines.adx, _checked(self.lines.adx, 100.0 * sum(mdm_vals)) / tr_sum)
        denom = _checked(self.lines.adx, pdi + mdi)
        if denom <= 1e-12:
            self.lines.adx[0] = 0.0
            return
        difference = _checked(self.lines.adx, pdi - mdi)
        scaled = _checked(self.lines.adx, 100.0 * abs(difference))
        self.lines.adx[0] = _checked(self.lines.adx, scaled / denom)


def _checked_ama(line, value):
    """Inspect ordinary/NumPy real scalars without calling float subclass hooks."""
    value_type = type(value)
    if issubclass(value_type, float):
        _checked(line, float.__float__(value))
    elif type.__getattribute__(value_type, "__module__") == "numpy" and issubclass(
        value_type, numbers.Real
    ):
        _checked(line, float(value))
    return value


class SafeAMA(Indicator):
    """Adaptive moving average indicator with safe initialization."""

    lines = ("ama",)
    params = (
        ("period", 9),
        ("fast_period", 2),
        ("slow_period", 30),
    )

    def __init__(self):
        """Initialize adaptive moving average state and warm-up window."""
        self._prev = None
        self._ama_recovering = False
        self._ama_source_length = None
        self._ama_prior_state = (None, False)
        self.addminperiod(self.p.period + 3)

    def next(self):
        """Update the AMA from the preceding source bar's committed state.

        Missing close values invalidate the efficiency window and clear its
        recursive seed. A complete non-NaN window is needed before reseeding.
        """
        source_length = len(self.data)
        prior_state = (
            (self._prev, self._ama_recovering)
            if source_length != self._ama_source_length
            else self._ama_prior_state
        )
        prev, recovering = prior_state
        line = self.lines.ama

        def publish(value, next_prev, next_recovering):
            line[0] = value
            self._ama_source_length = source_length
            self._ama_prior_state = prior_state
            self._prev, self._ama_recovering = next_prev, next_recovering
        price = float(self.data.close[0])
        if math.isnan(price):
            publish(float("nan"), None, True)
            return
        _checked_ama(line, price)
        if prev is None:
            if recovering:
                for idx in range(1, self.p.period + 1):
                    value = float(self.data.close[-idx])
                    if math.isnan(value):
                        publish(float("nan"), None, True)
                        return
                    _checked_ama(line, value)
            publish(price, price, False)
            return

        past = float(self.data.close[-self.p.period])
        if math.isnan(past):
            publish(float("nan"), None, True)
            return
        _checked_ama(line, past)
        direction = abs(_checked_ama(line, price - past))
        volatility = 0.0
        for idx in range(self.p.period):
            a = float(self.data.close[-idx])
            b = float(self.data.close[-idx - 1])
            if math.isnan(a) or math.isnan(b):
                publish(float("nan"), None, True)
                return
            _checked_ama(line, a)
            _checked_ama(line, b)
            change = _checked_ama(line, a - b)
            volatility = _checked_ama(line, volatility + abs(change))
        efficiency = 0.0 if volatility <= 1e-12 else _checked_ama(line, direction / volatility)
        fast_den = _checked_ama(line, self.p.fast_period + 1.0)
        fast_sc = _checked_ama(line, 2.0 / fast_den)
        slow_den = _checked_ama(line, self.p.slow_period + 1.0)
        slow_sc = _checked_ama(line, 2.0 / slow_den)
        delta_sc = _checked_ama(line, fast_sc - slow_sc)
        ratio_part = _checked_ama(line, efficiency * delta_sc)
        smoothing_base = _checked_ama(line, ratio_part + slow_sc)
        smoothing = _checked_ama(line, smoothing_base ** 2)
        price_delta = _checked_ama(line, float(self.data.close[0]) - prev)
        scaled = _checked_ama(line, smoothing * price_delta)
        current = _checked_ama(line, prev + scaled)
        publish(current, current, False)
