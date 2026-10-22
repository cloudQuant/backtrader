"""Native Alpha101 factor implementation for Alpha062."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Divide,
    LessThan,
    Multiply,
    RollingCorrelation,
    RollingSum,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha062Native(FactorIndicator):
    """AF46-062: cross-ranked correlation versus nested comparison rank."""

    lines = ("factor",)
    alpha_id = 62
    case_id = "AF46-062"
    lookback_h = 48
    formula_fields = ("open", "high", "low", "vwap", "dollar_volume", "adv20")
    required_fields = formula_fields
    formula = "((rank(correlation(vwap, sum(adv20, 22.4101), 9.91009)) < rank(((rank(open) + rank(open)) < (rank(((high + low) / 2)) + rank(high))))) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        adv20 = self.field_lines("adv20")
        adv_sum = per_asset(self, "adv20_sum22", RollingSum, adv20, period=22.4101)
        correlation = per_asset(
            self,
            "correlation9",
            RollingCorrelation,
            self.field_lines("vwap"),
            adv_sum,
            period=9.91009,
        )
        ranked_correlation = panel(self, "rank_correlation", CrossSectionalRank, correlation)
        open_rank_left = panel(self, "rank_open_left", CrossSectionalRank, self.field_lines("open"))
        open_rank_right = panel(
            self, "rank_open_right", CrossSectionalRank, self.field_lines("open")
        )
        open_rank_sum = per_asset(self, "open_rank_sum", Add, open_rank_left, open_rank_right)
        midpoint = per_asset(
            self,
            "midpoint",
            Divide,
            per_asset(
                self, "high_plus_low", Add, self.field_lines("high"), self.field_lines("low")
            ),
            (2.0,) * len(self.datas),
        )
        midpoint_rank = panel(self, "rank_midpoint", CrossSectionalRank, midpoint)
        high_rank = panel(self, "rank_high", CrossSectionalRank, self.field_lines("high"))
        right_sum = per_asset(self, "midpoint_plus_high_rank", Add, midpoint_rank, high_rank)
        nested_bool = per_asset(self, "nested_comparison", LessThan, open_rank_sum, right_sum)
        ranked_nested_bool = panel(self, "rank_nested_bool", CrossSectionalRank, nested_bool)
        comparison = per_asset(
            self, "outer_comparison", LessThan, ranked_correlation, ranked_nested_bool
        )
        self._result_lines = per_asset(
            self, "negative_boolean", Multiply, comparison, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
