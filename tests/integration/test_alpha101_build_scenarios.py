"""Full-registry build profiles and representative binding/lifecycle scenarios."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

import backtrader as bt
from backtrader.research import align_to_grid
from backtrader.research.alpha101 import get_alpha
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.specs import FactorSpec
from tests.integration.test_alpha101_native_data_contracts import (
    _assert_panel_tensor_close,
    _mutate_future_tail,
    _panel_tensor,
)
from tests.test_utils.alpha101_full_reference import (
    formula_ids,
    history_h,
    reference,
)
from tests.test_utils.alpha101_native_harness import (
    actual_matrix,
    assert_finite_witness,
    assert_lifecycle,
    assert_matrix_matches,
    make_positive_fixture,
    make_research_spec,
    oracle_expected,
    oracle_frames,
    run_native_batch,
    selected_alpha_ids,
)
from tests.test_utils.alpha101_trace_validation import validate_factor_trace
from tests.test_utils.alpha101_trace_validation import compare_factor_graphs
from tests.unit.test_factor_research_representatives import _ALIGNMENT_MARKER

_HISTORY = 320
_ASSET_COUNT = 6
_BATCH_SIZE = 20
_CUT_ROW = 280
_RUN_MODES = (False, True)  # runnext, runonce


def _selected_batches():
    selected = set(selected_alpha_ids())
    selected_ids = tuple(alpha_id for alpha_id in formula_ids() if alpha_id in selected)
    return tuple(
        selected_ids[index : index + _BATCH_SIZE]
        for index in range(0, len(selected_ids), _BATCH_SIZE)
    )


def _assert_factor_panel_exact(left_strategy, right_strategy, alpha_id, *, label, assets=None):
    """Compare one complete factor panel exactly, retaining observed row order."""
    column = "alpha%d" % alpha_id
    left = left_strategy.get_panel().factors
    right = right_strategy.get_panel().factors
    assert column in left.columns and column in right.columns, "%s factor is missing" % label
    left = left.loc[:, [column]]
    right = right.loc[:, [column]]
    if assets is not None:
        asset_set = set(assets)
        left = left.loc[left.index.get_level_values("asset").isin(asset_set)]
        right = right.loc[right.index.get_level_values("asset").isin(asset_set)]
    pd.testing.assert_frame_equal(
        left,
        right,
        check_exact=True,
        check_like=False,
        obj=label,
    )


def _assert_native_build_exact(native, build, alpha_id, *, label):
    _assert_factor_panel_exact(native, build, alpha_id, label=label + " complete panel")
    report = compare_factor_graphs(
        native.factor_instances["alpha%d" % alpha_id],
        build.factor_instances["alpha%d" % alpha_id],
        alpha_id,
    )
    assert report["equal"], "%s graph comparison failed: %s" % (label, report["failures"][:12])


@pytest.mark.slow
@pytest.mark.parametrize(
    "batch_index",
    range(len(_selected_batches())),
    ids=lambda value: "batch-%d" % value,
)
@pytest.mark.parametrize("runonce", _RUN_MODES, ids=("runnext", "runonce"))
def test_all_alpha101_build_batches_are_full_time_order_invariant_and_causal(batch_index, runonce):
    """Build output preserves every time/asset cell under reorder and future edits."""
    batch = _selected_batches()[batch_index]
    frames = make_positive_fixture(_HISTORY)
    assert len(frames) == _ASSET_COUNT
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    assert len(grid) == _HISTORY

    build_classes = {alpha_id: get_alpha(alpha_id) for alpha_id in batch}
    baseline = run_native_batch(
        frames, batch, runonce=runonce, factor_mode="build", alpha_classes=build_classes
    )
    reordered_frames = dict(reversed(tuple(frames.items())))
    reordered = run_native_batch(
        reordered_frames,
        batch,
        runonce=runonce,
        factor_mode="build",
        alpha_classes=build_classes,
    )
    perturbed_frames = _mutate_future_tail(frames, grid)
    perturbed = run_native_batch(
        perturbed_frames,
        batch,
        runonce=runonce,
        factor_mode="build",
        alpha_classes=build_classes,
    )
    assert_lifecycle(baseline, batch, grid, alpha_classes=build_classes)

    baseline_values, factor_names = _panel_tensor(
        baseline.get_panel().factors, assets, grid, label="build baseline"
    )
    reordered_values, reordered_names = _panel_tensor(
        reordered.get_panel().factors, assets, grid, label="build reordered"
    )
    perturbed_values, perturbed_names = _panel_tensor(
        perturbed.get_panel().factors, assets, grid, label="build perturbed"
    )
    assert factor_names == reordered_names == perturbed_names
    _assert_panel_tensor_close(reordered_values, baseline_values, label="build full reorder")
    np.testing.assert_array_equal(
        perturbed_values[:_CUT_ROW],
        baseline_values[:_CUT_ROW],
        err_msg="build future prefix",
    )

    for alpha_id in batch:
        name = "alpha%d" % alpha_id
        factor = baseline.factor_instances[name]
        report = validate_factor_trace(factor, alpha_id, frames, assets, grid, strategy=baseline)
        assert not report["failures"], "Alpha%d build trace failed:\n%s" % (
            alpha_id,
            "\n".join(report["failures"][:20]),
        )
        assert_finite_witness(alpha_id, report["expected"], history_h(alpha_id))

    changed_input = perturbed_frames[assets[0]].loc[
        grid[_CUT_ROW:], ["open", "high", "low", "close", "vwap", "volume"]
    ]
    original_input = frames[assets[0]].loc[
        grid[_CUT_ROW:], ["open", "high", "low", "close", "vwap", "volume"]
    ]
    assert not changed_input.equals(original_input), "future input mutation was a no-op"
    for asset in assets:
        np.testing.assert_array_equal(
            perturbed_frames[asset]["dollar_volume"].to_numpy(dtype="float64"),
            (perturbed_frames[asset]["vwap"] * perturbed_frames[asset]["volume"]).to_numpy(
                dtype="float64"
            ),
        )


@pytest.mark.parametrize("runonce", _RUN_MODES, ids=("runnext", "runonce"))
def test_new_build_contexts_are_isolated_in_mixed_and_separate_runs(runonce):
    """New build factors coexist with a native factor and match isolated runs."""
    frames = make_positive_fixture(_HISTORY)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    alpha_ids = (1, 100, 3)
    classes = {
        1: get_alpha(1),
        100: get_alpha(100),
        3: get_alpha(3),
    }
    mixed_modes = {1: "build", 100: "build", 3: "native"}
    mixed = run_native_batch(
        frames, alpha_ids, runonce=runonce, factor_modes=mixed_modes, alpha_classes=classes
    )
    separate = {
        alpha_id: run_native_batch(
            frames,
            (alpha_id,),
            runonce=runonce,
            factor_mode=mixed_modes[alpha_id],
            alpha_classes={alpha_id: classes[alpha_id]},
        )
        for alpha_id in alpha_ids
    }

    for alpha_id in alpha_ids:
        factor = mixed.factor_instances["alpha%d" % alpha_id]
        report = validate_factor_trace(factor, alpha_id, frames, assets, grid, strategy=mixed)
        assert not report["failures"], "Alpha%d mixed trace failed:\n%s" % (
            alpha_id,
            "\n".join(report["failures"][:20]),
        )
        isolated = separate[alpha_id]
        isolated_factor = isolated.factor_instances["alpha%d" % alpha_id]
        isolated_report = validate_factor_trace(
            isolated_factor, alpha_id, frames, assets, grid, strategy=isolated
        )
        assert not isolated_report["failures"], "Alpha%d isolated trace failed:\n%s" % (
            alpha_id,
            "\n".join(isolated_report["failures"][:20]),
        )
        _assert_factor_panel_exact(
            mixed,
            isolated,
            alpha_id,
            label="Alpha%d mixed versus separate run" % alpha_id,
        )
        pair = compare_factor_graphs(factor, isolated_factor, alpha_id)
        assert pair["equal"], "Alpha%d mixed/separate graph differs: %s" % (
            alpha_id,
            pair["failures"][:12],
        )

    build_ids = (1, 100)
    build_instances = [mixed.factor_instances["alpha%d" % alpha_id] for alpha_id in build_ids]
    isolated_instances = [
        separate[alpha_id].factor_instances["alpha%d" % alpha_id] for alpha_id in build_ids
    ]
    for instances in (build_instances, isolated_instances):
        assert instances[0] is not instances[1]
        assert instances[0]._expression_context is not instances[1]._expression_context
        assert instances[0]._nodes is not instances[1]._nodes
    for alpha_id in build_ids:
        mixed_factor = mixed.factor_instances["alpha%d" % alpha_id]
        isolated_factor = separate[alpha_id].factor_instances["alpha%d" % alpha_id]
        assert mixed_factor._expression_context is not isolated_factor._expression_context
        assert mixed_factor._nodes is not isolated_factor._nodes


@pytest.mark.parametrize("runonce", _RUN_MODES, ids=("runnext", "runonce"))
def test_alpha003_build_respects_research_group_isolation(runonce):
    frames = make_positive_fixture(_HISTORY)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    groups = {
        asset: "left" if index < len(assets) // 2 else "right" for index, asset in enumerate(assets)
    }
    changed = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    positions = np.arange(_HISTORY, dtype="float64")
    for index, asset in enumerate(assets[3:]):
        frame = changed[asset]
        phase = index * 0.9
        frame["open"] = frame["open"] + (0.55 + index * 0.15) * np.sin(positions * 0.41 + phase)
        frame["volume"] = frame["volume"] * (1.0 + 0.45 * np.cos(positions * 0.27 + phase))

    build_classes = {3: get_alpha(3)}
    baseline = run_native_batch(
        frames,
        (3,),
        runonce=runonce,
        factor_mode="build",
        alpha_classes=build_classes,
        groups=groups,
    )
    mutated = run_native_batch(
        changed,
        (3,),
        runonce=runonce,
        factor_mode="build",
        alpha_classes=build_classes,
        groups=groups,
    )
    before = actual_matrix(baseline, 3, assets, grid)
    after = actual_matrix(mutated, 3, assets, grid)
    before = np.asarray(before, dtype="float64")
    after = np.asarray(after, dtype="float64")

    expected_before, _ = oracle_expected(3, frames, grid=grid, groups=groups)
    expected_after, _ = oracle_expected(3, changed, grid=grid, groups=groups)
    _assert_panel_tensor_close(
        before,
        np.asarray(expected_before, dtype="float64"),
        label="grouped Alpha3 baseline",
    )
    _assert_panel_tensor_close(
        after,
        np.asarray(expected_after, dtype="float64"),
        label="grouped Alpha3 mutation",
    )
    _assert_factor_panel_exact(
        baseline,
        mutated,
        3,
        label="left research group under right group mutation",
        assets=assets[:3],
    )
    shared_finite = np.isfinite(before[:, 3:]) & np.isfinite(after[:, 3:])
    assert np.any(
        before[:, 3:][shared_finite] != after[:, 3:][shared_finite]
    ), "the right-group input mutation did not change any witnessed Alpha3 output"


@pytest.mark.parametrize("runonce", _RUN_MODES, ids=("runnext", "runonce"))
def test_build_boundaries_cover_missing_nan_flat_zero_and_math_domain(runonce):
    frames = make_positive_fixture(_HISTORY)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    missing_point = grid[140]
    frames["asset-1"] = frames["asset-1"].drop(index=missing_point)
    frames["asset-2"].loc[grid[245], "close"] = math.nan
    frames["asset-3"].loc[grid[220], "volume"] = 0.0
    frames["asset-3"]["dollar_volume"] = frames["asset-3"]["vwap"] * frames["asset-3"]["volume"]
    flat_point = grid[300]
    frames["asset-4"].loc[flat_point, ["open", "high", "low", "close"]] = 2.75
    frames["asset-5"].loc[grid[270:], ["open", "close", "volume"]] = 1.0

    alpha_ids = (2, 54, 101)
    build_classes = {alpha_id: get_alpha(alpha_id) for alpha_id in alpha_ids}
    native = run_native_batch(frames, alpha_ids, runonce=runonce)
    strategy = run_native_batch(
        frames, alpha_ids, runonce=runonce, factor_mode="build", alpha_classes=build_classes
    )
    for alpha_id in alpha_ids:
        for label, run in (("native", native), ("build", strategy)):
            factor = run.factor_instances["alpha%d" % alpha_id]
            report = validate_factor_trace(factor, alpha_id, frames, assets, grid, strategy=run)
            assert not report["failures"], "Alpha%d %s edge trace failed:\n%s" % (
                alpha_id,
                label,
                "\n".join(report["failures"][:20]),
            )
            assert_finite_witness(alpha_id, report["expected"], history_h(alpha_id))
        _assert_native_build_exact(native, strategy, alpha_id, label="Alpha%d edge" % alpha_id)

    output = strategy.get_panel().factors
    assert math.isnan(output.at[(missing_point, "asset-1"), "alpha101"])
    assert math.isnan(output.at[(grid[245].to_pydatetime(), "asset-2"), "alpha101"])
    assert math.isnan(output.at[(grid[220].to_pydatetime(), "asset-3"), "alpha2"])
    assert math.isnan(output.at[(flat_point.to_pydatetime(), "asset-4"), "alpha54"])
    assert output.at[(flat_point.to_pydatetime(), "asset-4"), "alpha101"] == 0.0


@pytest.mark.parametrize("runonce", _RUN_MODES, ids=("runnext", "runonce"))
def test_alpha063_build_tracks_changing_and_unknown_industry_groups(runonce):
    frames = make_positive_fixture(_HISTORY)
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    frames["asset-0"].loc[grid[250:], "industry"] = 99.0
    frames["asset-1"].loc[grid[270:], "industry"] = math.nan

    build_classes = {63: get_alpha(63)}
    native = run_native_batch(frames, (63,), runonce=runonce)
    strategy = run_native_batch(
        frames, (63,), runonce=runonce, factor_mode="build", alpha_classes=build_classes
    )
    for label, run in (("native", native), ("build", strategy)):
        report = validate_factor_trace(
            run.factor_instances["alpha63"], 63, frames, assets, grid, strategy=run
        )
        assert not report["failures"], "Alpha63 %s classification trace failed:\n%s" % (
            label,
            "\n".join(report["failures"][:20]),
        )
        assert_finite_witness(63, report["expected"], history_h(63))
    _assert_native_build_exact(native, strategy, 63, label="Alpha63 classification")
    assert frames["asset-0"].loc[grid[-1], "industry"] == 99.0
    assert math.isnan(frames["asset-1"].loc[grid[-1], "industry"])


class _ExplicitAdvFeed(bt.feeds.PandasData):
    lines = ("vwap", "dollar_volume", "cap", "sector", "industry", "subindustry", "adv20")
    params = tuple((name, name) for name in lines)


def _run_alpha007_with_explicit_adv(frames, *, factor_mode, runonce):
    research = make_research_spec(frames)
    cerebro = bt.Cerebro(stdstats=False, runonce=bool(runonce))
    for asset, frame in frames.items():
        aligned = align_to_grid(frame, research, asset)
        feed = _ExplicitAdvFeed(dataname=aligned.feed.p.dataname)
        setattr(feed, _ALIGNMENT_MARKER, getattr(aligned.feed, _ALIGNMENT_MARKER))
        cerebro.adddata(feed, name=asset)

    indicator = get_alpha(7)
    bindings = {alias: "feed:target:%s" % alias for alias in indicator.formula_fields}
    factor = FactorSpec(
        name="alpha7",
        indicator=indicator,
        panel_line="factor",
        field_bindings=bindings,
        mode=factor_mode,
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"alpha7": factor})
    return cerebro.run()[0]


@pytest.mark.parametrize("runonce", _RUN_MODES, ids=("runnext", "runonce"))
def test_alpha007_build_honors_explicit_adv_and_derived_adv_paths(runonce):
    derived_frames = make_positive_fixture(_HISTORY)
    explicit_frames = {asset: frame.copy(deep=True) for asset, frame in derived_frames.items()}
    for frame in explicit_frames.values():
        # This input deliberately disagrees with source-derived ADV so the
        # independent output proves the explicitly bound line was consumed.
        frame["adv20"] = 1.0

    grid = tuple(next(iter(derived_frames.values())).index)
    assets = tuple(derived_frames)
    derived_native = run_native_batch(derived_frames, (7,), runonce=runonce)
    derived_build = run_native_batch(
        derived_frames,
        (7,),
        runonce=runonce,
        factor_mode="build",
        alpha_classes={7: get_alpha(7)},
    )
    explicit_native = _run_alpha007_with_explicit_adv(
        explicit_frames, factor_mode="native", runonce=runonce
    )
    explicit_build = _run_alpha007_with_explicit_adv(
        explicit_frames, factor_mode="build", runonce=runonce
    )
    _assert_native_build_exact(derived_native, derived_build, 7, label="Alpha7 derived ADV")
    _assert_native_build_exact(explicit_native, explicit_build, 7, label="Alpha7 explicit ADV")

    expected_derived, _ = oracle_expected(7, derived_frames, grid=grid)
    for label, run in (("native", derived_native), ("build", derived_build)):
        assert_matrix_matches(
            actual_matrix(run, 7, assets, grid),
            expected_derived,
            label="Alpha7 %s source-derived ADV" % label,
        )
    matrices = oracle_frames(explicit_frames, grid=grid)
    matrices["adv20"] = [
        [float(explicit_frames[asset].reindex(grid)["adv20"].iloc[row]) for asset in assets]
        for row in range(len(grid))
    ]
    expected_explicit = reference(
        7,
        matrices,
        formula_universe=[[True] * len(assets) for _ in grid],
        groups=tuple("market" for _ in assets),
    )
    for label, run in (("native", explicit_native), ("build", explicit_build)):
        assert_matrix_matches(
            actual_matrix(run, 7, assets, grid),
            expected_explicit,
            label="Alpha7 %s explicit ADV" % label,
        )
    assert_finite_witness(7, expected_explicit, history_h(7))

    derived_values = np.asarray(actual_matrix(derived_build, 7, assets, grid), dtype="float64")
    explicit_values = np.asarray(actual_matrix(explicit_build, 7, assets, grid), dtype="float64")
    derived_finite = np.isfinite(derived_values)
    explicit_finite = np.isfinite(explicit_values)
    # Source-derived ADV has a warmup; while it is unknown the formula output
    # is unknown. Once that field exists, the false branch can be finite before
    # the long true branch. The explicit low ADV selects that long branch and
    # therefore exposes its own longer warmup.
    assert np.any(derived_finite & ~explicit_finite)
    assert np.all(~explicit_finite | derived_finite)
    common_finite = derived_finite & explicit_finite
    assert np.any(
        derived_values[common_finite] != explicit_values[common_finite]
    ), "explicit ADV was ignored in favor of source-derived ADV"
