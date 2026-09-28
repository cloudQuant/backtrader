#!/usr/bin/env python
"""Iteration 41 LOCAL_REPLAY_ONLY entrypoint for 012_2_event_driven_cross_exchange.

The required runtime/config.yaml selects simulation/replay. The existing
candidate-bound config.yaml, manifest, strategy and admission code are unchanged.
This is an offline formula fixture, not native execution or profitability evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from backtrader_runtime import (
    dispatch_configured_runtime,
    EffectiveRuntimeConfig,
    RuntimeConfigError,
    RuntimeRegistry,
    iteration41_runtime_registry,
    resolve_runner_effective_config,
)

HERE = Path(__file__).resolve().parent
DEFAULT_RUNTIME_DIR = HERE / "runtime"
STRATEGY_ID = "example.012_2.event_driven_cross_exchange"
SCENARIOS = frozenset({"profitable", "loss", "no_edge", "partial", "unknown", "gap"})


def runtime_registry() -> RuntimeRegistry:
    """Use only centrally reviewed canonical directories, never copied ones."""
    return iteration41_runtime_registry()


def _load_replay_runner():
    """Import the candidate runner only after the runtime contract is accepted."""
    if __package__:
        from . import run
    else:
        import run
    return run


def run_runtime(
    runtime_dir: Optional[Path] = DEFAULT_RUNTIME_DIR,
    *,
    registry: Optional[RuntimeRegistry] = None,
    effective: Optional[EffectiveRuntimeConfig] = None,
    runtime_directory: Optional[object] = None,
) -> dict:
    """Validate v4 configuration and invoke the original hash-bound replay API.

    A registry may be injected only by trusted code/tests; the CLI cannot define
    registrations, choose a mode, change candidate parameters or load credentials.
    """
    trusted_registry = runtime_registry() if registry is None else registry
    effective = resolve_runner_effective_config(runtime_dir, trusted_registry, effective=effective)
    config = effective.config
    if config.strategy_id != STRATEGY_ID:
        raise RuntimeConfigError(
            "PRESET_POLICY_VIOLATION",
            "This entrypoint is bound to its own cross-exchange replay strategy.",
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
            "PRESET_POLICY_VIOLATION",
            "This entrypoint supports only offline simulation/replay.",
            field_path="runtime.preset",
            reason="preset_not_bound",
        )
    scenario = config.parameters.get("scenario", "no_edge")
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise RuntimeConfigError(
            "CONFIG_SCHEMA_UNSUPPORTED",
            "Choose profitable, loss, no_edge, partial, unknown or gap.",
            field_path="parameters.scenario",
            reason="invalid_scenario",
        )
    try:
        legacy = _load_replay_runner()
    except ImportError as exc:
        raise RuntimeConfigError(
            "PRESET_POLICY_VIOLATION",
            "The local replay dependencies are unavailable; install the documented SDK environment.",
            field_path="replay_dependencies",
            reason="replay_dependency_unavailable",
        ) from exc
    try:
        # Keep the existing candidate/source/config hashes authoritative. Runtime
        # configuration never overrides or rebinds the frozen research inputs.
        report = legacy.run_replay(
            scenario=scenario,
            config_path=legacy.DEFAULT_CONFIG,
            manifest_path=legacy.MANIFEST_PATH,
        )
    except (legacy.RunnerConfigurationError, OSError) as exc:
        raise RuntimeConfigError(
            "CONFIG_SCHEMA_UNSUPPORTED",
            "The candidate-bound local replay fixture is missing, invalid or has source drift.",
            field_path="replay_fixture",
            reason="invalid_replay_fixture",
        ) from exc
    report["external_request_counts"] = {"network": 0, "order_write": 0}
    report["runtime_config"] = {
        "config_schema_version": 4,
        "strategy_id": config.strategy_id,
        "mode": config.mode,
        "preset": config.preset,
        "config_digest": config.config_digest,
        "scope": "LOCAL_REPLAY_ONLY",
        "evidence_boundary": "R0_FORMULA_FIXTURE_ONLY_NOT_NATIVE_EXECUTION",
        "allows_network": effective.allows_network,
        "allows_external_writes": effective.allows_external_writes,
        "allows_production_writes": effective.allows_production_writes,
    }
    return report


def main(argv=None) -> int:
    """Run the registered fixture; every unsupported mode fails before import."""
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
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "FORMULA_CHECK_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
