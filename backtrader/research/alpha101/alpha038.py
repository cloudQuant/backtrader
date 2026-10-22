"""Native Alpha101 factor implementation for Alpha038."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Divide,
    Multiply,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha038Native(FactorIndicator):
    """AF46-038: product of negative close time-rank and close/open rank."""

    lines = ("factor",)
    alpha_id = 38
    case_id = "AF46-038"
    formula = "((-1 * rank(Ts_Rank(close, 10))) * rank((close / open)))"
    lookback_h = 9
    formula_fields = ("close", "open")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        close = self.field_lines("close")
        close_rank = per_asset(self, "close_ts_rank_10", TsRank, close, period=10)
        ranked_close_time_rank = panel(
            self, "rank_close_ts_rank_10", CrossSectionalRank, close_rank
        )
        negative_time_rank = per_asset(
            self,
            "negative_ranked_close_time_rank",
            Multiply,
            (-1.0,) * count,
            ranked_close_time_rank,
        )
        close_over_open = per_asset(
            self, "close_over_open", Divide, close, self.field_lines("open")
        )
        ranked_close_over_open = panel(
            self, "rank_close_over_open", CrossSectionalRank, close_over_open
        )
        self._result_lines = per_asset(
            self, "factor", Multiply, negative_time_rank, ranked_close_over_open
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha038Build(FactorIndicator):
    """AF48-038: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha038Native.alpha_id
    case_id = Alpha038Native.case_id
    lookback_h = Alpha038Native.lookback_h
    formula_fields = Alpha038Native.formula_fields
    required_fields = Alpha038Native.required_fields
    formula = Alpha038Native.formula
    operator_profile = Alpha038Native.operator_profile
    input_policy = Alpha038Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        close = ctx.field("close")
        close_rank = ctx.ts_rank(close, 10)
        ranked_close_time_rank = ctx.rank(close_rank)
        negative_time_rank = -1.0 * ranked_close_time_rank
        close_over_open = close / ctx.field("open")
        ranked_close_over_open = ctx.rank(close_over_open)
        factor = negative_time_rank * ranked_close_over_open
        return factor
