"""Native Alpha101 factor implementation for Alpha041."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Multiply,
    Power,
    Subtract,
)
from .._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha041Native(FactorIndicator):
    """Alpha#41: geometric open-range proxy minus VWAP."""

    lines = ("factor",)
    alpha_id = 41
    case_id = "AF46-041"
    lookback_h = 0
    formula = "(((high * low)^0.5) - vwap)"
    formula_fields = ("high", "low", "vwap")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        high_low = per_asset(
            self, "high_times_low", Multiply, self.field_lines("high"), self.field_lines("low")
        )
        geometric_mean = per_asset(
            self, "geometric_mean", Power, high_low, (0.5,) * len(self.datas)
        )
        self._result_lines = per_asset(
            self, "minus_vwap", Subtract, geometric_mean, self.field_lines("vwap")
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
