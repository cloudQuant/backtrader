"""Native Alpha101 factor implementation for Alpha021."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    Divide,
    EqualTo,
    LessThan,
    LogicalOr,
    RollingStd,
    RollingSum,
    Subtract,
    Where,
)
from .._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha021Native(FactorIndicator):
    """AF46-021: three nested conditions over short/long close summaries and ADV."""

    lines = ("factor",)
    alpha_id = 21
    case_id = "AF46-021"
    formula = (
        "((((sum(close, 8) / 8) + stddev(close, 8)) < (sum(close, 2) / 2)) ? "
        "(-1 * 1) : (((sum(close, 2) / 2) < ((sum(close, 8) / 8) - stddev(close, 8))) ? "
        "1 : (((1 < (volume / adv20)) || ((volume / adv20) == 1)) ? 1 : (-1 * 1))))"
    )
    lookback_h = 19
    formula_fields = ("close", "volume", "dollar_volume", "adv20")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        close = self.field_lines("close")
        volume = self.field_lines("volume")
        adv20 = self.field_lines("adv20")
        ones = (1.0,) * count
        negative_ones = (-1.0,) * count
        sum_close_8 = per_asset(self, "sum_close_8", RollingSum, close, period=8)
        mean_close_8 = per_asset(self, "mean_close_8", Divide, sum_close_8, (8.0,) * count)
        std_close_8 = per_asset(self, "std_close_8", RollingStd, close, period=8)
        first_condition_left = per_asset(
            self, "first_condition_left", Add, mean_close_8, std_close_8
        )
        sum_close_2 = per_asset(self, "sum_close_2", RollingSum, close, period=2)
        mean_close_2 = per_asset(self, "mean_close_2", Divide, sum_close_2, (2.0,) * count)
        first_condition = per_asset(
            self, "first_condition", LessThan, first_condition_left, mean_close_2
        )
        second_condition_right = per_asset(
            self, "second_condition_right", Subtract, mean_close_8, std_close_8
        )
        second_condition = per_asset(
            self, "second_condition", LessThan, mean_close_2, second_condition_right
        )
        volume_over_adv = per_asset(self, "volume_over_adv20", Divide, volume, adv20)
        volume_gate_below = per_asset(self, "volume_gate_below", LessThan, ones, volume_over_adv)
        volume_gate_equal = per_asset(self, "volume_gate_equal", EqualTo, volume_over_adv, ones)
        volume_gate = per_asset(
            self, "volume_gate", LogicalOr, volume_gate_below, volume_gate_equal
        )
        final_branch = per_asset(self, "final_branch", Where, volume_gate, ones, negative_ones)
        second_branch = per_asset(
            self, "second_branch", Where, second_condition, ones, final_branch
        )
        self._result_lines = per_asset(
            self, "factor", Where, first_condition, negative_ones, second_branch
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        close = ctx.field("close")
        volume = ctx.field("volume")
        adv20 = ctx.field("adv20")
        ones = 1.0
        negative_ones = -1.0
        sum_close_8 = ctx.sum(close, 8)
        mean_close_8 = sum_close_8 / 8.0
        std_close_8 = ctx.stddev(close, 8)
        first_condition_left = mean_close_8 + std_close_8
        sum_close_2 = ctx.sum(close, 2)
        mean_close_2 = sum_close_2 / 2.0
        first_condition = first_condition_left < mean_close_2
        second_condition_right = mean_close_8 - std_close_8
        second_condition = mean_close_2 < second_condition_right
        volume_over_adv = volume / adv20
        volume_gate_below = ctx.less_than(ones, volume_over_adv)
        volume_gate_equal = volume_over_adv == ones
        volume_gate = ctx.logical_or(volume_gate_below, volume_gate_equal)
        final_branch = ctx.where(volume_gate, ones, negative_ones)
        second_branch = ctx.where(second_condition, ones, final_branch)
        factor = ctx.where(first_condition, negative_ones, second_branch)
        return factor
