"""Regression coverage for the offline Iteration 41 AI producer collector."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "collect_iteration41_ai_producer_inventory.py"


def _collector_module():
    name = "iteration41_ai_producer_inventory_test_module"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *arguments: str) -> None:
    completed = subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def _make_product(root: Path, product: str, package: str, *, version: str = "0.2.0") -> Path:
    root.mkdir()
    package_dir = root / "src" / package
    package_dir.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        "[project]\nname = \"{0}\"\nversion = \"{1}\"\n".format(product, version),
        encoding="utf-8",
    )
    (package_dir / "__init__.py").write_text(
        "__version__ = \"{0}\"\n".format(version), encoding="utf-8"
    )
    # If this module were imported the test would fail. The collector must
    # only read and hash it.
    (package_dir / "deployment_evidence.py").write_text(
        "raise RuntimeError('producer import is forbidden during collection')\n",
        encoding="utf-8",
    )
    _git(root, "init")
    _git(root, "config", "user.email", "iteration41@example.invalid")
    _git(root, "config", "user.name", "Iteration 41 Test")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "baseline")
    return root


def _fixture_roots(tmp_path: Path):
    return (
        (
            "backtrader-agent",
            _make_product(tmp_path / "backtrader-agent", "backtrader-agent", "backtrader_agent"),
        ),
        (
            "backtrader-skills",
            _make_product(tmp_path / "backtrader-skills", "backtrader-skills", "backtrader_skills"),
        ),
        (
            "backtrader-mcp",
            _make_product(tmp_path / "backtrader-mcp", "backtrader-mcp", "backtrader_mcp"),
        ),
    )


def test_collector_records_all_three_git_roots_without_importing_producer_code(tmp_path: Path) -> None:
    collector = _collector_module()
    roots = _fixture_roots(tmp_path)

    report = collector.collect_producer_inventory(roots)

    assert report["schema_version"] == collector.SCHEMA_VERSION
    assert report["status"] == "SOURCE_BASELINE_ONLY"
    assert [item["product"] for item in report["products"]] == [
        "backtrader-agent",
        "backtrader-mcp",
        "backtrader-skills",
    ]
    for item in report["products"]:
        assert len(item["git_commit"]) == 40
        assert item["working_tree_dirty"] is False
        assert len(item["working_tree_manifest_sha256"]) == 64
        assert len(item["deployment_evidence_sha256"]) == 64
        assert item["package_version"] == "0.2.0"


def test_dirty_content_changes_the_redacted_manifest_digest(tmp_path: Path) -> None:
    collector = _collector_module()
    roots = _fixture_roots(tmp_path)
    before = collector.collect_producer_inventory(roots)
    agent_root = dict(roots)["backtrader-agent"]
    (agent_root / "src" / "backtrader_agent" / "deployment_evidence.py").write_text(
        "# changed but never imported\n", encoding="utf-8"
    )
    after = collector.collect_producer_inventory(roots)
    before_agent = next(item for item in before["products"] if item["product"] == "backtrader-agent")
    after_agent = next(item for item in after["products"] if item["product"] == "backtrader-agent")

    assert after_agent["working_tree_dirty"] is True
    assert after_agent["working_tree_manifest_sha256"] != before_agent["working_tree_manifest_sha256"]
    assert after_agent["deployment_evidence_sha256"] != before_agent["deployment_evidence_sha256"]


def test_collector_cli_writes_source_baseline_only_artifact(tmp_path: Path, capsys) -> None:
    collector = _collector_module()
    roots = dict(_fixture_roots(tmp_path))
    output = tmp_path / "artifact" / "ai-producers.json"

    status = collector.main(
        [
            "--agent-root",
            str(roots["backtrader-agent"]),
            "--skills-root",
            str(roots["backtrader-skills"]),
            "--mcp-root",
            str(roots["backtrader-mcp"]),
            "--output",
            str(output),
        ]
    )

    assert status == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["status"] == "SOURCE_BASELINE_ONLY"
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "SOURCE_BASELINE_ONLY"


def test_collector_requires_exactly_the_three_reviewed_products(tmp_path: Path) -> None:
    collector = _collector_module()
    roots = _fixture_roots(tmp_path)

    with pytest.raises(collector.ProducerInventoryError, match="all three"):
        collector.collect_producer_inventory(roots[:2])
