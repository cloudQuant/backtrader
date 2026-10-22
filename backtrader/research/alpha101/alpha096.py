"""Native Alpha101 factor implementation for Alpha096."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    DecayLinear,
    Maximum,
    Multiply,
    RollingCorrelation,
    TsArgMax,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha096Native(FactorIndicator):
    """AF46-096: pointwise max of a short and nested long time-series branch."""

    lines = ("factor",)
    alpha_id = 96
    case_id = "AF46-096"
    lookback_h = 100
    formula_fields = ("close", "vwap", "volume", "dollar_volume", "adv60")
    required_fields = formula_fields
    formula = "(max(Ts_Rank(decay_linear(correlation(rank(vwap), rank(volume), 3.83878), 4.16783), 8.38151), Ts_Rank(decay_linear(Ts_ArgMax(correlation(Ts_Rank(close, 7.45404), Ts_Rank(adv60, 4.13242), 3.65459), 12.6556), 14.0365), 13.4143)) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        vwap_rank = panel(self, "rank_vwap", CrossSectionalRank, self.field_lines("vwap"))
        volume_rank = panel(self, "rank_volume", CrossSectionalRank, self.field_lines("volume"))
        short_correlation = per_asset(
            self, "short_correlation3", RollingCorrelation, vwap_rank, volume_rank, period=3.83878
        )
        short_decay = per_asset(
            self, "short_decay4", DecayLinear, short_correlation, period=4.16783
        )
        left = per_asset(self, "left_ts_rank8", TsRank, short_decay, period=8.38151)
        close_rank = per_asset(
            self, "close_ts_rank7", TsRank, self.field_lines("close"), period=7.45404
        )
        adv60 = self.field_lines("adv60")
        adv_rank = per_asset(self, "adv60_ts_rank4", TsRank, adv60, period=4.13242)
        long_correlation = per_asset(
            self, "long_correlation3", RollingCorrelation, close_rank, adv_rank, period=3.65459
        )
        argmax = per_asset(self, "correlation_argmax12", TsArgMax, long_correlation, period=12.6556)
        long_decay = per_asset(self, "long_decay14", DecayLinear, argmax, period=14.0365)
        right = per_asset(self, "right_ts_rank13", TsRank, long_decay, period=13.4143)
        maximum = per_asset(self, "pointwise_maximum", Maximum, left, right)
        self._result_lines = per_asset(self, "negate", Multiply, maximum, (-1.0,) * len(self.datas))
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
