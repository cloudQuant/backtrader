from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence" / "candidate-manifest.json"
SIDECAR = ROOT / "evidence" / "candidate-manifest.sha256"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


expected_manifest = SIDECAR.read_text(encoding="ascii").split()[0]
if sha256(MANIFEST) != expected_manifest:
    raise SystemExit("manifest hash mismatch")
data = json.loads(MANIFEST.read_text(encoding="utf-8"))
failures = []
for entry in data["files"]:
    path = (ROOT / Path(entry["path"])).resolve()
    if ROOT.resolve() not in path.parents:
        failures.append(f"path escapes root: {entry['path']}")
    elif not path.is_file():
        failures.append(f"missing: {entry['path']}")
    elif path.stat().st_size != entry["size_bytes"] or sha256(path) != entry["sha256"]:
        failures.append(f"changed: {entry['path']}")
if failures:
    raise SystemExit("\n".join(failures))
print(f"VERIFIED_PAYLOADS={len(data['files'])}")
print("MANIFEST_AND_PAYLOADS_PASS")
