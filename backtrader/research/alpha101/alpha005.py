"""Native Alpha101 factor implementation for Alpha005."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Abs,
    CrossSectionalRank,
    Divide,
    Multiply,
    RollingSum,
    Subtract,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha005Native(FactorIndicator):
    """Alpha #5: ranked open versus the ten-grid VWAP average."""

    lines = ("factor",)
    alpha_id = 5
    case_id = "AF46-005"
    lookback_h = 9
    formula = "(rank((open - (sum(vwap, 10) / 10))) * (-1 * abs(rank((close - vwap)))))"
    formula_fields = ("open", "vwap", "close")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        open_minus_average = per_asset(
            self,
            "open_minus_vwap_average",
            Subtract,
            self.field_lines("open"),
            per_asset(
                self,
                "vwap_average10",
                Divide,
                per_asset(self, "vwap_sum10", RollingSum, self.field_lines("vwap"), period=10),
                (10.0,) * count,
            ),
        )
        ranked_open_gap = panel(self, "rank_open_gap", CrossSectionalRank, open_minus_average)
        close_minus_vwap = per_asset(
            self, "close_minus_vwap", Subtract, self.field_lines("close"), self.field_lines("vwap")
        )
        ranked_close_gap = panel(self, "rank_close_gap", CrossSectionalRank, close_minus_vwap)
        absolute_rank = per_asset(self, "absolute_rank_close_gap", Abs, ranked_close_gap)
        negative_absolute_rank = per_asset(
            self, "negative_absolute_rank_close_gap", Multiply, absolute_rank, (-1.0,) * count
        )
        self._result_lines = per_asset(
            self, "factor", Multiply, ranked_open_gap, negative_absolute_rank
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        open_minus_average = ctx.field("open") - (ctx.sum(ctx.field("vwap"), 10) / 10.0)
        ranked_open_gap = ctx.rank(open_minus_average)
        close_minus_vwap = ctx.field("close") - ctx.field("vwap")
        ranked_close_gap = ctx.rank(close_minus_vwap)
        absolute_rank = ctx.abs(ranked_close_gap)
        negative_absolute_rank = absolute_rank * -1.0
        factor = ranked_open_gap * negative_absolute_rank
        return factor
