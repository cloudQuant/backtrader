"""Native Alpha101 factor implementation for Alpha011."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Delta,
    Multiply,
    Subtract,
    TsMax,
    TsMin,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha011Native(FactorIndicator):
    """Alpha #11: ranked rolling VWAP/close extrema plus ranked volume delta."""

    lines = ("factor",)
    alpha_id = 11
    case_id = "AF46-011"
    lookback_h = 3
    formula = "((rank(ts_max((vwap - close), 3)) + rank(ts_min((vwap - close), 3))) * rank(delta(volume, 3)))"
    formula_fields = ("vwap", "close", "volume")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        spread = per_asset(
            self, "vwap_minus_close", Subtract, self.field_lines("vwap"), self.field_lines("close")
        )
        high_spread = per_asset(self, "spread_max3", TsMax, spread, period=3)
        low_spread = per_asset(self, "spread_min3", TsMin, spread, period=3)
        ranked_high = panel(self, "rank_spread_max", CrossSectionalRank, high_spread)
        ranked_low = panel(self, "rank_spread_min", CrossSectionalRank, low_spread)
        extrema_rank_sum = per_asset(self, "ranked_extrema_sum", Add, ranked_high, ranked_low)
        volume_delta = per_asset(self, "volume_delta3", Delta, self.field_lines("volume"), period=3)
        ranked_volume_delta = panel(self, "rank_volume_delta", CrossSectionalRank, volume_delta)
        self._result_lines = per_asset(
            self, "factor", Multiply, extrema_rank_sum, ranked_volume_delta
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha011Build(FactorIndicator):
    """AF48-011: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha011Native.alpha_id
    case_id = Alpha011Native.case_id
    lookback_h = Alpha011Native.lookback_h
    formula_fields = Alpha011Native.formula_fields
    required_fields = Alpha011Native.required_fields
    formula = Alpha011Native.formula
    operator_profile = Alpha011Native.operator_profile
    input_policy = Alpha011Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        spread = ctx.field("vwap") - ctx.field("close")
        high_spread = ctx.ts_max(spread, 3)
        low_spread = ctx.ts_min(spread, 3)
        ranked_high = ctx.rank(high_spread)
        ranked_low = ctx.rank(low_spread)
        extrema_rank_sum = ranked_high + ranked_low
        volume_delta = ctx.delta(ctx.field("volume"), 3)
        ranked_volume_delta = ctx.rank(volume_delta)
        factor = extrema_rank_sum * ranked_volume_delta
        return factor
