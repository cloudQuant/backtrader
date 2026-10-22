"""Native Alpha101 factor implementation for Alpha065."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    LessThan,
    Multiply,
    RollingCorrelation,
    RollingSum,
    Subtract,
    TsMin,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha065Native(FactorIndicator):
    """Native implementation of Alpha065."""

    lines = ("factor",)
    alpha_id = 65
    case_id = "AF46-065"
    lookback_h = 71
    formula_fields = ("open", "vwap", "dollar_volume", "adv60")
    required_fields = formula_fields
    formula = "((rank(correlation(((open * 0.00817205) + (vwap * (1 - 0.00817205))), sum(adv60, 8.6911), 6.40374)) < rank((open - ts_min(open, 13.635)))) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        weight = 0.00817205
        weighted_open = per_asset(
            self, "weighted_open", Multiply, self.field_lines("open"), (weight,) * len(self.datas)
        )
        weighted_vwap = per_asset(
            self,
            "weighted_vwap",
            Multiply,
            self.field_lines("vwap"),
            (1.0 - weight,) * len(self.datas),
        )
        price_mix = per_asset(self, "weighted_price", Add, weighted_open, weighted_vwap)
        adv_sum = per_asset(
            self, "adv60_sum8", RollingSum, self.field_lines("adv60"), period=8.6911
        )
        correlation = per_asset(
            self, "sum_correlation6", RollingCorrelation, price_mix, adv_sum, period=6.40374
        )
        left_rank = panel(self, "sum_correlation_rank", CrossSectionalRank, correlation)
        open_min = per_asset(self, "open_ts_min13", TsMin, self.field_lines("open"), period=13.635)
        open_excess = per_asset(
            self, "open_minus_min", Subtract, self.field_lines("open"), open_min
        )
        right_rank = panel(self, "open_excess_rank", CrossSectionalRank, open_excess)
        comparison = per_asset(self, "rank_less_than", LessThan, left_rank, right_rank)
        self._result_lines = per_asset(
            self, "negative_boolean", Multiply, comparison, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha065Build(FactorIndicator):
    """AF48-065: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha065Native.alpha_id
    case_id = Alpha065Native.case_id
    lookback_h = Alpha065Native.lookback_h
    formula_fields = Alpha065Native.formula_fields
    required_fields = Alpha065Native.required_fields
    formula = Alpha065Native.formula
    operator_profile = Alpha065Native.operator_profile
    input_policy = Alpha065Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        weight = 0.00817205
        weighted_open = ctx.field("open") * weight
        weighted_vwap = ctx.field("vwap") * (1.0 - weight)
        price_mix = weighted_open + weighted_vwap
        adv_sum = ctx.sum(ctx.field("adv60"), 8.6911)
        correlation = ctx.correlation(price_mix, adv_sum, 6.40374)
        left_rank = ctx.rank(correlation)
        open_min = ctx.ts_min(ctx.field("open"), 13.635)
        open_excess = ctx.field("open") - open_min
        right_rank = ctx.rank(open_excess)
        comparison = ctx.less_than(left_rank, right_rank)
        factor = comparison * -1.0
        return factor
