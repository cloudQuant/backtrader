#!/usr/bin/env python
"""Re-issue the folder-local admission manifests for the 012_x candidates.

Iteration 30 made ``examples/012_1_midfreq_cross_exchange`` and
``examples/012_2_event_driven_cross_exchange`` self-contained: each folder now
carries a byte-identical copy of the admission policy plus a manifest whose
paths are folder-relative and whose source hashes are computed from that
folder's own files.

The repository-canonical manifest stays the authority for the *demo* path, so
this script never rewrites ``examples/strategy-candidate-manifest.json`` and
never changes an admission status: it only re-issues a working copy whose
identity matches the folder it lives in.

Usage::

    python scripts/refresh_cross_exchange_local_manifests.py [--check]

``--check`` verifies the committed copies without writing (exit code 1 when a
copy is stale), which is what the unit contract uses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
CANONICAL_MANIFEST = EXAMPLES / "strategy-candidate-manifest.json"
CANDIDATE_FOLDERS = (
    "012_1_midfreq_cross_exchange",
    "012_2_event_driven_cross_exchange",
)
LOCAL_MANIFEST_NAME = "strategy-candidate-manifest.json"
_FROZEN_FIELDS = ("runner_sha256", "strategy_sha256", "config_sha256")


def canonical_sha256(value: Mapping[str, Any]) -> str:
    """Hash a mapping the way the example runners do."""

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    """Hash one file byte-for-byte."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_payload(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Return the candidate payload a fingerprint is computed over."""

    return {
        key: value
        for key, value in candidate.items()
        if key not in {"candidate_sha256", "demo_approval"}
    }


def local_manifest(folder: str, canonical: Mapping[str, Any]) -> dict[str, Any]:
    """Build the folder-local manifest for one candidate folder."""

    folder_path = EXAMPLES / folder
    rows = [
        row
        for row in canonical.get("candidates", [])
        if isinstance(row, Mapping) and row.get("strategy_id") == folder
    ]
    if len(rows) != 1:
        raise SystemExit(f"canonical manifest must contain exactly one {folder} candidate")
    candidate = dict(rows[0])
    local = dict(canonical)
    candidate["resolved_example_path"] = "."
    for field, name in (
        ("runner_sha256", candidate["entrypoint"]),
        ("strategy_sha256", candidate["strategy_module"]),
        ("config_sha256", "config.yaml"),
    ):
        target = folder_path / str(name)
        if not target.is_file():
            raise SystemExit(f"{target} is missing")
        candidate[field] = file_sha256(target)
    candidate["candidate_sha256"] = canonical_sha256(candidate_payload(candidate))
    local["candidates"] = [candidate]
    return local


def _as_json(document: Mapping[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify without writing")
    args = parser.parse_args(argv)

    canonical = json.loads(CANONICAL_MANIFEST.read_text(encoding="utf-8"))
    stale: list[str] = []
    for folder in CANDIDATE_FOLDERS:
        target = EXAMPLES / folder / LOCAL_MANIFEST_NAME
        expected = _as_json(local_manifest(folder, canonical))
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current == expected:
            print(f"{folder}: up to date")
            continue
        stale.append(folder)
        if args.check:
            print(f"{folder}: STALE")
        else:
            target.write_text(expected, encoding="utf-8")
            print(f"{folder}: re-issued")
    if args.check and stale:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
