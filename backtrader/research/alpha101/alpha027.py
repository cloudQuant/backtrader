"""Native Alpha101 factor implementation for Alpha027."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Divide,
    LessThan,
    RollingCorrelation,
    RollingSum,
    Where,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha027Native(FactorIndicator):
    """AF46-027: rank of a two-grid sum of cross-rank correlation."""

    lines = ("factor",)
    alpha_id = 27
    case_id = "AF46-027"
    formula = (
        "((0.5 < rank((sum(correlation(rank(volume), rank(vwap), 6), 2) / 2.0))) ? " "(-1 * 1) : 1)"
    )
    lookback_h = 6
    formula_fields = ("volume", "vwap")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        volume_rank = panel(self, "rank_volume", CrossSectionalRank, self.field_lines("volume"))
        vwap_rank = panel(self, "rank_vwap", CrossSectionalRank, self.field_lines("vwap"))
        correlation = per_asset(
            self, "rank_correlation_6", RollingCorrelation, volume_rank, vwap_rank, period=6
        )
        correlation_sum = per_asset(self, "sum_correlation_2", RollingSum, correlation, period=2)
        mean_correlation = per_asset(
            self, "mean_correlation_2", Divide, correlation_sum, (2.0,) * count
        )
        ranked_sum = panel(self, "rank_mean_correlation", CrossSectionalRank, mean_correlation)
        condition = per_asset(self, "threshold", LessThan, (0.5,) * count, ranked_sum)
        self._result_lines = per_asset(
            self, "factor", Where, condition, (-1.0,) * count, (1.0,) * count
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha027Build(FactorIndicator):
    """AF48-027: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha027Native.alpha_id
    case_id = Alpha027Native.case_id
    lookback_h = Alpha027Native.lookback_h
    formula_fields = Alpha027Native.formula_fields
    required_fields = Alpha027Native.required_fields
    formula = Alpha027Native.formula
    operator_profile = Alpha027Native.operator_profile
    input_policy = Alpha027Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        volume_rank = ctx.rank(ctx.field("volume"))
        vwap_rank = ctx.rank(ctx.field("vwap"))
        correlation = ctx.correlation(volume_rank, vwap_rank, 6)
        correlation_sum = ctx.sum(correlation, 2)
        mean_correlation = correlation_sum / 2.0
        ranked_sum = ctx.rank(mean_correlation)
        condition = ctx.less_than(0.5, ranked_sum)
        factor = ctx.where(condition, -1.0, 1.0)
        return factor
