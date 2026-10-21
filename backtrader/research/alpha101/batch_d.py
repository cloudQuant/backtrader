"""Production Alpha101 formulas 64–80, excluding promoted Alpha067.

Each factor is an explicit native Indicator/Lines graph.  Formula text and
history declarations are copied from the frozen Appendix A catalog and the
independently reviewed Iteration 46 formula ledger.
"""

from types import MappingProxyType
from typing import Any, Tuple

from ..operators import (
    Add,
    CrossSectionalRank,
    DecayLinear,
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
    Sign,
    Subtract,
    TsMax,
    TsMin,
    TsRank,
)
from ._base import NativeAlphaBase, native_alpha


@native_alpha
class Alpha064Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 64
    case_id = "AF46-064"
    lookback_h = 145
    formula_fields = ("open", "low", "high", "vwap", "dollar_volume", "adv120")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    formula = "((rank(correlation(sum(((open * 0.178404) + (low * (1 - 0.178404))), 12.7054), sum(adv120, 12.7054), 16.6208)) < rank(delta(((((high + low) / 2) * 0.178404) + (vwap * (1 - 0.178404))), 3.69741))) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        weight = 0.178404
        open_part = self._per_asset(
            "open_weight", Multiply, self._field("open"), (weight,) * len(self.datas)
        )
        low_part = self._per_asset(
            "low_weight", Multiply, self._field("low"), (1.0 - weight,) * len(self.datas)
        )
        price_mix = self._per_asset("open_low_mix", Add, open_part, low_part)
        price_sum = self._per_asset("open_low_sum12", RollingSum, price_mix, period=12.7054)

        adv_sum = self._per_asset("adv120_sum12", RollingSum, self._field("adv120"), period=12.7054)
        correlation = self._per_asset(
            "sum_correlation16", RollingCorrelation, price_sum, adv_sum, period=16.6208
        )
        left_rank = self._panel("sum_correlation_rank", CrossSectionalRank, correlation)

        midpoint = self._per_asset(
            "high_low_midpoint",
            Divide,
            self._per_asset("high_low_sum", Add, self._field("high"), self._field("low")),
            (2.0,) * len(self.datas),
        )
        midpoint_part = self._per_asset(
            "midpoint_weight", Multiply, midpoint, (weight,) * len(self.datas)
        )
        vwap_part = self._per_asset(
            "vwap_weight", Multiply, self._field("vwap"), (1.0 - weight,) * len(self.datas)
        )
        delta = self._per_asset(
            "weighted_midpoint_delta3",
            Delta,
            self._per_asset("weighted_midpoint_vwap", Add, midpoint_part, vwap_part),
            period=3.69741,
        )
        right_rank = self._panel("weighted_midpoint_delta_rank", CrossSectionalRank, delta)
        comparison = self._per_asset("rank_less_than", LessThan, left_rank, right_rank)
        return self._per_asset("negative_boolean", Multiply, comparison, (-1.0,) * len(self.datas))


@native_alpha
class Alpha065Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 65
    case_id = "AF46-065"
    lookback_h = 71
    formula_fields = ("open", "vwap", "dollar_volume", "adv60")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    formula = "((rank(correlation(((open * 0.00817205) + (vwap * (1 - 0.00817205))), sum(adv60, 8.6911), 6.40374)) < rank((open - ts_min(open, 13.635)))) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        weight = 0.00817205
        weighted_open = self._per_asset(
            "weighted_open", Multiply, self._field("open"), (weight,) * len(self.datas)
        )
        weighted_vwap = self._per_asset(
            "weighted_vwap", Multiply, self._field("vwap"), (1.0 - weight,) * len(self.datas)
        )
        price_mix = self._per_asset("weighted_price", Add, weighted_open, weighted_vwap)
        adv_sum = self._per_asset("adv60_sum8", RollingSum, self._field("adv60"), period=8.6911)
        correlation = self._per_asset(
            "sum_correlation6", RollingCorrelation, price_mix, adv_sum, period=6.40374
        )
        left_rank = self._panel("sum_correlation_rank", CrossSectionalRank, correlation)

        open_min = self._per_asset("open_ts_min13", TsMin, self._field("open"), period=13.635)
        open_excess = self._per_asset("open_minus_min", Subtract, self._field("open"), open_min)
        right_rank = self._panel("open_excess_rank", CrossSectionalRank, open_excess)
        comparison = self._per_asset("rank_less_than", LessThan, left_rank, right_rank)
        return self._per_asset("negative_boolean", Multiply, comparison, (-1.0,) * len(self.datas))


@native_alpha
class Alpha066Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 66
    case_id = "AF46-066"
    lookback_h = 15
    formula_fields = ("vwap", "low", "open", "high")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    formula = "((rank(decay_linear(delta(vwap, 3.51013), 7.23052)) + Ts_Rank(decay_linear(((((low * 0.96633) + (low * (1 - 0.96633))) - vwap) / (open - ((high + low) / 2))), 11.4157), 6.72611)) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        vwap_delta = self._per_asset("vwap_delta3", Delta, self._field("vwap"), period=3.51013)
        vwap_decay = self._per_asset("vwap_delta_decay7", DecayLinear, vwap_delta, period=7.23052)
        first_rank = self._panel("vwap_delta_decay_rank", CrossSectionalRank, vwap_decay)

        low = self._field("low")
        open_ = self._field("open")
        high = self._field("high")
        weight = 0.96633
        weighted_low = self._per_asset(
            "weighted_low_first", Multiply, low, (weight,) * len(self.datas)
        )
        weighted_low_complement = self._per_asset(
            "weighted_low_second", Multiply, low, (1.0 - weight,) * len(self.datas)
        )
        low_mix = self._per_asset("weighted_low_sum", Add, weighted_low, weighted_low_complement)
        low_minus_vwap = self._per_asset(
            "low_mix_minus_vwap", Subtract, low_mix, self._field("vwap")
        )
        high_low_midpoint = self._per_asset(
            "high_low_midpoint",
            Divide,
            self._per_asset("high_low_sum", Add, high, low),
            (2.0,) * len(self.datas),
        )
        denominator = self._per_asset("open_minus_midpoint", Subtract, open_, high_low_midpoint)
        ratio = self._per_asset("weighted_low_vwap_ratio", Divide, low_minus_vwap, denominator)
        ratio_decay = self._per_asset("ratio_decay11", DecayLinear, ratio, period=11.4157)
        second = self._per_asset("ratio_ts_rank6", TsRank, ratio_decay, period=6.72611)
        combined = self._per_asset("rank_sum", Add, first_rank, second)
        return self._per_asset("negative_sum", Multiply, combined, (-1.0,) * len(self.datas))


@native_alpha
class Alpha068Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 68
    case_id = "AF46-068"
    lookback_h = 33
    formula_fields = ("high", "close", "low", "dollar_volume", "adv15")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    formula = "((Ts_Rank(correlation(rank(high), rank(adv15), 8.91644), 13.9333) < rank(delta(((close * 0.518371) + (low * (1 - 0.518371))), 1.06157))) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        high_rank = self._panel("high_rank", CrossSectionalRank, self._field("high"))
        adv_rank = self._panel("adv15_rank", CrossSectionalRank, self._field("adv15"))
        correlation = self._per_asset(
            "rank_correlation8", RollingCorrelation, high_rank, adv_rank, period=8.91644
        )
        left = self._per_asset("correlation_ts_rank13", TsRank, correlation, period=13.9333)

        weight = 0.518371
        close_part = self._per_asset(
            "weighted_close", Multiply, self._field("close"), (weight,) * len(self.datas)
        )
        low_part = self._per_asset(
            "weighted_low", Multiply, self._field("low"), (1.0 - weight,) * len(self.datas)
        )
        price_delta = self._per_asset(
            "weighted_price_delta1",
            Delta,
            self._per_asset("weighted_price", Add, close_part, low_part),
            period=1.06157,
        )
        right = self._panel("weighted_price_delta_rank", CrossSectionalRank, price_delta)
        comparison = self._per_asset("ts_rank_less_than_rank", LessThan, left, right)
        return self._per_asset("negative_boolean", Multiply, comparison, (-1.0,) * len(self.datas))


@native_alpha
class Alpha069Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 69
    case_id = "AF46-069"
    lookback_h = 30
    formula_fields = ("vwap", "close", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ("industry",)
    formula = "((rank(ts_max(delta(IndNeutralize(vwap, IndClass.industry), 2.72412), 4.79344))^Ts_Rank(correlation(((close * 0.490655) + (vwap * (1 - 0.490655))), adv20, 4.92416), 9.0615)) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        neutral_vwap = self._panel(
            "industry_neutral_vwap",
            IndNeutralize,
            self._field("vwap"),
            level="industry",
            groups=self._groups("industry"),
        )
        neutral_delta = self._per_asset("neutral_vwap_delta2", Delta, neutral_vwap, period=2.72412)
        neutral_max = self._per_asset("neutral_vwap_ts_max4", TsMax, neutral_delta, period=4.79344)
        base = self._panel("neutral_vwap_max_rank", CrossSectionalRank, neutral_max)

        weight = 0.490655
        close_part = self._per_asset(
            "weighted_close", Multiply, self._field("close"), (weight,) * len(self.datas)
        )
        vwap_part = self._per_asset(
            "weighted_vwap", Multiply, self._field("vwap"), (1.0 - weight,) * len(self.datas)
        )
        adv_correlation = self._per_asset(
            "weighted_price_adv20_corr4",
            RollingCorrelation,
            self._per_asset("weighted_price", Add, close_part, vwap_part),
            self._field("adv20"),
            period=4.92416,
        )
        exponent = self._per_asset("correlation_ts_rank9", TsRank, adv_correlation, period=9.0615)
        powered = self._per_asset("ordinary_power", Power, base, exponent)
        return self._per_asset("negative_power", Multiply, powered, (-1.0,) * len(self.datas))


@native_alpha
class Alpha070Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 70
    case_id = "AF46-070"
    lookback_h = 81
    formula_fields = ("vwap", "close", "dollar_volume", "adv50")
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ("industry",)
    formula = "((rank(delta(vwap, 1.29456))^Ts_Rank(correlation(IndNeutralize(close, IndClass.industry), adv50, 17.8256), 17.9171)) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        vwap_delta = self._per_asset("vwap_delta1", Delta, self._field("vwap"), period=1.29456)
        base = self._panel("vwap_delta_rank", CrossSectionalRank, vwap_delta)
        neutral_close = self._panel(
            "industry_neutral_close",
            IndNeutralize,
            self._field("close"),
            level="industry",
            groups=self._groups("industry"),
        )
        correlation = self._per_asset(
            "neutral_close_adv50_corr17",
            RollingCorrelation,
            neutral_close,
            self._field("adv50"),
            period=17.8256,
        )
        exponent = self._per_asset("correlation_ts_rank17", TsRank, correlation, period=17.9171)
        powered = self._per_asset("ordinary_power", Power, base, exponent)
        return self._per_asset("negative_power", Multiply, powered, (-1.0,) * len(self.datas))


@native_alpha
class Alpha071Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 71
    case_id = "AF46-071"
    lookback_h = 224
    formula_fields = ("close", "low", "open", "vwap", "dollar_volume", "adv180")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    formula = "max(Ts_Rank(decay_linear(correlation(Ts_Rank(close, 3.43976), Ts_Rank(adv180, 12.0647), 18.0175), 4.20501), 15.6948), Ts_Rank(decay_linear((rank(((low + open) - (vwap + vwap)))^2), 16.4662), 4.4388))"

    def _make_formula(self) -> Tuple[Any, ...]:
        close_rank = self._per_asset("close_ts_rank3", TsRank, self._field("close"), period=3.43976)
        adv_rank = self._per_asset(
            "adv180_ts_rank12", TsRank, self._field("adv180"), period=12.0647
        )
        correlation = self._per_asset(
            "rank_correlation18", RollingCorrelation, close_rank, adv_rank, period=18.0175
        )
        correlation_decay = self._per_asset(
            "correlation_decay4", DecayLinear, correlation, period=4.20501
        )
        first = self._per_asset("correlation_ts_rank15", TsRank, correlation_decay, period=15.6948)

        low_open = self._per_asset("low_plus_open", Add, self._field("low"), self._field("open"))
        vwap_twice = self._per_asset(
            "vwap_plus_vwap", Add, self._field("vwap"), self._field("vwap")
        )
        spread = self._per_asset("low_open_minus_vwap_twice", Subtract, low_open, vwap_twice)
        spread_rank = self._panel("spread_rank", CrossSectionalRank, spread)
        squared_rank = self._per_asset(
            "ordinary_rank_power2", Power, spread_rank, (2.0,) * len(self.datas)
        )
        spread_decay = self._per_asset("spread_decay16", DecayLinear, squared_rank, period=16.4662)
        second = self._per_asset("spread_ts_rank4", TsRank, spread_decay, period=4.4388)
        return self._per_asset("pointwise_maximum", Maximum, first, second)


@native_alpha
class Alpha072Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 72
    case_id = "AF46-072"
    lookback_h = 55
    formula_fields = ("high", "low", "vwap", "volume", "dollar_volume", "adv40")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    formula = "(rank(decay_linear(correlation(((high + low) / 2), adv40, 8.93345), 10.1519)) / rank(decay_linear(correlation(Ts_Rank(vwap, 3.72469), Ts_Rank(volume, 18.5188), 6.86671), 2.95011)))"

    def _make_formula(self) -> Tuple[Any, ...]:
        midpoint = self._per_asset(
            "high_low_midpoint",
            Divide,
            self._per_asset("high_low_sum", Add, self._field("high"), self._field("low")),
            (2.0,) * len(self.datas),
        )
        left_correlation = self._per_asset(
            "midpoint_adv40_corr8",
            RollingCorrelation,
            midpoint,
            self._field("adv40"),
            period=8.93345,
        )
        left_decay = self._per_asset("left_decay10", DecayLinear, left_correlation, period=10.1519)
        numerator = self._panel("left_rank", CrossSectionalRank, left_decay)

        vwap_rank = self._per_asset("vwap_ts_rank3", TsRank, self._field("vwap"), period=3.72469)
        volume_rank = self._per_asset(
            "volume_ts_rank18", TsRank, self._field("volume"), period=18.5188
        )
        right_correlation = self._per_asset(
            "ts_rank_correlation6",
            RollingCorrelation,
            vwap_rank,
            volume_rank,
            period=6.86671,
        )
        right_decay = self._per_asset(
            "right_decay2", DecayLinear, right_correlation, period=2.95011
        )
        denominator = self._panel("right_rank", CrossSectionalRank, right_decay)
        return self._per_asset("rank_ratio", Divide, numerator, denominator)


@native_alpha
class Alpha073Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 73
    case_id = "AF46-073"
    lookback_h = 19
    formula_fields = ("vwap", "open", "low")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    formula = "(max(rank(decay_linear(delta(vwap, 4.72775), 2.91864)), Ts_Rank(decay_linear(((delta(((open * 0.147155) + (low * (1 - 0.147155))), 2.03608) / ((open * 0.147155) + (low * (1 - 0.147155)))) * -1), 3.33829), 16.7411)) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        vwap_delta = self._per_asset("vwap_delta4", Delta, self._field("vwap"), period=4.72775)
        vwap_decay = self._per_asset("vwap_delta_decay2", DecayLinear, vwap_delta, period=2.91864)
        first = self._panel("vwap_delta_decay_rank", CrossSectionalRank, vwap_decay)

        weight = 0.147155
        open_part = self._per_asset(
            "weighted_open", Multiply, self._field("open"), (weight,) * len(self.datas)
        )
        low_part = self._per_asset(
            "weighted_low", Multiply, self._field("low"), (1.0 - weight,) * len(self.datas)
        )
        weighted_price = self._per_asset("weighted_price", Add, open_part, low_part)
        price_delta = self._per_asset(
            "weighted_price_delta2", Delta, weighted_price, period=2.03608
        )
        normalized_delta = self._per_asset("normalized_delta", Divide, price_delta, weighted_price)
        negative_delta = self._per_asset(
            "negative_normalized_delta", Multiply, normalized_delta, (-1.0,) * len(self.datas)
        )
        second_decay = self._per_asset(
            "negative_delta_decay3", DecayLinear, negative_delta, period=3.33829
        )
        second = self._per_asset("negative_delta_ts_rank16", TsRank, second_decay, period=16.7411)
        combined = self._per_asset("pointwise_maximum", Maximum, first, second)
        return self._per_asset("negative_maximum", Multiply, combined, (-1.0,) * len(self.datas))


@native_alpha
class Alpha074Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 74
    case_id = "AF46-074"
    lookback_h = 79
    formula_fields = ("close", "high", "vwap", "volume", "dollar_volume", "adv30")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    formula = "((rank(correlation(close, sum(adv30, 37.4843), 15.1365)) < rank(correlation(rank(((high * 0.0261661) + (vwap * (1 - 0.0261661)))), rank(volume), 11.4791))) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        adv_sum = self._per_asset("adv30_sum37", RollingSum, self._field("adv30"), period=37.4843)
        left_correlation = self._per_asset(
            "close_adv_sum_corr15",
            RollingCorrelation,
            self._field("close"),
            adv_sum,
            period=15.1365,
        )
        left_rank = self._panel("close_adv_sum_rank", CrossSectionalRank, left_correlation)

        weight = 0.0261661
        high_part = self._per_asset(
            "weighted_high", Multiply, self._field("high"), (weight,) * len(self.datas)
        )
        vwap_part = self._per_asset(
            "weighted_vwap", Multiply, self._field("vwap"), (1.0 - weight,) * len(self.datas)
        )
        price_rank = self._panel(
            "weighted_price_rank",
            CrossSectionalRank,
            self._per_asset("weighted_price", Add, high_part, vwap_part),
        )
        volume_rank = self._panel("volume_rank", CrossSectionalRank, self._field("volume"))
        right_correlation = self._per_asset(
            "price_volume_rank_corr11", RollingCorrelation, price_rank, volume_rank, period=11.4791
        )
        right_rank = self._panel(
            "price_volume_rank_corr_rank", CrossSectionalRank, right_correlation
        )
        comparison = self._per_asset("rank_less_than", LessThan, left_rank, right_rank)
        return self._per_asset("negative_boolean", Multiply, comparison, (-1.0,) * len(self.datas))


@native_alpha
class Alpha075Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 75
    case_id = "AF46-075"
    lookback_h = 60
    formula_fields = ("vwap", "volume", "low", "dollar_volume", "adv50")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    formula = "(rank(correlation(vwap, volume, 4.24304)) < rank(correlation(rank(low), rank(adv50), 12.4413)))"

    def _make_formula(self) -> Tuple[Any, ...]:
        left_correlation = self._per_asset(
            "vwap_volume_corr4",
            RollingCorrelation,
            self._field("vwap"),
            self._field("volume"),
            period=4.24304,
        )
        left_rank = self._panel("vwap_volume_corr_rank", CrossSectionalRank, left_correlation)

        low_rank = self._panel("low_rank", CrossSectionalRank, self._field("low"))
        adv_rank = self._panel("adv50_rank", CrossSectionalRank, self._field("adv50"))
        right_correlation = self._per_asset(
            "low_adv50_rank_corr12", RollingCorrelation, low_rank, adv_rank, period=12.4413
        )
        right_rank = self._panel("low_adv50_rank_corr_rank", CrossSectionalRank, right_correlation)
        return self._per_asset("rank_less_than", LessThan, left_rank, right_rank)


@native_alpha
class Alpha076Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 76
    case_id = "AF46-076"
    lookback_h = 139
    formula_fields = ("vwap", "low", "dollar_volume", "adv81")
    required_fields = formula_fields
    classification_levels = ("sector",)
    classification_fields = ("sector",)
    formula = "(max(rank(decay_linear(delta(vwap, 1.24383), 11.8259)), Ts_Rank(decay_linear(Ts_Rank(correlation(IndNeutralize(low, IndClass.sector), adv81, 8.14941), 19.569), 17.1543), 19.383)) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        vwap_delta = self._per_asset("vwap_delta1", Delta, self._field("vwap"), period=1.24383)
        vwap_decay = self._per_asset("vwap_delta_decay11", DecayLinear, vwap_delta, period=11.8259)
        first = self._panel("vwap_delta_decay_rank", CrossSectionalRank, vwap_decay)

        neutral_low = self._panel(
            "sector_neutral_low",
            IndNeutralize,
            self._field("low"),
            level="sector",
            groups=self._groups("sector"),
        )
        correlation = self._per_asset(
            "neutral_low_adv81_corr8",
            RollingCorrelation,
            neutral_low,
            self._field("adv81"),
            period=8.14941,
        )
        correlation_rank = self._per_asset(
            "correlation_ts_rank19", TsRank, correlation, period=19.569
        )
        correlation_decay = self._per_asset(
            "correlation_rank_decay17", DecayLinear, correlation_rank, period=17.1543
        )
        second = self._per_asset(
            "correlation_decay_ts_rank19", TsRank, correlation_decay, period=19.383
        )
        combined = self._per_asset("pointwise_maximum", Maximum, first, second)
        return self._per_asset("negative_maximum", Multiply, combined, (-1.0,) * len(self.datas))


@native_alpha
class Alpha077Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 77
    case_id = "AF46-077"
    lookback_h = 45
    formula_fields = ("high", "low", "vwap", "dollar_volume", "adv40")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    formula = "min(rank(decay_linear(((((high + low) / 2) + high) - (vwap + high)), 20.0451)), rank(decay_linear(correlation(((high + low) / 2), adv40, 3.1614), 5.64125)))"

    def _make_formula(self) -> Tuple[Any, ...]:
        high = self._field("high")
        low = self._field("low")
        midpoint = self._per_asset(
            "high_low_midpoint",
            Divide,
            self._per_asset("high_low_sum", Add, high, low),
            (2.0,) * len(self.datas),
        )
        midpoint_plus_high = self._per_asset("midpoint_plus_high", Add, midpoint, high)
        vwap_plus_high = self._per_asset("vwap_plus_high", Add, self._field("vwap"), high)
        spread = self._per_asset("spread", Subtract, midpoint_plus_high, vwap_plus_high)
        first_decay = self._per_asset("spread_decay20", DecayLinear, spread, period=20.0451)
        first = self._panel("spread_decay_rank", CrossSectionalRank, first_decay)

        correlation = self._per_asset(
            "midpoint_adv40_corr3",
            RollingCorrelation,
            midpoint,
            self._field("adv40"),
            period=3.1614,
        )
        second_decay = self._per_asset(
            "correlation_decay5", DecayLinear, correlation, period=5.64125
        )
        second = self._panel("correlation_decay_rank", CrossSectionalRank, second_decay)
        return self._per_asset("pointwise_minimum", Minimum, first, second)


@native_alpha
class Alpha078Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 78
    case_id = "AF46-078"
    lookback_h = 62
    formula_fields = ("low", "vwap", "volume", "dollar_volume", "adv40")
    required_fields = formula_fields
    classification_levels = ()
    classification_fields = ()
    formula = "(rank(correlation(sum(((low * 0.352233) + (vwap * (1 - 0.352233))), 19.7428), sum(adv40, 19.7428), 6.83313))^rank(correlation(rank(vwap), rank(volume), 5.77492)))"

    def _make_formula(self) -> Tuple[Any, ...]:
        weight = 0.352233
        low_part = self._per_asset(
            "weighted_low", Multiply, self._field("low"), (weight,) * len(self.datas)
        )
        vwap_part = self._per_asset(
            "weighted_vwap", Multiply, self._field("vwap"), (1.0 - weight,) * len(self.datas)
        )
        price_sum = self._per_asset(
            "weighted_price_sum19",
            RollingSum,
            self._per_asset("weighted_price", Add, low_part, vwap_part),
            period=19.7428,
        )
        adv_sum = self._per_asset("adv40_sum19", RollingSum, self._field("adv40"), period=19.7428)
        left_correlation = self._per_asset(
            "price_adv_sum_corr6", RollingCorrelation, price_sum, adv_sum, period=6.83313
        )
        base = self._panel("price_adv_sum_corr_rank", CrossSectionalRank, left_correlation)

        vwap_rank = self._panel("vwap_rank", CrossSectionalRank, self._field("vwap"))
        volume_rank = self._panel("volume_rank", CrossSectionalRank, self._field("volume"))
        right_correlation = self._per_asset(
            "rank_vwap_volume_corr5", RollingCorrelation, vwap_rank, volume_rank, period=5.77492
        )
        exponent = self._panel("rank_correlation_rank", CrossSectionalRank, right_correlation)
        return self._per_asset("ordinary_power", Power, base, exponent)


@native_alpha
class Alpha079Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 79
    case_id = "AF46-079"
    lookback_h = 170
    formula_fields = ("close", "open", "vwap", "dollar_volume", "adv150")
    required_fields = formula_fields
    classification_levels = ("sector",)
    classification_fields = ("sector",)
    formula = "(rank(delta(IndNeutralize(((close * 0.60733) + (open * (1 - 0.60733))), IndClass.sector), 1.23438)) < rank(correlation(Ts_Rank(vwap, 3.60973), Ts_Rank(adv150, 9.18637), 14.6644)))"

    def _make_formula(self) -> Tuple[Any, ...]:
        weight = 0.60733
        close_part = self._per_asset(
            "weighted_close", Multiply, self._field("close"), (weight,) * len(self.datas)
        )
        open_part = self._per_asset(
            "weighted_open", Multiply, self._field("open"), (1.0 - weight,) * len(self.datas)
        )
        neutral_price = self._panel(
            "sector_neutral_price",
            IndNeutralize,
            self._per_asset("weighted_price", Add, close_part, open_part),
            level="sector",
            groups=self._groups("sector"),
        )
        price_delta = self._per_asset("neutral_price_delta1", Delta, neutral_price, period=1.23438)
        left_rank = self._panel("neutral_price_delta_rank", CrossSectionalRank, price_delta)

        vwap_rank = self._per_asset("vwap_ts_rank3", TsRank, self._field("vwap"), period=3.60973)
        adv_rank = self._per_asset("adv150_ts_rank9", TsRank, self._field("adv150"), period=9.18637)
        right_correlation = self._per_asset(
            "ts_rank_correlation14", RollingCorrelation, vwap_rank, adv_rank, period=14.6644
        )
        right_rank = self._panel("ts_rank_correlation_rank", CrossSectionalRank, right_correlation)
        return self._per_asset("rank_less_than", LessThan, left_rank, right_rank)


@native_alpha
class Alpha080Native(NativeAlphaBase):
    lines: Any = ("factor",)
    alpha_id = 80
    case_id = "AF46-080"
    lookback_h = 17
    formula_fields = ("open", "high", "dollar_volume", "adv10")
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ("industry",)
    formula = "((rank(Sign(delta(IndNeutralize(((open * 0.868128) + (high * (1 - 0.868128))), IndClass.industry), 4.04545)))^Ts_Rank(correlation(high, adv10, 5.11456), 5.53756)) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        weight = 0.868128
        open_part = self._per_asset(
            "weighted_open", Multiply, self._field("open"), (weight,) * len(self.datas)
        )
        high_part = self._per_asset(
            "weighted_high", Multiply, self._field("high"), (1.0 - weight,) * len(self.datas)
        )
        neutral_price = self._panel(
            "industry_neutral_price",
            IndNeutralize,
            self._per_asset("weighted_price", Add, open_part, high_part),
            level="industry",
            groups=self._groups("industry"),
        )
        delta = self._per_asset("neutral_price_delta4", Delta, neutral_price, period=4.04545)
        signed = self._per_asset("sign_delta", Sign, delta)
        base = self._panel("sign_delta_rank", CrossSectionalRank, signed)

        correlation = self._per_asset(
            "high_adv10_corr5",
            RollingCorrelation,
            self._field("high"),
            self._field("adv10"),
            period=5.11456,
        )
        exponent = self._per_asset("correlation_ts_rank5", TsRank, correlation, period=5.53756)
        powered = self._per_asset("ordinary_power", Power, base, exponent)
        return self._per_asset("negative_power", Multiply, powered, (-1.0,) * len(self.datas))


_BATCH_CLASSES = (
    Alpha064Native,
    Alpha065Native,
    Alpha066Native,
    Alpha068Native,
    Alpha069Native,
    Alpha070Native,
    Alpha071Native,
    Alpha072Native,
    Alpha073Native,
    Alpha074Native,
    Alpha075Native,
    Alpha076Native,
    Alpha077Native,
    Alpha078Native,
    Alpha079Native,
    Alpha080Native,
)

_BATCH_FACTOR_MAP = {factor.alpha_id: factor for factor in _BATCH_CLASSES}
_BATCH_IDS = (64, 65, 66, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80)
if (
    len(_BATCH_FACTOR_MAP) != len(_BATCH_CLASSES)
    or any(type(alpha_id) is not int for alpha_id in _BATCH_FACTOR_MAP)
    or tuple(_BATCH_FACTOR_MAP) != _BATCH_IDS
):
    raise RuntimeError("Batch D must expose its exact ascending Alpha101 integer IDs")

BATCH_FACTORS = MappingProxyType(_BATCH_FACTOR_MAP)

__all__ = tuple(factor.__name__ for factor in _BATCH_CLASSES) + ("BATCH_FACTORS",)
