"""Native Alpha101 factor implementation for Alpha048."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Delay,
    Delta,
    Divide,
    IndNeutralize,
    Multiply,
    Power,
    RollingCorrelation,
    RollingSum,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha048Native(FactorIndicator):
    """AF46-048: subindustry-neutralized long correlation divided by return power."""

    lines = ("factor",)
    alpha_id = 48
    case_id = "AF46-048"
    lookback_h = 251
    formula_fields = ("close", "subindustry")
    required_fields = formula_fields
    formula = "(indneutralize(((correlation(delta(close, 1), delta(delay(close, 1), 1), 250) * delta(close, 1)) / close), IndClass.subindustry) / sum(((delta(close, 1) / delay(close, 1))^2), 250))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        close = self.field_lines("close")
        delta_now = per_asset(self, "delta_close1", Delta, close, period=1)
        close_delay = per_asset(self, "delay_close1", Delay, close, period=1)
        delta_delay = per_asset(self, "delta_delay_close1", Delta, close_delay, period=1)
        correlation = per_asset(
            self, "correlation250", RollingCorrelation, delta_now, delta_delay, period=250
        )
        corr_times_delta = per_asset(self, "corr_times_delta", Multiply, correlation, delta_now)
        normalized = per_asset(self, "price_normalized", Divide, corr_times_delta, close)
        neutralized = panel(
            self,
            "neutralized_numerator",
            IndNeutralize,
            normalized,
            level="subindustry",
            groups=self.field_lines("subindustry"),
        )
        return_ratio = per_asset(self, "return_ratio", Divide, delta_now, close_delay)
        square = per_asset(
            self, "return_ratio_squared", Power, return_ratio, (2.0,) * len(self.datas)
        )
        square_sum = per_asset(self, "square_sum250", RollingSum, square, period=250)
        self._result_lines = per_asset(self, "divide_denominator", Divide, neutralized, square_sum)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        close = ctx.close
        delta_now = ctx.delta(close, 1)
        close_delay = ctx.delay(close, 1)
        delta_delay = ctx.delta(close_delay, 1)
        correlation = ctx.correlation(delta_now, delta_delay, 250)
        corr_times_delta = correlation * delta_now
        normalized = corr_times_delta / close
        neutralized = ctx.indneutralize(
            normalized,
            ctx.subindustry,
            level="subindustry",
        )
        return_ratio = delta_now / close_delay
        square = return_ratio**2.0
        square_sum = ctx.sum(square, 250)
        return neutralized / square_sum
