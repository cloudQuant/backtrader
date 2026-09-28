from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence" / "r2b-manifest.json"
SIDECAR = ROOT / "evidence" / "r2b-manifest.sha256"
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".benchmarks", ".mypy_cache"}
EXCLUDED_FILES = {OUT.name, SIDECAR.name, "r2b-freeze-log.txt"}


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
    "candidate": "ctp-account-actor-main-store-wiring-r2b",
    "status": "AUTHOR_CANDIDATE_NO_WRITE",
    "main_production_source_edited_by_candidate": False,
    "parent_r2a_manifest_sha256": "5ad9cce0851fbebd9ac07d520919b7a02f793ab99a133cf96e91f58cede405fb",
    "parent_r2a_store_sha256": "18a02f00ec3b2031932284c9e855395c1c70c3e448dbafcd054e4f079048c4d0",
    "main_base_store_sha256": "dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826",
    "candidate_store_sha256": "24f8199e199bbe84bbb113c3edbbee9e71d4736fdd8573297e24ead3298f2518",
    "candidate_actor_module_sha256": "2e4b04d00c45ba9c6524c5ad0364273e6ecc1a1f653f595d21c3891be2644ee3",
    "candidate_focus_test_sha256": "fc675d30a1cd3e303357406e81edc067af0b7559d2230ac6a2ee3732466cc2c6",
    "candidate_migrated_ctp_test_sha256": "15d93e165ea817b5ba484adac52658baf67f89fb83d30eff142c3e1ba4203ae3",
    "candidate_pure_contract_test_sha256": "a61c8b0070a41c813d7c3adb1165f9ad38ea5b63986a9293e868e38d78f3b5cf",
    "main_base_apply_patch_sha256": "1a16aadb94edb99924553d6472bf72dcb02bd04c7f994276816d91991a729f37",
    "r2a_delta_patch_sha256": "d27a724711c3eb9c3622e5103c4d70da65d977510e740bb5030dea7990abf9dc",
    "verification": {
        "candidate_boundary_and_migrated_ctp_focus": "43 passed",
        "internal_route_mutation_negative_probes": "4 passed",
        "original_three_file_regression_set": "30 passed",
        "all_unit_stores_and_runtime": "55 passed",
        "ruff_configured_changed_files": "passed",
        "py_compile_changed_files": "passed",
        "main_base_git_apply_check_and_replay": "passed",
        "gateway_wrapper_gap_reproduced_before_fix": True,
        "gateway_wrapper_guard_rejects_after_provider_or_config_mutation": True,
        "private_same_process_factory_or_raw_client_access_isolated": False,
        "external_account_actor_dispatch": False,
        "caller_actor_port_authority": False,
        "ctp_local_sdk_dispatch": False,
        "default_runtime_route_or_write_authority": False,
        "real_g1_g5_f14_or_production_acceptance": False,
    },
    "files": files,
}
OUT.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
manifest_hash = sha256(OUT)
SIDECAR.write_text(f"{manifest_hash}  {OUT.name}\n", encoding="ascii")
print(f"manifest_sha256={manifest_hash}")
print(f"inventory_files={len(files)}")
print(f"candidate_store_sha256={sha256(ROOT / 'backtrader/stores/btapistore.py')}")
print(f"main_base_patch_sha256={sha256(ROOT / 'r2b-main-base-apply.patch')}")
