"""Native Alpha101 factor implementation for Alpha019."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Delay,
    Delta,
    Multiply,
    RollingSum,
    Sign,
    Subtract,
)
from .._helpers import panel, per_asset, simple_returns
from ._metadata import native_alpha


@native_alpha
class Alpha019Native(FactorIndicator):
    """Alpha #19: seven-grid close direction times the ranked 250-grid return sum."""

    lines = ("factor",)
    alpha_id = 19
    case_id = "AF46-019"
    lookback_h = 250
    formula = "((-1 * sign(((close - delay(close, 7)) + delta(close, 7)))) * (1 + rank((1 + sum(returns, 250)))))"
    formula_fields = ("close",)
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        close = self.field_lines("close")
        close_delay7 = per_asset(self, "close_delay7", Delay, close, period=7)
        close_minus_delay = per_asset(self, "close_minus_delay7", Subtract, close, close_delay7)
        close_delta7 = per_asset(self, "close_delta7", Delta, close, period=7)
        combined_change = per_asset(self, "combined_change", Add, close_minus_delay, close_delta7)
        change_sign = per_asset(self, "sign_combined_change", Sign, combined_change)
        negative_change_sign = per_asset(
            self, "negative_sign", Multiply, change_sign, (-1.0,) * count
        )
        returns_sum = per_asset(
            self, "returns_sum250", RollingSum, simple_returns(self, "returns"), period=250
        )
        sum_plus_one = per_asset(self, "sum_plus_one", Add, (1.0,) * count, returns_sum)
        ranked_return_sum = panel(self, "rank_sum_plus_one", CrossSectionalRank, sum_plus_one)
        rank_plus_one = per_asset(self, "rank_plus_one", Add, (1.0,) * count, ranked_return_sum)
        self._result_lines = per_asset(
            self, "factor", Multiply, negative_change_sign, rank_plus_one
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
