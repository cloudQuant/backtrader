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
    "candidate": "ctp-account-actor-main-store-wiring-r2",
    "status": "AUTHOR_CANDIDATE_NO_WRITE",
    "main_production_source_edited_by_candidate": False,
    "base_store_sha256": "dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826",
    "r1_parent_manifest_sha256": "ada5018781a7417206b88e3d934d59a67a77beab0c5e09e002a0e8f89a16ade4",
    "candidate_store_sha256": "a25edc57d4a4ac225b1b152a2672ff2b108b3c497cef05cd46a8fb22c1e586b8",
    "candidate_actor_module_sha256": "2e4b04d00c45ba9c6524c5ad0364273e6ecc1a1f653f595d21c3891be2644ee3",
    "candidate_test_sha256": "04968d98ae476d4b9ec33d448be11d19e0ffc9adb79585f423b37b37b759154f",
    "r2_apply_patch_sha256": "6e8575874cefeab4c693f6fedd5f3fc89dcec935005f5ad3a0d64f0e1284f90f",
    "legacy_delta_audit_report_sha256": "c2133a92cbc83a0a4b4c9cd3f10cccc2f7e4f7287026fddabb7bd1f6065cbd00",
    "legacy_delta_audit_zip_sha256": "4fa06de543221c3457088ee32a62ec81dbc25ab9359dbd85cd488e9a59891152",
    "legacy_delta_exact_base_log_sha256": "2990563f46564515e525768480213e650b33b67dbd9687f898304bf23b6499d1",
    "verification": {
        "candidate_boundary_plus_live_guard": "14 passed",
        "candidate_plus_managed_execution_adapter_plus_live_guard": "21 passed",
        "legacy_30_test_base": "30 passed",
        "legacy_30_test_r2": "9 passed, 21 failed at intentional CTP local-SDK fail-closed gate",
        "ruff": "passed",
        "py_compile": "passed",
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
