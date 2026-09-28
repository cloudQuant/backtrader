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
    files.append(
        {
            "path": relative.as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
    )

manifest = {
    "candidate": "ctp-account-actor-main-store-wiring-r1",
    "status": "AUTHOR_CANDIDATE_NO_WRITE",
    "main_production_source_edited_by_candidate": False,
    "base_store_sha256": "dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826",
    "frozen_r4_manifest_sha256": "8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8",
    "frozen_r4_actor_module_sha256": "e0d3147ec7ce867ec96f29e5dc3e8c4a9343b6ef2845b03e712a7676c9c55a48",
    "candidate_actor_module_sha256": "19f5935bc6aabcde178f60f62619757b01fa51b99ff5389120a8404e00e70372",
    "candidate_store_sha256": "a25edc57d4a4ac225b1b152a2672ff2b108b3c497cef05cd46a8fb22c1e586b8",
    "candidate_test_sha256": "b04100bac2cd4fba6c132d3cfb44e18fa6e40a0896e602aa276a69b2daebb12c",
    "patch_sha256": "b164d083aa4d4bd3a6dc325582c4ee82e0042945360c98a63ca3ec9212abcc58",
    "verification": {
        "candidate_boundary_plus_live_guard": "14 passed; 1 existing Quandl deprecation warning",
        "candidate_plus_managed_execution_adapter_plus_live_guard": "21 passed; 1 existing Quandl deprecation warning",
        "same_30_test_store_regression_base": "30 passed (r0 lineage baseline log)",
        "same_30_test_store_regression_candidate": "9 passed, 21 failed at closed CTP local-SDK gate; retained as compatibility delta",
        "ruff": "passed",
        "py_compile": "passed",
        "patch_replay_core_autocrlf_false": "all three target hashes byte-exact",
        "patch_replay_core_autocrlf_true": "Store byte-exact; new LF sources converted to CRLF but normalized source text equal",
        "external_actor_or_provider": False,
        "credentials_or_native_sdk": False,
        "runtime_default_route_or_write_authority": False,
        "real_g1_g5_or_live_acceptance": False,
    },
    "files": files,
}
OUT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
manifest_hash = sha256(OUT)
SIDECAR.write_text(f"{manifest_hash}  {OUT.name}\n", encoding="ascii")
print(f"manifest_sha256={manifest_hash}")
print(f"inventory_files={len(files)}")
