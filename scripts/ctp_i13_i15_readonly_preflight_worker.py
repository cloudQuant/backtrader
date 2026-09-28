"""Fixed worker body for the opt-in CTP read-only preflight operation.

This file is executed only after a separately protected deployment anchor has
bound its exact bytes and the authenticated pipe client's primary token. It
accepts no argv, environment-selected path, or caller-provided config. Tests
exercise only inert substitute worker bytes and never call ``main`` here.
"""

from __future__ import annotations

import json
import sys


WORKER_SCHEMA = "ctp_i13_i15_readonly_preflight_worker_output.v1"


def main() -> int:
    """Run the one fixed registered read-only preflight and emit redacted JSON."""

    from backtrader_runtime.cli import dispatch_registered_ctp_simnow_readonly_preflight
    from backtrader_runtime.inventory import ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR
    from backtrader_runtime.registry import default_runtime_registry, validate_runtime_config

    registry = default_runtime_registry()
    effective = validate_runtime_config(ITERATION41_013_3_CTP_PRIVATE_RUNTIME_DIR, registry)
    observation = dispatch_registered_ctp_simnow_readonly_preflight(effective, registry)
    public_projection = observation.as_public_dict()
    payload = {"schema": WORKER_SCHEMA, "observation": public_projection}
    output = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    sys.stdout.write(output)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
