"""Native Alpha101 factor implementation for Alpha070."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    Delta,
    IndNeutralize,
    Multiply,
    Power,
    RollingCorrelation,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha070Native(FactorIndicator):
    """Native implementation of Alpha070."""

    lines = ("factor",)
    alpha_id = 70
    case_id = "AF46-070"
    lookback_h = 81
    formula_fields = ("vwap", "close", "dollar_volume", "adv50", "industry")
    required_fields = formula_fields
    formula = "((rank(delta(vwap, 1.29456))^Ts_Rank(correlation(IndNeutralize(close, IndClass.industry), adv50, 17.8256), 17.9171)) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        vwap_delta = per_asset(self, "vwap_delta1", Delta, self.field_lines("vwap"), period=1.29456)
        base = panel(self, "vwap_delta_rank", CrossSectionalRank, vwap_delta)
        neutral_close = panel(
            self,
            "industry_neutral_close",
            IndNeutralize,
            self.field_lines("close"),
            level="industry",
            groups=self.field_lines("industry"),
        )
        correlation = per_asset(
            self,
            "neutral_close_adv50_corr17",
            RollingCorrelation,
            neutral_close,
            self.field_lines("adv50"),
            period=17.8256,
        )
        exponent = per_asset(self, "correlation_ts_rank17", TsRank, correlation, period=17.9171)
        powered = per_asset(self, "ordinary_power", Power, base, exponent)
        self._result_lines = per_asset(
            self, "negative_power", Multiply, powered, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
