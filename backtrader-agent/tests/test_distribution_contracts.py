import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from jsonschema import Draft202012Validator

from backtrader_agent.audit import SCHEMA_NAMES
from backtrader_agent.contracts import StrategySpec

from helpers import strategy_spec

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PRODUCT_ROOT / "src" / "backtrader_agent"


def test_source_distribution_manifest_covers_every_file() -> None:
    manifest_path = PRODUCT_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    excluded_parts = {"__pycache__", ".pytest_cache", "dist", "build"}
    actual = {
        path.relative_to(PRODUCT_ROOT).as_posix()
        for path in PRODUCT_ROOT.rglob("*")
        if path.is_file()
        and path != manifest_path
        and not excluded_parts.intersection(path.parts)
        and not any(part.endswith(".egg-info") for part in path.parts)
        and path.suffix != ".pyc"
    }
    assert manifest["file_count"] == len(actual)
    assert set(manifest["files"]) == actual
    for relative, expected_hash in manifest["files"].items():
        digest = hashlib.sha256((PRODUCT_ROOT / relative).read_bytes()).hexdigest()
        assert digest == expected_hash


def test_public_contract_assets_are_named_and_canonical() -> None:
    contracts = PACKAGE_ROOT / "resources" / "contracts"
    assert {path.name for path in contracts.glob("*.json")} == SCHEMA_NAMES
    parsed = {
        path.name: json.loads(path.read_text(encoding="utf-8")) for path in contracts.glob("*.json")
    }
    for schema in parsed.values():
        Draft202012Validator.check_schema(schema)
    data_schema = parsed["dataset-manifest-v1.schema.json"]
    assert "DataSpec" in data_schema["$defs"]
    assert set(data_schema["$defs"]["DataSpec"]["required"]) == {
        "schema_version",
        "spec_hash",
        "feeds",
        "master_feed",
        "alignment",
        "transforms",
    }
    session_schema = parsed["agent-session-manifest-v1.schema.json"]
    assert "AgentEvent" in session_schema["$defs"]
    comparison = json.loads(
        (PACKAGE_ROOT / "resources/policies/comparison-profile-v1.json").read_text(encoding="utf-8")
    )
    assert comparison["profile_version"] == "comparison-profile-v1"
    assert comparison["integer_metrics"] == [
        "bar_num",
        "buy_count",
        "sell_count",
        "win_count",
        "loss_count",
        "trade_num",
    ]
    assert comparison["float_metrics"] == [
        "final_value",
        "sharpe_ratio",
        "annual_return",
        "max_drawdown",
        "return_rate",
    ]
    assert comparison["nullable_metrics"] == ["sharpe_ratio", "annual_return"]
    assert comparison["default_float_tolerance"] == {
        "rel_tol": 1e-7,
        "abs_tol": 1e-9,
    }

    canonical = StrategySpec.from_dict(strategy_spec("ds_" + "a" * 64)).to_dict()
    Draft202012Validator(parsed["strategy-spec-v1.schema.json"]).validate(canonical)
    assert canonical["spec_version"] == "strategy-spec-v1"
    assert canonical["output_profile"] == "python_bundle"
    assert canonical["archetype"] == "single_data_indicator"
    assert "schema_version" not in canonical
    assert "profile" not in canonical
    assert "execution_modes" not in canonical

    legacy = strategy_spec("ds_" + "b" * 64)
    legacy["schema_version"] = legacy.pop("spec_version")
    legacy["profile"] = legacy.pop("output_profile")
    legacy["execution_modes"] = legacy.pop("run_modes")
    legacy["archetype"] = "single_indicator"
    migrated = StrategySpec.from_dict(legacy).to_dict()
    assert migrated["archetype"] == "single_data_indicator"
    assert migrated["run_modes"] == ["runonce", "runnext"]

    corpus = json.loads(
        (PACKAGE_ROOT / "resources/catalog/corpus-manifest.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(parsed["corpus-manifest-v1.schema.json"]).validate(corpus)


def test_built_wheel_contains_all_contracts_policy_catalog_and_payload(tmp_path: Path) -> None:
    source_copy = tmp_path / "source"
    shutil.copytree(
        PRODUCT_ROOT,
        source_copy,
        ignore=shutil.ignore_patterns(
            "build", "*.egg-info", "__pycache__", ".pytest_cache", "*.pyc"
        ),
    )
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            str(source_copy),
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    wheel = next(wheel_dir.glob("backtrader_agent-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    for schema_name in SCHEMA_NAMES:
        assert f"backtrader_agent/resources/contracts/{schema_name}" in names
    assert "backtrader_agent/resources/policies/comparison-profile-v1.json" in names
    assert "backtrader_agent/resources/catalog/corpus-v1.jsonl" in names
    assert "backtrader_agent/resources/catalog/snapshot.jsonl" in names
    assert "backtrader_agent/resources/catalog/corpus-manifest.json" in names
    assert "backtrader_agent/resources/agent-payload.md" in names
    for relative in (
        "claude-code/backtrader-agent.md",
        "codex/backtrader-agent.toml",
        "opencode/backtrader-agent.md",
        "openclaw/workspace/AGENTS.md",
        "openclaw/workspace/IDENTITY.md",
        "openclaw/workspace/README.md",
        "openclaw/workspace/registration-manifest.template.json",
    ):
        assert f"backtrader_agent/resources/adapters/{relative}" in names
    assert "backtrader_agent/resources/distribution-manifest.json" in names
    with zipfile.ZipFile(wheel) as archive:
        corpus = archive.read("backtrader_agent/resources/catalog/corpus-v1.jsonl")
    assert (
        hashlib.sha256(corpus).hexdigest()
        == "30973a10bd434e7935aa5b45577a5d5de0221a58b53a4c00a8124006438c5828"
    )
    assert len(corpus.splitlines()) == 1156

    clean_target = tmp_path / "clean-site"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(clean_target),
            str(wheel),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    outside = tmp_path / "outside-repository"
    outside.mkdir()
    completed = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            (
                "from backtrader_agent.catalog import SnapshotCatalog; "
                "c=SnapshotCatalog(); print(c.manifest['entry_count'], len(c.templates()))"
            ),
        ],
        cwd=outside,
        env={"PYTHONPATH": str(clean_target), "PATH": os.environ.get("PATH", "")},
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.stdout.strip() == "1155 14"
