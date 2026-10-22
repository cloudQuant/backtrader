"""Native Alpha101 factor implementation for Alpha059."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    DecayLinear,
    IndNeutralize,
    Multiply,
    RollingCorrelation,
    Subtract,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha059Native(FactorIndicator):
    """Alpha#59: industry-neutral VWAP correlation with decay and time rank."""

    lines = ("factor",)
    alpha_id = 59
    case_id = "AF46-059"
    lookback_h = 25
    formula = "(-1 * Ts_Rank(decay_linear(correlation(IndNeutralize(((vwap * 0.728317) + (vwap * (1 - 0.728317))), IndClass.industry), volume, 4.25197), 16.2289), 8.19648))"
    formula_fields = ("vwap", "volume", "industry")
    required_fields = formula_fields

    def __init__(self):
        super().__init__()
        self._nodes = {}
        vwap = self.field_lines("vwap")
        weighted_first = per_asset(
            self, "vwap_weighted_0728317", Multiply, vwap, (0.728317,) * len(self.datas)
        )
        complement = per_asset(
            self,
            "weight_complement",
            Subtract,
            (1.0,) * len(self.datas),
            (0.728317,) * len(self.datas),
        )
        weighted_second = per_asset(self, "vwap_weighted_complement", Multiply, vwap, complement)
        weighted_vwap = per_asset(self, "weighted_vwap_sum", Add, weighted_first, weighted_second)
        neutral_vwap = panel(
            self,
            "industry_neutral_vwap",
            IndNeutralize,
            weighted_vwap,
            level="industry",
            groups=self.field_lines("industry"),
        )
        correlation = per_asset(
            self,
            "neutral_vwap_volume_corr",
            RollingCorrelation,
            neutral_vwap,
            self.field_lines("volume"),
            period=4.25197,
        )
        decay = per_asset(self, "correlation_decay", DecayLinear, correlation, period=16.2289)
        time_rank = per_asset(self, "decay_ts_rank", TsRank, decay, period=8.19648)
        self._result_lines = per_asset(
            self, "negative_ts_rank", Multiply, time_rank, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]


@native_alpha
class Alpha059Build(FactorIndicator):
    """AF48-059: construct the native Alpha101 graph via expressions."""

    lines = ("factor",)
    panel_mode = "expression"
    alpha_id = Alpha059Native.alpha_id
    case_id = Alpha059Native.case_id
    lookback_h = Alpha059Native.lookback_h
    formula_fields = Alpha059Native.formula_fields
    required_fields = Alpha059Native.required_fields
    formula = Alpha059Native.formula
    operator_profile = Alpha059Native.operator_profile
    input_policy = Alpha059Native.input_policy

    @classmethod
    def build(cls, ctx, **params):
        vwap = ctx.field("vwap")
        weighted_first = vwap * 0.728317
        complement = ctx.subtract(1.0, 0.728317)
        weighted_second = vwap * complement
        weighted_vwap = weighted_first + weighted_second
        neutral_vwap = ctx.indneutralize(weighted_vwap, ctx.field("industry"), level="industry")
        correlation = ctx.correlation(neutral_vwap, ctx.field("volume"), 4.25197)
        decay = ctx.decay_linear(correlation, 16.2289)
        time_rank = ctx.ts_rank(decay, 8.19648)
        factor = time_rank * -1.0
        return factor
