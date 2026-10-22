"""Paper-versus-recipe regressions discovered while promoting Alpha101."""

import json
import math
from pathlib import Path

import pytest

from backtrader.research.alpha101 import ALPHA_REGISTRY, Alpha067Native
from tests.test_utils.alpha101_full_reference import formula_source, history_h, reference
from tests.unit.test_factor_research_representatives import _frames, _run_subset


def test_production_equations_and_independent_history_ledger():
    for alpha_id, factor in ALPHA_REGISTRY.items():
        assert factor.formula == formula_source(alpha_id)
        assert factor.lookback_h == history_h(alpha_id)
    path = (
        Path(__file__).resolve().parents[2]
        / "docs/_internal/opts/requirements/迭代46-Alpha101原生因子实现/生产因子台账.json"
    )
    rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
    assert [row["alpha_id"] for row in rows] == list(range(1, 102))
    for row in rows:
        alpha_id = row["alpha_id"]
        assert row["paper_formula"] == formula_source(alpha_id)
        assert row["independent_H_grid_bars"] == history_h(alpha_id)


@pytest.mark.parametrize("runonce", (False, True))
def test_alpha067_has_no_rank_after_ordinary_power(runonce):
    frames = _frames(periods=48)
    expected = reference(67, frames)
    h = history_h(67)
    strategy = _run_subset(frames, {"alpha67": Alpha067Native}, runonce=runonce)
    raw = strategy.get_panel().factors
    factor = strategy.factor_instances["alpha67"]
    assets = tuple(frames)
    grid = next(iter(frames.values())).index
    wrong_rank_witnesses = 0
    finite = 0
    for offset, point in enumerate(grid):
        valid = [value for value in expected[offset] if math.isfinite(value)]
        for column, asset in enumerate(assets):
            wanted = expected[offset][column] if offset >= h else math.nan
            got = float(raw.at[(point, asset), "alpha67"])
            if math.isnan(wanted):
                assert math.isnan(got)
                continue
            finite += 1
            assert abs(got - wanted) <= 1e-12 + 1e-10 * abs(wanted)
            # Ranking the positive power and then negating loses the actual
            # magnitude. Compute that wrong alternative independently.
            positive = -wanted
            powers = [-value for value in valid]
            wrong = -(
                1
                + sum(value < positive for value in powers)
                + (sum(value == positive for value in powers) - 1) / 2
            ) / len(powers)
            wrong_rank_witnesses += abs(wanted - wrong) > 1e-8
    assert finite > 0
    assert wrong_rank_witnesses > 0
    assert factor.lifecycle_diagnostics["call_count"] == len(grid)
    assert factor.lifecycle_diagnostics["grid_matches"]
