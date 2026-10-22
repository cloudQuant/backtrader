"""Native Alpha101 factor implementation for Alpha085."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Divide,
    Multiply,
    Power,
    RollingCorrelation,
    Subtract,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha085Native(FactorIndicator):
    """Alpha #85: ordinary power of two ranked rolling correlations."""

    lines = ("factor",)
    alpha_id = 85
    case_id = "AF46-085"
    lookback_h = 37
    formula = "(rank(correlation(((high * 0.876703) + (close * (1 - 0.876703))), adv30, 9.61331))^rank(correlation(Ts_Rank(((high + low) / 2), 3.70596), Ts_Rank(volume, 10.1595), 7.11408)))"
    formula_fields = ("high", "close", "low", "volume", "dollar_volume", "adv30")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        one_minus_alpha = per_asset(
            self, "one_minus_high_weight", Subtract, (1.0,) * count, (0.876703,) * count
        )
        high_part = per_asset(
            self, "high_part", Multiply, self.field_lines("high"), (0.876703,) * count
        )
        close_part = per_asset(
            self, "close_part", Multiply, self.field_lines("close"), one_minus_alpha
        )
        weighted_price = per_asset(self, "weighted_price", Add, high_part, close_part)
        first_correlation = per_asset(
            self,
            "weighted_price_adv30_correlation",
            RollingCorrelation,
            weighted_price,
            self.field_lines("adv30"),
            period=9.61331,
        )
        ranked_first_correlation = panel(
            self, "rank_weighted_price_adv30_correlation", CrossSectionalRank, first_correlation
        )
        midpoint = per_asset(
            self,
            "high_low_midpoint",
            Divide,
            per_asset(
                self, "high_plus_low", Add, self.field_lines("high"), self.field_lines("low")
            ),
            (2.0,) * count,
        )
        midpoint_time_rank = per_asset(self, "midpoint_time_rank", TsRank, midpoint, period=3.70596)
        volume_time_rank = per_asset(
            self, "volume_time_rank", TsRank, self.field_lines("volume"), period=10.1595
        )
        second_correlation = per_asset(
            self,
            "ranked_series_correlation",
            RollingCorrelation,
            midpoint_time_rank,
            volume_time_rank,
            period=7.11408,
        )
        ranked_second_correlation = panel(
            self, "rank_ranked_series_correlation", CrossSectionalRank, second_correlation
        )
        self._result_lines = per_asset(
            self, "ordinary_power", Power, ranked_first_correlation, ranked_second_correlation
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha085Build(FactorIndicator):
    """AF48-085: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha085Native.alpha_id
    case_id = Alpha085Native.case_id
    lookback_h = Alpha085Native.lookback_h
    formula_fields = Alpha085Native.formula_fields
    required_fields = Alpha085Native.required_fields
    formula = Alpha085Native.formula
    operator_profile = Alpha085Native.operator_profile
    input_policy = Alpha085Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        one_minus_alpha = ctx.subtract(1.0, 0.876703)
        high_part = ctx.field("high") * (0.876703)
        close_part = ctx.field("close") * one_minus_alpha
        weighted_price = high_part + close_part
        first_correlation = ctx.correlation(weighted_price, ctx.field("adv30"), 9.61331)
        ranked_first_correlation = ctx.rank(first_correlation)
        midpoint = (ctx.field("high") + ctx.field("low")) / (2.0)
        midpoint_time_rank = ctx.ts_rank(midpoint, 3.70596)
        volume_time_rank = ctx.ts_rank(ctx.field("volume"), 10.1595)
        second_correlation = ctx.correlation(midpoint_time_rank, volume_time_rank, 7.11408)
        ranked_second_correlation = ctx.rank(second_correlation)
        factor = ranked_first_correlation**ranked_second_correlation
        return factor
