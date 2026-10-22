"""Native Alpha101 factor implementation for Alpha053."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Delta,
    Divide,
    Multiply,
    Subtract,
)
from ._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha053Native(FactorIndicator):
    """Alpha#53: negative nine-grid delta of the close location ratio."""

    lines = ("factor",)
    alpha_id = 53
    case_id = "AF46-053"
    lookback_h = 9
    formula = "(-1 * delta((((close - low) - (high - close)) / (close - low)), 9))"
    formula_fields = ("close", "low", "high")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    # Paper execution timing metadata only; it does not change closed-bar H.
    paper_signal_delay = 0

    def __init__(self):
        super().__init__()
        self._nodes = {}
        close_low = per_asset(
            self, "close_minus_low", Subtract, self.field_lines("close"), self.field_lines("low")
        )
        high_close = per_asset(
            self, "high_minus_close", Subtract, self.field_lines("high"), self.field_lines("close")
        )
        numerator = per_asset(self, "location_numerator", Subtract, close_low, high_close)
        location = per_asset(self, "location_ratio", Divide, numerator, close_low)
        change = per_asset(self, "location_delta9", Delta, location, period=9)
        self._result_lines = per_asset(
            self, "negative_location_delta", Multiply, change, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
