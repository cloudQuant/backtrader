#!/usr/bin/env python
"""Iteration 41 entrypoint for the 013_1 local CTP replay.

Copy runtime/config.example.yaml to runtime/config.yaml before running. This
entrypoint accepts only the reviewed simulation/replay profile. It delays all
strategy and adapter imports until the configuration and registry fences have
accepted the run; it never selects the legacy SimNow path.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Optional

from backtrader_runtime import (
    dispatch_configured_runtime,
    CONFIG_SCHEMA_UNSUPPORTED,
    PRESET_POLICY_VIOLATION,
    EffectiveRuntimeConfig,
    RuntimeConfigError,
    RuntimeRegistry,
    iteration41_runtime_registry,
    resolve_runner_effective_config,
)


HERE = Path(__file__).resolve().parent
DEFAULT_RUNTIME_DIR = HERE / "runtime"
STRATEGY_ID = "example.013_1.midfreq_cross_arbitrage"
SCENARIOS = frozenset(("profitable", "loss", "no_edge"))
_OFFLINE_PROVIDER_OVERRIDE = "BT_STORE_PROVIDER"


def runtime_registry() -> RuntimeRegistry:
    """Return the central reviewed inventory, never a discovered directory."""

    return iteration41_runtime_registry()


def _load_replay_runner():
    """Delay legacy strategy/provider imports until the v4 contract is sealed."""

    if __package__:
        from . import run
    else:
        import run

    return run


def _require_offline_provider_selection() -> None:
    """Reject an ambient Store override before the legacy runner can import it."""

    if os.environ.get(_OFFLINE_PROVIDER_OVERRIDE):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "offline replay does not accept an ambient provider override",
            field_path="environment.BT_STORE_PROVIDER",
            reason="offline_provider_override_not_allowed",
        )


def run_runtime(
    runtime_dir: Optional[Path] = DEFAULT_RUNTIME_DIR,
    *,
    registry: Optional[RuntimeRegistry] = None,
    effective: Optional[EffectiveRuntimeConfig] = None,
    runtime_directory: Optional[object] = None,
) -> dict:
    """Validate the mandatory v4 config and execute the local synthetic replay."""

    trusted_registry = runtime_registry() if registry is None else registry
    effective = resolve_runner_effective_config(runtime_dir, trusted_registry, effective=effective)
    config = effective.config
    if config.strategy_id != STRATEGY_ID:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "this entrypoint is bound only to the 013_1 CTP replay strategy",
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
            "this entrypoint supports only offline simulation/replay",
            field_path="runtime.preset",
            reason="preset_not_bound",
        )
    scenario = config.parameters.get("scenario", "no_edge")
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise RuntimeConfigError(
            CONFIG_SCHEMA_UNSUPPORTED,
            "choose profitable, loss, or no_edge in parameters.scenario",
            field_path="parameters.scenario",
            reason="invalid_scenario",
        )
    _require_offline_provider_selection()
    try:
        legacy = _load_replay_runner()
    except ImportError as exc:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the local replay dependencies are unavailable",
            field_path="replay_dependencies",
            reason="replay_dependency_unavailable",
        ) from exc

    report = legacy.run_replay(scenario=scenario)
    report["external_request_counts"] = {"network": 0, "order_write": 0}
    report["admission_status"] = "LOCAL_REPLAY_ONLY"
    report["runtime_config"] = {
        "config_schema_version": 4,
        "strategy_id": config.strategy_id,
        "mode": config.mode,
        "preset": config.preset,
        "config_digest": config.config_digest,
        "scope": "LOCAL_REPLAY_ONLY",
        "evidence_boundary": "Synthetic local replay only; not real-market or trading admission.",
        "allows_network": effective.allows_network,
        "allows_external_writes": effective.allows_external_writes,
        "allows_production_writes": effective.allows_production_writes,
    }
    return report


def main(argv=None) -> int:
    """Run the registered replay or print a safe rejection before strategy startup."""

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=DEFAULT_RUNTIME_DIR,
        help="registered runtime directory containing config.yaml",
    )
    args = parser.parse_args(argv)
    try:
        report = dispatch_configured_runtime(args.runtime_dir, runtime_registry())
    except RuntimeConfigError as exc:
        print(
            json.dumps(
                {
                    "status": "REJECTED",
                    "error": exc.as_dict(),
                    "external_request_counts": {"network": 0, "order_write": 0},
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
