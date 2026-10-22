"""Full native Alpha101 acceptance matrix against the independent catalog oracle.

The default selection covers all six implementation batches and all 101 IDs.
For an incremental acceptance run, set ``BT_ALPHA101_NATIVE_BATCHES`` to a
comma-separated batch list or ``BT_ALPHA101_NATIVE_IDS`` to explicit IDs.  The
focused selectors deliberately avoid asserting that an incomplete registry
already contains the other batches.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research.errors import DatasetError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.specs import FactorSpec
from backtrader.research.alpha101 import get_alpha
from tests.test_utils.alpha101_full_reference import (
    formula_group,
    history_h,
    reference,
)
from tests.test_utils.alpha101_native_harness import (
    ALPHA_BATCHES,
    actual_matrix,
    alpha_name,
    assert_availability_matches_values,
    assert_batch_partition,
    assert_finite_witness,
    assert_lifecycle,
    assert_matrix_matches,
    assert_native_class_metadata,
    assert_registry_covers_all_ids,
    formula_universe_matrix,
    make_positive_fixture,
    make_research_spec,
    oracle_frames,
    run_native_batch,
    selected_alpha_batches,
    selected_alpha_ids,
    selection_is_focused,
)
from tests.unit.test_factor_research_representatives import _factor_spec, _research_feed

_RUN_MODES = (False, True)  # runnext, runonce
_MARKET_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "dollar_volume",
    "cap",
)


def _fixture_context(frames):
    assets = tuple(frames)
    grid = tuple(next(iter(frames.values())).index)
    members = formula_universe_matrix(grid, assets)
    groups = dict.fromkeys(assets, "market")
    return grid, assets, members, groups


def _preflight_source_field(alias):
    """Resolve a declared input alias to its independently supplied source."""
    if alias == "returns":
        return "close"
    if alias.startswith("adv") and alias[3:].isdigit():
        return "dollar_volume"
    return alias


def _expected_preflight_mask(alpha_id, frames, matrices, *, grid):
    """Project input availability over the public inclusive H-window contract.

    This derives only from the fixture's bar presence, market-field values, and
    already projected PIT classification matrices. It does not inspect the
    collected dataset or production availability table. Formula-universe
    membership is deliberately excluded: it is a current-output eligibility
    mask handled independently by the reference oracle.
    """
    assets = tuple(frames)
    factor_class = get_alpha(alpha_id)
    aliases = tuple(factor_class.formula_fields) + tuple(factor_class.classification_fields)
    source_fields = {alias: _preflight_source_field(alias) for alias in aliases}
    missing_sources = set(source_fields.values()) - set(matrices)
    if missing_sources:
        raise AssertionError(
            "Alpha%d fixture lacks preflight source matrices: %r"
            % (alpha_id, sorted(missing_sources))
        )
    if len(matrices) == 0 or any(
        len(matrices[field]) != len(grid) or any(len(row) != len(assets) for row in matrices[field])
        for field in source_fields.values()
    ):
        raise AssertionError("preflight source matrices must match the fixture grid")

    declared_h = history_h(alpha_id, matrices)
    present = {asset: set(frames[asset].index) for asset in assets}
    result = [[True for _asset in assets] for _point in grid]
    for row in range(len(grid)):
        start = max(0, row - declared_h)
        for column, asset in enumerate(assets):
            # FactorStrategy gives a missing current target bar precedence.
            if grid[row] not in present[asset]:
                result[row][column] = False
                continue
            for input_row in range(start, row + 1):
                if grid[input_row] not in present[asset]:
                    result[row][column] = False
                    break
                if any(
                    pd.isna(matrices[source_fields[alias]][input_row][column]) for alias in aliases
                ):
                    result[row][column] = False
                    break
    return result


def _oracle_output(
    alpha_id,
    matrices,
    members,
    groups,
    *,
    assets,
    expected_preflight_mask=None,
):
    oracle_groups = tuple(groups[asset] for asset in assets) if isinstance(groups, dict) else groups
    expected = reference(
        alpha_id,
        matrices,
        formula_universe=members,
        groups=oracle_groups,
    )
    declared_h = history_h(alpha_id, matrices)
    # Match the dataset's structural readiness gate independently of raw
    # formula evaluation; branch-local expressions can otherwise be finite
    # before the declared dependency-derived H.
    for row in range(min(declared_h, len(expected))):
        expected[row] = [math.nan] * len(expected[row])
    if expected_preflight_mask is not None:
        if len(expected_preflight_mask) != len(expected) or any(
            len(mask_row) != len(expected_row)
            for mask_row, expected_row in zip(expected_preflight_mask, expected)
        ):
            raise AssertionError("expected preflight mask must match the oracle time×asset grid")
        for row, mask_row in enumerate(expected_preflight_mask):
            for column, available in enumerate(mask_row):
                if not bool(available):
                    expected[row][column] = math.nan
    return expected, declared_h


def _checked_native_case(
    alpha_id,
    frames,
    *,
    runonce,
    grid,
    members,
    groups,
    research=None,
    matrices=None,
    expected_preflight_mask=None,
    alpha_classes=None,
):
    oracle_input = oracle_frames(frames, grid=grid) if matrices is None else matrices
    expected, declared_h = _oracle_output(
        alpha_id,
        oracle_input,
        members,
        groups,
        assets=tuple(frames),
        expected_preflight_mask=expected_preflight_mask,
    )
    if research is None:
        research = make_research_spec(
            frames,
            formula_universe=members,
            groups=groups,
        )
    strategy = run_native_batch(
        frames,
        (alpha_id,),
        runonce=runonce,
        alpha_classes=alpha_classes,
        research=research,
        formula_universe=members,
        groups=groups,
    )
    actual = actual_matrix(strategy, alpha_id, tuple(research.targets), grid)
    assert_matrix_matches(
        actual,
        expected,
        label="Alpha%d runonce=%s" % (alpha_id, runonce),
    )
    factor_class = alpha_classes[alpha_id] if alpha_classes is not None else get_alpha(alpha_id)
    assert factor_class.lookback_h == declared_h
    assert_finite_witness(alpha_id, expected, declared_h)
    assert_lifecycle(strategy, (alpha_id,), grid, alpha_classes=alpha_classes)
    assert_availability_matches_values(strategy, (alpha_id,), grid, tuple(research.targets))
    return strategy, actual, expected


def _availability(strategy, alpha_id, point, asset):
    key = (point.to_pydatetime(), asset, alpha_name(alpha_id))
    return strategy.get_dataset().availability.loc[key]


def _assert_state(strategy, alpha_id, point, asset, reason, *, ready, valid):
    state = _availability(strategy, alpha_id, point, asset)
    assert state["reason"] == reason
    assert bool(state["ready"]) is ready
    assert bool(state["valid"]) is valid


def _assert_preflight_reason_window(
    strategy,
    alpha_id,
    grid,
    asset,
    first_row,
    last_row,
    reason,
):
    for row in range(first_row, last_row + 1):
        _assert_state(
            strategy,
            alpha_id,
            grid[row],
            asset,
            reason,
            ready=False,
            valid=False,
        )


def test_alpha101_batch_matrix_matches_independent_oracle(
    batch_name,
    alpha_ids,
    alpha_classes=None,
):
    if alpha_classes is not None and set(alpha_classes) != set(alpha_ids):
        raise ValueError("alpha_classes must provide exactly the selected batch IDs")
    assert_native_class_metadata(alpha_ids, alpha_classes=alpha_classes)
    frames = make_positive_fixture()
    grid, assets, members, groups = _fixture_context(frames)
    matrices = oracle_frames(frames, grid=grid)
    expected_by_id = {}
    for alpha_id in alpha_ids:
        expected_by_id[alpha_id] = _oracle_output(
            alpha_id,
            matrices,
            members,
            groups,
            assets=assets,
        )

    by_mode = {}
    for runonce in _RUN_MODES:
        strategy = run_native_batch(
            frames,
            alpha_ids,
            runonce=runonce,
            alpha_classes=alpha_classes,
            formula_universe=members,
            groups=groups,
        )
        actual_by_id = {}
        for alpha_id in alpha_ids:
            expected, declared_h = expected_by_id[alpha_id]
            factor_class = (
                alpha_classes[alpha_id] if alpha_classes is not None else get_alpha(alpha_id)
            )
            label = "batch=%s Alpha%d runonce=%s" % (batch_name, alpha_id, runonce)
            assert factor_class.lookback_h == declared_h, label
            actual = actual_matrix(strategy, alpha_id, assets, grid)
            assert_matrix_matches(actual, expected, label=label)
            assert_finite_witness(alpha_id, expected, declared_h)
            actual_by_id[alpha_id] = actual
        assert_lifecycle(strategy, alpha_ids, grid, alpha_classes=alpha_classes)
        assert_availability_matches_values(strategy, alpha_ids, grid, assets)
        by_mode[runonce] = actual_by_id

    for alpha_id in alpha_ids:
        assert_matrix_matches(
            by_mode[False][alpha_id],
            by_mode[True][alpha_id],
            label="Alpha%d runnext versus runonce" % alpha_id,
        )

    # Exercise cross-sectional asset-order invariance and time-series
    # causality for every formula with one additional batched native run. The
    # changed suffix begins after the comparison prefix, and the oracle checks
    # the entire perturbed matrix (including that suffix).
    cutoff = 280
    perturbed = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    for offset, asset in enumerate(assets):
        frame = perturbed[asset]
        suffix = frame.index[cutoff:]
        multiplier = 1.25 + 0.17 * offset
        for field in ("open", "high", "low", "close", "vwap", "cap"):
            frame.loc[suffix, field] = frame.loc[suffix, field].astype(float) * multiplier + 11.0
        frame.loc[suffix, "volume"] = frame.loc[suffix, "volume"].astype(float) * (2.0 + offset)
        frame.loc[suffix, "dollar_volume"] = frame.loc[suffix, "vwap"] * frame.loc[suffix, "volume"]
    assert any(
        not frames[asset]
        .loc[grid[cutoff] :, field]
        .equals(perturbed[asset].loc[grid[cutoff] :, field])
        for asset in assets
        for field in _MARKET_FIELDS
    )

    reversed_assets = tuple(reversed(assets))
    reversed_frames = {asset: perturbed[asset] for asset in reversed_assets}
    reversed_members = formula_universe_matrix(grid, reversed_assets)
    reversed_groups = {asset: groups[asset] for asset in reversed_assets}
    reversed_matrices = oracle_frames(reversed_frames, grid=grid)
    reversed_expected = {
        alpha_id: _oracle_output(
            alpha_id,
            reversed_matrices,
            reversed_members,
            reversed_groups,
            assets=reversed_assets,
        )
        for alpha_id in alpha_ids
    }
    reversed_strategy = run_native_batch(
        reversed_frames,
        alpha_ids,
        runonce=False,
        alpha_classes=alpha_classes,
        formula_universe=reversed_members,
        groups=reversed_groups,
    )
    restored_positions = [reversed_assets.index(asset) for asset in assets]
    for alpha_id in alpha_ids:
        label = "batch=%s reordered future perturb Alpha%d" % (batch_name, alpha_id)
        expected, declared_h = reversed_expected[alpha_id]
        factor_class = alpha_classes[alpha_id] if alpha_classes is not None else get_alpha(alpha_id)
        assert factor_class.lookback_h == declared_h, label
        actual = actual_matrix(reversed_strategy, alpha_id, reversed_assets, grid)
        assert_matrix_matches(actual, expected, label=label)
        assert_finite_witness(alpha_id, expected, declared_h)
        actual_prefix = [
            [row[position] for position in restored_positions] for row in actual[:cutoff]
        ]
        baseline_prefix = by_mode[False][alpha_id][:cutoff]
        assert_matrix_matches(
            actual_prefix,
            baseline_prefix,
            label="batch=%s order/future invariance prefix Alpha%d" % (batch_name, alpha_id),
        )
        baseline_expected = expected_by_id[alpha_id][0]
        oracle_prefix = [
            [row[position] for position in restored_positions] for row in expected[:cutoff]
        ]
        assert_matrix_matches(
            oracle_prefix,
            baseline_expected[:cutoff],
            label="batch=%s independent oracle prefix Alpha%d" % (batch_name, alpha_id),
        )
    assert_lifecycle(
        reversed_strategy,
        alpha_ids,
        grid,
        alpha_classes=alpha_classes,
    )
    assert_availability_matches_values(reversed_strategy, alpha_ids, grid, reversed_assets)


test_alpha101_batch_matrix_matches_independent_oracle = pytest.mark.parametrize(
    ("batch_name", "alpha_ids"),
    selected_alpha_batches(),
    ids=[name for name, _ in selected_alpha_batches()],
)(test_alpha101_batch_matrix_matches_independent_oracle)


def test_alpha101_batch_partition_and_full_registry_contract():
    assert_batch_partition()
    selected = selected_alpha_ids()
    for alpha_id in selected:
        factor_class = get_alpha(alpha_id)
        assert factor_class.__bases__ == (FactorIndicator,)
        assert factor_class.__module__ == "backtrader.research.alpha101.alpha%03d" % alpha_id
        assert "__init__" in factor_class.__dict__
        assert "next" in factor_class.__dict__
    if not selection_is_focused():
        assert tuple(sorted(selected)) == tuple(range(1, 102))
        assert_registry_covers_all_ids()
    else:
        assert selected
        assert set(selected).issubset(
            {alpha_id for ids in ALPHA_BATCHES.values() for alpha_id in ids}
        )


def _run_asset_order_case(alpha_id, frames, runonce):
    grid, assets, members, groups = _fixture_context(frames)
    baseline, baseline_actual, _ = _checked_native_case(
        alpha_id,
        frames,
        runonce=runonce,
        grid=grid,
        members=members,
        groups=groups,
    )
    reversed_frames = {asset: frames[asset] for asset in reversed(assets)}
    reversed_assets = tuple(reversed(assets))
    reversed_members = formula_universe_matrix(grid, reversed_assets)
    reversed_groups = {asset: groups[asset] for asset in reversed_assets}
    reordered, reordered_actual, _ = _checked_native_case(
        alpha_id,
        reversed_frames,
        runonce=runonce,
        grid=grid,
        members=reversed_members,
        groups=reversed_groups,
    )
    positions = [reversed_assets.index(asset) for asset in assets]
    restored = [[row[position] for position in positions] for row in reordered_actual]
    assert_matrix_matches(
        restored,
        baseline_actual,
        label="Alpha%d asset-order invariance runonce=%s" % (alpha_id, runonce),
    )
    assert_lifecycle(baseline, (alpha_id,), grid)
    assert_lifecycle(reordered, (alpha_id,), grid)


def _run_future_perturbation_case(alpha_id, frames, runonce):
    grid, assets, members, groups = _fixture_context(frames)
    cutoff = 280
    changed = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    for offset, asset in enumerate(assets):
        frame = changed[asset]
        suffix = frame.index[cutoff:]
        multiplier = 1.25 + 0.17 * offset
        for field in ("open", "high", "low", "close", "vwap", "cap"):
            frame.loc[suffix, field] = frame.loc[suffix, field].astype(float) * multiplier + 11.0
        frame.loc[suffix, "volume"] = frame.loc[suffix, "volume"].astype(float) * (2.0 + offset)
        frame.loc[suffix, "dollar_volume"] = frame.loc[suffix, "vwap"] * frame.loc[suffix, "volume"]
    assert any(
        not frames[asset]
        .loc[grid[cutoff] :, field]
        .equals(changed[asset].loc[grid[cutoff] :, field])
        for asset in assets
        for field in _MARKET_FIELDS
    )

    baseline, baseline_actual, baseline_expected = _checked_native_case(
        alpha_id,
        frames,
        runonce=runonce,
        grid=grid,
        members=members,
        groups=groups,
    )
    perturbed, perturbed_actual, perturbed_expected = _checked_native_case(
        alpha_id,
        changed,
        runonce=runonce,
        grid=grid,
        members=members,
        groups=groups,
    )
    assert_matrix_matches(
        [row[:] for row in perturbed_actual[:cutoff]],
        [row[:] for row in baseline_actual[:cutoff]],
        label="Alpha%d native future-prefix invariance runonce=%s" % (alpha_id, runonce),
    )
    assert_matrix_matches(
        [row[:] for row in perturbed_expected[:cutoff]],
        [row[:] for row in baseline_expected[:cutoff]],
        label="Alpha%d oracle future-prefix invariance" % alpha_id,
    )
    assert_lifecycle(baseline, (alpha_id,), grid)
    assert_lifecycle(perturbed, (alpha_id,), grid)


def _run_missing_bar_case(frames, runonce):
    alpha_id = 9
    grid, assets, members, groups = _fixture_context(frames)
    research = make_research_spec(frames, formula_universe=members, groups=groups)
    missing_row = 180
    missing_time = grid[missing_row]
    gap_frames = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    gap_frames["asset-0"] = gap_frames["asset-0"].drop(index=missing_time)
    matrices = oracle_frames(gap_frames, grid=grid)
    preflight = _expected_preflight_mask(alpha_id, gap_frames, matrices, grid=grid)
    declared_h = history_h(alpha_id, matrices)
    last_blocked_row = min(len(grid) - 1, missing_row + declared_h)
    asset_column = assets.index("asset-0")
    assert all(not preflight[row][asset_column] for row in range(missing_row, last_blocked_row + 1))
    if last_blocked_row + 1 < len(grid):
        assert preflight[last_blocked_row + 1][asset_column]
    strategy, _, _ = _checked_native_case(
        alpha_id,
        gap_frames,
        runonce=runonce,
        grid=grid,
        members=members,
        groups=groups,
        research=research,
        matrices=matrices,
        expected_preflight_mask=preflight,
    )
    _assert_preflight_reason_window(
        strategy,
        alpha_id,
        grid,
        "asset-0",
        missing_row,
        last_blocked_row,
        "NO_CURRENT_BAR",
    )


def _run_formula_universe_case(frames, runonce):
    alpha_id = 3
    grid, assets, _, groups = _fixture_context(frames)
    members = formula_universe_matrix(grid, assets)
    first_exit, last_exit = 260, 265
    for row in range(first_exit, last_exit + 1):
        members[row][assets.index("asset-5")] = False
    matrices = oracle_frames(frames, grid=grid)
    preflight = _expected_preflight_mask(alpha_id, frames, matrices, grid=grid)
    asset_column = assets.index("asset-5")
    assert all(preflight[row][asset_column] for row in range(first_exit, last_exit + 1))
    assert preflight[280][asset_column]
    strategy, actual, expected = _checked_native_case(
        alpha_id,
        frames,
        runonce=runonce,
        grid=grid,
        members=members,
        groups=groups,
        matrices=matrices,
        expected_preflight_mask=preflight,
    )
    exit_point = grid[first_exit]
    _assert_state(
        strategy,
        alpha_id,
        exit_point,
        "asset-5",
        "FORMULA_INELIGIBLE",
        ready=False,
        valid=False,
    )
    reentered_point = grid[280]
    reentered_expected = expected[280][assets.index("asset-5")]
    assert math.isfinite(reentered_expected)
    assert math.isfinite(actual[280][assets.index("asset-5")])
    _assert_state(
        strategy,
        alpha_id,
        reentered_point,
        "asset-5",
        "READY",
        ready=True,
        valid=True,
    )


def _run_unknown_pit_case(alpha_id, level, unknown_row, frames, runonce):
    grid, assets, members, groups = _fixture_context(frames)
    unknown_time = grid[unknown_row]
    unknown_frames = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    unknown_frames["asset-0"].loc[unknown_time, level] = math.nan
    matrices = oracle_frames(unknown_frames, grid=grid)
    preflight = _expected_preflight_mask(alpha_id, unknown_frames, matrices, grid=grid)
    declared_h = history_h(alpha_id, matrices)
    last_blocked_row = min(len(grid) - 1, unknown_row + declared_h)
    asset_column = assets.index("asset-0")
    assert all(not preflight[row][asset_column] for row in range(unknown_row, last_blocked_row + 1))
    if last_blocked_row + 1 < len(grid):
        assert preflight[last_blocked_row + 1][asset_column]
    strategy, _, _ = _checked_native_case(
        alpha_id,
        unknown_frames,
        runonce=runonce,
        grid=grid,
        members=members,
        groups=groups,
        matrices=matrices,
        expected_preflight_mask=preflight,
    )
    _assert_preflight_reason_window(
        strategy,
        alpha_id,
        grid,
        "asset-0",
        unknown_row,
        last_blocked_row,
        "UNKNOWN_CLASSIFICATION",
    )


def _run_late_industry_case(frames, runonce):
    alpha_id = 63
    grid, assets, members, groups = _fixture_context(frames)
    base_research = make_research_spec(frames, formula_universe=members, groups=groups)
    tables = dict(base_research.classifications)
    industry = tables["pit_industry"]
    asset_rows = industry.index.get_level_values("asset") == "asset-0"
    first_key = industry.index[asset_rows][0]
    late_row = industry.loc[[first_key]].copy(deep=True)
    industry = industry.loc[~asset_rows].copy(deep=True)
    # Publish a previously unknown category late enough to exercise the PIT
    # projection, then allow the formula's structural input window to move
    # wholly past the unknown prefix before expecting a READY output.
    publication_row = 10
    late_point = grid[publication_row]
    late_row.index = pd.MultiIndex.from_tuples([(grid[0], "asset-0")], names=("time", "asset"))
    late_row.loc[(grid[0], "asset-0"), "effective_at"] = grid[0]
    late_row.loc[(grid[0], "asset-0"), "available_at"] = late_point
    tables["pit_industry"] = pd.concat((industry, late_row)).sort_index()
    research = make_research_spec(
        frames,
        formula_universe=members,
        groups=groups,
        classifications=tables,
    )
    matrices = oracle_frames(frames, grid=grid)
    published_industry = float(frames["asset-0"]["industry"].iloc[0])
    for row in range(publication_row):
        matrices["industry"][row][assets.index("asset-0")] = math.nan
    for row in range(publication_row, len(grid)):
        matrices["industry"][row][assets.index("asset-0")] = published_industry
    preflight = _expected_preflight_mask(alpha_id, frames, matrices, grid=grid)
    declared_h = history_h(alpha_id, matrices)
    first_ready_row = publication_row + declared_h
    asset_column = assets.index("asset-0")
    assert all(not preflight[row][asset_column] for row in range(first_ready_row))
    assert preflight[first_ready_row][asset_column]
    strategy, actual, expected = _checked_native_case(
        alpha_id,
        frames,
        runonce=runonce,
        grid=grid,
        members=members,
        groups=groups,
        research=research,
        matrices=matrices,
        expected_preflight_mask=preflight,
    )
    _assert_preflight_reason_window(
        strategy,
        alpha_id,
        grid,
        "asset-0",
        0,
        first_ready_row - 1,
        "NOT_YET_AVAILABLE",
    )
    assert math.isfinite(expected[first_ready_row][assets.index("asset-0")])
    assert math.isfinite(actual[first_ready_row][assets.index("asset-0")])
    _assert_state(
        strategy,
        alpha_id,
        grid[first_ready_row],
        "asset-0",
        "READY",
        ready=True,
        valid=True,
    )


def _run_domain_edge_case(alpha_id, frames, runonce):
    grid, assets, members, groups = _fixture_context(frames)
    constants = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    if alpha_id == 3:
        # Keep this asset's cross-sectional rank fixed at the low endpoint;
        # its rolling correlation is undefined while the other assets remain
        # ordinary finite witnesses.
        constants[assets[0]]["open"] = 0.001
    elif alpha_id == 48:
        # A zero close exercises the formula's denominator boundary for one
        # target without degenerating the whole six-asset panel.
        constants[assets[0]]["close"] = 0.0
    else:
        raise AssertionError("unexpected domain-edge formula")
    matrices = oracle_frames(constants, grid=grid)
    preflight = _expected_preflight_mask(alpha_id, constants, matrices, grid=grid)
    probe_row = 40 if alpha_id == 3 else 260
    assert preflight[probe_row][0], "domain witness inputs must remain preflight-available"
    strategy, actual, expected = _checked_native_case(
        alpha_id,
        constants,
        runonce=runonce,
        grid=grid,
        members=members,
        groups=groups,
        matrices=matrices,
        expected_preflight_mask=preflight,
    )
    assert math.isnan(expected[probe_row][0])
    assert math.isnan(actual[probe_row][0])
    _assert_state(
        strategy,
        alpha_id,
        grid[probe_row],
        assets[0],
        "DOMAIN_ERROR",
        ready=True,
        valid=False,
    )
    for column, asset in enumerate(assets[1:], start=1):
        assert math.isfinite(expected[probe_row][column])
        assert math.isfinite(actual[probe_row][column])
        _assert_state(
            strategy,
            alpha_id,
            grid[probe_row],
            asset,
            "READY",
            ready=True,
            valid=True,
        )


def _run_pure_ts_independence_case(frames, runonce):
    alpha_id = 9
    assert formula_group(alpha_id) == "TS"
    grid, assets, members, groups = _fixture_context(frames)
    changed = {asset: frame.copy(deep=True) for asset, frame in frames.items()}
    target = changed["asset-1"]
    target["close"] = target["close"].astype(float) * 2.75 + 13.0
    baseline, baseline_actual, _ = _checked_native_case(
        alpha_id,
        frames,
        runonce=runonce,
        grid=grid,
        members=members,
        groups=groups,
    )
    perturbed, perturbed_actual, _ = _checked_native_case(
        alpha_id,
        changed,
        runonce=runonce,
        grid=grid,
        members=members,
        groups=groups,
    )
    asset0 = assets.index("asset-0")
    assert_matrix_matches(
        [[row[asset0]] for row in perturbed_actual],
        [[row[asset0]] for row in baseline_actual],
        label="pure TS Alpha009 has no cross-asset input dependency",
    )
    assert_lifecycle(baseline, (alpha_id,), grid)
    assert_lifecycle(perturbed, (alpha_id,), grid)


def _run_invalid_binding_case(frames):
    alpha_id = 3
    grid, assets, members, groups = _fixture_context(frames)
    research = make_research_spec(frames, formula_universe=members, groups=groups)
    good = _factor_spec(alpha_name(alpha_id), get_alpha(alpha_id))
    bindings = dict(good.field_bindings)
    missing_alias = next(iter(bindings))
    del bindings[missing_alias]
    bad = FactorSpec(
        name=good.name,
        indicator=good.indicator,
        panel_line=good.panel_line,
        params=good.params,
        field_bindings=bindings,
        classification_bindings=good.classification_bindings,
        operator_profile=good.operator_profile,
        direction=good.direction,
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    for asset, frame in frames.items():
        cerebro.adddata(_research_feed(frame, research, asset), name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors={good.name: bad})
    with pytest.raises(DatasetError) as caught:
        cerebro.run()
    assert caught.value.code == "MISSING_INPUT"
    assert missing_alias in caught.value.report["missing_fields"]


def test_alpha101_full_native_contract_scenarios():
    selected = set(selected_alpha_ids())
    scenario_ids = {3, 9, 48, 58, 63}
    if not selected.intersection(scenario_ids):
        pytest.skip("focused Alpha101 selection does not include a scenario anchor")

    base_frames = make_positive_fixture()
    for runonce in _RUN_MODES:
        for alpha_id in (3, 48):
            if alpha_id in selected:
                _run_asset_order_case(alpha_id, base_frames, runonce)
        for alpha_id in (3, 9):
            if alpha_id in selected:
                _run_future_perturbation_case(alpha_id, base_frames, runonce)
        if 9 in selected:
            _run_missing_bar_case(base_frames, runonce)
            _run_pure_ts_independence_case(base_frames, runonce)
        if 3 in selected:
            _run_formula_universe_case(base_frames, runonce)
        if 58 in selected:
            _run_unknown_pit_case(58, "sector", 220, base_frames, runonce)
        if 63 in selected:
            _run_unknown_pit_case(63, "industry", 280, base_frames, runonce)
        if 63 in selected:
            _run_late_industry_case(base_frames, runonce)
        for alpha_id in (3, 48):
            if alpha_id in selected:
                _run_domain_edge_case(alpha_id, base_frames, runonce)

    if 3 in selected:
        _run_invalid_binding_case(base_frames)


test_alpha101_batch_matrix_matches_independent_oracle.__doc__ = (
    "Compare every selected ID in each configured batch against independent values, NaNs, H, "
    "run modes, lifecycle, and broker silence."
)
