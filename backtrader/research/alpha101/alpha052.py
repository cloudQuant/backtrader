"""Native Alpha101 factor implementation for Alpha052."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Delay,
    Divide,
    Multiply,
    RollingSum,
    Subtract,
    TsMin,
    TsRank,
)
from .._helpers import panel, per_asset, simple_returns
from ._metadata import native_alpha


@native_alpha
class Alpha052Native(FactorIndicator):
    """Alpha#52: delayed low minimum, long return-sum rank and volume rank."""

    lines = ("factor",)
    alpha_id = 52
    case_id = "AF46-052"
    lookback_h = 240
    formula = "((((-1 * ts_min(low, 5)) + delay(ts_min(low, 5), 5)) * rank(((sum(returns, 240) - sum(returns, 20)) / 220))) * ts_rank(volume, 5))"
    formula_fields = ("low", "volume", "close")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        low_minimum = per_asset(self, "low_minimum5", TsMin, self.field_lines("low"), period=5)
        delayed_low_minimum = per_asset(self, "low_minimum5_delay5", Delay, low_minimum, period=5)
        low_change = per_asset(
            self,
            "delayed_minimum_minus_minimum",
            Add,
            per_asset(
                self, "negative_low_minimum", Multiply, low_minimum, (-1.0,) * len(self.datas)
            ),
            delayed_low_minimum,
        )
        returns = simple_returns(self, "close_returns")
        return_sum240 = per_asset(self, "returns_sum240", RollingSum, returns, period=240)
        return_sum20 = per_asset(self, "returns_sum20", RollingSum, returns, period=20)
        return_sum_delta = per_asset(
            self, "returns_sum_delta", Subtract, return_sum240, return_sum20
        )
        return_sum_ratio = per_asset(
            self, "returns_sum_ratio", Divide, return_sum_delta, (220.0,) * len(self.datas)
        )
        return_rank = panel(self, "rank_returns_sum_ratio", CrossSectionalRank, return_sum_ratio)
        volume_rank = per_asset(
            self, "volume_ts_rank5", TsRank, self.field_lines("volume"), period=5
        )
        left = per_asset(self, "low_change_times_returns_rank", Multiply, low_change, return_rank)
        self._result_lines = per_asset(self, "alpha52", Multiply, left, volume_rank)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha052Build(FactorIndicator):
    """AF48-052: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha052Native.alpha_id
    case_id = Alpha052Native.case_id
    lookback_h = Alpha052Native.lookback_h
    formula_fields = Alpha052Native.formula_fields
    required_fields = Alpha052Native.required_fields
    formula = Alpha052Native.formula
    operator_profile = Alpha052Native.operator_profile
    input_policy = Alpha052Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        low_minimum = ctx.ts_min(ctx.field("low"), 5)
        delayed_low_minimum = ctx.delay(low_minimum, 5)
        negative_low_minimum = low_minimum * -1.0
        low_change = negative_low_minimum + delayed_low_minimum
        returns = ctx.returns()
        return_sum240 = ctx.sum(returns, 240)
        return_sum20 = ctx.sum(returns, 20)
        return_sum_delta = return_sum240 - return_sum20
        return_sum_ratio = return_sum_delta / 220.0
        return_rank = ctx.rank(return_sum_ratio)
        volume_rank = ctx.ts_rank(ctx.field("volume"), 5)
        left = low_change * return_rank
        factor = left * volume_rank
        return factor
