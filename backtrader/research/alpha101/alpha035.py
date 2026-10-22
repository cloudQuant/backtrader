"""Native Alpha101 factor implementation for Alpha035."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    Multiply,
    Subtract,
    TsRank,
)
from .._helpers import per_asset, simple_returns
from ._metadata import native_alpha


@native_alpha
class Alpha035Native(FactorIndicator):
    """AF46-035: product of volume, range, and return time ranks."""

    lines = ("factor",)
    alpha_id = 35
    case_id = "AF46-035"
    formula = (
        "((Ts_Rank(volume, 32) * (1 - Ts_Rank(((close + high) - low), 16))) * "
        "(1 - Ts_Rank(returns, 32)))"
    )
    lookback_h = 32
    formula_fields = ("volume", "close", "high", "low")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        volume_rank = per_asset(
            self, "volume_ts_rank_32", TsRank, self.field_lines("volume"), period=32
        )
        close_plus_high = per_asset(
            self, "close_plus_high", Add, self.field_lines("close"), self.field_lines("high")
        )
        range_input = per_asset(
            self, "close_high_minus_low", Subtract, close_plus_high, self.field_lines("low")
        )
        range_rank = per_asset(self, "range_ts_rank_16", TsRank, range_input, period=16)
        one_minus_range_rank = per_asset(
            self, "one_minus_range_rank", Subtract, (1.0,) * count, range_rank
        )
        returns = simple_returns(self, "returns")
        returns_rank = per_asset(self, "returns_ts_rank_32", TsRank, returns, period=32)
        one_minus_returns_rank = per_asset(
            self, "one_minus_returns_rank", Subtract, (1.0,) * count, returns_rank
        )
        first_product = per_asset(
            self, "volume_times_range_term", Multiply, volume_rank, one_minus_range_rank
        )
        self._result_lines = per_asset(
            self, "factor", Multiply, first_product, one_minus_returns_rank
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha035Build(FactorIndicator):
    """AF48-035: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha035Native.alpha_id
    case_id = Alpha035Native.case_id
    lookback_h = Alpha035Native.lookback_h
    formula_fields = Alpha035Native.formula_fields
    required_fields = Alpha035Native.required_fields
    formula = Alpha035Native.formula
    operator_profile = Alpha035Native.operator_profile
    input_policy = Alpha035Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        volume_rank = ctx.ts_rank(ctx.field("volume"), 32)
        close_plus_high = ctx.field("close") + ctx.field("high")
        range_input = close_plus_high - ctx.field("low")
        range_rank = ctx.ts_rank(range_input, 16)
        one_minus_range_rank = 1.0 - range_rank
        returns = ctx.returns()
        returns_rank = ctx.ts_rank(returns, 32)
        one_minus_returns_rank = 1.0 - returns_rank
        first_product = volume_rank * one_minus_range_rank
        factor = first_product * one_minus_returns_rank
        return factor
