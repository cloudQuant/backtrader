"""Native Alpha101 factor implementation for Alpha022."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Delta,
    Multiply,
    RollingCorrelation,
    RollingStd,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha022Native(FactorIndicator):
    """AF46-022: delta of high/volume correlation times ranked close volatility."""

    lines = ("factor",)
    alpha_id = 22
    case_id = "AF46-022"
    formula = "(-1 * (delta(correlation(high, volume, 5), 5) * rank(stddev(close, 20))))"
    lookback_h = 19
    formula_fields = ("high", "volume", "close")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        correlation = per_asset(
            self,
            "correlation_high_volume_5",
            RollingCorrelation,
            self.field_lines("high"),
            self.field_lines("volume"),
            period=5,
        )
        correlation_change = per_asset(self, "correlation_delta_5", Delta, correlation, period=5)
        close_volatility = per_asset(
            self, "close_std_20", RollingStd, self.field_lines("close"), period=20
        )
        ranked_volatility = panel(self, "rank_close_std_20", CrossSectionalRank, close_volatility)
        weighted = per_asset(
            self, "correlation_change_times_rank", Multiply, correlation_change, ranked_volatility
        )
        self._result_lines = per_asset(self, "factor", Multiply, (-1.0,) * count, weighted)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha022Build(FactorIndicator):
    """AF48-022: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha022Native.alpha_id
    case_id = Alpha022Native.case_id
    lookback_h = Alpha022Native.lookback_h
    formula_fields = Alpha022Native.formula_fields
    required_fields = Alpha022Native.required_fields
    formula = Alpha022Native.formula
    operator_profile = Alpha022Native.operator_profile
    input_policy = Alpha022Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        correlation = ctx.correlation(ctx.field("high"), ctx.field("volume"), 5)
        correlation_change = ctx.delta(correlation, 5)
        close_volatility = ctx.stddev(ctx.field("close"), 20)
        ranked_volatility = ctx.rank(close_volatility)
        weighted = correlation_change * ranked_volatility
        factor = -1.0 * weighted
        return factor
