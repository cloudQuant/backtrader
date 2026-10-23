"""Native Alpha101 factor implementation for Alpha010."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Delta,
    GreaterThan,
    LessThan,
    Multiply,
    TsMax,
    TsMin,
    Where,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha010Native(FactorIndicator):
    """Alpha #10: nested four-grid delta-extrema branch and cross-rank."""

    lines = ("factor",)
    alpha_id = 10
    case_id = "AF46-010"
    lookback_h = 4
    formula = "rank(((0 < ts_min(delta(close, 1), 4)) ? delta(close, 1) : ((ts_max(delta(close, 1), 4) < 0) ? delta(close, 1) : (-1 * delta(close, 1)))))"
    formula_fields = ("close",)
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        change = per_asset(self, "close_delta1", Delta, self.field_lines("close"), period=1)
        floor = per_asset(self, "delta_min4", TsMin, change, period=4)
        positive_floor = per_asset(self, "positive_minimum", GreaterThan, floor, (0.0,) * count)
        ceiling = per_asset(self, "delta_max4", TsMax, change, period=4)
        negative_ceiling = per_asset(self, "negative_maximum", LessThan, ceiling, (0.0,) * count)
        negative_change = per_asset(self, "negative_delta", Multiply, change, (-1.0,) * count)
        second_branch = per_asset(
            self, "second_where", Where, negative_ceiling, change, negative_change
        )
        selected = per_asset(self, "first_where", Where, positive_floor, change, second_branch)
        self._result_lines = panel(self, "rank_selected_delta", CrossSectionalRank, selected)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        change = ctx.delta(ctx.field("close"), 1)
        floor = ctx.ts_min(change, 4)
        positive_floor = floor > 0.0
        ceiling = ctx.ts_max(change, 4)
        negative_ceiling = ceiling < 0.0
        negative_change = change * -1.0
        second_branch = ctx.where(negative_ceiling, change, negative_change)
        selected = ctx.where(positive_floor, change, second_branch)
        factor = ctx.rank(selected)
        return factor
