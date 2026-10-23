"""Native Alpha101 factor implementation for Alpha088."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
    Minimum,
    RollingCorrelation,
    Subtract,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha088Native(FactorIndicator):
    """Alpha #88: pointwise minimum of an OHLC rank spread and TS branch."""

    lines = ("factor",)
    alpha_id = 88
    case_id = "AF46-088"
    lookback_h = 91
    formula = "min(rank(decay_linear(((rank(open) + rank(low)) - (rank(high) + rank(close))), 8.06882)), Ts_Rank(decay_linear(correlation(Ts_Rank(close, 8.44728), Ts_Rank(adv60, 20.6966), 8.01266), 6.65053), 2.61957))"
    formula_fields = ("open", "low", "high", "close", "dollar_volume", "adv60")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        open_rank = panel(self, "rank_open", CrossSectionalRank, self.field_lines("open"))
        low_rank = panel(self, "rank_low", CrossSectionalRank, self.field_lines("low"))
        high_rank = panel(self, "rank_high", CrossSectionalRank, self.field_lines("high"))
        close_rank = panel(self, "rank_close", CrossSectionalRank, self.field_lines("close"))
        low_rank_sum = per_asset(self, "open_rank_plus_low_rank", Add, open_rank, low_rank)
        high_rank_sum = per_asset(self, "high_rank_plus_close_rank", Add, high_rank, close_rank)
        rank_spread = per_asset(self, "rank_spread", Subtract, low_rank_sum, high_rank_sum)
        spread_decay = per_asset(
            self, "rank_spread_decay", DecayLinear, rank_spread, period=8.06882
        )
        ranked_spread_decay = panel(self, "rank_decayed_spread", CrossSectionalRank, spread_decay)
        close_time_rank = per_asset(
            self, "close_time_rank8", TsRank, self.field_lines("close"), period=8.44728
        )
        adv60_time_rank = per_asset(
            self, "adv60_time_rank20", TsRank, self.field_lines("adv60"), period=20.6966
        )
        correlation = per_asset(
            self,
            "time_rank_correlation",
            RollingCorrelation,
            close_time_rank,
            adv60_time_rank,
            period=8.01266,
        )
        correlation_decay = per_asset(
            self, "correlation_decay6", DecayLinear, correlation, period=6.65053
        )
        correlation_time_rank = per_asset(
            self, "correlation_time_rank2", TsRank, correlation_decay, period=2.61957
        )
        self._result_lines = per_asset(
            self, "minimum_of_branches", Minimum, ranked_spread_decay, correlation_time_rank
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        open_rank = ctx.rank(ctx.field("open"))
        low_rank = ctx.rank(ctx.field("low"))
        high_rank = ctx.rank(ctx.field("high"))
        close_rank = ctx.rank(ctx.field("close"))
        low_rank_sum = open_rank + low_rank
        high_rank_sum = high_rank + close_rank
        rank_spread = low_rank_sum - high_rank_sum
        spread_decay = ctx.decay_linear(rank_spread, 8.06882)
        ranked_spread_decay = ctx.rank(spread_decay)
        close_time_rank = ctx.ts_rank(ctx.field("close"), 8.44728)
        adv60_time_rank = ctx.ts_rank(ctx.field("adv60"), 20.6966)
        correlation = ctx.correlation(close_time_rank, adv60_time_rank, 8.01266)
        correlation_decay = ctx.decay_linear(correlation, 6.65053)
        correlation_time_rank = ctx.ts_rank(correlation_decay, 2.61957)
        factor = ctx.minimum(ranked_spread_decay, correlation_time_rank)
        return factor
