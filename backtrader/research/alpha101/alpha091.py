"""Native Alpha101 factor implementation for Alpha091."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    DecayLinear,
    IndNeutralize,
    Multiply,
    RollingCorrelation,
    Subtract,
    TsRank,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha091Native(FactorIndicator):
    """Alpha #91: difference of two branches with industry-neutral close history."""

    lines = ("factor",)
    alpha_id = 91
    case_id = "AF46-091"
    lookback_h = 33
    formula = "((Ts_Rank(decay_linear(decay_linear(correlation(IndNeutralize(close, IndClass.industry), volume, 9.74928), 16.398), 3.83219), 4.8667) - rank(decay_linear(correlation(vwap, adv30, 4.01303), 2.6809))) * -1)"
    formula_fields = ("close", "volume", "vwap", "dollar_volume", "adv30")
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ("industry",)

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        neutral_close = panel(
            self,
            "industry_neutral_close",
            IndNeutralize,
            self.field_lines("close"),
            level="industry",
        )
        close_volume_correlation = per_asset(
            self,
            "neutral_close_volume_correlation",
            RollingCorrelation,
            neutral_close,
            self.field_lines("volume"),
            period=9.74928,
        )
        first_decay = per_asset(
            self,
            "neutral_correlation_decay16",
            DecayLinear,
            close_volume_correlation,
            period=16.398,
        )
        second_decay = per_asset(
            self, "neutral_correlation_decay3", DecayLinear, first_decay, period=3.83219
        )
        first_branch = per_asset(
            self, "first_branch_time_rank", TsRank, second_decay, period=4.8667
        )
        vwap_adv_correlation = per_asset(
            self,
            "vwap_adv30_correlation",
            RollingCorrelation,
            self.field_lines("vwap"),
            self.field_lines("adv30"),
            period=4.01303,
        )
        vwap_adv_decay = per_asset(
            self, "vwap_adv_correlation_decay", DecayLinear, vwap_adv_correlation, period=2.6809
        )
        second_branch = panel(self, "rank_vwap_adv_decay", CrossSectionalRank, vwap_adv_decay)
        difference = per_asset(self, "branch_difference", Subtract, first_branch, second_branch)
        self._result_lines = per_asset(
            self, "negative_difference", Multiply, difference, (-1.0,) * count
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
