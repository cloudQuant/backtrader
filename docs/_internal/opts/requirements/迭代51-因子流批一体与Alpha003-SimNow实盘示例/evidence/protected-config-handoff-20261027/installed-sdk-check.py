"""Check only public installed SDK provenance before any protected handoff."""
import json
import sys
from pathlib import Path

sys.path.insert(0, "D:/source_code/backtrader/examples/unified/028_alpha003_simnow_minute")
out = Path("D:/temp/i51-protected-artifact-20261027.json")
if out.exists():
    raise SystemExit("OUTPUT_ALREADY_EXISTS")
status = {"schema": 1, "private_config_read": False, "provider_invoked": False}
try:
    import protected_simnow as bridge
    from backtrader_runtime.ctp_artifact_provenance import CtpArtifactProvenanceError

    with bridge.trusted_installed_capability_import_context(("bt_api_base", "bt_api_ctp")):
        bridge._verify_pinned_sdk_distributions(
            ("bt_api_base", "bt_api_ctp"), pins=bridge._SDK_PINS
        )
    status["status"] = "PASS_INSTALLED_SDK_PROVENANCE"
except Exception as error:
    status["status"] = "BLOCKED_INSTALLED_SDK_PROVENANCE"
    # Fixed categories only; public metadata errors never need raw messages.
    reason = getattr(error, "reason", None)
    allowed = {
        "artifact_unavailable", "artifact_record_pin_mismatch", "artifact_record_invalid",
        "artifact_record_mismatch", "artifact_identity_mismatch", "artifact_install_root_invalid",
        "artifact_provenance_invalid", "artifact_wheel_hash_mismatch", "artifact_pin_unavailable",
        "artifact_file_hash_mismatch", "artifact_file_size_mismatch", "artifact_package_inventory_mismatch",
    }
    status["reason"] = reason if type(reason) is str and reason in allowed else "OTHER_PUBLIC_PROVENANCE_ERROR"
out.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
print(json.dumps(status))
sys.exit(0 if status["status"].startswith("PASS") else 2)
