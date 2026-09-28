#!/usr/bin/env python
"""Fail-closed Iteration 41 migration route for the historical CTP examples.

The old 007 runners include direct SimNow/CTP wiring and locally owned order,
timer, and cancellation flows. They are retained for source review, but they
are not an execution route in this iteration. This registered profile only
validates a mandatory schema-v4 ``config.yaml`` and emits a local no-action
report. It never imports Backtrader, a CTP extension, an SDK provider, or
legacy YAML/credential files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Optional


HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backtrader_runtime import (  # noqa: E402
    dispatch_configured_runtime,
    CONFIG_SCHEMA_UNSUPPORTED,
    PRESET_POLICY_VIOLATION,
    EffectiveRuntimeConfig,
    RuntimeConfigError,
    RuntimeRegistry,
    iteration41_runtime_registry,
    resolve_runner_effective_config,
)


DEFAULT_RUNTIME_DIR = HERE / "runtime"
STRATEGY_ID = "example.007_ctp.legacy_direct"
LOCAL_SCENARIO = "no_action"


def runtime_registry() -> RuntimeRegistry:
    """Return the code-owned inventory rather than discovering a CWD route."""

    return iteration41_runtime_registry()


def _validate_profile(config: Any, effective: Any) -> None:
    """Bind the historical CTP surface to one zero-I/O migration profile."""

    if config.strategy_id != STRATEGY_ID:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "this CTP migration shell is bound only to its reviewed strategy identity",
            field_path="strategy.id",
            reason="strategy_not_bound",
        )
    if (
        (config.mode, config.preset) != ("simulation", "replay")
        or effective.allows_network
        or effective.allows_external_writes
        or effective.allows_production_writes
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the historical CTP migration shell supports only local simulation/replay",
            field_path="runtime.preset",
            reason="preset_not_bound",
        )
    if config.parameters.get("scenario", LOCAL_SCENARIO) != LOCAL_SCENARIO:
        raise RuntimeConfigError(
            CONFIG_SCHEMA_UNSUPPORTED,
            "the historical CTP migration profile accepts only parameters.scenario=no_action",
            field_path="parameters.scenario",
            reason="invalid_scenario",
        )


def run_runtime(
    runtime_dir: Optional[Path] = DEFAULT_RUNTIME_DIR,
    *,
    registry: Optional[RuntimeRegistry] = None,
    effective: Optional[EffectiveRuntimeConfig] = None,
    runtime_directory: Optional[object] = None,
) -> Dict[str, Any]:
    """Validate config v4 and return a report without touching CTP or a provider."""

    trusted_registry = runtime_registry() if registry is None else registry
    effective = resolve_runner_effective_config(runtime_dir, trusted_registry, effective=effective)
    config = effective.config
    _validate_profile(config, effective)
    return {
        "status": "LOCAL_REPLAY_PASS",
        "admission_status": "LOCAL_REPLAY_ONLY",
        "scenario": LOCAL_SCENARIO,
        "external_request_counts": {"network": 0, "order_write": 0},
        "legacy_direct_execution": "NOT_SUPPORTED",
        "covered_legacy_surfaces": {
            "ctp_sa_dual_ma": "NOT_SUPPORTED",
            "ctp_backtest_and_live_runners": "NOT_SUPPORTED",
            "ctp_penetration_certification": "NOT_SUPPORTED",
        },
        "evidence_boundary": (
            "CONFIG_GATE_AND_NO_ACTION_PROBE_ONLY_NOT_CTP_SIMNOW_OR_REAL_TRADING_EVIDENCE"
        ),
        "runtime_config": {
            "config_schema_version": 4,
            "strategy_id": config.strategy_id,
            "mode": config.mode,
            "preset": config.preset,
            "config_digest": config.config_digest,
            "effective_digest": effective.effective_digest,
            "scope": "LOCAL_REPLAY_ONLY",
            "allows_network": effective.allows_network,
            "allows_external_writes": effective.allows_external_writes,
            "allows_production_writes": effective.allows_production_writes,
        },
    }


def main(argv: Optional[tuple[str, ...]] = None) -> int:
    """Run the no-action report or reject before a historical import can occur."""

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=DEFAULT_RUNTIME_DIR,
        help="registered runtime directory; must contain config.yaml",
    )
    args = parser.parse_args(argv)
    try:
        report = dispatch_configured_runtime(args.runtime_dir, runtime_registry())
    except RuntimeConfigError as error:
        print(
            json.dumps(
                {
                    "status": "REJECTED",
                    "error": error.as_dict(),
                    "external_request_counts": {"network": 0, "order_write": 0},
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
