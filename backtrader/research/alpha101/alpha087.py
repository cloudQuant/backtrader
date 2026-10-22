"""Native Alpha101 factor implementation for Alpha087."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Abs,
    Add,
    CrossSectionalRank,
    DecayLinear,
    Delta,
    IndNeutralize,
    Maximum,
    Multiply,
    RollingCorrelation,
    Subtract,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha087Native(FactorIndicator):
    """Alpha #87: maximum of a weighted-price rank and industry-neutral branch."""

    lines = ("factor",)
    alpha_id = 87
    case_id = "AF46-087"
    lookback_h = 108
    formula = "(max(rank(decay_linear(delta(((close * 0.369701) + (vwap * (1 - 0.369701))), 1.91233), 2.65461)), Ts_Rank(decay_linear(abs(correlation(IndNeutralize(adv81, IndClass.industry), close, 13.4132)), 4.89768), 14.4535)) * -1)"
    formula_fields = ("close", "vwap", "dollar_volume", "adv81", "industry")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        alpha = 0.369701
        one_minus_alpha = per_asset(
            self, "one_minus_close_weight", Subtract, (1.0,) * count, (alpha,) * count
        )
        close_part = per_asset(
            self, "close_part", Multiply, self.field_lines("close"), (alpha,) * count
        )
        vwap_part = per_asset(
            self, "vwap_part", Multiply, self.field_lines("vwap"), one_minus_alpha
        )
        weighted_price = per_asset(self, "weighted_price", Add, close_part, vwap_part)
        price_change = per_asset(
            self, "weighted_price_delta", Delta, weighted_price, period=1.91233
        )
        decayed_change = per_asset(
            self, "weighted_price_decay", DecayLinear, price_change, period=2.65461
        )
        ranked_change = panel(self, "rank_weighted_price_decay", CrossSectionalRank, decayed_change)
        neutral_adv81 = panel(
            self,
            "industry_neutral_adv81",
            IndNeutralize,
            self.field_lines("adv81"),
            level="industry",
            groups=self.field_lines("industry"),
        )
        correlation = per_asset(
            self,
            "neutral_adv_close_correlation",
            RollingCorrelation,
            neutral_adv81,
            self.field_lines("close"),
            period=13.4132,
        )
        absolute_correlation = per_asset(
            self, "absolute_neutral_adv_close_correlation", Abs, correlation
        )
        correlation_decay = per_asset(
            self, "correlation_decay4", DecayLinear, absolute_correlation, period=4.89768
        )
        correlation_time_rank = per_asset(
            self, "correlation_time_rank14", TsRank, correlation_decay, period=14.4535
        )
        maximum = per_asset(
            self, "maximum_of_ranked_branches", Maximum, ranked_change, correlation_time_rank
        )
        self._result_lines = per_asset(self, "negative_maximum", Multiply, maximum, (-1.0,) * count)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
