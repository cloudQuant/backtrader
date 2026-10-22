"""Native Alpha101 factor implementation for Alpha089."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    DecayLinear,
    Delta,
    IndNeutralize,
    Multiply,
    RollingCorrelation,
    Subtract,
    TsRank,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha089Native(FactorIndicator):
    """Alpha #89: subtract an industry-neutral VWAP delta branch from a low/ADV branch."""

    lines = ("factor",)
    alpha_id = 89
    case_id = "AF46-089"
    lookback_h = 26
    formula = "(Ts_Rank(decay_linear(correlation(((low * 0.967285) + (low * (1 - 0.967285))), adv10, 6.94279), 5.51607), 3.79744) - Ts_Rank(decay_linear(delta(IndNeutralize(vwap, IndClass.industry), 3.48158), 10.1466), 15.3012))"
    formula_fields = ("low", "vwap", "dollar_volume", "adv10")
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ("industry",)

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        alpha = 0.967285
        one_minus_alpha = per_asset(
            self, "one_minus_low_weight", Subtract, (1.0,) * count, (alpha,) * count
        )
        low_part_a = per_asset(
            self, "low_part_a", Multiply, self.field_lines("low"), (alpha,) * count
        )
        low_part_b = per_asset(
            self, "low_part_b", Multiply, self.field_lines("low"), one_minus_alpha
        )
        weighted_low = per_asset(self, "weighted_low", Add, low_part_a, low_part_b)
        low_adv_correlation = per_asset(
            self,
            "weighted_low_adv10_correlation",
            RollingCorrelation,
            weighted_low,
            self.field_lines("adv10"),
            period=6.94279,
        )
        low_correlation_decay = per_asset(
            self, "low_correlation_decay", DecayLinear, low_adv_correlation, period=5.51607
        )
        low_time_rank = per_asset(
            self, "low_branch_time_rank", TsRank, low_correlation_decay, period=3.79744
        )
        neutral_vwap = panel(
            self, "industry_neutral_vwap", IndNeutralize, self.field_lines("vwap"), level="industry"
        )
        neutral_vwap_delta = per_asset(
            self, "neutral_vwap_delta", Delta, neutral_vwap, period=3.48158
        )
        vwap_delta_decay = per_asset(
            self, "neutral_vwap_delta_decay", DecayLinear, neutral_vwap_delta, period=10.1466
        )
        vwap_branch_time_rank = per_asset(
            self, "vwap_branch_time_rank", TsRank, vwap_delta_decay, period=15.3012
        )
        self._result_lines = per_asset(
            self, "branch_difference", Subtract, low_time_rank, vwap_branch_time_rank
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
