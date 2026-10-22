"""Native Alpha101 factor implementation for Alpha061."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    LessThan,
    RollingCorrelation,
    Subtract,
    TsMin,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha061Native(FactorIndicator):
    """Alpha#61: strict comparison of ranked VWAP channel and ADV correlation."""

    lines = ("factor",)
    alpha_id = 61
    case_id = "AF46-061"
    lookback_h = 195
    formula = "(rank((vwap - ts_min(vwap, 16.1219))) < rank(correlation(vwap, adv180, 17.9282)))"
    formula_fields = ("vwap", "dollar_volume", "adv180")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        vwap = self.field_lines("vwap")
        minimum = per_asset(self, "vwap_minimum16", TsMin, vwap, period=16.1219)
        minimum_gap = per_asset(self, "vwap_minus_minimum", Subtract, vwap, minimum)
        minimum_rank = panel(self, "rank_vwap_minimum_gap", CrossSectionalRank, minimum_gap)
        correlation = per_asset(
            self,
            "vwap_adv180_corr17",
            RollingCorrelation,
            vwap,
            self.field_lines("adv180"),
            period=17.9282,
        )
        correlation_rank = panel(self, "rank_vwap_adv180_corr", CrossSectionalRank, correlation)
        self._result_lines = per_asset(
            self, "ranked_comparison", LessThan, minimum_rank, correlation_rank
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
