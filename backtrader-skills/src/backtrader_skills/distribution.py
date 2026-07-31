"""Build and verify the tracked distribution manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import atomic_write_json, canonical_hash, file_hash, load_json
from .errors import IntegrityError

INCLUDED_ROOTS = (
    "evidence",
    "host_adapters",
    "resources",
    "scripts",
    "skills",
    "src",
)
INCLUDED_FILES = ("IMPLEMENTATION_REPORT.md", "README.md", "pyproject.toml")


def _files(root: Path):
    for name in INCLUDED_FILES:
        path = root / name
        if path.is_file():
            yield path
    for name in INCLUDED_ROOTS:
        directory = root / name
        if not directory.is_dir():
            continue
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            if (
                "__pycache__" in path.parts
                or any(part.endswith(".egg-info") for part in path.parts)
                or path.suffix == ".pyc"
            ):
                continue
            yield path


def build_distribution_manifest(root: Path) -> dict[str, Any]:
    entries = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": file_hash(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(_files(root))
    ]
    manifest = {
        "schema_version": "backtrader-skills-distribution-v1",
        "product": "backtrader-skills",
        "version": "0.1.0",
        "python": ">=3.10,<3.14",
        "backtrader": ">=1.3.0,<2",
        "hosts": ["claude", "codex", "opencode", "openclaw"],
        "canonical_skills": [
            "backtrader-strategy-author",
            "backtrader-strategy-review",
            "backtrader-strategy-test",
        ],
        "files": entries,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    atomic_write_json(root / "manifest.json", manifest)
    return manifest


def verify_distribution_manifest(root: Path) -> dict[str, Any]:
    manifest = load_json(root / "manifest.json")
    expected = manifest.get("manifest_hash")
    payload = dict(manifest)
    payload.pop("manifest_hash", None)
    if expected != canonical_hash(payload):
        raise IntegrityError("distribution manifest hash is invalid")
    current = {
        path.relative_to(root).as_posix(): {
            "sha256": file_hash(path),
            "bytes": path.stat().st_size,
        }
        for path in _files(root)
    }
    recorded = {
        item["path"]: {"sha256": item["sha256"], "bytes": item["bytes"]}
        for item in manifest["files"]
    }
    if current != recorded:
        raise IntegrityError("distribution files differ from manifest")
    return {
        "manifest_hash": expected,
        "file_count": len(recorded),
        "verified": True,
    }
