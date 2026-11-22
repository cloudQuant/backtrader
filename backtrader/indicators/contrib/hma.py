#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator
from ...linebuffer import _factor_context_for_line, _factor_phase

__all__ = [
    "HMA",
    "OsHMAIndicator",
]


def _preserve_subclass_callbacks(cls):
    """Use the callback lifecycle for subclass overrides without a batch peer."""
    namespace = cls.__dict__
    if "next" in namespace and "once" not in namespace:
        cls.once = Indicator.once_via_next
        if "preonce" not in namespace:
            cls.preonce = Indicator.preonce_via_prenext
        if "oncestart" not in namespace:
            cls.oncestart = Indicator.oncestart_via_nextstart
    else:
        if "prenext" in namespace and "preonce" not in namespace:
            cls.preonce = Indicator.preonce_via_prenext
        if "nextstart" in namespace and "oncestart" not in namespace:
            cls.oncestart = Indicator.oncestart_via_nextstart


class HMA(Indicator):
    """Hull Moving Average indicator used by OsHMA."""

    lines = ("hma",)
    params = (("period", 13),)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        _preserve_subclass_callbacks(cls)

    def __init__(self):
        """Use exactly the window required by the three weighted averages."""
        self._period = int(self.p.period)
        if self._period < 1:
            raise ValueError("HMA period must be positive")
        self._half = max(1, self._period // 2)
        self._sqrt = max(1, math.isqrt(self._period))
        self._window = self._period + self._sqrt - 1
        self.addminperiod(self._window)
        self.updateminperiod(getattr(self.data, "_minperiod", 1) + self._window - 1)

    def _wma(self, values, check):
        count = len(values)
        weighted = [(i + 1) * value for i, value in enumerate(values)]
        if check is not None:
            for value in values:
                check(value)
            for value in weighted:
                check(value)
        result = (2.0 / (count * (count + 1.0))) * math.fsum(weighted)
        if check is not None:
            check(result)
        return result

    def _calculate(self, values):
        # Recompute from the input window: the current replay bar may be revised
        # repeatedly without advancing its length.
        context = _factor_context_for_line(self.lines.hma)
        check = None
        if context is not None:
            from ...research.strict import reject_infinity

            phase = _factor_phase(context)

            def check(value):
                reject_infinity(context, value, phase, operation=self.lines.hma)
        differences = []
        for end in range(self._period, self._window + 1):
            full = values[end - self._period:end]
            half = values[end - self._half:end]
            doubled = 2.0 * self._wma(half, check)
            if check is not None:
                check(doubled)
            difference = doubled - self._wma(full, check)
            if check is not None:
                check(difference)
            differences.append(difference)
        return self._wma(differences, check)

    def next(self):
        self.lines.hma[0] = self._calculate(self.data.get(size=self._window))

    def once(self, start, end):
        source, output = self.data.array, self.lines.hma.array
        for index in range(max(start, self._minperiod - 1), min(end, len(source), len(output))):
            output[index] = self._calculate(source[index - self._window + 1:index + 1])


class OsHMAIndicator(Indicator):
    """Histogram indicator that combines fast and slow HMA lines."""

    lines = ("hist",)
    params = (
        ("fast_hma", 13),
        ("slow_hma", 26),
    )

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        _preserve_subclass_callbacks(cls)

    def __init__(self):
        """Initialize fast and slow HMA sub-indicators and histogram output."""
        periods = (int(self.p.fast_hma), int(self.p.slow_hma))
        if min(periods) < 1:
            raise ValueError("OsHMA periods must be positive")
        self.addminperiod(max(p + math.isqrt(p) - 1 for p in periods))
        self._fast = HMA(self.data.close, period=periods[0])
        self._slow = HMA(self.data.close, period=periods[1])

    def next(self):
        self.lines.hist[0] = self._fast.hma[0] - self._slow.hma[0]

    def once(self, start, end):
        fast, slow, output = self._fast.hma.array, self._slow.hma.array, self.lines.hist.array
        context = _factor_context_for_line(self.lines.hist)
        if context is not None:
            from ...research.strict import reject_infinity

            phase = _factor_phase(context)
        for index in range(max(start, self._minperiod - 1), min(end, len(fast), len(slow), len(output))):
            if context is not None:
                reject_infinity(context, fast[index], phase, operation=self.lines.hist)
                reject_infinity(context, slow[index], phase, operation=self.lines.hist)
            value = fast[index] - slow[index]
            if context is not None:
                reject_infinity(context, value, phase, operation=self.lines.hist)
            output[index] = value
