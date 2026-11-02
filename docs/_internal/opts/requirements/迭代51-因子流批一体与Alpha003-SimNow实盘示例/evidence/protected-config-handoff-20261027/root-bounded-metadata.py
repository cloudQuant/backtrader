"""Root-only bounded config inspection; never export private fields or digests."""
import json
import sys
from pathlib import Path

ROOT = Path("D:/source_code/backtrader")
OUT = ROOT / ".codex-tmp/i51_root_protected_config_metadata_20261027.json"


def main():
    if OUT.exists():
        raise RuntimeError("OUTPUT_ALREADY_EXISTS")
    sys.path.insert(0, str(ROOT))
    phase = "imports"
    result = {"schema": 1, "provider_invoked": False, "credential_exported": False}
    try:
        from backtrader_runtime.config import load_runtime_config
        from backtrader_runtime.inventory import (
            ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR,
            ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID,
            iteration41_runtime_registry,
        )
        from backtrader_runtime.registry import resolve_runtime_config

        phase = "registered_bounded_load"
        registry = iteration41_runtime_registry()
        config = load_runtime_config(
            ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR, registry=registry
        )
        phase = "effective_seal"
        effective = resolve_runtime_config(config, registry)
        binding = registry.require_ctp_simnow_readonly_binding(
            ITERATION41_013_3_CTP_PRIVATE_RUNTIME_ID
        )
        phase = "sealed_pair_metadata"
        _, _, pairs = binding._sealed_private_config(effective, registry)
        result.update(status="PASS_BOUNDED_CONFIG_METADATA_ONLY", pair_count=len(pairs))
    except BaseException:
        # No exception text, traceback, config repr or credential-derived digest.
        result.update(status="BLOCKED_BOUNDED_CONFIG_METADATA", phase=phase)
    with OUT.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result))
    return 0 if result["status"].startswith("PASS") else 2


if __name__ == "__main__":
    sys.exit(main())
