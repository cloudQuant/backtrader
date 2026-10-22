"""Native Alpha101 factor implementation for Alpha098."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    DecayLinear,
    RollingCorrelation,
    RollingSum,
    Subtract,
    TsArgMin,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha098Native(FactorIndicator):
    """Alpha #98: subtract a nested open/ADV argmin branch from a VWAP branch."""

    lines = ("factor",)
    alpha_id = 98
    case_id = "AF46-098"
    lookback_h = 52
    formula = "(rank(decay_linear(correlation(vwap, sum(adv5, 26.4719), 4.58418), 7.18088)) - rank(decay_linear(Ts_Rank(Ts_ArgMin(correlation(rank(open), rank(adv15), 20.8187), 8.62571), 6.95668), 8.07206)))"
    formula_fields = ("vwap", "open", "dollar_volume", "adv5", "adv15")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        adv5_sum = per_asset(
            self, "adv5_sum26", RollingSum, self.field_lines("adv5"), period=26.4719
        )
        vwap_adv5_correlation = per_asset(
            self,
            "vwap_adv5_sum_correlation",
            RollingCorrelation,
            self.field_lines("vwap"),
            adv5_sum,
            period=4.58418,
        )
        vwap_adv5_decay = per_asset(
            self, "vwap_adv5_correlation_decay", DecayLinear, vwap_adv5_correlation, period=7.18088
        )
        first_branch = panel(self, "rank_vwap_adv5_decay", CrossSectionalRank, vwap_adv5_decay)
        open_rank = panel(self, "rank_open", CrossSectionalRank, self.field_lines("open"))
        adv15_rank = panel(self, "rank_adv15", CrossSectionalRank, self.field_lines("adv15"))
        ranked_series_correlation = per_asset(
            self,
            "ranked_open_adv15_correlation",
            RollingCorrelation,
            open_rank,
            adv15_rank,
            period=20.8187,
        )
        argmin = per_asset(
            self, "correlation_argmin8", TsArgMin, ranked_series_correlation, period=8.62571
        )
        argmin_time_rank = per_asset(self, "argmin_time_rank6", TsRank, argmin, period=6.95668)
        argmin_decay = per_asset(
            self, "argmin_time_rank_decay8", DecayLinear, argmin_time_rank, period=8.07206
        )
        second_branch = panel(self, "rank_argmin_decay", CrossSectionalRank, argmin_decay)
        self._result_lines = per_asset(
            self, "branch_difference", Subtract, first_branch, second_branch
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha098Build(FactorIndicator):
    """AF48-098: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha098Native.alpha_id
    case_id = Alpha098Native.case_id
    lookback_h = Alpha098Native.lookback_h
    formula_fields = Alpha098Native.formula_fields
    required_fields = Alpha098Native.required_fields
    formula = Alpha098Native.formula
    operator_profile = Alpha098Native.operator_profile
    input_policy = Alpha098Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        adv5_sum = ctx.sum(ctx.field("adv5"), 26.4719)
        vwap_adv5_correlation = ctx.correlation(ctx.field("vwap"), adv5_sum, 4.58418)
        vwap_adv5_decay = ctx.decay_linear(vwap_adv5_correlation, 7.18088)
        first_branch = ctx.rank(vwap_adv5_decay)
        open_rank = ctx.rank(ctx.field("open"))
        adv15_rank = ctx.rank(ctx.field("adv15"))
        ranked_series_correlation = ctx.correlation(open_rank, adv15_rank, 20.8187)
        argmin = ctx.ts_argmin(ranked_series_correlation, 8.62571)
        argmin_time_rank = ctx.ts_rank(argmin, 6.95668)
        argmin_decay = ctx.decay_linear(argmin_time_rank, 8.07206)
        second_branch = ctx.rank(argmin_decay)
        factor = first_branch - second_branch
        return factor
