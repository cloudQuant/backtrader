"""Independent known-answer checks for the fixed native Alpha101 diagnostics.

The reference below is deliberately test-local: it operates on plain Python
matrices and never imports or calls the production operator nodes.
"""

import math
import random
from decimal import Decimal, localcontext
from fractions import Fraction

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from tests.test_utils.alpha101_diagnostic_factors import REPRESENTATIVE_FACTORS
from backtrader.research.specs import FactorSpec, ResearchSpec
from backtrader.research.inputs import prealign_bars

_ALPHA_IDS = (1, 2, 3, 4, 7, 9, 13, 29, 48, 56, 58, 62, 63, 67, 81, 84, 92, 96, 100, 101)
_HISTORY = {
    1: 24,
    2: 7,
    3: 9,
    4: 8,
    7: 66,
    9: 5,
    13: 4,
    29: 11,
    48: 251,
    56: 10,
    58: 12,
    62: 48,
    63: 238,
    67: 24,
    81: 77,
    84: 33,
    92: 45,
    96: 100,
    100: 29,
    101: 0,
}

_DISTINGUISHING_INPUTS = {
    1: ("close", "point_extreme"),
    2: ("volume", "point_extreme"),
    3: ("open", "scale"),
    4: ("low", "scale"),
    7: ("vwap", "adv_gate"),
    9: ("close", "scale"),
    13: ("volume", "scale"),
    29: ("close", "scale"),
    48: ("close", "scale"),
    56: ("cap", "scale"),
    58: ("volume", "all_alternating"),
    62: ("vwap", "point_extreme"),
    63: ("vwap", "scale"),
    67: ("high", "scale"),
    81: ("vwap", "scale"),
    84: ("close", "scale"),
    92: ("low", "low_window"),
    96: ("volume", "alternating_mild"),
    100: ("subindustry", "new_group"),
    101: ("high", "zero_range"),
}
_FORMULA_FIELDS = {
    1: ("close",),
    2: ("open", "close", "volume"),
    3: ("open", "volume"),
    4: ("low",),
    7: ("close", "volume", "dollar_volume", "adv20"),
    9: ("close",),
    13: ("close", "volume"),
    29: ("close",),
    48: ("close",),
    56: ("close", "cap"),
    58: ("vwap", "volume"),
    62: ("open", "high", "low", "vwap", "dollar_volume", "adv20"),
    63: ("close", "vwap", "open", "dollar_volume", "adv180"),
    67: ("high", "vwap", "dollar_volume", "adv20"),
    81: ("vwap", "volume", "dollar_volume", "adv10"),
    84: ("close", "vwap"),
    92: ("open", "high", "low", "close", "dollar_volume", "adv30"),
    96: ("close", "vwap", "volume", "dollar_volume", "adv60"),
    100: ("close", "high", "low", "volume", "dollar_volume", "adv20"),
    101: ("open", "high", "low", "close"),
}


class _FactorData(bt.feeds.PandasData):
    lines = ("vwap", "dollar_volume", "cap", "sector", "industry", "subindustry")
    params = tuple((name, name) for name in lines)


def _frames(periods=260):
    """Produce a deterministic positive panel with changing ranks and PIT groups."""
    index = pd.date_range("2024-01-01", periods=periods, freq="D", tz="UTC")
    bases = (2.20, 2.24, 2.28, 2.32, 2.36, 2.40)
    result = {}
    for asset, base in enumerate(bases):
        opens, highs, lows, closes, volumes, vwaps, caps = [], [], [], [], [], [], []
        close_noise = random.Random(45_101 + asset)
        open_noise = random.Random(45_201 + asset)
        volume_noise = random.Random(45_301 + asset)
        vwap_noise = random.Random(45_401 + asset)
        for t in range(periods):
            close = base + 0.0003 * t + close_noise.uniform(-0.35, 0.35)
            open_ = close + open_noise.uniform(-0.29, 0.29)
            high = max(open_, close) + 0.28 + 0.015 * math.cos(0.11 * t + asset)
            low = min(open_, close) - 0.20 - 0.012 * math.sin(0.13 * t + asset)
            volume = 4200.0 + 130.0 * asset + volume_noise.uniform(-850.0, 850.0)
            # This is an independent synthetic VWAP series. It is not an
            # OHLC average, which would accidentally bless a wrong binding.
            vwap = base + 0.0004 * t + vwap_noise.uniform(-0.36, 0.36)
            opens.append(open_)
            highs.append(high)
            lows.append(low)
            closes.append(close)
            volumes.append(volume)
            vwaps.append(vwap)
            caps.append(1_000_000.0 * (asset + 1) + 230.0 * t * (asset + 2))

        sector_id = 0.0 if asset < 4 else 1.0
        industry_id = float((0, 0, 0, 1, 2, 2)[asset])
        subindustry_id = float((0, 1, 1, 2, 3, 4)[asset])
        sectors = [sector_id] * periods
        if asset == 0:
            # This category becomes effective on this date only.
            sectors[205:] = [9.0] * (periods - 205)
        industries = [industry_id] * periods
        subindustries = [subindustry_id] * periods
        result["asset-%d" % asset] = pd.DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": volumes,
                "openinterest": [0.0] * periods,
                "vwap": vwaps,
                "dollar_volume": [price * volume for price, volume in zip(vwaps, volumes)],
                "cap": caps,
                "sector": sectors,
                "industry": industries,
                "subindustry": subindustries,
            },
            index=index,
        )
    return result


def _research_spec(frames, *, formula_universe=None, groups=None):
    names = tuple(frames)
    index = next(iter(frames.values())).index.rename("close_time")
    grid = pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index)
    keys = pd.MultiIndex.from_product([index, names], names=("time", "asset"))
    if formula_universe is None:
        formula_universe = pd.Series(True, index=keys, dtype=bool)
    return ResearchSpec(
        grid=grid,
        start=index[0],
        end=index[-1],
        targets=names,
        source_timezone="UTC",
        snapshot_id="iteration45-fixed20-independent-oracle-v1",
        price_basis="synthetic unadjusted independent OHLC and VWAP units",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
        feed_time_kind="close_time",
        groups=groups or dict.fromkeys(names, "market"),
        formula_universe=formula_universe,
        classifications=_classification_tables(frames),
    )


def _classification_tables(frames):
    """Build explicit synthetic PIT tables with effective and available times."""
    index = next(iter(frames.values())).index
    tables = {}
    for level in ("sector", "industry", "subindustry"):
        rows = []
        for asset, frame in frames.items():
            for point, raw_category in zip(index, frame[level]):
                category = (
                    None if pd.isna(raw_category) else "%s-%s" % (level, int(float(raw_category)))
                )
                rows.append(
                    {
                        "time": point,
                        "asset": asset,
                        "level": level,
                        "category": category,
                        "effective_at": point,
                        "available_at": point,
                        "taxonomy_version": "synthetic-hierarchy-v1",
                    }
                )
        tables["pit_%s" % level] = pd.DataFrame(rows).set_index(["time", "asset"])
    # Valid schema and alias level, but intentionally wrong category hierarchy
    # for the Alpha100 distinguishing test.
    wrong_subindustry = tables["pit_industry"].copy(deep=True)
    wrong_subindustry["level"] = "subindustry"
    wrong_subindustry["taxonomy_version"] = "synthetic-industry-as-subindustry-v1"
    tables["pit_wrong_subindustry"] = wrong_subindustry
    return tables


def _factor_spec(name, indicator, *, classification_bindings=None):
    fields = tuple(indicator.formula_fields)
    field_bindings = {}
    for alias in fields:
        if alias == "dollar_volume":
            field_bindings[alias] = "feed:target:dollar_volume"
        elif alias.startswith("adv") and alias[3:].isdigit():
            window = int(alias[3:])
            field_bindings[alias] = {
                "derive": "adv",
                "source": "dollar_volume",
                "window": window,
            }
        else:
            field_bindings[alias] = "feed:target:%s" % alias
    classification_aliases = tuple(
        dict.fromkeys(
            tuple(getattr(indicator, "classification_fields", ()))
            + tuple(getattr(indicator, "classification_levels", ()))
        )
    )
    bindings = {alias: "table:pit_%s" % alias for alias in classification_aliases}
    if classification_bindings is not None:
        bindings.update(classification_bindings)
    return FactorSpec(
        name=name,
        indicator=indicator,
        panel_line="factor",
        field_bindings=field_bindings,
        classification_bindings=bindings,
    )


def _research_feed(frame, research, asset):
    """Use the canonical grid alignment while retaining synthetic PIT lines."""
    frame.attrs["source_metadata"] = {
        "fields": {
            "dollar_volume": {
                "name": "dollar_volume",
                "semantic": "daily_dollar_volume",
                "unit": "USD",
                "currency": "USD",
                "adjustment": "synthetic-unadjusted-v1",
                "source_version": "iteration45-synthetic-vwap-volume-v1",
            },
            "vwap": {
                "name": "vwap",
                "semantic": "volume_weighted_average_price",
                "unit": "USD per share",
                "currency": "USD",
                "adjustment": "synthetic-unadjusted-v1",
                "statistic": "trade_volume_weighted_mean",
                "source_version": "iteration45-synthetic-vwap-v1",
            },
            "volume": {
                "name": "volume",
                "semantic": "share_volume",
                "unit": "shares",
                "adjustment": "synthetic-unadjusted-v1",
                "source_version": "iteration45-synthetic-volume-v1",
            },
        }
    }
    aligned = prealign_bars(frame, research, asset)
    # The aligned public frame contains the full research grid for labels and
    # audit metadata.  Factor feeds must stop at research.end, as the native
    # adapter does, so post-end rows remain unavailable to the calculation.
    feed_frame = aligned.feed.p.dataname
    feed = _FactorData(dataname=feed_frame)
    setattr(
        feed,
        "_factor_research_alignment_v1",
        getattr(aligned.feed, "_factor_research_alignment_v1"),
    )
    return feed


def _matrix(frames, field):
    return [
        [float(frames[name][field].iloc[row]) for name in frames]
        for row in range(len(next(iter(frames.values()))))
    ]


def _distinguish_formula_input(frames, alpha_id):
    """Change one known input on the active branch for a boundary oracle."""
    changed = {name: frame.copy(deep=True) for name, frame in frames.items()}
    field, mode = _DISTINGUISHING_INPUTS[alpha_id]
    target_name = {
        48: "asset-1",  # Shares a subindustry with asset-2.
        96: "asset-2",
        100: "asset-1",  # Splits a shared subindustry for neutralization.
    }.get(alpha_id, "asset-0")
    target = changed[target_name]
    if mode == "scale":
        target[field] = target[field].astype(float) * 7.0 + 3.0
    elif mode == "large":
        target[field] = target[field].astype(float) * 10_000.0 + 3.0
    elif mode == "point_extreme":
        target.loc[target.index[-1], field] = 1_000_000.0
    elif mode == "all_alternating":
        target.loc[target.index[::2], field] = (
            target.loc[target.index[::2], field].astype(float) * 0.01
        )
        target.loc[target.index[1::2], field] = (
            target.loc[target.index[1::2], field].astype(float) * 100.0
        )
        if field == "volume":
            target["dollar_volume"] = target["vwap"] * target["volume"]
    elif mode == "alternating_mild":
        for offset in range(2):
            rows = target.index[offset::5]
            multiplier = 0.8 if offset == 0 else 1.2
            target.loc[rows, field] = target.loc[rows, field].astype(float) * multiplier
        target["dollar_volume"] = target["vwap"] * target["volume"]
    elif mode == "low_window":
        target.loc[target.index[-30:], field] = 0.01
    elif mode == "adv_gate":
        # Keep dollar volume consistent with the synthetic VWAP and shares.
        recent = target.index[-20:]
        target.loc[recent, "vwap"] = 0.001
        target.loc[recent, "dollar_volume"] = (
            target.loc[recent, "vwap"] * target.loc[recent, "volume"]
        )
    elif mode == "new_group":
        # Move one member of the asset-1/asset-2 pair into asset-0's group,
        # retaining a non-singleton cross-section after neutralization.
        target[field] = 0.0
    elif mode == "zero_range":
        target[field] = target["low"].astype(float)
    else:
        raise AssertionError("unknown formula boundary mutation")
    if field in ("vwap", "volume"):
        target["dollar_volume"] = target["vwap"] * target["volume"]
    return changed


def _valid(value):
    return math.isfinite(value)


def _floor(period):
    return math.floor(period)


def _pointwise(function, *matrices):
    rows = len(matrices[0])
    columns = len(matrices[0][0])
    output = [[math.nan] * columns for _ in range(rows)]
    for row in range(rows):
        for column in range(columns):
            values = [matrix[row][column] for matrix in matrices]
            if all(_valid(value) for value in values):
                try:
                    value = float(function(*values))
                except (ArithmeticError, ValueError):
                    continue
                if _valid(value):
                    output[row][column] = value
    return output


def _where(condition, true_values, false_values):
    output = [[math.nan] * len(condition[0]) for _ in condition]
    for row, conditions in enumerate(condition):
        for column, test in enumerate(conditions):
            if _valid(test):
                selected = true_values if test == 1.0 else false_values
                value = selected[row][column]
                if _valid(value):
                    output[row][column] = value
    return output


def _shift(source, period):
    period = _floor(period)
    return [
        [
            source[row - period][column] if row >= period else math.nan
            for column in range(len(source[0]))
        ]
        for row in range(len(source))
    ]


def _delta(source, period):
    return _pointwise(lambda current, previous: current - previous, source, _shift(source, period))


def _rolling(source, period, function):
    period = _floor(period)
    columns = len(source[0])
    output = [[math.nan] * columns for _ in source]
    for row in range(period - 1, len(source)):
        start = row - period + 1
        for column in range(columns):
            values = [source[position][column] for position in range(start, row + 1)]
            if all(_valid(value) for value in values):
                try:
                    value = float(function(values))
                except (ArithmeticError, ValueError):
                    continue
                if _valid(value):
                    output[row][column] = value
    return output


def _rank(values):
    ranked = [math.nan] * len(values)
    finite = [(index, value) for index, value in enumerate(values) if _valid(value)]
    count = len(finite)
    for index, value in finite:
        below = sum(other < value for _, other in finite)
        tied = sum(other == value for _, other in finite)
        ranked[index] = (below + (tied + 1) / 2.0) / count
    return ranked


def _cs_rank(source, members=None, groups=None):
    """Plain-array cross rank with optional formula membership and static groups."""
    asset_count = len(source[0])
    membership = members or [[True] * asset_count for _ in range(len(source))]
    group_keys = list(groups or ("default",) * asset_count)
    output = [[math.nan] * asset_count for _ in source]
    for row, values in enumerate(source):
        partitions = {}
        for column, key in enumerate(group_keys):
            if membership[row][column] and _valid(values[column]):
                partitions.setdefault(key, []).append(column)
        for columns in partitions.values():
            ranks = _rank([values[column] for column in columns])
            for column, value in zip(columns, ranks):
                output[row][column] = value
    return output


def _ts_rank(source, period):
    period = _floor(period)
    output = [[math.nan] * len(source[0]) for _ in source]
    for row in range(period - 1, len(source)):
        start = row - period + 1
        for column in range(len(source[0])):
            values = [source[position][column] for position in range(start, row + 1)]
            if all(_valid(value) for value in values):
                output[row][column] = _rank(values)[-1]
    return output


def _sum(values):
    return math.fsum(values)


def _mean(values):
    return math.fsum(values) / len(values)


def _std(values):
    average = _mean(values)
    return math.sqrt(math.fsum((value - average) ** 2 for value in values) / len(values))


def _covariance(left, right):
    # Treat each upstream float64 rank as the exact observed input, accumulate
    # the population covariance exactly, and round only the covariance result.
    # This independent rational reference preserves the sign of tiny real
    # covariances and avoids letting a different mean/center operation order
    # arbitrarily split or reverse a later cross-sectional rank.
    exact_left = [Fraction.from_float(float(value)) for value in left]
    exact_right = [Fraction.from_float(float(value)) for value in right]
    average_left = sum(exact_left, Fraction()) / len(exact_left)
    average_right = sum(exact_right, Fraction()) / len(exact_right)
    covariance = sum(
        ((x - average_left) * (y - average_right) for x, y in zip(exact_left, exact_right)),
        Fraction(),
    ) / len(exact_left)
    return float(covariance)


def test_alpha013_reference_preserves_binary64_near_zero_covariance_sign():
    # These are the exact rank lines observed at Alpha13 row 50 for two
    # assets.  The second covariance is small but negative for the actual
    # binary64 inputs; recovering idealized sixths or changing accumulation
    # order can turn it into zero or a positive value and change the final
    # exact-tie rank.
    first_close = [2.0 / 3.0] * 5
    first_volume = [2.0 / 3.0, 0.5, 0.5, 1.0 / 6.0, 1.0 / 3.0]
    second_close = [0.5, 5.0 / 6.0, 0.5, 1.0 / 6.0, 1.0 / 3.0]
    second_volume = [1.0, 1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0, 0.5]

    assert _covariance(first_close, first_volume) == 0.0
    second_covariance = _covariance(second_close, second_volume)
    assert second_covariance == pytest.approx(-1.295260195396016e-18, rel=0.0, abs=0.0)
    assert second_covariance < 0.0


def test_alpha063_reference_has_the_documented_negated_rank_difference_sign():
    frames = _frames()
    expected, intermediate = _formula_reference(63, frames)

    # At this synthetic row the ranks are 1/3 and 1/2. Alpha63 is
    # -(left_rank - right_rank), so its independent known answer is +1/6.
    left_rank = intermediate["left_rank"][238][0]
    right_rank = intermediate["right_rank"][238][0]
    assert left_rank == pytest.approx(1.0 / 3.0, rel=0.0, abs=1e-15)
    assert right_rank == pytest.approx(1.0 / 2.0, rel=0.0, abs=1e-15)
    assert expected[238][0] == pytest.approx(1.0 / 6.0, rel=0.0, abs=1e-15)


def test_alpha096_exact_float_correlation_tie_keeps_earliest_argmax():
    frames = _frames()
    _, intermediate = _formula_reference(96, frames)

    # For asset-2, rows 83 and 92 are distinct exact correlations below +1,
    # but both correctly round to the same binary64 value. The 12-point
    # argmax therefore chooses the earlier row instead of splitting a float64
    # tie based on an intermediate centering-roundoff difference.
    correlations = intermediate["long_correlation3"]
    assert correlations[83][2] == 1.0
    assert correlations[92][2] == 1.0
    assert intermediate["correlation_argmax12"][92][2] == 3.0


@pytest.mark.parametrize("runonce", (False, True))
def test_alpha081_exact_float_correlation_tie_keeps_average_rank(runonce):
    from tests.test_utils.alpha101_diagnostic_factors import Alpha081

    frames = _frames()
    expected, intermediate = _formula_reference(81, frames)

    # Assets 1 and 3 have distinct rank inputs, but their exact Pearson
    # correlations over the binary64 inputs round to the same result. The
    # cross-sectional rank therefore averages the two positions (5/6, 1),
    # rather than splitting the tie because a centering operation happened
    # to round one correlation a couple of ulps higher.
    assert intermediate["second_correlation5"][4][1] == 0.600099198148979
    assert intermediate["second_correlation5"][4][3] == 0.600099198148979
    assert intermediate["second_rank"][4][1] == 11.0 / 12.0
    assert intermediate["second_rank"][4][3] == 11.0 / 12.0
    assert math.isnan(expected[4][1])  # the enclosing factor still needs H=77

    strategy = _run_subset(frames, {"alpha81": Alpha081}, runonce=runonce)
    factor = strategy.factor_instances["alpha81"]
    native_correlation = _node_matrix(factor, "second_correlation5", len(frames))
    native_rank = _node_matrix(factor, "second_rank", len(frames))
    assert native_correlation[1][4] == 0.600099198148979
    assert native_correlation[3][4] == 0.600099198148979
    assert native_rank[1][4] == 11.0 / 12.0
    assert native_rank[3][4] == 11.0 / 12.0


def _correlation(left, right):
    # Interpret each input as its actual binary64 rational, then round only
    # the final Pearson coefficient. Plain float centering can put mathematically
    # near-one values on opposite sides of the exact tie seen by TsArgMax.
    left_exact = [Fraction.from_float(float(value)) for value in left]
    right_exact = [Fraction.from_float(float(value)) for value in right]
    count = len(left_exact)
    left_sum = sum(left_exact, Fraction())
    right_sum = sum(right_exact, Fraction())
    covariance_numerator = (
        count * sum((x * y for x, y in zip(left_exact, right_exact)), Fraction())
        - left_sum * right_sum
    )
    left_variance_numerator = count * sum((x * x for x in left_exact), Fraction()) - left_sum**2
    right_variance_numerator = count * sum((y * y for y in right_exact), Fraction()) - right_sum**2
    if left_variance_numerator <= 0 or right_variance_numerator <= 0:
        return math.nan
    denominator_squared = left_variance_numerator * right_variance_numerator

    with localcontext() as context:
        context.prec = 100
        covariance = Decimal(covariance_numerator.numerator) / Decimal(
            covariance_numerator.denominator
        )
        variance_product = Decimal(denominator_squared.numerator) / Decimal(
            denominator_squared.denominator
        )
        return float(covariance / variance_product.sqrt())


def _pair_rolling(left, right, period, function):
    return _rolling_pair(left, right, period, function)


def _rolling_pair(left, right, period, function):
    period = _floor(period)
    output = [[math.nan] * len(left[0]) for _ in left]
    for row in range(period - 1, len(left)):
        start = row - period + 1
        for column in range(len(left[0])):
            xs = [left[position][column] for position in range(start, row + 1)]
            ys = [right[position][column] for position in range(start, row + 1)]
            if all(_valid(value) for value in xs + ys):
                try:
                    value = float(function(xs, ys))
                except (ArithmeticError, ValueError):
                    continue
                if _valid(value):
                    output[row][column] = value
    return output


def _arg_position(values, maximum=False):
    target = max(values) if maximum else min(values)
    return float(next(index + 1 for index, value in enumerate(values) if value == target))


def _decay(values):
    denominator = len(values) * (len(values) + 1) / 2.0
    return math.fsum((index + 1) * value for index, value in enumerate(values)) / denominator


def _scale(source, multiplier=1.0, members=None, groups=None):
    output = [[math.nan] * len(source[0]) for _ in source]
    asset_count = len(source[0])
    membership = members or [[True] * asset_count for _ in source]
    group_keys = list(groups or ("default",) * asset_count)
    for row, values in enumerate(source):
        partitions = {}
        for column, value in enumerate(values):
            if membership[row][column] and _valid(value):
                partitions.setdefault(group_keys[column], []).append(column)
        for columns in partitions.values():
            denominator = math.fsum(abs(values[column]) for column in columns)
            if denominator:
                for column in columns:
                    output[row][column] = multiplier * values[column] / denominator
    return output


def _neutralize(source, groups, members=None):
    output = [[math.nan] * len(source[0]) for _ in source]
    asset_count = len(source[0])
    membership = members or [[True] * asset_count for _ in source]
    for row in range(len(source)):
        members = {}
        for column, value in enumerate(source[row]):
            group = groups[row][column]
            if membership[row][column] and _valid(value) and _valid(group):
                members.setdefault(group, []).append(column)
        for columns in members.values():
            average = math.fsum(source[row][column] for column in columns) / len(columns)
            for column in columns:
                output[row][column] = source[row][column] - average
    return output


def _formula_reference(alpha_id, frames, *, members=None, groups=None):
    """Evaluate one frozen formula from plain arrays and test-local math."""
    f = {
        field: _matrix(frames, field)
        for field in (
            "open",
            "high",
            "low",
            "close",
            "volume",
            "vwap",
            "dollar_volume",
            "cap",
            "sector",
            "industry",
            "subindustry",
        )
    }
    nodes = {}

    def cross_rank(values):
        return _cs_rank(values, members=members, groups=groups)

    def cross_scale(values):
        return _scale(values, members=members, groups=groups)

    def neutralize(values, categories):
        return _neutralize(values, categories, members=members)

    def remember(name, matrix):
        nodes[name] = matrix
        if name == "factor":
            return matrix, nodes
        return matrix

    def returns():
        return _pointwise(
            lambda current, previous: (current - previous) / previous,
            f["close"],
            _shift(f["close"], 1),
        )

    if alpha_id == 1:
        ret = returns()
        volatility = _rolling(ret, 20, _std)
        negative = _pointwise(lambda value: float(value < 0), ret)
        chosen = _where(negative, volatility, f["close"])
        powered = _pointwise(lambda value: math.copysign(abs(value) ** 2, value), chosen)
        argmax = _rolling(powered, 5, lambda values: _arg_position(values, True))
        return remember("factor", _pointwise(lambda value: value - 0.5, cross_rank(argmax)))
    if alpha_id == 2:
        log_volume = _pointwise(math.log, f["volume"])
        volume_change = _delta(log_volume, 2)
        gap = _pointwise(lambda close, open_: (close - open_) / open_, f["close"], f["open"])
        left, right = cross_rank(volume_change), cross_rank(gap)
        corr = _pair_rolling(left, right, 6, _correlation)
        return remember("factor", _pointwise(lambda value: -value, corr))
    if alpha_id == 3:
        corr = _pair_rolling(cross_rank(f["open"]), cross_rank(f["volume"]), 10, _correlation)
        return remember("factor", _pointwise(lambda value: -value, corr))
    if alpha_id == 4:
        return remember(
            "factor", _pointwise(lambda value: -value, _ts_rank(cross_rank(f["low"]), 9))
        )
    if alpha_id == 7:
        adv20 = _rolling(f["dollar_volume"], 20, _mean)
        change = _delta(f["close"], 7)
        abs_change = _pointwise(abs, change)
        ranks = _ts_rank(abs_change, 60)
        condition = _pointwise(lambda adv, volume: float(adv < volume), adv20, f["volume"])
        active = _pointwise(
            lambda rank, delta: -rank * (1 if delta > 0 else -1 if delta < 0 else 0),
            ranks,
            change,
        )
        fallback = [[-1.0] * len(f["close"][0]) for _ in f["close"]]
        return remember("factor", _where(condition, active, fallback))
    if alpha_id == 9:
        change = _delta(f["close"], 1)
        minimum = _rolling(change, 5, min)
        maximum = _rolling(change, 5, max)
        return remember(
            "factor",
            _pointwise(
                lambda low, high, delta: delta if low > 0 else delta if high < 0 else -delta,
                minimum,
                maximum,
                change,
            ),
        )
    if alpha_id == 13:
        covariance = _pair_rolling(cross_rank(f["close"]), cross_rank(f["volume"]), 5, _covariance)
        remember("covariance5", covariance)
        return remember("factor", _pointwise(lambda value: -value, cross_rank(covariance)))
    if alpha_id == 29:
        close_minus_one = _pointwise(lambda value: value - 1.0, f["close"])
        remember("close_minus_one", close_minus_one)
        change = _delta(close_minus_one, 5)
        remember("delta5", change)
        rank_once = cross_rank(change)
        remember("rank_delta", rank_once)
        negative_rank = _pointwise(lambda value: -value, rank_once)
        remember("negative_rank", negative_rank)
        rank_twice = cross_rank(negative_rank)
        remember("rank_negative_rank", rank_twice)
        rank_thrice = cross_rank(rank_twice)
        remember("rank_rank_negative", rank_thrice)
        minimum = _rolling(rank_thrice, 2, min)
        remember("ts_min2", minimum)
        summed = _rolling(minimum, 1, _sum)
        remember("sum1", summed)
        logged = _pointwise(math.log, summed)
        remember("log_sum", logged)
        scaled = cross_scale(logged)
        remember("scale_log", scaled)
        ranked = cross_rank(scaled)
        remember("rank_scaled", ranked)
        ranked_twice = cross_rank(ranked)
        remember("rank_rank_scaled", ranked_twice)
        product = _rolling(ranked_twice, 1, math.prod)
        remember("product1", product)
        minimum5 = _rolling(product, 5, min)
        remember("ts_min5", minimum5)
        negative_returns = _pointwise(lambda value: -value, returns())
        remember("negative_returns", negative_returns)
        delayed = _shift(negative_returns, 6)
        remember("delay6", delayed)
        delayed_rank = _ts_rank(delayed, 5)
        remember("ts_rank5", delayed_rank)
        return remember(
            "factor", _pointwise(lambda left, right: left + right, minimum5, delayed_rank)
        )
    if alpha_id == 48:
        delta_now = _delta(f["close"], 1)
        delay_close = _shift(f["close"], 1)
        delta_delay = _delta(delay_close, 1)
        corr = _pair_rolling(delta_now, delta_delay, 250, _correlation)
        corr_times_delta = _pointwise(lambda value, change: value * change, corr, delta_now)
        numerator = _pointwise(lambda value, close: value / close, corr_times_delta, f["close"])
        neutral = neutralize(numerator, f["subindustry"])
        returns_squared = _pointwise(
            lambda change, previous: ((change / previous) ** 2), delta_now, delay_close
        )
        denominator = _rolling(returns_squared, 250, _sum)
        remember("delta_close1", delta_now)
        remember("delay_close1", delay_close)
        remember("delta_delay_close1", delta_delay)
        remember("correlation250", corr)
        remember("corr_times_delta", corr_times_delta)
        remember("price_normalized", numerator)
        remember("neutralized_numerator", neutral)
        remember("return_ratio", _pointwise(lambda x, y: x / y, delta_now, delay_close))
        remember("return_ratio_squared", returns_squared)
        remember("square_sum250", denominator)
        return remember(
            "factor", _pointwise(lambda value, total: value / total, neutral, denominator)
        )
    if alpha_id == 56:
        ret = returns()
        total10 = _rolling(ret, 10, _sum)
        total2 = _rolling(ret, 2, _sum)
        nested = _rolling(total2, 3, _sum)
        ratio = _pointwise(lambda left, right: left / right, total10, nested)
        rank_ratio = cross_rank(ratio)
        return_cap = _pointwise(lambda value, cap: value * cap, ret, f["cap"])
        cap_rank = cross_rank(return_cap)
        product = _pointwise(lambda left, right: -(left * right), rank_ratio, cap_rank)
        remember("returns", ret)
        remember("sum_returns10", total10)
        remember("sum_returns2", total2)
        remember("sum_of_sum3", nested)
        remember("sum_ratio", ratio)
        remember("rank_sum_ratio", rank_ratio)
        remember("return_times_cap", return_cap)
        remember("rank_return_cap", cap_rank)
        remember("rank_product", _pointwise(lambda left, right: left * right, rank_ratio, cap_rank))
        return remember("factor", product)
    if alpha_id == 58:
        neutral = neutralize(f["vwap"], f["sector"])
        corr = _pair_rolling(neutral, f["volume"], 3.92795, _correlation)
        decay = _rolling(corr, 7.89291, _decay)
        ranks = _ts_rank(decay, 5.50322)
        remember("sector_neutral_vwap", neutral)
        remember("correlation3", corr)
        remember("decay7", decay)
        return remember("factor", _pointwise(lambda value: -value, ranks))
    if alpha_id == 62:
        adv20 = _rolling(f["dollar_volume"], 20, _mean)
        adv_sum = _rolling(adv20, 22.4101, _sum)
        corr = _pair_rolling(f["vwap"], adv_sum, 9.91009, _correlation)
        corr_rank = cross_rank(corr)
        open_rank = cross_rank(f["open"])
        mid = _pointwise(lambda high, low: (high + low) / 2.0, f["high"], f["low"])
        mid_rank, high_rank = cross_rank(mid), cross_rank(f["high"])
        inside = _pointwise(
            lambda left, right: float(left < right),
            _pointwise(lambda value: 2.0 * value, open_rank),
            _pointwise(lambda left, right: left + right, mid_rank, high_rank),
        )
        nested_rank = cross_rank(inside)
        outer = _pointwise(lambda left, right: -float(left < right), corr_rank, nested_rank)
        remember("adv20_sum22", adv_sum)
        remember("correlation9", corr)
        remember("rank_correlation", corr_rank)
        remember("rank_open_left", open_rank)
        remember("rank_open_right", open_rank)
        remember("open_rank_sum", _pointwise(lambda value: 2.0 * value, open_rank))
        remember("high_plus_low", _pointwise(lambda high, low: high + low, f["high"], f["low"]))
        remember("midpoint", mid)
        remember("rank_midpoint", mid_rank)
        remember("rank_high", high_rank)
        remember(
            "midpoint_plus_high_rank",
            _pointwise(lambda left, right: left + right, mid_rank, high_rank),
        )
        remember("nested_comparison", inside)
        remember("rank_nested_bool", nested_rank)
        remember(
            "outer_comparison",
            _pointwise(lambda left, right: float(left < right), corr_rank, nested_rank),
        )
        return remember(
            "factor",
            outer,
        )
    if alpha_id == 63:
        neutral_close = neutralize(f["close"], f["industry"])
        close_delta = _delta(neutral_close, 2.25164)
        left_decay = _rolling(close_delta, 8.22237, _decay)
        left_rank = cross_rank(left_decay)
        price_mix = _pointwise(
            lambda vwap, open_: vwap * 0.318108 + open_ * (1.0 - 0.318108),
            f["vwap"],
            f["open"],
        )
        adv180 = _rolling(f["dollar_volume"], 180, _mean)
        adv_sum = _rolling(adv180, 37.2467, _sum)
        corr = _pair_rolling(price_mix, adv_sum, 13.557, _correlation)
        right_decay = _rolling(corr, 12.2883, _decay)
        right_rank = cross_rank(right_decay)
        remember("industry_neutral_close", neutral_close)
        remember("left_rank", left_rank)
        remember("right_rank", right_rank)
        return remember(
            "factor", _pointwise(lambda left, right: right - left, left_rank, right_rank)
        )
    if alpha_id == 67:
        high_min = _rolling(f["high"], 2.14593, min)
        high_excess = _pointwise(lambda high, low: high - low, f["high"], high_min)
        base = cross_rank(high_excess)
        sector_vwap = neutralize(f["vwap"], f["sector"])
        adv20 = _rolling(f["dollar_volume"], 20, _mean)
        subindustry_adv = neutralize(adv20, f["subindustry"])
        correlation = _pair_rolling(sector_vwap, subindustry_adv, 6.02936, _correlation)
        exponent = cross_rank(correlation)
        powered = _pointwise(math.pow, base, exponent)
        remember("high_min2", high_min)
        remember("high_minus_min", high_excess)
        remember("rank_base", base)
        remember("sector_neutral_vwap", sector_vwap)
        remember("subindustry_neutral_adv20", subindustry_adv)
        remember("exponent_correlation6", correlation)
        remember("rank_exponent", exponent)
        remember("ordinary_power", powered)
        return remember("factor", _pointwise(lambda value: -value, powered))
    if alpha_id == 81:
        adv10 = _rolling(f["dollar_volume"], 10, _mean)
        adv_sum = _rolling(adv10, 49.6054, _sum)
        corr = _pair_rolling(f["vwap"], adv_sum, 8.47743, _correlation)
        ranked = cross_rank(corr)
        powered_rank = cross_rank(_pointwise(lambda value: value**4, ranked))
        product = _rolling(powered_rank, 14.9655, math.prod)
        logged = _pointwise(math.log, product)
        left_rank = cross_rank(logged)
        vwap_rank = cross_rank(f["vwap"])
        volume_rank = cross_rank(f["volume"])
        second_corr = _pair_rolling(vwap_rank, volume_rank, 5.07914, _correlation)
        right_rank = cross_rank(second_corr)
        comparison = _pointwise(lambda left, right: -float(left < right), left_rank, right_rank)
        remember("adv10_sum49", adv_sum)
        remember("correlation8", corr)
        remember("first_rank", ranked)
        remember("rank_power4", _pointwise(lambda value: value**4, ranked))
        remember("powered_rank", powered_rank)
        remember("product14", product)
        remember("log_product", logged)
        remember("rank_log_product", left_rank)
        remember("rank_vwap", vwap_rank)
        remember("rank_volume", volume_rank)
        remember("second_correlation5", second_corr)
        remember("second_rank", right_rank)
        remember(
            "comparison", _pointwise(lambda left, right: float(left < right), left_rank, right_rank)
        )
        return remember("factor", comparison)
    if alpha_id == 84:
        maximum = _rolling(f["vwap"], 15.3217, max)
        offset = _pointwise(lambda value, high: value - high, f["vwap"], maximum)
        base = _ts_rank(offset, 20.7127)
        exponent = _delta(f["close"], 4.96796)
        signed = _pointwise(
            lambda value, power: math.copysign(abs(value) ** power, value), base, exponent
        )
        remember("vwap_max15", maximum)
        remember("vwap_minus_max", offset)
        remember("ts_rank20", base)
        remember("close_delta4", exponent)
        remember("signed_power", signed)
        return remember("factor", signed)
    if alpha_id == 92:
        midpoint = _pointwise(lambda high, low: (high + low) / 2.0, f["high"], f["low"])
        condition = _pointwise(
            lambda midpoint_, close, low, open_: float(midpoint_ + close < low + open_),
            midpoint,
            f["close"],
            f["low"],
            f["open"],
        )
        bool_decay = _rolling(condition, 14.7221, _decay)
        left = _ts_rank(bool_decay, 18.8683)
        low_rank = cross_rank(f["low"])
        adv30 = _rolling(f["dollar_volume"], 30, _mean)
        adv_rank = cross_rank(adv30)
        corr = _pair_rolling(low_rank, adv_rank, 7.58555, _correlation)
        correlation_decay = _rolling(corr, 6.94024, _decay)
        right = _ts_rank(correlation_decay, 6.80584)
        remember("midpoint", midpoint)
        remember(
            "midpoint_plus_close",
            _pointwise(lambda left, right: left + right, midpoint, f["close"]),
        )
        remember("low_plus_open", _pointwise(lambda left, right: left + right, f["low"], f["open"]))
        remember("midpoint_less_low_open", condition)
        remember("bool_decay14", bool_decay)
        remember("bool_ts_rank18", left)
        remember("rank_low", low_rank)
        remember("rank_adv30", adv_rank)
        remember("correlation7", corr)
        remember("correlation_decay6", correlation_decay)
        remember("correlation_ts_rank6", right)
        return remember("factor", _pointwise(min, left, right))
    if alpha_id == 96:
        short_corr = _pair_rolling(
            cross_rank(f["vwap"]), cross_rank(f["volume"]), 3.83878, _correlation
        )
        short_decay = _rolling(short_corr, 4.16783, _decay)
        left = _ts_rank(short_decay, 8.38151)
        close_rank = _ts_rank(f["close"], 7.45404)
        adv60 = _rolling(f["dollar_volume"], 60, _mean)
        adv_rank = _ts_rank(adv60, 4.13242)
        long_corr = _pair_rolling(close_rank, adv_rank, 3.65459, _correlation)
        argmax = _rolling(long_corr, 12.6556, lambda values: _arg_position(values, True))
        right = _ts_rank(_rolling(argmax, 14.0365, _decay), 13.4143)
        remember("short_correlation3", short_corr)
        remember("short_decay4", short_decay)
        remember("left_ts_rank8", left)
        remember("close_ts_rank7", close_rank)
        remember("adv60_ts_rank4", adv_rank)
        remember("long_correlation3", long_corr)
        remember("correlation_argmax12", argmax)
        remember("long_decay14", _rolling(argmax, 14.0365, _decay))
        remember("right_ts_rank13", right)
        return remember(
            "factor", _pointwise(lambda left_, right_: -max(left_, right_), left, right)
        )
    if alpha_id == 100:
        price_position = _pointwise(
            lambda close, low, high: ((close - low) - (high - close)) / (high - low),
            f["close"],
            f["low"],
            f["high"],
        )
        ranked_position = cross_rank(
            _pointwise(lambda position, volume: position * volume, price_position, f["volume"])
        )
        first_neutralized = neutralize(ranked_position, f["subindustry"])
        second_neutralized = neutralize(first_neutralized, f["subindustry"])
        first = cross_scale(second_neutralized)
        first = _pointwise(lambda value: 1.5 * value, first)
        adv20 = _rolling(f["dollar_volume"], 20, _mean)
        adv_rank = cross_rank(adv20)
        corr = _pair_rolling(f["close"], adv_rank, 5, _correlation)
        argmin = _rolling(f["close"], 30, lambda values: _arg_position(values, False))
        argmin_rank = cross_rank(argmin)
        third_input = _pointwise(lambda left, right: left - right, corr, argmin_rank)
        third_neutralized = neutralize(third_input, f["subindustry"])
        second = cross_scale(third_neutralized)
        remember("first_subindustry_neutralize", first_neutralized)
        remember("second_subindustry_neutralize", second_neutralized)
        remember("third_subindustry_neutralize", third_neutralized)
        remember("second_scale", second)
        remember("close_argmin30", argmin)
        return remember(
            "factor",
            _pointwise(
                lambda left, right, volume, adv: -((left - right) * (volume / adv)),
                first,
                second,
                f["volume"],
                adv20,
            ),
        )
    if alpha_id == 101:
        return remember(
            "factor",
            _pointwise(
                lambda close, open_, high, low: (close - open_) / ((high - low) + 0.001),
                f["close"],
                f["open"],
                f["high"],
                f["low"],
            ),
        )
    raise AssertionError("missing independent formula for Alpha%d" % alpha_id)


def _run(frames, *, runonce):
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    research = _research_spec(frames)
    for name, frame in frames.items():
        cerebro.adddata(_research_feed(frame, research, name), name=name)
    factors = {
        "alpha%d" % alpha_id: _factor_spec("alpha%d" % alpha_id, REPRESENTATIVE_FACTORS[alpha_id])
        for alpha_id in _ALPHA_IDS
    }
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    return cerebro.run()[0]


def _assert_matrix(actual, expected, names, *, label):
    assert len(actual) == len(expected), label
    for row, wanted in enumerate(expected):
        for column, value in enumerate(wanted):
            got = float(actual[row][column])
            if math.isnan(value):
                assert math.isnan(got), "%s at (%d, %d): expected NaN, got %r" % (
                    label,
                    row,
                    column,
                    got,
                )
            else:
                assert math.isfinite(got), "%s at (%d, %d): expected finite, got %r" % (
                    label,
                    row,
                    column,
                    got,
                )
                tolerance = 1e-12 + 1e-10 * abs(value)
                assert (
                    abs(got - value) <= tolerance
                ), "%s/%s at row %d: got %.17g, expected %.17g, tolerance %.17g" % (
                    label,
                    names[column],
                    row,
                    got,
                    value,
                    tolerance,
                )


def _node_matrix(factor, name, asset_count):
    node = factor._nodes.get(name)
    if node is not None and hasattr(node, "outputs"):
        return [list(node.outputs[data].value.array) for data in factor.datas]
    return [
        list(factor._nodes["%s_%d" % (name, index)].lines.value.array)
        for index in range(asset_count)
    ]


@pytest.mark.parametrize("runonce", (False, True))
def test_twenty_native_representatives_match_independent_grid_reference(runonce):
    frames = _frames()
    names = tuple(frames)
    strategy = _run(frames, runonce=runonce)
    dataset = strategy.get_dataset().raw_factors
    grid = tuple(next(iter(frames.values())).index.to_pydatetime())

    assert set(strategy.factor_instances) == {"alpha%d" % alpha_id for alpha_id in _ALPHA_IDS}
    for alpha_id in _ALPHA_IDS:
        factor = strategy.factor_instances["alpha%d" % alpha_id]
        expected, intermediate = _formula_reference(alpha_id, frames)
        # Formula nodes retain genuine branch values during warmup, while the
        # research collector marks every declared-H row as incomplete.
        expected = [
            row if row_index >= _HISTORY[alpha_id] else [math.nan] * len(names)
            for row_index, row in enumerate(expected)
        ]
        actual = [
            [dataset.at[(grid[row], name), "alpha%d" % alpha_id] for name in names]
            for row in range(len(grid))
        ]
        _assert_matrix(actual, expected, names, label="Alpha%d" % alpha_id)
        assert isinstance(factor, FactorIndicator)
        assert factor._minperiod == _HISTORY[alpha_id] + 1
        assert factor.lifecycle_diagnostics["call_count"] == len(grid)
        assert factor.lifecycle_diagnostics["grid_matches"]
        assert len(factor.datas) == len(names)
        for data in factor.datas:
            assert isinstance(factor.outputs[data].factor, bt.LineBuffer)
            assert len(factor.outputs[data].factor) == len(grid)

        if alpha_id in {13, 29, 48, 56, 58, 62, 63, 67, 81, 84, 92, 96, 100}:
            for name in intermediate:
                node_expected = intermediate[name]
                # The mapped intermediates below deliberately span both native
                # scalar and multi-feed operator nodes.
                if name in factor._nodes or "%s_0" % name in factor._nodes:
                    actual_by_asset = _node_matrix(factor, name, len(names))
                    actual_by_time = [
                        [actual_by_asset[column][row] for column in range(len(names))]
                        for row in range(len(grid))
                    ]
                    _assert_matrix(
                        actual_by_time, node_expected, names, label="Alpha%d.%s" % (alpha_id, name)
                    )
        if alpha_id == 96:
            left = intermediate["left_ts_rank8"]
            right = intermediate["right_ts_rank13"]
            left_wins = any(
                math.isfinite(left[row][asset])
                and math.isfinite(right[row][asset])
                and left[row][asset] > right[row][asset]
                for row in range(len(grid))
                for asset in range(len(names))
            )
            right_wins = any(
                math.isfinite(left[row][asset])
                and math.isfinite(right[row][asset])
                and right[row][asset] > left[row][asset]
                for row in range(len(grid))
                for asset in range(len(names))
            )
            assert left_wins and right_wins, "Alpha96 fixture must switch max branches"
        if alpha_id == 84:
            base = intermediate["ts_rank20"]
            exponent = intermediate["close_delta4"]
            signed = intermediate["signed_power"]
            negative_exponent = []
            positive_exponent = []
            for row in range(len(grid)):
                for asset in range(len(names)):
                    value = base[row][asset]
                    power = exponent[row][asset]
                    result = signed[row][asset]
                    if not all(math.isfinite(item) for item in (value, power, result)):
                        continue
                    assert value > 0.0
                    assert result == pytest.approx(value**power, rel=1e-12, abs=1e-12)
                    if power < 0.0:
                        negative_exponent.append(result)
                    elif power > 0.0:
                        positive_exponent.append(result)
            assert any(value > 1.0 for value in negative_exponent)
            assert any(value < 1.0 for value in positive_exponent)


@pytest.mark.parametrize("alpha_id", _ALPHA_IDS)
def test_every_formula_has_a_positive_finite_distinguishing_input_boundary(alpha_id):
    frames = _frames()
    changed = _distinguish_formula_input(frames, alpha_id)
    before, _ = _formula_reference(alpha_id, frames)
    after, _ = _formula_reference(alpha_id, changed)
    h = _HISTORY[alpha_id]

    # All market-value inputs in this fixture are positive and finite. This
    # gives each formula a real finite calculation alongside its warm-up NaNs.
    for panel in (frames, changed):
        for frame in panel.values():
            for field in ("open", "high", "low", "close", "volume", "vwap", "dollar_volume", "cap"):
                values = [float(value) for value in frame[field]]
                assert all(math.isfinite(value) and value > 0.0 for value in values)

    assert any(math.isfinite(value) for row in before[h:] for value in row)
    assert any(math.isfinite(value) for row in after[h:] for value in row)
    witnesses = [
        (row, asset, old, new)
        for row, (old_row, new_row) in enumerate(zip(before[h:], after[h:]), start=h)
        for asset, (old, new) in enumerate(zip(old_row, new_row))
        if not (math.isnan(old) and math.isnan(new))
        and (
            not math.isfinite(old)
            or not math.isfinite(new)
            or not math.isclose(old, new, rel_tol=1e-12, abs_tol=1e-12)
        )
    ]
    assert witnesses, "Alpha%d boundary mutation did not distinguish its formula" % alpha_id
    assert any(math.isfinite(old) or math.isfinite(new) for _, _, old, new in witnesses)


def test_manual_known_answers_for_alpha003_alpha004_alpha009_and_alpha013():
    from tests.test_utils.alpha101_diagnostic_factors import Alpha003, Alpha004, Alpha009, Alpha013

    rank_open = (
        (1, 2, 3),
        (2, 3, 1),
        (3, 1, 2),
        (1, 2, 3),
        (2, 3, 1),
        (3, 1, 2),
        (1, 2, 3),
        (2, 3, 1),
        (3, 1, 2),
        (1, 2, 3),
    )
    rank_volume = (
        (3, 2, 1),
        (2, 1, 3),
        (1, 3, 2),
        (3, 2, 1),
        (2, 1, 3),
        (1, 3, 2),
        (3, 2, 1),
        (2, 1, 3),
        (1, 3, 2),
        (1, 2, 3),
    )
    grid = pd.date_range("2024-02-01", periods=10, freq="D", tz="UTC")
    frames = {}
    for asset, column in zip(("A", "B", "C"), range(3)):
        frames[asset] = _minimal_frame(
            grid,
            open_=[10 + row[column] for row in rank_open],
            volume=[100 * row[column] for row in rank_volume],
            low=[0.5] * 10,
            close=[10.0] * 10,
            high=[20.0] * 10,
        )
    strategy = _run_subset(frames, {"alpha3": Alpha003})
    last = strategy.get_dataset().raw_factors.xs(grid[-1], level="time")["alpha3"]
    assert last.loc["A"] == pytest.approx(17 / 23)
    assert last.loc["B"] == pytest.approx(1.0)
    assert last.loc["C"] == pytest.approx(17 / 23)

    low_ranks = (
        (1, 2, 3),
        (2, 1, 3),
        (3, 1, 2),
        (1, 3, 2),
        (2, 1, 3),
        (3, 1, 2),
        (1, 2, 3),
        (2, 1, 3),
        (3, 1, 2),
    )
    grid9 = grid[:9]
    frames4 = {
        asset: _minimal_frame(
            grid9,
            open_=[10.0] * 9,
            high=[12.0] * 9,
            low=[row[column] for row in low_ranks],
            close=[11.0] * 9,
            volume=[100.0] * 9,
        )
        for asset, column in zip(("A", "B", "C"), range(3))
    }
    strategy4 = _run_subset(frames4, {"alpha4": Alpha004})
    assert strategy4.get_dataset().raw_factors.at[(grid9[-1], "A"), "alpha4"] == pytest.approx(
        -8 / 9
    )

    sequence = (100.0, 101.0, 102.0, 101.0, 100.0, 102.0)
    grid6 = grid[:6]
    frames9 = {"A": _minimal_frame(grid6, close=sequence)}
    strategy9 = _run_subset(frames9, {"alpha9": Alpha009})
    assert strategy9.get_dataset().raw_factors.at[(grid6[-1], "A"), "alpha9"] == pytest.approx(-2.0)

    ranks13 = ((1, 2, 3, 4), (1, 2, 3, 4), (1, 2, 4, 3), (3, 1, 4, 2), (4, 3, 1, 2))
    grid5 = grid[:5]
    frames13 = {
        "ABCD"[column]: _minimal_frame(
            grid5,
            close=[10 + row[column] for row in ranks13],
            volume=[100 * row[column] for row in ranks13],
            open_=[10.0] * 5,
            low=[9.0] * 5,
            high=[15.0] * 5,
        )
        for column in range(4)
    }
    strategy13 = _run_subset(frames13, {"alpha13": Alpha013})
    terminal = strategy13.get_dataset().raw_factors.xs(grid5[-1], level="time")["alpha13"]
    assert [terminal.loc[asset] for asset in "ABCD"] == pytest.approx([-1.0, -0.25, -0.75, -0.5])


@pytest.mark.parametrize("runonce", (False, True))
def test_alpha013_near_zero_covariance_matches_exact_float_input_oracle(runonce):
    from tests.test_utils.alpha101_diagnostic_factors import Alpha013

    frames = _frames(periods=56)
    strategy = _run_subset(frames, {"alpha13": Alpha013}, runonce=runonce)
    expected, trace = _formula_reference(13, frames)
    factor = strategy.factor_instances["alpha13"]
    dataset = strategy.get_dataset().raw_factors["alpha13"].unstack("asset")
    names = tuple(frames)

    _assert_matrix(dataset.values.tolist(), expected, names, label="Alpha13 exact-float oracle")
    actual_covariance = _node_matrix(factor, "covariance5", len(names))
    row = 50
    assert actual_covariance[1][row] == 0.0
    assert actual_covariance[2][row] == pytest.approx(-1.295260195396016e-18, rel=0.0, abs=0.0)
    assert trace["covariance5"][row][1] == 0.0
    assert trace["covariance5"][row][2] < 0.0


def _minimal_frame(index, *, open_=None, high=None, low=None, close=None, volume=None, vwap=None):
    count = len(index)
    open_ = list(open_ if open_ is not None else (close if close is not None else [10.0] * count))
    close = list(close if close is not None else open_)
    high = list(high if high is not None else [value + 1 for value in close])
    low = list(low if low is not None else [value - 1 for value in close])
    volume = list(volume if volume is not None else [100.0] * count)
    if vwap is None:
        vwap = [5.25 + 0.17 * math.sin(row * 0.7) for row in range(count)]
    else:
        vwap = list(vwap)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "openinterest": [0.0] * count,
            "vwap": vwap,
            "dollar_volume": [price * shares for price, shares in zip(vwap, volume)],
            "cap": [1000.0] * count,
            "sector": [1.0] * count,
            "industry": [1.0] * count,
            "subindustry": [1.0] * count,
        },
        index=index,
    )


def _run_subset(
    frames,
    factor_classes,
    *,
    runonce=True,
    formula_universe=None,
    groups=None,
    classification_bindings=None,
):
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    research = _research_spec(frames, formula_universe=formula_universe, groups=groups)
    for name, frame in frames.items():
        cerebro.adddata(_research_feed(frame, research, name), name=name)
    overrides = classification_bindings or {}
    specs = {
        name: _factor_spec(
            name,
            indicator,
            classification_bindings=overrides.get(name),
        )
        for name, indicator in factor_classes.items()
    }
    cerebro.addstrategy(FactorStrategy, research=research, factors=specs)
    return cerebro.run()[0]


def test_alpha101_positive_finite_known_answers_and_zero_range_boundary():
    from tests.test_utils.alpha101_diagnostic_factors import Alpha101

    grid = pd.date_range("2024-04-01", periods=1, freq="D", tz="UTC")
    frames = {
        "positive": _minimal_frame(grid, open_=[10.0], high=[16.0], low=[8.0], close=[14.0]),
        "zero-range": _minimal_frame(grid, open_=[10.0], high=[10.0], low=[10.0], close=[10.0]),
    }
    strategy = _run_subset(frames, {"alpha101": Alpha101})
    actual = strategy.get_dataset().raw_factors["alpha101"]
    assert actual.at[(grid[0], "positive")] == pytest.approx(4.0 / 8.001, rel=1e-14)
    assert actual.at[(grid[0], "zero-range")] == 0.0
    assert all(math.isfinite(value) for value in actual)


@pytest.mark.parametrize("runonce", (False, True))
def test_alpha048_zero_ratio_window_and_252_point_h_boundary(runonce):
    from tests.test_utils.alpha101_diagnostic_factors import Alpha048

    frames = _frames(periods=252)
    frames["asset-0"]["close"] = 100.0
    strategy = _run_subset(frames, {"alpha48": Alpha048}, runonce=runonce)
    factor = strategy.factor_instances["alpha48"]
    denominator = factor._nodes["square_sum250_0"].lines.value.array
    grid = tuple(next(iter(frames.values())).index.to_pydatetime())
    raw = strategy.get_dataset().raw_factors

    assert factor.lookback_h == 251
    assert factor._minperiod == 252
    assert math.isnan(denominator[249])
    assert denominator[250] == pytest.approx(0.0, abs=1e-15)
    assert denominator[251] == pytest.approx(0.0, abs=1e-15)
    assert math.isnan(raw.at[(grid[250], "asset-0"), "alpha48"])
    assert math.isnan(raw.at[(grid[251], "asset-0"), "alpha48"])


def test_formula_universe_and_static_groups_bound_cross_sectional_rank_and_scale():
    from tests.test_utils.alpha101_diagnostic_factors import Alpha029

    frames = _frames(periods=100)
    names = tuple(frames)
    index = next(iter(frames.values())).index
    keys = pd.MultiIndex.from_product([index, names], names=("time", "asset"))
    eligible = pd.Series(True, index=keys, dtype=bool)
    eligible.loc[eligible.index.get_level_values("asset") == "asset-5"] = False
    groups = {
        "asset-0": "group-a",
        "asset-1": "group-a",
        "asset-2": "group-a",
        "asset-3": "group-b",
        "asset-4": "group-b",
        "asset-5": "group-b",
    }
    member_row = [name != "asset-5" for name in names]
    member_matrix = [list(member_row) for _ in index]
    group_vector = [groups[name] for name in names]

    def run(panel):
        return _run_subset(
            panel,
            {"alpha29": Alpha029},
            formula_universe=eligible,
            groups=groups,
        )

    baseline = run(frames)
    expected, trace = _formula_reference(29, frames, members=member_matrix, groups=group_vector)
    actual_factor = baseline.get_dataset().raw_factors["alpha29"].unstack("asset")
    _assert_matrix(
        actual_factor.values.tolist(),
        expected,
        names,
        label="Alpha29 with formula membership/groups",
    )
    baseline_factor = baseline.factor_instances["alpha29"]
    for node_name in ("rank_delta", "scale_log"):
        actual_by_asset = _node_matrix(baseline_factor, node_name, len(names))
        actual_by_time = [
            [actual_by_asset[column][row] for column in range(len(names))]
            for row in range(len(index))
        ]
        _assert_matrix(
            actual_by_time,
            trace[node_name],
            names,
            label="Alpha29.%s with formula membership/groups" % node_name,
        )
    assert all(
        math.isnan(_node_matrix(baseline_factor, "rank_delta", len(names))[5][row])
        for row in range(len(index))
    )

    excluded_change = {name: frame.copy(deep=True) for name, frame in frames.items()}
    excluded_change["asset-5"]["close"] *= 100.0
    excluded_run = run(excluded_change)
    excluded_factor = excluded_run.factor_instances["alpha29"]
    for node_name in ("rank_delta", "scale_log"):
        before = _node_matrix(baseline_factor, node_name, len(names))
        after = _node_matrix(excluded_factor, node_name, len(names))
        for asset_index in range(5):
            for row in range(len(index)):
                old, new = before[asset_index][row], after[asset_index][row]
                assert math.isnan(old) == math.isnan(new)
                if math.isfinite(old):
                    assert new == pytest.approx(old, rel=1e-12, abs=1e-12)

    other_group_change = {name: frame.copy(deep=True) for name, frame in frames.items()}
    other_group_change["asset-4"]["close"] *= 10.0
    other_group_run = run(other_group_change)
    other_group_factor = other_group_run.factor_instances["alpha29"]
    for node_name in ("rank_delta", "scale_log"):
        before = _node_matrix(baseline_factor, node_name, len(names))
        after = _node_matrix(other_group_factor, node_name, len(names))
        for asset_index in (0, 1, 2):
            for row in range(len(index)):
                old, new = before[asset_index][row], after[asset_index][row]
                assert math.isnan(old) == math.isnan(new)
                if math.isfinite(old):
                    assert new == pytest.approx(old, rel=1e-12, abs=1e-12)
    baseline_rank = _node_matrix(baseline_factor, "rank_delta", len(names))
    other_rank = _node_matrix(other_group_factor, "rank_delta", len(names))
    assert any(
        math.isfinite(old) and math.isfinite(new) and not math.isclose(old, new)
        for asset_index in (3, 4)
        for old, new in zip(baseline_rank[asset_index], other_rank[asset_index])
    )


def test_pit_classification_and_missing_grid_boundaries_are_point_in_time():
    from tests.test_utils.alpha101_diagnostic_factors import (
        Alpha009,
        Alpha058,
        Alpha063,
        Alpha067,
        Alpha100,
    )
    from backtrader.research.operators import OperatorReason

    baseline = _frames()
    changed = {name: frame.copy(deep=True) for name, frame in baseline.items()}
    cutoff = 205
    # A future classification edit must not change any earlier output.
    changed["asset-0"].loc[changed["asset-0"].index[cutoff] :, "sector"] = 12.0
    classes = {"sector": Alpha058, "industry": Alpha063, "levels": Alpha067, "neutral": Alpha100}
    before = _run_subset(baseline, classes)
    after = _run_subset(changed, classes)
    old = before.get_dataset().raw_factors
    new = after.get_dataset().raw_factors
    prefix = old.index.get_level_values("time") < changed["asset-0"].index[cutoff]
    pd.testing.assert_frame_equal(old.loc[prefix], new.loc[prefix])

    factor58 = after.factor_instances["sector"]
    neutral = _node_matrix(factor58, "sector_neutral_vwap", len(changed))
    terminal = cutoff
    # asset-0 is a singleton in sector 12 on the effective date, so its
    # neutralized value is zero at that grid point.
    assert neutral[0][terminal] == pytest.approx(0.0, abs=1e-12)

    factor100 = after.factor_instances["neutral"]
    groups = _matrix(changed, "subindustry")
    sectors = _matrix(changed, "sector")
    assert groups[terminal] != sectors[terminal]
    neutral_nodes = (
        "first_subindustry_neutralize",
        "second_subindustry_neutralize",
        "third_subindustry_neutralize",
    )
    for node_name in neutral_nodes:
        values = _node_matrix(factor100, node_name, len(changed))
        for group in set(groups[terminal]):
            members = [
                values[asset][terminal]
                for asset, category in enumerate(groups[terminal])
                if category == group and math.isfinite(values[asset][terminal])
            ]
            if members:
                assert math.fsum(members) / len(members) == pytest.approx(0.0, abs=1e-10)

    first_node = factor100._nodes["first_subindustry_neutralize"]
    second_node = factor100._nodes["second_subindustry_neutralize"]
    third_node = factor100._nodes["third_subindustry_neutralize"]
    assert first_node is not second_node and second_node is not third_node
    ranked_inputs = tuple(
        factor100._nodes["rank_range_volume"].outputs[data].value for data in factor100.datas
    )
    assert all(actual is expected for actual, expected in zip(first_node._values, ranked_inputs))
    expected_groups = factor100.classification_lines("subindustry")
    assert all(actual is expected for actual, expected in zip(first_node._groups, expected_groups))
    expected_second_inputs = tuple(first_node.outputs[data].value for data in factor100.datas)
    assert all(
        actual is expected for actual, expected in zip(second_node._values, expected_second_inputs)
    )
    assert all(actual is expected for actual, expected in zip(second_node._groups, expected_groups))
    expected_third_inputs = tuple(
        factor100._nodes["correlation_minus_argmin_rank_%d" % index].lines.value
        for index in range(len(factor100.datas))
    )
    assert all(
        actual is expected for actual, expected in zip(third_node._values, expected_third_inputs)
    )
    assert all(actual is expected for actual, expected in zip(third_node._groups, expected_groups))

    wrong_hierarchy = _run_subset(
        baseline,
        {"wrong": Alpha100},
        classification_bindings={"wrong": {"subindustry": "table:pit_wrong_subindustry"}},
    )
    wrong_factor = wrong_hierarchy.factor_instances["wrong"]
    wrong_second = _node_matrix(wrong_factor, "second_subindustry_neutralize", len(baseline))
    correct_second = _node_matrix(factor100, "second_subindustry_neutralize", len(baseline))
    assert any(
        not math.isclose(correct_second[asset][100], wrong_second[asset][100])
        for asset in range(len(baseline))
        if math.isfinite(correct_second[asset][100]) and math.isfinite(wrong_second[asset][100])
    )
    wrong_groups = wrong_factor.classification_lines("subindustry")
    wrong_node = wrong_factor._nodes["second_subindustry_neutralize"]
    assert all(actual is expected for actual, expected in zip(wrong_node._groups, wrong_groups))

    unknown_frames = _frames(periods=40)
    unknown_time = unknown_frames["asset-0"].index[20]
    unknown_frames["asset-0"].loc[unknown_time, "sector"] = math.nan
    unknown_strategy = _run_subset(unknown_frames, {"unknown_sector": Alpha058})
    unknown_factor = unknown_strategy.factor_instances["unknown_sector"]
    unknown_data = unknown_factor.datas[0]
    unknown_line = unknown_factor.classification_lines("sector")[0]
    unknown_neutralized = unknown_factor._nodes["sector_neutral_vwap"].outputs[unknown_data].value
    assert math.isnan(unknown_line.array[20])
    assert math.isnan(unknown_neutralized.array[20])
    unknown_state = unknown_factor._factor_input_metadata[(id(unknown_data), "pit_sector", True)][
        unknown_time.to_pydatetime()
    ]
    assert unknown_state["reason"] == "UNKNOWN_CLASSIFICATION"

    gap_frames = _frames(periods=30)
    gap_name = "asset-0"
    gap_frames[gap_name].iloc[10, gap_frames[gap_name].columns.get_loc("close")] = math.nan
    gap_strategy = _run_subset(gap_frames, {"alpha9": Alpha009})
    gap_factor = gap_strategy.factor_instances["alpha9"]
    dataset = gap_strategy.get_dataset().raw_factors
    grid = tuple(next(iter(gap_frames.values())).index.to_pydatetime())
    for row in range(10, 16):
        assert math.isnan(dataset.at[(grid[row], gap_name), "alpha9"])
    assert math.isfinite(dataset.at[(grid[16], gap_name), "alpha9"])
    # The unknown comparison remains UNKNOWN through the conditional node;
    # it is not interpreted as false and the missing bar is not compressed.
    reason = gap_factor._nodes["condition_0"].lines.reason.array
    assert reason[10] == float(OperatorReason.UNKNOWN)


@pytest.mark.parametrize(
    "alpha_id,factor_class,missing_field,reason_node",
    (
        (62, "Alpha062", "vwap", "outer_comparison_0"),
        (92, "Alpha092", "open", "midpoint_less_low_open_0"),
    ),
)
def test_composed_comparison_paths_preserve_unknown_inputs(
    alpha_id, factor_class, missing_field, reason_node
):
    from tests.test_utils import alpha101_diagnostic_factors as representative
    from backtrader.research.operators import OperatorReason

    frames = _frames(periods=80)
    target = frames["asset-0"]
    target.iloc[-1, target.columns.get_loc(missing_field)] = math.nan
    expected, _ = _formula_reference(alpha_id, frames)
    assert math.isnan(expected[-1][0])

    strategy = _run_subset(frames, {"unknown": getattr(representative, factor_class)})
    dataset = strategy.get_dataset().raw_factors
    grid = tuple(next(iter(frames.values())).index.to_pydatetime())
    assert math.isnan(dataset.at[(grid[-1], "asset-0"), "unknown"])
    factor = strategy.factor_instances["unknown"]
    comparison = factor._nodes[reason_node].lines
    assert comparison.value.array[-1] != comparison.value.array[-1]
    assert comparison.reason.array[-1] == float(OperatorReason.UNKNOWN)

    if alpha_id == 62:
        # Unknown on the left operand survives the enclosing comparison and
        # its final multiplication instead of being ranked as false.
        result = factor._nodes["negative_boolean_0"].lines
        assert math.isnan(result.value.array[-1])
        assert result.reason.array[-1] == float(OperatorReason.UNKNOWN)
    else:
        # The unknown condition poisons the complete decay/TS-rank branch;
        # Minimum must not select the other branch as if it were a fallback.
        assert math.isnan(factor._nodes["bool_decay14_0"].lines.value.array[-1])
        assert math.isnan(factor._nodes["bool_ts_rank18_0"].lines.value.array[-1])


def test_factor_inventory_is_fixed_to_twenty_native_diagnostics():
    assert tuple(REPRESENTATIVE_FACTORS) == _ALPHA_IDS
    for alpha_id, factor_class in REPRESENTATIVE_FACTORS.items():
        assert issubclass(factor_class, FactorIndicator)
        assert factor_class.alpha_id == alpha_id
        assert factor_class.case_id == "AF45-%03d" % alpha_id
        assert factor_class.operator_profile == "alpha101-v1"
        assert factor_class.lookback_h == _HISTORY[alpha_id]
        assert factor_class.formula_fields == _FORMULA_FIELDS[alpha_id]
        assert factor_class.required_fields == factor_class.formula_fields
        assert factor_class.formula.startswith(("(", "min(")) or alpha_id == 84
