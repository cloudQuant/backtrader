"""Native factor declarations for the Iteration 45 multi-factor example."""

import math

from backtrader import Indicator
from backtrader.indicators import Highest, Lowest, ROC, SMA
from backtrader.research import FactorIndicator


class CloseMAFactor(FactorIndicator):
    """Close divided by its complete simple moving average."""

    lines = ("factor",)
    params = (("period", 20),)
    panel_mode = "next"
    formula_fields = ("close",)

    @classmethod
    def lookback_h(cls, period=20):
        if type(period) is not int or period < 1:
            raise ValueError("period must be a positive integer")
        return period - 1

    def __init__(self):
        super().__init__()
        self._averages = {data: SMA(data.close, period=self.p.period) for data in self.datas}

    def next(self):
        for data in self.datas:
            close = float(data.close[0])
            average = float(self._averages[data][0])
            value = math.nan
            if (
                len(data) >= self.p.period
                and math.isfinite(close)
                and math.isfinite(average)
                and average != 0.0
            ):
                value = close / average
            self.outputs[data].factor[0] = value


class ROCFactor(FactorIndicator):
    """Twenty-bar close-to-close simple rate of change."""

    lines = ("factor",)
    params = (("period", 20),)
    panel_mode = "next"
    formula_fields = ("close",)

    @classmethod
    def lookback_h(cls, period=20):
        if type(period) is not int or period < 1:
            raise ValueError("period must be a positive integer")
        return period

    def __init__(self):
        super().__init__()
        self._roc = {data: ROC(data.close, period=self.p.period) for data in self.datas}

    def next(self):
        for data in self.datas:
            close = float(data.close[0])
            previous = math.nan
            if len(data) > self.p.period:
                previous = float(data.close[-self.p.period])
            value = math.nan
            if len(data) > self.p.period and (
                math.isfinite(close) and math.isfinite(previous) and previous != 0.0
            ):
                candidate = float(self._roc[data][0])
                if math.isfinite(candidate):
                    value = candidate
            self.outputs[data].factor[0] = value


class _SafeRSV(Indicator):
    """Native per-feed RSV line with explicit missing zero-range windows."""

    lines = ("rsv",)
    params = (("period", 9),)

    def __init__(self):
        super().__init__()
        self._highest = Highest(self.data.high, period=self.p.period)
        self._lowest = Lowest(self.data.low, period=self.p.period)

    def next(self):
        high = float(self._highest[0])
        low = float(self._lowest[0])
        close = float(self.data.close[0])
        value = math.nan
        if math.isfinite(high) and math.isfinite(low) and math.isfinite(close) and high > low:
            value = 100.0 * (close - low) / (high - low)
        self.lines.rsv[0] = value


class KDJFactor(FactorIndicator):
    """Expose this example's selected J value through the ``factor`` panel line.

    RSV and the smoothed K/D series remain native child indicators. The single
    output line is a convention chosen by this example's panel configuration,
    not a restriction on FactorIndicator outputs.
    """

    lines = ("factor",)
    params = (("period", 9), ("period_dfast", 3), ("period_dslow", 3))
    panel_mode = "next"
    formula_fields = ("high", "low", "close")

    @classmethod
    def lookback_h(cls, period=9, period_dfast=3, period_dslow=3):
        values = (period, period_dfast, period_dslow)
        if any(type(value) is not int or value < 1 for value in values):
            raise ValueError("KDJ periods must be positive integers")
        return sum(values) - len(values)

    def __init__(self):
        super().__init__()
        self._rsv = {}
        self._k = {}
        self._d = {}
        for data in self.datas:
            rsv = _SafeRSV(data, period=self.p.period)
            k = SMA(rsv.rsv, period=self.p.period_dfast)
            d = SMA(k, period=self.p.period_dslow)
            self._rsv[data] = rsv
            self._k[data] = k
            self._d[data] = d

    def next(self):
        for data in self.datas:
            required_bars = self.p.period + self.p.period_dfast + self.p.period_dslow - 2
            k = d = math.nan
            if len(data) >= required_bars:
                k = float(self._k[data][0])
                d = float(self._d[data][0])
            j = math.nan
            if math.isfinite(k) and math.isfinite(d):
                j = 3.0 * k - 2.0 * d
            self.outputs[data].factor[0] = j
