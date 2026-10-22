"""Native Alpha101 factor implementation for Alpha100."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    CrossSectionalRank,
    CrossSectionalScale,
    Divide,
    IndNeutralize,
    Multiply,
    RollingCorrelation,
    Subtract,
    TsArgMin,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha100Native(FactorIndicator):
    """AF46-100: three ordered subindustry neutralizations and two scales."""

    lines = ("factor",)
    alpha_id = 100
    case_id = "AF46-100"
    lookback_h = 29
    formula_fields = ("close", "high", "low", "volume", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_levels = ("subindustry", "subindustry", "subindustry")
    classification_fields = ("subindustry",)
    formula = "(0 - (1 * (((1.5 * scale(indneutralize(indneutralize(rank(((((close - low) - (high - close)) / (high - low)) * volume)), IndClass.subindustry), IndClass.subindustry))) - scale(indneutralize((correlation(close, rank(adv20), 5) - rank(ts_argmin(close, 30))), IndClass.subindustry))) * (volume / adv20))))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        close = self.field_lines("close")
        low = self.field_lines("low")
        high = self.field_lines("high")
        numerator_left = per_asset(self, "close_minus_low", Subtract, close, low)
        numerator_right = per_asset(self, "high_minus_close", Subtract, high, close)
        numerator = per_asset(
            self, "range_position_numerator", Subtract, numerator_left, numerator_right
        )
        denominator = per_asset(self, "high_minus_low", Subtract, high, low)
        location = per_asset(self, "range_position", Divide, numerator, denominator)
        volume_weighted = per_asset(
            self, "range_times_volume", Multiply, location, self.field_lines("volume")
        )
        ranked_weighted = panel(self, "rank_range_volume", CrossSectionalRank, volume_weighted)
        neutralized_once = panel(
            self,
            "first_subindustry_neutralize",
            IndNeutralize,
            ranked_weighted,
            level="subindustry",
            groups=self.classification_lines("subindustry"),
        )
        neutralized_twice = panel(
            self,
            "second_subindustry_neutralize",
            IndNeutralize,
            neutralized_once,
            level="subindustry",
            groups=self.classification_lines("subindustry"),
        )
        first_scale = panel(self, "first_scale", CrossSectionalScale, neutralized_twice)
        first_scaled = per_asset(
            self, "scale_times_1_5", Multiply, first_scale, (1.5,) * len(self.datas)
        )
        adv20 = self.field_lines("adv20")
        adv_rank = panel(self, "rank_adv20", CrossSectionalRank, adv20)
        correlation = per_asset(
            self, "close_adv_correlation5", RollingCorrelation, close, adv_rank, period=5
        )
        close_argmin = per_asset(self, "close_argmin30", TsArgMin, close, period=30)
        argmin_rank = panel(self, "rank_close_argmin", CrossSectionalRank, close_argmin)
        correlation_minus_rank = per_asset(
            self, "correlation_minus_argmin_rank", Subtract, correlation, argmin_rank
        )
        second_neutralized = panel(
            self,
            "third_subindustry_neutralize",
            IndNeutralize,
            correlation_minus_rank,
            level="subindustry",
            groups=self.classification_lines("subindustry"),
        )
        second_scale = panel(self, "second_scale", CrossSectionalScale, second_neutralized)
        scale_difference = per_asset(
            self, "scaled_difference", Subtract, first_scaled, second_scale
        )
        volume_adv = per_asset(self, "volume_over_adv20", Divide, self.field_lines("volume"), adv20)
        weighted_difference = per_asset(
            self, "volume_weighted_difference", Multiply, scale_difference, volume_adv
        )
        times_one = per_asset(
            self, "times_one", Multiply, weighted_difference, (1.0,) * len(self.datas)
        )
        self._result_lines = per_asset(
            self, "zero_minus", Subtract, (0.0,) * len(self.datas), times_one
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
