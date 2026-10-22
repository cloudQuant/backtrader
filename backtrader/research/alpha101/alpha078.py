"""Native Alpha101 factor implementation for Alpha078."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Multiply,
    Power,
    RollingCorrelation,
    RollingSum,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha078Native(FactorIndicator):
    """Native implementation of Alpha078."""

    lines = ("factor",)
    alpha_id = 78
    case_id = "AF46-078"
    lookback_h = 62
    formula_fields = ("low", "vwap", "volume", "dollar_volume", "adv40")
    required_fields = formula_fields
    formula = "(rank(correlation(sum(((low * 0.352233) + (vwap * (1 - 0.352233))), 19.7428), sum(adv40, 19.7428), 6.83313))^rank(correlation(rank(vwap), rank(volume), 5.77492)))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        weight = 0.352233
        low_part = per_asset(
            self, "weighted_low", Multiply, self.field_lines("low"), (weight,) * len(self.datas)
        )
        vwap_part = per_asset(
            self,
            "weighted_vwap",
            Multiply,
            self.field_lines("vwap"),
            (1.0 - weight,) * len(self.datas),
        )
        price_sum = per_asset(
            self,
            "weighted_price_sum19",
            RollingSum,
            per_asset(self, "weighted_price", Add, low_part, vwap_part),
            period=19.7428,
        )
        adv_sum = per_asset(
            self, "adv40_sum19", RollingSum, self.field_lines("adv40"), period=19.7428
        )
        left_correlation = per_asset(
            self, "price_adv_sum_corr6", RollingCorrelation, price_sum, adv_sum, period=6.83313
        )
        base = panel(self, "price_adv_sum_corr_rank", CrossSectionalRank, left_correlation)
        vwap_rank = panel(self, "vwap_rank", CrossSectionalRank, self.field_lines("vwap"))
        volume_rank = panel(self, "volume_rank", CrossSectionalRank, self.field_lines("volume"))
        right_correlation = per_asset(
            self,
            "rank_vwap_volume_corr5",
            RollingCorrelation,
            vwap_rank,
            volume_rank,
            period=5.77492,
        )
        exponent = panel(self, "rank_correlation_rank", CrossSectionalRank, right_correlation)
        self._result_lines = per_asset(self, "ordinary_power", Power, base, exponent)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
