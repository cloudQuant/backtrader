#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "ColorHMA",
]


def _weighted_ma(values):
    weights = list(range(1, len(values) + 1))
    denominator = float(sum(weights))
    return sum(value * weight for value, weight in zip(values, weights)) / denominator


def _color_hma_once_indicator_source(indicator, start, end, callback_name):
    """Align an indicator source while retaining the original advance sequence."""
    if end <= start:
        return
    inputs = []
    seen = set()
    sources = (*indicator.datas, *indicator._lineiterators[0])
    for source in sources:
        for line in source.lines:
            if id(line) not in seen:
                seen.add(id(line))
                inputs.append((line, line.idx, line.lencount))
    outputs = [(line, line.idx, line.lencount) for line in indicator.lines]
    manual_recompute = any(idx >= start for _line, idx, _count in outputs)
    saved_history = indicator._dma_history[:]
    saved_bar = indicator._last_dma_bar
    try:
        if manual_recompute:
            indicator._dma_history = []
            indicator._last_dma_bar = None
            first = indicator._source_minperiod + indicator.period - 2
            for index in range(max(first, start - indicator.sqrt_period + 1), start):
                for line, _idx, _count in inputs:
                    line.idx = index
                    line.lencount = index + 1
                half = _weighted_ma(indicator._window(indicator.half_period))
                full = _weighted_ma(indicator._window(indicator.period))
                indicator._dma_history.append(2.0 * half - full)
                indicator._last_dma_bar = index + 1
            for line, idx, count in inputs:
                line.idx = idx
                line.lencount = count
        for index in range(start, end):
            for source in sources:
                source.advance()
            indicator.lines.advance()
            virtual = [
                (line, line.idx, line.lencount) for line, _idx, _count in (*inputs, *outputs)
            ]
            try:
                for line, _idx, _count in virtual:
                    line.idx = index
                    line.lencount = index + 1
                if callback_name == "prenext":
                    indicator.prenext()
                else:
                    indicator._factor_run_callback(
                        getattr(indicator, callback_name), "once_via_next"
                    )
            finally:
                for line, idx, count in virtual:
                    line.idx = idx
                    line.lencount = count
    finally:
        if manual_recompute:
            indicator._dma_history = saved_history
            indicator._last_dma_bar = saved_bar
            for line, idx, count in (*inputs, *outputs):
                line.idx = idx
                line.lencount = count


class ColorHMA(Indicator):
    """Hull Moving Average line plus its slope-direction ("color") line."""

    lines = ("hma", "direction")
    params = (("period", 13),)

    def __init__(self):
        """Derive the half, full, and sqrt periods and set the warmup window."""
        self.period = max(int(self.p.period), 2)
        self.half_period = max(int(math.floor(self.period / 2.0)), 1)
        self.sqrt_period = max(int(math.floor(math.sqrt(self.period))), 1)
        self._dma_history = []
        self._last_dma_bar = None
        self._source_minperiod = self.data._minperiod
        self.addminperiod(self._source_minperiod + self.period + self.sqrt_period - 1)

    def prenext(self):
        """Accumulate complete intermediate windows during warmup."""
        ColorHMA.next(self)

    def _window(self, length):
        return [float(self.data[-idx]) for idx in range(length - 1, -1, -1)]

    def preonce(self, start, end):
        if isinstance(self.data, Indicator):
            _color_hma_once_indicator_source(self, start, end, "prenext")
        else:
            self.preonce_via_prenext(start, end)

    def oncestart(self, start, end):
        if isinstance(self.data, Indicator):
            _color_hma_once_indicator_source(self, start, end, "nextstart")
        else:
            self.oncestart_via_nextstart(start, end)

    def once(self, start, end):
        if isinstance(self.data, Indicator):
            _color_hma_once_indicator_source(self, start, end, "next")
        else:
            self.once_via_next(start, end)

    def next(self):
        """Compute the HMA value for this bar and update its slope direction."""
        bar = len(self.data)
        if bar < self._source_minperiod + self.period - 1:
            return

        half_values = self._window(self.half_period)
        full_values = self._window(self.period)
        dma = 2.0 * _weighted_ma(half_values) - _weighted_ma(full_values)
        if self._last_dma_bar == bar:
            self._dma_history[-1] = dma
        else:
            if self._last_dma_bar is not None and bar < self._last_dma_bar:
                self._dma_history.clear()
            self._dma_history.append(dma)
            if len(self._dma_history) > self.sqrt_period:
                del self._dma_history[0]
        self._last_dma_bar = bar

        if len(self._dma_history) < self.sqrt_period:
            self.l.hma[0] = float("nan")
            self.l.direction[0] = float("nan")
            return

        hma = _weighted_ma(self._dma_history)
        prev_hma = float(self.l.hma[-1])
        if not math.isfinite(hma) or not math.isfinite(prev_hma):
            direction = float("nan")
        elif prev_hma < hma:
            direction = 1.0
        elif prev_hma > hma:
            direction = -1.0
        else:
            previous = float(self.l.direction[-1])
            direction = previous if math.isfinite(previous) else 0.0
        self.l.hma[0] = hma
        self.l.direction[0] = direction
