from __future__ import annotations

import hashlib
from pathlib import Path

from backtrader_mcp.service import BacktraderMCPService
from backtrader_mcp.settings import Settings

EXPECTED_COUNTS = {
    "functional_tests": 1152,
    "strategy_packages": 1035,
    "mapped": 1032,
}
EXPECTED_ASSET_SHA256 = "30973a10bd434e7935aa5b45577a5d5de0221a58b53a4c00a8124006438c5828"


def test_packaged_catalog_has_full_verified_metadata_and_fourteen_templates(service_env):
    service, _, _ = service_env
    snapshot = service.get_catalog_snapshot()
    assert snapshot["extensions"]["counts"] == EXPECTED_COUNTS
    assert snapshot["extensions"]["entry_count"] == 1155
    assert len(snapshot["entries"]) == 1155
    assert service.list_strategy_templates()["count"] == 14

    results = service.search_strategy_catalog(
        "moving average trend",
        archetype="single_data_indicator",
        limit=3,
    )
    assert len(results["entries"]) == 3
    assert all(entry["source_available"] is False for entry in results["entries"])
    inspected = service.inspect_strategy(results["entries"][0]["canonical_id"])
    assert inspected["source_attached"] is False
    assert inspected["strategy"]["entry_hash"]

    asset = (
        Path(__file__).resolve().parents[1] / "src" / "backtrader_mcp" / "catalog_snapshot.jsonl"
    )
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == EXPECTED_ASSET_SHA256


def test_source_attached_dual_corpus_refresh_is_read_only_and_detects_staleness(
    tmp_path: Path,
):
    functional = tmp_path / "functional"
    packages = tmp_path / "packages"
    target = tmp_path / "target"
    state = tmp_path / "state"
    test_dir = functional / "trend"
    package_dir = packages / "trend" / "0001_example"
    test_dir.mkdir(parents=True)
    package_dir.mkdir(parents=True)
    target.mkdir()
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
    (package_dir / "config.yaml").write_text("period: 5\n", encoding="utf-8")
    (package_dir / "run.py").write_text("from strategy_example import Example\n", encoding="utf-8")
    before = {
        path.relative_to(tmp_path).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (test_path, strategy_path, package_dir / "config.yaml", package_dir / "run.py")
    }

    service = BacktraderMCPService(
        Settings(
            state_root=state,
            source_roots={"functional": functional, "packages": packages},
            target_roots={"strategies": target},
            runtimes={},
        )
    )
    snapshot = service.refresh_strategy_catalog(
        "functional",
        package_root_id="packages",
    )
    assert snapshot["mode"] == "source-attached"
    assert snapshot["counts"] == {
        "functional_tests": 1,
        "strategy_packages": 1,
        "mapped": 1,
    }
    assert snapshot["extensions"]["diagnostics"][0]["code"] == "verified_baseline_count_mismatch"
    entry = snapshot["entries"][0]
    assert entry["source"] == "mapped"
    assert service.inspect_strategy(entry["id"], entry["content_hash"])["status"] == "ready"
    repeated = service.refresh_strategy_catalog(
        "functional",
        expected_previous_snapshot_hash=snapshot["snapshot_hash"],
        package_root_id="packages",
    )
    assert repeated["snapshot_hash"] == snapshot["snapshot_hash"]
    after = {
        path.relative_to(tmp_path).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (test_path, strategy_path, package_dir / "config.yaml", package_dir / "run.py")
    }
    assert after == before

    strategy_path.write_text(strategy_path.read_text(encoding="utf-8") + "# changed\n")
    assert service.inspect_strategy(entry["id"])["status"] == "stale"
