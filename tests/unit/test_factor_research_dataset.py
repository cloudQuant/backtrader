"""Focused contracts for immutable, fincore-free research snapshots."""

import json
import sys
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backtrader.research.dataset import ResearchDataset
from backtrader.research.specs import ResearchSpec
from backtrader.research.errors import (
    ConfigError,
    DataQualityError,
    DatasetError,
    DependencyError,
    FactorComputationError,
)
from backtrader.research import storage
from backtrader.research.storage import load_dataset


def _sample_dataset():
    times = pd.date_range("2024-01-01T00:00:00Z", periods=5, freq="D", name="close_time")
    grid = pd.DataFrame(
        {"open_time": times - pd.Timedelta(hours=6)},
        index=times,
    )
    targets = ("B", "A")
    start, end = times[1], times[3]
    panel_index = pd.MultiIndex.from_product([times[1:4], targets], names=["time", "asset"])
    values = [1.2345678901234567, 2.0, 3.0, np.nan, 5.0, 6.0]
    raw_factors = pd.DataFrame({"signal": values}, index=panel_index)
    availability_rows = []
    for time, asset in panel_index:
        value = raw_factors.at[(time, asset), "signal"]
        missing = pd.isna(value)
        availability_rows.append(
            {
                "time": time,
                "asset": asset,
                "factor": "signal",
                "ready": not missing,
                "valid": not missing,
                "reason": "NO_CURRENT_BAR" if missing else "READY",
                "input_times": {"target_close": time} if not missing else {"target_close": None},
                "available_at": pd.NaT if missing else time,
            }
        )
    availability = pd.DataFrame(availability_rows).set_index(["time", "asset", "factor"])
    universe = pd.Series(True, index=panel_index, name="eligible")
    formula_index = pd.MultiIndex.from_product(
        [times[times <= end], targets], names=["time", "asset"]
    )
    formula_universe = pd.Series(True, index=formula_index, name="eligible")
    research = SimpleNamespace(
        grid=grid,
        start=start,
        end=end,
        targets=targets,
        source_timezone="UTC",
        snapshot_id="sample-v1",
        price_basis="synthetic-unadjusted-usd",
        calendar_id="sample-calendar-v1",
        frequency="1session",
        feed_time_kind="close_time",
        groups={"A": "same", "B": "same"},
        universe=universe,
        formula_universe=formula_universe,
        formula_fields={},
        classifications={},
    )
    prices = {
        "open": pd.DataFrame({"A": [10, 11, 12, 13, 14], "B": [20, 21, 22, 23, 24]}, index=times),
        "close": pd.DataFrame(
            {"A": [10.5, 11.5, 12.5, 13.5, 14.5], "B": [20.5, 21.5, 22.5, 23.5, 24.5]},
            index=times,
        ),
    }
    return ResearchDataset.from_collection(
        research=research,
        raw_factors=raw_factors,
        availability=availability,
        prices=prices,
        provenance={
            "factor_directions": {"signal": -1},
            "factor_definitions": {"signal": "fixture-v1"},
        },
    )


def _fake_research_module(calls):
    from backtrader.research.fincore_adapter import _REQUIRED_METRICS, _REQUIRED_TABLES

    def normalize(values):
        calls["normalized"] = dict(values)
        return SimpleNamespace(**values)

    def evaluate(
        factors,
        *,
        grid,
        prices=None,
        universe=None,
        groups=None,
        precomputed_returns=None,
        spec,
    ):
        calls["evaluation"] = {
            "factors": factors,
            "grid": grid,
            "prices": prices,
            "universe": universe,
            "groups": groups,
            "precomputed_returns": precomputed_returns,
            "spec": spec,
        }
        tables = {name: pd.DataFrame() for name in _REQUIRED_TABLES}
        return SimpleNamespace(
            manifest={},
            status="OK",
            to_serializable=dict,
            export=lambda *args, **kwargs: None,
            **tables,
        )

    capabilities = {
        "api_version": "1.0",
        "result_schema_version": 1,
        "evaluation_config_schema_version": 1,
        "python_min": "3.11",
        "entrypoint": "fincore.factor_analysis.research.evaluate_factor_research",
        "spec": "fincore.factor_analysis.research.ResearchEvaluationSpec",
        "normalizer": "fincore.factor_analysis.research.normalize_research_evaluation_spec",
        "labels": ("close_to_close", "next_open_to_open", "precomputed"),
        "preprocess": ("cross_section_rank", "cross_section_zscore"),
        "metrics": tuple(_REQUIRED_METRICS),
        "result_tables": tuple(_REQUIRED_TABLES),
        "export_formats": ("json", "csv"),
        "charts_supported": True,
    }
    return SimpleNamespace(
        ConfigError=ConfigError,
        DatasetError=DatasetError,
        DependencyError=DependencyError,
        DataQualityError=DataQualityError,
        FactorComputationError=FactorComputationError,
        ResearchEvaluationSpec=type("ResearchEvaluationSpec", (), {}),
        normalize_research_evaluation_spec=normalize,
        research_capabilities=lambda: capabilities,
        evaluate_factor_research=evaluate,
    )


def test_dataset_keeps_full_grid_and_research_panel_is_defensive_copy():
    dataset = _sample_dataset()

    assert len(dataset.grid) == 5
    assert len(dataset.raw_factors) == 6
    assert dataset.raw_factors.index.get_level_values("time").min() == dataset.start
    assert dataset.raw_factors.index.get_level_values("time").max() == dataset.end
    missing_time = dataset.start + pd.Timedelta(days=1)
    assert pd.isna(dataset.raw_factors.at[(missing_time, "A"), "signal"])
    assert dataset.availability.loc[(missing_time, "A", "signal"), "reason"] == "NO_CURRENT_BAR"
    assert len(dataset.prices["open"]) == 5
    assert dataset.groups == {"A": "same", "B": "same"}

    exposed = dataset.raw_factors
    exposed.iloc[0, 0] = -999.0
    assert dataset.raw_factors.iloc[0, 0] != -999.0
    availability = dataset.availability
    key = availability.index[0]
    availability.at[key, "input_times"]["target_close"] = "mutated"
    assert dataset.availability.at[key, "input_times"]["target_close"] != "mutated"
    with pytest.raises(AttributeError, match="immutable"):
        dataset._dataset_id = "changed"
    assert not hasattr(dataset, "__dict__")


def test_storage_roundtrip_is_deterministic_and_keeps_float64(tmp_path):
    dataset = _sample_dataset()
    assert "fincore.factor_analysis.research" not in sys.modules

    destination = tmp_path / "snapshot"
    dataset.save(destination)
    loaded = load_dataset(destination)

    assert loaded.dataset_id == dataset.dataset_id
    assert loaded.raw_factors.equals(dataset.raw_factors)
    assert loaded.prices["close"].equals(dataset.prices["close"])
    assert loaded.availability.equals(dataset.availability)
    assert loaded.metadata == dataset.metadata
    exact = loaded.raw_factors.at[(dataset.start, "B"), "signal"]
    assert exact == 1.2345678901234567
    manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["complete"] is True
    assert manifest["dataset_id"] == dataset.dataset_id
    factors_payload = (destination / "factors.csv").read_bytes()
    assert b"\r\n" not in factors_payload
    assert b"NaN" not in factors_payload and b"Infinity" not in factors_payload
    assert b",A,\n" in factors_payload
    assert not list(destination.rglob("*.pkl"))

    with pytest.raises(DatasetError, match="overwrite"):
        dataset.save(destination)


def test_formula_input_source_metadata_is_hashed_and_roundtrips(tmp_path):
    def with_source_metadata(source_version):
        base = _sample_dataset()
        index = base.raw_factors.index
        values = pd.DataFrame(
            {
                "value": np.arange(1.0, len(index) + 1.0),
                "available_at": index.get_level_values("time"),
                "data_version": "table-rows-v1",
            },
            index=index,
        )
        values.attrs["source_metadata"] = {
            "name": "adv20",
            "semantic": "average_daily_dollar_volume",
            "unit": "USD",
            "currency": "USD",
            "window": 20,
            "complete_window": True,
            "source_version": source_version,
            "provenance_source_lookback_grid_bars": 19,
        }
        return (
            ResearchDataset(
                base.grid,
                base.raw_factors,
                base.availability,
                start=base.start,
                end=base.end,
                targets=base.targets,
                groups=base.groups,
                universe=base.universe,
                formula_universe=base.formula_universe,
                formula_inputs={"adv20": values},
                provenance=base.metadata["provenance"],
            ),
            values,
        )

    snapshot, source_table = with_source_metadata("vendor-snapshot-v1")
    expected_metadata = dict(source_table.attrs["source_metadata"])
    source_table.attrs["source_metadata"]["source_version"] = "mutated-after-seal"
    assert snapshot.formula_inputs["adv20"].attrs["source_metadata"] == expected_metadata

    exposed = snapshot.formula_inputs["adv20"]
    exposed.attrs["source_metadata"]["source_version"] = "mutated-public-copy"
    assert snapshot.formula_inputs["adv20"].attrs["source_metadata"] == expected_metadata

    changed_snapshot, _ = with_source_metadata("vendor-snapshot-v2")
    assert changed_snapshot.dataset_id != snapshot.dataset_id

    destination = tmp_path / "source-metadata"
    snapshot.save(destination)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == storage.SCHEMA_VERSION
    assert (
        manifest["tables"]["formula_inputs:adv20"]["attrs"]["source_metadata"] == expected_metadata
    )
    loaded = load_dataset(destination)
    assert loaded.dataset_id == snapshot.dataset_id
    assert loaded.formula_inputs["adv20"].attrs["source_metadata"] == expected_metadata

    manifest["tables"]["formula_inputs:adv20"]["attrs"]["source_metadata"][
        "source_version"
    ] = "tampered"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DatasetError, match="content identity"):
        load_dataset(destination)


def test_research_spec_preserves_formula_source_metadata_through_collection():
    base = _sample_dataset()
    source_table = pd.DataFrame(
        {
            "value": np.arange(1.0, len(base.raw_factors) + 1.0),
            "available_at": base.raw_factors.index.get_level_values("time"),
            "data_version": "table-rows-v1",
        },
        index=base.raw_factors.index,
    )
    source_table.attrs["source_metadata"] = {
        "name": "adv20",
        "semantic": "average_daily_dollar_volume",
        "unit": "USD",
        "currency": "USD",
        "window": 20,
        "complete_window": True,
        "source_version": "vendor-snapshot-v1",
        "provenance_source_lookback_grid_bars": 19,
    }
    expected_metadata = dict(source_table.attrs["source_metadata"])
    research = ResearchSpec(
        grid=base.grid,
        start=base.start,
        end=base.end,
        targets=base.targets,
        source_timezone="UTC",
        snapshot_id="spec-source-metadata-v1",
        price_basis="synthetic-unadjusted-usd",
        calendar_id="sample-calendar-v1",
        frequency="1session",
        groups=base.groups,
        universe=base.universe,
        formula_universe=base.formula_universe,
        formula_fields={"adv20": source_table},
    )

    source_table.attrs["source_metadata"]["source_version"] = "mutated-after-spec"
    assert research.formula_fields["adv20"].attrs["source_metadata"] == expected_metadata

    collected = ResearchDataset.from_collection(
        research=research,
        raw_factors=base.raw_factors,
        availability=base.availability,
        prices=base.prices,
        provenance=base.metadata["provenance"],
    )
    assert collected.formula_inputs["adv20"].attrs["source_metadata"] == expected_metadata


@pytest.mark.parametrize("failure", ("payload_write", "publish_rename"))
def test_save_failure_does_not_publish_or_leave_a_temporary_dataset(tmp_path, monkeypatch, failure):
    dataset = _sample_dataset()
    destination = tmp_path / failure

    if failure == "payload_write":
        original_open = storage.Path.open

        class FailingWriter:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def write(self, value):
                raise OSError("injected payload write failure")

        def fail_payload_write(path, mode="r", *args, **kwargs):
            if path.name == "factors.csv" and mode == "wb":
                return FailingWriter()
            return original_open(path, mode, *args, **kwargs)

        monkeypatch.setattr(storage.Path, "open", fail_payload_write)
    else:

        def fail_publish(source, target):
            raise OSError("injected atomic publish failure")

        monkeypatch.setattr(storage.os, "replace", fail_publish)

    with pytest.raises(OSError):
        dataset.save(destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".%s.tmp-*" % failure))


def test_load_rejects_explicit_incomplete_manifest(tmp_path):
    destination = tmp_path / "incomplete"
    _sample_dataset().save(destination)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["complete"] = False
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(DatasetError, match="incomplete"):
        load_dataset(destination)


def test_evaluate_dataset_accepts_keyword_config_and_routes_base_direction(monkeypatch):
    from backtrader.research import fincore_adapter

    dataset = _sample_dataset()
    calls = {}
    monkeypatch.setattr(
        fincore_adapter, "_import_research_module", lambda: _fake_research_module(calls)
    )

    result = dataset.evaluate(label="close_to_close", periods=(1,), quantiles=2)

    assert result.status == "OK"
    assert calls["normalized"]["label"] == "close_to_close"
    assert calls["normalized"]["periods"] == (1,)
    evaluation = calls["evaluation"]
    assert evaluation["factors"].attrs["factor_directions"] == {"signal": -1}
    assert evaluation["prices"] is not None
    assert evaluation["precomputed_returns"] is None

    fincore_adapter.evaluate_dataset(dataset, {"label": "next_open_to_open", "periods": (5,)})
    assert calls["normalized"]["label"] == "next_open_to_open"
    assert calls["normalized"]["periods"] == (5,)

    @dataclass(frozen=True)
    class EvaluationConfig:
        label: str
        periods: tuple

    dataset.evaluate(EvaluationConfig("close_to_close", (20,)))
    assert calls["normalized"]["label"] == "close_to_close"
    assert calls["normalized"]["periods"] == (20,)


def test_fincore_adapter_drops_only_datetime_index_frequency():
    from backtrader.research import fincore_adapter

    times = pd.date_range("2024-01-01T00:00:00Z", periods=3, freq="D", name="time")
    panel_index = pd.MultiIndex.from_product([times, ("A", "B")], names=("time", "asset"))
    source_grid = pd.DataFrame({"value": [1, 2, 3]}, index=times)
    source_factors = pd.DataFrame({"signal": np.arange(6.0)}, index=panel_index)
    source_factors.attrs["fixture"] = {"kept": True}
    source_universe = pd.Series(True, index=panel_index, name="eligible")

    assert source_grid.index.freq is not None
    assert source_factors.index.levels[0].freq is not None
    assert source_universe.index.levels[0].freq is not None

    grid_copy = source_grid.copy(deep=True)
    factors_copy = source_factors.copy(deep=True)
    universe_copy = source_universe.copy(deep=True)
    grid = fincore_adapter._drop_datetime_index_frequency(grid_copy, pd)
    factors = fincore_adapter._drop_datetime_index_frequency(factors_copy, pd)
    universe = fincore_adapter._drop_datetime_index_frequency(universe_copy, pd)

    pd.testing.assert_frame_equal(source_grid, grid, check_freq=False)
    pd.testing.assert_frame_equal(source_factors, factors, check_freq=False)
    pd.testing.assert_series_equal(source_universe, universe, check_freq=False)
    assert grid.index.freq is None
    assert factors.index.levels[0].freq is None
    assert universe.index.levels[0].freq is None
    assert factors.attrs == source_factors.attrs == {"fixture": {"kept": True}}
    assert source_grid.index.freq is not None
    assert source_factors.index.levels[0].freq is not None
    assert source_universe.index.levels[0].freq is not None


def test_evaluate_dataset_rejects_spec_and_keyword_config_together(monkeypatch):
    from backtrader.research import fincore_adapter

    def unexpected_import():
        raise AssertionError("conflicting config must fail before importing fincore")

    monkeypatch.setattr(fincore_adapter, "_import_research_module", unexpected_import)
    with pytest.raises(ConfigError) as caught:
        fincore_adapter.evaluate_dataset(
            _sample_dataset(), {"label": "close_to_close"}, periods=(1,)
        )
    assert caught.value.code == "INVALID_CONFIG"


def test_evaluate_dataset_propagates_unknown_evaluator_error_unchanged(monkeypatch):
    from backtrader.research import fincore_adapter

    module = _fake_research_module({})
    original = ValueError("unexpected evaluator failure")

    def fail(
        factors,
        *,
        grid,
        prices=None,
        universe=None,
        groups=None,
        precomputed_returns=None,
        spec,
    ):
        raise original

    module.evaluate_factor_research = fail
    monkeypatch.setattr(fincore_adapter, "_import_research_module", lambda: module)

    with pytest.raises(ValueError) as caught:
        fincore_adapter.evaluate_dataset(_sample_dataset(), label="close_to_close")

    assert caught.value is original


def test_evaluate_dataset_translates_only_declared_quality_error(monkeypatch):
    from backtrader.research import fincore_adapter

    class FincoreQualityError(Exception):
        def __init__(self):
            super().__init__("loss threshold exceeded")
            self.code = "LOSS_LIMIT_EXCEEDED"
            self.report = {"candidate_count": 20, "loss_count": 8}

    module = _fake_research_module({})
    module.DataQualityError = FincoreQualityError
    original = FincoreQualityError()

    def fail(
        factors,
        *,
        grid,
        prices=None,
        universe=None,
        groups=None,
        precomputed_returns=None,
        spec,
    ):
        raise original

    module.evaluate_factor_research = fail
    monkeypatch.setattr(fincore_adapter, "_import_research_module", lambda: module)

    with pytest.raises(DataQualityError) as caught:
        fincore_adapter.evaluate_dataset(_sample_dataset(), label="close_to_close")

    assert caught.value is not original
    assert caught.value.__cause__ is original
    assert caught.value.code == "LOSS_LIMIT_EXCEEDED"
    assert caught.value.report == original.report


def test_precomputed_return_snapshot_roundtrips_without_prices(tmp_path):
    dataset = _sample_dataset()
    times = dataset.grid.index[1:4]
    assets = dataset.targets
    index = pd.MultiIndex.from_product([times, assets, (1,)], names=("time", "asset", "horizon"))
    next_open = pd.DatetimeIndex(
        dataset.grid["open_time"].reindex(times + pd.Timedelta(days=1)).to_numpy()
    )
    entry_times = next_open.repeat(len(assets))
    exit_times = (next_open + pd.Timedelta(hours=1)).repeat(len(assets))
    precomputed = pd.DataFrame(
        {
            "value": np.tile([0.01, 0.02], len(times)),
            "entry_time": entry_times,
            "exit_time": exit_times,
            "label_id": "fixture-next-open-v1",
            "unit": "return",
            "price_semantics": "next_open_to_open",
        },
        index=index,
    )
    snapshot = ResearchDataset(
        dataset.grid,
        dataset.raw_factors,
        dataset.availability,
        start=dataset.start,
        end=dataset.end,
        targets=dataset.targets,
        universe=dataset.universe,
        groups=dataset.groups,
        formula_universe=dataset.formula_universe,
        precomputed_returns=precomputed,
        provenance=dataset.metadata["provenance"],
    )
    assert snapshot.prices == {}
    destination = tmp_path / "precomputed"
    snapshot.save(destination)
    loaded = load_dataset(destination)
    assert loaded.prices == {}
    assert loaded.precomputed_returns.equals(snapshot.precomputed_returns)
    assert (destination / "precomputed_returns.csv").is_file()


def test_load_rejects_partial_corrupt_and_unknown_schema(tmp_path):
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "factors.csv").write_text("time,asset,signal\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="manifest"):
        load_dataset(partial)

    corrupt = tmp_path / "corrupt"
    _sample_dataset().save(corrupt)
    with (corrupt / "factors.csv").open("ab") as stream:
        stream.write(b"tampered\n")
    with pytest.raises(DatasetError, match="checksum"):
        load_dataset(corrupt)

    unknown = tmp_path / "unknown"
    _sample_dataset().save(unknown)
    manifest_path = unknown / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 99
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DatasetError, match="schema version"):
        load_dataset(unknown)


@pytest.mark.parametrize("malformation", ("rows", "field_descriptor", "metadata_member"))
def test_load_normalizes_malformed_manifest_shapes_to_dataset_error(tmp_path, malformation):
    destination = tmp_path / malformation
    _sample_dataset().save(destination)
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if malformation == "rows":
        manifest["tables"]["factors"]["rows"] = "six"
    elif malformation == "field_descriptor":
        manifest["tables"]["factors"]["schema"]["columns"][0] = 17
    else:
        manifest["metadata"]["provenance"] = ["not", "a", "mapping"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DatasetError):
        load_dataset(destination)


def test_dataset_rejects_unknown_universe_cells():
    dataset = _sample_dataset()
    research = SimpleNamespace(
        grid=dataset.grid,
        start=dataset.start,
        end=dataset.end,
        targets=dataset.targets,
        source_timezone="UTC",
        snapshot_id="sample-v1",
        price_basis="synthetic-unadjusted-usd",
        calendar_id="sample-calendar-v1",
        frequency="1session",
        groups=dataset.groups,
        universe=dataset.universe.drop(dataset.universe.index[0]),
        formula_universe=dataset.formula_universe,
        formula_fields={},
        classifications={},
    )
    with pytest.raises(DatasetError) as caught:
        ResearchDataset.from_collection(
            research=research,
            raw_factors=dataset.raw_factors,
            availability=dataset.availability,
            prices=dataset.prices,
        )
    assert caught.value.code == "UNKNOWN_UNIVERSE"


def test_availability_rejects_extra_keys_unknown_reasons_and_contradictory_masks():
    dataset = _sample_dataset()
    availability = dataset.availability
    extra_key = (dataset.end + pd.Timedelta(days=1), "A", "signal")
    extra = availability.iloc[[0]].copy()
    extra.index = pd.MultiIndex.from_tuples([extra_key], names=availability.index.names)

    with pytest.raises(DatasetError) as caught:
        ResearchDataset(
            dataset.grid,
            dataset.raw_factors,
            pd.concat([availability, extra]),
            start=dataset.start,
            end=dataset.end,
            targets=dataset.targets,
            universe=dataset.universe,
            groups=dataset.groups,
            formula_universe=dataset.formula_universe,
        )
    assert caught.value.report["outside_count"] == 1

    unknown_reason = availability.copy()
    unknown_reason.iloc[0, unknown_reason.columns.get_loc("reason")] = "SILENT_DROP"
    with pytest.raises(DatasetError) as caught:
        ResearchDataset(
            dataset.grid,
            dataset.raw_factors,
            unknown_reason,
            start=dataset.start,
            end=dataset.end,
            targets=dataset.targets,
            universe=dataset.universe,
            groups=dataset.groups,
            formula_universe=dataset.formula_universe,
        )
    assert caught.value.report["unknown_reasons"] == ("SILENT_DROP",)

    contradictory = availability.copy()
    key = contradictory.index[0]
    contradictory.loc[key, "ready"] = False
    with pytest.raises(DatasetError, match="also be ready"):
        ResearchDataset(
            dataset.grid,
            dataset.raw_factors,
            contradictory,
            start=dataset.start,
            end=dataset.end,
            targets=dataset.targets,
            universe=dataset.universe,
            groups=dataset.groups,
            formula_universe=dataset.formula_universe,
        )


def test_formula_universe_unknown_is_diagnosed_not_mapped_to_ineligible():
    dataset = _sample_dataset()
    formula_universe = dataset.formula_universe.astype("boolean")
    formula_universe.iloc[0] = pd.NA
    with pytest.raises(DatasetError) as caught:
        ResearchDataset(
            dataset.grid,
            dataset.raw_factors,
            dataset.availability,
            start=dataset.start,
            end=dataset.end,
            targets=dataset.targets,
            universe=dataset.universe,
            groups=dataset.groups,
            formula_universe=formula_universe,
        )
    assert caught.value.code == "UNKNOWN_UNIVERSE"
    assert caught.value.report["unknown_count"] == 1


def test_boolean_universes_and_availability_reject_integer_flags():
    dataset = _sample_dataset()
    for name, universe in (
        ("universe", dataset.universe.astype("int64")),
        ("formula_universe", dataset.formula_universe.astype("int64")),
    ):
        with pytest.raises(DatasetError) as caught:
            ResearchDataset(
                dataset.grid,
                dataset.raw_factors,
                dataset.availability,
                start=dataset.start,
                end=dataset.end,
                targets=dataset.targets,
                universe=universe if name == "universe" else dataset.universe,
                groups=dataset.groups,
                formula_universe=(
                    universe if name == "formula_universe" else dataset.formula_universe
                ),
            )
        assert caught.value.code == "UNKNOWN_UNIVERSE"
        assert caught.value.report["invalid_type"] is True

    availability = dataset.availability
    availability["ready"] = availability["ready"].astype("int64")
    with pytest.raises(DatasetError, match="values must be booleans"):
        ResearchDataset(
            dataset.grid,
            dataset.raw_factors,
            availability,
            start=dataset.start,
            end=dataset.end,
            targets=dataset.targets,
            universe=dataset.universe,
            groups=dataset.groups,
            formula_universe=dataset.formula_universe,
        )


def test_availability_requires_timezone_aware_actual_input_times():
    dataset = _sample_dataset()
    for actual_time in (None, "2024-01-02 00:00:00", "not-a-time"):
        availability = dataset.availability
        availability.at[availability.index[0], "input_times"] = {"target_close": actual_time}
        with pytest.raises(DatasetError):
            ResearchDataset(
                dataset.grid,
                dataset.raw_factors,
                availability,
                start=dataset.start,
                end=dataset.end,
                targets=dataset.targets,
                universe=dataset.universe,
                groups=dataset.groups,
                formula_universe=dataset.formula_universe,
            )


def test_availability_preserves_missing_history_positions_on_unready_source_gaps():
    dataset = _sample_dataset()
    raw = dataset.raw_factors
    availability = dataset.availability
    key = availability.index[0]
    time = key[0]
    history = (dataset.grid.index[0], None, time)
    raw.at[(time, key[1]), key[2]] = np.nan
    availability.at[key, "ready"] = False
    availability.at[key, "valid"] = False
    availability.at[key, "reason"] = "NO_CURRENT_BAR"
    availability.at[key, "available_at"] = pd.NaT
    availability.at[key, "input_times"] = {
        "target_close": time,
        "feed:target:open": history,
    }

    collected = ResearchDataset(
        dataset.grid,
        raw,
        availability,
        start=dataset.start,
        end=dataset.end,
        targets=dataset.targets,
        universe=dataset.universe,
        groups=dataset.groups,
        formula_universe=dataset.formula_universe,
    )

    preserved = collected.availability.at[key, "input_times"]["feed:target:open"]
    assert preserved[0] == dataset.grid.index[0].isoformat().replace("+00:00", "Z")
    assert preserved[1] is None
    assert preserved[2] == time.isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize(
    ("reason", "ready", "valid"),
    (("READY", True, True), ("NONFINITE_INPUT", True, False), ("DOMAIN_ERROR", True, False)),
)
def test_availability_rejects_missing_history_positions_on_ready_outputs(reason, ready, valid):
    dataset = _sample_dataset()
    raw = dataset.raw_factors
    availability = dataset.availability
    key = availability.index[0]
    time = key[0]
    raw.at[(time, key[1]), key[2]] = 1.0 if valid else np.nan
    availability.at[key, "ready"] = ready
    availability.at[key, "valid"] = valid
    availability.at[key, "reason"] = reason
    availability.at[key, "available_at"] = time
    availability.at[key, "input_times"] = {
        "target_close": time,
        "feed:target:open": (dataset.grid.index[0], None, time),
    }

    with pytest.raises(DatasetError, match="missing input time positions"):
        ResearchDataset(
            dataset.grid,
            raw,
            availability,
            start=dataset.start,
            end=dataset.end,
            targets=dataset.targets,
            universe=dataset.universe,
            groups=dataset.groups,
            formula_universe=dataset.formula_universe,
        )


def test_availability_retains_future_publication_time_only_for_not_yet_available():
    dataset = _sample_dataset()
    raw = dataset.raw_factors
    availability = dataset.availability
    key = availability.index[0]
    time = key[0]
    future = time + pd.Timedelta(hours=3)
    raw.at[(time, key[1]), key[2]] = np.nan
    availability.at[key, "ready"] = False
    availability.at[key, "valid"] = False
    availability.at[key, "reason"] = "NOT_YET_AVAILABLE"
    availability.at[key, "available_at"] = time
    availability.at[key, "input_times"] = {"table:sales": future}
    delayed = ResearchDataset(
        dataset.grid,
        raw,
        availability,
        start=dataset.start,
        end=dataset.end,
        targets=dataset.targets,
        universe=dataset.universe,
        groups=dataset.groups,
        formula_universe=dataset.formula_universe,
    )
    assert delayed.availability.at[key, "available_at"] == time
    assert delayed.availability.at[key, "input_times"]["table:sales"] == future.isoformat().replace(
        "+00:00", "Z"
    )

    ready = dataset.availability
    ready.at[key, "available_at"] = future
    with pytest.raises(DatasetError, match="cannot be later than its grid time"):
        ResearchDataset(
            dataset.grid,
            dataset.raw_factors,
            ready,
            start=dataset.start,
            end=dataset.end,
            targets=dataset.targets,
            universe=dataset.universe,
            groups=dataset.groups,
            formula_universe=dataset.formula_universe,
        )

    ready = dataset.availability
    ready.at[key, "input_times"] = {"table:sales": future}
    with pytest.raises(DatasetError, match="input times cannot be later"):
        ResearchDataset(
            dataset.grid,
            dataset.raw_factors,
            ready,
            start=dataset.start,
            end=dataset.end,
            targets=dataset.targets,
            universe=dataset.universe,
            groups=dataset.groups,
            formula_universe=dataset.formula_universe,
        )


def test_pit_tables_preserve_schema_and_normalize_timestamp_offsets(tmp_path):
    dataset = _sample_dataset()
    times = dataset.grid.index[:2]
    source_index = pd.MultiIndex.from_product([times, ["A"]], names=["time", "asset"])
    formula_input = pd.DataFrame(
        {
            "value": [1.0, 2.0],
            "available_at": [
                times[0].isoformat(),
                (times[1] + pd.Timedelta(hours=3)).isoformat(),
            ],
            "data_version": ["source-v1", "source-v1"],
            "optional_flag": pd.Series([True, pd.NA], dtype="boolean"),
        },
        index=source_index,
    )
    classification = pd.DataFrame(
        {
            "level": ["industry", "industry"],
            "category": ["banks", "utilities"],
            "effective_at": [times[0], times[1]],
            "available_at": [times[0], times[1]],
            "taxonomy_version": ["taxonomy-v2", "taxonomy-v2"],
        },
        index=source_index,
    )
    # The source publication timestamp can be later than its observation time;
    # the retained value is normalized to UTC and is not exposed before then.
    formula_input.iloc[1, formula_input.columns.get_loc("available_at")] = (
        (times[1] + pd.Timedelta(hours=3)).tz_convert("-05:00").isoformat()
    )
    with_tables = ResearchDataset(
        dataset.grid,
        dataset.raw_factors,
        dataset.availability,
        start=dataset.start,
        end=dataset.end,
        targets=dataset.targets,
        groups=dataset.groups,
        universe=dataset.universe,
        formula_universe=dataset.formula_universe,
        formula_inputs={"sales": formula_input},
        classifications={"sector-v2": classification},
    )
    retained = with_tables.formula_inputs["sales"]
    assert retained.loc[(times[1], "A"), "available_at"] == times[1] + pd.Timedelta(hours=3)
    assert retained["available_at"].dt.tz is not None
    saved = with_tables.save(tmp_path / "pit-tables")
    loaded = load_dataset(saved)
    assert loaded.formula_inputs["sales"].equals(retained)
    assert loaded.classifications["sector-v2"].equals(with_tables.classifications["sector-v2"])
    with pytest.raises(DatasetError, match="level must be sector"):
        ResearchDataset(
            dataset.grid,
            dataset.raw_factors,
            dataset.availability,
            start=dataset.start,
            end=dataset.end,
            targets=dataset.targets,
            groups=dataset.groups,
            universe=dataset.universe,
            formula_universe=dataset.formula_universe,
            classifications={"bad-level": classification.assign(level="country")},
        )


def test_classification_categories_are_strings_or_unknown():
    dataset = _sample_dataset()
    times = dataset.grid.index[:2]
    index = pd.MultiIndex.from_product([times, ["A"]], names=["time", "asset"])
    classification = pd.DataFrame(
        {
            "level": ["industry", "industry"],
            "category": [1, "1"],
            "effective_at": times,
            "available_at": times,
            "taxonomy_version": ["taxonomy-v1", "taxonomy-v1"],
        },
        index=index,
    )
    kwargs = {
        "start": dataset.start,
        "end": dataset.end,
        "targets": dataset.targets,
        "groups": dataset.groups,
        "universe": dataset.universe,
        "formula_universe": dataset.formula_universe,
    }

    with pytest.raises(DatasetError, match="category values") as exc_info:
        ResearchDataset(
            dataset.grid,
            dataset.raw_factors,
            dataset.availability,
            classifications={"industry-taxonomy": classification},
            **kwargs,
        )
    assert exc_info.value.code == "MISSING_INPUT"

    classification["category"] = pd.Series(["banks", pd.NA], index=index, dtype=object)
    with_unknown = ResearchDataset(
        dataset.grid,
        dataset.raw_factors,
        dataset.availability,
        classifications={"industry-taxonomy": classification},
        **kwargs,
    )
    assert pd.isna(with_unknown.classifications["industry-taxonomy"].iloc[1]["category"])
