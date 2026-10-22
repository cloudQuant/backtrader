"""Native Alpha101 factor implementation for Alpha042."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Divide,
    Subtract,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha042Native(FactorIndicator):
    """Alpha#42: ratio of cross-sectional VWAP/close difference and sum ranks."""

    lines = ("factor",)
    alpha_id = 42
    case_id = "AF46-042"
    lookback_h = 0
    formula = "(rank((vwap - close)) / rank((vwap + close)))"
    formula_fields = ("vwap", "close")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    # Paper execution timing metadata only; it does not change closed-bar H.
    paper_signal_delay = 0

    def __init__(self):
        super().__init__()
        self._nodes = {}
        difference = per_asset(
            self, "vwap_minus_close", Subtract, self.field_lines("vwap"), self.field_lines("close")
        )
        difference_rank = panel(self, "rank_difference", CrossSectionalRank, difference)
        total = per_asset(
            self, "vwap_plus_close", Add, self.field_lines("vwap"), self.field_lines("close")
        )
        total_rank = panel(self, "rank_sum", CrossSectionalRank, total)
        self._result_lines = per_asset(self, "rank_ratio", Divide, difference_rank, total_rank)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
