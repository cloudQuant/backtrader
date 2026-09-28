from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "candidate-manifest.json"
MANIFEST_SHA = ROOT / "candidate-manifest.sha256"
ARCHIVE = ROOT / "candidate-evidence.zip"
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDED_FILES = {MANIFEST.name, MANIFEST_SHA.name, ARCHIVE.name}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def listed_files() -> list[dict[str, object]]:
    result = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if path.suffix == ".pyc" or path.name in EXCLUDED_FILES:
            continue
        result.append({
            "path": path.relative_to(ROOT).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    return result


def main() -> None:
    body = {
        "schema": "iteration41.g6s.settlement_consumer_candidate_manifest.v1",
        "classification": "FAKE_ONLY / NO_RELEASE / G6-S CLOSED / G7-S CLOSED",
        "captured_date": "2026-09-27",
        "file_count": 0,
        "files": [],
        "external_provenance": "source-inputs.json binds the read-only source snapshots and frozen SDK/wheelhouse inputs.",
    }
    body["files"] = listed_files()
    body["file_count"] = len(body["files"])
    encoded = (json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    MANIFEST.write_bytes(encoded)
    MANIFEST_SHA.write_text(f"{hashlib.sha256(encoded).hexdigest()}  {MANIFEST.name}\n", encoding="ascii")
    include = [ROOT / item["path"] for item in body["files"]]
    include.extend([MANIFEST, MANIFEST_SHA])
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in include:
            archive.write(path, path.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
