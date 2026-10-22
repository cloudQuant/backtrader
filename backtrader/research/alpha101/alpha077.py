"""Native Alpha101 factor implementation for Alpha077."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
    Divide,
    Minimum,
    RollingCorrelation,
    Subtract,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha077Native(FactorIndicator):
    """Native implementation of Alpha077."""

    lines = ("factor",)
    alpha_id = 77
    case_id = "AF46-077"
    lookback_h = 45
    formula_fields = ("high", "low", "vwap", "dollar_volume", "adv40")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    formula = "min(rank(decay_linear(((((high + low) / 2) + high) - (vwap + high)), 20.0451)), rank(decay_linear(correlation(((high + low) / 2), adv40, 3.1614), 5.64125)))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        high = self.field_lines("high")
        low = self.field_lines("low")
        midpoint = per_asset(
            self,
            "high_low_midpoint",
            Divide,
            per_asset(self, "high_low_sum", Add, high, low),
            (2.0,) * len(self.datas),
        )
        midpoint_plus_high = per_asset(self, "midpoint_plus_high", Add, midpoint, high)
        vwap_plus_high = per_asset(self, "vwap_plus_high", Add, self.field_lines("vwap"), high)
        spread = per_asset(self, "spread", Subtract, midpoint_plus_high, vwap_plus_high)
        first_decay = per_asset(self, "spread_decay20", DecayLinear, spread, period=20.0451)
        first = panel(self, "spread_decay_rank", CrossSectionalRank, first_decay)
        correlation = per_asset(
            self,
            "midpoint_adv40_corr3",
            RollingCorrelation,
            midpoint,
            self.field_lines("adv40"),
            period=3.1614,
        )
        second_decay = per_asset(
            self, "correlation_decay5", DecayLinear, correlation, period=5.64125
        )
        second = panel(self, "correlation_decay_rank", CrossSectionalRank, second_decay)
        self._result_lines = per_asset(self, "pointwise_minimum", Minimum, first, second)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
