"""Native Alpha101 factor implementation for Alpha095."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Divide,
    LessThan,
    Power,
    RollingCorrelation,
    RollingSum,
    Subtract,
    TsMin,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha095Native(FactorIndicator):
    """Alpha #95: compare the open range rank with a powered TS rank."""

    lines = ("factor",)
    alpha_id = 95
    case_id = "AF46-095"
    lookback_h = 78
    formula = "(rank((open - ts_min(open, 12.4105))) < Ts_Rank((rank(correlation(sum(((high + low) / 2), 19.1351), sum(adv40, 19.1351), 12.8742))^5), 11.7584))"
    formula_fields = ("open", "high", "low", "dollar_volume", "adv40")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        open_minimum = per_asset(
            self, "open_ts_min12", TsMin, self.field_lines("open"), period=12.4105
        )
        open_minus_minimum = per_asset(
            self, "open_minus_ts_min", Subtract, self.field_lines("open"), open_minimum
        )
        ranked_open_gap = panel(self, "rank_open_gap", CrossSectionalRank, open_minus_minimum)
        high_low_midpoint = per_asset(
            self,
            "high_low_midpoint",
            Divide,
            per_asset(
                self, "high_plus_low", Add, self.field_lines("high"), self.field_lines("low")
            ),
            (2.0,) * count,
        )
        midpoint_sum = per_asset(
            self, "high_low_midpoint_sum19", RollingSum, high_low_midpoint, period=19.1351
        )
        adv40_sum = per_asset(
            self, "adv40_sum19", RollingSum, self.field_lines("adv40"), period=19.1351
        )
        correlation = per_asset(
            self,
            "midpoint_adv40_correlation",
            RollingCorrelation,
            midpoint_sum,
            adv40_sum,
            period=12.8742,
        )
        ranked_correlation = panel(
            self, "rank_midpoint_adv40_correlation", CrossSectionalRank, correlation
        )
        powered_rank = per_asset(
            self, "ranked_correlation_power5", Power, ranked_correlation, (5.0,) * count
        )
        time_rank = per_asset(
            self, "powered_correlation_time_rank", TsRank, powered_rank, period=11.7584
        )
        self._result_lines = per_asset(self, "comparison", LessThan, ranked_open_gap, time_rank)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        open_minimum = ctx.ts_min(ctx.field("open"), 12.4105)
        open_minus_minimum = ctx.field("open") - open_minimum
        ranked_open_gap = ctx.rank(open_minus_minimum)
        high_low_midpoint = (ctx.field("high") + ctx.field("low")) / (2.0)
        midpoint_sum = ctx.sum(high_low_midpoint, 19.1351)
        adv40_sum = ctx.sum(ctx.field("adv40"), 19.1351)
        correlation = ctx.correlation(midpoint_sum, adv40_sum, 12.8742)
        ranked_correlation = ctx.rank(correlation)
        powered_rank = ranked_correlation ** (5.0)
        time_rank = ctx.ts_rank(powered_rank, 11.7584)
        factor = ctx.less_than(ranked_open_gap, time_rank)
        return factor
