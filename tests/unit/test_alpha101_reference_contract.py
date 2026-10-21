"""Contract checks for the independent, paper-source Alpha101 matrix oracle."""

import ast
import hashlib
import math
from pathlib import Path
import random

import pytest

from tests.test_utils import alpha101_full_reference as reference


_KNOWN_H = {
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


def _matrix_frames(rows=16, assets=4, *, with_adv=False):
    names = ("open", "high", "low", "close", "volume", "vwap", "dollar_volume", "cap")
    fields = {name: [] for name in names}
    rngs = [
        (
            random.Random(91_001 + asset),
            random.Random(92_003 + asset),
            random.Random(93_007 + asset),
            random.Random(94_009 + asset),
        )
        for asset in range(assets)
    ]
    for row in range(rows):
        values = {name: [] for name in names}
        for asset in range(assets):
            close_rng, open_rng, volume_rng, vwap_rng = rngs[asset]
            close = 20.0 + 0.18 * asset + 0.0005 * row + close_rng.uniform(-1.4, 1.4)
            open_ = close - 0.12 + open_rng.uniform(-0.3, 0.3)
            high = max(open_, close) + 0.21 + asset * 0.003
            low = min(open_, close) - 0.19 - row * 0.0001
            volume = 1000.0 + 37.0 * asset + 2.0 * row + volume_rng.uniform(-650.0, 650.0)
            vwap = close + vwap_rng.uniform(-0.5, 0.5)
            row_values = {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "vwap": vwap,
                "dollar_volume": vwap * volume,
                "cap": 1_000_000.0 + 100_000.0 * asset + 30.0 * row,
            }
            for name, value in row_values.items():
                values[name].append(value)
        for name in names:
            fields[name].append(values[name])
    fields["sector"] = [
        ["s0" if asset < 2 else "s1" for asset in range(assets)] for _ in range(rows)
    ]
    fields["industry"] = [
        ["i0" if asset < 2 else "i1" for asset in range(assets)] for _ in range(rows)
    ]
    fields["subindustry"] = [
        ["ss%d" % (asset // 2) for asset in range(assets)] for _ in range(rows)
    ]
    if with_adv:
        for window in (5, 10, 15, 20, 30, 40, 50, 60, 81, 120, 150, 180):
            source = fields["dollar_volume"]
            matrix = [[math.nan] * assets for _ in range(rows)]
            for row in range(window - 1, rows):
                for asset in range(assets):
                    matrix[row][asset] = (
                        math.fsum(
                            source[position][asset] for position in range(row - window + 1, row + 1)
                        )
                        / window
                    )
            fields["adv%d" % window] = matrix
    return fields


def test_reference_has_no_production_or_representative_imports():
    source_path = Path(reference.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any(
        name == "backtrader" or name.startswith("backtrader.") or "representative" in name
        for name in imported
    )


def test_catalog_source_hashes_groups_and_all_formula_trees_are_supported():
    assert reference.formula_ids() == tuple(range(1, 102))
    groups = [reference.formula_group(alpha_id) for alpha_id in reference.formula_ids()]
    assert {name: groups.count(name) for name in set(groups)} == {
        "CS": 65,
        "TS": 18,
        "industry": 18,
    }
    for alpha_id in reference.formula_ids():
        source = reference.formula_source(alpha_id)
        metadata = reference.formula_metadata(alpha_id)
        assert (
            hashlib.sha256(source.encode("utf-8")).hexdigest() == metadata["source_formula_sha256"]
        )
        assert metadata["id"] == alpha_id
        assert reference._parse(alpha_id)  # every original token stream parses


def test_independent_structural_h_matches_all_fixed_representative_anchors():
    assert {alpha_id: reference.history_h(alpha_id) for alpha_id in _KNOWN_H} == _KNOWN_H
    assert reference.history_h(81, _matrix_frames(with_adv=True)) == 68
    assert reference.history_h(81, _matrix_frames()) == 77


def test_all_formulas_evaluate_as_matrix_outputs_without_production_imports():
    frames = _matrix_frames()
    actual = reference.reference_all(frames)
    assert tuple(actual) == tuple(range(1, 102))
    assert all(
        len(matrix) == 16 and all(len(row) == 4 for row in matrix) for matrix in actual.values()
    )
    # Alpha101 has no temporal dependency and proves scalar broadcasting and
    # operator precedence against an independently calculated known answer.
    expected = (frames["close"][0][0] - frames["open"][0][0]) / (
        frames["high"][0][0] - frames["low"][0][0] + 0.001
    )
    assert actual[101][0][0] == pytest.approx(expected, rel=0.0, abs=1e-15)


def test_membership_and_research_groups_change_cross_sectional_denominators():
    frames = {
        "vwap": [[10.0, 20.0, 30.0, 40.0]],
        "close": [[40.0, 30.0, 20.0, 10.0]],
    }
    groups = ("left", "left", "right", "right")
    members = [[True, True, True, False]]
    result = reference.reference(42, frames, formula_universe=members, groups=groups)[0]
    assert result[:3] == pytest.approx([2.0 / 3.0, 4.0 / 3.0, 1.0], rel=0.0, abs=1e-15)
    assert math.isnan(result[3])


def test_asset_oriented_frames_preserve_asset_order_and_match_matrix_orientation():
    fields = {
        "open": [[1.0, 2.0], [2.0, 3.0]],
        "high": [[2.0, 3.0], [3.0, 4.0]],
        "low": [[0.0, 1.0], [1.0, 2.0]],
        "close": [[1.5, 2.5], [2.5, 3.5]],
    }
    assets = {
        "asset-a": {name: [matrix[row][0] for row in range(2)] for name, matrix in fields.items()},
        "asset-b": {name: [matrix[row][1] for row in range(2)] for name, matrix in fields.items()},
    }
    assert reference.reference(101, fields) == reference.reference(101, assets)


def test_unknown_membership_is_rejected_and_required_pit_level_never_falls_back():
    with pytest.raises(reference.FormulaError, match="unknown/non-boolean"):
        reference.reference(
            42,
            {"vwap": [[10.0, 20.0]], "close": [[20.0, 10.0]]},
            formula_universe=[[True, None]],
        )
    frames = _matrix_frames()
    del frames["subindustry"]
    with pytest.raises(reference.FormulaError, match="PIT subindustry"):
        reference.reference(48, frames)


def test_logical_or_uses_three_valued_alpha101_semantics():
    missing = math.nan
    result = reference._logical_or([[1.0, missing, 0.0]], [[missing, 0.0, missing]], 1, 3)
    assert result[0][0] == 1.0
    assert math.isnan(result[0][1])
    assert math.isnan(result[0][2])


def test_numerical_domains_are_nan_and_constant_correlation_is_undefined():
    invalid_range = {
        "close": [[1.0]],
        "open": [[0.9]],
        "high": [[0.0]],
        "low": [[0.001]],
    }
    assert math.isnan(reference.reference(101, invalid_range)[0][0])
    constant = {
        "open": [[1.0, 1.0] for _ in range(10)],
        "volume": [[5.0, 5.0] for _ in range(10)],
    }
    assert all(math.isnan(value) for row in reference.reference(3, constant) for value in row)

    # Exact Fraction moments keep mathematically tied Pearson results bit-equal
    # after a positive affine transform, and cross-sectional rank averages the
    # tied positions before normalizing by the full finite population.
    left = [[1.0, 1.0, 1.0], [2.0, 2.0, 2.0], [3.0, 3.0, 3.0], [4.0, 4.0, 4.0]]
    right = [[0.0, 10.0, 4.0], [1.0, 12.0, 3.0], [0.0, 10.0, 4.0], [1.0, 12.0, 3.0]]
    covariance = reference._pair_rolling(left, right, 4, covariance=True)[-1]
    correlation = reference._pair_rolling(left, right, 4, covariance=False)[-1]
    assert covariance == [0.25, 0.5, -0.25]
    assert correlation[0] == correlation[1]
    assert correlation[2] == -correlation[0]
    assert reference._rank(correlation) == [5.0 / 6.0, 5.0 / 6.0, 1.0 / 3.0]


def test_each_call_observes_mutated_input_instead_of_a_cross_call_result_cache():
    frames = {"close": [[2.0]], "open": [[1.0]], "high": [[3.0]], "low": [[0.0]]}
    first = reference.reference(101, frames)[0][0]
    frames["close"][0][0] = 1.0
    second = reference.reference(101, frames)[0][0]
    assert first != second
