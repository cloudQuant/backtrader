"""Native Alpha101 factor implementation for Alpha051."""

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
class Alpha051Native(FactorIndicator):
    """Alpha#51: strict negative-slope threshold with a one-grid fallback."""

    lines = ("factor",)
    alpha_id = 51
    case_id = "AF46-051"
    lookback_h = 20
    formula = "(((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < (-1 * 0.05)) ? 1 : ((-1 * 1) * (close - delay(close, 1))))"
    formula_fields = ("close",)
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        close = self.field_lines("close")
        delay20 = per_asset(self, "close_delay20", Delay, close, period=20)
        delay10_a = per_asset(self, "close_delay10_a", Delay, close, period=10)
        move_a = per_asset(self, "delay20_minus_delay10", Subtract, delay20, delay10_a)
        normalized_a = per_asset(
            self, "normalized_delay_move", Divide, move_a, (10.0,) * len(self.datas)
        )
        delay10_b = per_asset(self, "close_delay10_b", Delay, close, period=10)
        move_b = per_asset(self, "delay10_minus_close", Subtract, delay10_b, close)
        normalized_b = per_asset(
            self, "normalized_recent_move", Divide, move_b, (10.0,) * len(self.datas)
        )
        slope = per_asset(self, "slope", Subtract, normalized_a, normalized_b)
        below_threshold = per_asset(
            self, "slope_below_minus_point05", LessThan, slope, (-0.05,) * len(self.datas)
        )
        delay1 = per_asset(self, "close_delay1", Delay, close, period=1)
        last_move = per_asset(self, "close_minus_delay1", Subtract, close, delay1)
        negative_last_move = per_asset(
            self, "negative_close_move", Multiply, last_move, (-1.0,) * len(self.datas)
        )
        self._result_lines = per_asset(
            self,
            "threshold_branch",
            Where,
            below_threshold,
            (1.0,) * len(self.datas),
            negative_last_move,
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha051Build(FactorIndicator):
    """AF48-051: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha051Native.alpha_id
    case_id = Alpha051Native.case_id
    lookback_h = Alpha051Native.lookback_h
    formula_fields = Alpha051Native.formula_fields
    required_fields = Alpha051Native.required_fields
    formula = Alpha051Native.formula
    operator_profile = Alpha051Native.operator_profile
    input_policy = Alpha051Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        close = ctx.field("close")
        delay20 = ctx.delay(close, 20)
        delay10_a = ctx.delay(close, 10)
        move_a = delay20 - delay10_a
        normalized_a = move_a / 10.0
        delay10_b = ctx.delay(close, 10)
        move_b = delay10_b - close
        normalized_b = move_b / 10.0
        slope = normalized_a - normalized_b
        below_threshold = ctx.less_than(slope, -0.05)
        delay1 = ctx.delay(close, 1)
        last_move = close - delay1
        negative_last_move = last_move * -1.0
        factor = ctx.where(below_threshold, 1.0, negative_last_move)
        return factor
