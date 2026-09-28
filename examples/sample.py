#!/usr/bin/env python
"""Fail-closed Iteration 41 migration shell for the historical CTP sample.

The former version of this file imported ``ctpbeebt.CTPStore`` at module
import time, loaded ``params_01.json`` from the current working directory, and
could dispatch ``beeapi.action`` calls directly. That route predated the
configuration-first runtime contract and bypassed the Backtrader/SDK execution
boundary. It is deliberately *not* an Iteration 41 execution route.

The only supported entry point is the registered, local ``simulation/replay``
audit profile in ``examples/sample/runtime``. It validates mandatory schema-v4
``config.yaml`` and returns a zero-I/O migration report. Sandbox and live
execution are ``NOT_SUPPORTED`` until this example has a separately reviewed
managed SDK/execution migration.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, time
from pathlib import Path
import sys
from typing import Any, Dict, Optional


HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

# ``backtrader_runtime`` is intentionally dependency-free with respect to
# Backtrader, CTP, providers, gateways, and execution packages. Keep this
# import before any legacy strategy/provider import so a bad contract rejects
# without loading an external trading dependency.  # noqa: E402
from backtrader_runtime import (  # noqa: E402
    dispatch_configured_runtime,
    EffectiveRuntimeConfig,
    RuntimeConfigError,
    RuntimeRegistry,
    iteration41_runtime_registry,
    resolve_runner_effective_config,
)


STRATEGY_ID = "example.sample.ctp_legacy"
DEFAULT_RUNTIME_DIR = HERE / "sample" / "runtime"
LOCAL_SCENARIO = "no_action"
LEGACY_PARAMS_FILENAME = "params_01.json"


# These constants and the time helper remain pure local compatibility helpers.
# They do not authorize a provider session or turn the migration shell into a
# CTP runner.
DAY_START = time(8, 45)
DAY_END = time(15, 0)
NIGHT_START = time(20, 45)
NIGHT_END = time(2, 45)


class Origin:
    """Retained data-name adapter with no provider or execution behavior."""

    def __init__(self, data: Any) -> None:
        self.symbol = data._dataname.split(".")[0]
        self.exchange = data._name.split(".")[1]


def is_trading_period(now: Optional[datetime] = None) -> bool:
    """Return the historical CTP session-window calculation without I/O."""

    current_time = (datetime.now() if now is None else now).time()
    return (
        DAY_START <= current_time <= DAY_END
        or current_time >= NIGHT_START
        or current_time <= NIGHT_END
    )


class LegacyDirectExecutionDisabled(RuntimeError):
    """Raised before a historical direct action can reach an external object."""

    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(
            "legacy direct CTP action '{0}' is disabled; use a separately reviewed "
            "managed SDK/execution migration".format(action)
        )


def _reject_legacy_direct_execution(action: str) -> None:
    """Reject a legacy action without dereferencing ``beeapi`` or ``action``."""

    raise LegacyDirectExecutionDisabled(action)


class SmaCross:
    """Compatibility shell for the historical sample's direct action names.

    It intentionally no longer subclasses ``bt.Strategy``: importing the old
    framework/provider path merely to make a disabled direct writer available
    would violate the fail-closed startup boundary. The names remain here so
    old callers receive a deterministic rejection before any fake or real
    ``beeapi.action`` object can be touched.
    """

    lines = ("sma",)
    params = {"smaperiod": 5, "store": None}

    def open_long(self, price: Any, size: Any, data: Any) -> None:
        del price, size, data
        _reject_legacy_direct_execution("buy")

    def open_short(self, price: Any, size: Any, data: Any) -> None:
        del price, size, data
        _reject_legacy_direct_execution("short")

    def close_long(self, price: Any, size: Any, data: Any) -> None:
        del price, size, data
        _reject_legacy_direct_execution("cover")

    def close_short(self, price: Any, size: Any, data: Any) -> None:
        del price, size, data
        _reject_legacy_direct_execution("sell")


def runtime_registry() -> RuntimeRegistry:
    """Return only the code-owned Iteration 41 registry."""

    return iteration41_runtime_registry()


def _validate_sample_profile(config: Any, effective: Any) -> None:
    """Bind this retired direct sample to one local no-action profile."""

    if config.strategy_id != STRATEGY_ID:
        raise RuntimeConfigError(
            "PRESET_POLICY_VIOLATION",
            "This migration shell is registered only for the historical sample strategy.",
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
            "The historical CTP sample supports only the local no-action replay profile.",
            field_path="runtime.preset",
            reason="preset_not_bound",
        )
    scenario = config.parameters.get("scenario", LOCAL_SCENARIO)
    if scenario != LOCAL_SCENARIO:
        raise RuntimeConfigError(
            "CONFIG_SCHEMA_UNSUPPORTED",
            "The historical CTP migration profile accepts only parameters.scenario=no_action.",
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
    """Validate mandatory config and report a pure local, read-only migration.

    No CTP library, Backtrader strategy, parameter JSON, credential, provider,
    socket, broker, or action object is loaded on this route.
    """

    trusted_registry = runtime_registry() if registry is None else registry
    effective = resolve_runner_effective_config(runtime_dir, trusted_registry, effective=effective)
    config = effective.config
    _validate_sample_profile(config, effective)

    return {
        "status": "LOCAL_REPLAY_PASS",
        "admission_status": "LOCAL_REPLAY_ONLY",
        "scenario": LOCAL_SCENARIO,
        "external_request_counts": {"network": 0, "order_write": 0},
        "legacy_direct_execution": "NOT_SUPPORTED",
        "legacy_parameter_source": {
            "path": LEGACY_PARAMS_FILENAME,
            "status": "IGNORED_BY_ITERATION41_RUNTIME",
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
    """Run the no-action migration report or reject before legacy imports."""

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
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
