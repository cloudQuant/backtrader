"""Native Alpha101 factor implementation for Alpha097."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
    Delta,
    IndNeutralize,
    Multiply,
    RollingCorrelation,
    Subtract,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha097Native(FactorIndicator):
    """Alpha #97: ranked industry-neutral delta minus a nested TS-rank branch."""

    lines = ("factor",)
    alpha_id = 97
    case_id = "AF46-097"
    lookback_h = 114
    formula = "((rank(decay_linear(delta(IndNeutralize(((low * 0.721001) + (vwap * (1 - 0.721001))), IndClass.industry), 3.3705), 20.4523)) - Ts_Rank(decay_linear(Ts_Rank(correlation(Ts_Rank(low, 7.87871), Ts_Rank(adv60, 17.255), 4.97547), 18.5925), 15.7152), 6.71659)) * -1)"
    formula_fields = ("low", "vwap", "dollar_volume", "adv60", "industry")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        alpha = 0.721001
        one_minus_alpha = per_asset(
            self, "one_minus_low_weight", Subtract, (1.0,) * count, (alpha,) * count
        )
        low_part = per_asset(self, "low_part", Multiply, self.field_lines("low"), (alpha,) * count)
        vwap_part = per_asset(
            self, "vwap_part", Multiply, self.field_lines("vwap"), one_minus_alpha
        )
        weighted_price = per_asset(self, "weighted_price", Add, low_part, vwap_part)
        neutral_price = panel(
            self, "industry_neutral_weighted_price", IndNeutralize, weighted_price, level="industry", groups=self.field_lines("industry")
        )
        price_delta = per_asset(self, "neutral_price_delta", Delta, neutral_price, period=3.3705)
        price_decay = per_asset(
            self, "neutral_price_delta_decay", DecayLinear, price_delta, period=20.4523
        )
        ranked_price_decay = panel(
            self, "rank_neutral_price_decay", CrossSectionalRank, price_decay
        )
        low_time_rank = per_asset(
            self, "low_time_rank7", TsRank, self.field_lines("low"), period=7.87871
        )
        adv60_time_rank = per_asset(
            self, "adv60_time_rank17", TsRank, self.field_lines("adv60"), period=17.255
        )
        correlation = per_asset(
            self,
            "ranked_series_correlation",
            RollingCorrelation,
            low_time_rank,
            adv60_time_rank,
            period=4.97547,
        )
        correlation_time_rank = per_asset(
            self, "correlation_time_rank18", TsRank, correlation, period=18.5925
        )
        correlation_decay = per_asset(
            self,
            "correlation_time_rank_decay15",
            DecayLinear,
            correlation_time_rank,
            period=15.7152,
        )
        nested_time_rank = per_asset(
            self, "nested_time_rank6", TsRank, correlation_decay, period=6.71659
        )
        difference = per_asset(
            self,
            "ranked_price_minus_nested_time_rank",
            Subtract,
            ranked_price_decay,
            nested_time_rank,
        )
        self._result_lines = per_asset(
            self, "negative_difference", Multiply, difference, (-1.0,) * count
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
