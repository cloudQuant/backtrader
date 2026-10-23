"""Native Alpha101 factor implementation for Alpha074."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    LessThan,
    Multiply,
    RollingCorrelation,
    RollingSum,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha074Native(FactorIndicator):
    """Native implementation of Alpha074."""

    lines = ("factor",)
    alpha_id = 74
    case_id = "AF46-074"
    lookback_h = 79
    formula_fields = ("close", "high", "vwap", "volume", "dollar_volume", "adv30")
    required_fields = formula_fields
    formula = "((rank(correlation(close, sum(adv30, 37.4843), 15.1365)) < rank(correlation(rank(((high * 0.0261661) + (vwap * (1 - 0.0261661)))), rank(volume), 11.4791))) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        adv_sum = per_asset(
            self, "adv30_sum37", RollingSum, self.field_lines("adv30"), period=37.4843
        )
        left_correlation = per_asset(
            self,
            "close_adv_sum_corr15",
            RollingCorrelation,
            self.field_lines("close"),
            adv_sum,
            period=15.1365,
        )
        left_rank = panel(self, "close_adv_sum_rank", CrossSectionalRank, left_correlation)
        weight = 0.0261661
        high_part = per_asset(
            self, "weighted_high", Multiply, self.field_lines("high"), (weight,) * len(self.datas)
        )
        vwap_part = per_asset(
            self,
            "weighted_vwap",
            Multiply,
            self.field_lines("vwap"),
            (1.0 - weight,) * len(self.datas),
        )
        price_rank = panel(
            self,
            "weighted_price_rank",
            CrossSectionalRank,
            per_asset(self, "weighted_price", Add, high_part, vwap_part),
        )
        volume_rank = panel(self, "volume_rank", CrossSectionalRank, self.field_lines("volume"))
        right_correlation = per_asset(
            self,
            "price_volume_rank_corr11",
            RollingCorrelation,
            price_rank,
            volume_rank,
            period=11.4791,
        )
        right_rank = panel(
            self, "price_volume_rank_corr_rank", CrossSectionalRank, right_correlation
        )
        comparison = per_asset(self, "rank_less_than", LessThan, left_rank, right_rank)
        self._result_lines = per_asset(
            self, "negative_boolean", Multiply, comparison, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        adv_sum = ctx.sum(ctx.field("adv30"), 37.4843)
        left_correlation = ctx.correlation(ctx.field("close"), adv_sum, 15.1365)
        left_rank = ctx.rank(left_correlation)
        weight = 0.0261661
        high_part = ctx.field("high") * weight
        vwap_part = ctx.field("vwap") * (1.0 - weight)
        price_rank = ctx.rank((high_part + vwap_part))
        volume_rank = ctx.rank(ctx.field("volume"))
        right_correlation = ctx.correlation(price_rank, volume_rank, 11.4791)
        right_rank = ctx.rank(right_correlation)
        comparison = ctx.less_than(left_rank, right_rank)
        factor = comparison * -1.0
        return factor
