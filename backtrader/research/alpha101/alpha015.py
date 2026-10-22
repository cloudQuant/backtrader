"""Native Alpha101 factor implementation for Alpha015."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Multiply,
    RollingCorrelation,
    RollingSum,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha015Native(FactorIndicator):
    """Alpha #15: negative rolling sum of cross-ranked rolling correlation."""

    lines = ("factor",)
    alpha_id = 15
    case_id = "AF46-015"
    lookback_h = 4
    formula = "(-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))"
    formula_fields = ("high", "volume")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        high_rank = panel(self, "rank_high", CrossSectionalRank, self.field_lines("high"))
        volume_rank = panel(self, "rank_volume", CrossSectionalRank, self.field_lines("volume"))
        correlation = per_asset(
            self, "rank_correlation3", RollingCorrelation, high_rank, volume_rank, period=3
        )
        ranked_correlation = panel(self, "rank_correlation", CrossSectionalRank, correlation)
        total = per_asset(self, "sum_ranked_correlation3", RollingSum, ranked_correlation, period=3)
        self._result_lines = per_asset(self, "negative_sum", Multiply, total, (-1.0,) * count)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha015Build(FactorIndicator):
    """AF48-015: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha015Native.alpha_id
    case_id = Alpha015Native.case_id
    lookback_h = Alpha015Native.lookback_h
    formula_fields = Alpha015Native.formula_fields
    required_fields = Alpha015Native.required_fields
    formula = Alpha015Native.formula
    operator_profile = Alpha015Native.operator_profile
    input_policy = Alpha015Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        high_rank = ctx.rank(ctx.field("high"))
        volume_rank = ctx.rank(ctx.field("volume"))
        correlation = ctx.correlation(high_rank, volume_rank, 3)
        ranked_correlation = ctx.rank(correlation)
        total = ctx.sum(ranked_correlation, 3)
        factor = total * -1.0
        return factor
