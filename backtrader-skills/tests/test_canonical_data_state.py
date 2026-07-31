from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
import json
import jsonschema

from backtrader_skills.canonical import canonical_bytes, canonical_hash
from backtrader_skills.data import DataRegistry
from backtrader_skills.errors import ApprovalError, ContractError, IntegrityError, PathPolicyError
from backtrader_skills.runtime import RuntimePaths
from backtrader_skills.resources import resource_path
from backtrader_skills.state import TokenStore

from .helpers import isolated_target, register_dataset, write_market_csv


def test_canonical_json_is_stable_and_rejects_non_finite() -> None:
    left = {"é": [1, -0.0], "b": True}
    right = {"b": True, "e\u0301": [1, 0.0]}
    assert canonical_bytes(left) == canonical_bytes(right)
    assert canonical_hash(left) == canonical_hash(right)
    with pytest.raises(ContractError):
        canonical_bytes({"bad": math.nan})


def test_hash_bound_token_is_one_time(tmp_path) -> None:
    target = isolated_target(tmp_path)
    store = TokenStore(RuntimePaths(target))
    bindings = {"artifact_hash": "a" * 64, "operation": "render_apply"}
    token = store.issue("render_write", bindings)
    with pytest.raises(ApprovalError):
        store.consume(token["token_id"], "render_write", bindings)
    store.approve(token["token_id"])
    with pytest.raises(IntegrityError):
        store.verify(
            token["token_id"],
            "render_write",
            {"artifact_hash": "b" * 64, "operation": "render_apply"},
        )
    assert store.get(token["token_id"])["state"] == "REVOKED"
    replacement = store.issue("render_write", bindings)
    store.approve(replacement["token_id"])
    consumed = store.consume(replacement["token_id"], "render_write", bindings)
    assert consumed["state"] == "CONSUMED"
    with pytest.raises(ApprovalError):
        store.consume(replacement["token_id"], "render_write", bindings)


def test_token_persistence_is_digest_only_and_expiry_is_terminal(tmp_path) -> None:
    target = isolated_target(tmp_path)
    current = [datetime(2026, 7, 30, tzinfo=timezone.utc)]
    store = TokenStore(RuntimePaths(target), clock=lambda: current[0])
    bindings = {"artifact_hash": "a" * 64, "operation": "render_apply"}
    token = store.issue("render_write", bindings, ttl_seconds=10)
    persisted = next((target / ".backtrader-skills" / "tokens").glob("*.json"))
    raw = persisted.read_text(encoding="utf-8")
    assert token["token_id"] not in raw
    assert '"bindings"' not in raw
    assert persisted.stem == token["token_digest"]
    store.approve(token["token_id"])
    current[0] += timedelta(seconds=11)
    assert store.get(token["token_id"])["state"] == "EXPIRED"
    with pytest.raises(ApprovalError):
        store.verify(token["token_id"], "render_write", bindings)


def test_dataset_is_immutable_full_hash_and_bounded_preview(tmp_path) -> None:
    target = isolated_target(tmp_path)
    data_root = tmp_path / "data"
    data_root.mkdir()
    manifest = register_dataset(target, data_root)
    registry = DataRegistry(RuntimePaths(target))
    assert len(manifest["dataset_id"]) == 67
    assert manifest["dataset_id"] == f"ds_{manifest['semantic_hash']}"
    assert manifest["status"] == "valid"
    assert manifest["spec_hash"]
    schema = json.loads(
        resource_path("contracts", "dataset-manifest-v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.validate(manifest, schema)
    same = registry.register(
        {
            "schema_version": "data-spec-v1",
            "feeds": [
                {
                    "name": "asset0",
                    "symbol": "ASSET0",
                    "role": "execution",
                    "tradable": True,
                    "source": {
                        "root_id": "prices",
                        "relative_path": "asset0.csv",
                        "source_type": "local_file",
                    },
                    "format": "generic_csv",
                    "columns": {},
                    "timeframe": "days",
                    "compression": 1,
                    "timezone": "UTC",
                    "transforms": [],
                }
            ],
            "master_feed": "asset0",
            "alignment": "intersection",
            "minimum_overlap": 0.9,
            "license": "test-only",
            "sensitivity": "public",
        }
    )
    assert same["dataset_id"] == manifest["dataset_id"]
    preview = registry.preview(manifest["dataset_id"], rows=3)
    assert len(preview["feeds"][0]["sample"]) == 3
    with pytest.raises(ContractError):
        registry.preview(manifest["dataset_id"], rows=51)
    with pytest.raises(PathPolicyError):
        registry.inspect(
            {
                "name": "escape",
                "symbol": "ESC",
                "source": {
                    "root_id": "prices",
                    "relative_path": "../outside.csv",
                },
                "format": "generic_csv",
                "timezone": "UTC",
            }
        )
    source = data_root / "asset0.csv"
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(IntegrityError):
        registry.get_manifest(manifest["dataset_id"])


def test_multi_feed_alignment_rejects_non_overlapping_ranges(tmp_path) -> None:
    target = isolated_target(tmp_path)
    data_root = tmp_path / "data"
    data_root.mkdir()
    first = write_market_csv(data_root / "first.csv")
    second = write_market_csv(data_root / "second.csv")
    second.write_text(
        second.read_text(encoding="utf-8").replace("2024-", "2028-"),
        encoding="utf-8",
    )
    registry = DataRegistry(RuntimePaths(target))
    registry.add_root(data_root, root_id="prices")
    feeds = []
    for name, path in (("first", first), ("second", second)):
        feeds.append(
            {
                "name": name,
                "symbol": name.upper(),
                "role": "execution" if name == "first" else "signal",
                "source": {
                    "root_id": "prices",
                    "relative_path": path.name,
                    "source_type": "local_file",
                },
                "format": "generic_csv",
                "timeframe": "days",
                "timezone": "UTC",
            }
        )
    with pytest.raises(ContractError, match="alignment overlap"):
        registry.register(
            {
                "schema_version": "data-spec-v1",
                "feeds": feeds,
                "master_feed": "first",
                "alignment": "intersection",
                "minimum_overlap": 0.5,
            }
        )
