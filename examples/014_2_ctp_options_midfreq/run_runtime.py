#!/usr/bin/env python
"""Iteration 41 LOCAL_REPLAY_ONLY entrypoint for the CTP C/P/F fixture.

Copy runtime/config.example.yaml to runtime/config.yaml before running.  The
mandatory v4 runtime contract selects only simulation/replay; it cannot invoke
the legacy engineering adapter, SimNow launcher, credentials, or provider I/O.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Optional

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

# Direct-script support needs the source checkout path above.  # noqa: E402
from backtrader_runtime import (  # noqa: E402
    dispatch_configured_runtime,
    EffectiveRuntimeConfig,
    RuntimeConfigError,
    RuntimeRegistry,
    iteration41_runtime_registry,
    resolve_runner_effective_config,
)

DEFAULT_RUNTIME_DIR = HERE / "runtime"
STRATEGY_ID = "example.014_2.ctp_options_midfreq"
SCENARIOS = frozenset({"edge", "no_edge"})


def runtime_registry() -> RuntimeRegistry:
    """Use only centrally reviewed canonical directories, never copied source."""
    return iteration41_runtime_registry()


def _load_replay_runner():
    """Delay all Backtrader and adapter imports until configuration is accepted."""
    if __package__:
        from . import run
    else:
        import run
    return run


def _legacy_replay_config(legacy):
    """Load the frozen local fixture after v4 policy acceptance only."""
    try:
        raw = legacy.load_config(legacy.EXAMPLE_DIR / "config.yaml")
    except (legacy.ConfigurationError, OSError, ValueError) as exc:
        raise RuntimeConfigError(
            "CONFIG_SCHEMA_UNSUPPORTED",
            "The frozen local replay fixture is missing or invalid.",
            field_path="replay_fixture",
            reason="invalid_replay_fixture",
        ) from exc
    if raw.get("mode") != "replay":
        raise RuntimeConfigError(
            "PRESET_POLICY_VIOLATION",
            "The frozen fixture must remain local replay.",
            field_path="replay_fixture.mode",
            reason="replay_fixture_mode_not_bound",
        )
    return raw


def run_runtime(
    runtime_dir: Optional[Path] = DEFAULT_RUNTIME_DIR,
    *,
    registry: Optional[RuntimeRegistry] = None,
    effective: Optional[EffectiveRuntimeConfig] = None,
    runtime_directory: Optional[object] = None,
) -> dict:
    """Validate schema-v4 config and run the self-contained local replay only."""
    trusted_registry = runtime_registry() if registry is None else registry
    effective = resolve_runner_effective_config(runtime_dir, trusted_registry, effective=effective)
    config = effective.config
    if config.strategy_id != STRATEGY_ID:
        raise RuntimeConfigError(
            "PRESET_POLICY_VIOLATION",
            "This entrypoint is registered only for the 014_2 local replay strategy.",
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
            "Choose edge or no_edge in parameters.scenario.",
            field_path="parameters.scenario",
            reason="invalid_scenario",
        )

    legacy = _load_replay_runner()
    raw = _legacy_replay_config(legacy)
    try:
        report = legacy.run_replay(raw, scenario=scenario)
    except (legacy.ConfigurationError, OSError, ValueError) as exc:
        raise RuntimeConfigError(
            "CONFIG_SCHEMA_UNSUPPORTED",
            "The local replay fixture could not complete.",
            field_path="replay_fixture",
            reason="invalid_replay_fixture",
        ) from exc

    if (
        report.get("orders_submitted") != 0
        or report.get("external_network_requests") != 0
        or report.get("external_trade_writes") != 0
    ):
        raise RuntimeConfigError(
            "PRESET_POLICY_VIOLATION",
            "The local replay reported an external request or order write.",
            field_path="replay_result",
            reason="replay_write_detected",
        )
    report["external_request_counts"] = {"network": 0, "order_write": 0}
    report["runtime_config"] = {
        "config_schema_version": 4,
        "strategy_id": config.strategy_id,
        "mode": config.mode,
        "preset": config.preset,
        "config_digest": config.config_digest,
        "effective_digest": effective.effective_digest,
        "scope": "LOCAL_REPLAY_ONLY",
        "evidence_boundary": "SYNTHETIC_CPF_REPLAY_ONLY_NOT_CTP_OR_SIMNOW_EVIDENCE",
        "allows_network": effective.allows_network,
        "allows_external_writes": effective.allows_external_writes,
        "allows_production_writes": effective.allows_production_writes,
    }
    return report


def main(argv=None) -> int:
    """Run the registered local replay or emit a pre-import rejection."""
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
    return 0 if report.get("status") == "LOCAL_REPLAY_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
