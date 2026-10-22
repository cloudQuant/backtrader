"""Native Alpha101 factor implementation for Alpha090."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    IndNeutralize,
    Multiply,
    Power,
    RollingCorrelation,
    Subtract,
    TsMax,
    TsRank,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha090Native(FactorIndicator):
    """Alpha #90: ordinary power with a subindustry-neutral rolling-correlation exponent."""

    lines = ("factor",)
    alpha_id = 90
    case_id = "AF46-090"
    lookback_h = 45
    formula = "((rank((close - ts_max(close, 4.66719)))^Ts_Rank(correlation(IndNeutralize(adv40, IndClass.subindustry), low, 5.38375), 3.21856)) * -1)"
    formula_fields = ("close", "low", "dollar_volume", "adv40")
    required_fields = formula_fields
    classification_levels = ("subindustry",)
    classification_fields = ("subindustry",)

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        close_maximum = per_asset(
            self, "close_ts_max4", TsMax, self.field_lines("close"), period=4.66719
        )
        close_minus_maximum = per_asset(
            self, "close_minus_ts_max", Subtract, self.field_lines("close"), close_maximum
        )
        ranked_close_gap = panel(self, "rank_close_gap", CrossSectionalRank, close_minus_maximum)
        neutral_adv40 = panel(
            self,
            "subindustry_neutral_adv40",
            IndNeutralize,
            self.field_lines("adv40"),
            level="subindustry",
        )
        correlation = per_asset(
            self,
            "neutral_adv40_low_correlation",
            RollingCorrelation,
            neutral_adv40,
            self.field_lines("low"),
            period=5.38375,
        )
        exponent = per_asset(self, "correlation_time_rank", TsRank, correlation, period=3.21856)
        powered = per_asset(self, "ordinary_power", Power, ranked_close_gap, exponent)
        self._result_lines = per_asset(self, "negative_power", Multiply, powered, (-1.0,) * count)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
