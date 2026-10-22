"""Native Alpha101 factor implementation for Alpha047."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Delay,
    Divide,
    Multiply,
    RollingSum,
    Subtract,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha047Native(FactorIndicator):
    """Alpha#47: ADV-scaled ranked reciprocal and delayed-VWAP adjustment."""

    lines = ("factor",)
    alpha_id = 47
    case_id = "AF46-047"
    lookback_h = 19
    formula = "((((rank((1 / close)) * volume) / adv20) * ((high * rank((high - close))) / (sum(high, 5) / 5))) - rank((vwap - delay(vwap, 5))))"
    formula_fields = ("close", "volume", "high", "vwap", "dollar_volume", "adv20")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        one_over_close = per_asset(
            self, "one_over_close", Divide, (1.0,) * len(self.datas), self.field_lines("close")
        )
        reciprocal_rank = panel(self, "rank_reciprocal_close", CrossSectionalRank, one_over_close)
        volume_weighted_rank = per_asset(
            self,
            "volume_times_rank_reciprocal",
            Multiply,
            reciprocal_rank,
            self.field_lines("volume"),
        )
        adv_scaled = per_asset(
            self, "volume_rank_over_adv20", Divide, volume_weighted_rank, self.field_lines("adv20")
        )
        high_close_rank_input = per_asset(
            self, "high_minus_close", Subtract, self.field_lines("high"), self.field_lines("close")
        )
        high_close_rank = panel(
            self, "rank_high_minus_close", CrossSectionalRank, high_close_rank_input
        )
        high_rank_weighted = per_asset(
            self,
            "high_times_rank_high_minus_close",
            Multiply,
            self.field_lines("high"),
            high_close_rank,
        )
        high_sum5 = per_asset(self, "high_sum5", RollingSum, self.field_lines("high"), period=5)
        high_mean5 = per_asset(self, "high_mean5", Divide, high_sum5, (5.0,) * len(self.datas))
        high_component = per_asset(self, "high_component", Divide, high_rank_weighted, high_mean5)
        left = per_asset(
            self, "adv_scaled_times_high_component", Multiply, adv_scaled, high_component
        )
        vwap_delay5 = per_asset(self, "vwap_delay5", Delay, self.field_lines("vwap"), period=5)
        vwap_move = per_asset(
            self, "vwap_minus_delay5", Subtract, self.field_lines("vwap"), vwap_delay5
        )
        vwap_rank = panel(self, "rank_vwap_move", CrossSectionalRank, vwap_move)
        self._result_lines = per_asset(self, "alpha47", Subtract, left, vwap_rank)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
