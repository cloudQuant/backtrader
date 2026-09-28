#!/usr/bin/env python
"""Iteration 41 entrypoint for the 014_1 local replay fixture.

Copy runtime/config.example.yaml to runtime/config.yaml before running. This
entrypoint supports simulation/replay only. The existing run.py remains an
unmigrated baseline; its parameter file is read only after v4 validation and
cannot select a runtime mode. No external account or admission path is wired.
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
STRATEGY_ID = "example.014_1.ctp_options_lowfreq"
SCENARIOS = frozenset({"eligible", "no_edge", "budget_reject", "misaligned"})


def runtime_registry() -> RuntimeRegistry:
    """Use the central reviewed inventory; never trust copied directories."""
    return iteration41_runtime_registry()


def _load_replay_runner():
    """Delay strategy and adapter imports until configuration is accepted."""
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
    """Validate mandatory config and run the local fixture.

    The optional registry is a trusted code/test injection point. The CLI never
    constructs registrations from user configuration or a supplied directory.
    """
    trusted_registry = runtime_registry() if registry is None else registry
    effective = resolve_runner_effective_config(runtime_dir, trusted_registry, effective=effective)
    config = effective.config
    if config.strategy_id != STRATEGY_ID:
        raise RuntimeConfigError(
            "PRESET_POLICY_VIOLATION",
            "This entrypoint is registered only for the 014_1 local replay strategy.",
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
    scenario = config.parameters.get("scenario", "eligible")
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise RuntimeConfigError(
            "CONFIG_SCHEMA_UNSUPPORTED",
            "Choose eligible, no_edge, budget_reject or misaligned in parameters.scenario.",
            field_path="parameters.scenario",
            reason="invalid_scenario",
        )
    legacy = _load_replay_runner()
    try:
        # The frozen legacy file supplies fixture parameters only. In particular,
        # its own replay-mode fence remains authoritative and is never rewritten.
        report = legacy.run_replay(legacy.load_config(), scenario=scenario)
    except (legacy.RunnerConfigurationError, OSError) as exc:
        raise RuntimeConfigError(
            "CONFIG_SCHEMA_UNSUPPORTED",
            "The local replay parameter fixture is missing or invalid.",
            field_path="replay_fixture",
            reason="invalid_replay_fixture",
        ) from exc
    report["runtime_config"] = {
        "config_schema_version": 4,
        "strategy_id": config.strategy_id,
        "mode": config.mode,
        "preset": config.preset,
        "config_digest": config.config_digest,
        "scope": "LOCAL_REPLAY_ONLY",
        "allows_network": effective.allows_network,
        "allows_external_writes": effective.allows_external_writes,
        "allows_production_writes": effective.allows_production_writes,
    }
    return report


def main(argv=None) -> int:
    """Run the registered replay or report a rejection before strategy startup."""
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
    except RuntimeConfigError as exc:
        report = {
            "status": "REJECTED",
            "error": exc.as_dict(),
            "external_request_counts": {"network": 0, "order_write": 0},
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
