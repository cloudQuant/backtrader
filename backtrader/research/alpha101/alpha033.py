"""Native Alpha101 factor implementation for Alpha033."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Divide,
    Multiply,
    Power,
    Subtract,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha033Native(FactorIndicator):
    """AF46-033: cross-sectional rank of the ordinary-power open/close term."""

    lines = ("factor",)
    alpha_id = 33
    case_id = "AF46-033"
    formula = "rank((-1 * ((1 - (open / close))^1)))"
    lookback_h = 0
    formula_fields = ("open", "close")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        open_close = per_asset(
            self, "open_over_close", Divide, self.field_lines("open"), self.field_lines("close")
        )
        one_minus_ratio = per_asset(
            self, "one_minus_open_over_close", Subtract, (1.0,) * count, open_close
        )
        powered = per_asset(self, "ordinary_power_one", Power, one_minus_ratio, (1.0,) * count)
        negative = per_asset(self, "negative_power", Multiply, (-1.0,) * count, powered)
        self._result_lines = panel(self, "factor", CrossSectionalRank, negative)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        open_close = ctx.field("open") / ctx.field("close")
        one_minus_ratio = 1.0 - open_close
        powered = one_minus_ratio**1.0
        negative = -1.0 * powered
        factor = ctx.rank(negative)
        return factor
