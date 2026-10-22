"""L0 production-entry checks for promoted native Alpha003 and Alpha009."""

from decimal import Decimal, localcontext
from fractions import Fraction
import math

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research.alpha101 import (
    ALPHA_REGISTRY,
    Alpha003Native,
    Alpha009Native,
    get_alpha,
    list_alphas,
)
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.inputs import prealign_bars
from backtrader.research.specs import FactorSpec, ResearchSpec

_EXPECTED_DECLARATIONS = {
    3: {
        "case_id": "AF46-003",
        "formula": "(-1 * correlation(rank(open), rank(volume), 10))",
        "lookback_h": 9,
        "formula_fields": ("open", "volume"),
        "classification_levels": (),
        "classification_fields": (),
    },
    9: {
        "case_id": "AF46-009",
        "formula": (
            "((0 < ts_min(delta(close, 1), 5)) ? delta(close, 1) : "
            "((ts_max(delta(close, 1), 5) < 0) ? delta(close, 1) : "
            "(-1 * delta(close, 1))))"
        ),
        "lookback_h": 5,
        "formula_fields": ("close",),
        "classification_levels": (),
        "classification_fields": (),
    },
}

_OPEN_RANKS = (
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
_VOLUME_RANKS = (
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
_ASSETS = ("A", "B", "C")


def _frames():
    index = pd.date_range("2026-01-01", periods=len(_OPEN_RANKS), freq="D", tz="UTC")
    close_paths = {
        "A": [10.0 + row for row in range(len(index))],
        "B": [30.0 - row for row in range(len(index))],
        "C": [40.0, 41.0, 42.0, 41.0, 40.0, 42.0, 43.0, 42.0, 44.0, 43.0],
    }
    frames = {}
    for column, asset in enumerate(_ASSETS):
        close = close_paths[asset]
        frames[asset] = pd.DataFrame(
            {
                "open": [row[column] for row in _OPEN_RANKS],
                "high": [value + 1.0 for value in close],
                "low": [value - 1.0 for value in close],
                "close": close,
                "volume": [100.0 * row[column] for row in _VOLUME_RANKS],
                "openinterest": [0.0] * len(index),
            },
            index=index,
        )
    return frames


def _average_rank(values):
    """Independent normalized average ranks over finite scalar inputs."""
    result = []
    count = len(values)
    for value in values:
        below = sum(other < value for other in values)
        tied = sum(other == value for other in values)
        result.append((below + (tied + 1) / 2.0) / count)
    return result


def _pearson(left, right):
    """Independent exact-binary64 Pearson reference, rounded once to float."""
    left_exact = [Fraction.from_float(float(value)) for value in left]
    right_exact = [Fraction.from_float(float(value)) for value in right]
    count = len(left_exact)
    left_mean = sum(left_exact, Fraction()) / count
    right_mean = sum(right_exact, Fraction()) / count
    left_centered = [value - left_mean for value in left_exact]
    right_centered = [value - right_mean for value in right_exact]
    covariance = sum((x * y for x, y in zip(left_centered, right_centered)), Fraction())
    left_ss = sum((x * x for x in left_centered), Fraction())
    right_ss = sum((y * y for y in right_centered), Fraction())
    if left_ss <= 0 or right_ss <= 0:
        return math.nan
    with localcontext() as context:
        context.prec = 100
        numerator = Decimal(covariance.numerator) / Decimal(covariance.denominator)
        product = left_ss * right_ss
        denominator = (Decimal(product.numerator) / Decimal(product.denominator)).sqrt()
        return float(numerator / denominator)


def _alpha003_reference(frames):
    names = tuple(frames)
    length = len(next(iter(frames.values())))
    open_ranks = [
        _average_rank([float(frames[name]["open"].iloc[row]) for name in names])
        for row in range(length)
    ]
    volume_ranks = [
        _average_rank([float(frames[name]["volume"].iloc[row]) for name in names])
        for row in range(length)
    ]
    result = {name: [math.nan] * length for name in names}
    for row in range(9, length):
        for column, name in enumerate(names):
            start = row - 9
            result[name][row] = -_pearson(
                [values[column] for values in open_ranks[start : row + 1]],
                [values[column] for values in volume_ranks[start : row + 1]],
            )
    return result


def _alpha009_reference(frames):
    result = {}
    for name, frame in frames.items():
        closes = [float(value) for value in frame["close"]]
        changes = [math.nan] + [right - left for left, right in zip(closes, closes[1:])]
        values = [math.nan] * len(changes)
        for row in range(5, len(changes)):
            window = changes[row - 4 : row + 1]
            change = changes[row]
            if min(window) > 0.0 or max(window) < 0.0:
                values[row] = change
            else:
                values[row] = -change
        result[name] = values
    return result


def _research_spec(frames):
    index = next(iter(frames.values())).index.rename("close_time")
    grid = pd.DataFrame(
        {"open_time": index - pd.Timedelta(hours=6)},
        index=index,
    )
    return ResearchSpec(
        grid=grid,
        start=index[0],
        end=index[-1],
        targets=tuple(frames),
        source_timezone="UTC",
        snapshot_id="iteration46-l0-synthetic-v1",
        price_basis="synthetic positive unadjusted OHLC values",
        calendar_id="iteration46-l0-daily-v1",
        frequency="1session",
        groups=dict.fromkeys(frames, "market"),
    )


def _factor_spec(name, factor_class):
    return FactorSpec(
        name=name,
        indicator=factor_class,
        panel_line="factor",
        field_bindings={field: "feed:target:%s" % field for field in factor_class.formula_fields},
    )


def _run(frames, *, runonce):
    research = _research_spec(frames)
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)

    def reject_order(*args, **kwargs):
        raise AssertionError("factor research must not submit or cancel broker orders")

    cerebro.broker.submit = reject_order
    cerebro.broker.cancel = reject_order
    for asset, frame in frames.items():
        cerebro.adddata(prealign_bars(frame, research, asset).feed, name=asset)
    cerebro.addstrategy(
        FactorStrategy,
        research=research,
        factors={
            "alpha3": _factor_spec("alpha3", get_alpha(3)),
            "alpha9": _factor_spec("alpha9", get_alpha(9)),
        },
    )
    return cerebro.run()[0]


def test_native_registry_is_read_only_and_matches_independent_declarations():
    assert list_alphas() == tuple(sorted(ALPHA_REGISTRY))
    assert {3, 9}.issubset(ALPHA_REGISTRY)
    assert ALPHA_REGISTRY[3] is Alpha003Native
    assert ALPHA_REGISTRY[9] is Alpha009Native
    with pytest.raises(TypeError):
        ALPHA_REGISTRY[4] = Alpha003Native
    with pytest.raises(TypeError):
        get_alpha(True)
    with pytest.raises(TypeError):
        get_alpha(3.0)
    with pytest.raises(KeyError):
        get_alpha(102)

    for alpha_id, factor_class in ((3, Alpha003Native), (9, Alpha009Native)):
        expected = _EXPECTED_DECLARATIONS[alpha_id]
        assert issubclass(factor_class, FactorIndicator)
        assert factor_class.__bases__ == (FactorIndicator,)
        assert factor_class.alpha_id == alpha_id
        assert factor_class.case_id == expected["case_id"]
        assert "__init__" in factor_class.__dict__
        assert "next" in factor_class.__dict__
        assert factor_class.formula == expected["formula"]
        assert factor_class.lookback_h == expected["lookback_h"]
        assert factor_class.operator_profile == "alpha101-v1"
        assert factor_class.formula_fields == expected["formula_fields"]
        assert factor_class.required_fields == expected["formula_fields"]
        assert factor_class.classification_levels == expected["classification_levels"]
        assert factor_class.classification_fields == expected["classification_fields"]


@pytest.mark.parametrize("runonce", (False, True))
def test_l0_factors_share_factor_strategy_and_match_independent_references(runonce):
    frames = _frames()
    strategy = _run(frames, runonce=runonce)
    dataset = strategy.get_dataset()
    raw = dataset.raw_factors
    grid = tuple(next(iter(frames.values())).index.to_pydatetime())
    references = {
        "alpha3": _alpha003_reference(frames),
        "alpha9": _alpha009_reference(frames),
    }

    assert set(strategy.factor_instances) == {"alpha3", "alpha9"}
    for factor_name, formula_id, declared_h in (("alpha3", 3, 9), ("alpha9", 9, 5)):
        factor = strategy.factor_instances[factor_name]
        spec = strategy._factor_specs_by_name[factor_name]
        assert spec.indicator is get_alpha(formula_id)
        assert spec.lookback_h == declared_h
        assert len(factor._factor_call_times) == len(grid)
        for asset in _ASSETS:
            expected = references[factor_name][asset]
            actual = [float(raw.at[(point, asset), factor_name]) for point in grid]
            for row, (got, wanted) in enumerate(zip(actual, expected)):
                if math.isnan(wanted):
                    assert math.isnan(got), "%s row %d should remain in warmup" % (
                        factor_name,
                        row,
                    )
                else:
                    assert math.isfinite(got)
                    assert got == pytest.approx(wanted, rel=1e-12, abs=1e-12)
            assert any(math.isfinite(value) for value in actual)

    # Alpha009's last five changes exercise its positive, negative, and mixed
    # branches. Alpha003's leading minus sign must not be dropped.
    assert raw.at[(grid[5], "A"), "alpha9"] == pytest.approx(1.0)
    assert raw.at[(grid[5], "B"), "alpha9"] == pytest.approx(-1.0)
    assert raw.at[(grid[5], "C"), "alpha9"] == pytest.approx(-2.0)
    alpha003_expected = _alpha003_reference(frames)
    assert any(
        math.isfinite(alpha003_expected[name][-1])
        and abs(float(raw.at[(grid[-1], name), "alpha3"]) + alpha003_expected[name][-1]) > 1e-9
        for name in _ASSETS
    )
