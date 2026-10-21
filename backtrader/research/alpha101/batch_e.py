"""Explicit native Alpha101 formula trees for the fifth Iteration 46 batch.

The classes compose the frozen Appendix A formulas from native Backtrader
indicators and alpha101-v1 operators.  They do not parse or compile formula
text and do not introduce a second scheduler.
"""

from types import MappingProxyType

from ..operators import (
    Abs,
    Add,
    CrossSectionalRank,
    DecayLinear,
    Delay,
    Delta,
    Divide,
    IndNeutralize,
    LessThan,
    Maximum,
    Minimum,
    Multiply,
    Power,
    RollingCorrelation,
    RollingSum,
    Subtract,
    TsArgMin,
    TsMax,
    TsMin,
    TsRank,
)
from ._base import NativeAlphaBase, native_alpha


@native_alpha
class Alpha082Native(NativeAlphaBase):
    """Alpha #82: pointwise minimum of a ranked open change and sector branch."""

    lines = ("factor",)
    alpha_id = 82
    case_id = "AF46-082"
    lookback_h = 33
    formula = "(min(rank(decay_linear(delta(open, 1.46063), 14.8717)), Ts_Rank(decay_linear(correlation(IndNeutralize(volume, IndClass.sector), ((open * 0.634196) + (open * (1 - 0.634196))), 17.4842), 6.92131), 13.4283)) * -1)"
    formula_fields = ("open", "volume")
    required_fields = formula_fields
    classification_levels = ("sector",)
    classification_fields = ("sector",)

    def _make_formula(self):
        count = len(self.datas)
        open_delta = self._per_asset("open_delta", Delta, self._field("open"), period=1.46063)
        open_decay = self._per_asset("open_decay14", DecayLinear, open_delta, period=14.8717)
        ranked_open_decay = self._panel("rank_open_decay", CrossSectionalRank, open_decay)

        alpha = self._per_asset("open_weight_a", Multiply, self._field("open"), (0.634196,) * count)
        one_minus_alpha = self._per_asset(
            "one_minus_open_weight", Subtract, (1.0,) * count, (0.634196,) * count
        )
        beta = self._per_asset("open_weight_b", Multiply, self._field("open"), one_minus_alpha)
        weighted_open = self._per_asset("weighted_open", Add, alpha, beta)

        neutral_volume = self._panel(
            "sector_neutral_volume",
            IndNeutralize,
            self._field("volume"),
            level="sector",
        )
        correlation = self._per_asset(
            "volume_open_correlation",
            RollingCorrelation,
            neutral_volume,
            weighted_open,
            period=17.4842,
        )
        correlation_decay = self._per_asset(
            "correlation_decay6", DecayLinear, correlation, period=6.92131
        )
        correlation_time_rank = self._per_asset(
            "correlation_time_rank13", TsRank, correlation_decay, period=13.4283
        )
        minimum = self._per_asset(
            "minimum_of_ranked_branches",
            Minimum,
            ranked_open_decay,
            correlation_time_rank,
        )
        return self._per_asset("negative_minimum", Multiply, minimum, (-1.0,) * count)


@native_alpha
class Alpha083Native(NativeAlphaBase):
    """Alpha #83: delayed range rank, nested volume rank, and VWAP ratio."""

    lines = ("factor",)
    alpha_id = 83
    case_id = "AF46-083"
    lookback_h = 6
    formula = "((rank(delay(((high - low) / (sum(close, 5) / 5)), 2)) * rank(rank(volume))) / (((high - low) / (sum(close, 5) / 5)) / (vwap - close)))"
    formula_fields = ("high", "low", "close", "volume", "vwap")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        high_minus_low = self._per_asset(
            "high_minus_low", Subtract, self._field("high"), self._field("low")
        )
        close_mean = self._per_asset(
            "close_mean5",
            Divide,
            self._per_asset("close_sum5", RollingSum, self._field("close"), period=5),
            (5.0,) * count,
        )
        range_over_close_mean = self._per_asset(
            "range_over_close_mean", Divide, high_minus_low, close_mean
        )
        delayed_range = self._per_asset("delayed_range", Delay, range_over_close_mean, period=2)
        ranked_delayed_range = self._panel("rank_delayed_range", CrossSectionalRank, delayed_range)
        ranked_volume = self._panel("rank_volume", CrossSectionalRank, self._field("volume"))
        ranked_ranked_volume = self._panel("rank_ranked_volume", CrossSectionalRank, ranked_volume)
        numerator = self._per_asset(
            "rank_product", Multiply, ranked_delayed_range, ranked_ranked_volume
        )
        vwap_minus_close = self._per_asset(
            "vwap_minus_close", Subtract, self._field("vwap"), self._field("close")
        )
        denominator = self._per_asset(
            "range_over_close_mean_over_vwap_gap",
            Divide,
            range_over_close_mean,
            vwap_minus_close,
        )
        return self._per_asset("factor", Divide, numerator, denominator)


@native_alpha
class Alpha085Native(NativeAlphaBase):
    """Alpha #85: ordinary power of two ranked rolling correlations."""

    lines = ("factor",)
    alpha_id = 85
    case_id = "AF46-085"
    lookback_h = 37
    formula = "(rank(correlation(((high * 0.876703) + (close * (1 - 0.876703))), adv30, 9.61331))^rank(correlation(Ts_Rank(((high + low) / 2), 3.70596), Ts_Rank(volume, 10.1595), 7.11408)))"
    formula_fields = ("high", "close", "low", "volume", "dollar_volume", "adv30")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        one_minus_alpha = self._per_asset(
            "one_minus_high_weight", Subtract, (1.0,) * count, (0.876703,) * count
        )
        high_part = self._per_asset("high_part", Multiply, self._field("high"), (0.876703,) * count)
        close_part = self._per_asset("close_part", Multiply, self._field("close"), one_minus_alpha)
        weighted_price = self._per_asset("weighted_price", Add, high_part, close_part)
        first_correlation = self._per_asset(
            "weighted_price_adv30_correlation",
            RollingCorrelation,
            weighted_price,
            self._field("adv30"),
            period=9.61331,
        )
        ranked_first_correlation = self._panel(
            "rank_weighted_price_adv30_correlation",
            CrossSectionalRank,
            first_correlation,
        )

        midpoint = self._per_asset(
            "high_low_midpoint",
            Divide,
            self._per_asset("high_plus_low", Add, self._field("high"), self._field("low")),
            (2.0,) * count,
        )
        midpoint_time_rank = self._per_asset("midpoint_time_rank", TsRank, midpoint, period=3.70596)
        volume_time_rank = self._per_asset(
            "volume_time_rank", TsRank, self._field("volume"), period=10.1595
        )
        second_correlation = self._per_asset(
            "ranked_series_correlation",
            RollingCorrelation,
            midpoint_time_rank,
            volume_time_rank,
            period=7.11408,
        )
        ranked_second_correlation = self._panel(
            "rank_ranked_series_correlation",
            CrossSectionalRank,
            second_correlation,
        )
        return self._per_asset(
            "ordinary_power", Power, ranked_first_correlation, ranked_second_correlation
        )


@native_alpha
class Alpha086Native(NativeAlphaBase):
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

    def _make_formula(self):
        count = len(self.datas)
        adv_sum = self._per_asset("adv20_sum14", RollingSum, self._field("adv20"), period=14.7444)
        correlation = self._per_asset(
            "close_adv_sum_correlation",
            RollingCorrelation,
            self._field("close"),
            adv_sum,
            period=6.00049,
        )
        time_rank = self._per_asset("correlation_time_rank20", TsRank, correlation, period=20.4195)
        open_plus_close = self._per_asset(
            "open_plus_close", Add, self._field("open"), self._field("close")
        )
        vwap_plus_open = self._per_asset(
            "vwap_plus_open", Add, self._field("vwap"), self._field("open")
        )
        ranked_expression_input = self._per_asset(
            "open_close_minus_vwap_open",
            Subtract,
            open_plus_close,
            vwap_plus_open,
        )
        ranked_expression = self._panel(
            "rank_open_close_minus_vwap_open",
            CrossSectionalRank,
            ranked_expression_input,
        )
        less_than = self._per_asset("time_rank_less_rank", LessThan, time_rank, ranked_expression)
        return self._per_asset("negative_comparison", Multiply, less_than, (-1.0,) * count)


@native_alpha
class Alpha087Native(NativeAlphaBase):
    """Alpha #87: maximum of a weighted-price rank and industry-neutral branch."""

    lines = ("factor",)
    alpha_id = 87
    case_id = "AF46-087"
    lookback_h = 108
    formula = "(max(rank(decay_linear(delta(((close * 0.369701) + (vwap * (1 - 0.369701))), 1.91233), 2.65461)), Ts_Rank(decay_linear(abs(correlation(IndNeutralize(adv81, IndClass.industry), close, 13.4132)), 4.89768), 14.4535)) * -1)"
    formula_fields = ("close", "vwap", "dollar_volume", "adv81")
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ("industry",)

    def _make_formula(self):
        count = len(self.datas)
        alpha = 0.369701
        one_minus_alpha = self._per_asset(
            "one_minus_close_weight", Subtract, (1.0,) * count, (alpha,) * count
        )
        close_part = self._per_asset("close_part", Multiply, self._field("close"), (alpha,) * count)
        vwap_part = self._per_asset("vwap_part", Multiply, self._field("vwap"), one_minus_alpha)
        weighted_price = self._per_asset("weighted_price", Add, close_part, vwap_part)
        price_change = self._per_asset(
            "weighted_price_delta", Delta, weighted_price, period=1.91233
        )
        decayed_change = self._per_asset(
            "weighted_price_decay", DecayLinear, price_change, period=2.65461
        )
        ranked_change = self._panel("rank_weighted_price_decay", CrossSectionalRank, decayed_change)

        neutral_adv81 = self._panel(
            "industry_neutral_adv81",
            IndNeutralize,
            self._field("adv81"),
            level="industry",
        )
        correlation = self._per_asset(
            "neutral_adv_close_correlation",
            RollingCorrelation,
            neutral_adv81,
            self._field("close"),
            period=13.4132,
        )
        absolute_correlation = self._per_asset(
            "absolute_neutral_adv_close_correlation", Abs, correlation
        )
        correlation_decay = self._per_asset(
            "correlation_decay4", DecayLinear, absolute_correlation, period=4.89768
        )
        correlation_time_rank = self._per_asset(
            "correlation_time_rank14", TsRank, correlation_decay, period=14.4535
        )
        maximum = self._per_asset(
            "maximum_of_ranked_branches",
            Maximum,
            ranked_change,
            correlation_time_rank,
        )
        return self._per_asset("negative_maximum", Multiply, maximum, (-1.0,) * count)


@native_alpha
class Alpha088Native(NativeAlphaBase):
    """Alpha #88: pointwise minimum of an OHLC rank spread and TS branch."""

    lines = ("factor",)
    alpha_id = 88
    case_id = "AF46-088"
    lookback_h = 91
    formula = "min(rank(decay_linear(((rank(open) + rank(low)) - (rank(high) + rank(close))), 8.06882)), Ts_Rank(decay_linear(correlation(Ts_Rank(close, 8.44728), Ts_Rank(adv60, 20.6966), 8.01266), 6.65053), 2.61957))"
    formula_fields = ("open", "low", "high", "close", "dollar_volume", "adv60")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        open_rank = self._panel("rank_open", CrossSectionalRank, self._field("open"))
        low_rank = self._panel("rank_low", CrossSectionalRank, self._field("low"))
        high_rank = self._panel("rank_high", CrossSectionalRank, self._field("high"))
        close_rank = self._panel("rank_close", CrossSectionalRank, self._field("close"))
        low_rank_sum = self._per_asset("open_rank_plus_low_rank", Add, open_rank, low_rank)
        high_rank_sum = self._per_asset("high_rank_plus_close_rank", Add, high_rank, close_rank)
        rank_spread = self._per_asset("rank_spread", Subtract, low_rank_sum, high_rank_sum)
        spread_decay = self._per_asset(
            "rank_spread_decay", DecayLinear, rank_spread, period=8.06882
        )
        ranked_spread_decay = self._panel("rank_decayed_spread", CrossSectionalRank, spread_decay)

        close_time_rank = self._per_asset(
            "close_time_rank8", TsRank, self._field("close"), period=8.44728
        )
        adv60_time_rank = self._per_asset(
            "adv60_time_rank20", TsRank, self._field("adv60"), period=20.6966
        )
        correlation = self._per_asset(
            "time_rank_correlation",
            RollingCorrelation,
            close_time_rank,
            adv60_time_rank,
            period=8.01266,
        )
        correlation_decay = self._per_asset(
            "correlation_decay6", DecayLinear, correlation, period=6.65053
        )
        correlation_time_rank = self._per_asset(
            "correlation_time_rank2", TsRank, correlation_decay, period=2.61957
        )
        return self._per_asset(
            "minimum_of_branches",
            Minimum,
            ranked_spread_decay,
            correlation_time_rank,
        )


@native_alpha
class Alpha089Native(NativeAlphaBase):
    """Alpha #89: subtract an industry-neutral VWAP delta branch from a low/ADV branch."""

    lines = ("factor",)
    alpha_id = 89
    case_id = "AF46-089"
    lookback_h = 26
    formula = "(Ts_Rank(decay_linear(correlation(((low * 0.967285) + (low * (1 - 0.967285))), adv10, 6.94279), 5.51607), 3.79744) - Ts_Rank(decay_linear(delta(IndNeutralize(vwap, IndClass.industry), 3.48158), 10.1466), 15.3012))"
    formula_fields = ("low", "vwap", "dollar_volume", "adv10")
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ("industry",)

    def _make_formula(self):
        count = len(self.datas)
        alpha = 0.967285
        one_minus_alpha = self._per_asset(
            "one_minus_low_weight", Subtract, (1.0,) * count, (alpha,) * count
        )
        low_part_a = self._per_asset("low_part_a", Multiply, self._field("low"), (alpha,) * count)
        low_part_b = self._per_asset("low_part_b", Multiply, self._field("low"), one_minus_alpha)
        weighted_low = self._per_asset("weighted_low", Add, low_part_a, low_part_b)
        low_adv_correlation = self._per_asset(
            "weighted_low_adv10_correlation",
            RollingCorrelation,
            weighted_low,
            self._field("adv10"),
            period=6.94279,
        )
        low_correlation_decay = self._per_asset(
            "low_correlation_decay", DecayLinear, low_adv_correlation, period=5.51607
        )
        low_time_rank = self._per_asset(
            "low_branch_time_rank", TsRank, low_correlation_decay, period=3.79744
        )

        neutral_vwap = self._panel(
            "industry_neutral_vwap",
            IndNeutralize,
            self._field("vwap"),
            level="industry",
        )
        neutral_vwap_delta = self._per_asset(
            "neutral_vwap_delta", Delta, neutral_vwap, period=3.48158
        )
        vwap_delta_decay = self._per_asset(
            "neutral_vwap_delta_decay", DecayLinear, neutral_vwap_delta, period=10.1466
        )
        vwap_branch_time_rank = self._per_asset(
            "vwap_branch_time_rank", TsRank, vwap_delta_decay, period=15.3012
        )
        return self._per_asset("branch_difference", Subtract, low_time_rank, vwap_branch_time_rank)


@native_alpha
class Alpha090Native(NativeAlphaBase):
    """Alpha #90: ordinary power with a subindustry-neutral rolling-correlation exponent."""

    lines = ("factor",)
    alpha_id = 90
    case_id = "AF46-090"
    lookback_h = 45
    formula = "((rank((close - ts_max(close, 4.66719)))^Ts_Rank(correlation(IndNeutralize(adv40, IndClass.subindustry), low, 5.38375), 3.21856)) * -1)"
    formula_fields = ("close", "low", "dollar_volume", "adv40")
    required_fields = formula_fields
    classification_levels = ("subindustry",)
    classification_fields = ("subindustry",)

    def _make_formula(self):
        count = len(self.datas)
        close_maximum = self._per_asset(
            "close_ts_max4", TsMax, self._field("close"), period=4.66719
        )
        close_minus_maximum = self._per_asset(
            "close_minus_ts_max", Subtract, self._field("close"), close_maximum
        )
        ranked_close_gap = self._panel("rank_close_gap", CrossSectionalRank, close_minus_maximum)
        neutral_adv40 = self._panel(
            "subindustry_neutral_adv40",
            IndNeutralize,
            self._field("adv40"),
            level="subindustry",
        )
        correlation = self._per_asset(
            "neutral_adv40_low_correlation",
            RollingCorrelation,
            neutral_adv40,
            self._field("low"),
            period=5.38375,
        )
        exponent = self._per_asset("correlation_time_rank", TsRank, correlation, period=3.21856)
        powered = self._per_asset("ordinary_power", Power, ranked_close_gap, exponent)
        return self._per_asset("negative_power", Multiply, powered, (-1.0,) * count)


@native_alpha
class Alpha091Native(NativeAlphaBase):
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

    def _make_formula(self):
        count = len(self.datas)
        neutral_close = self._panel(
            "industry_neutral_close",
            IndNeutralize,
            self._field("close"),
            level="industry",
        )
        close_volume_correlation = self._per_asset(
            "neutral_close_volume_correlation",
            RollingCorrelation,
            neutral_close,
            self._field("volume"),
            period=9.74928,
        )
        first_decay = self._per_asset(
            "neutral_correlation_decay16",
            DecayLinear,
            close_volume_correlation,
            period=16.398,
        )
        second_decay = self._per_asset(
            "neutral_correlation_decay3", DecayLinear, first_decay, period=3.83219
        )
        first_branch = self._per_asset(
            "first_branch_time_rank", TsRank, second_decay, period=4.8667
        )

        vwap_adv_correlation = self._per_asset(
            "vwap_adv30_correlation",
            RollingCorrelation,
            self._field("vwap"),
            self._field("adv30"),
            period=4.01303,
        )
        vwap_adv_decay = self._per_asset(
            "vwap_adv_correlation_decay", DecayLinear, vwap_adv_correlation, period=2.6809
        )
        second_branch = self._panel("rank_vwap_adv_decay", CrossSectionalRank, vwap_adv_decay)
        difference = self._per_asset("branch_difference", Subtract, first_branch, second_branch)
        return self._per_asset("negative_difference", Multiply, difference, (-1.0,) * count)


@native_alpha
class Alpha093Native(NativeAlphaBase):
    """Alpha #93: industry-neutral VWAP/ADV history divided by a ranked price branch."""

    lines = ("factor",)
    alpha_id = 93
    case_id = "AF46-093"
    lookback_h = 120
    formula = "(Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, IndClass.industry), adv81, 17.4193), 19.848), 7.54455) / rank(decay_linear(delta(((close * 0.524434) + (vwap * (1 - 0.524434))), 2.77377), 16.2664)))"
    formula_fields = ("vwap", "close", "dollar_volume", "adv81")
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ("industry",)

    def _make_formula(self):
        count = len(self.datas)
        neutral_vwap = self._panel(
            "industry_neutral_vwap",
            IndNeutralize,
            self._field("vwap"),
            level="industry",
        )
        vwap_adv_correlation = self._per_asset(
            "neutral_vwap_adv81_correlation",
            RollingCorrelation,
            neutral_vwap,
            self._field("adv81"),
            period=17.4193,
        )
        correlation_decay = self._per_asset(
            "neutral_correlation_decay19",
            DecayLinear,
            vwap_adv_correlation,
            period=19.848,
        )
        numerator = self._per_asset(
            "numerator_time_rank", TsRank, correlation_decay, period=7.54455
        )

        alpha = 0.524434
        one_minus_alpha = self._per_asset(
            "one_minus_close_weight", Subtract, (1.0,) * count, (alpha,) * count
        )
        close_part = self._per_asset("close_part", Multiply, self._field("close"), (alpha,) * count)
        vwap_part = self._per_asset("vwap_part", Multiply, self._field("vwap"), one_minus_alpha)
        weighted_price = self._per_asset("weighted_price", Add, close_part, vwap_part)
        price_delta = self._per_asset("weighted_price_delta", Delta, weighted_price, period=2.77377)
        price_delta_decay = self._per_asset(
            "weighted_price_delta_decay", DecayLinear, price_delta, period=16.2664
        )
        denominator = self._panel(
            "rank_weighted_price_delta_decay",
            CrossSectionalRank,
            price_delta_decay,
        )
        return self._per_asset("factor", Divide, numerator, denominator)


@native_alpha
class Alpha094Native(NativeAlphaBase):
    """Alpha #94: ordinary power of VWAP range rank and a ranked TS branch."""

    lines = ("factor",)
    alpha_id = 94
    case_id = "AF46-094"
    lookback_h = 80
    formula = "((rank((vwap - ts_min(vwap, 11.5783)))^Ts_Rank(correlation(Ts_Rank(vwap, 19.6462), Ts_Rank(adv60, 4.02992), 18.0926), 2.70756)) * -1)"
    formula_fields = ("vwap", "dollar_volume", "adv60")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        vwap_minimum = self._per_asset("vwap_ts_min11", TsMin, self._field("vwap"), period=11.5783)
        vwap_minus_minimum = self._per_asset(
            "vwap_minus_ts_min", Subtract, self._field("vwap"), vwap_minimum
        )
        ranked_vwap_gap = self._panel("rank_vwap_gap", CrossSectionalRank, vwap_minus_minimum)
        vwap_time_rank = self._per_asset(
            "vwap_time_rank19", TsRank, self._field("vwap"), period=19.6462
        )
        adv60_time_rank = self._per_asset(
            "adv60_time_rank4", TsRank, self._field("adv60"), period=4.02992
        )
        correlation = self._per_asset(
            "time_rank_correlation",
            RollingCorrelation,
            vwap_time_rank,
            adv60_time_rank,
            period=18.0926,
        )
        exponent = self._per_asset("correlation_time_rank", TsRank, correlation, period=2.70756)
        powered = self._per_asset("ordinary_power", Power, ranked_vwap_gap, exponent)
        return self._per_asset("negative_power", Multiply, powered, (-1.0,) * count)


@native_alpha
class Alpha095Native(NativeAlphaBase):
    """Alpha #95: compare the open range rank with a powered TS rank."""

    lines = ("factor",)
    alpha_id = 95
    case_id = "AF46-095"
    lookback_h = 78
    formula = "(rank((open - ts_min(open, 12.4105))) < Ts_Rank((rank(correlation(sum(((high + low) / 2), 19.1351), sum(adv40, 19.1351), 12.8742))^5), 11.7584))"
    formula_fields = ("open", "high", "low", "dollar_volume", "adv40")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        open_minimum = self._per_asset("open_ts_min12", TsMin, self._field("open"), period=12.4105)
        open_minus_minimum = self._per_asset(
            "open_minus_ts_min", Subtract, self._field("open"), open_minimum
        )
        ranked_open_gap = self._panel("rank_open_gap", CrossSectionalRank, open_minus_minimum)

        high_low_midpoint = self._per_asset(
            "high_low_midpoint",
            Divide,
            self._per_asset("high_plus_low", Add, self._field("high"), self._field("low")),
            (2.0,) * count,
        )
        midpoint_sum = self._per_asset(
            "high_low_midpoint_sum19", RollingSum, high_low_midpoint, period=19.1351
        )
        adv40_sum = self._per_asset("adv40_sum19", RollingSum, self._field("adv40"), period=19.1351)
        correlation = self._per_asset(
            "midpoint_adv40_correlation",
            RollingCorrelation,
            midpoint_sum,
            adv40_sum,
            period=12.8742,
        )
        ranked_correlation = self._panel(
            "rank_midpoint_adv40_correlation",
            CrossSectionalRank,
            correlation,
        )
        powered_rank = self._per_asset(
            "ranked_correlation_power5", Power, ranked_correlation, (5.0,) * count
        )
        time_rank = self._per_asset(
            "powered_correlation_time_rank", TsRank, powered_rank, period=11.7584
        )
        return self._per_asset("comparison", LessThan, ranked_open_gap, time_rank)


@native_alpha
class Alpha097Native(NativeAlphaBase):
    """Alpha #97: ranked industry-neutral delta minus a nested TS-rank branch."""

    lines = ("factor",)
    alpha_id = 97
    case_id = "AF46-097"
    lookback_h = 114
    formula = "((rank(decay_linear(delta(IndNeutralize(((low * 0.721001) + (vwap * (1 - 0.721001))), IndClass.industry), 3.3705), 20.4523)) - Ts_Rank(decay_linear(Ts_Rank(correlation(Ts_Rank(low, 7.87871), Ts_Rank(adv60, 17.255), 4.97547), 18.5925), 15.7152), 6.71659)) * -1)"
    formula_fields = ("low", "vwap", "dollar_volume", "adv60")
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ("industry",)

    def _make_formula(self):
        count = len(self.datas)
        alpha = 0.721001
        one_minus_alpha = self._per_asset(
            "one_minus_low_weight", Subtract, (1.0,) * count, (alpha,) * count
        )
        low_part = self._per_asset("low_part", Multiply, self._field("low"), (alpha,) * count)
        vwap_part = self._per_asset("vwap_part", Multiply, self._field("vwap"), one_minus_alpha)
        weighted_price = self._per_asset("weighted_price", Add, low_part, vwap_part)
        neutral_price = self._panel(
            "industry_neutral_weighted_price",
            IndNeutralize,
            weighted_price,
            level="industry",
        )
        price_delta = self._per_asset("neutral_price_delta", Delta, neutral_price, period=3.3705)
        price_decay = self._per_asset(
            "neutral_price_delta_decay", DecayLinear, price_delta, period=20.4523
        )
        ranked_price_decay = self._panel(
            "rank_neutral_price_decay", CrossSectionalRank, price_decay
        )

        low_time_rank = self._per_asset(
            "low_time_rank7", TsRank, self._field("low"), period=7.87871
        )
        adv60_time_rank = self._per_asset(
            "adv60_time_rank17", TsRank, self._field("adv60"), period=17.255
        )
        correlation = self._per_asset(
            "ranked_series_correlation",
            RollingCorrelation,
            low_time_rank,
            adv60_time_rank,
            period=4.97547,
        )
        correlation_time_rank = self._per_asset(
            "correlation_time_rank18", TsRank, correlation, period=18.5925
        )
        correlation_decay = self._per_asset(
            "correlation_time_rank_decay15",
            DecayLinear,
            correlation_time_rank,
            period=15.7152,
        )
        nested_time_rank = self._per_asset(
            "nested_time_rank6", TsRank, correlation_decay, period=6.71659
        )
        difference = self._per_asset(
            "ranked_price_minus_nested_time_rank",
            Subtract,
            ranked_price_decay,
            nested_time_rank,
        )
        return self._per_asset("negative_difference", Multiply, difference, (-1.0,) * count)


@native_alpha
class Alpha098Native(NativeAlphaBase):
    """Alpha #98: subtract a nested open/ADV argmin branch from a VWAP branch."""

    lines = ("factor",)
    alpha_id = 98
    case_id = "AF46-098"
    lookback_h = 52
    formula = "(rank(decay_linear(correlation(vwap, sum(adv5, 26.4719), 4.58418), 7.18088)) - rank(decay_linear(Ts_Rank(Ts_ArgMin(correlation(rank(open), rank(adv15), 20.8187), 8.62571), 6.95668), 8.07206)))"
    formula_fields = ("vwap", "open", "dollar_volume", "adv5", "adv15")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        adv5_sum = self._per_asset("adv5_sum26", RollingSum, self._field("adv5"), period=26.4719)
        vwap_adv5_correlation = self._per_asset(
            "vwap_adv5_sum_correlation",
            RollingCorrelation,
            self._field("vwap"),
            adv5_sum,
            period=4.58418,
        )
        vwap_adv5_decay = self._per_asset(
            "vwap_adv5_correlation_decay", DecayLinear, vwap_adv5_correlation, period=7.18088
        )
        first_branch = self._panel("rank_vwap_adv5_decay", CrossSectionalRank, vwap_adv5_decay)

        open_rank = self._panel("rank_open", CrossSectionalRank, self._field("open"))
        adv15_rank = self._panel("rank_adv15", CrossSectionalRank, self._field("adv15"))
        ranked_series_correlation = self._per_asset(
            "ranked_open_adv15_correlation",
            RollingCorrelation,
            open_rank,
            adv15_rank,
            period=20.8187,
        )
        argmin = self._per_asset(
            "correlation_argmin8", TsArgMin, ranked_series_correlation, period=8.62571
        )
        argmin_time_rank = self._per_asset("argmin_time_rank6", TsRank, argmin, period=6.95668)
        argmin_decay = self._per_asset(
            "argmin_time_rank_decay8", DecayLinear, argmin_time_rank, period=8.07206
        )
        second_branch = self._panel("rank_argmin_decay", CrossSectionalRank, argmin_decay)
        return self._per_asset("branch_difference", Subtract, first_branch, second_branch)


@native_alpha
class Alpha099Native(NativeAlphaBase):
    """Alpha #99: compare two ranked rolling correlations and negate the result."""

    lines = ("factor",)
    alpha_id = 99
    case_id = "AF46-099"
    lookback_h = 84
    formula = "((rank(correlation(sum(((high + low) / 2), 19.8975), sum(adv60, 19.8975), 8.8136)) < rank(correlation(low, volume, 6.28259))) * -1)"
    formula_fields = ("high", "low", "volume", "dollar_volume", "adv60")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()

    def _make_formula(self):
        count = len(self.datas)
        midpoint = self._per_asset(
            "high_low_midpoint",
            Divide,
            self._per_asset("high_plus_low", Add, self._field("high"), self._field("low")),
            (2.0,) * count,
        )
        midpoint_sum = self._per_asset("midpoint_sum19", RollingSum, midpoint, period=19.8975)
        adv60_sum = self._per_asset("adv60_sum19", RollingSum, self._field("adv60"), period=19.8975)
        first_correlation = self._per_asset(
            "midpoint_adv60_correlation",
            RollingCorrelation,
            midpoint_sum,
            adv60_sum,
            period=8.8136,
        )
        ranked_first_correlation = self._panel(
            "rank_midpoint_adv60_correlation",
            CrossSectionalRank,
            first_correlation,
        )
        second_correlation = self._per_asset(
            "low_volume_correlation",
            RollingCorrelation,
            self._field("low"),
            self._field("volume"),
            period=6.28259,
        )
        ranked_second_correlation = self._panel(
            "rank_low_volume_correlation",
            CrossSectionalRank,
            second_correlation,
        )
        comparison = self._per_asset(
            "correlation_rank_comparison",
            LessThan,
            ranked_first_correlation,
            ranked_second_correlation,
        )
        return self._per_asset("negative_comparison", Multiply, comparison, (-1.0,) * count)


BATCH_FACTORS = MappingProxyType(
    {
        82: Alpha082Native,
        83: Alpha083Native,
        85: Alpha085Native,
        86: Alpha086Native,
        87: Alpha087Native,
        88: Alpha088Native,
        89: Alpha089Native,
        90: Alpha090Native,
        91: Alpha091Native,
        93: Alpha093Native,
        94: Alpha094Native,
        95: Alpha095Native,
        97: Alpha097Native,
        98: Alpha098Native,
        99: Alpha099Native,
    }
)


__all__ = (
    "Alpha082Native",
    "Alpha083Native",
    "Alpha085Native",
    "Alpha086Native",
    "Alpha087Native",
    "Alpha088Native",
    "Alpha089Native",
    "Alpha090Native",
    "Alpha091Native",
    "Alpha093Native",
    "Alpha094Native",
    "Alpha095Native",
    "Alpha097Native",
    "Alpha098Native",
    "Alpha099Native",
    "BATCH_FACTORS",
)
