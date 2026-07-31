from __future__ import annotations

import ast
import json
import subprocess
import sys
import zipfile

import jsonschema

from backtrader_skills.catalog import EXPECTED_COUNTS, load_snapshot, search_snapshot
from backtrader_skills.compare import compare_metrics, load_comparison_profile
from backtrader_skills.doctor import CONTRACT_FILES, run_doctor
from backtrader_skills.distribution import verify_distribution_manifest
from backtrader_skills.ir import default_strategy_spec
from backtrader_skills.resources import resource_path

from .conftest import PRODUCT_ROOT, REPOSITORY_ROOT


def test_catalog_snapshot_counts_hash_and_search() -> None:
    snapshot = resource_path("snapshots", "catalog-v1.jsonl")
    header, entries = load_snapshot(snapshot)
    assert header["counts"] == EXPECTED_COUNTS
    assert len(entries) == 1155
    result = search_snapshot(
        snapshot, "moving average trend", archetype="single_data_indicator", limit=3
    )
    assert result["template"]["current_fork_compliant"]
    assert len(result["results"]) == 3


def test_comparison_profile_core_and_fixtures() -> None:
    profile = load_comparison_profile()
    assert profile["integer_metrics"] == [
        "bar_num",
        "buy_count",
        "sell_count",
        "win_count",
        "loss_count",
        "trade_num",
    ]
    assert profile["float_metrics"] == [
        "final_value",
        "sharpe_ratio",
        "annual_return",
        "max_drawdown",
        "return_rate",
    ]
    assert profile["nullable_metrics"] == ["sharpe_ratio", "annual_return"]
    assert profile["default_float_tolerance"] == {
        "rel_tol": 1e-7,
        "abs_tol": 1e-9,
    }
    for fixture_name in ("comparison-positive.json", "comparison-negative.json"):
        fixture = json.loads(resource_path("fixtures", fixture_name).read_text(encoding="utf-8"))
        assert (
            compare_metrics(fixture["left"], fixture["right"])["passed"]
            is fixture["expected_passed"]
        )


def test_named_schemas_are_valid_and_accept_canonical_spec() -> None:
    schemas = {}
    for name in CONTRACT_FILES:
        schema = json.loads(resource_path("contracts", name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        schemas[name] = schema
    assert "DataSpec" in schemas["dataset-manifest-v1.schema.json"]["$defs"]
    spec = default_strategy_spec("single_data_indicator", "single_test", "ds_" + "a" * 64)
    jsonschema.validate(spec, schemas["strategy-spec-v1.schema.json"])


def test_no_sibling_product_imports_and_doctor() -> None:
    forbidden = {"backtrader_mcp", "backtrader_agent"}
    for path in (PRODUCT_ROOT / "src" / "backtrader_skills").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".", 1)[0])
        assert not imported & forbidden
    assert run_doctor(REPOSITORY_ROOT)["passed"]
    assert verify_distribution_manifest(PRODUCT_ROOT)["verified"]


def test_wheel_contains_contracts_policy_catalog_and_all_skills(tmp_path) -> None:
    output = tmp_path / "wheel"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(output),
            str(PRODUCT_ROOT),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    wheel = next(output.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    for contract in CONTRACT_FILES:
        assert any(name.endswith(f"resources/contracts/{contract}") for name in names)
    assert any(name.endswith("resources/policies/comparison-profile-v1.json") for name in names)
    assert any(name.endswith("resources/snapshots/catalog-v1.jsonl") for name in names)
    assert any(name.endswith("evidence/acceptance-7x2.json") for name in names)
    assert any(name.endswith("share/backtrader-skills/manifest.json") for name in names)
    for host in ("claude", "codex", "opencode", "openclaw"):
        assert any(name.endswith(f"host_adapters/{host}.json") for name in names)
    for skill in (
        "backtrader-strategy-author",
        "backtrader-strategy-review",
        "backtrader-strategy-test",
    ):
        assert any(name.endswith(f"skills/{skill}/SKILL.md") for name in names)
