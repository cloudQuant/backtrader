"""Native Alpha101 factor implementation for Alpha006."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Multiply,
    RollingCorrelation,
)
from .._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha006Native(FactorIndicator):
    """Alpha #6: negative ten-grid open/volume correlation (pure time series)."""

    lines = ("factor",)
    alpha_id = 6
    case_id = "AF46-006"
    lookback_h = 9
    formula = "(-1 * correlation(open, volume, 10))"
    formula_fields = ("open", "volume")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        correlation = per_asset(
            self,
            "correlation10",
            RollingCorrelation,
            self.field_lines("open"),
            self.field_lines("volume"),
            period=10,
        )
        self._result_lines = per_asset(
            self, "negative_correlation", Multiply, correlation, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha006Build(FactorIndicator):
    """AF48-006: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha006Native.alpha_id
    case_id = Alpha006Native.case_id
    lookback_h = Alpha006Native.lookback_h
    formula_fields = Alpha006Native.formula_fields
    required_fields = Alpha006Native.required_fields
    formula = Alpha006Native.formula
    operator_profile = Alpha006Native.operator_profile
    input_policy = Alpha006Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        correlation = ctx.correlation(ctx.field("open"), ctx.field("volume"), 10)
        factor = correlation * -1.0
        return factor
