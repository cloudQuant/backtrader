"""Native Alpha101 factor implementation for Alpha050."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Multiply,
    RollingCorrelation,
    TsMax,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha050Native(FactorIndicator):
    """Alpha#50: negative five-grid maximum of ranked rank-correlation."""

    lines = ("factor",)
    alpha_id = 50
    case_id = "AF46-050"
    lookback_h = 8
    formula = "(-1 * ts_max(rank(correlation(rank(volume), rank(vwap), 5)), 5))"
    formula_fields = ("volume", "vwap")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        volume_rank = panel(self, "rank_volume", CrossSectionalRank, self.field_lines("volume"))
        vwap_rank = panel(self, "rank_vwap", CrossSectionalRank, self.field_lines("vwap"))
        correlation = per_asset(
            self, "rank_volume_vwap_corr5", RollingCorrelation, volume_rank, vwap_rank, period=5
        )
        correlation_rank = panel(self, "rank_correlation", CrossSectionalRank, correlation)
        maximum = per_asset(self, "correlation_rank_max5", TsMax, correlation_rank, period=5)
        self._result_lines = per_asset(
            self, "negative_maximum", Multiply, maximum, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
