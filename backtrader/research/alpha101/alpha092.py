"""Native Alpha101 factor implementation for Alpha092."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
    Divide,
    LessThan,
    Minimum,
    RollingCorrelation,
    TsRank,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha092Native(FactorIndicator):
    """AF46-092: pointwise minimum of two independently ranked time branches."""

    lines = ("factor",)
    alpha_id = 92
    case_id = "AF46-092"
    lookback_h = 45
    formula_fields = ("open", "high", "low", "close", "dollar_volume", "adv30")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()
    formula = "min(Ts_Rank(decay_linear(((((high + low) / 2) + close) < (low + open)), 14.7221), 18.8683), Ts_Rank(decay_linear(correlation(rank(low), rank(adv30), 7.58555), 6.94024), 6.80584))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        high_low = per_asset(
            self, "high_plus_low", Add, self.field_lines("high"), self.field_lines("low")
        )
        midpoint = per_asset(self, "midpoint", Divide, high_low, (2.0,) * len(self.datas))
        midpoint_close = per_asset(
            self, "midpoint_plus_close", Add, midpoint, self.field_lines("close")
        )
        low_open = per_asset(
            self, "low_plus_open", Add, self.field_lines("low"), self.field_lines("open")
        )
        condition = per_asset(self, "midpoint_less_low_open", LessThan, midpoint_close, low_open)
        bool_decay = per_asset(self, "bool_decay14", DecayLinear, condition, period=14.7221)
        bool_rank = per_asset(self, "bool_ts_rank18", TsRank, bool_decay, period=18.8683)
        low_rank = panel(self, "rank_low", CrossSectionalRank, self.field_lines("low"))
        adv30 = self.field_lines("adv30")
        adv_rank = panel(self, "rank_adv30", CrossSectionalRank, adv30)
        correlation = per_asset(
            self, "correlation7", RollingCorrelation, low_rank, adv_rank, period=7.58555
        )
        correlation_decay = per_asset(
            self, "correlation_decay6", DecayLinear, correlation, period=6.94024
        )
        correlation_rank = per_asset(
            self, "correlation_ts_rank6", TsRank, correlation_decay, period=6.80584
        )
        self._result_lines = per_asset(
            self, "pointwise_minimum", Minimum, bool_rank, correlation_rank
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
