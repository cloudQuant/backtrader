"""Explicit native Alpha101 formula trees for the first Iteration 46 batch.

The classes below implement only their Appendix A formulas.  They compose the
existing Backtrader indicator and panel operators through the shared
representative helpers; no formula parser or alternate scheduler is involved.
"""

from types import MappingProxyType

from ..operators import (
    Abs,
    Add,
    CrossSectionalRank,
    Delay,
    Delta,
    Divide,
    GreaterThan,
    LessThan,
    Multiply,
    RollingCorrelation,
    RollingCovariance,
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
class Alpha005Native(NativeAlphaBase):
    """Alpha #5: ranked open versus the ten-grid VWAP average."""

    lines = ("factor",)
    alpha_id = 5
    case_id = "AF46-005"
    lookback_h = 9
    formula = "(rank((open - (sum(vwap, 10) / 10))) * (-1 * abs(rank((close - vwap)))))"
    formula_fields = ("open", "vwap", "close")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        open_minus_average = self._per_asset(
            "open_minus_vwap_average",
            Subtract,
            self._field("open"),
            self._per_asset(
                "vwap_average10",
                Divide,
                self._per_asset("vwap_sum10", RollingSum, self._field("vwap"), period=10),
                (10.0,) * count,
            ),
        )
        ranked_open_gap = self._panel("rank_open_gap", CrossSectionalRank, open_minus_average)

        close_minus_vwap = self._per_asset(
            "close_minus_vwap", Subtract, self._field("close"), self._field("vwap")
        )
        ranked_close_gap = self._panel("rank_close_gap", CrossSectionalRank, close_minus_vwap)
        absolute_rank = self._per_asset("absolute_rank_close_gap", Abs, ranked_close_gap)
        negative_absolute_rank = self._per_asset(
            "negative_absolute_rank_close_gap",
            Multiply,
            absolute_rank,
            (-1.0,) * count,
        )
        return self._per_asset("factor", Multiply, ranked_open_gap, negative_absolute_rank)


@native_alpha
class Alpha006Native(NativeAlphaBase):
    """Alpha #6: negative ten-grid open/volume correlation (pure time series)."""

    lines = ("factor",)
    alpha_id = 6
    case_id = "AF46-006"
    lookback_h = 9
    formula = "(-1 * correlation(open, volume, 10))"
    formula_fields = ("open", "volume")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        correlation = self._per_asset(
            "correlation10",
            RollingCorrelation,
            self._field("open"),
            self._field("volume"),
            period=10,
        )
        return self._per_asset(
            "negative_correlation", Multiply, correlation, (-1.0,) * len(self.datas)
        )


@native_alpha
class Alpha008Native(NativeAlphaBase):
    """Alpha #8: negative cross-rank of the delayed product difference."""

    lines = ("factor",)
    alpha_id = 8
    case_id = "AF46-008"
    lookback_h = 15
    formula = "(-1 * rank(((sum(open, 5) * sum(returns, 5)) - delay((sum(open, 5) * sum(returns, 5)), 10))))"
    formula_fields = ("open", "close")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        open_sum = self._per_asset("open_sum5", RollingSum, self._field("open"), period=5)
        returns = self._returns("returns")
        returns_sum = self._per_asset("returns_sum5", RollingSum, returns, period=5)
        product = self._per_asset("sum_product", Multiply, open_sum, returns_sum)
        prior_product = self._per_asset("delayed_sum_product", Delay, product, period=10)
        difference = self._per_asset("product_difference", Subtract, product, prior_product)
        ranked = self._panel("rank_product_difference", CrossSectionalRank, difference)
        return self._per_asset("negative_rank", Multiply, ranked, (-1.0,) * count)


@native_alpha
class Alpha010Native(NativeAlphaBase):
    """Alpha #10: nested four-grid delta-extrema branch and cross-rank."""

    lines = ("factor",)
    alpha_id = 10
    case_id = "AF46-010"
    lookback_h = 4
    formula = "rank(((0 < ts_min(delta(close, 1), 4)) ? delta(close, 1) : ((ts_max(delta(close, 1), 4) < 0) ? delta(close, 1) : (-1 * delta(close, 1)))))"
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        change = self._per_asset("close_delta1", Delta, self._field("close"), period=1)
        floor = self._per_asset("delta_min4", TsMin, change, period=4)
        positive_floor = self._per_asset("positive_minimum", GreaterThan, floor, (0.0,) * count)
        ceiling = self._per_asset("delta_max4", TsMax, change, period=4)
        negative_ceiling = self._per_asset("negative_maximum", LessThan, ceiling, (0.0,) * count)
        negative_change = self._per_asset("negative_delta", Multiply, change, (-1.0,) * count)
        second_branch = self._per_asset(
            "second_where", Where, negative_ceiling, change, negative_change
        )
        selected = self._per_asset("first_where", Where, positive_floor, change, second_branch)
        return self._panel("rank_selected_delta", CrossSectionalRank, selected)


@native_alpha
class Alpha011Native(NativeAlphaBase):
    """Alpha #11: ranked rolling VWAP/close extrema plus ranked volume delta."""

    lines = ("factor",)
    alpha_id = 11
    case_id = "AF46-011"
    lookback_h = 3
    formula = "((rank(ts_max((vwap - close), 3)) + rank(ts_min((vwap - close), 3))) * rank(delta(volume, 3)))"
    formula_fields = ("vwap", "close", "volume")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        spread = self._per_asset(
            "vwap_minus_close", Subtract, self._field("vwap"), self._field("close")
        )
        high_spread = self._per_asset("spread_max3", TsMax, spread, period=3)
        low_spread = self._per_asset("spread_min3", TsMin, spread, period=3)
        ranked_high = self._panel("rank_spread_max", CrossSectionalRank, high_spread)
        ranked_low = self._panel("rank_spread_min", CrossSectionalRank, low_spread)
        extrema_rank_sum = self._per_asset("ranked_extrema_sum", Add, ranked_high, ranked_low)

        volume_delta = self._per_asset("volume_delta3", Delta, self._field("volume"), period=3)
        ranked_volume_delta = self._panel("rank_volume_delta", CrossSectionalRank, volume_delta)
        return self._per_asset("factor", Multiply, extrema_rank_sum, ranked_volume_delta)


@native_alpha
class Alpha012Native(NativeAlphaBase):
    """Alpha #12: sign of volume change times negative close change."""

    lines = ("factor",)
    alpha_id = 12
    case_id = "AF46-012"
    lookback_h = 1
    formula = "(sign(delta(volume, 1)) * (-1 * delta(close, 1)))"
    formula_fields = ("volume", "close")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        volume_delta = self._per_asset("volume_delta1", Delta, self._field("volume"), period=1)
        volume_sign = self._per_asset("sign_volume_delta", Sign, volume_delta)
        close_delta = self._per_asset("close_delta1", Delta, self._field("close"), period=1)
        negative_close_delta = self._per_asset(
            "negative_close_delta", Multiply, close_delta, (-1.0,) * count
        )
        return self._per_asset("factor", Multiply, volume_sign, negative_close_delta)


@native_alpha
class Alpha014Native(NativeAlphaBase):
    """Alpha #14: negative ranked three-grid return delta times raw correlation."""

    lines = ("factor",)
    alpha_id = 14
    case_id = "AF46-014"
    lookback_h = 9
    formula = "((-1 * rank(delta(returns, 3))) * correlation(open, volume, 10))"
    formula_fields = ("close", "open", "volume")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        return_delta = self._per_asset("returns_delta3", Delta, self._returns("returns"), period=3)
        ranked_return_delta = self._panel("rank_returns_delta", CrossSectionalRank, return_delta)
        negative_ranked_delta = self._per_asset(
            "negative_ranked_returns_delta",
            Multiply,
            ranked_return_delta,
            (-1.0,) * count,
        )
        correlation = self._per_asset(
            "open_volume_correlation10",
            RollingCorrelation,
            self._field("open"),
            self._field("volume"),
            period=10,
        )
        return self._per_asset("factor", Multiply, negative_ranked_delta, correlation)


@native_alpha
class Alpha015Native(NativeAlphaBase):
    """Alpha #15: negative rolling sum of cross-ranked rolling correlation."""

    lines = ("factor",)
    alpha_id = 15
    case_id = "AF46-015"
    lookback_h = 4
    formula = "(-1 * sum(rank(correlation(rank(high), rank(volume), 3)), 3))"
    formula_fields = ("high", "volume")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        high_rank = self._panel("rank_high", CrossSectionalRank, self._field("high"))
        volume_rank = self._panel("rank_volume", CrossSectionalRank, self._field("volume"))
        correlation = self._per_asset(
            "rank_correlation3",
            RollingCorrelation,
            high_rank,
            volume_rank,
            period=3,
        )
        ranked_correlation = self._panel("rank_correlation", CrossSectionalRank, correlation)
        total = self._per_asset("sum_ranked_correlation3", RollingSum, ranked_correlation, period=3)
        return self._per_asset("negative_sum", Multiply, total, (-1.0,) * count)


@native_alpha
class Alpha016Native(NativeAlphaBase):
    """Alpha #16: negative cross-rank of five-grid rank covariance."""

    lines = ("factor",)
    alpha_id = 16
    case_id = "AF46-016"
    lookback_h = 4
    formula = "(-1 * rank(covariance(rank(high), rank(volume), 5)))"
    formula_fields = ("high", "volume")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        high_rank = self._panel("rank_high", CrossSectionalRank, self._field("high"))
        volume_rank = self._panel("rank_volume", CrossSectionalRank, self._field("volume"))
        covariance = self._per_asset(
            "rank_covariance5",
            RollingCovariance,
            high_rank,
            volume_rank,
            period=5,
        )
        ranked_covariance = self._panel("rank_covariance", CrossSectionalRank, covariance)
        return self._per_asset(
            "negative_ranked_covariance",
            Multiply,
            ranked_covariance,
            (-1.0,) * count,
        )


@native_alpha
class Alpha017Native(NativeAlphaBase):
    """Alpha #17: three cross-ranked branches, including dollar-volume ADV."""

    lines = ("factor",)
    alpha_id = 17
    case_id = "AF46-017"
    lookback_h = 23
    formula = "(((-1 * rank(ts_rank(close, 10))) * rank(delta(delta(close, 1), 1))) * rank(ts_rank((volume / adv20), 5)))"
    formula_fields = ("close", "volume", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        close_ts_rank = self._per_asset("close_ts_rank10", TsRank, self._field("close"), period=10)
        ranked_close_ts_rank = self._panel("rank_close_ts_rank", CrossSectionalRank, close_ts_rank)
        negative_close_rank = self._per_asset(
            "negative_ranked_close_ts_rank",
            Multiply,
            ranked_close_ts_rank,
            (-1.0,) * count,
        )

        close_delta1 = self._per_asset("close_delta1", Delta, self._field("close"), period=1)
        second_difference = self._per_asset("close_second_delta1", Delta, close_delta1, period=1)
        ranked_second_difference = self._panel(
            "rank_close_second_delta", CrossSectionalRank, second_difference
        )
        first_product = self._per_asset(
            "first_rank_product", Multiply, negative_close_rank, ranked_second_difference
        )

        volume_over_adv = self._per_asset(
            "volume_over_adv20",
            Divide,
            self._field("volume"),
            self._field("adv20"),
        )
        volume_adv_ts_rank = self._per_asset(
            "volume_adv_ts_rank5", TsRank, volume_over_adv, period=5
        )
        ranked_volume_adv_ts_rank = self._panel(
            "rank_volume_adv_ts_rank", CrossSectionalRank, volume_adv_ts_rank
        )
        return self._per_asset("factor", Multiply, first_product, ranked_volume_adv_ts_rank)


@native_alpha
class Alpha018Native(NativeAlphaBase):
    """Alpha #18: negative rank of the sum of spread volatility, spread and correlation."""

    lines = ("factor",)
    alpha_id = 18
    case_id = "AF46-018"
    lookback_h = 9
    formula = "(-1 * rank(((stddev(abs((close - open)), 5) + (close - open)) + correlation(close, open, 10))))"
    formula_fields = ("close", "open")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        spread = self._per_asset(
            "close_minus_open", Subtract, self._field("close"), self._field("open")
        )
        absolute_spread = self._per_asset("absolute_spread", Abs, spread)
        spread_std = self._per_asset("spread_std5", RollingStd, absolute_spread, period=5)
        std_plus_spread = self._per_asset("std_plus_spread", Add, spread_std, spread)
        correlation = self._per_asset(
            "close_open_correlation10",
            RollingCorrelation,
            self._field("close"),
            self._field("open"),
            period=10,
        )
        combined = self._per_asset("combined_spread_correlation", Add, std_plus_spread, correlation)
        ranked = self._panel("rank_combined", CrossSectionalRank, combined)
        return self._per_asset("negative_rank", Multiply, ranked, (-1.0,) * count)


@native_alpha
class Alpha019Native(NativeAlphaBase):
    """Alpha #19: seven-grid close direction times the ranked 250-grid return sum."""

    lines = ("factor",)
    alpha_id = 19
    case_id = "AF46-019"
    lookback_h = 250
    formula = "((-1 * sign(((close - delay(close, 7)) + delta(close, 7)))) * (1 + rank((1 + sum(returns, 250)))))"
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        close = self._field("close")
        close_delay7 = self._per_asset("close_delay7", Delay, close, period=7)
        close_minus_delay = self._per_asset("close_minus_delay7", Subtract, close, close_delay7)
        close_delta7 = self._per_asset("close_delta7", Delta, close, period=7)
        combined_change = self._per_asset("combined_change", Add, close_minus_delay, close_delta7)
        change_sign = self._per_asset("sign_combined_change", Sign, combined_change)
        negative_change_sign = self._per_asset(
            "negative_sign", Multiply, change_sign, (-1.0,) * count
        )

        returns_sum = self._per_asset(
            "returns_sum250", RollingSum, self._returns("returns"), period=250
        )
        sum_plus_one = self._per_asset("sum_plus_one", Add, (1.0,) * count, returns_sum)
        ranked_return_sum = self._panel("rank_sum_plus_one", CrossSectionalRank, sum_plus_one)
        rank_plus_one = self._per_asset("rank_plus_one", Add, (1.0,) * count, ranked_return_sum)
        return self._per_asset("factor", Multiply, negative_change_sign, rank_plus_one)


@native_alpha
class Alpha020Native(NativeAlphaBase):
    """Alpha #20: product of three cross-sectional open-minus-prior ranks."""

    lines = ("factor",)
    alpha_id = 20
    case_id = "AF46-020"
    lookback_h = 1
    formula = "(((-1 * rank((open - delay(high, 1)))) * rank((open - delay(close, 1)))) * rank((open - delay(low, 1))))"
    formula_fields = ("open", "high", "close", "low")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        open_ = self._field("open")
        high_delay = self._per_asset("high_delay1", Delay, self._field("high"), period=1)
        close_delay = self._per_asset("close_delay1", Delay, self._field("close"), period=1)
        low_delay = self._per_asset("low_delay1", Delay, self._field("low"), period=1)
        open_minus_high = self._per_asset("open_minus_high_delay", Subtract, open_, high_delay)
        open_minus_close = self._per_asset("open_minus_close_delay", Subtract, open_, close_delay)
        open_minus_low = self._per_asset("open_minus_low_delay", Subtract, open_, low_delay)
        rank_high = self._panel("rank_open_minus_high_delay", CrossSectionalRank, open_minus_high)
        negative_rank_high = self._per_asset(
            "negative_rank_open_minus_high_delay",
            Multiply,
            rank_high,
            (-1.0,) * count,
        )
        rank_close = self._panel(
            "rank_open_minus_close_delay", CrossSectionalRank, open_minus_close
        )
        first_product = self._per_asset(
            "first_rank_product", Multiply, negative_rank_high, rank_close
        )
        rank_low = self._panel("rank_open_minus_low_delay", CrossSectionalRank, open_minus_low)
        return self._per_asset("factor", Multiply, first_product, rank_low)


BATCH_FACTORS = MappingProxyType(
    {
        5: Alpha005Native,
        6: Alpha006Native,
        8: Alpha008Native,
        10: Alpha010Native,
        11: Alpha011Native,
        12: Alpha012Native,
        14: Alpha014Native,
        15: Alpha015Native,
        16: Alpha016Native,
        17: Alpha017Native,
        18: Alpha018Native,
        19: Alpha019Native,
        20: Alpha020Native,
    }
)


__all__ = (
    "Alpha005Native",
    "Alpha006Native",
    "Alpha008Native",
    "Alpha010Native",
    "Alpha011Native",
    "Alpha012Native",
    "Alpha014Native",
    "Alpha015Native",
    "Alpha016Native",
    "Alpha017Native",
    "Alpha018Native",
    "Alpha019Native",
    "Alpha020Native",
    "BATCH_FACTORS",
)
