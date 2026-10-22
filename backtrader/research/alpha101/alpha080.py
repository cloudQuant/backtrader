"""Native Alpha101 factor implementation for Alpha080."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Delta,
    IndNeutralize,
    Multiply,
    Power,
    RollingCorrelation,
    Sign,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha080Native(FactorIndicator):
    """Native implementation of Alpha080."""

    lines = ("factor",)
    alpha_id = 80
    case_id = "AF46-080"
    lookback_h = 17
    formula_fields = ("open", "high", "dollar_volume", "adv10", "industry")
    required_fields = formula_fields
    formula = "((rank(Sign(delta(IndNeutralize(((open * 0.868128) + (high * (1 - 0.868128))), IndClass.industry), 4.04545)))^Ts_Rank(correlation(high, adv10, 5.11456), 5.53756)) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        weight = 0.868128
        open_part = per_asset(
            self, "weighted_open", Multiply, self.field_lines("open"), (weight,) * len(self.datas)
        )
        high_part = per_asset(
            self,
            "weighted_high",
            Multiply,
            self.field_lines("high"),
            (1.0 - weight,) * len(self.datas),
        )
        neutral_price = panel(
            self,
            "industry_neutral_price",
            IndNeutralize,
            per_asset(self, "weighted_price", Add, open_part, high_part),
            level="industry",
            groups=self.field_lines("industry"),
        )
        delta = per_asset(self, "neutral_price_delta4", Delta, neutral_price, period=4.04545)
        signed = per_asset(self, "sign_delta", Sign, delta)
        base = panel(self, "sign_delta_rank", CrossSectionalRank, signed)
        correlation = per_asset(
            self,
            "high_adv10_corr5",
            RollingCorrelation,
            self.field_lines("high"),
            self.field_lines("adv10"),
            period=5.11456,
        )
        exponent = per_asset(self, "correlation_ts_rank5", TsRank, correlation, period=5.53756)
        powered = per_asset(self, "ordinary_power", Power, base, exponent)
        self._result_lines = per_asset(
            self, "negative_power", Multiply, powered, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha080Build(FactorIndicator):
    """AF48-080: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha080Native.alpha_id
    case_id = Alpha080Native.case_id
    lookback_h = Alpha080Native.lookback_h
    formula_fields = Alpha080Native.formula_fields
    required_fields = Alpha080Native.required_fields
    formula = Alpha080Native.formula
    operator_profile = Alpha080Native.operator_profile
    input_policy = Alpha080Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        weight = 0.868128
        open_part = ctx.field("open") * (weight)
        high_part = ctx.field("high") * (1.0 - weight)
        neutral_price = ctx.indneutralize(
            (open_part + high_part), ctx.field("industry"), level="industry"
        )
        delta = ctx.delta(neutral_price, 4.04545)
        signed = ctx.sign(delta)
        base = ctx.rank(signed)
        correlation = ctx.correlation(ctx.field("high"), ctx.field("adv10"), 5.11456)
        exponent = ctx.ts_rank(correlation, 5.53756)
        powered = base**exponent
        factor = powered * (-1.0)
        return factor
