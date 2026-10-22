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

from backtrader.research import align_to_grid
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.alpha101 import get_alpha
from tests.test_utils.alpha101_full_reference import history_h, reference
from tests.test_utils.alpha101_native_harness import (
    actual_matrix,
    assert_presence_matches_finite_values,
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
    research = make_research_spec(frames, groups=groups)
    return frames, grid, assets, groups, members, research


def _oracle_output(alpha_id, matrices, members, groups, assets):
    oracle_groups = tuple(groups[asset] for asset in assets)
    expected = reference(
        alpha_id,
        matrices,
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




