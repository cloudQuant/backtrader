"""Panel -> fincore evaluation integration, without the deleted dataset layer."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backtrader.errors import DependencyError
from backtrader.research import FactorPanel, evaluate_frames


def _panel() -> FactorPanel:
    grid = pd.date_range("2024-01-01", periods=60, freq="B", tz="UTC", name="close_time")
    grid_frame = pd.DataFrame({"open_time": grid - pd.Timedelta(hours=6)}, index=grid)
    assets = ("000001", "600000", "600519", "000002", "601318")
    index = pd.MultiIndex.from_product([grid, assets], names=("time", "asset"))
    values = []
    for step in range(60):
        for position in range(len(assets)):
            values.append(float((step * 7 + position * 3) % 11))
    factors = pd.DataFrame({"alpha": values}, index=index)
    prices = pd.DataFrame(
        [[10.0 + step + position for position in range(len(assets))] for step in range(60)],
        index=grid,
        columns=list(assets),
    )
    return FactorPanel(
        factors=factors,
        grid=grid_frame,
        prices_open=prices,
        prices_close=prices + 0.5,
        start=grid[0],
        end=grid[-1],
        target_order=assets,
        factor_order=("alpha",),
        directions={"alpha": -1},
    )


def _spec() -> dict:
    return {
        "periods": (1, 5),
        "label": "next_open_to_open",
        "preprocess": "cross_section_rank",
        "quantiles": 2,
        "min_assets": 2,
        "min_quantile_assets": 1,
        "max_loss": 1.0,
        "direction_overrides": {},
    }


def test_panel_evaluates_through_the_public_fincore_entry(tmp_path):
    pytest.importorskip("fincore.factor_analysis.research")
    panel = _panel()
    try:
        result = evaluate_frames(panel, _spec())
    except DependencyError as exc:
        pytest.skip("fincore research API unavailable: %s" % exc)
    assert result.status in ("OK", "PARTIAL")
    for name in (
        "signals",
        "labels",
        "ic",
        "ic_summary",
        "quantile_returns",
        "spreads",
        "stability",
        "correlation",
        "comparisons",
        "coverage",
        "diagnostics",
    ):
        assert isinstance(getattr(result, name), pd.DataFrame)
    assert len(result.coverage) == 1
    assert result.manifest["result_fingerprint"]
    assert len(result.manifest["result_fingerprint"]) == 64
    assert result.manifest["inputs"]["factors"]


def test_evaluation_fingerprint_is_content_bound(tmp_path):
    pytest.importorskip("fincore.factor_analysis.research")
    panel = _panel()
    try:
        first = evaluate_frames(panel, _spec())
        second = evaluate_frames(panel, _spec())
    except DependencyError as exc:
        pytest.skip("fincore research API unavailable: %s" % exc)
    assert first.manifest["result_fingerprint"] == second.manifest["result_fingerprint"]
    changed = _panel()
    changed.factors.iloc[0, 0] += 1e-9
    third = evaluate_frames(changed, _spec())
    assert third.manifest["result_fingerprint"] != first.manifest["result_fingerprint"]


def test_csv_round_trip_preserves_the_evaluation_identity(tmp_path):
    pytest.importorskip("fincore.factor_analysis.research")
    panel = _panel()
    panel.to_csv(tmp_path / "panel")
    restored = FactorPanel.from_csv(
        tmp_path / "panel",
        start=panel.start,
        end=panel.end,
        directions=panel.directions,
        target_order=panel.target_order,
        factor_order=panel.factor_order,
        groups=panel.groups,
    )
    try:
        live = evaluate_frames(panel, _spec())
        loaded = evaluate_frames(restored, _spec())
    except DependencyError as exc:
        pytest.skip("fincore research API unavailable: %s" % exc)
    assert loaded.manifest["evaluation_id"] == live.manifest["evaluation_id"]
    assert loaded.manifest["result_fingerprint"] == live.manifest["result_fingerprint"]
    assert loaded.ic.equals(live.ic)


def test_export_writes_tables_and_refuses_to_overwrite(tmp_path):
    pytest.importorskip("fincore.factor_analysis.research")
    panel = _panel()
    try:
        result = evaluate_frames(panel, _spec())
    except DependencyError as exc:
        pytest.skip("fincore research API unavailable: %s" % exc)
    target = result.export(tmp_path / "evaluation", charts=False)
    assert (target / "manifest.json").is_file()
    assert (target / "ic.csv").is_file()
    with pytest.raises(Exception):
        result.export(tmp_path / "evaluation", charts=False)
