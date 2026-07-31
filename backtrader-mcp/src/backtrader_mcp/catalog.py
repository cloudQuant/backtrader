"""Package-owned corpus snapshot, templates, and source-attached catalog refresh."""

from __future__ import annotations

import ast
import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

from .errors import InvalidRequest, NotFound
from .settings import Settings
from .state import StateStore
from .util import file_hash, sha256_json

ARCHETYPES = (
    "single_data_indicator",
    "multi_indicator_system",
    "multi_asset_allocation",
    "multi_timeframe",
    "pairs_spread",
    "order_risk",
    "precomputed_ml",
)
PROFILES = ("single_test", "python_bundle")
EXPECTED_COUNTS = {
    "functional_tests": 1152,
    "strategy_packages": 1035,
    "mapped": 1032,
}
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


def _manifest_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project JSONL corpus records into the product-neutral manifest contract."""

    projected = []
    for index, entry in enumerate(entries):
        metadata: dict[str, Any] = {"jsonl_record": index + 1}
        if entry.get("id") and entry.get("canonical_id"):
            metadata["canonical_id"] = entry["canonical_id"]
        if entry.get("category"):
            metadata["category"] = entry["category"]
        if entry.get("mapping_status"):
            metadata["mapping_status"] = entry["mapping_status"]
        if isinstance(entry.get("source"), dict):
            metadata["source_record"] = entry["source"]
        if entry.get("title"):
            metadata["title"] = entry["title"]
        projected.append(
            {
                "id": entry["id"] if "id" in entry else entry["canonical_id"],
                "source": entry.get("mapping_status", "source-attached"),
                "archetype": (
                    entry["archetype"] if "archetype" in entry else entry["archetypes"][0]
                ),
                "content_hash": entry.get("entry_hash", sha256_json(entry)),
                "metadata": metadata,
            }
        )
    return projected


def _tokens(value: str) -> set[str]:
    return {item for item in re.split(r"[^a-z0-9]+", value.casefold().replace("_", " ")) if item}


def _load_packaged_snapshot() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    resource = files("backtrader_mcp").joinpath("catalog_snapshot.jsonl")
    records = [
        json.loads(line)
        for line in resource.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not records or records[0].get("schema_version") != "corpus-manifest-v1":
        raise InvalidRequest("packaged catalog manifest is missing")
    header, entries = records[0], records[1:]
    if header.get("entry_count") != len(entries):
        raise InvalidRequest("packaged catalog entry count is invalid")
    for entry in entries:
        payload = dict(entry)
        expected = payload.pop("entry_hash", None)
        if expected != sha256_json(payload):
            raise InvalidRequest(
                f"packaged catalog entry hash is invalid: {entry.get('canonical_id')}"
            )
        if entry.get("source_available") is not False:
            raise InvalidRequest("packaged metadata must not claim source availability")
    if header.get("entries") != _manifest_entries(entries):
        raise InvalidRequest("packaged catalog manifest entries do not match JSONL records")
    expected_snapshot_hash = sha256_json(
        {key: value for key, value in header.items() if key != "snapshot_hash"}
    )
    if expected_snapshot_hash != header.get("snapshot_hash"):
        raise InvalidRequest("packaged catalog snapshot hash is invalid")
    return header, entries


def _package_hash(directory: Path) -> tuple[str, list[dict[str, str]]]:
    strategy_files = sorted(
        path
        for path in directory.glob("strategy_*.py")
        if not path.name.startswith(("pybind11_", "python_swig_"))
    )
    candidates = [*strategy_files[:1], directory / "config.yaml", directory / "run.py"]
    package_files = [
        {"path": path.name, "sha256": file_hash(path)} for path in candidates if path.is_file()
    ]
    return sha256_json(package_files), package_files


def _build_source_attached_entries(
    functional_root: Path,
    package_root: Path,
    functional_root_id: str,
    package_root_id: str,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Rebuild the two verified metadata adapters without importing corpus code."""

    tests: dict[str, Path] = {}
    for path in sorted(functional_root.rglob("test_*.py")):
        if path.is_symlink():
            continue
        relative = path.relative_to(functional_root)
        stem = path.stem[5:] if path.stem.startswith("test_") else path.stem
        tests[f"{relative.parent.as_posix()}/{stem}"] = path
    packages: dict[str, Path] = {}
    for path in sorted(package_root.glob("*/*")):
        strategy_files = [
            item
            for item in path.glob("strategy_*.py")
            if not item.name.startswith(("pybind11_", "python_swig_"))
        ]
        if (
            path.is_dir()
            and not path.is_symlink()
            and (path / "run.py").is_file()
            and strategy_files
        ):
            packages[f"{path.parent.name}/{path.name}"] = path
    mapped = set(tests) & set(packages)
    counts = {
        "functional_tests": len(tests),
        "strategy_packages": len(packages),
        "mapped": len(mapped),
    }
    entries: list[dict[str, Any]] = []
    for canonical_id in sorted(set(tests) | set(packages)):
        category, slug = canonical_id.split("/", maxsplit=1)
        test_path = tests.get(canonical_id)
        package_path = packages.get(canonical_id)
        package_sha = None
        package_files: list[dict[str, str]] = []
        if package_path is not None:
            package_sha, package_files = _package_hash(package_path)
        stable_key = {
            "functional_root_id": functional_root_id,
            "package_root_id": package_root_id,
            "canonical_id": canonical_id,
        }
        entry = {
            "schema_version": "corpus-entry-v1",
            "id": f"source-{sha256_json(stable_key)}",
            "canonical_id": canonical_id,
            "category": category,
            "slug": slug,
            "archetypes": (
                list(ARCHETYPES)
                if category in MULTI_LABEL_CATEGORIES
                else [CATEGORY_ARCHETYPE.get(category, "single_data_indicator")]
            ),
            "profiles": list(PROFILES),
            "functional_test": (
                {
                    "root_id": functional_root_id,
                    "relative_path": test_path.relative_to(functional_root).as_posix(),
                    "sha256": file_hash(test_path),
                }
                if test_path
                else None
            ),
            "strategy_package": (
                {
                    "root_id": package_root_id,
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
            "source_available": True,
            "dependencies": [],
            "risk_tags": (["multi_label_review"] if category in MULTI_LABEL_CATEGORIES else []),
            "source": {
                "mode": "dual_corpus",
                "functional_root_id": functional_root_id,
                "package_root_id": package_root_id,
            },
        }
        entry["entry_hash"] = sha256_json(entry)
        entries.append(entry)
    return counts, entries


class CatalogService:
    def __init__(self, settings: Settings, state: StateStore) -> None:
        self.settings = settings
        self.state = state
        self.snapshot, self.entries = _load_packaged_snapshot()
        template_path = files("backtrader_mcp").joinpath("catalog_snapshot.json")
        self.template_catalog: dict[str, Any] = json.loads(
            template_path.read_text(encoding="utf-8")
        )
        self.snapshot_hash = self.snapshot["snapshot_hash"]

    def get_snapshot(self) -> dict[str, Any]:
        return dict(self.snapshot)

    def get_entry(self, entry_id: str) -> dict[str, Any]:
        for entry in self.entries:
            if entry["canonical_id"] == entry_id:
                return {
                    **entry,
                    "snapshot_hash": self.snapshot_hash,
                    "corpus_id": self.get_snapshot()["corpus_id"],
                }
        raise NotFound(f"catalog entry not found: {entry_id}")

    def search(
        self, query: str = "", archetype: str | None = None, limit: int = 20
    ) -> dict[str, Any]:
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise InvalidRequest("catalog search limit must be between 1 and 100")
        if archetype is not None and archetype not in ARCHETYPES:
            raise InvalidRequest(f"unknown archetype: {archetype}")
        terms = _tokens(query)
        ranked: list[tuple[int, str, dict[str, Any], list[str]]] = []
        entries = list(self.entries)
        entries.extend(self.state.list("catalog_entry"))
        for entry in entries:
            archetypes = entry.get("archetypes", [entry.get("archetype")])
            archetypes = [value for value in archetypes if value]
            if archetype is not None and archetype not in archetypes:
                continue
            entry_id = entry.get("canonical_id", entry.get("id", ""))
            searchable = " ".join(
                [
                    entry_id,
                    entry.get("category", ""),
                    entry.get("slug", ""),
                    entry.get("title", ""),
                    entry.get("summary", ""),
                    *entry.get("tags", []),
                    *archetypes,
                ]
            )
            overlap = terms & _tokens(searchable)
            lexical_score = len(overlap) * 10
            reasons = []
            if overlap:
                reasons.append(f"lexical tokens: {', '.join(sorted(overlap))}")
            if terms and lexical_score == 0:
                continue
            score = lexical_score
            if archetype is not None:
                score += 25
                reasons.append(f"archetype: {archetype}")
            if entry.get("mapping_status") == "mapped":
                score += 3
                reasons.append("mapped across both verified corpora")
            ranked.append((-score, entry_id, entry, reasons))
        ranked.sort(key=lambda item: (item[0], item[1]))
        return {
            "query": query,
            "archetype": archetype,
            "snapshot_hash": self.snapshot_hash,
            "corpus_id": self.get_snapshot()["corpus_id"],
            "entries": [
                {
                    **entry,
                    "strategy_id": entry.get("id", entry_id),
                    "score": -score,
                    "match_reasons": reasons,
                }
                for score, entry_id, entry, reasons in ranked[:limit]
            ],
        }

    def list_templates(self) -> dict[str, Any]:
        templates = [
            {
                "template_id": f"{entry['archetype']}:{profile}",
                "archetype": entry["archetype"],
                "output_profile": profile,
                "catalog_entry_id": entry["id"],
            }
            for entry in self.template_catalog["entries"]
            for profile in PROFILES
        ]
        return {
            "schema_version": "strategy-template-list-v1",
            "count": len(templates),
            "templates": templates,
            "snapshot_hash": self.snapshot_hash,
        }

    def refresh_source_catalog(
        self,
        source_root_id: str,
        expected_previous_snapshot_hash: str | None = None,
        package_root_id: str | None = None,
    ) -> dict[str, Any]:
        if package_root_id is not None:
            return self._refresh_dual_corpus(
                source_root_id, package_root_id, expected_previous_snapshot_hash
            )
        root = self.settings.target_roots.get(source_root_id)
        if root is None:
            raise NotFound(f"source-attached strategy root not registered: {source_root_id}")
        root = root.resolve(strict=True)
        previous = self.state.maybe_get("catalog_source", source_root_id)
        if expected_previous_snapshot_hash is not None and (
            previous is None or previous["snapshot_hash"] != expected_previous_snapshot_hash
        ):
            raise InvalidRequest("source catalog snapshot precondition is stale")
        entries: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        python_files = sorted(root.rglob("*.py"))
        if len(python_files) > 5000:
            raise InvalidRequest("source-attached catalog exceeds the 5000-file P0 limit")
        for path in python_files:
            if path.is_symlink():
                diagnostics.append(
                    {
                        "code": "symlink_skipped",
                        "relative_path": str(path.relative_to(root)),
                    }
                )
                continue
            relative = str(path.relative_to(root))
            content = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(content, filename=relative)
            except SyntaxError as exc:
                diagnostics.append(
                    {
                        "code": "syntax_error",
                        "relative_path": relative,
                        "line": exc.lineno,
                    }
                )
                continue
            imports = sorted(
                {
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Import)
                    for alias in node.names
                }
                | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            )
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = {
                    (
                        base.id
                        if isinstance(base, ast.Name)
                        else base.attr if isinstance(base, ast.Attribute) else ""
                    )
                    for base in node.bases
                }
                if "Strategy" not in bases:
                    continue
                stable_key = {
                    "root_id": source_root_id,
                    "relative_path": relative,
                    "class_name": node.name,
                }
                entry_id = f"source-{sha256_json(stable_key)}"
                entries.append(
                    {
                        "id": entry_id,
                        "archetype": "single_data_indicator",
                        "title": node.name,
                        "tags": ["source-attached", "strategy"],
                        "summary": f"Static source-attached strategy {node.name}.",
                        "source": {
                            **stable_key,
                            "source_sha256": file_hash(path),
                            "imports": imports,
                            "methods": sorted(
                                child.name
                                for child in node.body
                                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                            ),
                        },
                    }
                )
        entries.sort(key=lambda entry: entry["id"])
        snapshot = {
            "schema_version": "corpus-manifest-v1",
            "corpus_id": f"backtrader-mcp-source-{source_root_id}",
            "mode": "source-attached",
            "entries": _manifest_entries(entries),
            "entry_count": len(entries),
            "counts": {"source_strategies": len(entries)},
            "provenance": {
                "product": "backtrader-mcp",
                "source_available": True,
                "source_root_id": source_root_id,
            },
            "extensions": {
                "diagnostics": diagnostics,
                "entry_count": len(entries),
                "source_root_id": source_root_id,
            },
        }
        snapshot["snapshot_hash"] = sha256_json(snapshot)
        for entry in entries:
            self.state.put("catalog_entry", entry["id"], entry, replace=True)
        self.state.put("catalog_source", source_root_id, snapshot, replace=True)
        self.state.audit(
            "catalog.refreshed",
            source_root_id,
            {"snapshot_hash": snapshot["snapshot_hash"], "entry_count": len(entries)},
        )
        return snapshot

    def _refresh_dual_corpus(
        self,
        functional_root_id: str,
        package_root_id: str,
        expected_previous_snapshot_hash: str | None,
    ) -> dict[str, Any]:
        functional_root = self.settings.source_roots.get(functional_root_id)
        package_root = self.settings.source_roots.get(package_root_id)
        if functional_root is None or package_root is None:
            raise NotFound("both source-attached corpus root IDs must be registered read-only")
        functional_root = functional_root.resolve(strict=True)
        package_root = package_root.resolve(strict=True)
        state_id = f"{functional_root_id}:{package_root_id}"
        previous = self.state.maybe_get("catalog_source", state_id)
        if expected_previous_snapshot_hash is not None and (
            previous is None or previous["snapshot_hash"] != expected_previous_snapshot_hash
        ):
            raise InvalidRequest("source catalog snapshot precondition is stale")
        counts, entries = _build_source_attached_entries(
            functional_root,
            package_root,
            functional_root_id,
            package_root_id,
        )
        diagnostics = []
        if counts != EXPECTED_COUNTS:
            diagnostics.append(
                {
                    "code": "verified_baseline_count_mismatch",
                    "expected": EXPECTED_COUNTS,
                    "actual": counts,
                }
            )
        snapshot = {
            "schema_version": "corpus-manifest-v1",
            "corpus_id": f"backtrader-mcp-source-{state_id}",
            "mode": "source-attached",
            "counts": counts,
            "entry_count": len(entries),
            "entries": _manifest_entries(entries),
            "provenance": {
                "product": "backtrader-mcp",
                "source_available": True,
                "functional_root_id": functional_root_id,
                "package_root_id": package_root_id,
            },
            "extensions": {
                "diagnostics": diagnostics,
                "entry_count": len(entries),
                "functional_root_id": functional_root_id,
                "package_root_id": package_root_id,
            },
        }
        snapshot["snapshot_hash"] = sha256_json(snapshot)
        for entry in entries:
            self.state.put("catalog_entry", entry["id"], entry, replace=True)
        self.state.put("catalog_source", state_id, snapshot, replace=True)
        self.state.audit(
            "catalog.dual_corpus_refreshed",
            state_id,
            {
                "snapshot_hash": snapshot["snapshot_hash"],
                "entry_count": len(entries),
                "counts": counts,
            },
        )
        return snapshot

    def inspect_strategy(
        self, strategy_id: str, expected_source_hash: str | None = None
    ) -> dict[str, Any]:
        for entry in self.entries:
            if entry["canonical_id"] == strategy_id:
                return {
                    "schema_version": "strategy-inspection-v1",
                    "status": "ready",
                    "strategy": entry,
                    "source_attached": False,
                }
        entry = self.state.get("catalog_entry", strategy_id)
        source = entry["source"]
        if source.get("mode") == "dual_corpus":
            if expected_source_hash is not None and expected_source_hash != entry["entry_hash"]:
                raise InvalidRequest("strategy source hash precondition is stale")
            diagnostics = []
            functional = entry.get("functional_test")
            if functional:
                root = self.settings.source_roots.get(functional["root_id"])
                path = (
                    root / functional["relative_path"] if root is not None else Path("__missing__")
                )
                if not path.is_file() or file_hash(path) != functional["sha256"]:
                    diagnostics.append({"code": "functional_source_changed_since_refresh"})
            package = entry.get("strategy_package")
            if package:
                root = self.settings.source_roots.get(package["root_id"])
                directory = (
                    root / package["relative_path"] if root is not None else Path("__missing__")
                )
                current_hash = _package_hash(directory)[0] if directory.is_dir() else "__MISSING__"
                if current_hash != package["sha256"]:
                    diagnostics.append({"code": "package_source_changed_since_refresh"})
            return {
                "schema_version": "strategy-inspection-v1",
                "status": "stale" if diagnostics else "ready",
                "strategy": entry,
                "source_attached": True,
                "diagnostics": diagnostics,
            }
        root = self.settings.target_roots.get(source["root_id"])
        if root is None:
            raise NotFound("source-attached root is no longer registered")
        path = (root / source["relative_path"]).resolve(strict=True)
        current_hash = file_hash(path)
        if expected_source_hash is not None and current_hash != expected_source_hash:
            raise InvalidRequest("strategy source hash precondition is stale")
        return {
            "schema_version": "strategy-inspection-v1",
            "status": "ready" if current_hash == source["source_sha256"] else "stale",
            "strategy": entry,
            "source_attached": True,
            "current_source_sha256": current_hash,
            "diagnostics": (
                []
                if current_hash == source["source_sha256"]
                else [{"code": "source_changed_since_refresh"}]
            ),
        }
