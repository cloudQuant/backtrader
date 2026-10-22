"""Native Alpha101 factor implementation for Alpha079."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    Delta,
    IndNeutralize,
    LessThan,
    Multiply,
    RollingCorrelation,
    TsRank,
)
from .._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha079Native(FactorIndicator):
    """Native implementation of Alpha079."""

    lines = ("factor",)
    alpha_id = 79
    case_id = "AF46-079"
    lookback_h = 170
    formula_fields = ("close", "open", "vwap", "dollar_volume", "adv150", "sector")
    required_fields = formula_fields
    formula = "(rank(delta(IndNeutralize(((close * 0.60733) + (open * (1 - 0.60733))), IndClass.sector), 1.23438)) < rank(correlation(Ts_Rank(vwap, 3.60973), Ts_Rank(adv150, 9.18637), 14.6644)))"

    def __init__(self):
        super().__init__()
        self._nodes = {}
        weight = 0.60733
        close_part = per_asset(
            self, "weighted_close", Multiply, self.field_lines("close"), (weight,) * len(self.datas)
        )
        open_part = per_asset(
            self,
            "weighted_open",
            Multiply,
            self.field_lines("open"),
            (1.0 - weight,) * len(self.datas),
        )
        neutral_price = panel(
            self,
            "sector_neutral_price",
            IndNeutralize,
            per_asset(self, "weighted_price", Add, close_part, open_part),
            level="sector",
            groups=self.field_lines("sector"),
        )
        price_delta = per_asset(self, "neutral_price_delta1", Delta, neutral_price, period=1.23438)
        left_rank = panel(self, "neutral_price_delta_rank", CrossSectionalRank, price_delta)
        vwap_rank = per_asset(
            self, "vwap_ts_rank3", TsRank, self.field_lines("vwap"), period=3.60973
        )
        adv_rank = per_asset(
            self, "adv150_ts_rank9", TsRank, self.field_lines("adv150"), period=9.18637
        )
        right_correlation = per_asset(
            self, "ts_rank_correlation14", RollingCorrelation, vwap_rank, adv_rank, period=14.6644
        )
        right_rank = panel(self, "ts_rank_correlation_rank", CrossSectionalRank, right_correlation)
        self._result_lines = per_asset(self, "rank_less_than", LessThan, left_rank, right_rank)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
