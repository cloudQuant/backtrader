"""Native Alpha101 factor implementation for Alpha093."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
    Delta,
    Divide,
    IndNeutralize,
    Multiply,
    RollingCorrelation,
    Subtract,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha093Native(FactorIndicator):
    """Alpha #93: industry-neutral VWAP/ADV history divided by a ranked price branch."""

    lines = ("factor",)
    alpha_id = 93
    case_id = "AF46-093"
    lookback_h = 120
    formula = "(Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, IndClass.industry), adv81, 17.4193), 19.848), 7.54455) / rank(decay_linear(delta(((close * 0.524434) + (vwap * (1 - 0.524434))), 2.77377), 16.2664)))"
    formula_fields = ("vwap", "close", "dollar_volume", "adv81", "industry")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        neutral_vwap = panel(
            self, "industry_neutral_vwap", IndNeutralize, self.field_lines("vwap"), level="industry", groups=self.field_lines("industry")
        )
        vwap_adv_correlation = per_asset(
            self,
            "neutral_vwap_adv81_correlation",
            RollingCorrelation,
            neutral_vwap,
            self.field_lines("adv81"),
            period=17.4193,
        )
        correlation_decay = per_asset(
            self, "neutral_correlation_decay19", DecayLinear, vwap_adv_correlation, period=19.848
        )
        numerator = per_asset(
            self, "numerator_time_rank", TsRank, correlation_decay, period=7.54455
        )
        alpha = 0.524434
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
        price_delta = per_asset(self, "weighted_price_delta", Delta, weighted_price, period=2.77377)
        price_delta_decay = per_asset(
            self, "weighted_price_delta_decay", DecayLinear, price_delta, period=16.2664
        )
        denominator = panel(
            self, "rank_weighted_price_delta_decay", CrossSectionalRank, price_delta_decay
        )
        self._result_lines = per_asset(self, "factor", Divide, numerator, denominator)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    @classmethod
    def build(cls, ctx, **params):
        neutral_vwap = ctx.indneutralize(ctx.field("vwap"), ctx.field("industry"), level="industry")
        vwap_adv_correlation = ctx.correlation(neutral_vwap, ctx.field("adv81"), 17.4193)
        correlation_decay = ctx.decay_linear(vwap_adv_correlation, 19.848)
        numerator = ctx.ts_rank(correlation_decay, 7.54455)
        alpha = 0.524434
        one_minus_alpha = ctx.subtract(1.0, alpha)
        close_part = ctx.field("close") * (alpha)
        vwap_part = ctx.field("vwap") * one_minus_alpha
        weighted_price = close_part + vwap_part
        price_delta = ctx.delta(weighted_price, 2.77377)
        price_delta_decay = ctx.decay_linear(price_delta, 16.2664)
        denominator = ctx.rank(price_delta_decay)
        factor = numerator / denominator
        return factor
