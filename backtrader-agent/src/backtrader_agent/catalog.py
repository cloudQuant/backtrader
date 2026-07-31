"""Deterministic package-owned corpus catalog and source-attached rebuilder."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .canonical import atomic_write_bytes, hash_object
from .errors import AgentError

TOKEN_RE = re.compile(r"[a-z0-9_]+")
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


def _manifest_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_hash(directory: Path) -> Tuple[str, List[Dict[str, str]]]:
    strategy_files = sorted(
        path
        for path in directory.glob("strategy_*.py")
        if not path.name.startswith(("pybind11_", "python_swig_"))
    )
    candidates = [*strategy_files[:1], directory / "config.yaml", directory / "run.py"]
    files = [
        {"path": path.name, "sha256": _file_hash(path)} for path in candidates if path.is_file()
    ]
    return hash_object(files), files


def _assert_output_outside_source(output: Path, source_roots: Tuple[Path, Path]) -> None:
    output = output.resolve(strict=False)
    for root in source_roots:
        try:
            output.relative_to(root)
        except ValueError:
            continue
        raise AgentError(
            "BTAG-CATALOG-OUTPUT",
            "source-attached snapshot output must be outside both read-only corpus roots",
        )


class SnapshotCatalog:
    def __init__(
        self,
        snapshot_path: Optional[Path] = None,
        template_path: Optional[Path] = None,
    ) -> None:
        resource_root = Path(__file__).resolve().parent / "resources" / "catalog"
        self.snapshot_path = snapshot_path or (resource_root / "corpus-v1.jsonl")
        self.template_path = template_path or (resource_root / "snapshot.jsonl")
        self.manifest, self._entries = self._load_corpus()
        self._templates = self._load_templates()

    def _load_corpus(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        records: List[Dict[str, Any]] = []
        try:
            with self.snapshot_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        item = json.loads(line)
                        if not isinstance(item, dict):
                            raise ValueError("catalog record is not an object")
                        records.append(item)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise AgentError("BTAG-CATALOG-READ", "packaged corpus snapshot is invalid") from exc
        if not records or records[0].get("schema_version") != "corpus-manifest-v1":
            raise AgentError("BTAG-CATALOG-INTEGRITY", "corpus manifest is missing")
        manifest, entries = records[0], records[1:]
        if manifest.get("entry_count") != len(entries):
            raise AgentError("BTAG-CATALOG-INTEGRITY", "corpus entry count is invalid")
        ids = [item.get("canonical_id") for item in entries]
        if len(ids) != len(set(ids)):
            raise AgentError("BTAG-CATALOG-INTEGRITY", "corpus IDs are missing or duplicated")
        for entry in entries:
            payload = dict(entry)
            expected = payload.pop("entry_hash", None)
            if expected != hash_object(payload):
                raise AgentError("BTAG-CATALOG-INTEGRITY", "corpus entry hash is invalid")
            if manifest.get("mode") == "snapshot" and entry.get("source_available") is not False:
                raise AgentError(
                    "BTAG-CATALOG-INTEGRITY",
                    "metadata-only snapshot must not claim source availability",
                )
        if manifest.get("entries") != _manifest_entries(entries):
            raise AgentError(
                "BTAG-CATALOG-INTEGRITY",
                "corpus manifest entries do not match JSONL records",
            )
        expected_snapshot_hash = hash_object(
            {key: value for key, value in manifest.items() if key != "snapshot_hash"}
        )
        if expected_snapshot_hash != manifest.get("snapshot_hash"):
            raise AgentError("BTAG-CATALOG-INTEGRITY", "corpus snapshot hash is invalid")
        return manifest, entries

    def _load_templates(self) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        try:
            with self.template_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        item = json.loads(line)
                        if not isinstance(item, dict):
                            raise ValueError("template entry is not an object")
                        entries.append(item)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise AgentError("BTAG-CATALOG-READ", "packaged template catalog is invalid") from exc
        ids = [item.get("entry_id") for item in entries]
        pairs = [(item.get("archetype"), item.get("profile")) for item in entries]
        if (
            len(entries) != len(ARCHETYPES) * len(PROFILES)
            or len(ids) != len(set(ids))
            or set(pairs)
            != {(archetype, profile) for archetype in ARCHETYPES for profile in PROFILES}
        ):
            raise AgentError(
                "BTAG-CATALOG-INTEGRITY",
                "the fourteen archetype/profile template entries are incomplete",
            )
        return entries

    @staticmethod
    def _tokens(text: str) -> Set[str]:
        return set(TOKEN_RE.findall(text.lower().replace("-", " ").replace("_", " ")))

    def search(
        self,
        query: str,
        *,
        archetype: Optional[str] = None,
        profile: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        if top_k < 1 or top_k > 20:
            raise AgentError("BTAG-CATALOG-LIMIT", "top_k must be between 1 and 20")
        if archetype and archetype not in ARCHETYPES:
            raise AgentError("BTAG-CATALOG-ARCHETYPE", "catalog archetype is unknown")
        if profile and profile not in PROFILES:
            raise AgentError("BTAG-CATALOG-PROFILE", "catalog profile is unknown")
        query_tokens = self._tokens(query)
        ranked: List[Tuple[int, str, Dict[str, Any]]] = []
        for entry in self._entries:
            if archetype and archetype not in entry["archetypes"]:
                continue
            if profile and profile not in entry["profiles"]:
                continue
            searchable = " ".join(
                [
                    entry["canonical_id"],
                    entry["category"],
                    entry["slug"],
                    " ".join(entry["archetypes"]),
                    " ".join(entry.get("risk_tags", [])),
                ]
            )
            tokens = self._tokens(searchable)
            lexical_score = len(query_tokens & tokens) * 10
            if query.lower() in searchable.lower():
                lexical_score += 5
            if query_tokens and lexical_score == 0:
                continue
            score = lexical_score
            if archetype:
                score += 25
            if entry["mapping_status"] == "mapped":
                score += 3
            if not query_tokens:
                score = 1
            ranked.append((-score, entry["canonical_id"], entry))
        ranked.sort(key=lambda value: (value[0], value[1]))
        results = []
        for negative_score, _, entry in ranked[:top_k]:
            public = dict(entry)
            selected_archetype = archetype or entry["archetypes"][0]
            selected_profile = profile or "single_test"
            public.update(
                {
                    "entry_id": entry["canonical_id"],
                    "title": entry["slug"].replace("_", " "),
                    "archetype": selected_archetype,
                    "profile": selected_profile,
                    "source_hash": entry["entry_hash"],
                    "source_path_id": entry["canonical_id"],
                    "summary": (
                        f"{entry['mapping_status']} metadata reference in category "
                        f"{entry['category']}."
                    ),
                    "tags": [
                        entry["category"],
                        entry["mapping_status"],
                        *entry["archetypes"],
                    ],
                }
            )
            public["score"] = -negative_score
            results.append(public)
        return results

    def inspect(self, entry_id: str) -> Dict[str, Any]:
        for entry in self._entries:
            if entry["canonical_id"] == entry_id:
                value = dict(entry)
                value["entry_id"] = entry["canonical_id"]
                value["source_hash"] = entry["entry_hash"]
                return value
        for template in self._templates:
            if template["entry_id"] == entry_id:
                return dict(template)
        raise AgentError("BTAG-CATALOG-UNKNOWN", "catalog entry ID is unknown")

    def templates(
        self,
        *,
        archetype: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if archetype and archetype not in ARCHETYPES:
            raise AgentError("BTAG-CATALOG-ARCHETYPE", "catalog archetype is unknown")
        if profile and profile not in PROFILES:
            raise AgentError("BTAG-CATALOG-PROFILE", "catalog profile is unknown")
        return [
            dict(item)
            for item in self._templates
            if (not archetype or item["archetype"] == archetype)
            and (not profile or item["profile"] == profile)
        ]

    def metadata(self) -> Dict[str, Any]:
        return dict(self.manifest)

    @classmethod
    def refresh_source_attached(
        cls,
        functional_root: Path,
        package_root: Path,
        output: Path,
        *,
        require_verified_counts: bool = True,
    ) -> Dict[str, Any]:
        """Rebuild both corpus adapters without importing or modifying strategy source."""

        functional_root = Path(functional_root).resolve(strict=True)
        package_root = Path(package_root).resolve(strict=True)
        if not functional_root.is_dir() or not package_root.is_dir():
            raise AgentError("BTAG-CATALOG-ROOT", "both corpus roots must be directories")
        output = Path(output)
        _assert_output_outside_source(output, (functional_root, package_root))

        tests: Dict[str, Path] = {}
        for path in sorted(functional_root.rglob("test_*.py")):
            if path.is_symlink():
                continue
            relative = path.relative_to(functional_root)
            stem = path.stem[5:] if path.stem.startswith("test_") else path.stem
            tests[f"{relative.parent.as_posix()}/{stem}"] = path
        packages: Dict[str, Path] = {}
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
        if require_verified_counts and counts != EXPECTED_COUNTS:
            raise AgentError(
                "BTAG-CATALOG-COUNTS",
                f"verified corpus counts changed: expected {EXPECTED_COUNTS}, got {counts}",
            )

        entries: List[Dict[str, Any]] = []
        for canonical_id in sorted(set(tests) | set(packages)):
            category, slug = canonical_id.split("/", maxsplit=1)
            test_path = tests.get(canonical_id)
            package_path = packages.get(canonical_id)
            package_hash = None
            package_files: List[Dict[str, str]] = []
            if package_path is not None:
                package_hash, package_files = _package_hash(package_path)
            entry = {
                "schema_version": "corpus-entry-v1",
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
                        "relative_path": test_path.relative_to(functional_root).as_posix(),
                        "sha256": _file_hash(test_path),
                    }
                    if test_path
                    else None
                ),
                "strategy_package": (
                    {
                        "relative_path": package_path.relative_to(package_root).as_posix(),
                        "sha256": package_hash,
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
            }
            entry["entry_hash"] = hash_object(entry)
            entries.append(entry)
        manifest = {
            "schema_version": "corpus-manifest-v1",
            "corpus_id": "backtrader-agent-source-attached-v1",
            "mode": "source-attached",
            "counts": counts,
            "entry_count": len(entries),
            "entries": _manifest_entries(entries),
            "provenance": {
                "functional_adapter": "functional-test-adapter-v1",
                "package_adapter": "three-file-package-adapter-v1",
                "source_available": True,
            },
            "extensions": {
                "counts": counts,
                "encoding": "jsonl-following-records",
                "entry_count": len(entries),
                "template_count": len(ARCHETYPES) * len(PROFILES),
            },
        }
        manifest["snapshot_hash"] = hash_object(manifest)
        payload = b"\n".join(
            json.dumps(
                item,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            for item in [manifest, *entries]
        )
        atomic_write_bytes(output, payload + b"\n")
        return manifest
