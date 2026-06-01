#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "StepMANRTRIndicator",
]


class StepMANRTRIndicator(Indicator):
    """Reconstructs StepMA_NRTR indicator.

    StepSizeCalc: Volty-based step size from ATR-like calculation.
    StepMACalc: Trend-following MA with NRTR ratchet.
    4 buffers: UpBuffer(0), DnBuffer(1), BuySignal(2), SellSignal(3).
    Buy when trend flips from down to up. Sell on reverse.
    """

    lines = ("trend_up", "trend_down", "buy_signal", "sell_signal")
    params = (
        ("length", 10),
        ("kv", 1.0),
        ("step_size", 0),
        ("percentage", 0),
        ("switch", 1),
    )

    def __init__(self):
        """Initialize rolling state and derived parameters for indicator updates."""
        self._length = int(self.p.length)
        self._kv = float(self.p.kv)
        self._step_size = int(self.p.step_size)
        self._percentage = float(self.p.percentage)
        self._switch = int(self.p.switch)  # 0=Close, 1=HighLow
        self._trend0 = 0
        self._trend1 = 0
        self._trend1_ = 0
        self._smax1 = 0.0
        self._smin1 = 0.0
        self._first = True
        self.addminperiod(self._length + 3)

    def _step_size_calc(self, bar_idx):
        length = self._length
        kv = self._kv
        if self._step_size > 0:
            return self._step_size
        # Volty calculation: average of high-low ranges
        total = 0.0
        for i in range(length):
            h = float(self.data.high[-i])
            low_price = float(self.data.low[-i])
            total += h - low_price
        avg = total / length if length > 0 else 0
        # Convert to points-like value
        step = avg * kv / self.data.close[0] * 10000 if self.data.close[0] != 0 else 0
        return max(step, 1)

    def _step_ma_calc(self):
        step = self._step_size_calc(0)
        point = float(self.data.close[0]) / 10000.0 if float(self.data.close[0]) > 10 else 0.0001
        size_p = step * point
        size_2p = size_p * 2

        cur_high = float(self.data.high[0])
        cur_low = float(self.data.low[0])
        cur_close = float(self.data.close[0])

        if self._first:
            self._trend1 = 0
            self._smax1 = cur_low + size_2p
            self._smin1 = cur_high - size_2p
            self._first = False

        if self._switch:  # HighLow mode
            smax0 = cur_high - size_2p
            smin0 = cur_low + size_2p
        else:
            smax0 = cur_close + size_2p
            smin0 = cur_close - size_2p

        self._trend0 = self._trend1

        if cur_close > self._smax1:
            self._trend0 = 1
        if cur_close < self._smin1:
            self._trend0 = -1

        if self._trend0 > 0:
            if smin0 < self._smin1:
                smin0 = self._smin1
            result = smin0 + size_p
        else:
            if smax0 > self._smax1:
                smax0 = self._smax1
            result = smax0 - size_p

        self._trend1_ = self._trend1
        self._smax1 = smax0
        self._smin1 = smin0
        self._trend1 = self._trend0

        return result, size_p

    def next(self):
        """Compute trend-up/down lines and buy/sell trigger levels for this bar."""
        result, size_p = self._step_ma_calc()
        ratio = self._percentage / 100.0 if self._percentage > 0 else 0
        step = self._step_size_calc(0)
        if step > 0:
            result += ratio / step

        tu = 0.0
        td = 0.0
        bs = 0.0
        ss = 0.0

        point = float(self.data.close[0]) / 10000.0 if float(self.data.close[0]) > 10 else 0.0001

        if self._trend0 > 0:
            tu = result - step * point
            if self._trend1_ < 0:
                bs = tu
        if self._trend0 < 0:
            td = result + step * point
            if self._trend1_ > 0:
                ss = td

        self.lines.trend_up[0] = tu
        self.lines.trend_down[0] = td
        self.lines.buy_signal[0] = bs
        self.lines.sell_signal[0] = ss
