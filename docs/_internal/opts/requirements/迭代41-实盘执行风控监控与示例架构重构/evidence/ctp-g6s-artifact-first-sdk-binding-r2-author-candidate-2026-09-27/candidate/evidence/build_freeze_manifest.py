"""Build the source-only inventory for this isolated candidate."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "candidate-source-manifest.json"
RECEIPT = ROOT / "freeze-receipt.json"
SDK_ROOT = Path(r"D:\temp\iteration41-g4r2-settlement-query-candidate-20260927")
SDK_MANIFEST = SDK_ROOT / "settlement-source-manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def included(path: Path) -> bool:
    if path in {MANIFEST, RECEIPT}:
        return False
    if any(part in {"__pycache__", ".pytest_cache", ".ruff_cache"} for part in path.parts):
        return False
    return path.is_file()


def main() -> None:
    files = []
    for path in sorted(ROOT.rglob("*")):
        if included(path):
            files.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    sdk_data = json.loads(SDK_MANIFEST.read_text(encoding="utf-8"))
    source = ROOT / "backtrader_runtime" / "ctp_simnow_td_trading_readiness.py"
    test = ROOT / "tests" / "unit" / "runtime" / "test_ctp_simnow_td_trading_readiness.py"
    payload = {
        "schema": "iteration41.g6s.main_td_settlement_consumer.source_manifest.v1",
        "classification": "isolated source-only fake candidate; no route/pin change",
        "candidate_root": str(ROOT),
        "base": {
            "repository": r"D:\source_code\backtrader",
            "readiness_path": "backtrader_runtime/ctp_simnow_td_trading_readiness.py",
            "readiness_sha256": "F016783A6817D858A03CDA6E3F78ABEB43E769C0626D55757EE2DEBB7502D09D",
            "test_path": "tests/unit/runtime/test_ctp_simnow_td_trading_readiness.py",
            "test_sha256": "B7CBA6AC34626726340565AD5BA002750EFE87EA668E3419035357D071C276F3",
        },
        "sdk_input": {
            "candidate_root": str(SDK_ROOT),
            "manifest_path": "settlement-source-manifest.json",
            "manifest_sha256": sha256(SDK_MANIFEST),
            "manifest_schema": sdk_data["schema"],
            "package_version": sdk_data["lineage"]["package_version"],
            "settlement_evidence_source_sha256": "53333798198177DD675F96478D8D7D2D0445E2E41459E54D4F021BDD32FA3282",
            "public_export_source_sha256": "246F5963130219D87C7773637C840B2B6FF5B99CE97DD2C0C1CEF670197DE505",
            "sdk_acceptance": "awaiting independent QA; no wheel/G6-S claim",
        },
        "candidate_changes": {
            "readiness_sha256": sha256(source),
            "test_sha256": sha256(test),
            "summary": [
                "typed verifier is mandatory and absent verifier rejects before settlement query",
                "verifier source manifest digest is fixed to the specified G4-r2 manifest",
                "requires nominal SDK evidence object and its seal-checked public projection",
                "checks evidence digest, filter digest, request/account/day/generation, terminal row, and UTC plus monotonic expiry",
                "returns evidence, callback-history, and SDK-source manifest digests",
            ],
        },
        "verification": {
            "python": sys.executable,
            "python_version": sys.version.split()[0],
            "working_directory": str(ROOT),
            "pythonpath": str(ROOT),
            "pytest_disable_plugin_autoload": True,
            "pytest_command": "python -m pytest --noconftest tests\\unit\\runtime\\test_ctp_simnow_td_trading_readiness.py -q --tb=short --junitxml=evidence\\run\\focused-junit.xml",
            "pytest_result": "22 passed",
            "native_import_guard": "fresh process imported candidate readiness module with bt_api_ctp imports denied; zero SDK modules loaded",
            "syntax": "candidate source/test compiled via compile() without writing bytecode",
            "ruff_scope": "I001 and UP035 passed for changed source/test files; full legacy lint not used as an acceptance gate",
        },
        "scope": {
            "main_repository_modified": False,
            "sdk_candidate_modified": False,
            "native_loaded_or_called": False,
            "provider_or_network_called": False,
            "credentials_or_private_config_read": False,
            "default_route_or_pin_changed": False,
            "wheel_built_or_installed": False,
            "g4_accepted": False,
            "g6s_accepted": False,
            "production_verifier_present": False,
            "python_injection_is_security_boundary": False,
        },
        "payload_files": files,
    }
    MANIFEST.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(sha256(MANIFEST))
    print(len(files))


if __name__ == "__main__":
    main()
