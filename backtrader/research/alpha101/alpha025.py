"""Native Alpha101 factor implementation for Alpha025."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Multiply,
    Subtract,
)
from ._helpers import panel, per_asset, simple_returns
from ._metadata import native_alpha


@native_alpha
class Alpha025Native(FactorIndicator):
    """AF46-025: cross-sectional rank of the return/ADV/VWAP price term."""

    lines = ("factor",)
    alpha_id = 25
    case_id = "AF46-025"
    formula = "rank(((((-1 * returns) * adv20) * vwap) * (high - close)))"
    lookback_h = 19
    formula_fields = ("vwap", "high", "close", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        returns = simple_returns(self, "returns")
        negative_returns = per_asset(self, "negative_returns", Multiply, (-1.0,) * count, returns)
        return_adv = per_asset(
            self, "return_times_adv20", Multiply, negative_returns, self.field_lines("adv20")
        )
        return_adv_vwap = per_asset(
            self, "return_adv_times_vwap", Multiply, return_adv, self.field_lines("vwap")
        )
        high_minus_close = per_asset(
            self, "high_minus_close", Subtract, self.field_lines("high"), self.field_lines("close")
        )
        product = per_asset(self, "rank_input", Multiply, return_adv_vwap, high_minus_close)
        self._result_lines = panel(self, "factor", CrossSectionalRank, product)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
