"""Panel -> fincore evaluation integration, without the deleted dataset layer."""

from __future__ import annotations

import copy
import math

import pandas as pd
import pytest

from backtrader.errors import DependencyError, ResearchConfigError
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


def test_missing_fincore_research_api_is_a_typed_dependency_error(monkeypatch):
    from backtrader.research import fincore_adapter

    monkeypatch.setattr(
        fincore_adapter, "_RESEARCH_MODULE", "fincore.factor_analysis.__missing_research__"
    )
    with pytest.raises(DependencyError) as caught:
        fincore_adapter.evaluate_frames(_panel(), _spec())
    assert caught.value.code == "DEPENDENCY_UNAVAILABLE"


def test_evaluation_does_not_mutate_panel_frames_indexes_or_attrs():
    pytest.importorskip("fincore.factor_analysis.research")
    panel = _panel()
    panel.factors.attrs["caller_metadata"] = {"tags": ["keep"]}
    frames = {
        name: getattr(panel, name)
        for name in ("factors", "grid", "prices_open", "prices_close", "universe")
        if isinstance(getattr(panel, name, None), pd.DataFrame)
    }
    snapshots = {
        name: (frame.copy(deep=True), frame.index, copy.deepcopy(frame.attrs))
        for name, frame in frames.items()
    }

    try:
        result = evaluate_frames(panel, _spec())
    except DependencyError as exc:
        pytest.skip("fincore research API unavailable: %s" % exc)

    assert result.status in ("OK", "PARTIAL")
    for name, frame in frames.items():
        values, original_index, attrs = snapshots[name]
        assert frame.equals(values), name
        assert frame.index is original_index, name
        assert frame.attrs == attrs, name


def test_unused_multiindex_levels_are_canonicalized_without_panel_mutation(monkeypatch):
    research = pytest.importorskip("fincore.factor_analysis.research")
    from backtrader.research import fincore_adapter

    panel = _panel()
    try:
        clean_result = evaluate_frames(panel, _spec())
    except DependencyError as exc:
        pytest.skip("fincore research API unavailable: %s" % exc)

    index = panel.factors.index
    clean_index = index
    expanded_levels = [
        index.levels[0].append(pd.DatetimeIndex(["2030-01-01"], tz="UTC", name="time")),
        index.levels[1].append(pd.Index(["UNUSED"], name="asset")),
    ]
    panel.factors.index = pd.MultiIndex(
        levels=expanded_levels,
        codes=[codes.copy() for codes in index.codes],
        names=index.names,
        verify_integrity=False,
    )
    original_index = panel.factors.index
    original_factors = panel.factors.copy(deep=True)
    original_attrs = copy.deepcopy(panel.factors.attrs)
    original_evaluate = research.evaluate_factor_research
    received_indices = []

    def capture_evaluate(
        factors,
        *,
        grid,
        prices,
        universe,
        groups,
        precomputed_returns,
        spec,
    ):
        received_indices.append(factors.index)
        return original_evaluate(
            factors,
            grid=grid,
            prices=prices,
            universe=universe,
            groups=groups,
            precomputed_returns=precomputed_returns,
            spec=spec,
        )

    monkeypatch.setattr(fincore_adapter, "_import_research_module", lambda: research)
    monkeypatch.setattr(research, "evaluate_factor_research", capture_evaluate)
    result = evaluate_frames(panel, _spec())

    assert len(received_indices) == 1
    received_index = received_indices[0]
    assert len(received_index.levels[0]) == len(clean_index.levels[0])
    assert len(received_index.levels[1]) == len(clean_index.levels[1])
    assert received_index.to_list() == clean_index.to_list()
    assert result.manifest["result_fingerprint"] == clean_result.manifest["result_fingerprint"]
    assert panel.factors.equals(original_factors)
    assert panel.factors.index is original_index
    assert panel.factors.attrs == original_attrs


def test_multi_factor_directions_are_applied_independently():
    pytest.importorskip("fincore.factor_analysis.research")
    source = _panel()
    factors = source.factors.copy(deep=True)
    factors["beta"] = factors["alpha"] * 2.0 + 1.0
    panel = FactorPanel(
        factors=factors,
        grid=source.grid,
        prices_open=source.prices_open,
        prices_close=source.prices_close,
        universe=source.universe,
        start=source.start,
        end=source.end,
        target_order=source.target_order,
        factor_order=("alpha", "beta"),
        directions={"alpha": -1, "beta": 1},
        groups=source.groups,
    )
    original_factors = panel.factors.copy(deep=True)
    original_index = panel.factors.index
    original_attrs = copy.deepcopy(panel.factors.attrs)

    try:
        result = evaluate_frames(panel, _spec())
    except DependencyError as exc:
        pytest.skip("fincore research API unavailable: %s" % exc)

    assert set(result.signals["factor"]) == {"alpha", "beta"}
    assert result.signals.groupby("factor")["direction"].first().to_dict() == {
        "alpha": -1,
        "beta": 1,
    }
    for name, direction in (("alpha", -1), ("beta", 1)):
        actual = (
            result.signals.loc[result.signals["factor"] == name]
            .set_index(["time", "asset"])["value"]
            .sort_index()
        )
        expected = panel.factors[name].mul(direction).sort_index()
        pd.testing.assert_series_equal(actual, expected, check_names=False)
    assert panel.factors.equals(original_factors)
    assert panel.factors.index is original_index
    assert panel.factors.attrs == original_attrs


def test_precomputed_label_is_rejected_without_a_precomputed_returns_frame(monkeypatch):
    research = pytest.importorskip("fincore.factor_analysis.research")
    from backtrader.research import fincore_adapter

    def unexpected_evaluate(
        factors,
        *,
        grid,
        prices,
        universe,
        groups,
        precomputed_returns,
        spec,
    ):
        pytest.fail("the adapter must reject precomputed labels before evaluation")

    monkeypatch.setattr(fincore_adapter, "_import_research_module", lambda: research)
    monkeypatch.setattr(research, "evaluate_factor_research", unexpected_evaluate)

    with pytest.raises(ResearchConfigError) as caught:
        evaluate_frames(_panel(), {**_spec(), "label": "precomputed"})

    assert caught.value.code == "missing_precomputed_returns"


def test_missing_turnover_capability_rejects_legacy_fincore(monkeypatch):
    research = pytest.importorskip("fincore.factor_analysis.research")
    from backtrader.research import fincore_adapter

    capabilities = research.research_capabilities()
    capabilities["result_tables"] = tuple(
        name for name in capabilities["result_tables"] if name != "turnover"
    )
    monkeypatch.setattr(research, "research_capabilities", lambda: capabilities)
    monkeypatch.setattr(fincore_adapter, "_import_research_module", lambda: research)

    with pytest.raises(DependencyError) as caught:
        evaluate_frames(_panel(), _spec())

    assert caught.value.code == "DEPENDENCY_UNAVAILABLE"
    assert "result_tables" in str(caught.value)
