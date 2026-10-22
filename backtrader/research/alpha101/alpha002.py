"""Native Alpha101 factor implementation for Alpha002."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Delta,
    Divide,
    Log,
    Multiply,
    RollingCorrelation,
    Subtract,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha002Native(FactorIndicator):
    """AF46-002: two ranked series and six-grid rolling correlation."""

    lines = ("factor",)
    alpha_id = 2
    case_id = "AF46-002"
    lookback_h = 7
    formula_fields = ("open", "close", "volume")
    required_fields = formula_fields
    formula = "(-1 * correlation(rank(delta(log(volume), 2)), rank(((close - open) / open)), 6))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        logged_volume = per_asset(self, "log_volume", Log, self.field_lines("volume"))
        volume_delta = per_asset(self, "volume_log_delta2", Delta, logged_volume, period=2)
        ranked_volume_delta = panel(self, "rank_volume_delta", CrossSectionalRank, volume_delta)
        open_gap = per_asset(
            self, "close_minus_open", Subtract, self.field_lines("close"), self.field_lines("open")
        )
        gap_fraction = per_asset(
            self, "open_gap_fraction", Divide, open_gap, self.field_lines("open")
        )
        ranked_gap = panel(self, "rank_open_gap", CrossSectionalRank, gap_fraction)
        correlation = per_asset(
            self, "correlation6", RollingCorrelation, ranked_volume_delta, ranked_gap, period=6
        )
        self._result_lines = per_asset(
            self, "negate", Multiply, correlation, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
