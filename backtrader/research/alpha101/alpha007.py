"""Native Alpha101 factor implementation for Alpha007."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Abs,
    Delta,
    LessThan,
    Multiply,
    Sign,
    TsRank,
    Where,
)
from .._helpers import per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha007Native(FactorIndicator):
    """AF46-007: dollar-ADV/share-volume gate with a sixty-grid true branch."""

    lines = ("factor",)
    alpha_id = 7
    case_id = "AF46-007"
    lookback_h = 66
    formula_fields = ("close", "volume", "dollar_volume", "adv20")
    required_fields = formula_fields
    formula = "((adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7))) : (-1 * 1))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        adv20 = self.field_lines("adv20")
        condition = per_asset(
            self, "adv20_less_volume", LessThan, adv20, self.field_lines("volume")
        )
        change = per_asset(self, "close_delta7", Delta, self.field_lines("close"), period=7)
        magnitude = per_asset(self, "abs_delta7", Abs, change)
        time_rank = per_asset(self, "ts_rank60", TsRank, magnitude, period=60)
        negative_rank = per_asset(
            self, "negative_ts_rank", Multiply, time_rank, (-1.0,) * len(self.datas)
        )
        direction = per_asset(self, "delta_sign", Sign, change)
        active = per_asset(self, "active_branch", Multiply, negative_rank, direction)
        self._result_lines = per_asset(
            self, "where", Where, condition, active, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
