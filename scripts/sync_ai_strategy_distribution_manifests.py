#!/usr/bin/env python
"""Refresh deterministic distribution manifests after product payload changes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = REPOSITORY_ROOT / "backtrader-agent"
AGENT_SOURCE = AGENT_ROOT / "src" / "backtrader_agent"
AGENT_PACKAGE_MANIFEST = AGENT_SOURCE / "resources" / "distribution-manifest.json"
AGENT_PRODUCT_MANIFEST = AGENT_ROOT / "manifest.json"


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8") + b"\n"


def _agent_package_files() -> list[Path]:
    return [
        path
        for path in sorted(AGENT_SOURCE.rglob("*"))
        if path.is_file()
        and path != AGENT_PACKAGE_MANIFEST
        and "__pycache__" not in path.parts
        and not any(part.endswith(".egg-info") for part in path.parts)
        and path.suffix != ".pyc"
    ]


def _agent_product_files() -> list[Path]:
    excluded_parts = {"__pycache__", ".pytest_cache", "dist", "build"}
    return [
        path
        for path in sorted(AGENT_ROOT.rglob("*"))
        if path.is_file()
        and path != AGENT_PRODUCT_MANIFEST
        and not excluded_parts.intersection(path.parts)
        and not any(part.endswith(".egg-info") for part in path.parts)
        and path.suffix != ".pyc"
    ]


def _build_agent_package_manifest() -> bytes:
    files = {
        path.relative_to(AGENT_SOURCE).as_posix(): _hash(path) for path in _agent_package_files()
    }
    return _json_bytes(
        {
            "compatibility": {
                "backtrader": "source fork or compatible installed distribution",
                "python": ">=3.8",
            },
            "files": files,
            "hash_algorithm": "sha256",
            "manifest_excludes": ["resources/distribution-manifest.json"],
            "product": "backtrader-agent",
            "schema_version": "distribution-manifest-v1",
            "version": "0.1.0",
        }
    )


def _build_agent_product_manifest() -> bytes:
    files = {
        path.relative_to(AGENT_ROOT).as_posix(): _hash(path) for path in _agent_product_files()
    }
    return _json_bytes(
        {
            "schema_version": "distribution-manifest-v1",
            "product": "backtrader-agent",
            "version": "0.1.0",
            "compatibility": {
                "python": ">=3.8",
                "backtrader": "source fork or compatible installed distribution",
                "hosts": ["claude-code", "codex", "opencode", "openclaw"],
            },
            "hash_algorithm": "sha256",
            "manifest_excludes": ["manifest.json"],
            "file_count": len(files),
            "files": files,
        }
    )


def _sync_file(path: Path, payload: bytes, *, check: bool) -> bool:
    if check:
        return path.is_file() and path.read_bytes() == payload
    path.write_bytes(payload)
    return True


def _sync_skills(*, check: bool) -> bool:
    skills_root = REPOSITORY_ROOT / "backtrader-skills"
    sys.path.insert(0, str(skills_root / "src"))
    from backtrader_skills.distribution import (
        build_distribution_manifest,
        verify_distribution_manifest,
    )

    if check:
        try:
            verify_distribution_manifest(skills_root)
        except Exception:
            return False
    else:
        build_distribution_manifest(skills_root)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    failures: list[str] = []
    if not args.check:
        AGENT_PACKAGE_MANIFEST.write_bytes(_build_agent_package_manifest())
    elif AGENT_PACKAGE_MANIFEST.read_bytes() != _build_agent_package_manifest():
        failures.append("backtrader-agent package manifest")
    if not _sync_file(
        AGENT_PRODUCT_MANIFEST,
        _build_agent_product_manifest(),
        check=args.check,
    ):
        failures.append("backtrader-agent product manifest")
    if not _sync_skills(check=args.check):
        failures.append("backtrader-skills product manifest")
    for failure in failures:
        print(f"distribution manifest differs: {failure}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
