"""Native Alpha101 factor implementation for Alpha069."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Delta,
    IndNeutralize,
    Multiply,
    Power,
    RollingCorrelation,
    TsMax,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha069Native(FactorIndicator):
    """Native implementation of Alpha069."""

    lines = ("factor",)
    alpha_id = 69
    case_id = "AF46-069"
    lookback_h = 30
    formula_fields = ("vwap", "close", "dollar_volume", "adv20", "industry")
    required_fields = formula_fields
    formula = "((rank(ts_max(delta(IndNeutralize(vwap, IndClass.industry), 2.72412), 4.79344))^Ts_Rank(correlation(((close * 0.490655) + (vwap * (1 - 0.490655))), adv20, 4.92416), 9.0615)) * -1)"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        neutral_vwap = panel(
            self,
            "industry_neutral_vwap",
            IndNeutralize,
            self.field_lines("vwap"),
            level="industry",
            groups=self.field_lines("industry"),
        )
        neutral_delta = per_asset(self, "neutral_vwap_delta2", Delta, neutral_vwap, period=2.72412)
        neutral_max = per_asset(self, "neutral_vwap_ts_max4", TsMax, neutral_delta, period=4.79344)
        base = panel(self, "neutral_vwap_max_rank", CrossSectionalRank, neutral_max)
        weight = 0.490655
        close_part = per_asset(
            self, "weighted_close", Multiply, self.field_lines("close"), (weight,) * len(self.datas)
        )
        vwap_part = per_asset(
            self,
            "weighted_vwap",
            Multiply,
            self.field_lines("vwap"),
            (1.0 - weight,) * len(self.datas),
        )
        adv_correlation = per_asset(
            self,
            "weighted_price_adv20_corr4",
            RollingCorrelation,
            per_asset(self, "weighted_price", Add, close_part, vwap_part),
            self.field_lines("adv20"),
            period=4.92416,
        )
        exponent = per_asset(self, "correlation_ts_rank9", TsRank, adv_correlation, period=9.0615)
        powered = per_asset(self, "ordinary_power", Power, base, exponent)
        self._result_lines = per_asset(
            self, "negative_power", Multiply, powered, (-1.0,) * len(self.datas)
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
