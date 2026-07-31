#!/usr/bin/env python
"""Audit the three standalone AI strategy products without importing them."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = REPOSITORY_ROOT / "contracts" / "ai-strategy-v1"
PRODUCTS = {
    "backtrader-skills": "backtrader_skills",
    "backtrader-mcp": "backtrader_mcp",
    "backtrader-agent": "backtrader_agent",
}
HOST_MARKERS = ("Claude Code", "Codex", "OpenCode", "OpenClaw")
HOST_SPECIFIC_HOME = re.compile(
    r"(?:/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/|[A-Za-z]:\\\\Users\\\\[^\\\\/]+\\\\)"
)
SCHEMA_NAMES = (
    "strategy-spec-v1.schema.json",
    "dataset-manifest-v1.schema.json",
    "corpus-manifest-v1.schema.json",
    "artifact-manifest-v1.schema.json",
    "validation-report-v1.schema.json",
    "run-manifest-v1.schema.json",
    "run-result-v1.schema.json",
)
PRODUCT_CONTRACTS = {
    "backtrader-skills": {
        "strategy-spec-v1.schema.json": "resources/contracts/strategy-spec-v1.schema.json",
        "dataset-manifest-v1.schema.json": "resources/contracts/dataset-manifest-v1.schema.json",
        "corpus-manifest-v1.schema.json": "resources/contracts/corpus-manifest-v1.schema.json",
        "artifact-manifest-v1.schema.json": (
            "resources/contracts/strategy-artifact-manifest-v1.schema.json"
        ),
        "validation-report-v1.schema.json": (
            "resources/contracts/validation-report-v1.schema.json"
        ),
        "run-manifest-v1.schema.json": "resources/contracts/run-manifest-v1.schema.json",
        "run-result-v1.schema.json": "resources/contracts/run-result-v1.schema.json",
        "comparison-profile-v1.json": "resources/policies/comparison-profile-v1.json",
    },
    "backtrader-mcp": {
        "strategy-spec-v1.schema.json": "src/backtrader_mcp/schemas/strategy-spec.schema.json",
        "dataset-manifest-v1.schema.json": (
            "src/backtrader_mcp/schemas/dataset-manifest.schema.json"
        ),
        "corpus-manifest-v1.schema.json": (
            "src/backtrader_mcp/schemas/corpus-manifest.schema.json"
        ),
        "artifact-manifest-v1.schema.json": (
            "src/backtrader_mcp/schemas/artifact-manifest.schema.json"
        ),
        "validation-report-v1.schema.json": (
            "src/backtrader_mcp/schemas/validation-report.schema.json"
        ),
        "run-manifest-v1.schema.json": "src/backtrader_mcp/schemas/run-manifest.schema.json",
        "run-result-v1.schema.json": "src/backtrader_mcp/schemas/run-result.schema.json",
        "comparison-profile-v1.json": "src/backtrader_mcp/policies/comparison-profile-v1.json",
    },
    "backtrader-agent": {
        **{name: f"src/backtrader_agent/resources/contracts/{name}" for name in SCHEMA_NAMES},
        "comparison-profile-v1.json": (
            "src/backtrader_agent/resources/policies/comparison-profile-v1.json"
        ),
    },
}
CATALOG_PATHS = {
    "backtrader-skills": "resources/snapshots/catalog-v1.jsonl",
    "backtrader-mcp": "src/backtrader_mcp/catalog_snapshot.jsonl",
    "backtrader-agent": "src/backtrader_agent/resources/catalog/corpus-v1.jsonl",
}
CANONICAL_MODULES = {
    "backtrader-skills": ("backtrader_skills.canonical", "canonical_bytes", False),
    "backtrader-mcp": ("backtrader_mcp.util", "canonical_json", True),
    "backtrader-agent": ("backtrader_agent.canonical", "canonical_json_bytes", False),
}
CONTRACT_FIELDS = {
    "strategy-spec": {
        "spec_version",
        "name",
        "slug",
        "category",
        "archetype",
        "output_profile",
        "dataset_id",
        "feeds",
        "parameters",
        "entry",
        "exit",
        "sizing",
        "risk",
        "run_modes",
        "allowed_imports",
        "spec_hash",
    },
    "dataset-manifest": {
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
    },
    "corpus-manifest": {
        "schema_version",
        "corpus_id",
        "mode",
        "entries",
        "snapshot_hash",
        "provenance",
    },
    "artifact-manifest": {
        "schema_version",
        "artifact_id",
        "spec_hash",
        "dataset_id",
        "output_profile",
        "files",
        "artifact_hash",
    },
    "validation-report": {
        "schema_version",
        "validation_id",
        "artifact_hash",
        "dataset_id",
        "status",
        "diagnostics",
        "evidence",
        "validation_hash",
    },
    "run-manifest": {
        "schema_version",
        "run_id",
        "artifact_hash",
        "dataset_id",
        "engine",
        "environment_hash",
        "run_profile",
        "approval_id",
        "manifest_hash",
    },
    "run-result": {
        "schema_version",
        "run_id",
        "status",
        "metrics",
        "diagnostics",
        "artifacts",
        "result_hash",
    },
}
ARCHETYPES = {
    "single_data_indicator",
    "multi_indicator_system",
    "multi_asset_allocation",
    "multi_timeframe",
    "pairs_spread",
    "order_risk",
    "precomputed_ml",
}
INTEGER_METRICS = {
    "bar_num",
    "buy_count",
    "sell_count",
    "win_count",
    "loss_count",
    "trade_num",
}
FLOAT_METRICS = {
    "final_value",
    "sharpe_ratio",
    "annual_return",
    "max_drawdown",
    "return_rate",
}


def _module_imports(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    return imports


def _dangerous_calls(tree: ast.AST) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name in {"exec", "eval", "__import__"}:
            findings.append({"line": node.lineno, "call": name})
    return findings


def _load_json(path: Path, product_root: Path, failures: list[dict[str, Any]]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(
            {
                "code": "INVALID_JSON",
                "path": str(path.relative_to(product_root)),
                "detail": str(exc),
            }
        )
        return None


def _audit_contracts(
    product_name: str,
    product_root: Path,
    failures: list[dict[str, Any]],
) -> None:
    for marker, expected_fields in CONTRACT_FIELDS.items():
        source_name = f"{marker}-v1.schema.json"
        relative = PRODUCT_CONTRACTS[product_name].get(source_name)
        path = product_root / relative if relative else None
        if path is None or not path.is_file():
            failures.append({"code": "MISSING_CONTRACT", "contract": marker})
            continue
        authoritative = CONTRACT_ROOT / source_name
        if path.read_bytes() != authoritative.read_bytes():
            failures.append(
                {
                    "code": "CONTRACT_BYTE_MISMATCH",
                    "contract": marker,
                    "path": str(path.relative_to(product_root)),
                }
            )
        schema = _load_json(path, product_root, failures)
        if not isinstance(schema, dict):
            continue
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            failures.append(
                {
                    "code": "INVALID_JSON_SCHEMA",
                    "contract": marker,
                    "path": str(path.relative_to(product_root)),
                    "detail": str(exc),
                }
            )
            continue
        schema_id = schema.get("$id")
        if (
            not isinstance(schema_id, str)
            or not schema_id.startswith("https://backtrader.org/contracts/ai-strategy/v1/")
            or product_name in schema_id
        ):
            failures.append(
                {
                    "code": "PRODUCT_SPECIFIC_SCHEMA_ID",
                    "contract": marker,
                    "path": str(path.relative_to(product_root)),
                    "actual": schema_id,
                }
            )
        properties = schema.get("properties")
        required = schema.get("required")
        if not isinstance(properties, dict) or not isinstance(required, list):
            failures.append(
                {
                    "code": "INVALID_CONTRACT_SHAPE",
                    "contract": marker,
                    "path": str(path.relative_to(product_root)),
                }
            )
            continue
        missing_properties = sorted(expected_fields - set(properties))
        missing_required = sorted(expected_fields - set(required))
        if missing_properties or missing_required:
            failures.append(
                {
                    "code": "CONTRACT_CORE_MISMATCH",
                    "contract": marker,
                    "path": str(path.relative_to(product_root)),
                    "missing_properties": missing_properties,
                    "missing_required": missing_required,
                }
            )
        if marker == "strategy-spec":
            dataset_pattern = properties.get("dataset_id", {}).get("pattern")
            archetypes = properties.get("archetype", {}).get("enum")
            if dataset_pattern != r"^ds_[0-9a-f]{64}$":
                failures.append(
                    {
                        "code": "DATASET_ID_PATTERN_MISMATCH",
                        "path": str(path.relative_to(product_root)),
                        "actual": dataset_pattern,
                    }
                )
            if not isinstance(archetypes, list) or set(archetypes) != ARCHETYPES:
                failures.append(
                    {
                        "code": "ARCHETYPE_ENUM_MISMATCH",
                        "path": str(path.relative_to(product_root)),
                        "actual": archetypes,
                    }
                )
        elif marker == "dataset-manifest":
            definitions = schema.get("$defs")
            if not isinstance(definitions, dict) or "DataSpec" not in definitions:
                failures.append(
                    {
                        "code": "MISSING_DATA_SPEC",
                        "path": str(path.relative_to(product_root)),
                    }
                )


def _audit_comparison_profile(
    product_name: str,
    product_root: Path,
    failures: list[dict[str, Any]],
) -> None:
    relative = PRODUCT_CONTRACTS[product_name]["comparison-profile-v1.json"]
    path = product_root / relative
    if not path.is_file():
        failures.append({"code": "MISSING_POLICY", "policy": "comparison-profile"})
        return
    authoritative = CONTRACT_ROOT / "comparison-profile-v1.json"
    if path.read_bytes() != authoritative.read_bytes():
        failures.append(
            {
                "code": "POLICY_BYTE_MISMATCH",
                "path": str(path.relative_to(product_root)),
            }
        )
    profile = _load_json(path, product_root, failures)
    if not isinstance(profile, dict):
        return
    tolerance = profile.get("default_float_tolerance")
    expected = {
        "profile_version": profile.get("profile_version") == "comparison-profile-v1",
        "integer_metrics": set(profile.get("integer_metrics", [])) == INTEGER_METRICS,
        "float_metrics": set(profile.get("float_metrics", [])) == FLOAT_METRICS,
        "nullable_metrics": profile.get("nullable_metrics") == ["sharpe_ratio", "annual_return"],
        "rel_tol": isinstance(tolerance, dict) and tolerance.get("rel_tol") == 1e-7,
        "abs_tol": isinstance(tolerance, dict) and tolerance.get("abs_tol") == 1e-9,
        "non_finite": profile.get("non_finite") == "fail",
        "missing_required": profile.get("missing_required") == "fail",
        "null_comparison": profile.get("null_comparison") == "only_equal_to_null",
        "event_fields": profile.get("event_fields")
        == ["sequence", "kind", "data", "size", "price", "status"],
    }
    mismatches = sorted(key for key, passed in expected.items() if not passed)
    if mismatches:
        failures.append(
            {
                "code": "COMPARISON_PROFILE_MISMATCH",
                "path": str(path.relative_to(product_root)),
                "fields": mismatches,
            }
        )


def _set_path(value: dict[str, Any], dotted: str, replacement: Any) -> None:
    parts = dotted.split(".")
    current: Any = value
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    if isinstance(current, list):
        current[int(parts[-1])] = replacement
    else:
        current[parts[-1]] = replacement


def _delete_path(value: dict[str, Any], dotted: str) -> None:
    parts = dotted.split(".")
    current: Any = value
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    if isinstance(current, list):
        del current[int(parts[-1])]
    else:
        del current[parts[-1]]


def _audit_golden_contracts(
    product_name: str,
    product_root: Path,
    failures: list[dict[str, Any]],
) -> None:
    positive = json.loads(
        (CONTRACT_ROOT / "fixtures" / "golden-positive.json").read_text(encoding="utf-8")
    )
    negative = json.loads(
        (CONTRACT_ROOT / "fixtures" / "golden-negative.json").read_text(encoding="utf-8")
    )
    schemas = {
        name: json.loads(
            (product_root / PRODUCT_CONTRACTS[product_name][name]).read_text(encoding="utf-8")
        )
        for name in SCHEMA_NAMES
    }
    for name, payload in positive["contracts"].items():
        try:
            Draft202012Validator(schemas[name]).validate(payload)
        except ValidationError as exc:
            failures.append(
                {
                    "code": "GOLDEN_POSITIVE_REJECTED",
                    "contract": name,
                    "detail": exc.message,
                }
            )
    data_spec_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": schemas["dataset-manifest-v1.schema.json"]["$defs"],
        "$ref": "#/$defs/DataSpec",
    }
    try:
        Draft202012Validator(data_spec_schema).validate(positive["data_spec"])
    except ValidationError as exc:
        failures.append(
            {
                "code": "GOLDEN_POSITIVE_REJECTED",
                "contract": "DataSpec",
                "detail": exc.message,
            }
        )
    for case in negative["cases"]:
        if case["contract"] == "DataSpec":
            payload = copy.deepcopy(positive["data_spec"])
            schema = data_spec_schema
        else:
            payload = copy.deepcopy(positive["contracts"][case["contract"]])
            schema = schemas[case["contract"]]
        for dotted, replacement in case.get("patch", {}).items():
            _set_path(payload, dotted, replacement)
        if "delete" in case:
            _delete_path(payload, case["delete"])
        if not list(Draft202012Validator(schema).iter_errors(payload)):
            failures.append(
                {
                    "code": "GOLDEN_NEGATIVE_ACCEPTED",
                    "contract": case["contract"],
                    "case": case["id"],
                }
            )


def _audit_catalog(
    product_name: str,
    product_root: Path,
    failures: list[dict[str, Any]],
) -> None:
    path = product_root / CATALOG_PATHS[product_name]
    authoritative = REPOSITORY_ROOT / "backtrader-skills" / CATALOG_PATHS["backtrader-skills"]
    if not path.is_file():
        failures.append({"code": "MISSING_CATALOG", "path": str(path)})
        return
    if path.read_bytes() != authoritative.read_bytes():
        failures.append(
            {
                "code": "CATALOG_BYTE_MISMATCH",
                "path": str(path.relative_to(product_root)),
            }
        )
    try:
        records = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except json.JSONDecodeError as exc:
        failures.append(
            {
                "code": "INVALID_CATALOG_JSONL",
                "path": str(path.relative_to(product_root)),
                "detail": str(exc),
            }
        )
        return
    if not records:
        failures.append({"code": "EMPTY_CATALOG", "path": str(path.relative_to(product_root))})
        return
    manifest, entries = records[0], records[1:]
    schema = json.loads(
        (
            product_root / PRODUCT_CONTRACTS[product_name]["corpus-manifest-v1.schema.json"]
        ).read_text(encoding="utf-8")
    )
    try:
        Draft202012Validator(schema).validate(manifest)
    except ValidationError as exc:
        failures.append(
            {
                "code": "CATALOG_MANIFEST_INVALID",
                "path": str(path.relative_to(product_root)),
                "detail": exc.message,
            }
        )
        return
    if manifest.get("entry_count") != 1155 or len(entries) != 1155:
        failures.append(
            {
                "code": "CATALOG_COUNT_MISMATCH",
                "path": str(path.relative_to(product_root)),
                "entry_count": manifest.get("entry_count"),
                "records": len(entries),
            }
        )
    if [item.get("content_hash") for item in manifest["entries"]] != [
        item.get("entry_hash") for item in entries
    ]:
        failures.append(
            {
                "code": "CATALOG_ENTRY_BINDING_MISMATCH",
                "path": str(path.relative_to(product_root)),
            }
        )
    hash_payload = {key: value for key, value in manifest.items() if key != "snapshot_hash"}
    canonical = json.dumps(
        hash_payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if manifest.get("snapshot_hash") != hashlib.sha256(canonical).hexdigest():
        failures.append(
            {
                "code": "CATALOG_HASH_MISMATCH",
                "path": str(path.relative_to(product_root)),
            }
        )
    if product_name == "backtrader-agent":
        standalone = product_root / "src/backtrader_agent/resources/catalog/corpus-manifest.json"
        if (
            not standalone.is_file()
            or json.loads(standalone.read_text(encoding="utf-8")) != manifest
        ):
            failures.append(
                {
                    "code": "CATALOG_STANDALONE_MANIFEST_MISMATCH",
                    "path": str(standalone.relative_to(product_root)),
                }
            )


def _canonical_fixture_outputs(
    product_name: str,
    product_root: Path,
    failures: list[dict[str, Any]],
) -> list[str] | None:
    module_name, function_name, returns_text = CANONICAL_MODULES[product_name]
    fixture = CONTRACT_ROOT / "fixtures" / "canonical-json-v1.json"
    script = """
import importlib
import json
import math
import sys

sys.path.insert(0, sys.argv[1])
module = importlib.import_module(sys.argv[2])
function = getattr(module, sys.argv[3])
returns_text = sys.argv[4] == "1"
fixture = json.loads(open(sys.argv[5], encoding="utf-8").read())

def encode(value):
    result = function(value)
    return result.encode("utf-8") if returns_text else result

outputs = []
for case in fixture["positive"]:
    left = encode(case["left"])
    right = encode(case["right"])
    if left != right:
        raise AssertionError(case["id"])
    outputs.append(left.hex())
for value in (math.nan, math.inf, -math.inf):
    try:
        encode({"value": value})
    except Exception:
        pass
    else:
        raise AssertionError("non-finite value accepted")
keys = fixture["negative"][-1]["keys"]
try:
    encode({keys[0]: 1, keys[1]: 2})
except Exception:
    pass
else:
    raise AssertionError("NFC key collision accepted")
print(json.dumps(outputs))
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(product_root / "src"),
            module_name,
            function_name,
            "1" if returns_text else "0",
            str(fixture),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        failures.append(
            {
                "code": "CANONICAL_FIXTURE_FAILED",
                "detail": (completed.stderr or completed.stdout)[-1000:],
            }
        )
        return None
    try:
        outputs = json.loads(completed.stdout)
    except json.JSONDecodeError:
        failures.append(
            {
                "code": "CANONICAL_FIXTURE_OUTPUT_INVALID",
                "detail": completed.stdout[-1000:],
            }
        )
        return None
    return outputs


def audit_product(product_name: str, package_name: str) -> dict[str, Any]:
    product_root = REPOSITORY_ROOT / product_name
    failures: list[dict[str, Any]] = []
    for required in ("README.md", "pyproject.toml"):
        if not (product_root / required).is_file():
            failures.append({"code": "MISSING_FILE", "path": required})

    readme_path = product_root / "README.md"
    if readme_path.is_file():
        readme = readme_path.read_text(encoding="utf-8")
        for host in HOST_MARKERS:
            if host not in readme:
                failures.append({"code": "MISSING_HOST_DOC", "host": host})
        match = HOST_SPECIFIC_HOME.search(readme)
        if match:
            failures.append(
                {
                    "code": "HOST_SPECIFIC_PUBLIC_COMMAND",
                    "path": "README.md",
                    "example": match.group(0),
                }
            )

    _audit_contracts(product_name, product_root, failures)
    _audit_comparison_profile(product_name, product_root, failures)
    _audit_golden_contracts(product_name, product_root, failures)
    _audit_catalog(product_name, product_root, failures)
    canonical_outputs = _canonical_fixture_outputs(product_name, product_root, failures)

    sibling_packages = set(PRODUCTS.values()) - {package_name}
    for source_path in product_root.rglob("*.py"):
        if "__pycache__" in source_path.parts:
            continue
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        except (OSError, SyntaxError) as exc:
            failures.append(
                {
                    "code": "PYTHON_PARSE",
                    "path": str(source_path.relative_to(product_root)),
                    "detail": str(exc),
                }
            )
            continue
        imported_siblings = sorted(_module_imports(tree) & sibling_packages)
        if imported_siblings:
            failures.append(
                {
                    "code": "SIBLING_IMPORT",
                    "path": str(source_path.relative_to(product_root)),
                    "modules": imported_siblings,
                }
            )
        for finding in _dangerous_calls(tree):
            failures.append(
                {
                    "code": "DYNAMIC_EXECUTION",
                    "path": str(source_path.relative_to(product_root)),
                    **finding,
                }
            )

    return {
        "product": product_name,
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "_canonical_outputs": canonical_outputs,
    }


def main() -> int:
    reports = [
        audit_product(product_name, package_name) for product_name, package_name in PRODUCTS.items()
    ]
    canonical_outputs = {
        item["product"]: item.pop("_canonical_outputs")
        for item in reports
        if item.get("_canonical_outputs") is not None
    }
    if len(canonical_outputs) == len(PRODUCTS):
        distinct = {tuple(value) for value in canonical_outputs.values()}
        if len(distinct) != 1:
            for report in reports:
                report["failures"].append({"code": "CROSS_PRODUCT_CANONICAL_MISMATCH"})
    for report in reports:
        report.pop("_canonical_outputs", None)
        report["status"] = "passed" if not report["failures"] else "failed"
    payload = {
        "schema_version": "backtrader-ai-products-audit-v1",
        "status": "passed" if all(item["status"] == "passed" for item in reports) else "failed",
        "products": reports,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
