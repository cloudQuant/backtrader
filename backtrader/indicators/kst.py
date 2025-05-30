#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
import backtrader as bt
from . import SMA, ROC100


# KnowSureThing指标
class KnowSureThing(bt.Indicator):
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
        rcma1 = self.p._rmovav(ROC100(period=self.p.rp1), period=self.p.rma1)
        rcma2 = self.p._rmovav(ROC100(period=self.p.rp2), period=self.p.rma2)
        rcma3 = self.p._rmovav(ROC100(period=self.p.rp3), period=self.p.rma3)
        rcma4 = self.p._rmovav(ROC100(period=self.p.rp4), period=self.p.rma4)
        self.l.kst = sum(
            [rfi * rci for rfi, rci in zip(self.p.rfactors, [rcma1, rcma2, rcma3, rcma4])]
        )

        self.l.signal = self.p._smovav(self.l.kst, period=self.p.rsignal)
        super(KnowSureThing, self).__init__()
