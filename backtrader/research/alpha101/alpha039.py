"""Native Alpha101 factor implementation for Alpha039."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
    Delta,
    Divide,
    Multiply,
    RollingSum,
    Subtract,
)
from .._helpers import panel, per_asset, simple_returns
from ._metadata import native_alpha


@native_alpha
class Alpha039Native(FactorIndicator):
    """AF46-039: ranked seven-grid price change, decay gate, and 250-grid return sum."""

    lines = ("factor",)
    alpha_id = 39
    case_id = "AF46-039"
    formula = (
        "((-1 * rank((delta(close, 7) * (1 - rank(decay_linear((volume / adv20), 9)))))) * "
        "(1 + rank(sum(returns, 250))))"
    )
    lookback_h = 250
    formula_fields = ("close", "volume", "dollar_volume", "adv20")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        volume_over_adv = per_asset(
            self, "volume_over_adv20", Divide, self.field_lines("volume"), self.field_lines("adv20")
        )
        decayed_ratio = per_asset(
            self, "decay_volume_over_adv_9", DecayLinear, volume_over_adv, period=9
        )
        ranked_decay = panel(self, "rank_decay_volume_over_adv", CrossSectionalRank, decayed_ratio)
        one_minus_ranked_decay = per_asset(
            self, "one_minus_ranked_decay", Subtract, (1.0,) * count, ranked_decay
        )
        close_delta_7 = per_asset(self, "close_delta_7", Delta, self.field_lines("close"), period=7)
        gated_price_change = per_asset(
            self, "gated_close_delta_7", Multiply, close_delta_7, one_minus_ranked_decay
        )
        ranked_gated_price_change = panel(
            self, "rank_gated_close_delta_7", CrossSectionalRank, gated_price_change
        )
        negative_ranked_price_change = per_asset(
            self,
            "negative_ranked_price_change",
            Multiply,
            (-1.0,) * count,
            ranked_gated_price_change,
        )
        returns = simple_returns(self, "returns")
        return_sum_250 = per_asset(self, "sum_returns_250", RollingSum, returns, period=250)
        ranked_return_sum = panel(self, "rank_sum_returns_250", CrossSectionalRank, return_sum_250)
        one_plus_ranked_return_sum = per_asset(
            self, "one_plus_ranked_return_sum", Add, (1.0,) * count, ranked_return_sum
        )
        self._result_lines = per_asset(
            self, "factor", Multiply, negative_ranked_price_change, one_plus_ranked_return_sum
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
