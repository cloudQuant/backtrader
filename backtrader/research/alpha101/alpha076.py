"""Native Alpha101 factor implementation for Alpha076."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    DecayLinear,
    Delta,
    IndNeutralize,
    Maximum,
    Multiply,
    RollingCorrelation,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha076Native(FactorIndicator):
    """Native implementation of Alpha076."""

    lines = ("factor",)
    alpha_id = 76
    case_id = "AF46-076"
    lookback_h = 139
    formula_fields = ("vwap", "low", "dollar_volume", "adv81", "sector")
    required_fields = formula_fields
    formula = "(max(rank(decay_linear(delta(vwap, 1.24383), 11.8259)), Ts_Rank(decay_linear(Ts_Rank(correlation(IndNeutralize(low, IndClass.sector), adv81, 8.14941), 19.569), 17.1543), 19.383)) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        vwap_delta = per_asset(self, "vwap_delta1", Delta, self.field_lines("vwap"), period=1.24383)
        vwap_decay = per_asset(self, "vwap_delta_decay11", DecayLinear, vwap_delta, period=11.8259)
        first = panel(self, "vwap_delta_decay_rank", CrossSectionalRank, vwap_decay)
        neutral_low = panel(
            self,
            "sector_neutral_low",
            IndNeutralize,
            self.field_lines("low"),
            level="sector",
            groups=self.field_lines("sector"),
        )
        correlation = per_asset(
            self,
            "neutral_low_adv81_corr8",
            RollingCorrelation,
            neutral_low,
            self.field_lines("adv81"),
            period=8.14941,
        )
        correlation_rank = per_asset(
            self, "correlation_ts_rank19", TsRank, correlation, period=19.569
        )
        correlation_decay = per_asset(
            self, "correlation_rank_decay17", DecayLinear, correlation_rank, period=17.1543
        )
        second = per_asset(
            self, "correlation_decay_ts_rank19", TsRank, correlation_decay, period=19.383
        )
        combined = per_asset(self, "pointwise_maximum", Maximum, first, second)
        self._result_lines = per_asset(
            self, "negative_maximum", Multiply, combined, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
