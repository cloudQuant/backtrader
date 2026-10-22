"""Native Alpha101 factor implementation for Alpha009."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Delta,
    GreaterThan,
    LessThan,
    Multiply,
    TsMax,
    TsMin,
    Where,
)
from .._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha009Native(FactorIndicator):
    """AF46-009: nested five-grid extrema condition over one-grid change."""

    lines = ("factor",)
    alpha_id = 9
    case_id = "AF46-009"
    lookback_h = 5
    formula_fields = ("close",)
    required_fields = formula_fields
    formula = "((0 < ts_min(delta(close, 1), 5)) ? delta(close, 1) : ((ts_max(delta(close, 1), 5) < 0) ? delta(close, 1) : (-1 * delta(close, 1))))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        change = per_asset(self, "close_delta1", Delta, self.field_lines("close"), period=1)
        floor = per_asset(self, "delta_min5", TsMin, change, period=5)
        ceiling = per_asset(self, "delta_max5", TsMax, change, period=5)
        all_positive = per_asset(self, "all_positive", GreaterThan, floor, (0.0,) * len(self.datas))
        all_negative = per_asset(self, "all_negative", LessThan, ceiling, (0.0,) * len(self.datas))
        reverse = per_asset(self, "reverse_delta", Multiply, change, (-1.0,) * len(self.datas))
        negative_or_mixed = per_asset(
            self, "negative_or_mixed", Where, all_negative, change, reverse
        )
        self._result_lines = per_asset(
            self, "condition", Where, all_positive, change, negative_or_mixed
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
