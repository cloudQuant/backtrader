"""Native Alpha101 factor implementation for Alpha075."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    LessThan,
    RollingCorrelation,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha075Native(FactorIndicator):
    """Native implementation of Alpha075."""

    lines = ("factor",)
    alpha_id = 75
    case_id = "AF46-075"
    lookback_h = 60
    formula_fields = ("vwap", "volume", "low", "dollar_volume", "adv50")
    required_fields = formula_fields
    formula = "(rank(correlation(vwap, volume, 4.24304)) < rank(correlation(rank(low), rank(adv50), 12.4413)))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        left_correlation = per_asset(
            self,
            "vwap_volume_corr4",
            RollingCorrelation,
            self.field_lines("vwap"),
            self.field_lines("volume"),
            period=4.24304,
        )
        left_rank = panel(self, "vwap_volume_corr_rank", CrossSectionalRank, left_correlation)
        low_rank = panel(self, "low_rank", CrossSectionalRank, self.field_lines("low"))
        adv_rank = panel(self, "adv50_rank", CrossSectionalRank, self.field_lines("adv50"))
        right_correlation = per_asset(
            self, "low_adv50_rank_corr12", RollingCorrelation, low_rank, adv_rank, period=12.4413
        )
        right_rank = panel(self, "low_adv50_rank_corr_rank", CrossSectionalRank, right_correlation)
        self._result_lines = per_asset(self, "rank_less_than", LessThan, left_rank, right_rank)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        left_correlation = ctx.correlation(ctx.field("vwap"), ctx.field("volume"), 4.24304)
        left_rank = ctx.rank(left_correlation)
        low_rank = ctx.rank(ctx.field("low"))
        adv_rank = ctx.rank(ctx.field("adv50"))
        right_correlation = ctx.correlation(low_rank, adv_rank, 12.4413)
        right_rank = ctx.rank(right_correlation)
        factor = ctx.less_than(left_rank, right_rank)
        return factor
