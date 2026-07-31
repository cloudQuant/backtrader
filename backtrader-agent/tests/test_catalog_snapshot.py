import hashlib
from pathlib import Path

import pytest

from backtrader_agent.catalog import EXPECTED_COUNTS, SnapshotCatalog
from backtrader_agent.errors import AgentError

EXPECTED_ASSET_SHA256 = "30973a10bd434e7935aa5b45577a5d5de0221a58b53a4c00a8124006438c5828"


def test_packaged_catalog_has_full_verified_metadata_and_fourteen_templates() -> None:
    catalog = SnapshotCatalog()
    assert catalog.manifest["counts"] == EXPECTED_COUNTS
    assert catalog.manifest["entry_count"] == 1155
    assert len(catalog.templates()) == 14
    assert len(catalog.templates(archetype="pairs_spread", profile="python_bundle")) == 1
    results = catalog.search(
        "moving average trend",
        archetype="single_data_indicator",
        profile="single_test",
        top_k=3,
    )
    assert len(results) == 3
    assert all(result["source_available"] is False for result in results)
    assert catalog.inspect(results[0]["entry_id"])["source_available"] is False

    snapshot = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "backtrader_agent"
        / "resources"
        / "catalog"
        / "corpus-v1.jsonl"
    )
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == EXPECTED_ASSET_SHA256


def test_source_attached_refresh_rebuilds_both_adapters_without_mutating_source(
    tmp_path: Path,
) -> None:
    functional = tmp_path / "functional"
    packages = tmp_path / "packages"
    output = tmp_path / "state" / "source-catalog.jsonl"
    test_dir = functional / "trend"
    package_dir = packages / "trend" / "0001_example"
    test_dir.mkdir(parents=True)
    package_dir.mkdir(parents=True)
    test_path = test_dir / "test_0001_example.py"
    strategy_path = package_dir / "strategy_example.py"
    test_path.write_text(
        "import backtrader as bt\nclass Example(bt.Strategy):\n    pass\n",
        encoding="utf-8",
    )
    strategy_path.write_text(
        "import backtrader as bt\nclass Example(bt.Strategy):\n    pass\n",
        encoding="utf-8",
    )
    config_path = package_dir / "config.yaml"
    run_path = package_dir / "run.py"
    config_path.write_text("period: 5\n", encoding="utf-8")
    run_path.write_text("from strategy_example import Example\n", encoding="utf-8")
    inputs = (test_path, strategy_path, config_path, run_path)
    before = {
        path.relative_to(tmp_path).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in inputs
    }

    manifest = SnapshotCatalog.refresh_source_attached(
        functional,
        packages,
        output,
        require_verified_counts=False,
    )
    assert manifest["mode"] == "source-attached"
    assert manifest["counts"] == {
        "functional_tests": 1,
        "strategy_packages": 1,
        "mapped": 1,
    }
    rebuilt = SnapshotCatalog(snapshot_path=output)
    assert rebuilt.inspect("trend/0001_example")["source_available"] is True
    repeated_output = tmp_path / "state" / "source-catalog-repeated.jsonl"
    repeated = SnapshotCatalog.refresh_source_attached(
        functional,
        packages,
        repeated_output,
        require_verified_counts=False,
    )
    assert repeated["snapshot_hash"] == manifest["snapshot_hash"]
    assert repeated_output.read_bytes() == output.read_bytes()
    after = {
        path.relative_to(tmp_path).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in inputs
    }
    assert after == before

    with pytest.raises(AgentError) as error:
        SnapshotCatalog.refresh_source_attached(
            functional,
            packages,
            functional / "forbidden-output.jsonl",
            require_verified_counts=False,
        )
    assert error.value.code == "BTAG-CATALOG-OUTPUT"


def test_source_attached_verified_baseline_gate_rejects_partial_corpora(
    tmp_path: Path,
) -> None:
    functional = tmp_path / "functional"
    packages = tmp_path / "packages"
    functional.mkdir()
    packages.mkdir()
    with pytest.raises(AgentError) as error:
        SnapshotCatalog.refresh_source_attached(
            functional,
            packages,
            tmp_path / "catalog.jsonl",
        )
    assert error.value.code == "BTAG-CATALOG-COUNTS"
