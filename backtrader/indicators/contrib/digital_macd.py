#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from collections import deque

from .. import (
    Indicator,
    SimpleMovingAverage,
)

__all__ = [
    "DigitalMacd",
]


class DigitalMacd(Indicator):
    """Digital MACD indicator built from fixed FIR fast/slow filter banks."""

    lines = ("macd", "signal")
    params = (
        ("signal_period", 5),
        ("point", 0.01),
    )

    FAST_COEFFS = [
        0.2149840610,
        0.2065763732,
        0.1903728890,
        0.1675422436,
        0.1397053150,
        0.1087951881,
        0.0768869405,
        0.0460244906,
        0.0180517395,
        -0.0055294579,
        -0.0236660212,
        -0.0358140055,
        -0.0419497760,
        -0.0425331450,
        -0.0384279507,
        -0.0307917433,
        -0.0209443384,
        -0.0102335925,
        0.0000932767,
        0.0089950015,
        0.0157131144,
        0.0198149331,
        0.0211989019,
        0.0200639819,
        0.0168532934,
        0.0121825067,
        0.0067474241,
        0.0012444305,
        -0.0037087682,
        -0.0076300416,
        -0.0102110543,
        -0.0113306266,
        -0.0110462105,
        -0.0095662166,
        -0.0072080453,
        -0.0043494435,
        -0.0013771970,
        0.0013575268,
        0.0035760416,
        0.0050946166,
        0.0058339574,
        0.0058160431,
        0.0051486631,
        0.0039984014,
        0.0025619380,
        0.0010531475,
        -0.0003481453,
        -0.0014937154,
        -0.0022905986,
        -0.0027000514,
        -0.0027359080,
        -0.0024543322,
        -0.0019409837,
        -0.0012957482,
        -0.0006179734,
        0.0000057542,
        0.0005111297,
        0.0008605279,
        0.0010441921,
        0.0010775684,
        0.0009966494,
        0.0008537300,
        0.0007142855,
        0.0006599146,
        -0.0008151017,
    ]

    SLOW_COEFFS = [
        0.0825641231,
        0.0822783080,
        0.0814249974,
        0.0800166909,
        0.0780735197,
        0.0756232268,
        0.0727009740,
        0.0693478349,
        0.0656105823,
        0.0615409157,
        0.0571939540,
        0.0526285643,
        0.0479025123,
        0.0430785482,
        0.0382152880,
        0.0333706133,
        0.0286021160,
        0.0239614376,
        0.0194972056,
        0.0152532583,
        0.0112682658,
        0.0075745482,
        0.0041980052,
        0.0011588603,
        -0.0015292889,
        -0.0038593393,
        -0.0058303888,
        -0.0074473108,
        -0.0087203043,
        -0.0096645874,
        -0.0102995666,
        -0.0106483424,
        -0.0107374524,
        -0.0105952115,
        -0.0102516944,
        -0.0097377645,
        -0.0090838346,
        -0.0083237046,
        -0.0074804382,
        -0.0065902734,
        -0.0056742995,
        -0.0047554314,
        -0.0038574209,
        -0.0029983549,
        -0.0021924972,
        -0.0014513858,
        -0.0007848072,
        -0.0001995891,
        0.0003009728,
        0.0007162164,
        0.0010478905,
        0.0012994016,
        0.0014755433,
        0.0015824007,
        0.0016272598,
        0.0016185271,
        0.0015648336,
        0.0014747659,
        0.0013569946,
        0.0012193896,
        0.0010695971,
        0.0009140878,
        0.0007591540,
        0.0016019033,
    ]

    def __init__(self):
        """Cache FIR coefficients, set warmup, and build the signal SMA.

        Side effects:
            Stores the fast/slow coefficient tuples, allocates the rolling close
            buffer, sets the minimum warmup period, and wires ``signal`` as an
            SMA of the ``macd`` line.
        """
        self._fast_coeffs = tuple(float(v) for v in self.FAST_COEFFS)
        self._slow_coeffs = tuple(float(v) for v in self.SLOW_COEFFS)
        self._max_lookback = max(len(self._fast_coeffs), len(self._slow_coeffs))
        self._closes = deque(maxlen=self._max_lookback)
        self.addminperiod(self._max_lookback + max(int(self.p.signal_period), 1))
        self._point = float(self.p.point) if float(self.p.point) else 1.0
        self.l.signal = SimpleMovingAverage(self.l.macd, period=max(int(self.p.signal_period), 1))

    def next(self):
        """Convolve the rolling close window with the FIR banks to set ``macd``.

        Emits NaN until the buffer is full, then writes the point-scaled
        difference of the fast and slow digital filter outputs to ``macd``.
        """
        self._closes.append(float(self.data.close[0]))
        if len(self._closes) < self._max_lookback:
            self.l.macd[0] = float("nan")
            return

        closes = tuple(self._closes)
        fast_dma = 0.0
        for idx, coeff in enumerate(self._fast_coeffs):
            fast_dma += coeff * closes[-(idx + 1)]

        slow_dma = 0.0
        for idx, coeff in enumerate(self._slow_coeffs):
            slow_dma += coeff * closes[-(idx + 1)]

        self.l.macd[0] = (fast_dma - slow_dma) / self._point
