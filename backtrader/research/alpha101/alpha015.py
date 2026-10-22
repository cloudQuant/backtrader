"""Native Alpha101 factor implementation for Alpha015."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Multiply,
    RollingCorrelation,
    RollingSum,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha015Native(FactorIndicator):
    """Alpha #15: negative rolling sum of cross-ranked rolling correlation."""

    lines = ("factor",)
    alpha_id = 15
    case_id = "AF46-015"
    lookback_h = 4
    formula = "(-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))"
    formula_fields = ("high", "volume")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        high_rank = panel(self, "rank_high", CrossSectionalRank, self.field_lines("high"))
        volume_rank = panel(self, "rank_volume", CrossSectionalRank, self.field_lines("volume"))
        correlation = per_asset(
            self, "rank_correlation3", RollingCorrelation, high_rank, volume_rank, period=3
        )
        ranked_correlation = panel(self, "rank_correlation", CrossSectionalRank, correlation)
        total = per_asset(self, "sum_ranked_correlation3", RollingSum, ranked_correlation, period=3)
        self._result_lines = per_asset(self, "negative_sum", Multiply, total, (-1.0,) * count)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
