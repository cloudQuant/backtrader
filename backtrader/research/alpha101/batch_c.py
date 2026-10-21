"""Explicit native implementations for the Iteration 46 Batch C formulas.

The formula trees below are ordinary Backtrader operators assembled by hand.
This module does not parse formula text or create a formula language; every
class carries its own Appendix A identity and independently declared history.
"""

from types import MappingProxyType
from typing import Mapping, Type

from ..operators import (
    Add,
    CrossSectionalRank,
    CrossSectionalScale,
    DecayLinear,
    Delay,
    Delta,
    Divide,
    IndNeutralize,
    LessThan,
    Multiply,
    Power,
    RollingCorrelation,
    RollingSum,
    Subtract,
    TsArgMax,
    TsMax,
    TsMin,
    TsRank,
    Where,
)
from ._base import NativeAlphaBase, native_alpha


@native_alpha
class Alpha041Native(NativeAlphaBase):
    """Alpha#41: geometric open-range proxy minus VWAP."""

    lines = ("factor",)
    alpha_id = 41
    case_id = "AF46-041"
    lookback_h = 0
    formula = "(((high * low)^0.5) - vwap)"
    formula_fields = ("high", "low", "vwap")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        high_low = self._per_asset(
            "high_times_low", Multiply, self._field("high"), self._field("low")
        )
        geometric_mean = self._per_asset(
            "geometric_mean", Power, high_low, (0.5,) * len(self.datas)
        )
        return self._per_asset("minus_vwap", Subtract, geometric_mean, self._field("vwap"))


@native_alpha
class Alpha042Native(NativeAlphaBase):
    """Alpha#42: ratio of cross-sectional VWAP/close difference and sum ranks."""

    lines = ("factor",)
    alpha_id = 42
    case_id = "AF46-042"
    lookback_h = 0
    formula = "(rank((vwap - close)) / rank((vwap + close)))"
    formula_fields = ("vwap", "close")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    # Paper execution timing metadata only; it does not change closed-bar H.
    paper_signal_delay = 0

    def _make_formula(self):
        difference = self._per_asset(
            "vwap_minus_close", Subtract, self._field("vwap"), self._field("close")
        )
        difference_rank = self._panel("rank_difference", CrossSectionalRank, difference)
        total = self._per_asset("vwap_plus_close", Add, self._field("vwap"), self._field("close"))
        total_rank = self._panel("rank_sum", CrossSectionalRank, total)
        return self._per_asset("rank_ratio", Divide, difference_rank, total_rank)


@native_alpha
class Alpha043Native(NativeAlphaBase):
    """Alpha#43: product of two within-asset volume/price time-series ranks."""

    lines = ("factor",)
    alpha_id = 43
    case_id = "AF46-043"
    lookback_h = 38
    formula = "(ts_rank((volume / adv20), 20) * ts_rank((-1 * delta(close, 7)), 8))"
    formula_fields = ("volume", "close", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        volume_to_adv = self._per_asset(
            "volume_to_adv20", Divide, self._field("volume"), self._field("adv20")
        )
        volume_rank = self._per_asset("volume_adv_ts_rank20", TsRank, volume_to_adv, period=20)
        close_delta = self._per_asset("close_delta7", Delta, self._field("close"), period=7)
        negative_delta = self._per_asset(
            "negative_close_delta7", Multiply, close_delta, (-1.0,) * len(self.datas)
        )
        price_rank = self._per_asset("negative_delta_ts_rank8", TsRank, negative_delta, period=8)
        return self._per_asset("rank_product", Multiply, volume_rank, price_rank)


@native_alpha
class Alpha044Native(NativeAlphaBase):
    """Alpha#44: negative rolling correlation of high with ranked volume."""

    lines = ("factor",)
    alpha_id = 44
    case_id = "AF46-044"
    lookback_h = 4
    formula = "(-1 * correlation(high, rank(volume), 5))"
    formula_fields = ("high", "volume")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        volume_rank = self._panel("rank_volume", CrossSectionalRank, self._field("volume"))
        correlation = self._per_asset(
            "high_ranked_volume_corr5",
            RollingCorrelation,
            self._field("high"),
            volume_rank,
            period=5,
        )
        return self._per_asset(
            "negative_correlation", Multiply, correlation, (-1.0,) * len(self.datas)
        )


@native_alpha
class Alpha045Native(NativeAlphaBase):
    """Alpha#45: nested ranks, delayed sum, and short rolling correlations."""

    lines = ("factor",)
    alpha_id = 45
    case_id = "AF46-045"
    lookback_h = 24
    formula = "(-1 * ((rank((sum(delay(close, 5), 20) / 20)) * correlation(close, volume, 2)) * rank(correlation(sum(close, 5), sum(close, 20), 2))))"
    formula_fields = ("close", "volume")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        close = self._field("close")
        delayed_close = self._per_asset("close_delay5", Delay, close, period=5)
        delayed_sum = self._per_asset("delayed_close_sum20", RollingSum, delayed_close, period=20)
        delayed_mean = self._per_asset(
            "delayed_close_sum_mean20",
            Divide,
            delayed_sum,
            (20.0,) * len(self.datas),
        )
        delayed_rank = self._panel("rank_delayed_close_mean", CrossSectionalRank, delayed_mean)

        short_correlation = self._per_asset(
            "close_volume_corr2", RollingCorrelation, close, self._field("volume"), period=2
        )
        close_sum5 = self._per_asset("close_sum5", RollingSum, close, period=5)
        close_sum20 = self._per_asset("close_sum20", RollingSum, close, period=20)
        sum_correlation = self._per_asset(
            "close_sums_corr2", RollingCorrelation, close_sum5, close_sum20, period=2
        )
        sum_correlation_rank = self._panel(
            "rank_close_sums_corr", CrossSectionalRank, sum_correlation
        )
        left_product = self._per_asset("rank_times_corr", Multiply, delayed_rank, short_correlation)
        product = self._per_asset(
            "multiply_sum_correlation_rank", Multiply, left_product, sum_correlation_rank
        )
        return self._per_asset("negative_product", Multiply, product, (-1.0,) * len(self.datas))


@native_alpha
class Alpha046Native(NativeAlphaBase):
    """Alpha#46: nested threshold branches over the 20-grid close slope."""

    lines = ("factor",)
    alpha_id = 46
    case_id = "AF46-046"
    lookback_h = 20
    formula = "((0.25 < (((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10))) ? (-1 * 1) : (((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < 0) ? 1 : ((-1 * 1) * (close - delay(close, 1)))))"
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        close = self._field("close")
        close_delay20 = self._per_asset("close_delay20", Delay, close, period=20)
        close_delay10_a = self._per_asset("close_delay10_a", Delay, close, period=10)
        move_a = self._per_asset("delay20_minus_delay10", Subtract, close_delay20, close_delay10_a)
        normalized_a = self._per_asset(
            "normalized_delay_move", Divide, move_a, (10.0,) * len(self.datas)
        )
        close_delay10_b = self._per_asset("close_delay10_b", Delay, close, period=10)
        move_b = self._per_asset("delay10_minus_close", Subtract, close_delay10_b, close)
        normalized_b = self._per_asset(
            "normalized_recent_move", Divide, move_b, (10.0,) * len(self.datas)
        )
        slope = self._per_asset("slope", Subtract, normalized_a, normalized_b)

        above_quarter = self._per_asset(
            "slope_above_quarter", LessThan, (0.25,) * len(self.datas), slope
        )
        below_zero = self._per_asset("slope_below_zero", LessThan, slope, (0.0,) * len(self.datas))
        close_delay1 = self._per_asset("close_delay1", Delay, close, period=1)
        last_move = self._per_asset("close_minus_delay1", Subtract, close, close_delay1)
        negative_last_move = self._per_asset(
            "negative_close_minus_delay1", Multiply, last_move, (-1.0,) * len(self.datas)
        )
        lower_branch = self._per_asset(
            "lower_slope_branch",
            Where,
            below_zero,
            (1.0,) * len(self.datas),
            negative_last_move,
        )
        return self._per_asset(
            "outer_slope_branch",
            Where,
            above_quarter,
            (-1.0,) * len(self.datas),
            lower_branch,
        )


@native_alpha
class Alpha047Native(NativeAlphaBase):
    """Alpha#47: ADV-scaled ranked reciprocal and delayed-VWAP adjustment."""

    lines = ("factor",)
    alpha_id = 47
    case_id = "AF46-047"
    lookback_h = 19
    formula = "((((rank((1 / close)) * volume) / adv20) * ((high * rank((high - close))) / (sum(high, 5) / 5))) - rank((vwap - delay(vwap, 5))))"
    formula_fields = ("close", "volume", "high", "vwap", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        one_over_close = self._per_asset(
            "one_over_close", Divide, (1.0,) * len(self.datas), self._field("close")
        )
        reciprocal_rank = self._panel("rank_reciprocal_close", CrossSectionalRank, one_over_close)
        volume_weighted_rank = self._per_asset(
            "volume_times_rank_reciprocal", Multiply, reciprocal_rank, self._field("volume")
        )
        adv_scaled = self._per_asset(
            "volume_rank_over_adv20", Divide, volume_weighted_rank, self._field("adv20")
        )

        high_close_rank_input = self._per_asset(
            "high_minus_close", Subtract, self._field("high"), self._field("close")
        )
        high_close_rank = self._panel(
            "rank_high_minus_close", CrossSectionalRank, high_close_rank_input
        )
        high_rank_weighted = self._per_asset(
            "high_times_rank_high_minus_close", Multiply, self._field("high"), high_close_rank
        )
        high_sum5 = self._per_asset("high_sum5", RollingSum, self._field("high"), period=5)
        high_mean5 = self._per_asset("high_mean5", Divide, high_sum5, (5.0,) * len(self.datas))
        high_component = self._per_asset("high_component", Divide, high_rank_weighted, high_mean5)
        left = self._per_asset(
            "adv_scaled_times_high_component", Multiply, adv_scaled, high_component
        )

        vwap_delay5 = self._per_asset("vwap_delay5", Delay, self._field("vwap"), period=5)
        vwap_move = self._per_asset("vwap_minus_delay5", Subtract, self._field("vwap"), vwap_delay5)
        vwap_rank = self._panel("rank_vwap_move", CrossSectionalRank, vwap_move)
        return self._per_asset("alpha47", Subtract, left, vwap_rank)


@native_alpha
class Alpha049Native(NativeAlphaBase):
    """Alpha#49: strict negative-slope threshold with a one-grid fallback."""

    lines = ("factor",)
    alpha_id = 49
    case_id = "AF46-049"
    lookback_h = 20
    formula = "(((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < (-1 * 0.1)) ? 1 : ((-1 * 1) * (close - delay(close, 1))))"
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        close = self._field("close")
        delay20 = self._per_asset("close_delay20", Delay, close, period=20)
        delay10_a = self._per_asset("close_delay10_a", Delay, close, period=10)
        move_a = self._per_asset("delay20_minus_delay10", Subtract, delay20, delay10_a)
        normalized_a = self._per_asset(
            "normalized_delay_move", Divide, move_a, (10.0,) * len(self.datas)
        )
        delay10_b = self._per_asset("close_delay10_b", Delay, close, period=10)
        move_b = self._per_asset("delay10_minus_close", Subtract, delay10_b, close)
        normalized_b = self._per_asset(
            "normalized_recent_move", Divide, move_b, (10.0,) * len(self.datas)
        )
        slope = self._per_asset("slope", Subtract, normalized_a, normalized_b)
        below_threshold = self._per_asset(
            "slope_below_minus_point1", LessThan, slope, (-0.1,) * len(self.datas)
        )
        delay1 = self._per_asset("close_delay1", Delay, close, period=1)
        last_move = self._per_asset("close_minus_delay1", Subtract, close, delay1)
        negative_last_move = self._per_asset(
            "negative_close_move", Multiply, last_move, (-1.0,) * len(self.datas)
        )
        return self._per_asset(
            "threshold_branch",
            Where,
            below_threshold,
            (1.0,) * len(self.datas),
            negative_last_move,
        )


@native_alpha
class Alpha050Native(NativeAlphaBase):
    """Alpha#50: negative five-grid maximum of ranked rank-correlation."""

    lines = ("factor",)
    alpha_id = 50
    case_id = "AF46-050"
    lookback_h = 8
    formula = "(-1 * ts_max(rank(correlation(rank(volume), rank(vwap), 5)), 5))"
    formula_fields = ("volume", "vwap")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        volume_rank = self._panel("rank_volume", CrossSectionalRank, self._field("volume"))
        vwap_rank = self._panel("rank_vwap", CrossSectionalRank, self._field("vwap"))
        correlation = self._per_asset(
            "rank_volume_vwap_corr5", RollingCorrelation, volume_rank, vwap_rank, period=5
        )
        correlation_rank = self._panel("rank_correlation", CrossSectionalRank, correlation)
        maximum = self._per_asset("correlation_rank_max5", TsMax, correlation_rank, period=5)
        return self._per_asset("negative_maximum", Multiply, maximum, (-1.0,) * len(self.datas))


@native_alpha
class Alpha051Native(NativeAlphaBase):
    """Alpha#51: strict negative-slope threshold with a one-grid fallback."""

    lines = ("factor",)
    alpha_id = 51
    case_id = "AF46-051"
    lookback_h = 20
    formula = "(((((delay(close, 20) - delay(close, 10)) / 10) - ((delay(close, 10) - close) / 10)) < (-1 * 0.05)) ? 1 : ((-1 * 1) * (close - delay(close, 1))))"
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        close = self._field("close")
        delay20 = self._per_asset("close_delay20", Delay, close, period=20)
        delay10_a = self._per_asset("close_delay10_a", Delay, close, period=10)
        move_a = self._per_asset("delay20_minus_delay10", Subtract, delay20, delay10_a)
        normalized_a = self._per_asset(
            "normalized_delay_move", Divide, move_a, (10.0,) * len(self.datas)
        )
        delay10_b = self._per_asset("close_delay10_b", Delay, close, period=10)
        move_b = self._per_asset("delay10_minus_close", Subtract, delay10_b, close)
        normalized_b = self._per_asset(
            "normalized_recent_move", Divide, move_b, (10.0,) * len(self.datas)
        )
        slope = self._per_asset("slope", Subtract, normalized_a, normalized_b)
        below_threshold = self._per_asset(
            "slope_below_minus_point05", LessThan, slope, (-0.05,) * len(self.datas)
        )
        delay1 = self._per_asset("close_delay1", Delay, close, period=1)
        last_move = self._per_asset("close_minus_delay1", Subtract, close, delay1)
        negative_last_move = self._per_asset(
            "negative_close_move", Multiply, last_move, (-1.0,) * len(self.datas)
        )
        return self._per_asset(
            "threshold_branch",
            Where,
            below_threshold,
            (1.0,) * len(self.datas),
            negative_last_move,
        )


@native_alpha
class Alpha052Native(NativeAlphaBase):
    """Alpha#52: delayed low minimum, long return-sum rank and volume rank."""

    lines = ("factor",)
    alpha_id = 52
    case_id = "AF46-052"
    lookback_h = 240
    formula = "((((-1 * ts_min(low, 5)) + delay(ts_min(low, 5), 5)) * rank(((sum(returns, 240) - sum(returns, 20)) / 220))) * ts_rank(volume, 5))"
    formula_fields = ("low", "volume", "close")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        low_minimum = self._per_asset("low_minimum5", TsMin, self._field("low"), period=5)
        delayed_low_minimum = self._per_asset("low_minimum5_delay5", Delay, low_minimum, period=5)
        low_change = self._per_asset(
            "delayed_minimum_minus_minimum",
            Add,
            self._per_asset(
                "negative_low_minimum", Multiply, low_minimum, (-1.0,) * len(self.datas)
            ),
            delayed_low_minimum,
        )

        returns = self._returns("close_returns")
        return_sum240 = self._per_asset("returns_sum240", RollingSum, returns, period=240)
        return_sum20 = self._per_asset("returns_sum20", RollingSum, returns, period=20)
        return_sum_delta = self._per_asset(
            "returns_sum_delta", Subtract, return_sum240, return_sum20
        )
        return_sum_ratio = self._per_asset(
            "returns_sum_ratio", Divide, return_sum_delta, (220.0,) * len(self.datas)
        )
        return_rank = self._panel("rank_returns_sum_ratio", CrossSectionalRank, return_sum_ratio)
        volume_rank = self._per_asset("volume_ts_rank5", TsRank, self._field("volume"), period=5)
        left = self._per_asset("low_change_times_returns_rank", Multiply, low_change, return_rank)
        return self._per_asset("alpha52", Multiply, left, volume_rank)


@native_alpha
class Alpha053Native(NativeAlphaBase):
    """Alpha#53: negative nine-grid delta of the close location ratio."""

    lines = ("factor",)
    alpha_id = 53
    case_id = "AF46-053"
    lookback_h = 9
    formula = "(-1 * delta((((close - low) - (high - close)) / (close - low)), 9))"
    formula_fields = ("close", "low", "high")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    # Paper execution timing metadata only; it does not change closed-bar H.
    paper_signal_delay = 0

    def _make_formula(self):
        close_low = self._per_asset(
            "close_minus_low", Subtract, self._field("close"), self._field("low")
        )
        high_close = self._per_asset(
            "high_minus_close", Subtract, self._field("high"), self._field("close")
        )
        numerator = self._per_asset("location_numerator", Subtract, close_low, high_close)
        location = self._per_asset("location_ratio", Divide, numerator, close_low)
        change = self._per_asset("location_delta9", Delta, location, period=9)
        return self._per_asset(
            "negative_location_delta", Multiply, change, (-1.0,) * len(self.datas)
        )


@native_alpha
class Alpha054Native(NativeAlphaBase):
    """Alpha#54: fifth-power OHLC expression with the source denominator."""

    lines = ("factor",)
    alpha_id = 54
    case_id = "AF46-054"
    lookback_h = 0
    formula = "((-1 * ((low - close) * (open^5))) / ((low - high) * (close^5)))"
    formula_fields = ("low", "close", "open", "high")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    # Paper execution timing metadata only; it does not change closed-bar H.
    paper_signal_delay = 0

    def _make_formula(self):
        low_close = self._per_asset(
            "low_minus_close", Subtract, self._field("low"), self._field("close")
        )
        open_fifth = self._per_asset(
            "open_fifth_power", Power, self._field("open"), (5.0,) * len(self.datas)
        )
        numerator = self._per_asset("low_close_times_open_fifth", Multiply, low_close, open_fifth)
        negative_numerator = self._per_asset(
            "negative_numerator", Multiply, numerator, (-1.0,) * len(self.datas)
        )
        low_high = self._per_asset(
            "low_minus_high", Subtract, self._field("low"), self._field("high")
        )
        close_fifth = self._per_asset(
            "close_fifth_power", Power, self._field("close"), (5.0,) * len(self.datas)
        )
        denominator = self._per_asset("denominator", Multiply, low_high, close_fifth)
        return self._per_asset("alpha54", Divide, negative_numerator, denominator)


@native_alpha
class Alpha055Native(NativeAlphaBase):
    """Alpha#55: rolling high/low channel rank correlated with ranked volume."""

    lines = ("factor",)
    alpha_id = 55
    case_id = "AF46-055"
    lookback_h = 16
    formula = "(-1 * correlation(rank(((close - ts_min(low, 12)) / (ts_max(high, 12) - ts_min(low, 12)))), rank(volume), 6))"
    formula_fields = ("close", "low", "high", "volume")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        low_minimum = self._per_asset("low_minimum12", TsMin, self._field("low"), period=12)
        high_maximum = self._per_asset("high_maximum12", TsMax, self._field("high"), period=12)
        channel_numerator = self._per_asset(
            "close_minus_low_minimum", Subtract, self._field("close"), low_minimum
        )
        channel_width = self._per_asset("channel_width", Subtract, high_maximum, low_minimum)
        channel_location = self._per_asset(
            "channel_location", Divide, channel_numerator, channel_width
        )
        location_rank = self._panel("rank_channel_location", CrossSectionalRank, channel_location)
        volume_rank = self._panel("rank_volume", CrossSectionalRank, self._field("volume"))
        correlation = self._per_asset(
            "channel_volume_rank_corr6", RollingCorrelation, location_rank, volume_rank, period=6
        )
        return self._per_asset(
            "negative_correlation", Multiply, correlation, (-1.0,) * len(self.datas)
        )


@native_alpha
class Alpha057Native(NativeAlphaBase):
    """Alpha#57: close/VWAP gap scaled by a decayed ranked argmax."""

    lines = ("factor",)
    alpha_id = 57
    case_id = "AF46-057"
    lookback_h = 30
    formula = "(0 - (1 * ((close - vwap) / decay_linear(rank(ts_argmax(close, 30)), 2))))"
    formula_fields = ("close", "vwap")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        close_vwap = self._per_asset(
            "close_minus_vwap", Subtract, self._field("close"), self._field("vwap")
        )
        argmax = self._per_asset("close_argmax30", TsArgMax, self._field("close"), period=30)
        argmax_rank = self._panel("rank_close_argmax", CrossSectionalRank, argmax)
        decayed_rank = self._per_asset("decay_argmax_rank2", DecayLinear, argmax_rank, period=2)
        ratio = self._per_asset("close_vwap_over_decayed_rank", Divide, close_vwap, decayed_rank)
        weighted_ratio = self._per_asset(
            "one_times_ratio", Multiply, (1.0,) * len(self.datas), ratio
        )
        return self._per_asset(
            "zero_minus_ratio", Subtract, (0.0,) * len(self.datas), weighted_ratio
        )


@native_alpha
class Alpha059Native(NativeAlphaBase):
    """Alpha#59: industry-neutral VWAP correlation with decay and time rank."""

    lines = ("factor",)
    alpha_id = 59
    case_id = "AF46-059"
    lookback_h = 25
    formula = "(-1 * Ts_Rank(decay_linear(correlation(IndNeutralize(((vwap * 0.728317) + (vwap * (1 - 0.728317))), IndClass.industry), volume, 4.25197), 16.2289), 8.19648))"
    formula_fields = ("vwap", "volume")
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ("industry",)

    def _make_formula(self):
        vwap = self._field("vwap")
        weighted_first = self._per_asset(
            "vwap_weighted_0728317", Multiply, vwap, (0.728317,) * len(self.datas)
        )
        complement = self._per_asset(
            "weight_complement", Subtract, (1.0,) * len(self.datas), (0.728317,) * len(self.datas)
        )
        weighted_second = self._per_asset("vwap_weighted_complement", Multiply, vwap, complement)
        weighted_vwap = self._per_asset("weighted_vwap_sum", Add, weighted_first, weighted_second)
        neutral_vwap = self._panel(
            "industry_neutral_vwap",
            IndNeutralize,
            weighted_vwap,
            level="industry",
            groups=self._groups("industry"),
        )
        correlation = self._per_asset(
            "neutral_vwap_volume_corr",
            RollingCorrelation,
            neutral_vwap,
            self._field("volume"),
            period=4.25197,
        )
        decay = self._per_asset("correlation_decay", DecayLinear, correlation, period=16.2289)
        time_rank = self._per_asset("decay_ts_rank", TsRank, decay, period=8.19648)
        return self._per_asset("negative_ts_rank", Multiply, time_rank, (-1.0,) * len(self.datas))


@native_alpha
class Alpha060Native(NativeAlphaBase):
    """Alpha#60: difference of scaled ranked money-flow and argmax signals."""

    lines = ("factor",)
    alpha_id = 60
    case_id = "AF46-060"
    lookback_h = 9
    formula = "(0 - (1 * ((2 * scale(rank(((((close - low) - (high - close)) / (high - low)) * volume)))) - scale(rank(ts_argmax(close, 10))))))"
    formula_fields = ("close", "low", "high", "volume")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        close_low = self._per_asset(
            "close_minus_low", Subtract, self._field("close"), self._field("low")
        )
        high_close = self._per_asset(
            "high_minus_close", Subtract, self._field("high"), self._field("close")
        )
        position_numerator = self._per_asset("position_numerator", Subtract, close_low, high_close)
        high_low = self._per_asset(
            "high_minus_low", Subtract, self._field("high"), self._field("low")
        )
        position = self._per_asset("close_position", Divide, position_numerator, high_low)
        money_flow = self._per_asset(
            "position_times_volume", Multiply, position, self._field("volume")
        )
        money_flow_rank = self._panel("rank_money_flow", CrossSectionalRank, money_flow)
        money_flow_scale = self._panel(
            "scale_money_flow", CrossSectionalScale, money_flow_rank, a=1.0
        )
        scaled_money_flow = self._per_asset(
            "twice_scaled_money_flow", Multiply, (2.0,) * len(self.datas), money_flow_scale
        )

        argmax = self._per_asset("close_argmax10", TsArgMax, self._field("close"), period=10)
        argmax_rank = self._panel("rank_close_argmax", CrossSectionalRank, argmax)
        argmax_scale = self._panel("scale_argmax_rank", CrossSectionalScale, argmax_rank, a=1.0)
        difference = self._per_asset(
            "scaled_component_difference", Subtract, scaled_money_flow, argmax_scale
        )
        weighted_difference = self._per_asset(
            "one_times_component_difference", Multiply, (1.0,) * len(self.datas), difference
        )
        return self._per_asset(
            "zero_minus_component_difference",
            Subtract,
            (0.0,) * len(self.datas),
            weighted_difference,
        )


@native_alpha
class Alpha061Native(NativeAlphaBase):
    """Alpha#61: strict comparison of ranked VWAP channel and ADV correlation."""

    lines = ("factor",)
    alpha_id = 61
    case_id = "AF46-061"
    lookback_h = 195
    formula = "(rank((vwap - ts_min(vwap, 16.1219))) < rank(correlation(vwap, adv180, 17.9282)))"
    formula_fields = ("vwap", "dollar_volume", "adv180")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        vwap = self._field("vwap")
        minimum = self._per_asset("vwap_minimum16", TsMin, vwap, period=16.1219)
        minimum_gap = self._per_asset("vwap_minus_minimum", Subtract, vwap, minimum)
        minimum_rank = self._panel("rank_vwap_minimum_gap", CrossSectionalRank, minimum_gap)
        correlation = self._per_asset(
            "vwap_adv180_corr17", RollingCorrelation, vwap, self._field("adv180"), period=17.9282
        )
        correlation_rank = self._panel("rank_vwap_adv180_corr", CrossSectionalRank, correlation)
        return self._per_asset("ranked_comparison", LessThan, minimum_rank, correlation_rank)


BATCH_FACTORS: Mapping[int, Type[NativeAlphaBase]] = MappingProxyType(
    {
        41: Alpha041Native,
        42: Alpha042Native,
        43: Alpha043Native,
        44: Alpha044Native,
        45: Alpha045Native,
        46: Alpha046Native,
        47: Alpha047Native,
        49: Alpha049Native,
        50: Alpha050Native,
        51: Alpha051Native,
        52: Alpha052Native,
        53: Alpha053Native,
        54: Alpha054Native,
        55: Alpha055Native,
        57: Alpha057Native,
        59: Alpha059Native,
        60: Alpha060Native,
        61: Alpha061Native,
    }
)


__all__ = (
    "Alpha041Native",
    "Alpha042Native",
    "Alpha043Native",
    "Alpha044Native",
    "Alpha045Native",
    "Alpha046Native",
    "Alpha047Native",
    "Alpha049Native",
    "Alpha050Native",
    "Alpha051Native",
    "Alpha052Native",
    "Alpha053Native",
    "Alpha054Native",
    "Alpha055Native",
    "Alpha057Native",
    "Alpha059Native",
    "Alpha060Native",
    "Alpha061Native",
    "BATCH_FACTORS",
)
