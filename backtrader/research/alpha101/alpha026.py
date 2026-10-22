"""Native Alpha101 factor implementation for Alpha026."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Multiply,
    RollingCorrelation,
    TsMax,
    TsRank,
)
from .._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha026Native(FactorIndicator):
    """AF46-026: rolling maximum of correlations between volume/high time ranks."""

    lines = ("factor",)
    alpha_id = 26
    case_id = "AF46-026"
    formula = "(-1 * ts_max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))"
    lookback_h = 10
    formula_fields = ("volume", "high")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        volume_rank = per_asset(
            self, "volume_ts_rank_5", TsRank, self.field_lines("volume"), period=5
        )
        high_rank = per_asset(self, "high_ts_rank_5", TsRank, self.field_lines("high"), period=5)
        correlation = per_asset(
            self, "rank_correlation_5", RollingCorrelation, volume_rank, high_rank, period=5
        )
        maximum = per_asset(self, "correlation_max_3", TsMax, correlation, period=3)
        self._result_lines = per_asset(self, "factor", Multiply, (-1.0,) * count, maximum)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
