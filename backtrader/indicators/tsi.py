#!/usr/bin/env python
"""TSI Indicator Module - True Strength Index.

This module provides the TSI (True Strength Index) indicator developed
by William Blau for measuring momentum with double smoothing.

Classes:
    TrueStrengthIndicator: TSI indicator (alias: TSI).

Example:
    class MyStrategy(bt.Strategy):
        def __init__(self):
            self.tsi = bt.indicators.TSI(self.data.close, period1=25, period2=13)

        def next(self):
            if self.tsi[0] > 0:
                self.buy()
"""

from . import Indicator
from ..functions import DivByZero
from .ema import ExponentialMovingAverage


class TrueStrengthIndicator(Indicator):
    """
    The True Strength Indicators was first introduced in Stocks & Commodities
    Magazine by its author William Blau. It measures momentum with a double
    exponential (default) of the prices.

    It shows divergence if the extremes keep on growign but closing prices
    do not in the same manner (distance to the extremes grows)

    Formula:
      - price_change = close - close(pchange periods ago)
      - sm1_simple = EMA(price_close_change, period1)
      - sm1_double = EMA(sm1_simple, period2)
      - sm2_simple = EMA(abs(price_close_change), period1)
      - sm2_double = EMA(sm2_simple, period2)
      - tsi = 100.0 * sm1_double / sm2_double

    See:
      - http://stockcharts.com/school/doku.php?id=chart_school:technical_indicators:true_strength_index

    Params

      - ``period1``: the period for the first smoothing
      - ``period2``: the period for the second smoothing
      - ``pchange``: the lookback period for the price change
      - ``_movav``: the moving average to apply for the smoothing
    """

    alias = ("TSI",)
    params = (
        ("period1", 25),
        ("period2", 13),
        ("pchange", 1),
        ("_movav", ExponentialMovingAverage),
    )
    lines = ("tsi",)

    def __init__(self):
        """Initialize the TSI indicator.

        Calculates alpha values for double smoothing and sets
        minimum period from the first price change through both EMA seeds.
        """
        super().__init__()
        self._uses_manual_ema = self.p._movav is ExponentialMovingAverage
        if not self._uses_manual_ema:
            momentum = self.data - self.data(-self.p.pchange)
            sm1 = self.p._movav(momentum, period=self.p.period1)
            sm12 = self.p._movav(sm1, period=self.p.period2)
            abs_momentum = abs(momentum)
            sm2 = self.p._movav(abs_momentum, period=self.p.period1)
            sm22 = self.p._movav(sm2, period=self.p.period2)
            self.lines.tsi = DivByZero(100.0 * sm12, sm22, zero=0.0)
            return

        self.alpha1 = 2.0 / (1.0 + self.p.period1)
        self.alpha1_1 = 1.0 - self.alpha1
        self.alpha2 = 2.0 / (1.0 + self.p.period2)
        self.alpha2_1 = 1.0 - self.alpha2

        # The input may itself have a warmup. Its first valid price change is
        # available after that source minimum period plus ``pchange`` bars.
        self._source_minperiod = max(1, getattr(self.data, "_minperiod", 1))
        self._sm1_seed_sum = 0.0
        self._sm2_seed_sum = 0.0
        self._sm1_seed_count = 0
        self._sm1 = 0.0
        self._sm2 = 0.0
        self._sm1_ready = False
        self._sm12_seed_sum = 0.0
        self._sm22_seed_sum = 0.0
        self._sm12_seed_count = 0
        self._sm12 = 0.0
        self._sm22 = 0.0
        self._sm12_ready = False

        # EMA(period1) first produces a value after period1 price changes;
        # EMA(period2) then needs period2 of those values. The overlapping
        # boundary bar is counted once.
        self.addminperiod(self.p.pchange + self.p.period1 + self.p.period2 - 1)

    @staticmethod
    def _ema_step(previous, current, alpha, alpha1):
        """Apply one EMA recurrence step after its SMA seed."""
        return previous * alpha1 + current * alpha

    @staticmethod
    def _ratio(smoothed_momentum, smoothed_absolute_momentum):
        """Return TSI, with a defined zero result for a flat denominator."""
        if smoothed_absolute_momentum != 0:
            return 100.0 * smoothed_momentum / smoothed_absolute_momentum
        return 0.0

    def _process_next(self):
        """Advance both EMA stages by one available input price change."""
        if not self._uses_manual_ema:
            return

        data_len = len(self.data)
        if data_len < self._source_minperiod + self.p.pchange:
            self.lines.tsi[0] = float("nan")
            return

        pc = self.data[0] - self.data[-self.p.pchange]

        if not self._sm1_ready:
            self._sm1_seed_sum += pc
            self._sm2_seed_sum += abs(pc)
            self._sm1_seed_count += 1
            if self._sm1_seed_count < self.p.period1:
                self.lines.tsi[0] = float("nan")
                return

            self._sm1 = self._sm1_seed_sum / self.p.period1
            self._sm2 = self._sm2_seed_sum / self.p.period1
            self._sm1_ready = True
        else:
            self._sm1 = self._ema_step(
                self._sm1, pc, self.alpha1, self.alpha1_1
            )
            self._sm2 = self._ema_step(
                self._sm2, abs(pc), self.alpha1, self.alpha1_1
            )

        if not self._sm12_ready:
            self._sm12_seed_sum += self._sm1
            self._sm22_seed_sum += self._sm2
            self._sm12_seed_count += 1
            if self._sm12_seed_count < self.p.period2:
                self.lines.tsi[0] = float("nan")
                return

            self._sm12 = self._sm12_seed_sum / self.p.period2
            self._sm22 = self._sm22_seed_sum / self.p.period2
            self._sm12_ready = True
        else:
            self._sm12 = self._ema_step(
                self._sm12, self._sm1, self.alpha2, self.alpha2_1
            )
            self._sm22 = self._ema_step(
                self._sm22, self._sm2, self.alpha2, self.alpha2_1
            )

        self.lines.tsi[0] = self._ratio(self._sm12, self._sm22)

    def prenext(self):
        """Accumulate both EMA seeds while the output is warming up."""
        self._process_next()

    def nextstart(self):
        """Emit the first TSI value after both SMA-seeded EMAs are ready."""
        self._process_next()

    def next(self):
        """Calculate TSI for the current bar.

        Applies double smoothing to price change and absolute price change,
        then computes the ratio as a percentage.
        """
        self._process_next()

    def once(self, start, end):
        """Calculate TSI in runonce mode.

        Seed each EMA with the SMA of its first full input window, matching
        the incremental path used by ``prenext``/``next``.
        """
        if not self._uses_manual_ema:
            return
        if end <= start:
            return

        darray = self.data.array
        larray = self.lines.tsi.array
        pchange = self.p.pchange
        alpha1 = self.alpha1
        alpha1_1 = self.alpha1_1
        alpha2 = self.alpha2
        alpha2_1 = self.alpha2_1
        period1 = self.p.period1
        period2 = self.p.period2
        limit = min(end, len(darray))

        while len(larray) < end:
            larray.append(float("nan"))

        write_start = max(start, 0)
        write_end = min(end, len(larray))
        for i in range(write_start, write_end):
            larray[i] = float("nan")

        first_pc = self._source_minperiod - 1 + pchange
        first_ema1 = first_pc + period1 - 1
        first_tsi = first_ema1 + period2 - 1
        if first_tsi >= limit:
            return

        sm1_sum = 0.0
        sm2_sum = 0.0
        for i in range(first_pc, first_ema1 + 1):
            pc = darray[i] - darray[i - pchange]
            sm1_sum += pc
            sm2_sum += abs(pc)

        sm1 = sm1_sum / period1
        sm2 = sm2_sum / period1
        sm12_sum = sm1
        sm22_sum = sm2

        for i in range(first_ema1 + 1, first_tsi + 1):
            pc = darray[i] - darray[i - pchange]
            sm1 = self._ema_step(sm1, pc, alpha1, alpha1_1)
            sm2 = self._ema_step(sm2, abs(pc), alpha1, alpha1_1)
            sm12_sum += sm1
            sm22_sum += sm2

        sm12 = sm12_sum / period2
        sm22 = sm22_sum / period2
        if start <= first_tsi < end:
            larray[first_tsi] = self._ratio(sm12, sm22)

        for i in range(first_tsi + 1, limit):
            pc = darray[i] - darray[i - pchange]
            sm1 = self._ema_step(sm1, pc, alpha1, alpha1_1)
            sm2 = self._ema_step(sm2, abs(pc), alpha1, alpha1_1)
            sm12 = self._ema_step(sm12, sm1, alpha2, alpha2_1)
            sm22 = self._ema_step(sm22, sm2, alpha2, alpha2_1)
            if start <= i < end:
                larray[i] = self._ratio(sm12, sm22)
