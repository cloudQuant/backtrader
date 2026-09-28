from __future__ import annotations
import hashlib
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "candidate-manifest.json"
SIDECAR = ROOT / "evidence" / "candidate-manifest.sha256"
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".benchmarks", ".mypy_cache"}
EXCLUDED_FILES = {OUT.name, SIDECAR.name}
def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
files = []
for path in sorted(ROOT.rglob("*")):
    if not path.is_file():
        continue
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        continue
    if path.name in EXCLUDED_FILES or path.suffix.lower() in {".pyc", ".pyo"}:
        continue
    files.append({"path": relative.as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256(path)})
manifest = {
    "candidate": "ctp-account-actor-main-store-wiring-r2a",
    "status": "AUTHOR_CANDIDATE_NO_WRITE",
    "main_production_source_edited_by_candidate": False,
    "parent_r2_manifest_sha256": "5b68f9ed2a457e51941bbd60052a100d2e045907b9b2e3bb454482304badd27a",
    "base_store_sha256": "dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826",
    "r2_parent_store_sha256": "a25edc57d4a4ac225b1b152a2672ff2b108b3c497cef05cd46a8fb22c1e586b8",
    "candidate_store_sha256": "18a02f00ec3b2031932284c9e855395c1c70c3e448dbafcd054e4f079048c4d0",
    "candidate_test_sha256": "6b8eab8156f40e5b14403e4063b323386edb3671e9c614c882604e2c02f6ca4b",
    "r2a_patch_sha256": "7708df2f0923b74e5f95315390580eb417e9ca05cfa4c6fe41422bc410908e99",
    "verification": {
        "explicit_env_custom_object_negative_focus": "4 passed",
        "candidate_boundary_plus_live_guard": "18 passed",
        "candidate_plus_managed_execution_plus_live_guard": "25 passed",
        "legacy_30_test_candidate": "9 passed, 21 failed at intentional CTP actor-unavailable gate",
        "legacy_30_test_exact_base": "30 passed; see frozen r1 audit log",
        "ruff": "passed",
        "py_compile": "passed",
        "exact_parent_r2_patch_replay": "passed",
        "external_actor_dispatch": False,
        "caller_actor_port_authority": False,
        "local_ctp_sdk_or_queue": False,
        "default_runtime_route_or_write_authority": False,
        "real_acceptance": False,
    },
    "files": files,
}
OUT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
manifest_hash = sha256(OUT)
SIDECAR.write_text(f"{manifest_hash}  {OUT.name}\n", encoding="ascii")
print(f"manifest_sha256={manifest_hash}")
print(f"inventory_files={len(files)}")
