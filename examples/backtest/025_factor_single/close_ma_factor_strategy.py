"""Single-factor declaration for the Iteration 45 research example."""

import math

from backtrader import Indicator
from backtrader.indicators import SMA
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


class CloseMAFactor(FactorIndicator):
    """Close divided by its complete simple moving average."""

    lines = ("factor",)
    params = (("period", 20),)
    formula_fields = ("close",)

    @classmethod
    def lookback_h(cls, period=20):
        """Return the span from the first to last bar in the SMA window."""
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


CloseMAFactor._factor_once_expected_callbacks = tuple(
    (name, getattr(CloseMAFactor, name))
    for name in ("next", "prenext", "nextstart", "preonce", "oncestart", "once")
)
