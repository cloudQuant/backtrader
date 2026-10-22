"""Native Alpha101 factor implementation for Alpha084."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Delta,
    SignedPower,
    Subtract,
    TsMax,
    TsRank,
)
from .._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha084Native(FactorIndicator):
    """AF46-084: signed power with dynamic close-change exponent."""

    lines = ("factor",)
    alpha_id = 84
    case_id = "AF46-084"
    lookback_h = 33
    formula_fields = ("close", "vwap")
    required_fields = formula_fields
    formula = "SignedPower(Ts_Rank((vwap - ts_max(vwap, 15.3217)), 20.7127), delta(close, 4.96796))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        vwap_max = per_asset(self, "vwap_max15", TsMax, self.field_lines("vwap"), period=15.3217)
        offset = per_asset(self, "vwap_minus_max", Subtract, self.field_lines("vwap"), vwap_max)
        base = per_asset(self, "ts_rank20", TsRank, offset, period=20.7127)
        exponent = per_asset(self, "close_delta4", Delta, self.field_lines("close"), period=4.96796)
        self._result_lines = per_asset(self, "signed_power", SignedPower, base, exponent)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha084Build(FactorIndicator):
    """AF48-084: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha084Native.alpha_id
    case_id = Alpha084Native.case_id
    lookback_h = Alpha084Native.lookback_h
    formula_fields = Alpha084Native.formula_fields
    required_fields = Alpha084Native.required_fields
    formula = Alpha084Native.formula
    operator_profile = Alpha084Native.operator_profile
    input_policy = Alpha084Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        vwap_max = ctx.ts_max(ctx.field("vwap"), 15.3217)
        offset = ctx.field("vwap") - vwap_max
        base = ctx.ts_rank(offset, 20.7127)
        exponent = ctx.delta(ctx.field("close"), 4.96796)
        factor = ctx.signed_power(base, exponent)
        return factor
