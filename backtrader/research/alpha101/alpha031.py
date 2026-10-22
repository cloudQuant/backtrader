"""Native Alpha101 factor implementation for Alpha031."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    CrossSectionalScale,
    DecayLinear,
    Delta,
    Multiply,
    RollingCorrelation,
    Sign,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha031Native(FactorIndicator):
    """AF46-031: nested rank/decay terms plus a scaled ADV/low correlation sign."""

    lines = ("factor",)
    alpha_id = 31
    case_id = "AF46-031"
    formula = (
        "((rank(rank(rank(decay_linear((-1 * rank(rank(delta(close, 10)))), 10)))) + "
        "rank((-1 * delta(close, 3)))) + sign(scale(correlation(adv20, low, 12))))"
    )
    lookback_h = 30
    formula_fields = ("close", "low", "dollar_volume", "adv20")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        close = self.field_lines("close")
        close_delta_10 = per_asset(self, "close_delta_10", Delta, close, period=10)
        ranked_delta_10 = panel(self, "rank_delta_10", CrossSectionalRank, close_delta_10)
        ranked_ranked_delta_10 = panel(
            self, "rank_rank_delta_10", CrossSectionalRank, ranked_delta_10
        )
        negative_ranked_ranked_delta = per_asset(
            self, "negative_rank_rank_delta_10", Multiply, (-1.0,) * count, ranked_ranked_delta_10
        )
        decayed = per_asset(
            self, "decay_rank_rank_delta_10", DecayLinear, negative_ranked_ranked_delta, period=10
        )
        ranked_decay_1 = panel(self, "rank_decay_1", CrossSectionalRank, decayed)
        ranked_decay_2 = panel(self, "rank_decay_2", CrossSectionalRank, ranked_decay_1)
        ranked_decay_3 = panel(self, "rank_decay_3", CrossSectionalRank, ranked_decay_2)
        close_delta_3 = per_asset(self, "close_delta_3", Delta, close, period=3)
        negative_close_delta_3 = per_asset(
            self, "negative_close_delta_3", Multiply, (-1.0,) * count, close_delta_3
        )
        ranked_negative_delta = panel(
            self, "rank_negative_delta_3", CrossSectionalRank, negative_close_delta_3
        )
        adv_low_correlation = per_asset(
            self,
            "adv20_low_correlation_12",
            RollingCorrelation,
            self.field_lines("adv20"),
            self.field_lines("low"),
            period=12,
        )
        scaled_correlation = panel(
            self, "scale_adv20_low_correlation", CrossSectionalScale, adv_low_correlation
        )
        correlation_sign = per_asset(self, "sign_scaled_correlation", Sign, scaled_correlation)
        first_two_terms = per_asset(
            self, "first_two_terms", Add, ranked_decay_3, ranked_negative_delta
        )
        self._result_lines = per_asset(self, "factor", Add, first_two_terms, correlation_sign)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha031Build(FactorIndicator):
    """AF48-031: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha031Native.alpha_id
    case_id = Alpha031Native.case_id
    lookback_h = Alpha031Native.lookback_h
    formula_fields = Alpha031Native.formula_fields
    required_fields = Alpha031Native.required_fields
    formula = Alpha031Native.formula
    operator_profile = Alpha031Native.operator_profile
    input_policy = Alpha031Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        close = ctx.field("close")
        close_delta_10 = ctx.delta(close, 10)
        ranked_delta_10 = ctx.rank(close_delta_10)
        ranked_ranked_delta_10 = ctx.rank(ranked_delta_10)
        negative_ranked_ranked_delta = -1.0 * ranked_ranked_delta_10
        decayed = ctx.decay_linear(negative_ranked_ranked_delta, 10)
        ranked_decay_1 = ctx.rank(decayed)
        ranked_decay_2 = ctx.rank(ranked_decay_1)
        ranked_decay_3 = ctx.rank(ranked_decay_2)
        close_delta_3 = ctx.delta(close, 3)
        negative_close_delta_3 = -1.0 * close_delta_3
        ranked_negative_delta = ctx.rank(negative_close_delta_3)
        adv_low_correlation = ctx.correlation(ctx.field("adv20"), ctx.field("low"), 12)
        scaled_correlation = ctx.scale(adv_low_correlation)
        correlation_sign = ctx.sign(scaled_correlation)
        first_two_terms = ranked_decay_3 + ranked_negative_delta
        factor = first_two_terms + correlation_sign
        return factor
