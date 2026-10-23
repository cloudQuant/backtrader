"""Native Alpha101 factor implementation for Alpha101."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    Divide,
    Subtract,
)
from .._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha101Native(FactorIndicator):
    """AF46-101: intraday move over range plus the frozen 0.001 offset."""

    lines = ("factor",)
    alpha_id = 101
    case_id = "AF46-101"
    lookback_h = 0
    formula_fields = ("open", "high", "low", "close")
    required_fields = formula_fields
    formula = "((close - open) / ((high - low) + .001))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        intraday_move = per_asset(
            self, "close_minus_open", Subtract, self.field_lines("close"), self.field_lines("open")
        )
        range_width = per_asset(
            self, "high_minus_low", Subtract, self.field_lines("high"), self.field_lines("low")
        )
        denominator = per_asset(
            self, "range_plus_offset", Add, range_width, (0.001,) * len(self.datas)
        )
        self._result_lines = per_asset(self, "factor", Divide, intraday_move, denominator)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        intraday_move = ctx.field("close") - ctx.field("open")
        range_width = ctx.field("high") - ctx.field("low")
        denominator = range_width + (0.001)
        factor = intraday_move / denominator
        return factor
