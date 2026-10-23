"""Native Alpha101 factor implementation for Alpha071."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
    Maximum,
    Power,
    RollingCorrelation,
    Subtract,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha071Native(FactorIndicator):
    """Native implementation of Alpha071."""

    lines = ("factor",)
    alpha_id = 71
    case_id = "AF46-071"
    lookback_h = 224
    formula_fields = ("close", "low", "open", "vwap", "dollar_volume", "adv180")
    required_fields = formula_fields
    formula = "max(Ts_Rank(decay_linear(correlation(Ts_Rank(close, 3.43976), Ts_Rank(adv180, 12.0647), 18.0175), 4.20501), 15.6948), Ts_Rank(decay_linear((rank(((low + open) - (vwap + vwap)))^2), 16.4662), 4.4388))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        close_rank = per_asset(
            self, "close_ts_rank3", TsRank, self.field_lines("close"), period=3.43976
        )
        adv_rank = per_asset(
            self, "adv180_ts_rank12", TsRank, self.field_lines("adv180"), period=12.0647
        )
        correlation = per_asset(
            self, "rank_correlation18", RollingCorrelation, close_rank, adv_rank, period=18.0175
        )
        correlation_decay = per_asset(
            self, "correlation_decay4", DecayLinear, correlation, period=4.20501
        )
        first = per_asset(self, "correlation_ts_rank15", TsRank, correlation_decay, period=15.6948)
        low_open = per_asset(
            self, "low_plus_open", Add, self.field_lines("low"), self.field_lines("open")
        )
        vwap_twice = per_asset(
            self, "vwap_plus_vwap", Add, self.field_lines("vwap"), self.field_lines("vwap")
        )
        spread = per_asset(self, "low_open_minus_vwap_twice", Subtract, low_open, vwap_twice)
        spread_rank = panel(self, "spread_rank", CrossSectionalRank, spread)
        squared_rank = per_asset(
            self, "ordinary_rank_power2", Power, spread_rank, (2.0,) * len(self.datas)
        )
        spread_decay = per_asset(self, "spread_decay16", DecayLinear, squared_rank, period=16.4662)
        second = per_asset(self, "spread_ts_rank4", TsRank, spread_decay, period=4.4388)
        self._result_lines = per_asset(self, "pointwise_maximum", Maximum, first, second)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        close_rank = ctx.ts_rank(ctx.field("close"), 3.43976)
        adv_rank = ctx.ts_rank(ctx.field("adv180"), 12.0647)
        correlation = ctx.correlation(close_rank, adv_rank, 18.0175)
        correlation_decay = ctx.decay_linear(correlation, 4.20501)
        first = ctx.ts_rank(correlation_decay, 15.6948)
        low_open = ctx.field("low") + ctx.field("open")
        vwap_twice = ctx.field("vwap") + ctx.field("vwap")
        spread = low_open - vwap_twice
        spread_rank = ctx.rank(spread)
        squared_rank = spread_rank**2.0
        spread_decay = ctx.decay_linear(squared_rank, 16.4662)
        second = ctx.ts_rank(spread_decay, 4.4388)
        factor = ctx.maximum(first, second)
        return factor
