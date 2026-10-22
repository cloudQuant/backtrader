"""Native Alpha101 factor implementation for Alpha023."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Delta,
    Divide,
    LessThan,
    Multiply,
    RollingSum,
    Where,
)
from ._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha023Native(FactorIndicator):
    """AF46-023: conditional negative two-grid high change."""

    lines = ("factor",)
    alpha_id = 23
    case_id = "AF46-023"
    formula = "(((sum(high, 20) / 20) < high) ? (-1 * delta(high, 2)) : 0)"
    lookback_h = 19
    formula_fields = ("high",)
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        high = self.field_lines("high")
        high_sum = per_asset(self, "sum_high_20", RollingSum, high, period=20)
        high_mean = per_asset(self, "mean_high_20", Divide, high_sum, (20.0,) * count)
        condition = per_asset(self, "high_above_mean_20", LessThan, high_mean, high)
        high_change = per_asset(self, "high_delta_2", Delta, high, period=2)
        negative_change = per_asset(
            self, "negative_high_delta_2", Multiply, (-1.0,) * count, high_change
        )
        self._result_lines = per_asset(
            self, "factor", Where, condition, negative_change, (0.0,) * count
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
