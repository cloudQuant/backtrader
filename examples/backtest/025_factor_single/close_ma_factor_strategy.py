"""Native single-factor declaration for the Iteration 45 research example."""

import math

from backtrader.indicators import SMA
from backtrader.research import FactorIndicator


class CloseMAFactor(FactorIndicator):
    """Close divided by its complete simple moving average."""

    lines = ("factor",)
    params = (("period", 20),)
    panel_mode = "next"
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
            if (
                len(data) >= self.p.period
                and math.isfinite(close)
                and math.isfinite(average)
                and average != 0.0
            ):
                value = close / average
            self.outputs[data].factor[0] = value
