"""Single-factor declaration for the Iteration 45 research example."""

import math

from backtrader.indicators import SMA
from backtrader.research import FactorIndicator


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

    @classmethod
    def build(cls, ctx, period=20, **params):
        return ctx.apply(_close_ratio, ctx.close, ctx.sma(ctx.close, period))
