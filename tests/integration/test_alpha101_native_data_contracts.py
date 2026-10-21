"""Small Alpha101 contract scenarios for real feed-grid and PIT inputs.

These cases complement the full native matrix with two focused data contracts:
independently trading markets aligned to one research grid, and a subindustry
classification that is initially unavailable, briefly unknown, and revised
only in the future.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backtrader.research.inputs import prealign_bars, prealign_pit_table
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.alpha101 import get_alpha
from tests.test_utils.alpha101_full_reference import history_h, reference
from tests.test_utils.alpha101_native_harness import (
    actual_matrix,
    assert_availability_matches_values,
    assert_finite_witness,
    assert_matrix_matches,
    formula_universe_matrix,
    make_research_spec,
    oracle_frames,
    run_native_batch,
)
from tests.unit.test_factor_research_representatives import _frames


_RUN_MODES = (False, True)  # runnext, runonce
_SUSPENSION_ROWS = (20, 21, 22, 23)
_PIT_PUBLICATION_ROW = 4
_PIT_UNKNOWN_ROW = 30
_PIT_RESTORATION_ROW = 31
_PIT_REVISION_ROW = 80


def _full_grid_frames(periods: int = 48):
    """Reuse the Iteration 45 deterministic bars on a synthetic business grid."""
    frames = _frames(periods=periods)
    grid = pd.bdate_range("2025-01-06", periods=periods, freq="B", tz="UTC", name="close_time")
    for frame in frames.values():
        frame.index = grid
    assets = tuple(frames)
    groups = {
        asset: ("market-east" if index < 3 else "market-west") for index, asset in enumerate(assets)
    }
    members = formula_universe_matrix(grid, assets)
    research = make_research_spec(frames, formula_universe=members, groups=groups)
    return frames, grid, assets, groups, members, research


def _oracle_output(alpha_id, matrices, members, groups, assets):
    oracle_groups = tuple(groups[asset] for asset in assets)
    expected = reference(
        alpha_id,
        matrices,
        formula_universe=members,
        groups=oracle_groups,
    )
    declared_h = history_h(alpha_id, matrices)
    for row in range(min(declared_h, len(expected))):
        expected[row] = [math.nan] * len(expected[row])
    return expected, declared_h


def _assert_factor_lifecycle(strategy, alpha_ids, grid):
    """Check every group-local factor and operator ran once per common grid."""
    expected_names = {"alpha%d" % alpha_id for alpha_id in alpha_ids}
    expected_times = tuple(point.to_pydatetime() for point in grid)
    assert set(strategy.factor_instances) == expected_names
    assert strategy._alpha101_broker_call_counts == {"submit": 0, "cancel": 0}
    assert not strategy.broker.orders
    assert not strategy.broker.pending
    assert not strategy.broker.submitted

    for alpha_id in alpha_ids:
        factor_group = strategy.factor_instances["alpha%d" % alpha_id]
        grouped = getattr(factor_group, "group_instances", None)
        instances = tuple(grouped.values()) if grouped is not None else (factor_group,)
        assert instances
        for factor in instances:
            assert factor._minperiod == get_alpha(alpha_id).lookback_h + 1
            for nested in FactorStrategy._factor_tree(factor):
                diagnostics = nested.lifecycle_diagnostics
                assert diagnostics["call_count"] == len(grid)
                assert diagnostics["grid_count"] == len(grid)
                assert diagnostics["grid_matches"]
                assert tuple(diagnostics["call_times"]) == expected_times


def _different_market_calendars(full_frames):
    """Drop market holidays, staggered starts, and one continuous suspension."""
    closed_rows = {
        "market-east": {5, 13, 29},
        "market-west": {2, 10, 27, 41},
    }
    asset_gaps = {
        "asset-0": set(_SUSPENSION_ROWS),
        "asset-1": {0, 8},
        "asset-4": {1, 18},
        "asset-5": {0, 6},
    }
    sparse = {}
    for index, (asset, frame) in enumerate(full_frames.items()):
        market = "market-east" if index < 3 else "market-west"
        missing = closed_rows[market] | asset_gaps.get(asset, set())
        keep = [row for row in range(len(frame)) if row not in missing]
        sparse[asset] = frame.iloc[keep].copy(deep=True)
    return sparse


@pytest.mark.parametrize("runonce", _RUN_MODES, ids=("runnext", "runonce"))
def test_alpha3_alpha9_align_distinct_market_calendars_without_forward_fill(runonce):
    full_frames, grid, assets, groups, members, research = _full_grid_frames()
    frames = _different_market_calendars(full_frames)
    assert set(frames["asset-0"].index) != set(frames["asset-3"].index)
    assert frames["asset-1"].index[0] > grid[0]
    assert frames["asset-5"].index[0] > grid[0]

    # The two market calendars, an individual staggered start, and a continuous
    # suspension all remain explicit holes on the common research grid.
    for asset, frame in frames.items():
        aligned = prealign_bars(frame, research, asset)
        assert aligned.frame.index.equals(grid)
        expected_missing = set(range(len(grid))) - {
            row for row, point in enumerate(grid) if point in frame.index
        }
        for row in expected_missing:
            assert not bool(aligned.present.iloc[row])
            assert pd.isna(aligned.frame.iloc[row]["close"])
        assert bool(aligned.present.iloc[24]) is (grid[24] in frame.index)

    matrices = oracle_frames(frames, grid=grid)
    asset0 = assets.index("asset-0")
    for row in _SUSPENSION_ROWS:
        assert math.isnan(matrices["close"][row][asset0])
    assert math.isfinite(float(frames["asset-0"].loc[grid[24], "close"]))

    strategy = run_native_batch(
        frames,
        (3, 9),
        runonce=runonce,
        research=research,
        formula_universe=members,
        groups=groups,
    )
    _assert_factor_lifecycle(strategy, (3, 9), grid)
    assert_availability_matches_values(strategy, (3, 9), grid, assets)

    for alpha_id in (3, 9):
        expected, declared_h = _oracle_output(alpha_id, matrices, members, groups, assets)
        actual = actual_matrix(strategy, alpha_id, assets, grid)
        assert_matrix_matches(
            actual,
            expected,
            label="Alpha%d staggered market calendars runonce=%s" % (alpha_id, runonce),
        )
        assert_finite_witness(alpha_id, expected, declared_h)
        for row in _SUSPENSION_ROWS:
            assert math.isnan(actual[row][asset0]), (alpha_id, row, actual[row][asset0])
        assert any(
            math.isfinite(actual[row][asset0]) for row in range(_SUSPENSION_ROWS[-1] + 1, len(grid))
        ), ("Alpha%d did not recover after the resumed close" % alpha_id)


def _subindustry_revision_table(base_table, grid, asset, *, include_future_revision):
    asset_mask = base_table.index.get_level_values("asset") == asset
    other_assets = base_table.loc[~asset_mask].copy(deep=True)
    # Keep the target in a populated category so neutralized rolling inputs can
    # produce a finite target value before the unknown interval. The revision
    # moves it to a distinct category only at the future publication row.
    original_category = base_table.loc[(grid[0], asset), "category"]
    revised_category = base_table.loc[(grid[1], "asset-1"), "category"]

    records = [
        # This category is effective from the first grid but published only at
        # row 4, so the earlier projection must remain NOT_YET_AVAILABLE.
        (
            grid[0],
            original_category,
            grid[0],
            grid[_PIT_PUBLICATION_ROW],
            "synthetic-subindustry-v1",
        ),
        # One explicitly unknown PIT classification followed by a known
        # restoration exercises UNKNOWN_CLASSIFICATION independently.
        (
            grid[_PIT_UNKNOWN_ROW],
            None,
            grid[_PIT_UNKNOWN_ROW],
            grid[_PIT_UNKNOWN_ROW],
            "synthetic-subindustry-v1",
        ),
        (
            grid[_PIT_RESTORATION_ROW],
            original_category,
            grid[_PIT_RESTORATION_ROW],
            grid[_PIT_RESTORATION_ROW],
            "synthetic-subindustry-v1",
        ),
    ]
    if include_future_revision:
        records.append(
            (
                grid[_PIT_REVISION_ROW],
                revised_category,
                grid[_PIT_REVISION_ROW],
                grid[_PIT_REVISION_ROW],
                "synthetic-subindustry-v2",
            )
        )

    index = pd.MultiIndex.from_tuples(
        [(source_time, asset) for source_time, *_ in records], names=("time", "asset")
    )
    revisions = pd.DataFrame(
        [
            {
                "category": category,
                "effective_at": effective_at,
                "available_at": available_at,
                "level": "subindustry",
                "taxonomy_version": version,
            }
            for _, category, effective_at, available_at, version in records
        ],
        index=index,
    )
    return pd.concat((other_assets, revisions)).sort_index(), original_category, revised_category


def _subindustry_oracle_matrices(full_frames, grid, asset_index, old, new, *, future_revision):
    matrices = oracle_frames(full_frames, grid=grid)
    values = matrices["subindustry"]
    # The PIT table uses taxonomy labels while the frozen frame helper uses
    # numeric category IDs. Map labels back to those IDs for the independent
    # formula oracle so equal categories remain equal across representations.
    old_code = float(old.rsplit("-", 1)[-1]) if isinstance(old, str) else float(old)
    new_code = float(new.rsplit("-", 1)[-1]) if isinstance(new, str) else float(new)
    for row in range(_PIT_PUBLICATION_ROW):
        values[row][asset_index] = math.nan
    for row in range(_PIT_PUBLICATION_ROW, _PIT_UNKNOWN_ROW):
        values[row][asset_index] = old_code
    values[_PIT_UNKNOWN_ROW][asset_index] = math.nan
    for row in range(_PIT_RESTORATION_ROW, _PIT_REVISION_ROW):
        values[row][asset_index] = old_code
    for row in range(_PIT_REVISION_ROW, len(grid)):
        values[row][asset_index] = new_code if future_revision else old_code
    return matrices


def _expected_subindustry_window_reasons(grid_length, history_h):
    """Project PIT availability from source facts, without consulting outputs."""
    source_reasons = ["NOT_YET_AVAILABLE"] * grid_length
    for row in range(_PIT_PUBLICATION_ROW, grid_length):
        source_reasons[row] = "READY"
    source_reasons[_PIT_UNKNOWN_ROW] = "UNKNOWN_CLASSIFICATION"

    projected = []
    for row in range(grid_length):
        first = max(0, row - history_h)
        history = source_reasons[first : row + 1]
        if "NOT_YET_AVAILABLE" in history:
            projected.append("NOT_YET_AVAILABLE")
        elif "UNKNOWN_CLASSIFICATION" in history:
            projected.append("UNKNOWN_CLASSIFICATION")
        else:
            projected.append("READY")
    return tuple(projected)


def _assert_target_availability(strategy, asset, grid, rows, expected_reasons):
    dataset = strategy.get_dataset()
    availability = dataset.availability
    raw = dataset.raw_factors
    for row in rows:
        point = grid[row].to_pydatetime()
        state = availability.loc[(point, asset, "alpha67")]
        expected_reason = expected_reasons[row]
        expected_valid = expected_reason == "READY"
        assert state["reason"] == expected_reason, (row, state.to_dict())
        assert bool(state["ready"]) is expected_valid, (row, state.to_dict())
        assert bool(state["valid"]) is expected_valid, (row, state.to_dict())
        value = float(raw.at[(point, asset), "alpha67"])
        assert math.isfinite(value) is expected_valid, (row, value, state.to_dict())


@pytest.mark.parametrize("runonce", _RUN_MODES, ids=("runnext", "runonce"))
def test_alpha67_subindustry_unknown_late_publication_and_future_revision_are_causal(runonce):
    full_frames, grid, assets, _, _, _ = _full_grid_frames(periods=96)
    # This case isolates PIT industry neutralization from market-level rank
    # partitions; the production operator sees the complete formula panel.
    # Give asset-0 a peer in its unchanged original category, so its output can
    # become finite without introducing a category transition at publication.
    target_category = full_frames["asset-0"].iloc[0]["subindustry"]
    full_frames["asset-2"].loc[:, "subindustry"] = target_category
    groups = dict.fromkeys(assets, "market-all")
    members = formula_universe_matrix(grid, assets)
    base_research = make_research_spec(full_frames, formula_universe=members, groups=groups)
    asset = "asset-0"
    asset_index = assets.index(asset)
    tables = dict(base_research.classifications)
    base_table, old_category, revised_category = _subindustry_revision_table(
        tables["pit_subindustry"], grid, asset, include_future_revision=False
    )
    future_table, _, _ = _subindustry_revision_table(
        tables["pit_subindustry"], grid, asset, include_future_revision=True
    )
    assert old_category != revised_category

    base_tables = dict(tables)
    base_tables["pit_subindustry"] = base_table
    future_tables = dict(tables)
    future_tables["pit_subindustry"] = future_table
    base_research = make_research_spec(
        full_frames,
        formula_universe=members,
        groups=groups,
        classifications=base_tables,
    )
    future_research = make_research_spec(
        full_frames,
        formula_universe=members,
        groups=groups,
        classifications=future_tables,
    )

    aligned = prealign_pit_table(
        future_table, future_research, "pit_subindustry", classification=True
    )
    assert aligned.reason.loc[(grid[0], asset)] == "NOT_YET_AVAILABLE"
    assert aligned.reason.loc[(grid[_PIT_PUBLICATION_ROW - 1], asset)] == "NOT_YET_AVAILABLE"
    assert aligned.reason.loc[(grid[_PIT_PUBLICATION_ROW], asset)] == "READY"
    assert aligned.values.loc[(grid[_PIT_PUBLICATION_ROW], asset), "category"] == old_category
    assert aligned.reason.loc[(grid[_PIT_UNKNOWN_ROW], asset)] == "UNKNOWN_CLASSIFICATION"
    assert aligned.reason.loc[(grid[_PIT_RESTORATION_ROW], asset)] == "READY"
    assert aligned.values.loc[(grid[_PIT_REVISION_ROW - 1], asset), "category"] == old_category
    assert aligned.values.loc[(grid[_PIT_REVISION_ROW], asset), "category"] == revised_category

    base_matrices = _subindustry_oracle_matrices(
        full_frames, grid, asset_index, old_category, revised_category, future_revision=False
    )
    future_matrices = _subindustry_oracle_matrices(
        full_frames, grid, asset_index, old_category, revised_category, future_revision=True
    )
    base_expected, declared_h = _oracle_output(67, base_matrices, members, groups, assets)
    future_expected, future_h = _oracle_output(67, future_matrices, members, groups, assets)
    assert future_h == declared_h
    assert declared_h == get_alpha(67).lookback_h
    expected_reasons = _expected_subindustry_window_reasons(len(grid), declared_h)
    # Apply the independently projected input-availability contract to the
    # oracle target column. The formula oracle sees category values, while this
    # gate separately models when the source facts were actually available.
    for row, reason in enumerate(expected_reasons):
        if reason != "READY":
            base_expected[row][asset_index] = math.nan
            future_expected[row][asset_index] = math.nan
    assert_finite_witness(67, base_expected, declared_h)
    assert_finite_witness(67, future_expected, future_h)
    publication_history_ready_row = _PIT_PUBLICATION_ROW + declared_h
    restored_history_ready_row = _PIT_RESTORATION_ROW + declared_h
    assert 55 <= restored_history_ready_row < _PIT_REVISION_ROW
    assert expected_reasons[publication_history_ready_row] == "READY"
    assert expected_reasons[_PIT_UNKNOWN_ROW] == "UNKNOWN_CLASSIFICATION"
    assert expected_reasons[_PIT_UNKNOWN_ROW + declared_h] == "UNKNOWN_CLASSIFICATION"
    assert expected_reasons[restored_history_ready_row] == "READY"

    base_strategy = run_native_batch(
        full_frames,
        (67,),
        runonce=runonce,
        research=base_research,
        formula_universe=members,
        groups=groups,
    )
    future_strategy = run_native_batch(
        full_frames,
        (67,),
        runonce=runonce,
        research=future_research,
        formula_universe=members,
        groups=groups,
    )
    base_actual = actual_matrix(base_strategy, 67, assets, grid)
    future_actual = actual_matrix(future_strategy, 67, assets, grid)
    assert_matrix_matches(base_actual, base_expected, label="Alpha067 late-PIT baseline")

    # The future revision is absent from the source set before row 80, so every
    # already-visible historical output must match the independent oracle and
    # stay unchanged.  The changed classification is tested as a PIT projection
    # above; the post-revision path is deliberately outside this causal check.
    assert_matrix_matches(
        future_actual[:_PIT_REVISION_ROW],
        future_expected[:_PIT_REVISION_ROW],
        label="Alpha067 future-PIT oracle prefix",
    )
    assert_matrix_matches(
        future_actual[:_PIT_REVISION_ROW],
        base_actual[:_PIT_REVISION_ROW],
        label="Alpha067 pre-revision causal prefix",
    )
    assert math.isfinite(base_actual[publication_history_ready_row][asset_index])
    assert math.isfinite(base_actual[restored_history_ready_row][asset_index])
    assert any(math.isfinite(base_actual[row][asset_index]) for row in range(55, _PIT_REVISION_ROW))
    state_rows = (
        _PIT_PUBLICATION_ROW - 1,
        publication_history_ready_row,
        _PIT_UNKNOWN_ROW,
        _PIT_UNKNOWN_ROW + declared_h,
        restored_history_ready_row,
    )
    for strategy in (base_strategy, future_strategy):
        _assert_factor_lifecycle(strategy, (67,), grid)
        assert_availability_matches_values(strategy, (67,), grid, assets)
        _assert_target_availability(strategy, asset, grid, state_rows, expected_reasons)
