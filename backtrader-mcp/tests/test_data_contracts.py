from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backtrader_mcp.errors import Forbidden, InvalidRequest
from backtrader_mcp.util import sha256_json


def test_dataset_register_preview_derive_and_confinement(service_env):
    service, _, _ = service_env
    inspected = service.inspect_dataset("market", "prices.csv")
    assert inspected["columns"] == ["datetime", "open", "high", "low", "close", "volume"]
    mapping = {
        "datetime": "datetime",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    }
    dataset = service.register_dataset("market", "prices.csv", mapping)
    assert dataset["schema_version"] == "dataset-manifest-v1"
    assert re.fullmatch(r"ds_[0-9a-f]{64}", dataset["dataset_id"])
    assert dataset["dataset_id"] == f"ds_{dataset['semantic_hash']}"
    assert dataset["feeds"][0]["name"] == "primary"
    assert dataset["status"] == "valid"
    assert dataset["alignment"] == {"mode": "intersection", "minimum_overlap": 1.0}
    assert dataset["manifest_hash"] == sha256_json(
        {key: value for key, value in dataset.items() if key != "manifest_hash"}
    )
    assert service.preview_dataset(dataset["dataset_id"], 3)["rows"][0]["openinterest"] == "0"
    derived = service.derive_tabular_dataset(
        dataset["dataset_id"],
        "sma",
        {"column": "close", "period": 3, "output": "close_sma"},
        dataset["manifest_hash"],
    )
    assert derived["dataset_id"] != dataset["dataset_id"]
    assert "close_sma" in derived["extensions"]["columns"]
    with pytest.raises(InvalidRequest):
        service.derive_tabular_dataset(dataset["dataset_id"], "identity", {}, "0" * 64)
    with pytest.raises(Forbidden):
        service.inspect_dataset("market", "../outside.csv")


def test_canonical_schemas_and_comparison_policy_are_real_files():
    package = Path(__file__).resolve().parents[1] / "src" / "backtrader_mcp"
    schema_names = {
        "strategy-spec",
        "dataset-manifest",
        "corpus-manifest",
        "artifact-manifest",
        "validation-report",
        "run-manifest",
        "run-result",
    }
    for name in schema_names:
        value = json.loads((package / "schemas" / f"{name}.schema.json").read_text())
        assert value["$schema"].endswith("2020-12/schema")
        assert value["required"]
    dataset_schema = json.loads((package / "schemas" / "dataset-manifest.schema.json").read_text())
    assert set(
        ["schema_version", "spec_hash", "feeds", "master_feed", "alignment", "transforms"]
    ) == set(dataset_schema["$defs"]["DataSpec"]["required"])
    profile = json.loads((package / "policies" / "comparison-profile-v1.json").read_text())
    assert profile["profile_version"] == "comparison-profile-v1"
    assert profile["nullable_metrics"] == ["sharpe_ratio", "annual_return"]
    assert len(profile["integer_metrics"]) == 6
    assert len(profile["float_metrics"]) == 5


def test_typed_multi_feed_data_spec_registration_and_materialization(service_env):
    service, source, _ = service_env
    second = source / "second.csv"
    second.write_bytes((source / "prices.csv").read_bytes())
    feeds = []
    for name, role, relative in (
        ("primary", "execution", "prices.csv"),
        ("secondary", "signal", "second.csv"),
    ):
        feeds.append(
            {
                "name": name,
                "role": role,
                "symbol": name.upper(),
                "source": {
                    "root_id": "market",
                    "relative_path": relative,
                    "source_type": "local_file",
                },
                "format": "generic_csv",
                "timeframe": "days",
                "timezone": "UTC",
                "columns": {
                    "datetime": "datetime",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                },
            }
        )
    core = {
        "schema_version": "data-spec-v1",
        "feeds": feeds,
        "master_feed": "primary",
        "alignment": {"mode": "intersection", "minimum_overlap": 1.0},
        "transforms": [],
    }
    manifest = service.register_local_dataset({**core, "spec_hash": sha256_json(core)})
    assert [feed["name"] for feed in manifest["feeds"]] == ["primary", "secondary"]
    assert set(manifest["extensions"]["feed_objects"]) == {"primary", "secondary"}
    materialized = service.datasets.materialization(manifest["dataset_id"])
    assert [feed["name"] for feed in materialized["feeds"]] == ["primary", "secondary"]
    assert all(feed["input_format"] == "generic_csv" for feed in materialized["feeds"])
    assert all(
        feed["adapter"] == "backtrader.feeds.GenericCSVData" for feed in materialized["feeds"]
    )
    assert all(feed["bar_operation"] == {"mode": "direct"} for feed in materialized["feeds"])


@pytest.mark.parametrize(
    ("source_type", "relative_path"),
    [
        ("local_file", "prices.csv"),
        ("materialized_dataframe", "prices.pkl"),
    ],
)
def test_pandas_adapter_accepts_only_materialized_csv(
    service_env, source_type: str, relative_path: str
):
    service, source, _ = service_env
    if relative_path.endswith(".pkl"):
        (source / relative_path).write_text("not a pickle", encoding="utf-8")
    feed = {
        "name": "primary",
        "role": "execution",
        "symbol": "PRIMARY",
        "source": {
            "root_id": "market",
            "relative_path": relative_path,
            "source_type": source_type,
        },
        "format": "pandas",
        "timeframe": "days",
        "timezone": "UTC",
        "columns": {
            "datetime": "datetime",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        },
    }
    core = {
        "schema_version": "data-spec-v1",
        "feeds": [feed],
        "master_feed": "primary",
        "alignment": {"mode": "intersection", "minimum_overlap": 1.0},
        "transforms": [],
    }
    with pytest.raises(InvalidRequest):
        service.register_local_dataset({**core, "spec_hash": sha256_json(core)})
