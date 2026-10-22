"""Native Alpha101 factor implementation for Alpha082."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
    Delta,
    IndNeutralize,
    Minimum,
    Multiply,
    RollingCorrelation,
    Subtract,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha082Native(FactorIndicator):
    """Alpha #82: pointwise minimum of a ranked open change and sector branch."""

    lines = ("factor",)
    alpha_id = 82
    case_id = "AF46-082"
    lookback_h = 33
    formula = "(min(rank(decay_linear(delta(open, 1.46063), 14.8717)), Ts_Rank(decay_linear(correlation(IndNeutralize(volume, IndClass.sector), ((open * 0.634196) + (open * (1 - 0.634196))), 17.4842), 6.92131), 13.4283)) * -1)"
    formula_fields = ("open", "volume", "sector")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        open_delta = per_asset(self, "open_delta", Delta, self.field_lines("open"), period=1.46063)
        open_decay = per_asset(self, "open_decay14", DecayLinear, open_delta, period=14.8717)
        ranked_open_decay = panel(self, "rank_open_decay", CrossSectionalRank, open_decay)
        alpha = per_asset(
            self, "open_weight_a", Multiply, self.field_lines("open"), (0.634196,) * count
        )
        one_minus_alpha = per_asset(
            self, "one_minus_open_weight", Subtract, (1.0,) * count, (0.634196,) * count
        )
        beta = per_asset(self, "open_weight_b", Multiply, self.field_lines("open"), one_minus_alpha)
        weighted_open = per_asset(self, "weighted_open", Add, alpha, beta)
        neutral_volume = panel(
            self, "sector_neutral_volume", IndNeutralize, self.field_lines("volume"), level="sector", groups=self.field_lines("sector")
        )
        correlation = per_asset(
            self,
            "volume_open_correlation",
            RollingCorrelation,
            neutral_volume,
            weighted_open,
            period=17.4842,
        )
        correlation_decay = per_asset(
            self, "correlation_decay6", DecayLinear, correlation, period=6.92131
        )
        correlation_time_rank = per_asset(
            self, "correlation_time_rank13", TsRank, correlation_decay, period=13.4283
        )
        minimum = per_asset(
            self, "minimum_of_ranked_branches", Minimum, ranked_open_decay, correlation_time_rank
        )
        self._result_lines = per_asset(self, "negative_minimum", Multiply, minimum, (-1.0,) * count)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
