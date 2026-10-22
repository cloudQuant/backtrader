"""Native Alpha101 factor implementation for Alpha055."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Divide,
    Multiply,
    RollingCorrelation,
    Subtract,
    TsMax,
    TsMin,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha055Native(FactorIndicator):
    """Alpha#55: rolling high/low channel rank correlated with ranked volume."""

    lines = ("factor",)
    alpha_id = 55
    case_id = "AF46-055"
    lookback_h = 16
    formula = "(-1 * correlation(rank(((close - ts_min(low, 12)) / (ts_max(high, 12) - ts_min(low, 12)))), rank(volume), 6))"
    formula_fields = ("close", "low", "high", "volume")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        low_minimum = per_asset(self, "low_minimum12", TsMin, self.field_lines("low"), period=12)
        high_maximum = per_asset(self, "high_maximum12", TsMax, self.field_lines("high"), period=12)
        channel_numerator = per_asset(
            self, "close_minus_low_minimum", Subtract, self.field_lines("close"), low_minimum
        )
        channel_width = per_asset(self, "channel_width", Subtract, high_maximum, low_minimum)
        channel_location = per_asset(
            self, "channel_location", Divide, channel_numerator, channel_width
        )
        location_rank = panel(self, "rank_channel_location", CrossSectionalRank, channel_location)
        volume_rank = panel(self, "rank_volume", CrossSectionalRank, self.field_lines("volume"))
        correlation = per_asset(
            self,
            "channel_volume_rank_corr6",
            RollingCorrelation,
            location_rank,
            volume_rank,
            period=6,
        )
        self._result_lines = per_asset(
            self, "negative_correlation", Multiply, correlation, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
