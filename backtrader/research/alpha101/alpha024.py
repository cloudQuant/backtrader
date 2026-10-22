"""Native Alpha101 factor implementation for Alpha024."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Delay,
    Delta,
    Divide,
    EqualTo,
    LessThan,
    LogicalOr,
    Multiply,
    RollingSum,
    Subtract,
    TsMin,
    Where,
)
from .._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha024Native(FactorIndicator):
    """AF46-024: exact threshold OR and two conditional close branches."""

    lines = ("factor",)
    alpha_id = 24
    case_id = "AF46-024"
    formula = (
        "((((delta((sum(close, 100) / 100), 100) / delay(close, 100)) < 0.05) || "
        "((delta((sum(close, 100) / 100), 100) / delay(close, 100)) == 0.05)) ? "
        "(-1 * (close - ts_min(close, 100))) : (-1 * delta(close, 3)))"
    )
    lookback_h = 199
    formula_fields = ("close",)
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        close = self.field_lines("close")
        close_sum = per_asset(self, "sum_close_100", RollingSum, close, period=100)
        close_mean = per_asset(self, "mean_close_100", Divide, close_sum, (100.0,) * count)
        mean_change = per_asset(self, "mean_close_delta_100", Delta, close_mean, period=100)
        close_delay = per_asset(self, "delay_close_100", Delay, close, period=100)
        ratio = per_asset(self, "mean_change_over_close_delay", Divide, mean_change, close_delay)
        below_threshold = per_asset(self, "threshold_below", LessThan, ratio, (0.05,) * count)
        at_threshold = per_asset(self, "threshold_equal", EqualTo, ratio, (0.05,) * count)
        condition = per_asset(self, "threshold_condition", LogicalOr, below_threshold, at_threshold)
        close_minimum = per_asset(self, "close_min_100", TsMin, close, period=100)
        distance_from_minimum = per_asset(
            self, "close_minus_min_100", Subtract, close, close_minimum
        )
        true_branch = per_asset(
            self, "negative_close_distance", Multiply, (-1.0,) * count, distance_from_minimum
        )
        close_change = per_asset(self, "close_delta_3", Delta, close, period=3)
        false_branch = per_asset(
            self, "negative_close_delta_3", Multiply, (-1.0,) * count, close_change
        )
        self._result_lines = per_asset(self, "factor", Where, condition, true_branch, false_branch)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
