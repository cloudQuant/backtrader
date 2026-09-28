#!/usr/bin/env python
"""Iteration 41 entrypoint for the 015 CTP-options local tick replay.

Copy ``runtime/config.example.yaml`` to ``runtime/config.yaml`` before running.
Only the reviewed ``simulation/replay`` profile is accepted.  Configuration
and the exact central registry binding are checked before importing the legacy
runner, which is then used solely for its deterministic offline replay API.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

# Keep the documented ``python examples/.../run_runtime.py`` form usable from
# the repository root.  This is a fixed source-tree path, never a CWD or user
# supplied import path; legacy strategy code still remains unimported here.
if __package__ in (None, ""):
    _SOURCE_ROOT = Path(__file__).resolve().parents[2]
    if str(_SOURCE_ROOT) not in sys.path:
        sys.path.insert(0, str(_SOURCE_ROOT))

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
STRATEGY_ID = "example.015.ctp_options_highfreq"
SCENARIOS = frozenset(
    (
        "valid_cohort",
        "insufficient_cohort",
        "duplicate_payload",
        "stale_source",
        "mixed_trading_day",
        "bar_only",
        "quality_gap",
        "quality_flag",
        "incomplete_volume",
        "volume_quality_gap",
        "out_of_limit",
        "execution_ineligible",
    )
)
_OFFLINE_ENVIRONMENT_OVERRIDES = ("BT_STORE_PROVIDER", "ITER30_SIMNOW_PROFILE")


def runtime_registry() -> RuntimeRegistry:
    """Return the reviewed inventory; never discover a directory from CWD."""

    return iteration41_runtime_registry()


def _load_replay_runner():
    """Delay legacy strategy and adapter imports until the v4 contract is sealed."""

    if __package__:
        from . import run
    else:
        import run

    return run


def _require_offline_environment() -> None:
    """Reject ambient provider or SimNow selection before legacy code is imported."""

    for name in _OFFLINE_ENVIRONMENT_OVERRIDES:
        if os.environ.get(name):
            raise RuntimeConfigError(
                PRESET_POLICY_VIOLATION,
                "offline replay does not accept ambient provider or SimNow selection",
                field_path="environment.{0}".format(name),
                reason="offline_environment_override_not_allowed",
            )


def _load_offline_replay_config(legacy: Any) -> Mapping[str, Any]:
    """Load the frozen legacy candidate parameters after the runtime fence.

    The v4 file selects only a reviewed scenario.  It cannot replace the
    candidate's fixture, contracts, mode, purpose, or other legacy parameters.
    """

    try:
        legacy_config, _ = legacy.load_config()
        return legacy_config
    except (legacy.RunnerConfigurationError, OSError, ValueError) as exc:
        raise RuntimeConfigError(
            CONFIG_SCHEMA_UNSUPPORTED,
            "the local replay parameter fixture is missing or invalid",
            field_path="replay_fixture",
            reason="invalid_replay_fixture",
        ) from exc


def run_runtime(
    runtime_dir: Optional[Path] = DEFAULT_RUNTIME_DIR,
    *,
    registry: Optional[RuntimeRegistry] = None,
    effective: Optional[EffectiveRuntimeConfig] = None,
    runtime_directory: Optional[object] = None,
) -> dict:
    """Validate mandatory v4 config and run exactly one local offline replay."""

    trusted_registry = runtime_registry() if registry is None else registry
    effective = resolve_runner_effective_config(runtime_dir, trusted_registry, effective=effective)
    config = effective.config
    if config.strategy_id != STRATEGY_ID:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "this entrypoint is bound only to the 015 CTP-options replay strategy",
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
    scenario = config.parameters.get("scenario", "valid_cohort")
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise RuntimeConfigError(
            CONFIG_SCHEMA_UNSUPPORTED,
            "choose a reviewed offline replay scenario in parameters.scenario",
            field_path="parameters.scenario",
            reason="invalid_scenario",
        )

    _require_offline_environment()
    try:
        legacy = _load_replay_runner()
    except ImportError as exc:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the local replay dependencies are unavailable",
            field_path="replay_dependencies",
            reason="replay_dependency_unavailable",
        ) from exc

    legacy_config = _load_offline_replay_config(legacy)
    try:
        report = legacy.run_replay(legacy_config, scenario=scenario)
    except (legacy.RunnerConfigurationError, OSError, ValueError) as exc:
        raise RuntimeConfigError(
            CONFIG_SCHEMA_UNSUPPORTED,
            "the local replay fixture cannot be run",
            field_path="replay_fixture",
            reason="invalid_replay_fixture",
        ) from exc

    evidence_boundary = (
        "Synthetic local tick replay only; it is not HFT capability, real-market execution, "
        "provider activity, profitability, or real-trading admission."
    )
    report["external_request_counts"] = {"network": 0, "order_write": 0}
    report["admission_status"] = "LOCAL_REPLAY_ONLY"
    report["hft_status"] = "NOT_ADMITTED"
    report["evidence_boundary"] = evidence_boundary
    report["runtime_config"] = {
        "config_schema_version": 4,
        "strategy_id": config.strategy_id,
        "mode": config.mode,
        "preset": config.preset,
        "config_digest": config.config_digest,
        "scope": "LOCAL_REPLAY_ONLY",
        "evidence_boundary": evidence_boundary,
        "allows_network": effective.allows_network,
        "allows_external_writes": effective.allows_external_writes,
        "allows_production_writes": effective.allows_production_writes,
    }
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the registered replay or print a safe rejection before startup."""

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
