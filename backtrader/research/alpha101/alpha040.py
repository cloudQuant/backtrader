"""Native Alpha101 factor implementation for Alpha040."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Multiply,
    RollingCorrelation,
    RollingStd,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha040Native(FactorIndicator):
    """AF46-040: negative ranked high volatility times high/volume correlation."""

    lines = ("factor",)
    alpha_id = 40
    case_id = "AF46-040"
    formula = "((-1 * rank(stddev(high, 10))) * correlation(high, volume, 10))"
    lookback_h = 9
    formula_fields = ("high", "volume")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        high_volatility = per_asset(
            self, "high_std_10", RollingStd, self.field_lines("high"), period=10
        )
        ranked_high_volatility = panel(
            self, "rank_high_std_10", CrossSectionalRank, high_volatility
        )
        negative_ranked_volatility = per_asset(
            self,
            "negative_ranked_high_volatility",
            Multiply,
            (-1.0,) * count,
            ranked_high_volatility,
        )
        high_volume_correlation = per_asset(
            self,
            "high_volume_correlation_10",
            RollingCorrelation,
            self.field_lines("high"),
            self.field_lines("volume"),
            period=10,
        )
        self._result_lines = per_asset(
            self, "factor", Multiply, negative_ranked_volatility, high_volume_correlation
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
