"""Native Alpha101 factor implementation for Alpha014."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Delta,
    Multiply,
    RollingCorrelation,
)
from ._helpers import panel, per_asset, simple_returns
from ._metadata import native_alpha


@native_alpha
class Alpha014Native(FactorIndicator):
    """Alpha #14: negative ranked three-grid return delta times raw correlation."""

    lines = ("factor",)
    alpha_id = 14
    case_id = "AF46-014"
    lookback_h = 9
    formula = "((-1 * rank(delta(returns, 3))) * correlation(open, volume, 10))"
    formula_fields = ("close", "open", "volume")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        return_delta = per_asset(
            self, "returns_delta3", Delta, simple_returns(self, "returns"), period=3
        )
        ranked_return_delta = panel(self, "rank_returns_delta", CrossSectionalRank, return_delta)
        negative_ranked_delta = per_asset(
            self, "negative_ranked_returns_delta", Multiply, ranked_return_delta, (-1.0,) * count
        )
        correlation = per_asset(
            self,
            "open_volume_correlation10",
            RollingCorrelation,
            self.field_lines("open"),
            self.field_lines("volume"),
            period=10,
        )
        self._result_lines = per_asset(self, "factor", Multiply, negative_ranked_delta, correlation)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
