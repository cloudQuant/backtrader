"""Fixed Iteration 45 Alpha101 native diagnostic representatives.

These twenty classes are formula diagnostics, not the production Alpha101
registry.  Each formula is composed from ordinary Backtrader Indicator
instances and the alpha101-v1 native operators; the diagnostic harness in
``tests/unit/test_factor_research_representatives.py`` owns independent
reference calculations.
"""

from typing import Any, Dict, Mapping, Sequence, Tuple, Type

from .factor_indicator import FactorIndicator
from .operators import (
    Abs,
    Add,
    CrossSectionalRank,
    CrossSectionalScale,
    DecayLinear,
    Delay,
    Delta,
    Divide,
    GreaterThan,
    IndNeutralize,
    LessThan,
    Log,
    Maximum,
    Minimum,
    Multiply,
    Power,
    RollingCorrelation,
    RollingCovariance,
    RollingProduct,
    RollingStd,
    RollingSum,
    Sign,
    SignedPower,
    Subtract,
    TsArgMax,
    TsArgMin,
    TsMax,
    TsMin,
    TsRank,
    Where,
)


class _RepresentativeFactor(FactorIndicator):
    """Small constructor helpers shared by the explicit representative trees."""

    lines: Any = ("factor",)
    operator_profile = "alpha101-v1"
    classification_fields: Tuple[str, ...] = ()

    def __init__(self) -> None:
        super().__init__()
        self._nodes: Dict[str, Any] = {}
        self._result_lines = self._make_formula()
        if len(self._result_lines) != len(self.datas):
            raise RuntimeError("representative formula did not produce one line per feed")
        # This is a reviewed manual dependency span from the frozen R4 recipe.
        # It is deliberately not inferred by compiling the native child tree.
        self.addminperiod(self.lookback_h + 1)

    def _make_formula(self) -> Tuple[Any, ...]:
        raise NotImplementedError

    def next(self) -> None:
        for data, result in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = result[0]

    def _field(self, name: str) -> Tuple[Any, ...]:
        return self.field_lines(name)

    def _groups(self, name: str) -> Tuple[Any, ...]:
        return self.classification_lines(name)

    def _scalar(self, name: str, operator: Any, *inputs: Any, **kwargs: Any) -> Any:
        node = operator(*inputs, **kwargs)
        self._nodes[name] = node
        return node.lines.value

    def _per_asset(
        self, name: str, operator: Any, *series: Sequence[Any], **kwargs: Any
    ) -> Tuple[Any, ...]:
        if any(len(items) != len(self.datas) for items in series):
            raise RuntimeError("per-asset operator inputs do not match the bound feeds")
        results = []
        for index, operands in enumerate(zip(*series)):
            results.append(self._scalar("%s_%d" % (name, index), operator, *operands, **kwargs))
        return tuple(results)

    def _panel(
        self, name: str, operator: Any, values: Sequence[Any], **kwargs: Any
    ) -> Tuple[Any, ...]:
        if len(values) != len(self.datas):
            raise RuntimeError("cross-sectional operator inputs do not match the bound feeds")
        panel_kwargs = dict(kwargs)
        panel_kwargs.setdefault("members", self.formula_members)
        if operator in (CrossSectionalRank, CrossSectionalScale):
            panel_kwargs.setdefault("groups", self.research_groups)
        node = operator.bind(*self.datas, values=tuple(values), **panel_kwargs)
        self._nodes[name] = node
        return tuple(node.outputs[data].value for data in self.datas)

    def _returns(self, name: str = "returns") -> Tuple[Any, ...]:
        close = self._field("close")
        prior = self._per_asset(name + "_prior", Delay, close, period=1)
        change = self._per_asset(name + "_change", Subtract, close, prior)
        return self._per_asset(name, Divide, change, prior)


class Alpha001(_RepresentativeFactor):
    """AF45-001: signed-power condition, five-grid argmax and cross rank."""

    lines: Any = ("factor",)
    alpha_id = 1
    case_id = "AF45-001"
    lookback_h = 24
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ()
    formula = (
        "(rank(Ts_ArgMax(SignedPower(((returns < 0) ? stddev(returns, 20) : close), 2.), 5)) - 0.5)"
    )

    def _make_formula(self) -> Tuple[Any, ...]:
        returns = self._returns("returns")
        negative = self._per_asset("negative_return", LessThan, returns, (0.0,) * len(self.datas))
        volatility = self._per_asset("returns_std20", RollingStd, returns, period=20)
        selected = self._per_asset("condition", Where, negative, volatility, self._field("close"))
        power = self._per_asset("signed_power2", SignedPower, selected, (2.0,) * len(self.datas))
        argmax = self._per_asset("argmax5", TsArgMax, power, period=5)
        ranked = self._panel("rank_argmax", CrossSectionalRank, argmax)
        return self._per_asset("offset_half", Subtract, ranked, (0.5,) * len(self.datas))


class Alpha002(_RepresentativeFactor):
    """AF45-002: two ranked series and six-grid rolling correlation."""

    lines: Any = ("factor",)
    alpha_id = 2
    case_id = "AF45-002"
    lookback_h = 7
    formula_fields = ("open", "close", "volume")
    required_fields = formula_fields
    classification_levels = ()
    formula = "(-1 * correlation(rank(delta(log(volume), 2)), rank(((close - open) / open)), 6))"

    def _make_formula(self) -> Tuple[Any, ...]:
        logged_volume = self._per_asset("log_volume", Log, self._field("volume"))
        volume_delta = self._per_asset("volume_log_delta2", Delta, logged_volume, period=2)
        ranked_volume_delta = self._panel("rank_volume_delta", CrossSectionalRank, volume_delta)
        open_gap = self._per_asset(
            "close_minus_open", Subtract, self._field("close"), self._field("open")
        )
        gap_fraction = self._per_asset("open_gap_fraction", Divide, open_gap, self._field("open"))
        ranked_gap = self._panel("rank_open_gap", CrossSectionalRank, gap_fraction)
        correlation = self._per_asset(
            "correlation6", RollingCorrelation, ranked_volume_delta, ranked_gap, period=6
        )
        return self._per_asset("negate", Multiply, correlation, (-1.0,) * len(self.datas))


class Alpha003(_RepresentativeFactor):
    """AF45-003: negative ten-grid correlation of daily open and volume ranks."""

    lines: Any = ("factor",)
    alpha_id = 3
    case_id = "AF45-003"
    lookback_h = 9
    formula_fields = ("open", "volume")
    required_fields = formula_fields
    classification_levels = ()
    formula = "(-1 * correlation(rank(open), rank(volume), 10))"

    def _make_formula(self) -> Tuple[Any, ...]:
        open_rank = self._panel("rank_open", CrossSectionalRank, self._field("open"))
        volume_rank = self._panel("rank_volume", CrossSectionalRank, self._field("volume"))
        correlation = self._per_asset(
            "correlation10", RollingCorrelation, open_rank, volume_rank, period=10
        )
        return self._per_asset("negate", Multiply, correlation, (-1.0,) * len(self.datas))


class Alpha004(_RepresentativeFactor):
    """AF45-004: daily low rank followed by within-asset nine-grid rank."""

    lines: Any = ("factor",)
    alpha_id = 4
    case_id = "AF45-004"
    lookback_h = 8
    formula_fields = ("low",)
    required_fields = formula_fields
    classification_levels = ()
    formula = "(-1 * Ts_Rank(rank(low), 9))"

    def _make_formula(self) -> Tuple[Any, ...]:
        low_rank = self._panel("rank_low", CrossSectionalRank, self._field("low"))
        time_rank = self._per_asset("ts_rank9", TsRank, low_rank, period=9)
        return self._per_asset("negate", Multiply, time_rank, (-1.0,) * len(self.datas))


class Alpha007(_RepresentativeFactor):
    """AF45-007: dollar-ADV/share-volume gate with a sixty-grid true branch."""

    lines: Any = ("factor",)
    alpha_id = 7
    case_id = "AF45-007"
    lookback_h = 66
    formula_fields = ("close", "volume", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_levels = ()
    formula = "((adv20 < volume) ? ((-1 * ts_rank(abs(delta(close, 7)), 60)) * sign(delta(close, 7))) : (-1 * 1))"

    def _make_formula(self) -> Tuple[Any, ...]:
        adv20 = self._field("adv20")
        condition = self._per_asset("adv20_less_volume", LessThan, adv20, self._field("volume"))
        change = self._per_asset("close_delta7", Delta, self._field("close"), period=7)
        magnitude = self._per_asset("abs_delta7", Abs, change)
        time_rank = self._per_asset("ts_rank60", TsRank, magnitude, period=60)
        negative_rank = self._per_asset(
            "negative_ts_rank", Multiply, time_rank, (-1.0,) * len(self.datas)
        )
        direction = self._per_asset("delta_sign", Sign, change)
        active = self._per_asset("active_branch", Multiply, negative_rank, direction)
        return self._per_asset("where", Where, condition, active, (-1.0,) * len(self.datas))


class Alpha009(_RepresentativeFactor):
    """AF45-009: nested five-grid extrema condition over one-grid change."""

    lines: Any = ("factor",)
    alpha_id = 9
    case_id = "AF45-009"
    lookback_h = 5
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ()
    formula = "((0 < ts_min(delta(close, 1), 5)) ? delta(close, 1) : ((ts_max(delta(close, 1), 5) < 0) ? delta(close, 1) : (-1 * delta(close, 1))))"

    def _make_formula(self) -> Tuple[Any, ...]:
        change = self._per_asset("close_delta1", Delta, self._field("close"), period=1)
        floor = self._per_asset("delta_min5", TsMin, change, period=5)
        ceiling = self._per_asset("delta_max5", TsMax, change, period=5)
        all_positive = self._per_asset("all_positive", GreaterThan, floor, (0.0,) * len(self.datas))
        all_negative = self._per_asset("all_negative", LessThan, ceiling, (0.0,) * len(self.datas))
        reverse = self._per_asset("reverse_delta", Multiply, change, (-1.0,) * len(self.datas))
        negative_or_mixed = self._per_asset(
            "negative_or_mixed", Where, all_negative, change, reverse
        )
        return self._per_asset("condition", Where, all_positive, change, negative_or_mixed)


class Alpha013(_RepresentativeFactor):
    """AF45-013: cross-ranked price/volume covariance followed by cross rank."""

    lines: Any = ("factor",)
    alpha_id = 13
    case_id = "AF45-013"
    lookback_h = 4
    formula_fields = ("close", "volume")
    required_fields = formula_fields
    classification_levels = ()
    formula = "(-1 * rank(covariance(rank(close), rank(volume), 5)))"

    def _make_formula(self) -> Tuple[Any, ...]:
        close_rank = self._panel("rank_close", CrossSectionalRank, self._field("close"))
        volume_rank = self._panel("rank_volume", CrossSectionalRank, self._field("volume"))
        covariance = self._per_asset(
            "covariance5", RollingCovariance, close_rank, volume_rank, period=5
        )
        ranked_covariance = self._panel("rank_covariance", CrossSectionalRank, covariance)
        return self._per_asset("negate", Multiply, ranked_covariance, (-1.0,) * len(self.datas))


class Alpha029(_RepresentativeFactor):
    """AF45-029: nested rank/scale/log/product path and delayed-return rank."""

    lines: Any = ("factor",)
    alpha_id = 29
    case_id = "AF45-029"
    lookback_h = 11
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ()
    formula = "(min(product(rank(rank(scale(log(sum(ts_min(rank(rank((-1 * rank(delta((close - 1), 5))))), 2), 1))))), 1), 5) + ts_rank(delay((-1 * returns), 6), 5))"

    def _make_formula(self) -> Tuple[Any, ...]:
        close_minus_one = self._per_asset(
            "close_minus_one", Subtract, self._field("close"), (1.0,) * len(self.datas)
        )
        change = self._per_asset("delta5", Delta, close_minus_one, period=5)
        rank_once = self._panel("rank_delta", CrossSectionalRank, change)
        negate = self._per_asset("negative_rank", Multiply, rank_once, (-1.0,) * len(self.datas))
        rank_twice = self._panel("rank_negative_rank", CrossSectionalRank, negate)
        rank_thrice = self._panel("rank_rank_negative", CrossSectionalRank, rank_twice)
        local_min = self._per_asset("ts_min2", TsMin, rank_thrice, period=2)
        local_sum = self._per_asset("sum1", RollingSum, local_min, period=1)
        logged = self._per_asset("log_sum", Log, local_sum)
        scaled = self._panel("scale_log", CrossSectionalScale, logged)
        ranked_scaled = self._panel("rank_scaled", CrossSectionalRank, scaled)
        ranked_again = self._panel("rank_rank_scaled", CrossSectionalRank, ranked_scaled)
        product = self._per_asset("product1", RollingProduct, ranked_again, period=1)
        rolling_min = self._per_asset("ts_min5", TsMin, product, period=5)

        returns = self._returns("returns")
        negative_returns = self._per_asset(
            "negative_returns", Multiply, returns, (-1.0,) * len(self.datas)
        )
        delayed = self._per_asset("delay6", Delay, negative_returns, period=6)
        delayed_rank = self._per_asset("ts_rank5", TsRank, delayed, period=5)
        return self._per_asset("add_branches", Add, rolling_min, delayed_rank)


class Alpha048(_RepresentativeFactor):
    """AF45-048: subindustry-neutralized long correlation divided by return power."""

    lines: Any = ("factor",)
    alpha_id = 48
    case_id = "AF45-048"
    lookback_h = 251
    formula_fields = ("close",)
    required_fields = formula_fields
    classification_levels = ("subindustry",)
    classification_fields = ("subindustry",)
    formula = "(indneutralize(((correlation(delta(close, 1), delta(delay(close, 1), 1), 250) * delta(close, 1)) / close), IndClass.subindustry) / sum(((delta(close, 1) / delay(close, 1))^2), 250))"

    def _make_formula(self) -> Tuple[Any, ...]:
        close = self._field("close")
        delta_now = self._per_asset("delta_close1", Delta, close, period=1)
        close_delay = self._per_asset("delay_close1", Delay, close, period=1)
        delta_delay = self._per_asset("delta_delay_close1", Delta, close_delay, period=1)
        correlation = self._per_asset(
            "correlation250", RollingCorrelation, delta_now, delta_delay, period=250
        )
        corr_times_delta = self._per_asset("corr_times_delta", Multiply, correlation, delta_now)
        normalized = self._per_asset("price_normalized", Divide, corr_times_delta, close)
        neutralized = self._panel(
            "neutralized_numerator",
            IndNeutralize,
            normalized,
            level="subindustry",
            groups=self._groups("subindustry"),
        )
        return_ratio = self._per_asset("return_ratio", Divide, delta_now, close_delay)
        square = self._per_asset(
            "return_ratio_squared", Power, return_ratio, (2.0,) * len(self.datas)
        )
        square_sum = self._per_asset("square_sum250", RollingSum, square, period=250)
        return self._per_asset("divide_denominator", Divide, neutralized, square_sum)


class Alpha056(_RepresentativeFactor):
    """AF45-056: nested return sums times a point-in-time cap rank."""

    lines: Any = ("factor",)
    alpha_id = 56
    case_id = "AF45-056"
    lookback_h = 10
    formula_fields = ("close", "cap")
    required_fields = formula_fields
    classification_levels = ()
    formula = (
        "(0 - (1 * (rank((sum(returns, 10) / sum(sum(returns, 2), 3))) * rank((returns * cap)))))"
    )

    def _make_formula(self) -> Tuple[Any, ...]:
        returns = self._returns("returns")
        long_sum = self._per_asset("sum_returns10", RollingSum, returns, period=10)
        inner_sum = self._per_asset("sum_returns2", RollingSum, returns, period=2)
        nested_sum = self._per_asset("sum_of_sum3", RollingSum, inner_sum, period=3)
        ratio = self._per_asset("sum_ratio", Divide, long_sum, nested_sum)
        ranked_ratio = self._panel("rank_sum_ratio", CrossSectionalRank, ratio)
        return_cap = self._per_asset("return_times_cap", Multiply, returns, self._field("cap"))
        ranked_return_cap = self._panel("rank_return_cap", CrossSectionalRank, return_cap)
        product = self._per_asset("rank_product", Multiply, ranked_ratio, ranked_return_cap)
        times_one = self._per_asset("times_one", Multiply, product, (1.0,) * len(self.datas))
        return self._per_asset("zero_minus", Subtract, (0.0,) * len(self.datas), times_one)


class Alpha058(_RepresentativeFactor):
    """AF45-058: sector-neutral VWAP correlation, decay and time rank."""

    lines: Any = ("factor",)
    alpha_id = 58
    case_id = "AF45-058"
    lookback_h = 12
    formula_fields = ("vwap", "volume")
    required_fields = formula_fields
    classification_levels = ("sector",)
    classification_fields = ("sector",)
    formula = "(-1 * Ts_Rank(decay_linear(correlation(IndNeutralize(vwap, IndClass.sector), volume, 3.92795), 7.89291), 5.50322))"

    def _make_formula(self) -> Tuple[Any, ...]:
        neutral_vwap = self._panel(
            "sector_neutral_vwap",
            IndNeutralize,
            self._field("vwap"),
            level="sector",
            groups=self._groups("sector"),
        )
        correlation = self._per_asset(
            "correlation3", RollingCorrelation, neutral_vwap, self._field("volume"), period=3.92795
        )
        decay = self._per_asset("decay7", DecayLinear, correlation, period=7.89291)
        time_rank = self._per_asset("ts_rank5", TsRank, decay, period=5.50322)
        return self._per_asset("negate", Multiply, time_rank, (-1.0,) * len(self.datas))


class Alpha062(_RepresentativeFactor):
    """AF45-062: cross-ranked correlation versus nested comparison rank."""

    lines: Any = ("factor",)
    alpha_id = 62
    case_id = "AF45-062"
    lookback_h = 48
    formula_fields = ("open", "high", "low", "vwap", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_levels = ()
    formula = "((rank(correlation(vwap, sum(adv20, 22.4101), 9.91009)) < rank(((rank(open) + rank(open)) < (rank(((high + low) / 2)) + rank(high))))) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        adv20 = self._field("adv20")
        adv_sum = self._per_asset("adv20_sum22", RollingSum, adv20, period=22.4101)
        correlation = self._per_asset(
            "correlation9", RollingCorrelation, self._field("vwap"), adv_sum, period=9.91009
        )
        ranked_correlation = self._panel("rank_correlation", CrossSectionalRank, correlation)

        open_rank_left = self._panel("rank_open_left", CrossSectionalRank, self._field("open"))
        open_rank_right = self._panel("rank_open_right", CrossSectionalRank, self._field("open"))
        open_rank_sum = self._per_asset("open_rank_sum", Add, open_rank_left, open_rank_right)
        midpoint = self._per_asset(
            "midpoint",
            Divide,
            self._per_asset("high_plus_low", Add, self._field("high"), self._field("low")),
            (2.0,) * len(self.datas),
        )
        midpoint_rank = self._panel("rank_midpoint", CrossSectionalRank, midpoint)
        high_rank = self._panel("rank_high", CrossSectionalRank, self._field("high"))
        right_sum = self._per_asset("midpoint_plus_high_rank", Add, midpoint_rank, high_rank)
        nested_bool = self._per_asset("nested_comparison", LessThan, open_rank_sum, right_sum)
        ranked_nested_bool = self._panel("rank_nested_bool", CrossSectionalRank, nested_bool)
        comparison = self._per_asset(
            "outer_comparison", LessThan, ranked_correlation, ranked_nested_bool
        )
        return self._per_asset("negative_boolean", Multiply, comparison, (-1.0,) * len(self.datas))


class Alpha063(_RepresentativeFactor):
    """AF45-063: industry-neutral delta versus long ADV correlation branch."""

    lines: Any = ("factor",)
    alpha_id = 63
    case_id = "AF45-063"
    lookback_h = 238
    formula_fields = ("close", "vwap", "open", "dollar_volume", "adv180")
    required_fields = formula_fields
    classification_levels = ("industry",)
    classification_fields = ("industry",)
    formula = "((rank(decay_linear(delta(IndNeutralize(close, IndClass.industry), 2.25164), 8.22237)) - rank(decay_linear(correlation(((vwap * 0.318108) + (open * (1 - 0.318108))), sum(adv180, 37.2467), 13.557), 12.2883))) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        neutral_close = self._panel(
            "industry_neutral_close",
            IndNeutralize,
            self._field("close"),
            level="industry",
            groups=self._groups("industry"),
        )
        close_delta = self._per_asset("neutral_close_delta2", Delta, neutral_close, period=2.25164)
        left_decay = self._per_asset("left_decay8", DecayLinear, close_delta, period=8.22237)
        left_rank = self._panel("left_rank", CrossSectionalRank, left_decay)

        weight = 0.318108
        weighted_vwap = self._per_asset(
            "weighted_vwap", Multiply, self._field("vwap"), (weight,) * len(self.datas)
        )
        weighted_open = self._per_asset(
            "weighted_open", Multiply, self._field("open"), (1.0 - weight,) * len(self.datas)
        )
        price_mix = self._per_asset("weighted_price", Add, weighted_vwap, weighted_open)
        adv180 = self._field("adv180")
        adv_sum = self._per_asset("adv180_sum37", RollingSum, adv180, period=37.2467)
        correlation = self._per_asset(
            "correlation13", RollingCorrelation, price_mix, adv_sum, period=13.557
        )
        right_decay = self._per_asset("right_decay12", DecayLinear, correlation, period=12.2883)
        right_rank = self._panel("right_rank", CrossSectionalRank, right_decay)
        difference = self._per_asset("rank_difference", Subtract, left_rank, right_rank)
        return self._per_asset("negate_difference", Multiply, difference, (-1.0,) * len(self.datas))


class Alpha067(_RepresentativeFactor):
    """AF45-067: ordinary power of ranks, then negate (no outer rank)."""

    lines: Any = ("factor",)
    alpha_id = 67
    case_id = "AF45-067"
    lookback_h = 24
    formula_fields = ("high", "vwap", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_levels = ("sector", "subindustry")
    classification_fields = ("sector", "subindustry")
    formula = "((rank((high - ts_min(high, 2.14593)))^rank(correlation(IndNeutralize(vwap, IndClass.sector), IndNeutralize(adv20, IndClass.subindustry), 6.02936))) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        high_min = self._per_asset("high_min2", TsMin, self._field("high"), period=2.14593)
        high_excess = self._per_asset("high_minus_min", Subtract, self._field("high"), high_min)
        base = self._panel("rank_base", CrossSectionalRank, high_excess)

        sector_vwap = self._panel(
            "sector_neutral_vwap",
            IndNeutralize,
            self._field("vwap"),
            level="sector",
            groups=self._groups("sector"),
        )
        adv20 = self._field("adv20")
        subindustry_adv = self._panel(
            "subindustry_neutral_adv20",
            IndNeutralize,
            adv20,
            level="subindustry",
            groups=self._groups("subindustry"),
        )
        exponent_correlation = self._per_asset(
            "exponent_correlation6",
            RollingCorrelation,
            sector_vwap,
            subindustry_adv,
            period=6.02936,
        )
        exponent = self._panel("rank_exponent", CrossSectionalRank, exponent_correlation)
        powered = self._per_asset("ordinary_power", Power, base, exponent)
        return self._per_asset("negate", Multiply, powered, (-1.0,) * len(self.datas))


class Alpha081(_RepresentativeFactor):
    """AF45-081: powered ranked correlation, rolling product/log and comparison."""

    lines: Any = ("factor",)
    alpha_id = 81
    case_id = "AF45-081"
    lookback_h = 77
    formula_fields = ("vwap", "volume", "dollar_volume", "adv10")
    required_fields = formula_fields
    classification_levels = ()
    formula = "((rank(Log(product(rank((rank(correlation(vwap, sum(adv10, 49.6054), 8.47743))^4)), 14.9655))) < rank(correlation(rank(vwap), rank(volume), 5.07914))) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        adv10 = self._field("adv10")
        adv_sum = self._per_asset("adv10_sum49", RollingSum, adv10, period=49.6054)
        first_correlation = self._per_asset(
            "correlation8", RollingCorrelation, self._field("vwap"), adv_sum, period=8.47743
        )
        first_rank = self._panel("first_rank", CrossSectionalRank, first_correlation)
        powered = self._per_asset("rank_power4", Power, first_rank, (4.0,) * len(self.datas))
        powered_rank = self._panel("powered_rank", CrossSectionalRank, powered)
        product = self._per_asset("product14", RollingProduct, powered_rank, period=14.9655)
        logged = self._per_asset("log_product", Log, product)
        ranked_log = self._panel("rank_log_product", CrossSectionalRank, logged)

        vwap_rank = self._panel("rank_vwap", CrossSectionalRank, self._field("vwap"))
        volume_rank = self._panel("rank_volume", CrossSectionalRank, self._field("volume"))
        second_correlation = self._per_asset(
            "second_correlation5", RollingCorrelation, vwap_rank, volume_rank, period=5.07914
        )
        second_rank = self._panel("second_rank", CrossSectionalRank, second_correlation)
        comparison = self._per_asset("comparison", LessThan, ranked_log, second_rank)
        return self._per_asset(
            "negative_comparison", Multiply, comparison, (-1.0,) * len(self.datas)
        )


class Alpha084(_RepresentativeFactor):
    """AF45-084: signed power with dynamic close-change exponent."""

    lines: Any = ("factor",)
    alpha_id = 84
    case_id = "AF45-084"
    lookback_h = 33
    formula_fields = ("close", "vwap")
    required_fields = formula_fields
    classification_levels = ()
    formula = "SignedPower(Ts_Rank((vwap - ts_max(vwap, 15.3217)), 20.7127), delta(close, 4.96796))"

    def _make_formula(self) -> Tuple[Any, ...]:
        vwap_max = self._per_asset("vwap_max15", TsMax, self._field("vwap"), period=15.3217)
        offset = self._per_asset("vwap_minus_max", Subtract, self._field("vwap"), vwap_max)
        base = self._per_asset("ts_rank20", TsRank, offset, period=20.7127)
        exponent = self._per_asset("close_delta4", Delta, self._field("close"), period=4.96796)
        return self._per_asset("signed_power", SignedPower, base, exponent)


class Alpha092(_RepresentativeFactor):
    """AF45-092: pointwise minimum of two independently ranked time branches."""

    lines: Any = ("factor",)
    alpha_id = 92
    case_id = "AF45-092"
    lookback_h = 45
    formula_fields = ("open", "high", "low", "close", "dollar_volume", "adv30")
    required_fields = formula_fields
    classification_levels = ()
    formula = "min(Ts_Rank(decay_linear(((((high + low) / 2) + close) < (low + open)), 14.7221), 18.8683), Ts_Rank(decay_linear(correlation(rank(low), rank(adv30), 7.58555), 6.94024), 6.80584))"

    def _make_formula(self) -> Tuple[Any, ...]:
        high_low = self._per_asset("high_plus_low", Add, self._field("high"), self._field("low"))
        midpoint = self._per_asset("midpoint", Divide, high_low, (2.0,) * len(self.datas))
        midpoint_close = self._per_asset("midpoint_plus_close", Add, midpoint, self._field("close"))
        low_open = self._per_asset("low_plus_open", Add, self._field("low"), self._field("open"))
        condition = self._per_asset("midpoint_less_low_open", LessThan, midpoint_close, low_open)
        bool_decay = self._per_asset("bool_decay14", DecayLinear, condition, period=14.7221)
        bool_rank = self._per_asset("bool_ts_rank18", TsRank, bool_decay, period=18.8683)

        low_rank = self._panel("rank_low", CrossSectionalRank, self._field("low"))
        adv30 = self._field("adv30")
        adv_rank = self._panel("rank_adv30", CrossSectionalRank, adv30)
        correlation = self._per_asset(
            "correlation7", RollingCorrelation, low_rank, adv_rank, period=7.58555
        )
        correlation_decay = self._per_asset(
            "correlation_decay6", DecayLinear, correlation, period=6.94024
        )
        correlation_rank = self._per_asset(
            "correlation_ts_rank6", TsRank, correlation_decay, period=6.80584
        )
        return self._per_asset("pointwise_minimum", Minimum, bool_rank, correlation_rank)


class Alpha096(_RepresentativeFactor):
    """AF45-096: pointwise max of a short and nested long time-series branch."""

    lines: Any = ("factor",)
    alpha_id = 96
    case_id = "AF45-096"
    lookback_h = 100
    formula_fields = ("close", "vwap", "volume", "dollar_volume", "adv60")
    required_fields = formula_fields
    classification_levels = ()
    formula = "(max(Ts_Rank(decay_linear(correlation(rank(vwap), rank(volume), 3.83878), 4.16783), 8.38151), Ts_Rank(decay_linear(Ts_ArgMax(correlation(Ts_Rank(close, 7.45404), Ts_Rank(adv60, 4.13242), 3.65459), 12.6556), 14.0365), 13.4143)) * -1)"

    def _make_formula(self) -> Tuple[Any, ...]:
        vwap_rank = self._panel("rank_vwap", CrossSectionalRank, self._field("vwap"))
        volume_rank = self._panel("rank_volume", CrossSectionalRank, self._field("volume"))
        short_correlation = self._per_asset(
            "short_correlation3", RollingCorrelation, vwap_rank, volume_rank, period=3.83878
        )
        short_decay = self._per_asset(
            "short_decay4", DecayLinear, short_correlation, period=4.16783
        )
        left = self._per_asset("left_ts_rank8", TsRank, short_decay, period=8.38151)

        close_rank = self._per_asset("close_ts_rank7", TsRank, self._field("close"), period=7.45404)
        adv60 = self._field("adv60")
        adv_rank = self._per_asset("adv60_ts_rank4", TsRank, adv60, period=4.13242)
        long_correlation = self._per_asset(
            "long_correlation3", RollingCorrelation, close_rank, adv_rank, period=3.65459
        )
        argmax = self._per_asset("correlation_argmax12", TsArgMax, long_correlation, period=12.6556)
        long_decay = self._per_asset("long_decay14", DecayLinear, argmax, period=14.0365)
        right = self._per_asset("right_ts_rank13", TsRank, long_decay, period=13.4143)
        maximum = self._per_asset("pointwise_maximum", Maximum, left, right)
        return self._per_asset("negate", Multiply, maximum, (-1.0,) * len(self.datas))


class Alpha100(_RepresentativeFactor):
    """AF45-100: three ordered subindustry neutralizations and two scales."""

    lines: Any = ("factor",)
    alpha_id = 100
    case_id = "AF45-100"
    lookback_h = 29
    formula_fields = ("close", "high", "low", "volume", "dollar_volume", "adv20")
    required_fields = formula_fields
    classification_levels = ("subindustry", "subindustry", "subindustry")
    classification_fields = ("subindustry",)
    formula = "(0 - (1 * (((1.5 * scale(indneutralize(indneutralize(rank(((((close - low) - (high - close)) / (high - low)) * volume)), IndClass.subindustry), IndClass.subindustry))) - scale(indneutralize((correlation(close, rank(adv20), 5) - rank(ts_argmin(close, 30))), IndClass.subindustry))) * (volume / adv20))))"

    def _make_formula(self) -> Tuple[Any, ...]:
        close = self._field("close")
        low = self._field("low")
        high = self._field("high")
        numerator_left = self._per_asset("close_minus_low", Subtract, close, low)
        numerator_right = self._per_asset("high_minus_close", Subtract, high, close)
        numerator = self._per_asset(
            "range_position_numerator", Subtract, numerator_left, numerator_right
        )
        denominator = self._per_asset("high_minus_low", Subtract, high, low)
        location = self._per_asset("range_position", Divide, numerator, denominator)
        volume_weighted = self._per_asset(
            "range_times_volume", Multiply, location, self._field("volume")
        )
        ranked_weighted = self._panel("rank_range_volume", CrossSectionalRank, volume_weighted)
        neutralized_once = self._panel(
            "first_subindustry_neutralize",
            IndNeutralize,
            ranked_weighted,
            level="subindustry",
            groups=self._groups("subindustry"),
        )
        neutralized_twice = self._panel(
            "second_subindustry_neutralize",
            IndNeutralize,
            neutralized_once,
            level="subindustry",
            groups=self._groups("subindustry"),
        )
        first_scale = self._panel("first_scale", CrossSectionalScale, neutralized_twice)
        first_scaled = self._per_asset(
            "scale_times_1_5", Multiply, first_scale, (1.5,) * len(self.datas)
        )

        adv20 = self._field("adv20")
        adv_rank = self._panel("rank_adv20", CrossSectionalRank, adv20)
        correlation = self._per_asset(
            "close_adv_correlation5", RollingCorrelation, close, adv_rank, period=5
        )
        close_argmin = self._per_asset("close_argmin30", TsArgMin, close, period=30)
        argmin_rank = self._panel("rank_close_argmin", CrossSectionalRank, close_argmin)
        correlation_minus_rank = self._per_asset(
            "correlation_minus_argmin_rank", Subtract, correlation, argmin_rank
        )
        second_neutralized = self._panel(
            "third_subindustry_neutralize",
            IndNeutralize,
            correlation_minus_rank,
            level="subindustry",
            groups=self._groups("subindustry"),
        )
        second_scale = self._panel("second_scale", CrossSectionalScale, second_neutralized)

        scale_difference = self._per_asset(
            "scaled_difference", Subtract, first_scaled, second_scale
        )
        volume_adv = self._per_asset("volume_over_adv20", Divide, self._field("volume"), adv20)
        weighted_difference = self._per_asset(
            "volume_weighted_difference", Multiply, scale_difference, volume_adv
        )
        times_one = self._per_asset(
            "times_one", Multiply, weighted_difference, (1.0,) * len(self.datas)
        )
        return self._per_asset("zero_minus", Subtract, (0.0,) * len(self.datas), times_one)


class Alpha101(_RepresentativeFactor):
    """AF45-101: intraday move over range plus the frozen 0.001 offset."""

    lines: Any = ("factor",)
    alpha_id = 101
    case_id = "AF45-101"
    lookback_h = 0
    formula_fields = ("open", "high", "low", "close")
    required_fields = formula_fields
    classification_levels = ()
    formula = "((close - open) / ((high - low) + .001))"

    def _make_formula(self) -> Tuple[Any, ...]:
        intraday_move = self._per_asset(
            "close_minus_open", Subtract, self._field("close"), self._field("open")
        )
        range_width = self._per_asset(
            "high_minus_low", Subtract, self._field("high"), self._field("low")
        )
        denominator = self._per_asset(
            "range_plus_offset", Add, range_width, (0.001,) * len(self.datas)
        )
        return self._per_asset("factor", Divide, intraday_move, denominator)


REPRESENTATIVE_FACTORS: Mapping[int, Type[FactorIndicator]] = {
    factor.alpha_id: factor
    for factor in (
        Alpha001,
        Alpha002,
        Alpha003,
        Alpha004,
        Alpha007,
        Alpha009,
        Alpha013,
        Alpha029,
        Alpha048,
        Alpha056,
        Alpha058,
        Alpha062,
        Alpha063,
        Alpha067,
        Alpha081,
        Alpha084,
        Alpha092,
        Alpha096,
        Alpha100,
        Alpha101,
    )
}


def bind_representative(alpha_id: int, *datas: Any) -> FactorIndicator:
    """Bind one fixed diagnostic class; this is not a full Alpha101 registry."""
    if isinstance(alpha_id, bool) or not isinstance(alpha_id, int):
        raise TypeError("alpha_id must be an integer")
    try:
        factor = REPRESENTATIVE_FACTORS[alpha_id]
    except KeyError as exc:
        raise ValueError("alpha_id is not in the fixed Iteration 45 representative set") from exc
    return factor.bind(*datas)


__all__ = (
    "Alpha001",
    "Alpha002",
    "Alpha003",
    "Alpha004",
    "Alpha007",
    "Alpha009",
    "Alpha013",
    "Alpha029",
    "Alpha048",
    "Alpha056",
    "Alpha058",
    "Alpha062",
    "Alpha063",
    "Alpha067",
    "Alpha081",
    "Alpha084",
    "Alpha092",
    "Alpha096",
    "Alpha100",
    "Alpha101",
    "REPRESENTATIVE_FACTORS",
    "bind_representative",
)
