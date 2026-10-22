"""Native Alpha101 factor implementation for Alpha073."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
    Delta,
    Divide,
    Maximum,
    Multiply,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha073Native(FactorIndicator):
    """Native implementation of Alpha073."""

    lines = ("factor",)
    alpha_id = 73
    case_id = "AF46-073"
    lookback_h = 19
    formula_fields = ("vwap", "open", "low")
    required_fields = formula_fields
    formula = "(max(rank(decay_linear(delta(vwap, 4.72775), 2.91864)), Ts_Rank(decay_linear(((delta(((open * 0.147155) + (low * (1 - 0.147155))), 2.03608) / ((open * 0.147155) + (low * (1 - 0.147155)))) * -1), 3.33829), 16.7411)) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        vwap_delta = per_asset(self, "vwap_delta4", Delta, self.field_lines("vwap"), period=4.72775)
        vwap_decay = per_asset(self, "vwap_delta_decay2", DecayLinear, vwap_delta, period=2.91864)
        first = panel(self, "vwap_delta_decay_rank", CrossSectionalRank, vwap_decay)
        weight = 0.147155
        open_part = per_asset(
            self, "weighted_open", Multiply, self.field_lines("open"), (weight,) * len(self.datas)
        )
        low_part = per_asset(
            self,
            "weighted_low",
            Multiply,
            self.field_lines("low"),
            (1.0 - weight,) * len(self.datas),
        )
        weighted_price = per_asset(self, "weighted_price", Add, open_part, low_part)
        price_delta = per_asset(
            self, "weighted_price_delta2", Delta, weighted_price, period=2.03608
        )
        normalized_delta = per_asset(self, "normalized_delta", Divide, price_delta, weighted_price)
        negative_delta = per_asset(
            self, "negative_normalized_delta", Multiply, normalized_delta, (-1.0,) * len(self.datas)
        )
        second_decay = per_asset(
            self, "negative_delta_decay3", DecayLinear, negative_delta, period=3.33829
        )
        second = per_asset(self, "negative_delta_ts_rank16", TsRank, second_decay, period=16.7411)
        combined = per_asset(self, "pointwise_maximum", Maximum, first, second)
        self._result_lines = per_asset(
            self, "negative_maximum", Multiply, combined, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
