#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator
from ...linebuffer import _factor_context_for_line, _reject_factor_infinity

__all__ = [
    "RFTLIndicator",
]


RFTL_WEIGHTS = [
    -0.0025097319,
    0.0513007762,
    0.1142800493,
    0.1699342860,
    0.2025269304,
    0.2025269304,
    0.1699342860,
    0.1142800493,
    0.0513007762,
    -0.0025097319,
]


class RFTLIndicator(Indicator):
    """Indicator that computes a weighted RFTL value from weighted close history."""

    lines = ("rftl",)
    params = (("weights", tuple(RFTL_WEIGHTS)),)

    def __init__(self):
        """Preserve the historical scheduling minimum for the weighted window."""
        self._rftl_weights = tuple(float(weight) for weight in self.p.weights)
        declared_count = len(self.p.weights)
        count = len(self._rftl_weights)
        if not count:
            raise TypeError("RFTL weights must not be empty")
        object.__setattr__(self, "_rftl_source", self.data.close)
        source_minperiod = self._rftl_source._minperiod
        minimum = max(self._minperiod, source_minperiod + count - 1) + declared_count
        self.addminperiod(minimum - self._minperiod + 1)
        self.lines.rftl.updateminperiod(minimum)

    def prenext(self):
        self.next()

    def next(self):
        """Recalculate from the current data window, including replay updates."""
        if len(self.data) < len(self._rftl_weights):
            if _factor_context_for_line(self.lines.rftl) is not None:
                total = 0.0
                for weight in self._rftl_weights:
                    _reject_factor_infinity(self.lines.rftl, weight)
                for offset, weight in enumerate(self._rftl_weights[: len(self.data)]):
                    total = self._combine(total, weight, self._rftl_source[-offset])
            self.lines.rftl[0] = float("nan")
            return
        total = 0.0
        for offset, weight in enumerate(self._rftl_weights):
            total = self._combine(total, weight, self._rftl_source[-offset])
        self.lines.rftl[0] = total

    def _combine(self, total, weight, value):
        """Retain the line-operation checks at each multiplication and sum."""
        line = self.lines.rftl
        for item in (total, weight, value):
            _reject_factor_infinity(line, item)
        if weight != weight or value != value:
            return float("nan")
        if abs(weight) == float("inf"):
            weight = 0.0
        if abs(value) == float("inf"):
            value = 0.0
        product = weight * value
        _reject_factor_infinity(line, product)
        if abs(product) == float("inf"):
            product = 0.0
        if total != total:
            return float("nan")
        result = total + product
        _reject_factor_infinity(line, result)
        return 0.0 if abs(result) == float("inf") else result

    def preonce(self, start, end):
        self.once(start, end)

    def once(self, start, end):
        """Write only the requested batch range, preserving earlier segments."""
        source = self._rftl_source.array
        target = self.lines.rftl.array
        weights = self._rftl_weights
        for index in range(start, end):
            if index < len(weights) - 1:
                if _factor_context_for_line(self.lines.rftl) is not None:
                    total = 0.0
                    for weight in weights:
                        _reject_factor_infinity(self.lines.rftl, weight)
                    for offset, weight in enumerate(weights[: index + 1]):
                        total = self._combine(total, weight, source[index - offset])
                target[index] = float("nan")
                continue
            total = 0.0
            for offset, weight in enumerate(weights):
                total = self._combine(total, weight, source[index - offset])
            target[index] = total
