"""Native Alpha101 factor implementation for Alpha030."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Delay,
    Divide,
    Multiply,
    RollingSum,
    Sign,
    Subtract,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha030Native(FactorIndicator):
    """AF46-030: rank the sum of three separately signed close changes."""

    lines = ("factor",)
    alpha_id = 30
    case_id = "AF46-030"
    formula = (
        "(((1.0 - rank(((sign((close - delay(close, 1))) + "
        "sign((delay(close, 1) - delay(close, 2)))) + "
        "sign((delay(close, 2) - delay(close, 3)))))) * sum(volume, 5)) / sum(volume, 20))"
    )
    lookback_h = 19
    formula_fields = ("close", "volume")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        close = self.field_lines("close")
        close_delay_1 = per_asset(self, "delay_close_1", Delay, close, period=1)
        close_delay_2 = per_asset(self, "delay_close_2", Delay, close, period=2)
        close_delay_3 = per_asset(self, "delay_close_3", Delay, close, period=3)
        change_1 = per_asset(self, "close_change_1", Subtract, close, close_delay_1)
        change_2 = per_asset(self, "close_change_2", Subtract, close_delay_1, close_delay_2)
        change_3 = per_asset(self, "close_change_3", Subtract, close_delay_2, close_delay_3)
        sign_1 = per_asset(self, "sign_close_change_1", Sign, change_1)
        sign_2 = per_asset(self, "sign_close_change_2", Sign, change_2)
        sign_3 = per_asset(self, "sign_close_change_3", Sign, change_3)
        sign_sum_1 = per_asset(self, "sign_sum_1", Add, sign_1, sign_2)
        sign_sum = per_asset(self, "sign_sum", Add, sign_sum_1, sign_3)
        ranked_sign_sum = panel(self, "rank_sign_sum", CrossSectionalRank, sign_sum)
        one_minus_rank = per_asset(
            self, "one_minus_rank", Subtract, (1.0,) * count, ranked_sign_sum
        )
        volume_5 = per_asset(self, "volume_sum_5", RollingSum, self.field_lines("volume"), period=5)
        volume_20 = per_asset(
            self, "volume_sum_20", RollingSum, self.field_lines("volume"), period=20
        )
        weighted = per_asset(self, "weighted_volume_5", Multiply, one_minus_rank, volume_5)
        self._result_lines = per_asset(self, "factor", Divide, weighted, volume_20)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
