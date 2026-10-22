"""Native Alpha101 factor implementation for Alpha094."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Multiply,
    Power,
    RollingCorrelation,
    Subtract,
    TsMin,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha094Native(FactorIndicator):
    """Alpha #94: ordinary power of VWAP range rank and a ranked TS branch."""

    lines = ("factor",)
    alpha_id = 94
    case_id = "AF46-094"
    lookback_h = 80
    formula = "((rank((vwap - ts_min(vwap, 11.5783)))^Ts_Rank(correlation(Ts_Rank(vwap, 19.6462), Ts_Rank(adv60, 4.02992), 18.0926), 2.70756)) * -1)"
    formula_fields = ("vwap", "dollar_volume", "adv60")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        vwap_minimum = per_asset(
            self, "vwap_ts_min11", TsMin, self.field_lines("vwap"), period=11.5783
        )
        vwap_minus_minimum = per_asset(
            self, "vwap_minus_ts_min", Subtract, self.field_lines("vwap"), vwap_minimum
        )
        ranked_vwap_gap = panel(self, "rank_vwap_gap", CrossSectionalRank, vwap_minus_minimum)
        vwap_time_rank = per_asset(
            self, "vwap_time_rank19", TsRank, self.field_lines("vwap"), period=19.6462
        )
        adv60_time_rank = per_asset(
            self, "adv60_time_rank4", TsRank, self.field_lines("adv60"), period=4.02992
        )
        correlation = per_asset(
            self,
            "time_rank_correlation",
            RollingCorrelation,
            vwap_time_rank,
            adv60_time_rank,
            period=18.0926,
        )
        exponent = per_asset(self, "correlation_time_rank", TsRank, correlation, period=2.70756)
        powered = per_asset(self, "ordinary_power", Power, ranked_vwap_gap, exponent)
        self._result_lines = per_asset(self, "negative_power", Multiply, powered, (-1.0,) * count)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha094Build(FactorIndicator):
    """AF48-094: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha094Native.alpha_id
    case_id = Alpha094Native.case_id
    lookback_h = Alpha094Native.lookback_h
    formula_fields = Alpha094Native.formula_fields
    required_fields = Alpha094Native.required_fields
    formula = Alpha094Native.formula
    operator_profile = Alpha094Native.operator_profile
    input_policy = Alpha094Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        vwap_minimum = ctx.ts_min(ctx.field("vwap"), 11.5783)
        vwap_minus_minimum = ctx.field("vwap") - vwap_minimum
        ranked_vwap_gap = ctx.rank(vwap_minus_minimum)
        vwap_time_rank = ctx.ts_rank(ctx.field("vwap"), 19.6462)
        adv60_time_rank = ctx.ts_rank(ctx.field("adv60"), 4.02992)
        correlation = ctx.correlation(vwap_time_rank, adv60_time_rank, 18.0926)
        exponent = ctx.ts_rank(correlation, 2.70756)
        powered = ranked_vwap_gap**exponent
        factor = powered * (-1.0)
        return factor
