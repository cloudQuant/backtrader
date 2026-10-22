"""Native Alpha101 factor implementation for Alpha016."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Multiply,
    RollingCovariance,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha016Native(FactorIndicator):
    """Alpha #16: negative cross-rank of five-grid rank covariance."""

    lines = ("factor",)
    alpha_id = 16
    case_id = "AF46-016"
    lookback_h = 4
    formula = "(-1 * rank(covariance(rank(high), rank(volume), 5)))"
    formula_fields = ("high", "volume")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        high_rank = panel(self, "rank_high", CrossSectionalRank, self.field_lines("high"))
        volume_rank = panel(self, "rank_volume", CrossSectionalRank, self.field_lines("volume"))
        covariance = per_asset(
            self, "rank_covariance5", RollingCovariance, high_rank, volume_rank, period=5
        )
        ranked_covariance = panel(self, "rank_covariance", CrossSectionalRank, covariance)
        self._result_lines = per_asset(
            self, "negative_ranked_covariance", Multiply, ranked_covariance, (-1.0,) * count
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha016Build(FactorIndicator):
    """AF48-016: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha016Native.alpha_id
    case_id = Alpha016Native.case_id
    lookback_h = Alpha016Native.lookback_h
    formula_fields = Alpha016Native.formula_fields
    required_fields = Alpha016Native.required_fields
    formula = Alpha016Native.formula
    operator_profile = Alpha016Native.operator_profile
    input_policy = Alpha016Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        high_rank = ctx.rank(ctx.field("high"))
        volume_rank = ctx.rank(ctx.field("volume"))
        covariance = ctx.covariance(high_rank, volume_rank, 5)
        ranked_covariance = ctx.rank(covariance)
        factor = ranked_covariance * -1.0
        return factor
