"""Distribution, independence, and runtime readiness checks."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from .catalog import EXPECTED_COUNTS, load_snapshot
from .installer import SKILL_NAMES, distribution_root
from .resources import resource_path, resource_root

CONTRACT_FILES = (
    "strategy-spec-v1.schema.json",
    "dataset-manifest-v1.schema.json",
    "corpus-manifest-v1.schema.json",
    "strategy-artifact-manifest-v1.schema.json",
    "validation-report-v1.schema.json",
    "run-manifest-v1.schema.json",
    "run-result-v1.schema.json",
)
FORBIDDEN_SIBLING_IMPORTS = {"backtrader_mcp", "backtrader_agent"}


def run_doctor(target: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    resources = resource_root()
    for name in CONTRACT_FILES:
        path = resource_path("contracts", name)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            passed = payload.get("$schema", "").endswith("2020-12/schema")
            if name == "dataset-manifest-v1.schema.json":
                passed = passed and "DataSpec" in payload.get("$defs", {})
        except (OSError, json.JSONDecodeError):
            passed = False
        checks.append({"check": f"contract:{name}", "passed": passed})
    profile = json.loads(
        resource_path("policies", "comparison-profile-v1.json").read_text(encoding="utf-8")
    )
    checks.append(
        {
            "check": "comparison-profile-v1",
            "passed": profile.get("profile_version") == "comparison-profile-v1",
        }
    )
    header, entries = load_snapshot(resource_path("snapshots", "catalog-v1.jsonl"))
    checks.append(
        {
            "check": "catalog-counts",
            "passed": header["counts"] == EXPECTED_COUNTS and len(entries) == header["entry_count"],
            "observed": header["counts"],
        }
    )
    root = distribution_root()
    for skill in SKILL_NAMES:
        checks.append(
            {
                "check": f"skill:{skill}",
                "passed": (root / "skills" / skill / "SKILL.md").is_file()
                and (root / "skills" / skill / "agents" / "openai.yaml").is_file(),
            }
        )
    sibling_imports: list[str] = []
    source_root = Path(__file__).resolve().parent
    for path in source_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", maxsplit=1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".", maxsplit=1)[0]]
            else:
                continue
            sibling_imports.extend(name for name in names if name in FORBIDDEN_SIBLING_IMPORTS)
    checks.append(
        {
            "check": "no-sibling-product-imports",
            "passed": not sibling_imports,
            "observed": sorted(set(sibling_imports)),
        }
    )
    checks.append(
        {
            "check": "target-backtrader-source",
            "passed": (target / "backtrader" / "version.py").is_file(),
        }
    )
    return {
        "schema_version": "doctor-result-v1",
        "resource_root": str(resources),
        "checks": checks,
        "passed": all(item["passed"] for item in checks),
    }
