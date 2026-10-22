"""Native Alpha101 factor implementation for Alpha086."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Add,
    CrossSectionalRank,
    LessThan,
    Multiply,
    RollingCorrelation,
    RollingSum,
    Subtract,
    TsRank,
)
from ._helpers import panel, per_asset
from ._metadata import native_alpha


@native_alpha
class Alpha086Native(FactorIndicator):
    """Alpha #86: threshold the ranked open/close/VWAP expression by TS rank."""

    lines = ("factor",)
    alpha_id = 86
    case_id = "AF46-086"
    lookback_h = 56
    formula = "((Ts_Rank(correlation(close, sum(adv20, 14.7444), 6.00049), 20.4195) < rank(((open + close) - (vwap + open)))) * -1)"
    formula_fields = ("close", "open", "vwap", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        adv_sum = per_asset(
            self, "adv20_sum14", RollingSum, self.field_lines("adv20"), period=14.7444
        )
        correlation = per_asset(
            self,
            "close_adv_sum_correlation",
            RollingCorrelation,
            self.field_lines("close"),
            adv_sum,
            period=6.00049,
        )
        time_rank = per_asset(self, "correlation_time_rank20", TsRank, correlation, period=20.4195)
        open_plus_close = per_asset(
            self, "open_plus_close", Add, self.field_lines("open"), self.field_lines("close")
        )
        vwap_plus_open = per_asset(
            self, "vwap_plus_open", Add, self.field_lines("vwap"), self.field_lines("open")
        )
        ranked_expression_input = per_asset(
            self, "open_close_minus_vwap_open", Subtract, open_plus_close, vwap_plus_open
        )
        ranked_expression = panel(
            self, "rank_open_close_minus_vwap_open", CrossSectionalRank, ranked_expression_input
        )
        less_than = per_asset(self, "time_rank_less_rank", LessThan, time_rank, ranked_expression)
        self._result_lines = per_asset(
            self, "negative_comparison", Multiply, less_than, (-1.0,) * count
        )
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
