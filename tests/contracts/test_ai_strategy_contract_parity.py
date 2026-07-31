"""Cross-product conformance tests for the shared AI strategy contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = REPOSITORY_ROOT / "contracts" / "ai-strategy-v1"
PRODUCTS = ("backtrader-skills", "backtrader-mcp", "backtrader-agent")
SCHEMAS = (
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
    },
    "backtrader-agent": {
        name: f"src/backtrader_agent/resources/contracts/{name}" for name in SCHEMAS
    },
}
CATALOGS = {
    "backtrader-skills": "resources/snapshots/catalog-v1.jsonl",
    "backtrader-mcp": "src/backtrader_mcp/catalog_snapshot.jsonl",
    "backtrader-agent": "src/backtrader_agent/resources/catalog/corpus-v1.jsonl",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


@pytest.fixture(scope="module")
def golden_positive() -> dict[str, Any]:
    return _load_json(CONTRACT_ROOT / "fixtures" / "golden-positive.json")


def test_all_vendored_schemas_are_byte_identical_and_product_neutral() -> None:
    for product, mapping in PRODUCT_CONTRACTS.items():
        for name, relative in mapping.items():
            authoritative = CONTRACT_ROOT / name
            vendored = REPOSITORY_ROOT / product / relative
            assert vendored.read_bytes() == authoritative.read_bytes(), (product, name)
            schema = _load_json(vendored)
            assert schema["$id"].startswith("https://backtrader.org/contracts/ai-strategy/v1/")
            assert product not in schema["$id"]


@pytest.mark.parametrize("producer", PRODUCTS)
@pytest.mark.parametrize("consumer", PRODUCTS)
def test_three_by_three_golden_contract_acceptance(
    producer: str,
    consumer: str,
    golden_positive: dict[str, Any],
) -> None:
    """Every product's public payload is accepted by every consumer's schemas."""

    del producer  # The product-neutral golden payload is the required producer output.
    for name, payload in golden_positive["contracts"].items():
        schema_path = REPOSITORY_ROOT / consumer / PRODUCT_CONTRACTS[consumer][name]
        Draft202012Validator(_load_json(schema_path)).validate(copy.deepcopy(payload))
    dataset_schema = _load_json(
        REPOSITORY_ROOT / consumer / PRODUCT_CONTRACTS[consumer]["dataset-manifest-v1.schema.json"]
    )
    data_spec_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": dataset_schema["$defs"],
        "$ref": "#/$defs/DataSpec",
    }
    Draft202012Validator(data_spec_schema).validate(copy.deepcopy(golden_positive["data_spec"]))


@pytest.mark.parametrize("consumer", PRODUCTS)
def test_shared_negative_fixtures_are_rejected(
    consumer: str,
    golden_positive: dict[str, Any],
) -> None:
    negative = _load_json(CONTRACT_ROOT / "fixtures" / "golden-negative.json")
    for case in negative["cases"]:
        if case["contract"] == "DataSpec":
            payload = copy.deepcopy(golden_positive["data_spec"])
            dataset_schema = _load_json(
                REPOSITORY_ROOT
                / consumer
                / PRODUCT_CONTRACTS[consumer]["dataset-manifest-v1.schema.json"]
            )
            schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$defs": dataset_schema["$defs"],
                "$ref": "#/$defs/DataSpec",
            }
        else:
            payload = copy.deepcopy(golden_positive["contracts"][case["contract"]])
            schema = _load_json(
                REPOSITORY_ROOT / consumer / PRODUCT_CONTRACTS[consumer][case["contract"]]
            )
        for dotted, replacement in case.get("patch", {}).items():
            _set_path(payload, dotted, replacement)
        if "delete" in case:
            _delete_path(payload, case["delete"])
        assert list(Draft202012Validator(schema).iter_errors(payload)), (
            consumer,
            case["id"],
        )


def test_canonical_json_bytes_and_hashes_match_across_products() -> None:
    for relative in (
        "backtrader-skills/src",
        "backtrader-mcp/src",
        "backtrader-agent/src",
    ):
        sys.path.insert(0, str(REPOSITORY_ROOT / relative))
    from backtrader_agent.canonical import canonical_json_bytes, hash_object
    from backtrader_agent.errors import AgentError
    from backtrader_mcp.util import canonical_json, sha256_json
    from backtrader_skills.canonical import canonical_bytes, canonical_hash
    from backtrader_skills.errors import ContractError

    fixture = _load_json(CONTRACT_ROOT / "fixtures" / "canonical-json-v1.json")
    for case in fixture["positive"]:
        left = case["left"]
        right = case["right"]
        expected = canonical_bytes(left)
        assert canonical_bytes(right) == expected
        assert canonical_json(left).encode("utf-8") == expected
        assert canonical_json(right).encode("utf-8") == expected
        assert canonical_json_bytes(left) == expected
        assert canonical_json_bytes(right) == expected
        expected_hash = hashlib.sha256(expected).hexdigest()
        assert canonical_hash(left) == sha256_json(left) == hash_object(left) == expected_hash
    for non_finite in (math.nan, math.inf, -math.inf):
        for canonicalizer in (
            canonical_bytes,
            lambda value: canonical_json(value).encode("utf-8"),
            canonical_json_bytes,
        ):
            with pytest.raises((AgentError, ContractError, ValueError)):
                canonicalizer({"value": non_finite})
    colliding = {"é": 1, "e\u0301": 2}
    for canonicalizer in (
        canonical_bytes,
        lambda value: canonical_json(value).encode("utf-8"),
        canonical_json_bytes,
    ):
        with pytest.raises((AgentError, ContractError, ValueError)):
            canonicalizer(colliding)


def test_catalog_assets_are_byte_identical_schema_valid_and_hash_bound() -> None:
    payloads = {
        product: (REPOSITORY_ROOT / product / relative).read_bytes()
        for product, relative in CATALOGS.items()
    }
    assert len(set(payloads.values())) == 1
    records = [
        json.loads(line)
        for line in next(iter(payloads.values())).decode("utf-8").splitlines()
        if line.strip()
    ]
    manifest, entries = records[0], records[1:]
    schema = _load_json(CONTRACT_ROOT / "corpus-manifest-v1.schema.json")
    Draft202012Validator(schema).validate(manifest)
    assert manifest["entry_count"] == len(manifest["entries"]) == len(entries) == 1155
    without_hash = {key: value for key, value in manifest.items() if key != "snapshot_hash"}
    from backtrader_skills.canonical import canonical_hash

    assert manifest["snapshot_hash"] == canonical_hash(without_hash)
    assert [item["content_hash"] for item in manifest["entries"]] == [
        item["entry_hash"] for item in entries
    ]
