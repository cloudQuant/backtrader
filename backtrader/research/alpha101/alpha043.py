"""Native Alpha101 factor implementation for Alpha043."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Delta,
    Divide,
    Multiply,
    TsRank,
)
from ._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha043Native(FactorIndicator):
    """Alpha#43: product of two within-asset volume/price time-series ranks."""

    lines = ("factor",)
    alpha_id = 43
    case_id = "AF46-043"
    lookback_h = 38
    formula = "(ts_rank((volume / adv20), 20) * ts_rank((-1 * delta(close, 7)), 8))"
    formula_fields = ("volume", "close", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        volume_to_adv = per_asset(
            self, "volume_to_adv20", Divide, self.field_lines("volume"), self.field_lines("adv20")
        )
        volume_rank = per_asset(self, "volume_adv_ts_rank20", TsRank, volume_to_adv, period=20)
        close_delta = per_asset(self, "close_delta7", Delta, self.field_lines("close"), period=7)
        negative_delta = per_asset(
            self, "negative_close_delta7", Multiply, close_delta, (-1.0,) * len(self.datas)
        )
        price_rank = per_asset(self, "negative_delta_ts_rank8", TsRank, negative_delta, period=8)
        self._result_lines = per_asset(self, "rank_product", Multiply, volume_rank, price_rank)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
