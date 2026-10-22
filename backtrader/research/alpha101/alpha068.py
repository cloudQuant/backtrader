"""Native Alpha101 factor implementation for Alpha068."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Delta,
    LessThan,
    Multiply,
    RollingCorrelation,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha068Native(FactorIndicator):
    """Native implementation of Alpha068."""

    lines = ("factor",)
    alpha_id = 68
    case_id = "AF46-068"
    lookback_h = 33
    formula_fields = ("high", "close", "low", "dollar_volume", "adv15")
    required_fields = formula_fields
    formula = "((Ts_Rank(correlation(rank(high), rank(adv15), 8.91644), 13.9333) < rank(delta(((close * 0.518371) + (low * (1 - 0.518371))), 1.06157))) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        high_rank = panel(self, "high_rank", CrossSectionalRank, self.field_lines("high"))
        adv_rank = panel(self, "adv15_rank", CrossSectionalRank, self.field_lines("adv15"))
        correlation = per_asset(
            self, "rank_correlation8", RollingCorrelation, high_rank, adv_rank, period=8.91644
        )
        left = per_asset(self, "correlation_ts_rank13", TsRank, correlation, period=13.9333)
        weight = 0.518371
        close_part = per_asset(
            self, "weighted_close", Multiply, self.field_lines("close"), (weight,) * len(self.datas)
        )
        low_part = per_asset(
            self,
            "weighted_low",
            Multiply,
            self.field_lines("low"),
            (1.0 - weight,) * len(self.datas),
        )
        price_delta = per_asset(
            self,
            "weighted_price_delta1",
            Delta,
            per_asset(self, "weighted_price", Add, close_part, low_part),
            period=1.06157,
        )
        right = panel(self, "weighted_price_delta_rank", CrossSectionalRank, price_delta)
        comparison = per_asset(self, "ts_rank_less_than_rank", LessThan, left, right)
        self._result_lines = per_asset(
            self, "negative_boolean", Multiply, comparison, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha068Build(FactorIndicator):
    """AF48-068: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha068Native.alpha_id
    case_id = Alpha068Native.case_id
    lookback_h = Alpha068Native.lookback_h
    formula_fields = Alpha068Native.formula_fields
    required_fields = Alpha068Native.required_fields
    formula = Alpha068Native.formula
    operator_profile = Alpha068Native.operator_profile
    input_policy = Alpha068Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        high_rank = ctx.rank(ctx.field("high"))
        adv_rank = ctx.rank(ctx.field("adv15"))
        correlation = ctx.correlation(high_rank, adv_rank, 8.91644)
        left = ctx.ts_rank(correlation, 13.9333)
        weight = 0.518371
        close_part = ctx.field("close") * weight
        low_part = ctx.field("low") * (1.0 - weight)
        price_delta = ctx.delta((close_part + low_part), 1.06157)
        right = ctx.rank(price_delta)
        comparison = ctx.less_than(left, right)
        factor = comparison * -1.0
        return factor
