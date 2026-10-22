"""Native Alpha101 factor implementation for Alpha067."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    IndNeutralize,
    Multiply,
    Power,
    RollingCorrelation,
    Subtract,
    TsMin,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha067Native(FactorIndicator):
    """AF46-067: ordinary power of ranks, then negate (no outer rank)."""

    lines = ("factor",)
    alpha_id = 67
    case_id = "AF46-067"
    lookback_h = 24
    formula_fields = ("high", "vwap", "dollar_volume", "adv20", "sector", "subindustry")
    required_fields = formula_fields
    formula = "((rank((high - ts_min(high, 2.14593)))^rank(correlation(IndNeutralize(vwap, IndClass.sector), IndNeutralize(adv20, IndClass.subindustry), 6.02936))) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        high_min = per_asset(self, "high_min2", TsMin, self.field_lines("high"), period=2.14593)
        high_excess = per_asset(
            self, "high_minus_min", Subtract, self.field_lines("high"), high_min
        )
        base = panel(self, "rank_base", CrossSectionalRank, high_excess)
        sector_vwap = panel(
            self,
            "sector_neutral_vwap",
            IndNeutralize,
            self.field_lines("vwap"),
            level="sector",
            groups=self.field_lines("sector"),
        )
        adv20 = self.field_lines("adv20")
        subindustry_adv = panel(
            self,
            "subindustry_neutral_adv20",
            IndNeutralize,
            adv20,
            level="subindustry",
            groups=self.field_lines("subindustry"),
        )
        exponent_correlation = per_asset(
            self,
            "exponent_correlation6",
            RollingCorrelation,
            sector_vwap,
            subindustry_adv,
            period=6.02936,
        )
        exponent = panel(self, "rank_exponent", CrossSectionalRank, exponent_correlation)
        powered = per_asset(self, "ordinary_power", Power, base, exponent)
        self._result_lines = per_asset(self, "negate", Multiply, powered, (-1.0,) * len(self.datas))
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha067Build(FactorIndicator):
    """AF48-067: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha067Native.alpha_id
    case_id = Alpha067Native.case_id
    lookback_h = Alpha067Native.lookback_h
    formula_fields = Alpha067Native.formula_fields
    required_fields = Alpha067Native.required_fields
    formula = Alpha067Native.formula
    operator_profile = Alpha067Native.operator_profile
    input_policy = Alpha067Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        high_min = ctx.ts_min(ctx.field("high"), 2.14593)
        high_excess = ctx.field("high") - high_min
        base = ctx.rank(high_excess)
        sector_vwap = ctx.indneutralize(ctx.field("vwap"), ctx.field("sector"), level="sector")
        adv20 = ctx.field("adv20")
        subindustry_adv = ctx.indneutralize(adv20, ctx.field("subindustry"), level="subindustry")
        exponent_correlation = ctx.correlation(sector_vwap, subindustry_adv, 6.02936)
        exponent = ctx.rank(exponent_correlation)
        powered = base**exponent
        factor = powered * -1.0
        return factor
