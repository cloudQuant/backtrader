"""Native Alpha101 factor implementation for Alpha036."""

from ..factor_indicator import FactorIndicator
from ..operators import (
    Abs,
    Add,
    CrossSectionalRank,
    Delay,
    Divide,
    Multiply,
    RollingCorrelation,
    RollingSum,
    Subtract,
    TsRank,
)
from ._helpers import panel, per_asset, simple_returns
from ._metadata import native_alpha


@native_alpha
class Alpha036Native(FactorIndicator):
    """AF46-036: five weighted cross-sectional rank terms."""

    lines = ("factor",)
    alpha_id = 36
    case_id = "AF46-036"
    formula = (
        "(((((2.21 * rank(correlation((close - open), delay(volume, 1), 15))) + "
        "(0.7 * rank((open - close)))) + "
        "(0.73 * rank(Ts_Rank(delay((-1 * returns), 6), 5)))) + "
        "rank(abs(correlation(vwap, adv20, 6)))) + "
        "(0.6 * rank((((sum(close, 200) / 200) - open) * (close - open)))))"
    )
    lookback_h = 199
    formula_fields = (
        "close",
        "open",
        "volume",
        "vwap",
        "dollar_volume",
        "adv20",
    )
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def __init__(self):
        super().__init__()
        self._nodes = {}
        count = len(self.datas)
        close = self.field_lines("close")
        open_price = self.field_lines("open")
        volume = self.field_lines("volume")
        vwap = self.field_lines("vwap")
        close_minus_open = per_asset(self, "close_minus_open", Subtract, close, open_price)
        volume_delay_1 = per_asset(self, "delay_volume_1", Delay, volume, period=1)
        first_correlation = per_asset(
            self,
            "close_open_volume_correlation_15",
            RollingCorrelation,
            close_minus_open,
            volume_delay_1,
            period=15,
        )
        first_rank = panel(
            self, "rank_close_open_volume_correlation", CrossSectionalRank, first_correlation
        )
        first_term = per_asset(
            self, "weighted_correlation_rank", Multiply, (2.21,) * count, first_rank
        )
        open_minus_close = per_asset(self, "open_minus_close", Subtract, open_price, close)
        second_rank = panel(self, "rank_open_minus_close", CrossSectionalRank, open_minus_close)
        second_term = per_asset(
            self, "weighted_open_close_rank", Multiply, (0.7,) * count, second_rank
        )
        returns = simple_returns(self, "returns")
        negative_returns = per_asset(self, "negative_returns", Multiply, (-1.0,) * count, returns)
        negative_returns_delay_6 = per_asset(
            self, "delay_negative_returns_6", Delay, negative_returns, period=6
        )
        delayed_return_rank = per_asset(
            self, "delay_negative_returns_ts_rank_5", TsRank, negative_returns_delay_6, period=5
        )
        third_rank = panel(
            self, "rank_delayed_return_ts_rank", CrossSectionalRank, delayed_return_rank
        )
        third_term = per_asset(
            self, "weighted_delayed_return_rank", Multiply, (0.73,) * count, third_rank
        )
        adv20_vwap_correlation = per_asset(
            self,
            "adv20_vwap_correlation_6",
            RollingCorrelation,
            vwap,
            self.field_lines("adv20"),
            period=6,
        )
        absolute_correlation = per_asset(
            self, "absolute_adv20_vwap_correlation", Abs, adv20_vwap_correlation
        )
        fourth_rank = panel(
            self, "rank_absolute_adv20_vwap_correlation", CrossSectionalRank, absolute_correlation
        )
        close_sum_200 = per_asset(self, "sum_close_200", RollingSum, close, period=200)
        close_mean_200 = per_asset(self, "mean_close_200", Divide, close_sum_200, (200.0,) * count)
        mean_minus_open = per_asset(
            self, "mean_close_minus_open", Subtract, close_mean_200, open_price
        )
        close_minus_open_again = per_asset(
            self, "close_minus_open_for_term_5", Subtract, close, open_price
        )
        fifth_product = per_asset(
            self, "long_mean_times_intraday_move", Multiply, mean_minus_open, close_minus_open_again
        )
        fifth_rank = panel(
            self, "rank_long_mean_intraday_product", CrossSectionalRank, fifth_product
        )
        fifth_term = per_asset(
            self, "weighted_long_mean_intraday_rank", Multiply, (0.6,) * count, fifth_rank
        )
        first_two_terms = per_asset(self, "first_two_terms", Add, first_term, second_term)
        first_three_terms = per_asset(self, "first_three_terms", Add, first_two_terms, third_term)
        first_four_terms = per_asset(self, "first_four_terms", Add, first_three_terms, fourth_rank)
        self._result_lines = per_asset(self, "factor", Add, first_four_terms, fifth_term)
        self.addminperiod(self.lookback_h + 1)

    def next(self):
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]
