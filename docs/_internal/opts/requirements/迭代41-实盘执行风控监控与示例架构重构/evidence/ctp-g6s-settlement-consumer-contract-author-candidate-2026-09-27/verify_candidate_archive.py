from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent
manifest_path = root / "candidate-manifest.json"
archive_path = root / "candidate-evidence.zip"
manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
sha_line = (root / "candidate-manifest.sha256").read_text(encoding="ascii").strip()
manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
files = manifest["files"]
expected_members = {item["path"] for item in files} | {"candidate-manifest.json", "candidate-manifest.sha256"}
problems = []
for item in files:
    path = root / item["path"]
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != item["size_bytes"] or digest != item["sha256"]:
        problems.append("disk:" + item["path"])
with zipfile.ZipFile(archive_path, "r") as archive:
    names = archive.namelist()
    if len(names) != len(set(names)):
        problems.append("duplicate-members")
    if set(names) != expected_members:
        problems.append("member-set-mismatch")
    if archive.testzip() is not None:
        problems.append("crc-failure")
    for item in files:
        payload = archive.read(item["path"])
        if len(payload) != item["size_bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
            problems.append("zip:" + item["path"])
    zipped_manifest_sha = hashlib.sha256(archive.read("candidate-manifest.json")).hexdigest()
    zipped_sha_line = archive.read("candidate-manifest.sha256").decode("ascii").strip()
if zipped_manifest_sha != manifest_sha:
    problems.append("manifest-copy-mismatch")
if sha_line != f"{manifest_sha}  candidate-manifest.json" or zipped_sha_line != sha_line:
    problems.append("manifest-sha-mismatch")
source_snapshots = json.loads((root / "source-snapshot-verification.json").read_text(encoding="utf-8-sig"))
source_refs = json.loads((root / "source-reference-verification.json").read_text(encoding="utf-8-sig"))
if source_snapshots.get("all_match") is not True or source_snapshots.get("checked_count") != 9:
    problems.append("snapshot-source-verification-failed")
if source_refs.get("all_match") is not True or source_refs.get("checked_count") != 10:
    problems.append("external-source-verification-failed")
print(json.dumps({
    "all_checks_passed": not problems,
    "problems": problems,
    "manifest_sha256": manifest_sha,
    "zip_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
    "manifest_file_count": manifest["file_count"],
    "zip_member_count": len(names),
    "zip_crc_test": "ok" if zipfile.ZipFile(archive_path).testzip() is None else "failed",
}, sort_keys=True, indent=2))
if problems:
    raise SystemExit(1)
