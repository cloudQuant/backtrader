"""Native Alpha101 factor implementation for Alpha060."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    CrossSectionalScale,
    Divide,
    Multiply,
    Subtract,
    TsArgMax,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha060Native(FactorIndicator):
    """Alpha#60: difference of scaled ranked money-flow and argmax signals."""

    lines = ("factor",)
    alpha_id = 60
    case_id = "AF46-060"
    lookback_h = 9
    formula = "(0 - (1 * ((2 * scale(rank(((((close - low) - (high - close)) / (high - low)) * volume)))) - scale(rank(ts_argmax(close, 10))))))"
    formula_fields = ("close", "low", "high", "volume")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        close_low = per_asset(
            self, "close_minus_low", Subtract, self.field_lines("close"), self.field_lines("low")
        )
        high_close = per_asset(
            self, "high_minus_close", Subtract, self.field_lines("high"), self.field_lines("close")
        )
        position_numerator = per_asset(self, "position_numerator", Subtract, close_low, high_close)
        high_low = per_asset(
            self, "high_minus_low", Subtract, self.field_lines("high"), self.field_lines("low")
        )
        position = per_asset(self, "close_position", Divide, position_numerator, high_low)
        money_flow = per_asset(
            self, "position_times_volume", Multiply, position, self.field_lines("volume")
        )
        money_flow_rank = panel(self, "rank_money_flow", CrossSectionalRank, money_flow)
        money_flow_scale = panel(
            self, "scale_money_flow", CrossSectionalScale, money_flow_rank, a=1.0
        )
        scaled_money_flow = per_asset(
            self, "twice_scaled_money_flow", Multiply, (2.0,) * len(self.datas), money_flow_scale
        )
        argmax = per_asset(self, "close_argmax10", TsArgMax, self.field_lines("close"), period=10)
        argmax_rank = panel(self, "rank_close_argmax", CrossSectionalRank, argmax)
        argmax_scale = panel(self, "scale_argmax_rank", CrossSectionalScale, argmax_rank, a=1.0)
        difference = per_asset(
            self, "scaled_component_difference", Subtract, scaled_money_flow, argmax_scale
        )
        weighted_difference = per_asset(
            self, "one_times_component_difference", Multiply, (1.0,) * len(self.datas), difference
        )
        self._result_lines = per_asset(
            self,
            "zero_minus_component_difference",
            Subtract,
            (0.0,) * len(self.datas),
            weighted_difference,
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha060Build(FactorIndicator):
    """AF48-060: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha060Native.alpha_id
    case_id = Alpha060Native.case_id
    lookback_h = Alpha060Native.lookback_h
    formula_fields = Alpha060Native.formula_fields
    required_fields = Alpha060Native.required_fields
    formula = Alpha060Native.formula
    operator_profile = Alpha060Native.operator_profile
    input_policy = Alpha060Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        close_low = ctx.field("close") - ctx.field("low")
        high_close = ctx.field("high") - ctx.field("close")
        position_numerator = close_low - high_close
        high_low = ctx.field("high") - ctx.field("low")
        position = position_numerator / high_low
        money_flow = position * ctx.field("volume")
        money_flow_rank = ctx.rank(money_flow)
        money_flow_scale = ctx.scale(money_flow_rank, a=1.0)
        scaled_money_flow = 2.0 * money_flow_scale
        argmax = ctx.ts_argmax(ctx.field("close"), 10)
        argmax_rank = ctx.rank(argmax)
        argmax_scale = ctx.scale(argmax_rank, a=1.0)
        difference = scaled_money_flow - argmax_scale
        weighted_difference = 1.0 * difference
        factor = 0.0 - weighted_difference
        return factor
