"""Explicit native Formulaic Alpha implementations for Iteration 46 batch B.

The formula trees below use the existing Alpha101-v1 Indicator/Lines operators.
They are deliberately written out by hand; this module contains no formula
parser, expression language, or DAG builder.
"""

from types import MappingProxyType
from typing import Mapping, Tuple, Type

from ..operators import (
    Abs,
    Add,
    CrossSectionalRank,
    CrossSectionalScale,
    DecayLinear,
    Delay,
    Delta,
    Divide,
    EqualTo,
    LessThan,
    LogicalOr,
    Multiply,
    Power,
    RollingCorrelation,
    RollingStd,
    RollingSum,
    Sign,
    Subtract,
    TsMax,
    TsMin,
    TsRank,
    Where,
)
from ._base import NativeAlphaBase, native_alpha


@native_alpha
class Alpha021Native(NativeAlphaBase):
    """AF46-021: three nested conditions over short/long close summaries and ADV."""

    lines = ("factor",)
    alpha_id = 21
    case_id = "AF46-021"
    formula = (
        "((((sum(close, 8) / 8) + stddev(close, 8)) < (sum(close, 2) / 2)) ? "
        "(-1 * 1) : (((sum(close, 2) / 2) < ((sum(close, 8) / 8) - stddev(close, 8))) ? "
        "1 : (((1 < (volume / adv20)) || ((volume / adv20) == 1)) ? 1 : (-1 * 1))))"
    )
    lookback_h = 19
    formula_fields = ("close", "volume", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        close = self._field("close")
        volume = self._field("volume")
        adv20 = self._field("adv20")
        ones = (1.0,) * count
        negative_ones = (-1.0,) * count

        sum_close_8 = self._per_asset("sum_close_8", RollingSum, close, period=8)
        mean_close_8 = self._per_asset("mean_close_8", Divide, sum_close_8, (8.0,) * count)
        std_close_8 = self._per_asset("std_close_8", RollingStd, close, period=8)
        first_condition_left = self._per_asset(
            "first_condition_left", Add, mean_close_8, std_close_8
        )
        sum_close_2 = self._per_asset("sum_close_2", RollingSum, close, period=2)
        mean_close_2 = self._per_asset("mean_close_2", Divide, sum_close_2, (2.0,) * count)
        first_condition = self._per_asset(
            "first_condition", LessThan, first_condition_left, mean_close_2
        )

        second_condition_right = self._per_asset(
            "second_condition_right", Subtract, mean_close_8, std_close_8
        )
        second_condition = self._per_asset(
            "second_condition", LessThan, mean_close_2, second_condition_right
        )

        volume_over_adv = self._per_asset("volume_over_adv20", Divide, volume, adv20)
        volume_gate_below = self._per_asset("volume_gate_below", LessThan, ones, volume_over_adv)
        volume_gate_equal = self._per_asset("volume_gate_equal", EqualTo, volume_over_adv, ones)
        volume_gate = self._per_asset(
            "volume_gate", LogicalOr, volume_gate_below, volume_gate_equal
        )
        final_branch = self._per_asset("final_branch", Where, volume_gate, ones, negative_ones)
        second_branch = self._per_asset(
            "second_branch", Where, second_condition, ones, final_branch
        )
        return self._per_asset("factor", Where, first_condition, negative_ones, second_branch)


@native_alpha
class Alpha022Native(NativeAlphaBase):
    """AF46-022: delta of high/volume correlation times ranked close volatility."""

    lines = ("factor",)
    alpha_id = 22
    case_id = "AF46-022"
    formula = "(-1 * (delta(correlation(high, volume, 5), 5) * rank(stddev(close, 20))))"
    lookback_h = 19
    formula_fields = ("high", "volume", "close")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        correlation = self._per_asset(
            "correlation_high_volume_5",
            RollingCorrelation,
            self._field("high"),
            self._field("volume"),
            period=5,
        )
        correlation_change = self._per_asset("correlation_delta_5", Delta, correlation, period=5)
        close_volatility = self._per_asset(
            "close_std_20", RollingStd, self._field("close"), period=20
        )
        ranked_volatility = self._panel("rank_close_std_20", CrossSectionalRank, close_volatility)
        weighted = self._per_asset(
            "correlation_change_times_rank", Multiply, correlation_change, ranked_volatility
        )
        return self._per_asset("factor", Multiply, (-1.0,) * count, weighted)


@native_alpha
class Alpha023Native(NativeAlphaBase):
    """AF46-023: conditional negative two-grid high change."""

    lines = ("factor",)
    alpha_id = 23
    case_id = "AF46-023"
    formula = "(((sum(high, 20) / 20) < high) ? (-1 * delta(high, 2)) : 0)"
    lookback_h = 19
    formula_fields = ("high",)
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        high = self._field("high")
        high_sum = self._per_asset("sum_high_20", RollingSum, high, period=20)
        high_mean = self._per_asset("mean_high_20", Divide, high_sum, (20.0,) * count)
        condition = self._per_asset("high_above_mean_20", LessThan, high_mean, high)
        high_change = self._per_asset("high_delta_2", Delta, high, period=2)
        negative_change = self._per_asset(
            "negative_high_delta_2", Multiply, (-1.0,) * count, high_change
        )
        return self._per_asset("factor", Where, condition, negative_change, (0.0,) * count)


@native_alpha
class Alpha024Native(NativeAlphaBase):
    """AF46-024: exact threshold OR and two conditional close branches."""

    lines = ("factor",)
    alpha_id = 24
    case_id = "AF46-024"
    formula = (
        "((((delta((sum(close, 100) / 100), 100) / delay(close, 100)) < 0.05) || "
        "((delta((sum(close, 100) / 100), 100) / delay(close, 100)) == 0.05)) ? "
        "(-1 * (close - ts_min(close, 100))) : (-1 * delta(close, 3)))"
    )
    lookback_h = 199
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        close = self._field("close")
        close_sum = self._per_asset("sum_close_100", RollingSum, close, period=100)
        close_mean = self._per_asset("mean_close_100", Divide, close_sum, (100.0,) * count)
        mean_change = self._per_asset("mean_close_delta_100", Delta, close_mean, period=100)
        close_delay = self._per_asset("delay_close_100", Delay, close, period=100)
        ratio = self._per_asset("mean_change_over_close_delay", Divide, mean_change, close_delay)
        below_threshold = self._per_asset("threshold_below", LessThan, ratio, (0.05,) * count)
        at_threshold = self._per_asset("threshold_equal", EqualTo, ratio, (0.05,) * count)
        condition = self._per_asset("threshold_condition", LogicalOr, below_threshold, at_threshold)

        close_minimum = self._per_asset("close_min_100", TsMin, close, period=100)
        distance_from_minimum = self._per_asset(
            "close_minus_min_100", Subtract, close, close_minimum
        )
        true_branch = self._per_asset(
            "negative_close_distance", Multiply, (-1.0,) * count, distance_from_minimum
        )
        close_change = self._per_asset("close_delta_3", Delta, close, period=3)
        false_branch = self._per_asset(
            "negative_close_delta_3", Multiply, (-1.0,) * count, close_change
        )
        return self._per_asset("factor", Where, condition, true_branch, false_branch)


@native_alpha
class Alpha025Native(NativeAlphaBase):
    """AF46-025: cross-sectional rank of the return/ADV/VWAP price term."""

    lines = ("factor",)
    alpha_id = 25
    case_id = "AF46-025"
    formula = "rank(((((-1 * returns) * adv20) * vwap) * (high - close)))"
    lookback_h = 19
    formula_fields = ("vwap", "high", "close", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        returns = self._returns("returns")
        negative_returns = self._per_asset("negative_returns", Multiply, (-1.0,) * count, returns)
        return_adv = self._per_asset(
            "return_times_adv20", Multiply, negative_returns, self._field("adv20")
        )
        return_adv_vwap = self._per_asset(
            "return_adv_times_vwap", Multiply, return_adv, self._field("vwap")
        )
        high_minus_close = self._per_asset(
            "high_minus_close", Subtract, self._field("high"), self._field("close")
        )
        product = self._per_asset("rank_input", Multiply, return_adv_vwap, high_minus_close)
        return self._panel("factor", CrossSectionalRank, product)


@native_alpha
class Alpha026Native(NativeAlphaBase):
    """AF46-026: rolling maximum of correlations between volume/high time ranks."""

    lines = ("factor",)
    alpha_id = 26
    case_id = "AF46-026"
    formula = "(-1 * ts_max(correlation(ts_rank(volume, 5), ts_rank(high, 5), 5), 3))"
    lookback_h = 10
    formula_fields = ("volume", "high")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        volume_rank = self._per_asset("volume_ts_rank_5", TsRank, self._field("volume"), period=5)
        high_rank = self._per_asset("high_ts_rank_5", TsRank, self._field("high"), period=5)
        correlation = self._per_asset(
            "rank_correlation_5", RollingCorrelation, volume_rank, high_rank, period=5
        )
        maximum = self._per_asset("correlation_max_3", TsMax, correlation, period=3)
        return self._per_asset("factor", Multiply, (-1.0,) * count, maximum)


@native_alpha
class Alpha027Native(NativeAlphaBase):
    """AF46-027: rank of a two-grid sum of cross-rank correlation."""

    lines = ("factor",)
    alpha_id = 27
    case_id = "AF46-027"
    formula = (
        "((0.5 < rank((sum(correlation(rank(volume), rank(vwap), 6), 2) / 2.0))) ? " "(-1 * 1) : 1)"
    )
    lookback_h = 6
    formula_fields = ("volume", "vwap")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        volume_rank = self._panel("rank_volume", CrossSectionalRank, self._field("volume"))
        vwap_rank = self._panel("rank_vwap", CrossSectionalRank, self._field("vwap"))
        correlation = self._per_asset(
            "rank_correlation_6", RollingCorrelation, volume_rank, vwap_rank, period=6
        )
        correlation_sum = self._per_asset("sum_correlation_2", RollingSum, correlation, period=2)
        mean_correlation = self._per_asset(
            "mean_correlation_2", Divide, correlation_sum, (2.0,) * count
        )
        ranked_sum = self._panel("rank_mean_correlation", CrossSectionalRank, mean_correlation)
        condition = self._per_asset("threshold", LessThan, (0.5,) * count, ranked_sum)
        return self._per_asset("factor", Where, condition, (-1.0,) * count, (1.0,) * count)


@native_alpha
class Alpha028Native(NativeAlphaBase):
    """AF46-028: scaled sum of ADV/low correlation and the high-low midpoint."""

    lines = ("factor",)
    alpha_id = 28
    case_id = "AF46-028"
    formula = "scale(((correlation(adv20, low, 5) + ((high + low) / 2)) - close))"
    lookback_h = 23
    formula_fields = ("low", "high", "close", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        correlation = self._per_asset(
            "adv20_low_correlation_5",
            RollingCorrelation,
            self._field("adv20"),
            self._field("low"),
            period=5,
        )
        high_plus_low = self._per_asset(
            "high_plus_low", Add, self._field("high"), self._field("low")
        )
        midpoint = self._per_asset("high_low_midpoint", Divide, high_plus_low, (2.0,) * count)
        correlation_plus_midpoint = self._per_asset(
            "correlation_plus_midpoint", Add, correlation, midpoint
        )
        unscaled = self._per_asset(
            "scale_input", Subtract, correlation_plus_midpoint, self._field("close")
        )
        return self._panel("factor", CrossSectionalScale, unscaled)


@native_alpha
class Alpha030Native(NativeAlphaBase):
    """AF46-030: rank the sum of three separately signed close changes."""

    lines = ("factor",)
    alpha_id = 30
    case_id = "AF46-030"
    formula = (
        "(((1.0 - rank(((sign((close - delay(close, 1))) + "
        "sign((delay(close, 1) - delay(close, 2)))) + "
        "sign((delay(close, 2) - delay(close, 3)))))) * sum(volume, 5)) / sum(volume, 20))"
    )
    lookback_h = 19
    formula_fields = ("close", "volume")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        close = self._field("close")
        close_delay_1 = self._per_asset("delay_close_1", Delay, close, period=1)
        close_delay_2 = self._per_asset("delay_close_2", Delay, close, period=2)
        close_delay_3 = self._per_asset("delay_close_3", Delay, close, period=3)
        change_1 = self._per_asset("close_change_1", Subtract, close, close_delay_1)
        change_2 = self._per_asset("close_change_2", Subtract, close_delay_1, close_delay_2)
        change_3 = self._per_asset("close_change_3", Subtract, close_delay_2, close_delay_3)
        sign_1 = self._per_asset("sign_close_change_1", Sign, change_1)
        sign_2 = self._per_asset("sign_close_change_2", Sign, change_2)
        sign_3 = self._per_asset("sign_close_change_3", Sign, change_3)
        sign_sum_1 = self._per_asset("sign_sum_1", Add, sign_1, sign_2)
        sign_sum = self._per_asset("sign_sum", Add, sign_sum_1, sign_3)
        ranked_sign_sum = self._panel("rank_sign_sum", CrossSectionalRank, sign_sum)
        one_minus_rank = self._per_asset(
            "one_minus_rank", Subtract, (1.0,) * count, ranked_sign_sum
        )
        volume_5 = self._per_asset("volume_sum_5", RollingSum, self._field("volume"), period=5)
        volume_20 = self._per_asset("volume_sum_20", RollingSum, self._field("volume"), period=20)
        weighted = self._per_asset("weighted_volume_5", Multiply, one_minus_rank, volume_5)
        return self._per_asset("factor", Divide, weighted, volume_20)


@native_alpha
class Alpha031Native(NativeAlphaBase):
    """AF46-031: nested rank/decay terms plus a scaled ADV/low correlation sign."""

    lines = ("factor",)
    alpha_id = 31
    case_id = "AF46-031"
    formula = (
        "((rank(rank(rank(decay_linear((-1 * rank(rank(delta(close, 10)))), 10)))) + "
        "rank((-1 * delta(close, 3)))) + sign(scale(correlation(adv20, low, 12))))"
    )
    lookback_h = 30
    formula_fields = ("close", "low", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        close = self._field("close")
        close_delta_10 = self._per_asset("close_delta_10", Delta, close, period=10)
        ranked_delta_10 = self._panel("rank_delta_10", CrossSectionalRank, close_delta_10)
        ranked_ranked_delta_10 = self._panel(
            "rank_rank_delta_10", CrossSectionalRank, ranked_delta_10
        )
        negative_ranked_ranked_delta = self._per_asset(
            "negative_rank_rank_delta_10", Multiply, (-1.0,) * count, ranked_ranked_delta_10
        )
        decayed = self._per_asset(
            "decay_rank_rank_delta_10", DecayLinear, negative_ranked_ranked_delta, period=10
        )
        ranked_decay_1 = self._panel("rank_decay_1", CrossSectionalRank, decayed)
        ranked_decay_2 = self._panel("rank_decay_2", CrossSectionalRank, ranked_decay_1)
        ranked_decay_3 = self._panel("rank_decay_3", CrossSectionalRank, ranked_decay_2)

        close_delta_3 = self._per_asset("close_delta_3", Delta, close, period=3)
        negative_close_delta_3 = self._per_asset(
            "negative_close_delta_3", Multiply, (-1.0,) * count, close_delta_3
        )
        ranked_negative_delta = self._panel(
            "rank_negative_delta_3", CrossSectionalRank, negative_close_delta_3
        )

        adv_low_correlation = self._per_asset(
            "adv20_low_correlation_12",
            RollingCorrelation,
            self._field("adv20"),
            self._field("low"),
            period=12,
        )
        scaled_correlation = self._panel(
            "scale_adv20_low_correlation", CrossSectionalScale, adv_low_correlation
        )
        correlation_sign = self._per_asset("sign_scaled_correlation", Sign, scaled_correlation)

        first_two_terms = self._per_asset(
            "first_two_terms", Add, ranked_decay_3, ranked_negative_delta
        )
        return self._per_asset("factor", Add, first_two_terms, correlation_sign)


@native_alpha
class Alpha032Native(NativeAlphaBase):
    """AF46-032: two scaled price terms, including a five-delayed 230-grid correlation."""

    lines = ("factor",)
    alpha_id = 32
    case_id = "AF46-032"
    formula = (
        "(scale(((sum(close, 7) / 7) - close)) + "
        "(20 * scale(correlation(vwap, delay(close, 5), 230))))"
    )
    lookback_h = 234
    formula_fields = ("close", "vwap")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        close = self._field("close")
        close_sum_7 = self._per_asset("sum_close_7", RollingSum, close, period=7)
        close_mean_7 = self._per_asset("mean_close_7", Divide, close_sum_7, (7.0,) * count)
        close_mean_difference = self._per_asset(
            "close_mean_difference", Subtract, close_mean_7, close
        )
        scaled_mean_difference = self._panel(
            "scale_close_mean_difference", CrossSectionalScale, close_mean_difference
        )

        close_delay_5 = self._per_asset("delay_close_5", Delay, close, period=5)
        correlation = self._per_asset(
            "vwap_close_correlation_230",
            RollingCorrelation,
            self._field("vwap"),
            close_delay_5,
            period=230,
        )
        scaled_correlation = self._panel(
            "scale_vwap_close_correlation", CrossSectionalScale, correlation
        )
        weighted_correlation = self._per_asset(
            "weighted_correlation", Multiply, (20.0,) * count, scaled_correlation
        )
        return self._per_asset("factor", Add, scaled_mean_difference, weighted_correlation)


@native_alpha
class Alpha033Native(NativeAlphaBase):
    """AF46-033: cross-sectional rank of the ordinary-power open/close term."""

    lines = ("factor",)
    alpha_id = 33
    case_id = "AF46-033"
    formula = "rank((-1 * ((1 - (open / close))^1)))"
    lookback_h = 0
    formula_fields = ("open", "close")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        open_close = self._per_asset(
            "open_over_close", Divide, self._field("open"), self._field("close")
        )
        one_minus_ratio = self._per_asset(
            "one_minus_open_over_close", Subtract, (1.0,) * count, open_close
        )
        powered = self._per_asset("ordinary_power_one", Power, one_minus_ratio, (1.0,) * count)
        negative = self._per_asset("negative_power", Multiply, (-1.0,) * count, powered)
        return self._panel("factor", CrossSectionalRank, negative)


@native_alpha
class Alpha034Native(NativeAlphaBase):
    """AF46-034: ranked combination of relative volatility and close change ranks."""

    lines = ("factor",)
    alpha_id = 34
    case_id = "AF46-034"
    formula = (
        "rank(((1 - rank((stddev(returns, 2) / stddev(returns, 5)))) + "
        "(1 - rank(delta(close, 1)))))"
    )
    lookback_h = 5
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        returns = self._returns("returns")
        std_returns_2 = self._per_asset("returns_std_2", RollingStd, returns, period=2)
        std_returns_5 = self._per_asset("returns_std_5", RollingStd, returns, period=5)
        relative_volatility = self._per_asset(
            "relative_volatility", Divide, std_returns_2, std_returns_5
        )
        ranked_volatility = self._panel(
            "rank_relative_volatility", CrossSectionalRank, relative_volatility
        )
        one_minus_volatility_rank = self._per_asset(
            "one_minus_volatility_rank", Subtract, (1.0,) * count, ranked_volatility
        )
        close_change = self._per_asset("close_delta_1", Delta, self._field("close"), period=1)
        ranked_close_change = self._panel("rank_close_delta_1", CrossSectionalRank, close_change)
        one_minus_change_rank = self._per_asset(
            "one_minus_change_rank", Subtract, (1.0,) * count, ranked_close_change
        )
        combined = self._per_asset(
            "combined_rank_terms", Add, one_minus_volatility_rank, one_minus_change_rank
        )
        return self._panel("factor", CrossSectionalRank, combined)


@native_alpha
class Alpha035Native(NativeAlphaBase):
    """AF46-035: product of volume, range, and return time ranks."""

    lines = ("factor",)
    alpha_id = 35
    case_id = "AF46-035"
    formula = (
        "((Ts_Rank(volume, 32) * (1 - Ts_Rank(((close + high) - low), 16))) * "
        "(1 - Ts_Rank(returns, 32)))"
    )
    lookback_h = 32
    formula_fields = ("volume", "close", "high", "low")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        volume_rank = self._per_asset("volume_ts_rank_32", TsRank, self._field("volume"), period=32)
        close_plus_high = self._per_asset(
            "close_plus_high", Add, self._field("close"), self._field("high")
        )
        range_input = self._per_asset(
            "close_high_minus_low", Subtract, close_plus_high, self._field("low")
        )
        range_rank = self._per_asset("range_ts_rank_16", TsRank, range_input, period=16)
        one_minus_range_rank = self._per_asset(
            "one_minus_range_rank", Subtract, (1.0,) * count, range_rank
        )
        returns = self._returns("returns")
        returns_rank = self._per_asset("returns_ts_rank_32", TsRank, returns, period=32)
        one_minus_returns_rank = self._per_asset(
            "one_minus_returns_rank", Subtract, (1.0,) * count, returns_rank
        )
        first_product = self._per_asset(
            "volume_times_range_term", Multiply, volume_rank, one_minus_range_rank
        )
        return self._per_asset("factor", Multiply, first_product, one_minus_returns_rank)


@native_alpha
class Alpha036Native(NativeAlphaBase):
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

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        close = self._field("close")
        open_price = self._field("open")
        volume = self._field("volume")
        vwap = self._field("vwap")

        close_minus_open = self._per_asset("close_minus_open", Subtract, close, open_price)
        volume_delay_1 = self._per_asset("delay_volume_1", Delay, volume, period=1)
        first_correlation = self._per_asset(
            "close_open_volume_correlation_15",
            RollingCorrelation,
            close_minus_open,
            volume_delay_1,
            period=15,
        )
        first_rank = self._panel(
            "rank_close_open_volume_correlation", CrossSectionalRank, first_correlation
        )
        first_term = self._per_asset(
            "weighted_correlation_rank", Multiply, (2.21,) * count, first_rank
        )

        open_minus_close = self._per_asset("open_minus_close", Subtract, open_price, close)
        second_rank = self._panel("rank_open_minus_close", CrossSectionalRank, open_minus_close)
        second_term = self._per_asset(
            "weighted_open_close_rank", Multiply, (0.7,) * count, second_rank
        )

        returns = self._returns("returns")
        negative_returns = self._per_asset("negative_returns", Multiply, (-1.0,) * count, returns)
        negative_returns_delay_6 = self._per_asset(
            "delay_negative_returns_6", Delay, negative_returns, period=6
        )
        delayed_return_rank = self._per_asset(
            "delay_negative_returns_ts_rank_5",
            TsRank,
            negative_returns_delay_6,
            period=5,
        )
        third_rank = self._panel(
            "rank_delayed_return_ts_rank", CrossSectionalRank, delayed_return_rank
        )
        third_term = self._per_asset(
            "weighted_delayed_return_rank", Multiply, (0.73,) * count, third_rank
        )

        adv20_vwap_correlation = self._per_asset(
            "adv20_vwap_correlation_6",
            RollingCorrelation,
            vwap,
            self._field("adv20"),
            period=6,
        )
        absolute_correlation = self._per_asset(
            "absolute_adv20_vwap_correlation", Abs, adv20_vwap_correlation
        )
        fourth_rank = self._panel(
            "rank_absolute_adv20_vwap_correlation",
            CrossSectionalRank,
            absolute_correlation,
        )

        close_sum_200 = self._per_asset("sum_close_200", RollingSum, close, period=200)
        close_mean_200 = self._per_asset("mean_close_200", Divide, close_sum_200, (200.0,) * count)
        mean_minus_open = self._per_asset(
            "mean_close_minus_open", Subtract, close_mean_200, open_price
        )
        close_minus_open_again = self._per_asset(
            "close_minus_open_for_term_5", Subtract, close, open_price
        )
        fifth_product = self._per_asset(
            "long_mean_times_intraday_move", Multiply, mean_minus_open, close_minus_open_again
        )
        fifth_rank = self._panel(
            "rank_long_mean_intraday_product", CrossSectionalRank, fifth_product
        )
        fifth_term = self._per_asset(
            "weighted_long_mean_intraday_rank", Multiply, (0.6,) * count, fifth_rank
        )

        first_two_terms = self._per_asset("first_two_terms", Add, first_term, second_term)
        first_three_terms = self._per_asset("first_three_terms", Add, first_two_terms, third_term)
        first_four_terms = self._per_asset("first_four_terms", Add, first_three_terms, fourth_rank)
        return self._per_asset("factor", Add, first_four_terms, fifth_term)


@native_alpha
class Alpha037Native(NativeAlphaBase):
    """AF46-037: rank of delayed intraday-move correlation plus its direct rank."""

    lines = ("factor",)
    alpha_id = 37
    case_id = "AF46-037"
    formula = "(rank(correlation(delay((open - close), 1), close, 200)) + rank((open - close)))"
    lookback_h = 200
    formula_fields = ("open", "close")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        open_close = self._per_asset(
            "open_minus_close", Subtract, self._field("open"), self._field("close")
        )
        delayed_open_close = self._per_asset(
            "delay_open_minus_close_1", Delay, open_close, period=1
        )
        correlation = self._per_asset(
            "delayed_open_close_correlation_200",
            RollingCorrelation,
            delayed_open_close,
            self._field("close"),
            period=200,
        )
        ranked_correlation = self._panel(
            "rank_delayed_open_close_correlation", CrossSectionalRank, correlation
        )
        ranked_open_close = self._panel("rank_open_minus_close", CrossSectionalRank, open_close)
        return self._per_asset("factor", Add, ranked_correlation, ranked_open_close)


@native_alpha
class Alpha038Native(NativeAlphaBase):
    """AF46-038: product of negative close time-rank and close/open rank."""

    lines = ("factor",)
    alpha_id = 38
    case_id = "AF46-038"
    formula = "((-1 * rank(Ts_Rank(close, 10))) * rank((close / open)))"
    lookback_h = 9
    formula_fields = ("close", "open")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        close = self._field("close")
        close_rank = self._per_asset("close_ts_rank_10", TsRank, close, period=10)
        ranked_close_time_rank = self._panel(
            "rank_close_ts_rank_10", CrossSectionalRank, close_rank
        )
        negative_time_rank = self._per_asset(
            "negative_ranked_close_time_rank",
            Multiply,
            (-1.0,) * count,
            ranked_close_time_rank,
        )
        close_over_open = self._per_asset("close_over_open", Divide, close, self._field("open"))
        ranked_close_over_open = self._panel(
            "rank_close_over_open", CrossSectionalRank, close_over_open
        )
        return self._per_asset("factor", Multiply, negative_time_rank, ranked_close_over_open)


@native_alpha
class Alpha039Native(NativeAlphaBase):
    """AF46-039: ranked seven-grid price change, decay gate, and 250-grid return sum."""

    lines = ("factor",)
    alpha_id = 39
    case_id = "AF46-039"
    formula = (
        "((-1 * rank((delta(close, 7) * (1 - rank(decay_linear((volume / adv20), 9)))))) * "
        "(1 + rank(sum(returns, 250))))"
    )
    lookback_h = 250
    formula_fields = ("close", "volume", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        volume_over_adv = self._per_asset(
            "volume_over_adv20", Divide, self._field("volume"), self._field("adv20")
        )
        decayed_ratio = self._per_asset(
            "decay_volume_over_adv_9", DecayLinear, volume_over_adv, period=9
        )
        ranked_decay = self._panel("rank_decay_volume_over_adv", CrossSectionalRank, decayed_ratio)
        one_minus_ranked_decay = self._per_asset(
            "one_minus_ranked_decay", Subtract, (1.0,) * count, ranked_decay
        )
        close_delta_7 = self._per_asset("close_delta_7", Delta, self._field("close"), period=7)
        gated_price_change = self._per_asset(
            "gated_close_delta_7", Multiply, close_delta_7, one_minus_ranked_decay
        )
        ranked_gated_price_change = self._panel(
            "rank_gated_close_delta_7", CrossSectionalRank, gated_price_change
        )
        negative_ranked_price_change = self._per_asset(
            "negative_ranked_price_change",
            Multiply,
            (-1.0,) * count,
            ranked_gated_price_change,
        )

        returns = self._returns("returns")
        return_sum_250 = self._per_asset("sum_returns_250", RollingSum, returns, period=250)
        ranked_return_sum = self._panel("rank_sum_returns_250", CrossSectionalRank, return_sum_250)
        one_plus_ranked_return_sum = self._per_asset(
            "one_plus_ranked_return_sum", Add, (1.0,) * count, ranked_return_sum
        )
        return self._per_asset(
            "factor", Multiply, negative_ranked_price_change, one_plus_ranked_return_sum
        )


@native_alpha
class Alpha040Native(NativeAlphaBase):
    """AF46-040: negative ranked high volatility times high/volume correlation."""

    lines = ("factor",)
    alpha_id = 40
    case_id = "AF46-040"
    formula = "((-1 * rank(stddev(high, 10))) * correlation(high, volume, 10))"
    lookback_h = 9
    formula_fields = ("high", "volume")
    required_fields = formula_fields
    classification_fields = ()
    classification_levels = ()

    def _make_formula(self) -> Tuple[object, ...]:
        count = len(self.datas)
        high_volatility = self._per_asset("high_std_10", RollingStd, self._field("high"), period=10)
        ranked_high_volatility = self._panel(
            "rank_high_std_10", CrossSectionalRank, high_volatility
        )
        negative_ranked_volatility = self._per_asset(
            "negative_ranked_high_volatility",
            Multiply,
            (-1.0,) * count,
            ranked_high_volatility,
        )
        high_volume_correlation = self._per_asset(
            "high_volume_correlation_10",
            RollingCorrelation,
            self._field("high"),
            self._field("volume"),
            period=10,
        )
        return self._per_asset(
            "factor", Multiply, negative_ranked_volatility, high_volume_correlation
        )


BATCH_FACTORS: Mapping[int, Type[NativeAlphaBase]] = MappingProxyType(
    {
        21: Alpha021Native,
        22: Alpha022Native,
        23: Alpha023Native,
        24: Alpha024Native,
        25: Alpha025Native,
        26: Alpha026Native,
        27: Alpha027Native,
        28: Alpha028Native,
        30: Alpha030Native,
        31: Alpha031Native,
        32: Alpha032Native,
        33: Alpha033Native,
        34: Alpha034Native,
        35: Alpha035Native,
        36: Alpha036Native,
        37: Alpha037Native,
        38: Alpha038Native,
        39: Alpha039Native,
        40: Alpha040Native,
    }
)


__all__ = (
    "Alpha021Native",
    "Alpha022Native",
    "Alpha023Native",
    "Alpha024Native",
    "Alpha025Native",
    "Alpha026Native",
    "Alpha027Native",
    "Alpha028Native",
    "Alpha030Native",
    "Alpha031Native",
    "Alpha032Native",
    "Alpha033Native",
    "Alpha034Native",
    "Alpha035Native",
    "Alpha036Native",
    "Alpha037Native",
    "Alpha038Native",
    "Alpha039Native",
    "Alpha040Native",
    "BATCH_FACTORS",
)
