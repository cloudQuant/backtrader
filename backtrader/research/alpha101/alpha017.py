"""Native Alpha101 factor implementation for Alpha017."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Delta,
    Divide,
    Multiply,
    TsRank,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha017Native(FactorIndicator):
    """Alpha #17: three cross-ranked branches, including dollar-volume ADV."""

    lines = ("factor",)
    alpha_id = 17
    case_id = "AF46-017"
    lookback_h = 23
    formula = "(((-1 * rank(ts_rank(close, 10))) * rank(delta(delta(close, 1), 1))) * rank(ts_rank((volume / adv20), 5)))"
    formula_fields = ("close", "volume", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        close_ts_rank = per_asset(
            self, "close_ts_rank10", TsRank, self.field_lines("close"), period=10
        )
        ranked_close_ts_rank = panel(self, "rank_close_ts_rank", CrossSectionalRank, close_ts_rank)
        negative_close_rank = per_asset(
            self, "negative_ranked_close_ts_rank", Multiply, ranked_close_ts_rank, (-1.0,) * count
        )
        close_delta1 = per_asset(self, "close_delta1", Delta, self.field_lines("close"), period=1)
        second_difference = per_asset(self, "close_second_delta1", Delta, close_delta1, period=1)
        ranked_second_difference = panel(
            self, "rank_close_second_delta", CrossSectionalRank, second_difference
        )
        first_product = per_asset(
            self, "first_rank_product", Multiply, negative_close_rank, ranked_second_difference
        )
        volume_over_adv = per_asset(
            self, "volume_over_adv20", Divide, self.field_lines("volume"), self.field_lines("adv20")
        )
        volume_adv_ts_rank = per_asset(
            self, "volume_adv_ts_rank5", TsRank, volume_over_adv, period=5
        )
        ranked_volume_adv_ts_rank = panel(
            self, "rank_volume_adv_ts_rank", CrossSectionalRank, volume_adv_ts_rank
        )
        self._result_lines = per_asset(
            self, "factor", Multiply, first_product, ranked_volume_adv_ts_rank
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
