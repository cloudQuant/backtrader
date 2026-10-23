"""Native Alpha101 factor implementation for Alpha013."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Multiply,
    RollingCovariance,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha013Native(FactorIndicator):
    """AF46-013: cross-ranked price/volume covariance followed by cross rank."""

    lines = ("factor",)
    alpha_id = 13
    case_id = "AF46-013"
    lookback_h = 4
    formula_fields = ("close", "volume")
    required_fields = formula_fields
    formula = "(-1 * rank(covariance(rank(close), rank(volume), 5)))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        close_rank = panel(self, "rank_close", CrossSectionalRank, self.field_lines("close"))
        volume_rank = panel(self, "rank_volume", CrossSectionalRank, self.field_lines("volume"))
        covariance = per_asset(
            self, "covariance5", RollingCovariance, close_rank, volume_rank, period=5
        )
        ranked_covariance = panel(self, "rank_covariance", CrossSectionalRank, covariance)
        self._result_lines = per_asset(
            self, "negate", Multiply, ranked_covariance, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        close_rank = ctx.rank(ctx.field("close"))
        volume_rank = ctx.rank(ctx.field("volume"))
        covariance = ctx.covariance(close_rank, volume_rank, 5)
        ranked_covariance = ctx.rank(covariance)
        factor = ranked_covariance * -1.0
        return factor
