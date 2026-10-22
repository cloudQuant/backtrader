"""Native Alpha101 factor implementation for Alpha083."""

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
class Alpha083Native(FactorIndicator):
    """Alpha #83: delayed range rank, nested volume rank, and VWAP ratio."""

    lines = ("factor",)
    alpha_id = 83
    case_id = "AF46-083"
    lookback_h = 6
    formula = "((rank(delay(((high - low) / (sum(close, 5) / 5)), 2)) * rank(rank(volume))) / (((high - low) / (sum(close, 5) / 5)) / (vwap - close)))"
    formula_fields = ("high", "low", "close", "volume", "vwap")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        high_minus_low = per_asset(
            self, "high_minus_low", Subtract, self.field_lines("high"), self.field_lines("low")
        )
        close_mean = per_asset(
            self,
            "close_mean5",
            Divide,
            per_asset(self, "close_sum5", RollingSum, self.field_lines("close"), period=5),
            (5.0,) * count,
        )
        range_over_close_mean = per_asset(
            self, "range_over_close_mean", Divide, high_minus_low, close_mean
        )
        delayed_range = per_asset(self, "delayed_range", Delay, range_over_close_mean, period=2)
        ranked_delayed_range = panel(self, "rank_delayed_range", CrossSectionalRank, delayed_range)
        ranked_volume = panel(self, "rank_volume", CrossSectionalRank, self.field_lines("volume"))
        ranked_ranked_volume = panel(self, "rank_ranked_volume", CrossSectionalRank, ranked_volume)
        numerator = per_asset(
            self, "rank_product", Multiply, ranked_delayed_range, ranked_ranked_volume
        )
        vwap_minus_close = per_asset(
            self, "vwap_minus_close", Subtract, self.field_lines("vwap"), self.field_lines("close")
        )
        denominator = per_asset(
            self,
            "range_over_close_mean_over_vwap_gap",
            Divide,
            range_over_close_mean,
            vwap_minus_close,
        )
        self._result_lines = per_asset(self, "factor", Divide, numerator, denominator)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
