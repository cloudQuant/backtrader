"""Native Alpha101 factor implementation for Alpha099."""

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
class Alpha099Native(FactorIndicator):
    """Alpha #99: compare two ranked rolling correlations and negate the result."""

    lines = ("factor",)
    alpha_id = 99
    case_id = "AF46-099"
    lookback_h = 84
    formula = "((rank(correlation(sum(((high + low) / 2), 19.8975), sum(adv60, 19.8975), 8.8136)) < rank(correlation(low, volume, 6.28259))) * -1)"
    formula_fields = ("high", "low", "volume", "dollar_volume", "adv60")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        midpoint = per_asset(
            self,
            "high_low_midpoint",
            Divide,
            per_asset(
                self, "high_plus_low", Add, self.field_lines("high"), self.field_lines("low")
            ),
            (2.0,) * count,
        )
        midpoint_sum = per_asset(self, "midpoint_sum19", RollingSum, midpoint, period=19.8975)
        adv60_sum = per_asset(
            self, "adv60_sum19", RollingSum, self.field_lines("adv60"), period=19.8975
        )
        first_correlation = per_asset(
            self,
            "midpoint_adv60_correlation",
            RollingCorrelation,
            midpoint_sum,
            adv60_sum,
            period=8.8136,
        )
        ranked_first_correlation = panel(
            self, "rank_midpoint_adv60_correlation", CrossSectionalRank, first_correlation
        )
        second_correlation = per_asset(
            self,
            "low_volume_correlation",
            RollingCorrelation,
            self.field_lines("low"),
            self.field_lines("volume"),
            period=6.28259,
        )
        ranked_second_correlation = panel(
            self, "rank_low_volume_correlation", CrossSectionalRank, second_correlation
        )
        comparison = per_asset(
            self,
            "correlation_rank_comparison",
            LessThan,
            ranked_first_correlation,
            ranked_second_correlation,
        )
        self._result_lines = per_asset(
            self, "negative_comparison", Multiply, comparison, (-1.0,) * count
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
