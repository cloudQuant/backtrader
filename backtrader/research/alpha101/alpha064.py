"""Native Alpha101 factor implementation for Alpha064."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Delta,
    Divide,
    LessThan,
    Multiply,
    RollingCorrelation,
    RollingSum,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha064Native(FactorIndicator):
    """Native implementation of Alpha064."""

    lines = ("factor",)
    alpha_id = 64
    case_id = "AF46-064"
    lookback_h = 145
    formula_fields = ("open", "low", "high", "vwap", "dollar_volume", "adv120")
    required_fields = formula_fields
    formula = "((rank(correlation(sum(((open * 0.178404) + (low * (1 - 0.178404))), 12.7054), sum(adv120, 12.7054), 16.6208)) < rank(delta(((((high + low) / 2) * 0.178404) + (vwap * (1 - 0.178404))), 3.69741))) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        weight = 0.178404
        open_part = per_asset(
            self, "open_weight", Multiply, self.field_lines("open"), (weight,) * len(self.datas)
        )
        low_part = per_asset(
            self, "low_weight", Multiply, self.field_lines("low"), (1.0 - weight,) * len(self.datas)
        )
        price_mix = per_asset(self, "open_low_mix", Add, open_part, low_part)
        price_sum = per_asset(self, "open_low_sum12", RollingSum, price_mix, period=12.7054)
        adv_sum = per_asset(
            self, "adv120_sum12", RollingSum, self.field_lines("adv120"), period=12.7054
        )
        correlation = per_asset(
            self, "sum_correlation16", RollingCorrelation, price_sum, adv_sum, period=16.6208
        )
        left_rank = panel(self, "sum_correlation_rank", CrossSectionalRank, correlation)
        midpoint = per_asset(
            self,
            "high_low_midpoint",
            Divide,
            per_asset(self, "high_low_sum", Add, self.field_lines("high"), self.field_lines("low")),
            (2.0,) * len(self.datas),
        )
        midpoint_part = per_asset(
            self, "midpoint_weight", Multiply, midpoint, (weight,) * len(self.datas)
        )
        vwap_part = per_asset(
            self,
            "vwap_weight",
            Multiply,
            self.field_lines("vwap"),
            (1.0 - weight,) * len(self.datas),
        )
        delta = per_asset(
            self,
            "weighted_midpoint_delta3",
            Delta,
            per_asset(self, "weighted_midpoint_vwap", Add, midpoint_part, vwap_part),
            period=3.69741,
        )
        right_rank = panel(self, "weighted_midpoint_delta_rank", CrossSectionalRank, delta)
        comparison = per_asset(self, "rank_less_than", LessThan, left_rank, right_rank)
        self._result_lines = per_asset(
            self, "negative_boolean", Multiply, comparison, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        weight = 0.178404
        open_part = ctx.field("open") * weight
        low_part = ctx.field("low") * (1.0 - weight)
        price_mix = open_part + low_part
        price_sum = ctx.sum(price_mix, 12.7054)
        adv_sum = ctx.sum(ctx.field("adv120"), 12.7054)
        correlation = ctx.correlation(price_sum, adv_sum, 16.6208)
        left_rank = ctx.rank(correlation)
        midpoint = (ctx.field("high") + ctx.field("low")) / 2.0
        midpoint_part = midpoint * weight
        vwap_part = ctx.field("vwap") * (1.0 - weight)
        delta = ctx.delta((midpoint_part + vwap_part), 3.69741)
        right_rank = ctx.rank(delta)
        comparison = ctx.less_than(left_rank, right_rank)
        factor = comparison * -1.0
        return factor
