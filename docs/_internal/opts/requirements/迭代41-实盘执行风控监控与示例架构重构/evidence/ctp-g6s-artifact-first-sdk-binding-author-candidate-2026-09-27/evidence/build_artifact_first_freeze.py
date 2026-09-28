"""Build the immutable source manifest and freeze receipt for this candidate."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "candidate-source-manifest.json"
RECEIPT_PATH = ROOT / "freeze-receipt.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def included(path: Path) -> bool:
    if path in {MANIFEST_PATH, RECEIPT_PATH}:
        return False
    excluded_parts = {"__pycache__", ".pytest_cache", ".ruff_cache"}
    if any(part in excluded_parts for part in path.parts):
        return False
    return path.is_file()


def file_map(paths: list[str]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for relative in paths:
        path = ROOT / relative
        result[relative] = {"size": path.stat().st_size, "sha256": sha256(path)}
    return result


def main() -> None:
    payload_files = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        }
        for path in sorted(ROOT.rglob("*"))
        if included(path)
    ]
    changed = file_map(
        [
            "backtrader_runtime/ctp_sdk_artifact_binding.py",
            "backtrader_runtime/ctp_simnow_td_trading_readiness.py",
            "tests/unit/runtime/test_ctp_sdk_artifact_binding.py",
            "tests/unit/runtime/test_ctp_simnow_td_trading_readiness.py",
            "README.md",
        ]
    )
    parent_manifest = ROOT / "evidence" / "parent-candidate-source-manifest.json"
    parent_receipt = ROOT / "evidence" / "parent-freeze-receipt.json"
    sdk_manifest = ROOT / "evidence" / "sdk" / "settlement-source-manifest.json"
    run = ROOT / "evidence" / "artifact-first-run"

    manifest = {
        "schema": "iteration41.g6s.artifact_first_sdk_binding.source_manifest.v1",
        "classification": "isolated source-only fake candidate; no G4/G6-S acceptance",
        "candidate_root": str(ROOT),
        "base": {
            "previous_candidate_root": r"D:\temp\iteration41-g6s-main-td-settlement-candidate-20260927",
            "previous_candidate_manifest_path": "evidence/parent-candidate-source-manifest.json",
            "previous_candidate_manifest_sha256": sha256(parent_manifest),
            "previous_candidate_receipt_path": "evidence/parent-freeze-receipt.json",
            "previous_candidate_receipt_sha256": sha256(parent_receipt),
            "main_repository": r"D:\source_code\backtrader",
            "main_readiness_path": "backtrader_runtime/ctp_simnow_td_trading_readiness.py",
            "main_readiness_sha256": "F016783A6817D858A03CDA6E3F78ABEB43E769C0626D55757EE2DEBB7502D09D",
            "main_readiness_test_path": "tests/unit/runtime/test_ctp_simnow_td_trading_readiness.py",
            "main_readiness_test_sha256": "B7CBA6AC34626726340565AD5BA002750EFE87EA668E3419035357D071C276F3",
        },
        "sdk_input": {
            "candidate_root": r"D:\temp\iteration41-g4r2-settlement-query-candidate-20260927",
            "manifest_path": "evidence/sdk/settlement-source-manifest.json",
            "manifest_sha256": sha256(sdk_manifest),
            "settlement_evidence_source_sha256": "53333798198177DD675F96478D8D7D2D0445E2E41459E54D4F021BDD32FA3282",
            "public_export_source_sha256": "246F5963130219D87C7773637C840B2B6FF5B99CE97DD2C0C1CEF670197DE505",
            "independent_sdk_qa": "pending; no installed wheel or approved artifact pin",
        },
        "candidate_changes": {
            "files": changed,
            "summary": [
                "Public readiness accepts no verifier or artifact policy from callers.",
                "A no-argument pre-client bridge requires a code-owned artifact policy and default policy is unset.",
                "Before SDK evidence import, bridge rejects empty path entries, archive paths, altered hooks/cached finders, then requires one package and matching dist-info and validates metadata, pinned RECORD bytes, RECORD hashes/sizes, package inventory, critical source/native digests, and standard meta-path chain.",
                "After import, bridge checks exact module spec/loader/origin and source digest, tracks module object identity, and compares the exact evidence class object.",
                "The bridge revalidates package/RECORD/source/module/native facts before returning evidence; it never imports the native extension itself.",
                "Synthetic installation fixtures test tampering, duplicate install, pyc, origin, extension metadata, and same-name/module spoof cases.",
            ],
        },
        "verification": {
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "working_directory": str(ROOT),
            "pythonpath": str(ROOT),
            "pytest_disable_plugin_autoload": True,
            "dont_write_bytecode": True,
            "pytest_command": "python -m pytest --noconftest tests\\unit\\runtime\\test_ctp_sdk_artifact_binding.py tests\\unit\\runtime\\test_ctp_simnow_td_trading_readiness.py -q --tb=short --junitxml=evidence\\artifact-first-run\\focused-junit.xml",
            "pytest_result": "36 passed, 0 skipped, exit 0",
            "pytest_log": {
                "path": "evidence/artifact-first-run/focused-pytest.log",
                "sha256": sha256(run / "focused-pytest.log"),
            },
            "junit": {
                "path": "evidence/artifact-first-run/focused-junit.xml",
                "sha256": sha256(run / "focused-junit.xml"),
            },
            "static_checks": {
                "path": "evidence/artifact-first-run/static-checks.log",
                "sha256": sha256(run / "static-checks.log"),
                "result": "compile() passed for four changed Python files; Ruff I001/UP035 passed on four changed files; full Ruff and format check passed on new binding module/test",
            },
            "fresh_process_import_guard": {
                "path": "evidence/artifact-first-run/source-origin-sdk-block-guard.log",
                "sha256": sha256(run / "source-origin-sdk-block-guard.log"),
                "result": "both candidate module origins resolved from isolated candidate; code-owned pin unset; zero bt_api_ctp modules loaded",
            },
        },
        "security_and_acceptance_scope": {
            "main_repository_modified": False,
            "sdk_candidate_modified": False,
            "native_extension_loaded_or_executed": False,
            "provider_or_network_called": False,
            "credentials_or_private_config_read": False,
            "default_route_or_pin_changed": False,
            "code_owned_artifact_policy": "None (default fail-closed)",
            "fake_policy_is_production_authority": False,
            "python_injection_is_security_boundary": False,
            "protected_windows_handle_or_acl_boundary": False,
            "wheel_built_or_installed": False,
            "G4_accepted": False,
            "G6S_accepted": False,
        },
        "payload_files": payload_files,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_sha = sha256(MANIFEST_PATH)
    receipt = {
        "schema": "iteration41.g6s.artifact_first_sdk_binding.freeze_receipt.v1",
        "status": "ISOLATED_SOURCE_FAKE_ONLY_CANDIDATE_NO_ACCEPTANCE",
        "candidate_root": str(ROOT),
        "source_manifest": {
            "path": "candidate-source-manifest.json",
            "sha256": manifest_sha,
            "payload_file_count": len(payload_files),
        },
        "changes": changed,
        "verification_result": "36 passed, 0 skipped, exit 0; fake-only source/installer fixtures",
        "limitations": [
            "No production SDK artifact policy is set; public pre-client route rejects before SDK import/client access.",
            "Python path hashing uses ordinary filesystem reads and is not a protected-handle, ACL, signed-pin, or OS process trust boundary.",
            "Synthetic extension bytes are inert placeholders; no native extension was loaded or executed.",
            "G4 SDK independent QA and wheel/pin acceptance are pending; this is not G4 or G6-S acceptance.",
        ],
        "main_repository_modified": False,
        "sdk_candidate_modified": False,
        "native_loaded_or_called": False,
        "provider_or_network_called": False,
        "credentials_or_private_config_read": False,
        "default_route_or_pin_changed": False,
    }
    RECEIPT_PATH.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"manifest_sha256": manifest_sha, "payload_file_count": len(payload_files), "receipt_sha256": sha256(RECEIPT_PATH)}, sort_keys=True))


if __name__ == "__main__":
    main()
