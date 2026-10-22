"""Ordinary-feed presence and cross-sectional contracts for native formulas."""

from __future__ import annotations

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research import FactorSpec, FactorStrategy, ResearchSpec, align_to_grid
from backtrader.research.alpha101 import get_alpha
from backtrader.research.operators import OperatorReason


class _ResearchFeed(bt.feeds.PandasData):
    lines = ("vwap", "dollar_volume", "industry", "subindustry")
    params = tuple((name, name) for name in lines)


def _research(frames, *, start=None, end=None, universe=None, groups=None):
    index = next(iter(frames.values())).index
    grid = pd.DataFrame(
        {"open_time": index - pd.Timedelta(hours=1)}, index=index.rename("close_time")
    )
    targets = tuple(frames)
    return ResearchSpec(
        grid=grid,
        start=start or index[0],
        end=end or index[-1],
        targets=targets,
        source_timezone="UTC",
        snapshot_id="alpha101-ordinary-feed-contract",
        price_basis="synthetic values",
        calendar_id="synthetic-daily-grid",
        frequency="1session",
        groups=groups or dict.fromkeys(targets, "market"),
        universe=universe,
    )


def _factor_spec(name, indicator):
    bindings = {}
    for alias in indicator.formula_fields:
        if alias.startswith("adv") and alias[3:].isdigit():
            bindings[alias] = {
                "derive": "adv",
                "source": "dollar_volume",
                "window": int(alias[3:]),
            }
        else:
            bindings[alias] = "feed:target:%s" % alias
    return FactorSpec(name=name, indicator=indicator, panel_line="factor", field_bindings=bindings)


def _run(frames, alpha_ids, *, research=None, runonce=True):
    research = research or _research(frames)
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    for asset, frame in frames.items():
        aligned = align_to_grid(frame, research, asset)
        feed = _ResearchFeed(dataname=aligned.feed.p.dataname)
        setattr(
            feed,
            "_factor_research_alignment_v2",
            getattr(aligned.feed, "_factor_research_alignment_v2"),
        )
        cerebro.adddata(feed, name=asset)
    factors = {
        "alpha%d" % alpha_id: _factor_spec("alpha%d" % alpha_id, get_alpha(alpha_id))
        for alpha_id in alpha_ids
    }
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    return cerebro.run()[0]


def _frames(index, close_series):
    frames = {}
    for number, (asset, closes) in enumerate(close_series.items()):
        close = pd.Series(closes, index=index, dtype="float64")
        frames[asset] = pd.DataFrame(
            {
                "open": close - 0.1,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000.0 + number,
                "openinterest": 0.0,
                "vwap": close + 0.2,
                "dollar_volume": (close + 0.2) * (1000.0 + number),
                "industry": float(number // 2),
                "subindustry": float(number // 2),
            },
            index=index,
        )
    return frames


@pytest.mark.parametrize("runonce", (False, True))
def test_alpha009_positive_negative_constant_and_missing_bar_branches(runonce):
    grid = pd.date_range("2025-01-01", periods=24, freq="D", tz="UTC")
    close_series = {
        "up": [10.0 + row for row in range(len(grid))],
        "down": [50.0 - row for row in range(len(grid))],
        "constant": [20.0] * len(grid),
        "halted": [70.0 + row for row in range(len(grid))],
    }
    frames = _frames(grid, close_series)
    frames["halted"] = frames["halted"].drop(index=grid[12])

    strategy = _run(frames, (9,), runonce=runonce)
    panel = strategy.get_panel()
    values = panel.factors["alpha9"]

    assert values.at[(grid[8], "up")] == pytest.approx(1.0)
    assert values.at[(grid[8], "down")] == pytest.approx(-1.0)
    assert values.at[(grid[8], "constant")] == pytest.approx(0.0)
    assert all(math.isnan(values.at[(grid[row], "halted")]) for row in range(12, 18))
    assert math.isfinite(values.at[(grid[18], "halted")])
    assert strategy.factor_instances["alpha9"].lifecycle_diagnostics["grid_matches"]


@pytest.mark.parametrize("runonce", (False, True))
def test_alpha029_rank_uses_real_bar_presence_and_hand_calculated_ranks(runonce):
    grid = pd.date_range("2025-02-01", periods=20, freq="D", tz="UTC")
    close_series = {
        "a": [10.0 + 0.1 * row for row in range(len(grid))],
        "b": [20.0 + 0.2 * row for row in range(len(grid))],
        "c": [30.0 + 0.3 * row for row in range(len(grid))],
        "missing": [40.0 + 0.4 * row for row in range(len(grid))],
    }
    frames = _frames(grid, close_series)
    frames["missing"] = frames["missing"].drop(index=grid[12])

    strategy = _run(frames, (29,), runonce=runonce)
    factor = strategy.factor_instances["alpha29"]
    rank = factor._nodes["rank_delta"]
    by_asset = dict(zip(strategy._research.targets, strategy._target_datas))

    assert rank.outputs[by_asset["a"]].value.array[12] == pytest.approx(1.0 / 3.0)
    assert rank.outputs[by_asset["b"]].value.array[12] == pytest.approx(2.0 / 3.0)
    assert rank.outputs[by_asset["c"]].value.array[12] == pytest.approx(1.0)
    assert math.isnan(rank.outputs[by_asset["missing"]].value.array[12])
    assert rank.outputs[by_asset["missing"]].reason.array[12] == float(
        OperatorReason.FORMULA_INELIGIBLE
    )
    membership = factor.formula_members[-1]
    assert membership.array[12] == 0.0
    assert math.isnan(strategy.get_panel().factors.at[(grid[12], "missing"), "alpha29"])


def test_research_universe_is_evaluation_only_and_tail_changes_do_not_rewrite_alpha009():
    grid = pd.date_range("2025-03-01", periods=24, freq="D", tz="UTC")
    close_series = {
        "a": [10.0 + row + 0.1 * (row % 3) for row in range(len(grid))],
        "b": [30.0 + 0.5 * row + 0.2 * (row % 4) for row in range(len(grid))],
        "c": [50.0 + 0.2 * row + 0.3 * (row % 5) for row in range(len(grid))],
    }
    frames = _frames(grid, close_series)
    start, end = grid[5], grid[19]
    study_index = grid[(grid >= start) & (grid <= end)]
    keys = pd.MultiIndex.from_product([study_index, tuple(frames)], names=("time", "asset"))
    universe = pd.Series(True, index=keys, dtype=bool)
    universe.loc[(grid[12], "b")] = False
    research = _research(frames, start=start, end=end)
    masked_research = _research(frames, start=start, end=end, universe=universe)

    baseline = _run(frames, (9,), research=research)
    masked = _run(frames, (9,), research=masked_research)
    reordered_frames = dict(reversed(tuple(frames.items())))
    reordered = _run(
        reordered_frames, (9,), research=_research(reordered_frames, start=start, end=end)
    )

    pd.testing.assert_frame_equal(baseline.get_panel().factors, masked.get_panel().factors)
    assert baseline.get_panel().universe.at[grid[12], "b"]
    assert not masked.get_panel().universe.at[grid[12], "b"]
    pd.testing.assert_series_equal(
        baseline.get_panel().factors["alpha9"].sort_index(),
        reordered.get_panel().factors["alpha9"].sort_index(),
    )

    perturbed = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    for frame in perturbed.values():
        frame.loc[grid[20] :, "close"] += 500.0
        frame.loc[grid[20] :, "open"] += 500.0
        frame.loc[grid[20] :, "high"] += 500.0
        frame.loc[grid[20] :, "low"] += 500.0
    future_changed = _run(perturbed, (9,), research=research)
    pd.testing.assert_frame_equal(baseline.get_panel().factors, future_changed.get_panel().factors)
    assert future_changed.factor_instances["alpha9"].lifecycle_diagnostics["grid_matches"]
    assert (
        future_changed.get_panel().prices_close.at[grid[-1], "a"]
        != baseline.get_panel().prices_close.at[grid[-1], "a"]
    )


def _alpha100_frames(periods=36):
    index = pd.date_range("2025-04-01", periods=periods, freq="D", tz="UTC")
    categories = (0, 0, 1, 1, 2, 2)
    frames = {}
    for asset_index in range(6):
        rows = []
        for row in range(periods):
            close = (
                100.0
                + asset_index * 0.25
                + row * 0.03
                + (0.8 + asset_index * 0.03) * math.sin(row * 0.33 + asset_index)
            )
            open_ = close + 0.12 * math.cos(row * 0.47 + asset_index)
            high = max(open_, close) + 0.9 + 0.04 * math.sin(row * 0.21 + asset_index)
            low = min(open_, close) - 0.8 - 0.05 * math.cos(row * 0.19 + asset_index)
            volume = (
                1500.0
                + 230.0 * math.sin(row * (0.21 + 0.01 * asset_index) + asset_index)
                + 17.0 * asset_index
            )
            vwap = (open_ + close) / 2.0 + 0.03 * asset_index
            rows.append((open_, high, low, close, volume, vwap))
        frame = pd.DataFrame(
            rows,
            columns=("open", "high", "low", "close", "volume", "vwap"),
            index=index,
        )
        frame["openinterest"] = 0.0
        frame["dollar_volume"] = frame["vwap"] * frame["volume"]
        frame["industry"] = [float(categories[asset_index])] * periods
        frame["subindustry"] = [float(categories[asset_index])] * periods
        frames["asset-%d" % asset_index] = frame
    return frames


def test_alpha100_industry_groups_scale_missing_code_reorder_and_future_tail():
    frames = _alpha100_frames()
    grid = next(iter(frames.values())).index
    start, end = grid[29], grid[32]
    research = _research(frames, start=start, end=end)
    baseline = _run(frames, (100,), research=research)
    factor = baseline.factor_instances["alpha100"]
    target_data = dict(zip(research.targets, baseline._target_datas))
    last_row = 32

    neutral = factor._nodes["first_subindustry_neutralize"]
    neutral_values = {
        asset: float(neutral.outputs[data].value.array[last_row])
        for asset, data in target_data.items()
    }
    category = {"asset-%d" % index: index // 2 for index in range(6)}
    for group in set(category.values()):
        values = [value for asset, value in neutral_values.items() if category[asset] == group]
        assert all(math.isfinite(value) for value in values)
        assert math.fsum(values) / len(values) == pytest.approx(0.0, abs=1e-12)

    scaled = factor._nodes["first_scale"]
    scale_values = [
        float(scaled.outputs[data].value.array[last_row]) for data in target_data.values()
    ]
    assert all(math.isfinite(value) for value in scale_values)
    assert math.fsum(abs(value) for value in scale_values) == pytest.approx(1.0, abs=1e-12)

    regrouped_frames = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    regrouped_frames["asset-1"]["subindustry"] = 1.0
    regrouped = _run(
        regrouped_frames,
        (100,),
        research=_research(regrouped_frames, start=start, end=end),
    )
    regrouped_node = regrouped.factor_instances["alpha100"]._nodes["first_subindustry_neutralize"]
    regrouped_data = dict(zip(regrouped._research.targets, regrouped._target_datas))
    assert any(
        not math.isclose(
            neutral_values[asset],
            float(regrouped_node.outputs[regrouped_data[asset]].value.array[last_row]),
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        for asset in target_data
    )

    missing_frames = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    missing_frames["asset-0"].loc[grid[last_row], "subindustry"] = math.nan
    missing = _run(
        missing_frames,
        (100,),
        research=_research(missing_frames, start=start, end=end),
    )
    missing_factor = missing.factor_instances["alpha100"]
    missing_node = missing_factor._nodes["first_subindustry_neutralize"]
    missing_data = dict(zip(missing._research.targets, missing._target_datas))
    assert math.isnan(missing.get_panel().factors.at[(grid[last_row], "asset-0"), "alpha100"])
    assert math.isnan(missing_node.outputs[missing_data["asset-0"]].value.array[last_row])
    assert missing_node.outputs[missing_data["asset-0"]].reason.array[last_row] == float(
        OperatorReason.UNKNOWN_CLASSIFICATION
    )
    assert math.isfinite(missing_node.outputs[missing_data["asset-1"]].value.array[last_row])

    reordered_frames = dict(reversed(tuple(frames.items())))
    reordered = _run(
        reordered_frames,
        (100,),
        research=_research(reordered_frames, start=start, end=end),
    )
    pd.testing.assert_series_equal(
        baseline.get_panel().factors["alpha100"].sort_index(),
        reordered.get_panel().factors["alpha100"].sort_index(),
    )

    tail_changed_frames = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    for frame in tail_changed_frames.values():
        frame.loc[grid[33] :, ["open", "high", "low", "close", "vwap"]] += 900.0
        frame.loc[grid[33] :, "dollar_volume"] = (
            frame.loc[grid[33] :, "vwap"] * frame.loc[grid[33] :, "volume"]
        )
    tail_changed = _run(
        tail_changed_frames,
        (100,),
        research=_research(tail_changed_frames, start=start, end=end),
    )
    pd.testing.assert_frame_equal(baseline.get_panel().factors, tail_changed.get_panel().factors)
    assert (
        tail_changed.get_panel().prices_close.at[grid[-1], "asset-0"]
        != baseline.get_panel().prices_close.at[grid[-1], "asset-0"]
    )
