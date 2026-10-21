"""Real installed-fincore API contract; run only in the pinned integration venv."""

import importlib
import os
import sys

import numpy as np
import pandas as pd
import pytest

from backtrader.research import ResearchDataset, evaluate_dataset, load_dataset


if os.environ.get("BT_FACTOR_RESEARCH_RUN_INSTALLED_INTEGRATION") != "1":
    pytestmark = pytest.mark.skip(
        reason="requires the root-pinned, installed fincore development wheel"
    )


def _known_dataset():
    times = pd.date_range("2024-03-01T00:00:00Z", periods=4, freq="D", name="close_time")
    assets = ("A", "B", "C", "D")
    grid = pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times)
    research_times = times[:3]
    panel_index = pd.MultiIndex.from_product([research_times, assets], names=("time", "asset"))
    raw_factors = pd.DataFrame(
        {"alpha": np.tile(np.arange(1.0, 5.0), len(research_times))},
        index=panel_index,
    )
    availability = pd.DataFrame(
        {
            "ready": True,
            "valid": True,
            "reason": "READY",
            "available_at": [time for time, _ in panel_index],
            "input_times": [{"target_close": time} for time, _ in panel_index],
        },
        index=pd.MultiIndex.from_tuples(
            [(time, asset, "alpha") for time, asset in panel_index],
            names=("time", "asset", "factor"),
        ),
    )
    close_values = np.asarray(
        [
            [100.0, 100.0, 100.0, 100.0],
            [101.0, 102.0, 103.0, 104.0],
            [102.01, 104.04, 106.09, 108.16],
            [103.0301, 106.1208, 109.2727, 112.4864],
        ]
    )
    prices = {
        "open": pd.DataFrame(close_values * 0.99, index=times, columns=assets),
        "close": pd.DataFrame(close_values, index=times, columns=assets),
    }
    universe_index = pd.MultiIndex.from_product([research_times, assets], names=("time", "asset"))
    formula_index = pd.MultiIndex.from_product([times[:3], assets], names=("time", "asset"))
    research = {
        "grid": grid,
        "start": research_times[0],
        "end": research_times[-1],
        "targets": assets,
        "source_timezone": "UTC",
        "snapshot_id": "hand-computed-monotonic-labels-v1",
        "price_basis": "synthetic-unadjusted-usd",
        "calendar_id": "integration-daily-grid-v1",
        "frequency": "1session",
        "feed_time_kind": "close_time",
        "groups": {asset: "US" for asset in assets},
        "universe": pd.Series(True, index=universe_index, name="eligible"),
        "formula_universe": pd.Series(True, index=formula_index, name="eligible"),
        "formula_fields": {},
        "classifications": {},
    }
    return ResearchDataset.from_collection(
        research=research,
        raw_factors=raw_factors,
        availability=availability,
        prices=prices,
        provenance={"factor_directions": {"alpha": 1}},
    )


def test_installed_fincore_evaluates_saved_snapshot_against_hand_result(tmp_path):
    module = importlib.import_module("fincore.factor_analysis.research")
    module_path = os.path.realpath(module.__file__).lower()
    assert "site-packages" in module_path or "dist-packages" in module_path
    assert (
        os.path.commonpath([os.path.realpath(sys.prefix).lower(), module_path])
        == os.path.realpath(sys.prefix).lower()
    )
    if os.environ.get("BT_FACTOR_RESEARCH_REQUIRE_INSTALLED_BACKTRADER") == "1":
        backtrader_module = importlib.import_module("backtrader")
        backtrader_path = os.path.realpath(backtrader_module.__file__).lower()
        assert (
            os.path.commonpath([os.path.realpath(sys.prefix).lower(), backtrader_path])
            == os.path.realpath(sys.prefix).lower()
        )

    collected = _known_dataset()
    saved_path = tmp_path / "research-snapshot"
    collected.save(saved_path)
    dataset = load_dataset(saved_path)
    assert dataset.dataset_id == collected.dataset_id

    result = evaluate_dataset(
        dataset,
        label="close_to_close",
        periods=(1,),
        quantiles=2,
        min_assets=4,
        min_quantile_assets=1,
        max_loss=1.0,
        stability_lags=(1,),
    )
    assert result.status == "PARTIAL"
    first_period_stability = result.stability.loc[result.stability["time"] == dataset.start]
    later_stability = result.stability.loc[result.stability["time"] > dataset.start]
    assert not first_period_stability.empty
    assert set(first_period_stability["reason"].dropna()) == {"INSUFFICIENT_HISTORY"}
    assert first_period_stability["status"].eq("UNEVALUABLE").all()
    assert later_stability["status"].eq("OK").all()
    assert {"metric", "value", "record_type"}.issubset(result.ic.columns)
    period_ic = result.ic.loc[result.ic["record_type"] == "period"]
    assert {"pearson", "spearman"}.issubset(set(period_ic["metric"]))
    assert np.allclose(period_ic["value"].dropna().to_numpy(), 1.0)
    assert "value" in result.labels.columns
    expected = np.asarray([0.01, 0.02, 0.03, 0.04])
    observed = result.labels["value"].dropna().to_numpy()
    assert len(observed) == 12
    assert np.allclose(np.sort(observed.reshape(3, 4), axis=1), expected)
    assert result.manifest["dataset_id"] == dataset.dataset_id
