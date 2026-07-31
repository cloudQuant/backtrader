#!/usr/bin/env python
"""Normalize and synchronize the shared metadata-only strategy catalog assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CATALOGS = (
    REPOSITORY_ROOT / "backtrader-skills/resources/snapshots/catalog-v1.jsonl",
    REPOSITORY_ROOT / "backtrader-mcp/src/backtrader_mcp/catalog_snapshot.jsonl",
    REPOSITORY_ROOT / "backtrader-agent/src/backtrader_agent/resources/catalog/corpus-v1.jsonl",
)
AGENT_MANIFEST = (
    REPOSITORY_ROOT / "backtrader-agent/src/backtrader_agent/resources/catalog/corpus-manifest.json"
)


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, float) and value == 0:
        return 0.0
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValueError(f"normalized key collision: {normalized_key!r}")
            normalized[normalized_key] = _normalize(item)
        return normalized
    return value


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _normalize(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _manifest_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": entry["canonical_id"],
            "source": entry["mapping_status"],
            "archetype": entry["archetypes"][0],
            "content_hash": entry["entry_hash"],
            "metadata": {
                "category": entry["category"],
                "jsonl_record": index + 1,
                "mapping_status": entry["mapping_status"],
            },
        }
        for index, entry in enumerate(entries)
    ]


def _build_payload(source: Path) -> tuple[bytes, bytes]:
    records = [
        json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if len(records) < 2:
        raise ValueError(f"catalog has no entries: {source}")
    old_header, entries = records[0], records[1:]
    header = {
        "schema_version": "corpus-manifest-v1",
        "corpus_id": old_header.get("corpus_id", "backtrader-corpus-v1"),
        "mode": "snapshot",
        "entries": _manifest_entries(entries),
        "entry_count": len(entries),
        "counts": old_header["counts"],
        "provenance": old_header["provenance"],
        "extensions": {
            "counts": old_header["counts"],
            "encoding": "jsonl-following-records",
            "entry_count": len(entries),
            "template_count": 14,
        },
    }
    header["snapshot_hash"] = _canonical_hash(header)
    catalog = b"\n".join(_canonical_bytes(item) for item in [header, *entries]) + b"\n"
    manifest = (
        json.dumps(
            header,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    return catalog, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    catalog, agent_manifest = _build_payload(CATALOGS[0])
    failures: list[Path] = []
    for path in CATALOGS:
        if args.check:
            if not path.is_file() or path.read_bytes() != catalog:
                failures.append(path)
        else:
            path.write_bytes(catalog)
    if args.check:
        if not AGENT_MANIFEST.is_file() or AGENT_MANIFEST.read_bytes() != agent_manifest:
            failures.append(AGENT_MANIFEST)
    else:
        AGENT_MANIFEST.write_bytes(agent_manifest)
    for path in failures:
        print(f"catalog copy differs: {path.relative_to(REPOSITORY_ROOT)}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
