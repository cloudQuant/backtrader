"""Native Alpha101 factor implementation for Alpha072."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
    Divide,
    RollingCorrelation,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha072Native(FactorIndicator):
    """Native implementation of Alpha072."""

    lines = ("factor",)
    alpha_id = 72
    case_id = "AF46-072"
    lookback_h = 55
    formula_fields = ("high", "low", "vwap", "volume", "dollar_volume", "adv40")
    required_fields = formula_fields
    formula = "(rank(decay_linear(correlation(((high + low) / 2), adv40, 8.93345), 10.1519)) / rank(decay_linear(correlation(Ts_Rank(vwap, 3.72469), Ts_Rank(volume, 18.5188), 6.86671), 2.95011)))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        midpoint = per_asset(
            self,
            "high_low_midpoint",
            Divide,
            per_asset(self, "high_low_sum", Add, self.field_lines("high"), self.field_lines("low")),
            (2.0,) * len(self.datas),
        )
        left_correlation = per_asset(
            self,
            "midpoint_adv40_corr8",
            RollingCorrelation,
            midpoint,
            self.field_lines("adv40"),
            period=8.93345,
        )
        left_decay = per_asset(self, "left_decay10", DecayLinear, left_correlation, period=10.1519)
        numerator = panel(self, "left_rank", CrossSectionalRank, left_decay)
        vwap_rank = per_asset(
            self, "vwap_ts_rank3", TsRank, self.field_lines("vwap"), period=3.72469
        )
        volume_rank = per_asset(
            self, "volume_ts_rank18", TsRank, self.field_lines("volume"), period=18.5188
        )
        right_correlation = per_asset(
            self, "ts_rank_correlation6", RollingCorrelation, vwap_rank, volume_rank, period=6.86671
        )
        right_decay = per_asset(
            self, "right_decay2", DecayLinear, right_correlation, period=2.95011
        )
        denominator = panel(self, "right_rank", CrossSectionalRank, right_decay)
        self._result_lines = per_asset(self, "rank_ratio", Divide, numerator, denominator)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha072Build(FactorIndicator):
    """AF48-072: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha072Native.alpha_id
    case_id = Alpha072Native.case_id
    lookback_h = Alpha072Native.lookback_h
    formula_fields = Alpha072Native.formula_fields
    required_fields = Alpha072Native.required_fields
    formula = Alpha072Native.formula
    operator_profile = Alpha072Native.operator_profile
    input_policy = Alpha072Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        midpoint = (ctx.field("high") + ctx.field("low")) / 2.0
        left_correlation = ctx.correlation(midpoint, ctx.field("adv40"), 8.93345)
        left_decay = ctx.decay_linear(left_correlation, 10.1519)
        numerator = ctx.rank(left_decay)
        vwap_rank = ctx.ts_rank(ctx.field("vwap"), 3.72469)
        volume_rank = ctx.ts_rank(ctx.field("volume"), 18.5188)
        right_correlation = ctx.correlation(vwap_rank, volume_rank, 6.86671)
        right_decay = ctx.decay_linear(right_correlation, 2.95011)
        denominator = ctx.rank(right_decay)
        factor = numerator / denominator
        return factor
