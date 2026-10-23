"""Factor declarations for the Iteration 45 multi-factor example."""

import math

from backtrader import Indicator
from backtrader.indicators import Highest, Lowest, ROC, SMA
from backtrader.research import FactorIndicator
from backtrader.research.factor_indicator import (
    _factor_once_execute,
    _factor_once_read,
    _factor_once_write,
)


def _close_ratio(close, average):
    value = math.nan
    if math.isfinite(close) and math.isfinite(average) and average != 0.0:
        value = close / average
    return value


def _kdj_rsv(high, low, close):
    value = math.nan
    if math.isfinite(high) and math.isfinite(low) and math.isfinite(close) and high > low:
        value = 100.0 * (close - low) / (high - low)
    return value


def _kdj_j(k, d):
    value = math.nan
    if math.isfinite(k) and math.isfinite(d):
        value = 3.0 * k - 2.0 * d
    return value


class CloseMAFactor(FactorIndicator):
    """Close divided by its complete simple moving average."""

    lines = ("factor",)
    params = (("period", 20),)
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
            if len(data) >= self.p.period:
                value = _close_ratio(close, average)
            self.outputs[data].factor[0] = value

    def _once_range(self, start, end):
        period = self.p.period
        for index in range(start, end):
            for data in self.datas:
                close = float(_factor_once_read(data.close, index))
                average = float(_factor_once_read(self._averages[data].lines[0], index))
                value = math.nan
                if index + 1 >= period:
                    value = _close_ratio(close, average)
                _factor_once_write(self.outputs[data].factor, index, value)

    def preonce(self, start, end):
        if not _factor_once_execute(
            self, CloseMAFactor, self._once_range, start, end, phase="once"
        ):
            Indicator.preonce_via_prenext(self, start, end)

    def oncestart(self, start, end):
        if not _factor_once_execute(self, CloseMAFactor, self._once_range, start, end):
            Indicator.oncestart_via_nextstart(self, start, end)

    def once(self, start, end):
        if not _factor_once_execute(self, CloseMAFactor, self._once_range, start, end):
            Indicator.once_via_next(self, start, end)

    @classmethod
    def build(cls, ctx, period=20, **params):
        return ctx.apply(_close_ratio, ctx.close, ctx.sma(ctx.close, period))


class ROCFactor(FactorIndicator):
    """Twenty-bar close-to-close simple rate of change."""

    lines = ("factor",)
    params = (("period", 20),)
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

    def _once_range(self, start, end):
        period = self.p.period
        for index in range(start, end):
            bars = index + 1
            for data in self.datas:
                close = float(_factor_once_read(data.close, index))
                previous = math.nan
                if bars > period:
                    previous = float(_factor_once_read(data.close, index, -period))
                value = math.nan
                if bars > period and (
                    math.isfinite(close) and math.isfinite(previous) and previous != 0.0
                ):
                    candidate = float(_factor_once_read(self._roc[data].lines[0], index))
                    if math.isfinite(candidate):
                        value = candidate
                _factor_once_write(self.outputs[data].factor, index, value)

    def preonce(self, start, end):
        if not _factor_once_execute(self, ROCFactor, self._once_range, start, end, phase="once"):
            Indicator.preonce_via_prenext(self, start, end)

    def oncestart(self, start, end):
        if not _factor_once_execute(self, ROCFactor, self._once_range, start, end):
            Indicator.oncestart_via_nextstart(self, start, end)

    def once(self, start, end):
        if not _factor_once_execute(self, ROCFactor, self._once_range, start, end):
            Indicator.once_via_next(self, start, end)

    @classmethod
    def build(cls, ctx, period=20, **params):
        return ctx.roc(ctx.close, period)


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
        self.lines.rsv[0] = _kdj_rsv(high, low, close)

    def _once_range(self, start, end):
        high_line = self._highest.lines[0]
        low_line = self._lowest.lines[0]
        close_line = self.data.close
        output = self.lines.rsv
        for index in range(start, end):
            high = float(_factor_once_read(high_line, index))
            low = float(_factor_once_read(low_line, index))
            close = float(_factor_once_read(close_line, index))
            _factor_once_write(output, index, _kdj_rsv(high, low, close))

    def preonce(self, start, end):
        if not _factor_once_execute(self, _SafeRSV, self._once_range, start, end, phase="once"):
            Indicator.preonce_via_prenext(self, start, end)

    def oncestart(self, start, end):
        if not _factor_once_execute(self, _SafeRSV, self._once_range, start, end):
            Indicator.oncestart_via_nextstart(self, start, end)

    def once(self, start, end):
        if not _factor_once_execute(self, _SafeRSV, self._once_range, start, end):
            Indicator.once_via_next(self, start, end)


class KDJFactor(FactorIndicator):
    """Expose this example's selected J value through the ``factor`` panel line.

    RSV and the smoothed K/D series remain native child indicators. The single
    output line is a convention chosen by this example's panel configuration,
    not a restriction on FactorIndicator outputs.
    """

    lines = ("factor",)
    params = (("period", 9), ("period_dfast", 3), ("period_dslow", 3))
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
            j = _kdj_j(k, d)
            self.outputs[data].factor[0] = j

    def _once_range(self, start, end):
        required_bars = self.p.period + self.p.period_dfast + self.p.period_dslow - 2
        for index in range(start, end):
            bars = index + 1
            for data in self.datas:
                k = d = math.nan
                if bars >= required_bars:
                    k = float(_factor_once_read(self._k[data].lines[0], index))
                    d = float(_factor_once_read(self._d[data].lines[0], index))
                _factor_once_write(self.outputs[data].factor, index, _kdj_j(k, d))

    def preonce(self, start, end):
        if not _factor_once_execute(self, KDJFactor, self._once_range, start, end, phase="once"):
            Indicator.preonce_via_prenext(self, start, end)

    def oncestart(self, start, end):
        if not _factor_once_execute(self, KDJFactor, self._once_range, start, end):
            Indicator.oncestart_via_nextstart(self, start, end)

    def once(self, start, end):
        if not _factor_once_execute(self, KDJFactor, self._once_range, start, end):
            Indicator.once_via_next(self, start, end)

    @classmethod
    def build(cls, ctx, period=9, period_dfast=3, period_dslow=3, **params):
        highest = ctx.highest(ctx.high, period)
        lowest = ctx.lowest(ctx.low, period)
        rsv = ctx.apply(_kdj_rsv, highest, lowest, ctx.close)
        k = ctx.sma(rsv, period_dfast)
        d = ctx.sma(k, period_dslow)
        return ctx.apply(_kdj_j, k, d)


for _factor_once_class in (CloseMAFactor, ROCFactor, _SafeRSV, KDJFactor):
    _factor_once_class._factor_once_expected_callbacks = tuple(
        (name, getattr(_factor_once_class, name))
        for name in ("next", "prenext", "nextstart", "preonce", "oncestart", "once")
    )
