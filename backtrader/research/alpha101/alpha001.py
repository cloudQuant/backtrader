"""Native Alpha101 factor implementation for Alpha001."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    LessThan,
    RollingStd,
    SignedPower,
    Subtract,
    TsArgMax,
    Where,
)
from .._helpers import panel, per_asset, simple_returns
from ._metadata import native_alpha


@native_alpha
class Alpha001Native(FactorIndicator):
    """AF46-001: signed-power condition, five-grid argmax and cross rank."""

    lines = ("factor",)
    alpha_id = 1
    case_id = "AF46-001"
    lookback_h = 24
    formula_fields = ("close",)
    required_fields = formula_fields
    formula = (
        "(rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5)"
    )

    def __init__(self):
        super().__init__()
        self._nodes = {}
        returns = simple_returns(self, "returns")
        negative = per_asset(self, "negative_return", LessThan, returns, (0.0,) * len(self.datas))
        volatility = per_asset(self, "returns_std20", RollingStd, returns, period=20)
        selected = per_asset(
            self, "condition", Where, negative, volatility, self.field_lines("close")
        )
        power = per_asset(self, "signed_power2", SignedPower, selected, (2.0,) * len(self.datas))
        argmax = per_asset(self, "argmax5", TsArgMax, power, period=5)
        ranked = panel(self, "rank_argmax", CrossSectionalRank, argmax)
        self._result_lines = per_asset(
            self, "offset_half", Subtract, ranked, (0.5,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha001Build(FactorIndicator):
    """AF48-001: construct the native Alpha001 graph through the build API."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha001Native.alpha_id
    case_id = Alpha001Native.case_id
    lookback_h = Alpha001Native.lookback_h
    formula_fields = Alpha001Native.formula_fields
    required_fields = Alpha001Native.required_fields
    formula = Alpha001Native.formula
    operator_profile = Alpha001Native.operator_profile
    input_policy = Alpha001Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        returns = ctx.returns()
        selected = ctx.where(
            returns < 0.0,
            ctx.stddev(returns, 20),
            ctx.close,
        )
        powered = ctx.signed_power(selected, 2.0)
        return ctx.rank(ctx.ts_argmax(powered, 5)) - 0.5
