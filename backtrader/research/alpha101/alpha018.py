"""Native Alpha101 factor implementation for Alpha018."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Abs,
    Add,
    CrossSectionalRank,
    Multiply,
    RollingCorrelation,
    RollingStd,
    Subtract,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha018Native(FactorIndicator):
    """Alpha #18: negative rank of the sum of spread volatility, spread and correlation."""

    lines = ("factor",)
    alpha_id = 18
    case_id = "AF46-018"
    lookback_h = 9
    formula = "(-1 * rank(((stddev(abs((close - open)), 5) + (close - open)) + correlation(close, open, 10))))"
    formula_fields = ("close", "open")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        spread = per_asset(
            self, "close_minus_open", Subtract, self.field_lines("close"), self.field_lines("open")
        )
        absolute_spread = per_asset(self, "absolute_spread", Abs, spread)
        spread_std = per_asset(self, "spread_std5", RollingStd, absolute_spread, period=5)
        std_plus_spread = per_asset(self, "std_plus_spread", Add, spread_std, spread)
        correlation = per_asset(
            self,
            "close_open_correlation10",
            RollingCorrelation,
            self.field_lines("close"),
            self.field_lines("open"),
            period=10,
        )
        combined = per_asset(self, "combined_spread_correlation", Add, std_plus_spread, correlation)
        ranked = panel(self, "rank_combined", CrossSectionalRank, combined)
        self._result_lines = per_asset(self, "negative_rank", Multiply, ranked, (-1.0,) * count)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
