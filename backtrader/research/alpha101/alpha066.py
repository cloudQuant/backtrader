"""Native Alpha101 factor implementation for Alpha066."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
    Delta,
    Divide,
    Multiply,
    Subtract,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha066Native(FactorIndicator):
    """Native implementation of Alpha066."""

    lines = ("factor",)
    alpha_id = 66
    case_id = "AF46-066"
    lookback_h = 15
    formula_fields = ("vwap", "low", "open", "high")
    required_fields = formula_fields
    formula = "((rank(decay_linear(delta(vwap, 3.51013), 7.23052)) + Ts_Rank(decay_linear(((((low * 0.96633) + (low * (1 - 0.96633))) - vwap) / (open - ((high + low) / 2))), 11.4157), 6.72611)) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        vwap_delta = per_asset(self, "vwap_delta3", Delta, self.field_lines("vwap"), period=3.51013)
        vwap_decay = per_asset(self, "vwap_delta_decay7", DecayLinear, vwap_delta, period=7.23052)
        first_rank = panel(self, "vwap_delta_decay_rank", CrossSectionalRank, vwap_decay)
        low = self.field_lines("low")
        open_ = self.field_lines("open")
        high = self.field_lines("high")
        weight = 0.96633
        weighted_low = per_asset(
            self, "weighted_low_first", Multiply, low, (weight,) * len(self.datas)
        )
        weighted_low_complement = per_asset(
            self, "weighted_low_second", Multiply, low, (1.0 - weight,) * len(self.datas)
        )
        low_mix = per_asset(self, "weighted_low_sum", Add, weighted_low, weighted_low_complement)
        low_minus_vwap = per_asset(
            self, "low_mix_minus_vwap", Subtract, low_mix, self.field_lines("vwap")
        )
        high_low_midpoint = per_asset(
            self,
            "high_low_midpoint",
            Divide,
            per_asset(self, "high_low_sum", Add, high, low),
            (2.0,) * len(self.datas),
        )
        denominator = per_asset(self, "open_minus_midpoint", Subtract, open_, high_low_midpoint)
        ratio = per_asset(self, "weighted_low_vwap_ratio", Divide, low_minus_vwap, denominator)
        ratio_decay = per_asset(self, "ratio_decay11", DecayLinear, ratio, period=11.4157)
        second = per_asset(self, "ratio_ts_rank6", TsRank, ratio_decay, period=6.72611)
        combined = per_asset(self, "rank_sum", Add, first_rank, second)
        self._result_lines = per_asset(
            self, "negative_sum", Multiply, combined, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
