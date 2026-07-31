import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backtrader_agent.data import DatasetService
from backtrader_agent.errors import AgentError
from backtrader_agent.roots import RootRegistry

from helpers import data_spec, write_adapter_price_csv, write_price_csv


def test_dataset_inspect_register_preview_is_stable_and_immutable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    input_root = tmp_path / "input"
    workspace.mkdir()
    input_root.mkdir()
    write_price_csv(input_root / "prices.csv")

    state_root = workspace / ".backtrader-agent"
    roots = RootRegistry(state_root)
    roots.register("workspace", workspace, writable=True, kind="workspace")
    roots.register("input", input_root, writable=False, kind="dataset")
    service = DatasetService(roots, state_root)

    inspected = service.inspect(data_spec())
    assert inspected["status"] == "valid"
    assert inspected["feeds"][0]["row_count"] == 40
    assert len(inspected["feeds"][0]["normalized_sha256"]) == 64

    registered = service.register(data_spec())
    repeated = service.register(data_spec())
    for field in (
        "schema_version",
        "dataset_id",
        "spec_hash",
        "semantic_hash",
        "manifest_hash",
        "feeds",
        "master_feed",
        "alignment",
        "status",
        "diagnostics",
        "transforms",
        "provenance",
    ):
        assert field in registered
    assert registered["dataset_id"] == "ds_" + registered["semantic_hash"]
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "src/backtrader_agent/resources/contracts/dataset-manifest-v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(registered)
    assert repeated["dataset_id"] == registered["dataset_id"]
    assert repeated["manifest_hash"] == registered["manifest_hash"]

    preview = service.preview(registered["dataset_id"], rows=2)
    assert preview["feeds"][0]["head"][0]["datetime"] == "2024-01-01T00:00:00Z"
    assert preview["feeds"][0]["tail"][-1]["close"] == "139"

    cas_relative = registered["feeds"][0]["extensions"]["backtrader_agent"]["cas_relative_path"]
    assert (state_root / cas_relative).read_bytes()


def test_dataset_rejects_traversal_and_invalid_ohlc(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    input_root = tmp_path / "input"
    workspace.mkdir()
    input_root.mkdir()
    bad = input_root / "bad.csv"
    bad.write_text(
        "date,open,high,low,close,volume,openinterest\n" "2024-01-01,10,8,9,10,1,0\n",
        encoding="utf-8",
    )
    roots = RootRegistry(workspace / ".backtrader-agent")
    roots.register("input", input_root, writable=False, kind="dataset")
    service = DatasetService(roots, workspace / ".backtrader-agent")

    with pytest.raises(AgentError, match="BTAG-PATH"):
        service.inspect(data_spec("../escape.csv"))
    with pytest.raises(AgentError, match="BTAG-DATA-OHLC"):
        service.inspect(data_spec("bad.csv"))


@pytest.mark.parametrize(
    "adapter",
    [
        "generic_csv",
        "backtrader_csv",
        "yahoo_csv",
        "mt5_csv",
        "pandas",
        "pandas_custom_lines",
    ],
)
def test_all_six_offline_adapters_materialize_canonical_csv(
    tmp_path: Path,
    adapter: str,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    write_adapter_price_csv(input_root / "prices.csv", adapter)
    state = tmp_path / "state"
    roots = RootRegistry(state)
    roots.register("input", input_root, writable=False, kind="dataset")
    spec = data_spec()
    spec["feeds"][0]["format"] = adapter
    spec["feeds"][0]["columns"] = {"signal": "signal"} if adapter == "pandas_custom_lines" else {}
    if adapter == "mt5_csv":
        spec["feeds"][0]["delimiter"] = "\t"
    manifest = DatasetService(roots, state).register(spec)
    assert manifest["feeds"][0]["format"] == adapter
    expected_last_column = "signal" if adapter == "pandas_custom_lines" else "openinterest"
    assert manifest["feeds"][0]["canonical_columns"][-1] == expected_last_column
    cas_path = state / manifest["feeds"][0]["extensions"]["backtrader_agent"]["cas_relative_path"]
    assert cas_path.suffix == ".csv"


@pytest.mark.parametrize("profile_id", ["resample", "replay"])
def test_typed_resample_and_replay_are_preserved_in_registered_manifest(
    tmp_path: Path,
    profile_id: str,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    write_price_csv(input_root / "prices.csv")
    state = tmp_path / "state"
    roots = RootRegistry(state)
    roots.register("input", input_root, writable=False, kind="dataset")
    spec = data_spec()
    spec["feeds"][0]["timeframe"] = "Minutes"
    spec["transforms"] = [
        {
            "profile_id": profile_id,
            "parameters": {"feed": "primary", "timeframe": "Days", "compression": 1},
        }
    ]
    manifest = DatasetService(roots, state).register(spec)
    assert manifest["transforms"] == spec["transforms"]


def test_pandas_adapter_rejects_pickle_instead_of_deserializing_it(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "prices.pkl").write_bytes(b"not-a-tabular-csv")
    state = tmp_path / "state"
    roots = RootRegistry(state)
    roots.register("input", input_root, writable=False, kind="dataset")
    spec = data_spec("prices.pkl")
    spec["feeds"][0]["format"] = "pandas"
    with pytest.raises(AgentError, match="BTAG-DATA-PANDAS-MATERIALIZED"):
        DatasetService(roots, state).inspect(spec)
