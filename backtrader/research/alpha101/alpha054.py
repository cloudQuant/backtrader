"""Native Alpha101 factor implementation for Alpha054."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Divide,
    Multiply,
    Power,
    Subtract,
)
from .._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha054Native(FactorIndicator):
    """Alpha#54: fifth-power OHLC expression with the source denominator."""

    lines = ("factor",)
    alpha_id = 54
    case_id = "AF46-054"
    lookback_h = 0
    formula = "((-1 * ((low - close) * (open^5))) / ((low - high) * (close^5)))"
    formula_fields = ("low", "close", "open", "high")
    required_fields = formula_fields
    # Paper execution timing metadata only; it does not change closed-bar H.
    paper_signal_delay = 0

    def __init__(self):
        super().__init__()
        self._nodes = {}
        low_close = per_asset(
            self, "low_minus_close", Subtract, self.field_lines("low"), self.field_lines("close")
        )
        open_fifth = per_asset(
            self, "open_fifth_power", Power, self.field_lines("open"), (5.0,) * len(self.datas)
        )
        numerator = per_asset(self, "low_close_times_open_fifth", Multiply, low_close, open_fifth)
        negative_numerator = per_asset(
            self, "negative_numerator", Multiply, numerator, (-1.0,) * len(self.datas)
        )
        low_high = per_asset(
            self, "low_minus_high", Subtract, self.field_lines("low"), self.field_lines("high")
        )
        close_fifth = per_asset(
            self, "close_fifth_power", Power, self.field_lines("close"), (5.0,) * len(self.datas)
        )
        denominator = per_asset(self, "denominator", Multiply, low_high, close_fifth)
        self._result_lines = per_asset(self, "alpha54", Divide, negative_numerator, denominator)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha054Build(FactorIndicator):
    """AF48-054: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha054Native.alpha_id
    case_id = Alpha054Native.case_id
    lookback_h = Alpha054Native.lookback_h
    formula_fields = Alpha054Native.formula_fields
    required_fields = Alpha054Native.required_fields
    formula = Alpha054Native.formula
    operator_profile = Alpha054Native.operator_profile
    input_policy = Alpha054Native.input_policy
    paper_signal_delay = Alpha054Native.paper_signal_delay

    @classmethod
    def build(cls, ctx, **params):
        low_close = ctx.field("low") - ctx.field("close")
        open_fifth = ctx.field("open") ** 5.0
        numerator = low_close * open_fifth
        negative_numerator = numerator * -1.0
        low_high = ctx.field("low") - ctx.field("high")
        close_fifth = ctx.field("close") ** 5.0
        denominator = low_high * close_fifth
        factor = negative_numerator / denominator
        return factor
