"""Native Alpha101 factor implementation for Alpha057."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    DecayLinear,
    Divide,
    Multiply,
    Subtract,
    TsArgMax,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha057Native(FactorIndicator):
    """Alpha#57: close/VWAP gap scaled by a decayed ranked argmax."""

    lines = ("factor",)
    alpha_id = 57
    case_id = "AF46-057"
    lookback_h = 30
    formula = "(0 - (1 * ((close - vwap) / decay_linear(rank(ts_argmax(close, 30)), 2))))"
    formula_fields = ("close", "vwap")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        close_vwap = per_asset(
            self, "close_minus_vwap", Subtract, self.field_lines("close"), self.field_lines("vwap")
        )
        argmax = per_asset(self, "close_argmax30", TsArgMax, self.field_lines("close"), period=30)
        argmax_rank = panel(self, "rank_close_argmax", CrossSectionalRank, argmax)
        decayed_rank = per_asset(self, "decay_argmax_rank2", DecayLinear, argmax_rank, period=2)
        ratio = per_asset(self, "close_vwap_over_decayed_rank", Divide, close_vwap, decayed_rank)
        weighted_ratio = per_asset(
            self, "one_times_ratio", Multiply, (1.0,) * len(self.datas), ratio
        )
        self._result_lines = per_asset(
            self, "zero_minus_ratio", Subtract, (0.0,) * len(self.datas), weighted_ratio
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha057Build(FactorIndicator):
    """AF48-057: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha057Native.alpha_id
    case_id = Alpha057Native.case_id
    lookback_h = Alpha057Native.lookback_h
    formula_fields = Alpha057Native.formula_fields
    required_fields = Alpha057Native.required_fields
    formula = Alpha057Native.formula
    operator_profile = Alpha057Native.operator_profile
    input_policy = Alpha057Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        close_vwap = ctx.field("close") - ctx.field("vwap")
        argmax = ctx.ts_argmax(ctx.field("close"), 30)
        argmax_rank = ctx.rank(argmax)
        decayed_rank = ctx.decay_linear(argmax_rank, 2)
        ratio = close_vwap / decayed_rank
        weighted_ratio = 1.0 * ratio
        factor = 0.0 - weighted_ratio
        return factor
