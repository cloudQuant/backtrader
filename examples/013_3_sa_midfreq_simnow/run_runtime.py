#!/usr/bin/env python
"""Iteration 41 replay-only entrypoint for the SA mid-frequency fixture.

Copy runtime/config.example.yaml to runtime/config.yaml before running.  This
entrypoint accepts only schema-v4 simulation/replay.  It cannot use the legacy
SimNow mode, a receipt, credentials, or an external provider route.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from typing import Optional
from uuid import uuid4

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
STRATEGY_ID = "example.013_3.sa_midfreq_simnow"
SCENARIOS = frozenset({"no_signal", "reverse", "trend"})
_RESEARCH_STATUS = "RESEARCH_NOT_ESTABLISHED"


def runtime_registry() -> RuntimeRegistry:
    """Use the central reviewed inventory; copied directories are untrusted."""
    return iteration41_runtime_registry()


def _load_replay_runner():
    """Delay Backtrader, Store, and example imports until policy acceptance."""
    if __package__:
        from . import run
    else:
        import run
    return run


def _legacy_replay_config(legacy):
    """Return the frozen local fixture configuration with replay made explicit.

    The old config.yaml remains a source-controlled fixture parameter file.  It
    is never an Iteration 41 runtime contract, cannot select SimNow here, and
    must retain the non-admitted research status before this wrapper will use it.
    """
    try:
        raw, _ = legacy.load_config(legacy.DEFAULT_CONFIG)
    except (legacy.RunnerConfigurationError, OSError, ValueError) as exc:
        raise RuntimeConfigError(
            "CONFIG_SCHEMA_UNSUPPORTED",
            "The frozen local replay fixture is missing or invalid.",
            field_path="replay_fixture",
            reason="invalid_replay_fixture",
        ) from exc

    research = raw.get("research")
    if not isinstance(research, dict) or research.get("status") != _RESEARCH_STATUS:
        raise RuntimeConfigError(
            "PRESET_POLICY_VIOLATION",
            "The replay fixture must remain RESEARCH_NOT_ESTABLISHED.",
            field_path="replay_fixture.research.status",
            reason="replay_research_status_not_established",
        )

    # The legacy fixture predates v4 and records shadow as its operator default.
    # Its replay function is explicit; make that local-only choice visible to the
    # frozen legacy validator as well, without modifying the tracked file.
    replay_config = deepcopy(raw)
    replay_config["mode"] = "replay"
    try:
        legacy.validate_config(replay_config)
    except (legacy.RunnerConfigurationError, ValueError) as exc:
        raise RuntimeConfigError(
            "CONFIG_SCHEMA_UNSUPPORTED",
            "The frozen local replay fixture no longer satisfies its replay contract.",
            field_path="replay_fixture",
            reason="invalid_replay_fixture",
        ) from exc
    return replay_config


def _evidence_directory(runtime_dir: Optional[Path], runtime_directory: Optional[object]) -> Path:
    """Choose a path which cannot follow a replaced POSIX runtime directory.

    Direct invocation retains the documented ``runtime/reports`` location.
    POSIX dispatch deliberately withholds that mutable pathname and supplies a
    descriptor capability instead.  The legacy evidence writer is path based,
    so it runs below a newly-created private workspace until it has its own
    descriptor-aware output API; it must never reconstruct the withheld
    runtime pathname from the sealed config.
    """

    if runtime_dir is not None:
        return runtime_dir.resolve() / "reports" / f"replay-{uuid4().hex}"
    if runtime_directory is None:
        raise RuntimeConfigError(
            "PRESET_POLICY_VIOLATION",
            "A POSIX dispatched replay requires a runtime-directory capability.",
            field_path="runtime.runner",
            reason="runtime_directory_capability_required",
        )
    workspace = Path(tempfile.mkdtemp(prefix="backtrader-iteration41-replay-"))
    return workspace / f"replay-{uuid4().hex}"


def run_runtime(
    runtime_dir: Optional[Path] = DEFAULT_RUNTIME_DIR,
    *,
    registry: Optional[RuntimeRegistry] = None,
    effective: Optional[EffectiveRuntimeConfig] = None,
    runtime_directory: Optional[object] = None,
) -> dict:
    """Validate v4 configuration and run only the deterministic local replay."""
    trusted_registry = runtime_registry() if registry is None else registry
    effective = resolve_runner_effective_config(runtime_dir, trusted_registry, effective=effective)
    config = effective.config
    if config.strategy_id != STRATEGY_ID:
        raise RuntimeConfigError(
            "PRESET_POLICY_VIOLATION",
            "This entrypoint is registered only for the 013_3 local replay strategy.",
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
    scenario = config.parameters.get("scenario", "no_signal")
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise RuntimeConfigError(
            "CONFIG_SCHEMA_UNSUPPORTED",
            "Choose no_signal, reverse, or trend in parameters.scenario.",
            field_path="parameters.scenario",
            reason="invalid_scenario",
        )

    legacy = _load_replay_runner()
    replay_config = _legacy_replay_config(legacy)
    try:
        report = legacy.run_replay(
            replay_config,
            output_directory=_evidence_directory(runtime_dir, runtime_directory),
            scenario=scenario,
            retention_root=None,
        )
    except (legacy.RunnerConfigurationError, OSError, ValueError) as exc:
        raise RuntimeConfigError(
            "CONFIG_SCHEMA_UNSUPPORTED",
            "The local replay fixture could not complete.",
            field_path="replay_fixture",
            reason="invalid_replay_fixture",
        ) from exc

    if report.get("orders") or report.get("sdk_write_requests") != 0:
        raise RuntimeConfigError(
            "PRESET_POLICY_VIOLATION",
            "The local replay reported an order or provider write.",
            field_path="replay_result",
            reason="replay_write_detected",
        )
    report["status"] = "LOCAL_REPLAY_PASS"
    report["external_request_counts"] = {"network": 0, "order_write": 0}
    report["runtime_config"] = {
        "config_schema_version": 4,
        "strategy_id": config.strategy_id,
        "mode": config.mode,
        "preset": config.preset,
        "config_digest": config.config_digest,
        "effective_digest": effective.effective_digest,
        "scope": "LOCAL_REPLAY_ONLY",
        "research_status": _RESEARCH_STATUS,
        "simnow_admission_boundary": "INDEPENDENT_SIMNOW_ADMISSION_REQUIRED",
        "evidence_boundary": "SYNTHETIC_REPLAY_ONLY_NOT_MARKET_OR_PROFITABILITY_EVIDENCE",
        "allows_network": effective.allows_network,
        "allows_external_writes": effective.allows_external_writes,
        "allows_production_writes": effective.allows_production_writes,
    }
    return report


def main(argv=None) -> int:
    """Run the registered local replay or reject before loading strategy code."""
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
