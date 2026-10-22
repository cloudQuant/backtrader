"""Native Alpha101 factor implementation for Alpha058."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    DecayLinear,
    IndNeutralize,
    Multiply,
    RollingCorrelation,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha058Native(FactorIndicator):
    """AF46-058: sector-neutral VWAP correlation, decay and time rank."""

    lines = ("factor",)
    alpha_id = 58
    case_id = "AF46-058"
    lookback_h = 12
    formula_fields = ("vwap", "volume", "sector")
    required_fields = formula_fields
    formula = "(-1 * Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, IndClass.sector), volume, 3.92795), 7.89291), 5.50322))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        neutral_vwap = panel(
            self,
            "sector_neutral_vwap",
            IndNeutralize,
            self.field_lines("vwap"),
            level="sector",
            groups=self.field_lines("sector"),
        )
        correlation = per_asset(
            self,
            "correlation3",
            RollingCorrelation,
            neutral_vwap,
            self.field_lines("volume"),
            period=3.92795,
        )
        decay = per_asset(self, "decay7", DecayLinear, correlation, period=7.89291)
        time_rank = per_asset(self, "ts_rank5", TsRank, decay, period=5.50322)
        self._result_lines = per_asset(
            self, "negate", Multiply, time_rank, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha058Build(FactorIndicator):
    """AF48-058: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha058Native.alpha_id
    case_id = Alpha058Native.case_id
    lookback_h = Alpha058Native.lookback_h
    formula_fields = Alpha058Native.formula_fields
    required_fields = Alpha058Native.required_fields
    formula = Alpha058Native.formula
    operator_profile = Alpha058Native.operator_profile
    input_policy = Alpha058Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        neutral_vwap = ctx.indneutralize(ctx.field("vwap"), ctx.field("sector"), level="sector")
        correlation = ctx.correlation(neutral_vwap, ctx.field("volume"), 3.92795)
        decay = ctx.decay_linear(correlation, 7.89291)
        time_rank = ctx.ts_rank(decay, 5.50322)
        factor = time_rank * -1.0
        return factor
