"""Composite boundary matrix for native Alpha101 factors.

The fixture is shared by the six acceptance batches. Expected numeric values
come from the standalone catalog oracle; readiness and reason codes are
projected separately from the public feed/PIT preflight contract.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research.alpha101 import get_alpha
from backtrader.errors import DatasetError
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.specs import FactorSpec
from tests.test_utils.alpha101_full_reference import (
    history_h,
    reference,
)
from tests.test_utils.alpha101_native_harness import (
    actual_matrix,
    alpha_name,
    assert_finite_witness,
    assert_lifecycle,
    assert_matrix_matches,
    assert_native_class_metadata,
    formula_universe_matrix,
    make_positive_fixture,
    make_research_spec,
    oracle_frames,
    run_native_batch,
    selected_alpha_batches,
    selected_alpha_ids,
)
from tests.unit.test_factor_research_representatives import _factor_spec, _research_feed


_CATEGORY_FIELDS = ("sector", "industry", "subindustry")
_TIED_ROWS = tuple(range(260, 265))
_UNKNOWN_SUBINDUSTRY_ROWS = tuple(range(180, 183))
_MISSING_BAR_ROWS = (40, 41)
_MISSING_DOLLAR_VOLUME_ROW = 290
_ZERO_VOLUME_ROW = 300
_ZERO_CLOSE_ROW = 301


def _build_composite_fixture() -> Dict[str, Any]:
    base_frames = make_positive_fixture(periods=320)
    assets = tuple(base_frames)
    grid = tuple(next(iter(base_frames.values())).index)
    members = formula_universe_matrix(grid, assets)
    groups = dict.fromkeys(assets, "market")

    base_research = make_research_spec(
        base_frames,
        formula_universe=members,
        groups=groups,
    )
    classifications = dict(base_research.classifications)
    subindustry = classifications["pit_subindustry"].copy(deep=True)
    for row in _UNKNOWN_SUBINDUSTRY_ROWS:
        subindustry.loc[(grid[row], "asset-3"), "category"] = None
    classifications["pit_subindustry"] = subindustry
    research = make_research_spec(
        base_frames,
        formula_universe=members,
        groups=groups,
        classifications=classifications,
    )

    frames = {asset: frame.copy(deep=True) for asset, frame in base_frames.items()}

    # A short constant panel segment gives every cross-sectional formula real
    # ties while leaving a long, varied prefix for finite-value witnesses.
    tied_values = {
        "open": 2.0,
        "high": 2.5,
        "low": 1.5,
        "close": 2.0,
        "volume": 4500.0,
        "vwap": 2.0,
        "cap": 1_000_000.0,
    }
    tied_times = [grid[row] for row in _TIED_ROWS]
    for frame in frames.values():
        for field, value in tied_values.items():
            frame.loc[tied_times, field] = value
        frame.loc[tied_times, "dollar_volume"] = (
            frame.loc[tied_times, "vwap"] * frame.loc[tied_times, "volume"]
        )

    # These are finite, present bars. A zero volume keeps dollar volume
    # consistent, and a zero close is isolated to a separate asset/bar.
    frames["asset-1"].loc[grid[_ZERO_VOLUME_ROW], "volume"] = 0.0
    frames["asset-1"].loc[grid[_ZERO_VOLUME_ROW], "dollar_volume"] = 0.0
    frames["asset-2"].loc[grid[_ZERO_CLOSE_ROW], "close"] = 0.0
    frames["asset-2"].loc[grid[_ZERO_CLOSE_ROW], "low"] = 0.0

    # A present bar with one unavailable required raw source distinguishes a
    # non-finite input from a missing current bar.
    frames["asset-4"].loc[grid[_MISSING_DOLLAR_VOLUME_ROW], "dollar_volume"] = math.nan

    # PIT categories are separate from market-feed presence. Preserve the full
    # source classification table and publish an explicit unknown interval.
    for row in _UNKNOWN_SUBINDUSTRY_ROWS:
        frames["asset-3"].loc[grid[row], "subindustry"] = math.nan

    # Halt and reopen one actual feed. The ResearchSpec/PIT tables above remain
    # on the complete grid and are not built from this shorter feed.
    frames["asset-0"] = frames["asset-0"].drop(index=[grid[row] for row in _MISSING_BAR_ROWS])
    effective_members = [list(row) for row in members]
    asset_positions = {asset: position for position, asset in enumerate(assets)}
    for row_index, point in enumerate(grid):
        for asset in assets:
            if point not in frames[asset].index:
                effective_members[row_index][asset_positions[asset]] = False

    matrices = oracle_frames(frames, grid=grid)
    for level in _CATEGORY_FIELDS:
        table = research.classifications["pit_%s" % level]
        matrices[level] = [
            [
                math.nan
                if pd.isna(table.at[(point, asset), "category"])
                else table.at[(point, asset), "category"]
                for asset in assets
            ]
            for point in grid
        ]

    return {
        "frames": frames,
        "research": research,
        "grid": grid,
        "assets": assets,
        "members": members,
        "effective_members": effective_members,
        "groups": groups,
        "oracle_groups": tuple(groups[asset] for asset in assets),
        "matrices": matrices,
    }


@pytest.fixture(scope="module")
def alpha101_composite_boundary_fixture():
    return _build_composite_fixture()


def _source_field(alias: str) -> str:
    if alias == "returns":
        return "close"
    if alias.startswith("adv") and alias[3:].isdigit():
        return "dollar_volume"
    return alias


def _alias_preflight_reason(
    alias: str,
    *,
    is_classification: bool,
    factor_class: Any,
    asset_index: int,
    row_index: int,
    fixture: Mapping[str, Any],
) -> Optional[str]:
    grid = fixture["grid"]
    asset = fixture["assets"][asset_index]
    frames = fixture["frames"]
    matrices = fixture["matrices"]
    frame = frames[asset]
    first_row = max(0, row_index - factor_class.lookback_h)

    for input_row in range(first_row, row_index + 1):
        point = grid[input_row]
        if is_classification:
            value = matrices[alias][input_row][asset_index]
            if pd.isna(value):
                return "UNKNOWN_CLASSIFICATION"
            continue

        field = _source_field(alias)
        if field not in frame.columns:
            return "MISSING_FIELD"
        if point not in frame.index:
            return "NO_CURRENT_BAR"
        if pd.isna(frame.at[point, field]):
            return "NONFINITE_INPUT"
    return None


def _expected_reason(
    factor_class: Any,
    asset_index: int,
    row_index: int,
    raw_value: float,
    fixture: Mapping[str, Any],
) -> Tuple[str, bool, bool]:
    asset = fixture["assets"][asset_index]
    point = fixture["grid"][row_index]
    if point not in fixture["frames"][asset].index:
        return "NO_CURRENT_BAR", False, False

    for alias in tuple(factor_class.formula_fields) + tuple(factor_class.classification_fields):
        reason = _alias_preflight_reason(
            alias,
            is_classification=alias in factor_class.classification_fields,
            factor_class=factor_class,
            asset_index=asset_index,
            row_index=row_index,
            fixture=fixture,
        )
        if reason == "NONFINITE_INPUT":
            return reason, True, False
        if reason is not None:
            return reason, False, False

    declared_h = factor_class.lookback_h
    if row_index < declared_h:
        return "INCOMPLETE_WINDOW", False, False
    if math.isfinite(raw_value):
        return "READY", True, True
    return "DOMAIN_ERROR", True, False


def _project_oracle_and_preflight(
    alpha_id: int, factor_class: Any, fixture: Mapping[str, Any]
) -> Tuple[list, list, int]:
    matrices = fixture["matrices"]
    raw_expected = reference(
        alpha_id,
        matrices,
        formula_universe=fixture["effective_members"],
        groups=fixture["oracle_groups"],
    )
    declared_h = history_h(alpha_id, matrices)
    if factor_class.lookback_h != declared_h:
        raise AssertionError(
            "Alpha%d production H=%d differs from independent H=%d"
            % (alpha_id, factor_class.lookback_h, declared_h)
        )

    expected = [list(row) for row in raw_expected]
    states = []
    for row_index, row in enumerate(raw_expected):
        state_row = []
        for asset_index, raw_value in enumerate(row):
            raw_value = float(raw_value)
            if math.isinf(raw_value):
                raise AssertionError("Alpha%d oracle produced infinity" % alpha_id)
            state = _expected_reason(
                factor_class,
                asset_index,
                row_index,
                raw_value,
                fixture,
            )
            reason, ready, valid = state
            if not valid:
                expected[row_index][asset_index] = math.nan
            elif not math.isfinite(raw_value):
                raise AssertionError(
                    "Alpha%d preflight marked an oracle NaN valid at (%d,%d)"
                    % (alpha_id, row_index, asset_index)
                )
            state_row.append((reason, ready, valid))
        states.append(state_row)
    assert_finite_witness(alpha_id, expected, declared_h)
    return expected, states, declared_h


def _resolve_class(alpha_id: int, alpha_classes: Optional[Mapping[int, Any]]) -> Any:
    if alpha_classes is None:
        factor_class = get_alpha(alpha_id)
    else:
        if alpha_id not in alpha_classes:
            raise ValueError("alpha_classes does not include Alpha%d" % alpha_id)
        factor_class = alpha_classes[alpha_id]
    if getattr(factor_class, "alpha_id", None) != alpha_id:
        raise AssertionError("Alpha%d class mapping has a mismatched alpha_id" % alpha_id)
    assert_native_class_metadata((alpha_id,), alpha_classes={alpha_id: factor_class})
    return factor_class


def _assert_availability(
    strategy: Any,
    alpha_id: int,
    states: Sequence[Sequence[Tuple[str, bool, bool]]],
    fixture: Mapping[str, Any],
) -> None:
    availability = strategy.get_dataset().availability
    name = alpha_name(alpha_id)
    for row_index, state_row in enumerate(states):
        point = fixture["grid"][row_index].to_pydatetime()
        for asset_index, expected in enumerate(state_row):
            asset = fixture["assets"][asset_index]
            actual = availability.loc[(point, asset, name)]
            assert (
                actual["reason"] == expected[0]
            ), "Alpha%d availability reason differs at row=%d asset=%s: %s != %s" % (
                alpha_id,
                row_index,
                asset,
                actual["reason"],
                expected[0],
            )
            assert bool(actual["ready"]) is expected[1]
            assert bool(actual["valid"]) is expected[2]


def _assert_fixture_contract(fixture: Mapping[str, Any]) -> None:
    frames = fixture["frames"]
    assets = fixture["assets"]
    grid = fixture["grid"]
    matrices = fixture["matrices"]
    assert len(assets) == 6 and len(grid) == 320
    assert tuple(frames["asset-0"].index) == tuple(
        point for row, point in enumerate(grid) if row not in _MISSING_BAR_ROWS
    )
    asset0 = assets.index("asset-0")
    assert all(fixture["members"][row][asset0] for row in _MISSING_BAR_ROWS)
    assert all(not fixture["effective_members"][row][asset0] for row in _MISSING_BAR_ROWS)
    assert frames["asset-1"].at[grid[_ZERO_VOLUME_ROW], "volume"] == 0.0
    assert frames["asset-2"].at[grid[_ZERO_CLOSE_ROW], "close"] == 0.0
    assert pd.isna(frames["asset-4"].at[grid[_MISSING_DOLLAR_VOLUME_ROW], "dollar_volume"])
    assert all(
        pd.isna(matrices["subindustry"][row][assets.index("asset-3")])
        for row in _UNKNOWN_SUBINDUSTRY_ROWS
    )
    for field in ("open", "high", "low", "close", "volume", "vwap", "cap"):
        for row in _TIED_ROWS:
            assert len({matrices[field][row][column] for column in range(len(assets))}) == 1


@pytest.mark.parametrize(
    ("batch_name", "alpha_ids"),
    selected_alpha_batches(),
    ids=[name for name, _ in selected_alpha_batches()],
)
def test_alpha101_composite_boundaries_match_oracle_and_preflight(
    batch_name: str,
    alpha_ids: Sequence[int],
    alpha101_composite_boundary_fixture: Mapping[str, Any],
    alpha_classes: Optional[Mapping[int, Any]] = None,
) -> None:
    if alpha_classes is not None and set(alpha_classes) != set(alpha_ids):
        raise ValueError("alpha_classes must provide exactly the selected batch IDs")
    assert_native_class_metadata(alpha_ids, alpha_classes=alpha_classes)
    fixture = alpha101_composite_boundary_fixture
    _assert_fixture_contract(fixture)

    expected_by_id = {}
    for alpha_id in alpha_ids:
        factor_class = _resolve_class(alpha_id, alpha_classes)
        expected, states, declared_h = _project_oracle_and_preflight(
            alpha_id, factor_class, fixture
        )
        expected_by_id[alpha_id] = (expected, states, declared_h)

    for runonce in (False, True):
        strategy = run_native_batch(
            fixture["frames"],
            alpha_ids,
            runonce=runonce,
            alpha_classes=alpha_classes,
            research=fixture["research"],
            formula_universe=fixture["members"],
            groups=fixture["groups"],
        )
        assert_lifecycle(
            strategy,
            alpha_ids,
            fixture["grid"],
            alpha_classes=alpha_classes,
        )
        for alpha_id in alpha_ids:
            expected, states, _declared_h = expected_by_id[alpha_id]
            actual = actual_matrix(strategy, alpha_id, fixture["assets"], fixture["grid"])
            assert_matrix_matches(
                actual,
                expected,
                label="batch=%s composite-boundary Alpha%d runonce=%s"
                % (batch_name, alpha_id, runonce),
            )
            _assert_availability(strategy, alpha_id, states, fixture)


def _short_missing_binding_context():
    full = make_positive_fixture(periods=320)
    frames = {asset: frame.iloc[:12].copy(deep=True) for asset, frame in tuple(full.items())[:3]}
    grid = tuple(next(iter(frames.values())).index)
    assets = tuple(frames)
    members = formula_universe_matrix(grid, assets)
    groups = dict.fromkeys(assets, "market")
    research = make_research_spec(frames, formula_universe=members, groups=groups)
    return frames, research


@pytest.fixture(scope="module")
def alpha101_short_missing_binding_context():
    return _short_missing_binding_context()


def _bad_factor_spec(
    alpha_id: int,
    factor_class: Any,
    *,
    field_alias: Optional[str] = None,
    classification_alias: Optional[str] = None,
) -> Tuple[FactorSpec, str]:
    good = _factor_spec(alpha_name(alpha_id), factor_class)
    fields = dict(good.field_bindings)
    classifications = dict(good.classification_bindings)
    if field_alias is not None:
        del fields[field_alias]
        expected_missing = field_alias
    else:
        del classifications[classification_alias]
        expected_missing = classification_alias
    bad = FactorSpec(
        name=good.name,
        indicator=good.indicator,
        panel_line=good.panel_line,
        params=good.params,
        field_bindings=fields,
        classification_bindings=classifications,
        operator_profile=good.operator_profile,
        direction=good.direction,
    )
    return bad, expected_missing


@pytest.mark.parametrize("alpha_id", selected_alpha_ids(), ids=lambda value: "alpha%d" % value)
def test_each_alpha_rejects_an_absent_required_raw_field_before_calculation(
    alpha_id: int,
    alpha101_short_missing_binding_context: Tuple[Mapping[str, Any], Any],
    alpha_classes: Optional[Mapping[int, Any]] = None,
) -> None:
    factor_class = _resolve_class(alpha_id, alpha_classes)
    frames, research = alpha101_short_missing_binding_context
    raw_columns = set(next(iter(frames.values())).columns)
    raw_aliases = tuple(
        alias
        for alias in factor_class.formula_fields
        if not alias.startswith("adv") and _source_field(alias) in raw_columns
    )
    if not raw_aliases:
        raise AssertionError("Alpha%d declares no directly bound raw input alias" % alpha_id)
    missing_alias = raw_aliases[0]
    bad, expected_missing = _bad_factor_spec(
        alpha_id,
        factor_class,
        field_alias=missing_alias,
    )
    assert expected_missing == missing_alias
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    for asset, frame in frames.items():
        cerebro.adddata(_research_feed(frame, research, asset), name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors={bad.name: bad})

    with pytest.raises(DatasetError) as caught:
        cerebro.run()
    assert caught.value.code == "MISSING_INPUT"
    assert caught.value.report["missing_fields"] == (expected_missing,)


def test_classification_factor_rejects_an_absent_required_category_binding():
    alpha_id = 58
    factor_class = get_alpha(alpha_id)
    frames, research = _short_missing_binding_context()
    missing_alias = tuple(factor_class.classification_fields)[0]
    bad, expected_missing = _bad_factor_spec(
        alpha_id,
        factor_class,
        classification_alias=missing_alias,
    )
    assert expected_missing == missing_alias
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    for asset, frame in frames.items():
        cerebro.adddata(_research_feed(frame, research, asset), name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors={bad.name: bad})

    with pytest.raises(DatasetError) as caught:
        cerebro.run()
    assert caught.value.code == "MISSING_INPUT"
    assert caught.value.report["missing_classifications"] == (expected_missing,)


__all__ = (
    "alpha101_composite_boundary_fixture",
    "alpha101_short_missing_binding_context",
    "test_alpha101_composite_boundaries_match_oracle_and_preflight",
    "test_classification_factor_rejects_an_absent_required_category_binding",
    "test_each_alpha_rejects_an_absent_required_raw_field_before_calculation",
)
