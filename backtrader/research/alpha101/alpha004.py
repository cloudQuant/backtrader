"""Native Alpha101 factor implementation for Alpha004."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Multiply,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha004Native(FactorIndicator):
    """AF46-004: daily low rank followed by within-asset nine-grid rank."""

    lines = ("factor",)
    alpha_id = 4
    case_id = "AF46-004"
    lookback_h = 8
    formula_fields = ("low",)
    required_fields = formula_fields
    formula = "(-1 * Ts_Rank(rank(low), 9))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        low_rank = panel(self, "rank_low", CrossSectionalRank, self.field_lines("low"))
        time_rank = per_asset(self, "ts_rank9", TsRank, low_rank, period=9)
        self._result_lines = per_asset(
            self, "negate", Multiply, time_rank, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha004Build(FactorIndicator):
    """AF48-004: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha004Native.alpha_id
    case_id = Alpha004Native.case_id
    lookback_h = Alpha004Native.lookback_h
    formula_fields = Alpha004Native.formula_fields
    required_fields = Alpha004Native.required_fields
    formula = Alpha004Native.formula
    operator_profile = Alpha004Native.operator_profile
    input_policy = Alpha004Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        low_rank = ctx.rank(ctx.field("low"))
        time_rank = ctx.ts_rank(low_rank, 9)
        factor = time_rank * -1.0
        return factor
