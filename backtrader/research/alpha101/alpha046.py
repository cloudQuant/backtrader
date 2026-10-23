"""Native Alpha101 factor implementation for Alpha046."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Delay,
    Divide,
    LessThan,
    Multiply,
    Subtract,
    Where,
)
from .._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha046Native(FactorIndicator):
    """Alpha#46: nested threshold branches over the 20-grid close slope."""

    lines = ("factor",)
    alpha_id = 46
    case_id = "AF46-046"
    lookback_h = 20
    formula = "((0.25 < (((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10))) ? (-1 * 1) : (((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < 0) ? 1 : ((-1 * 1) * (close - delay(close, 1)))))"
    formula_fields = ("close",)
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        close = self.field_lines("close")
        close_delay20 = per_asset(self, "close_delay20", Delay, close, period=20)
        close_delay10_a = per_asset(self, "close_delay10_a", Delay, close, period=10)
        move_a = per_asset(self, "delay20_minus_delay10", Subtract, close_delay20, close_delay10_a)
        normalized_a = per_asset(
            self, "normalized_delay_move", Divide, move_a, (10.0,) * len(self.datas)
        )
        close_delay10_b = per_asset(self, "close_delay10_b", Delay, close, period=10)
        move_b = per_asset(self, "delay10_minus_close", Subtract, close_delay10_b, close)
        normalized_b = per_asset(
            self, "normalized_recent_move", Divide, move_b, (10.0,) * len(self.datas)
        )
        slope = per_asset(self, "slope", Subtract, normalized_a, normalized_b)
        above_quarter = per_asset(
            self, "slope_above_quarter", LessThan, (0.25,) * len(self.datas), slope
        )
        below_zero = per_asset(self, "slope_below_zero", LessThan, slope, (0.0,) * len(self.datas))
        close_delay1 = per_asset(self, "close_delay1", Delay, close, period=1)
        last_move = per_asset(self, "close_minus_delay1", Subtract, close, close_delay1)
        negative_last_move = per_asset(
            self, "negative_close_minus_delay1", Multiply, last_move, (-1.0,) * len(self.datas)
        )
        lower_branch = per_asset(
            self,
            "lower_slope_branch",
            Where,
            below_zero,
            (1.0,) * len(self.datas),
            negative_last_move,
        )
        self._result_lines = per_asset(
            self,
            "outer_slope_branch",
            Where,
            above_quarter,
            (-1.0,) * len(self.datas),
            lower_branch,
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        close = ctx.field("close")
        close_delay20 = ctx.delay(close, 20)
        close_delay10_a = ctx.delay(close, 10)
        move_a = close_delay20 - close_delay10_a
        normalized_a = move_a / 10.0
        close_delay10_b = ctx.delay(close, 10)
        move_b = close_delay10_b - close
        normalized_b = move_b / 10.0
        slope = normalized_a - normalized_b
        above_quarter = ctx.less_than(0.25, slope)
        below_zero = ctx.less_than(slope, 0.0)
        close_delay1 = ctx.delay(close, 1)
        last_move = close - close_delay1
        negative_last_move = last_move * -1.0
        lower_branch = ctx.where(below_zero, 1.0, negative_last_move)
        factor = ctx.where(above_quarter, -1.0, lower_branch)
        return factor
