#!/usr/bin/env python
"""KST Indicator Module - Know Sure Thing indicator.

This module provides the KST (Know Sure Thing) momentum indicator
developed by Martin Pring.

Classes:
    KnowSureThing: KST indicator (alias: KST).

Example:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.addindicator(bt.indicators.KST)
"""
import math

from . import ROC100, SMA, Indicator


class KnowSureThing(Indicator):
    """
    It is a "summed" momentum indicator. Developed by Martin Pring and
    published in 1992 in Stocks & Commodities.

    Formula:
      - rcma1 = MovAv(roc100(rp1), period)
      - rcma2 = MovAv(roc100(rp2), period)
      - rcma3 = MovAv(roc100(rp3), period)
      - rcma4 = MovAv(roc100(rp4), period)

      - Kst = 1.0 * rcma1 + 2.0 * rcma2 + 3.0 * rcma3 + 4.0 * rcma4
      - signal = MovAv(kst, speriod)

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:know_sure_thing_kst

    Params

      - ``rma1``, ``rma2``, ``rma3``, ``rma4``: for the MovingAverages on ROCs
      - ``rp1``, ``rp2``, ``rp3``, ``rp4``: for the ROCs
      - ``rsig``: for the MovingAverage for the signal line
      - ``rfactors``: list of factors to apply to the different MovAv(ROCs)
      - ``_movav`` and ``_movavs``, allows to change the Moving Average type
        applied for the calculation of kst and signal

    """

    alias = ("KST",)
    lines = (
        "kst",
        "signal",
    )
    params = (
        ("rp1", 10),
        ("rp2", 15),
        ("rp3", 20),
        ("rp4", 30),
        ("rma1", 10),
        ("rma2", 10),
        ("rma3", 10),
        ("rma4", 10),
        ("rsignal", 9),
        ("rfactors", [1.0, 2.0, 3.0, 4.0]),
        ("_rmovav", SMA),
        ("_smovav", SMA),
    )

    plotinfo = dict(plothlines=[0.0])

    def __init__(self):
        """Initialize the KST indicator.

        Creates 4 ROC and moving average sub-indicators.
        """
        super().__init__()
        self.rcma1 = self.p._rmovav(ROC100(self.data, period=self.p.rp1), period=self.p.rma1)
        self.rcma2 = self.p._rmovav(ROC100(self.data, period=self.p.rp2), period=self.p.rma2)
        self.rcma3 = self.p._rmovav(ROC100(self.data, period=self.p.rp3), period=self.p.rma3)
        self.rcma4 = self.p._rmovav(ROC100(self.data, period=self.p.rp4), period=self.p.rma4)

    def next(self):
        """Calculate KST and signal for the current bar.

        Formula: KST = w1*RCMA1 + w2*RCMA2 + w3*RCMA3 + w4*RCMA4
        Signal = SMA(KST, rsignal)
        """
        rf = self.p.rfactors
        kst_val = (
            rf[0] * self.rcma1[0]
            + rf[1] * self.rcma2[0]
            + rf[2] * self.rcma3[0]
            + rf[3] * self.rcma4[0]
        )
        self.lines.kst[0] = kst_val

        # Calculate signal (SMA of KST)
        rsignal = self.p.rsignal
        kst_sum = kst_val
        for i in range(1, rsignal):
            kst_sum += self.lines.kst[-i]
        self.lines.signal[0] = kst_sum / rsignal

    def once(self, start, end):
        """Calculate KST and signal in runonce mode."""
        rcma1_array = self.rcma1.lines[0].array
        rcma2_array = self.rcma2.lines[0].array
        rcma3_array = self.rcma3.lines[0].array
        rcma4_array = self.rcma4.lines[0].array
        kst_array = self.lines.kst.array
        signal_array = self.lines.signal.array
        rf = self.p.rfactors
        rsignal = self.p.rsignal

        for arr in [kst_array, signal_array]:
            while len(arr) < end:
                arr.append(0.0)

        # Calculate KST
        for i in range(
            start, min(end, len(rcma1_array), len(rcma2_array), len(rcma3_array), len(rcma4_array))
        ):
            v1 = rcma1_array[i] if i < len(rcma1_array) else 0.0
            v2 = rcma2_array[i] if i < len(rcma2_array) else 0.0
            v3 = rcma3_array[i] if i < len(rcma3_array) else 0.0
            v4 = rcma4_array[i] if i < len(rcma4_array) else 0.0

            if any(isinstance(v, float) and math.isnan(v) for v in [v1, v2, v3, v4]):
                kst_array[i] = float("nan")
            else:
                kst_array[i] = rf[0] * v1 + rf[1] * v2 + rf[2] * v3 + rf[3] * v4

        # Calculate signal (SMA of KST)
        for i in range(start, min(end, len(kst_array))):
            kst_val = kst_array[i]
            if isinstance(kst_val, float) and math.isnan(kst_val):
                signal_array[i] = float("nan")
            elif i < rsignal - 1:
                signal_array[i] = float("nan")
            else:
                kst_sum = 0.0
                valid = True
                for j in range(rsignal):
                    idx = i - j
                    if idx >= 0 and idx < len(kst_array):
                        val = kst_array[idx]
                        if isinstance(val, float) and math.isnan(val):
                            valid = False
                            break
                        kst_sum += val
                if valid:
                    signal_array[i] = kst_sum / rsignal
                else:
                    signal_array[i] = float("nan")
