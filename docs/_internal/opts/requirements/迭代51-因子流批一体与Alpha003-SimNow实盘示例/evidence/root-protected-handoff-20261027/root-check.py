"""Root-only local protected handoff check; no Store/client/provider calls."""
import hashlib
import json
import sys
from pathlib import Path

EXAMPLE = Path("D:/source_code/backtrader/examples/unified/028_alpha003_simnow_minute")
PIN = "6d411641a2cf5cafd1ead5fa530c7cd145a138adb84d579e7dcffaaa805847ec"
OUTPUT = Path("D:/temp/i51-root-protected-handoff-20261027.json")
CONSUMER = Path("D:/temp/i51cal-consumer-20261027-r1/consumer/Lib/site-packages")


def main():
    if OUTPUT.exists():
        raise SystemExit("OUTPUT_ALREADY_EXISTS")
    result = {
        "schema": 1, "provider_invoked": False, "store_created": False,
        "credential_values_exported": False, "selected_config_index": 0,
    }
    phase = "source_binding"
    try:
        assert hashlib.sha256((EXAMPLE / "protected_simnow.py").read_bytes()).hexdigest() == PIN
        sys.path.insert(0, str(EXAMPLE))
        import backtrader_runtime
        import protected_simnow

        assert Path(backtrader_runtime.__file__).resolve().is_relative_to(CONSUMER)
        phase = "protected_handoff"
        with protected_simnow.protected_simnow_store_config(selected_config_index=0) as handoff:
            mapping = handoff.for_runner()
            assert mapping["api_kwargs"] == {}
            assert all(type(mapping["config"][name]) is str and bool(mapping["config"][name])
                       for name in protected_simnow.CTP_AUTHENTICATION_CREDENTIAL_KEYS)
            assert handoff.for_runner()["config"] == mapping["config"]
            assert repr(mapping) == "PrivateSimNowMapping(<redacted>)"
            result["sealed_inprocess_mapping_verified"] = True
        phase = "context_exit"
        assert mapping["config"] == {}
        try:
            handoff.for_runner()
        except protected_simnow.ProtectedSimNowConfigError as error:
            assert error.args == ("CONFIG_CONTEXT_CLOSED",)
        else:
            raise AssertionError("CONTEXT_REUSED")
        assert hashlib.sha256((EXAMPLE / "protected_simnow.py").read_bytes()).hexdigest() == PIN
        result.update(status="PASS_ROOT_LOCAL_PROTECTED_HANDOFF_ONLY", context_closed=True)
    except BaseException as error:
        result.update(status="BLOCKED_ROOT_LOCAL_PROTECTED_HANDOFF", phase=phase)
        codes = {
            "CONFIG_INDEX_INVALID", "PROTECTED_CONFIG_REJECTED", "SDK_ARTIFACT_REJECTED",
            "OFFICIAL_SIMNOW_PAIR_REQUIRED", "CREDENTIAL_RESOLUTION_REJECTED",
            "CONFIG_CONTEXT_CLOSED", "CREDENTIAL_BINDING_CHANGED",
        }
        # Only helper-owned literal categories. No arbitrary exception message,
        # traceback, configuration value, endpoint or credential-derived hash.
        if type(error).__name__ == "ProtectedSimNowConfigError" and len(error.args) == 1:
            code = error.args[0]
            if type(code) is str and code in codes:
                result["reason"] = code
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["status"].startswith("PASS") else 2


if __name__ == "__main__":
    sys.exit(main())
