"""Native Alpha101 factor implementation for Alpha063."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
    Delta,
    IndNeutralize,
    Multiply,
    RollingCorrelation,
    RollingSum,
    Subtract,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha063Native(FactorIndicator):
    """AF46-063: industry-neutral delta versus long ADV correlation branch."""

    lines = ("factor",)
    alpha_id = 63
    case_id = "AF46-063"
    lookback_h = 238
    formula_fields = ("close", "vwap", "open", "dollar_volume", "adv180", "industry")
    required_fields = formula_fields
    formula = "((rank(decay_linear(delta(IndNeutralize(close, IndClass.industry), 2.25164), 8.22237)) - rank(decay_linear(correlation(((vwap * 0.318108) + (open * (1 - 0.318108))), sum(adv180, 37.2467), 13.557), 12.2883))) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        neutral_close = panel(
            self,
            "industry_neutral_close",
            IndNeutralize,
            self.field_lines("close"),
            level="industry",
            groups=self.field_lines("industry"),
        )
        close_delta = per_asset(self, "neutral_close_delta2", Delta, neutral_close, period=2.25164)
        left_decay = per_asset(self, "left_decay8", DecayLinear, close_delta, period=8.22237)
        left_rank = panel(self, "left_rank", CrossSectionalRank, left_decay)
        weight = 0.318108
        weighted_vwap = per_asset(
            self, "weighted_vwap", Multiply, self.field_lines("vwap"), (weight,) * len(self.datas)
        )
        weighted_open = per_asset(
            self,
            "weighted_open",
            Multiply,
            self.field_lines("open"),
            (1.0 - weight,) * len(self.datas),
        )
        price_mix = per_asset(self, "weighted_price", Add, weighted_vwap, weighted_open)
        adv180 = self.field_lines("adv180")
        adv_sum = per_asset(self, "adv180_sum37", RollingSum, adv180, period=37.2467)
        correlation = per_asset(
            self, "correlation13", RollingCorrelation, price_mix, adv_sum, period=13.557
        )
        right_decay = per_asset(self, "right_decay12", DecayLinear, correlation, period=12.2883)
        right_rank = panel(self, "right_rank", CrossSectionalRank, right_decay)
        difference = per_asset(self, "rank_difference", Subtract, left_rank, right_rank)
        self._result_lines = per_asset(
            self, "negate_difference", Multiply, difference, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha063Build(FactorIndicator):
    """AF48-063: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha063Native.alpha_id
    case_id = Alpha063Native.case_id
    lookback_h = Alpha063Native.lookback_h
    formula_fields = Alpha063Native.formula_fields
    required_fields = Alpha063Native.required_fields
    formula = Alpha063Native.formula
    operator_profile = Alpha063Native.operator_profile
    input_policy = Alpha063Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        neutral_close = ctx.indneutralize(
            ctx.field("close"), ctx.field("industry"), level="industry"
        )
        close_delta = ctx.delta(neutral_close, 2.25164)
        left_decay = ctx.decay_linear(close_delta, 8.22237)
        left_rank = ctx.rank(left_decay)
        weight = 0.318108
        weighted_vwap = ctx.field("vwap") * weight
        weighted_open = ctx.field("open") * (1.0 - weight)
        price_mix = weighted_vwap + weighted_open
        adv180 = ctx.field("adv180")
        adv_sum = ctx.sum(adv180, 37.2467)
        correlation = ctx.correlation(price_mix, adv_sum, 13.557)
        right_decay = ctx.decay_linear(correlation, 12.2883)
        right_rank = ctx.rank(right_decay)
        difference = left_rank - right_rank
        factor = difference * -1.0
        return factor
