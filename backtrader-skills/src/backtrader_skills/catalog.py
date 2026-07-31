"""Static corpus catalog construction and deterministic lexical search."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from .canonical import atomic_write_bytes, canonical_bytes, canonical_hash, file_hash
from .errors import ContractError, IntegrityError
from .ir import ARCHETYPES, OUTPUT_PROFILES

CATEGORY_ARCHETYPE = {
    "asset_allocation": "multi_asset_allocation",
    "rotation": "multi_asset_allocation",
    "pairs_trading": "pairs_spread",
    "order_types": "order_risk",
    "risk_management": "order_risk",
    "options": "order_risk",
    "machine_learning": "precomputed_ml",
    "forecasting": "precomputed_ml",
    "sentiment": "precomputed_ml",
    "time_based": "multi_timeframe",
    "time_session_system": "multi_timeframe",
    "multi_indicator": "multi_indicator_system",
    "multi_indicator_system": "multi_indicator_system",
    "pivot_fibonacci_system": "multi_indicator_system",
}
MULTI_LABEL_CATEGORIES = {"advanced", "special", "misc", "others"}
EXPECTED_COUNTS = {
    "functional_tests": 1152,
    "strategy_packages": 1035,
    "mapped": 1032,
}


def _manifest_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project JSONL corpus records into the product-neutral manifest contract."""

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


def _archetype(category: str) -> str:
    return CATEGORY_ARCHETYPE.get(category, "single_data_indicator")


def _tokens(value: str) -> set[str]:
    return {item for item in re.split(r"[^a-z0-9]+", value.lower().replace("_", " ")) if item}


def _package_hash(directory: Path) -> tuple[str, list[dict[str, str]]]:
    files = []
    strategy_files = sorted(
        path
        for path in directory.glob("strategy_*.py")
        if not path.name.startswith(("pybind11_", "python_swig_"))
    )
    candidates = [*strategy_files[:1], directory / "config.yaml", directory / "run.py"]
    for path in candidates:
        if path.is_file():
            files.append({"path": path.name, "sha256": file_hash(path)})
    return canonical_hash(files), files


def build_snapshot(
    functional_root: Path,
    package_root: Path,
    output: Path,
    *,
    require_expected_counts: bool = True,
) -> dict[str, Any]:
    """Build metadata only; never import or execute corpus files."""

    tests: dict[str, Path] = {}
    for path in sorted(functional_root.rglob("test_*.py")):
        relative = path.relative_to(functional_root)
        stem = path.stem[5:] if path.stem.startswith("test_") else path.stem
        canonical_id = f"{relative.parent.as_posix()}/{stem}"
        tests[canonical_id] = path
    packages: dict[str, Path] = {}
    for path in sorted(package_root.glob("*/*")):
        source_files = [
            item
            for item in path.glob("strategy_*.py")
            if not item.name.startswith(("pybind11_", "python_swig_"))
        ]
        if path.is_dir() and (path / "run.py").is_file() and source_files:
            packages[f"{path.parent.name}/{path.name}"] = path
    mapped = set(tests) & set(packages)
    counts = {
        "functional_tests": len(tests),
        "strategy_packages": len(packages),
        "mapped": len(mapped),
    }
    if require_expected_counts and counts != EXPECTED_COUNTS:
        raise IntegrityError(f"catalog counts changed: expected {EXPECTED_COUNTS}, got {counts}")
    entries: list[dict[str, Any]] = []
    for canonical_id in sorted(set(tests) | set(packages)):
        category, slug = canonical_id.split("/", maxsplit=1)
        test_path = tests.get(canonical_id)
        package_path = packages.get(canonical_id)
        package_sha = None
        package_files: list[dict[str, str]] = []
        if package_path:
            package_sha, package_files = _package_hash(package_path)
        entry = {
            "schema_version": "corpus-entry-v1",
            "canonical_id": canonical_id,
            "category": category,
            "slug": slug,
            "archetypes": (
                list(ARCHETYPES) if category in MULTI_LABEL_CATEGORIES else [_archetype(category)]
            ),
            "profiles": list(OUTPUT_PROFILES),
            "functional_test": (
                {
                    "relative_path": test_path.relative_to(functional_root).as_posix(),
                    "sha256": file_hash(test_path),
                }
                if test_path
                else None
            ),
            "strategy_package": (
                {
                    "relative_path": package_path.relative_to(package_root).as_posix(),
                    "sha256": package_sha,
                    "files": package_files,
                }
                if package_path
                else None
            ),
            "mapping_status": (
                "mapped"
                if canonical_id in mapped
                else "functional_only" if test_path else "package_only"
            ),
            "source_available": False,
            "dependencies": [],
            "risk_tags": (["multi_label_review"] if category in MULTI_LABEL_CATEGORIES else []),
        }
        entry["entry_hash"] = canonical_hash(entry)
        entries.append(entry)
    header = {
        "schema_version": "corpus-manifest-v1",
        "corpus_id": "backtrader-corpus-v1",
        "mode": "snapshot",
        "counts": counts,
        "entry_count": len(entries),
        "entries": _manifest_entries(entries),
        "provenance": {
            "functional_adapter": "functional-test-adapter-v1",
            "package_adapter": "three-file-package-adapter-v1",
            "source_available": False,
        },
        "extensions": {
            "counts": counts,
            "encoding": "jsonl-following-records",
            "entry_count": len(entries),
            "template_count": len(ARCHETYPES) * len(OUTPUT_PROFILES),
        },
    }
    header["snapshot_hash"] = canonical_hash(header)
    payload = b"\n".join(canonical_bytes(item) for item in [header, *entries]) + b"\n"
    atomic_write_bytes(output, payload)
    return header


def load_snapshot(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    if not records or records[0].get("schema_version") != "corpus-manifest-v1":
        raise ContractError("catalog snapshot header is missing")
    header, entries = records[0], records[1:]
    if header["entry_count"] != len(entries):
        raise IntegrityError("catalog snapshot entry count is invalid")
    for entry in entries:
        payload = dict(entry)
        expected = payload.pop("entry_hash", None)
        if expected != canonical_hash(payload):
            raise IntegrityError(f"catalog entry hash is invalid: {entry.get('canonical_id')}")
    if header.get("entries") != _manifest_entries(entries):
        raise IntegrityError("catalog manifest entries do not match JSONL records")
    expected_snapshot_hash = canonical_hash(
        {key: item for key, item in header.items() if key != "snapshot_hash"}
    )
    if expected_snapshot_hash != header["snapshot_hash"]:
        raise IntegrityError("catalog snapshot hash is invalid")
    return header, entries


def search_snapshot(
    path: Path,
    query: str,
    *,
    archetype: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    if limit < 1 or limit > 10:
        raise ContractError("catalog search limit must be between 1 and 10")
    if archetype is not None and archetype not in ARCHETYPES:
        raise ContractError(f"unknown archetype: {archetype}")
    header, entries = load_snapshot(path)
    query_tokens = _tokens(query)
    ranked: list[tuple[int, str, dict[str, Any], list[str]]] = []
    for entry in entries:
        reasons = []
        entry_tokens = _tokens(
            " ".join(
                [
                    entry["canonical_id"],
                    entry["category"],
                    entry["slug"],
                    *entry["archetypes"],
                ]
            )
        )
        overlap = query_tokens & entry_tokens
        score = len(overlap) * 10
        if overlap:
            reasons.append(f"lexical tokens: {', '.join(sorted(overlap))}")
        if archetype and archetype in entry["archetypes"]:
            score += 25
            reasons.append(f"archetype: {archetype}")
        if entry["mapping_status"] == "mapped":
            score += 3
            reasons.append("mapped across both verified corpora")
        if score > 0 or not query_tokens:
            ranked.append((score, entry["canonical_id"], entry, reasons))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = ranked[:limit]
    template_archetype = archetype or (
        selected[0][2]["archetypes"][0] if selected else "single_data_indicator"
    )
    return {
        "schema_version": "catalog-search-result-v1",
        "snapshot_hash": header["snapshot_hash"],
        "mode": "snapshot",
        "template": {
            "archetype": template_archetype,
            "profiles": list(OUTPUT_PROFILES),
            "current_fork_compliant": True,
        },
        "results": [
            {
                "canonical_id": entry["canonical_id"],
                "score": score,
                "match_reasons": reasons,
                "mapping_status": entry["mapping_status"],
                "source_available": False,
                "entry_hash": entry["entry_hash"],
                "risk_tags": entry["risk_tags"],
                "recommended_profile": "single_test",
            }
            for score, _, entry, reasons in selected
        ],
    }


def iter_catalog_ids(path: Path) -> Iterable[str]:
    _, entries = load_snapshot(path)
    return (entry["canonical_id"] for entry in entries)
