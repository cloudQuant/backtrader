"""Native Alpha101 factor implementation for Alpha044."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Multiply,
    RollingCorrelation,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha044Native(FactorIndicator):
    """Alpha#44: negative rolling correlation of high with ranked volume."""

    lines = ("factor",)
    alpha_id = 44
    case_id = "AF46-044"
    lookback_h = 4
    formula = "(-1 * correlation(high, rank(volume), 5))"
    formula_fields = ("high", "volume")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        volume_rank = panel(self, "rank_volume", CrossSectionalRank, self.field_lines("volume"))
        correlation = per_asset(
            self,
            "high_ranked_volume_corr5",
            RollingCorrelation,
            self.field_lines("high"),
            volume_rank,
            period=5,
        )
        self._result_lines = per_asset(
            self, "negative_correlation", Multiply, correlation, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha044Build(FactorIndicator):
    """AF48-044: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha044Native.alpha_id
    case_id = Alpha044Native.case_id
    lookback_h = Alpha044Native.lookback_h
    formula_fields = Alpha044Native.formula_fields
    required_fields = Alpha044Native.required_fields
    formula = Alpha044Native.formula
    operator_profile = Alpha044Native.operator_profile
    input_policy = Alpha044Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        volume_rank = ctx.rank(ctx.field("volume"))
        correlation = ctx.correlation(ctx.field("high"), volume_rank, 5)
        factor = correlation * -1.0
        return factor
