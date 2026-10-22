"""Native Alpha101 factor implementation for Alpha045."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Delay,
    Divide,
    Multiply,
    RollingCorrelation,
    RollingSum,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha045Native(FactorIndicator):
    """Alpha#45: nested ranks, delayed sum, and short rolling correlations."""

    lines = ("factor",)
    alpha_id = 45
    case_id = "AF46-045"
    lookback_h = 24
    formula = "(-1 * ((rank((sum(delay(close, 5), 20) / 20)) * correlation(close, volume, 2)) * rank(correlation(sum(close, 5), sum(close, 20), 2))))"
    formula_fields = ("close", "volume")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        close = self.field_lines("close")
        delayed_close = per_asset(self, "close_delay5", Delay, close, period=5)
        delayed_sum = per_asset(self, "delayed_close_sum20", RollingSum, delayed_close, period=20)
        delayed_mean = per_asset(
            self, "delayed_close_sum_mean20", Divide, delayed_sum, (20.0,) * len(self.datas)
        )
        delayed_rank = panel(self, "rank_delayed_close_mean", CrossSectionalRank, delayed_mean)
        short_correlation = per_asset(
            self,
            "close_volume_corr2",
            RollingCorrelation,
            close,
            self.field_lines("volume"),
            period=2,
        )
        close_sum5 = per_asset(self, "close_sum5", RollingSum, close, period=5)
        close_sum20 = per_asset(self, "close_sum20", RollingSum, close, period=20)
        sum_correlation = per_asset(
            self, "close_sums_corr2", RollingCorrelation, close_sum5, close_sum20, period=2
        )
        sum_correlation_rank = panel(
            self, "rank_close_sums_corr", CrossSectionalRank, sum_correlation
        )
        left_product = per_asset(self, "rank_times_corr", Multiply, delayed_rank, short_correlation)
        product = per_asset(
            self, "multiply_sum_correlation_rank", Multiply, left_product, sum_correlation_rank
        )
        self._result_lines = per_asset(
            self, "negative_product", Multiply, product, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
