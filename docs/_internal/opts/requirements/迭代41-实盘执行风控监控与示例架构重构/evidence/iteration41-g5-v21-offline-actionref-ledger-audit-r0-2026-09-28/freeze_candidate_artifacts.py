"""Write patch and hash manifest for this disposable local candidate."""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = Path(r"D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source_manifest_path = SOURCE / "SOURCE-MANIFEST.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    verified_payloads: list[dict[str, object]] = []
    for item in source_manifest["files"]:
        relative = Path(item["path"])
        frozen = SOURCE / relative
        copied = ROOT / relative
        source_hash = sha256(frozen)
        if source_hash != item["sha256"] or sha256(copied) != source_hash:
            raise SystemExit(f"frozen source mismatch: {relative}")
        verified_payloads.append(
            {"path": relative.as_posix(), "sha256": source_hash, "bytes": frozen.stat().st_size}
        )

    changed_files = (
        ROOT / "src/bt_api_execution/offline_actionref_ledger_audit.py",
        ROOT / "tests/test_offline_actionref_ledger_audit.py",
    )
    patch_parts: list[str] = []
    for changed_file in changed_files:
        relative = changed_file.relative_to(ROOT).as_posix()
        patch_parts.extend(
            difflib.unified_diff(
                [],
                changed_file.read_text(encoding="utf-8").splitlines(keepends=True),
                fromfile="/dev/null",
                tofile=f"b/{relative}",
                n=3,
            )
        )
    patch_path = ROOT / "PATCH.diff"
    patch_path.write_text("".join(patch_parts), encoding="utf-8", newline="\n")

    artifact_paths = {
        "patch": patch_path,
        "projector": changed_files[0],
        "tests": changed_files[1],
        "candidate_report": ROOT / "CANDIDATE.md",
        "independent_qa_history": ROOT / "QA-HISTORY.md",
        "freeze_helper": Path(__file__),
    }
    manifest = {
        "schema": "iteration41-local-offline-candidate-freeze.v1",
        "candidate": "v21-actionref-ledger-audit-r0",
        "disposition": [
            "LOCAL_OFFLINE_ONLY",
            "NO_AUTHORITY",
            "NO_CUTOVER",
            "NO_WRITE",
            "LIVE_NO_GO",
        ],
        "frozen_source": {
            "root": str(SOURCE),
            "manifest": "SOURCE-MANIFEST.json",
            "manifest_sha256": sha256(source_manifest_path),
            "store_py_sha256": sha256(SOURCE / "src/bt_api_execution/store.py"),
            "payload_files_verified": len(verified_payloads),
            "all_payloads_byte_identical": True,
        },
        "artifacts": {
            key: {
                "path": str(value.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(value),
                "bytes": value.stat().st_size,
            }
            for key, value in artifact_paths.items()
        },
        "verification": {
            "focused_pytest": "10 passed",
            "ruff_check": "passed",
            "ruff_format_check": "passed",
            "py_compile": "passed",
            "freeze_helper_ruff": "passed",
            "tests_use_synthetic_sqlite_only": True,
            "native_provider_network_credentials_used": False,
        },
        "verified_source_payloads": verified_payloads,
    }
    manifest_path = ROOT / "FROZEN-MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "payload_files_verified": len(verified_payloads),
                "patch_sha256": sha256(patch_path),
                "projector_sha256": sha256(changed_files[0]),
                "tests_sha256": sha256(changed_files[1]),
                "candidate_report_sha256": sha256(ROOT / "CANDIDATE.md"),
                "freeze_helper_sha256": sha256(Path(__file__)),
                "manifest_sha256": sha256(manifest_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
