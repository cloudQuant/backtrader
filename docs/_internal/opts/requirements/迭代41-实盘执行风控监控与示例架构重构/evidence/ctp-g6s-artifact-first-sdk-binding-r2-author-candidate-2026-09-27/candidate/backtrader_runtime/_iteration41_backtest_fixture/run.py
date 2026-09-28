"""Run the packaged, credential-free Iteration 41 local-backtest fixture.

This module exists to prove the config-first ``backtest/local_backtest`` path
with the real Cerebro engine.  It has no provider import, no account access,
and no order submission.  Its tiny CSV fixture is package data, so a fresh
wheel installation can run it without a checkout or a network dependency.
"""

from __future__ import annotations

import argparse
import json
import socket
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from backtrader_runtime.errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from backtrader_runtime.registry import EffectiveRuntimeConfig, RuntimeRegistry
from backtrader_runtime.runner import (
    dispatch_configured_runtime,
    resolve_runner_effective_config,
)


DEFAULT_RUNTIME_DIR = Path(__file__).resolve().parent / "runtimes" / "local_backtest"
STRATEGY_ID = "backtrader.iteration41.local_backtest_fixture"
_STRATEGY_CLASS_MODULE = __spec__.name if __spec__ is not None else __name__


def runtime_registry() -> RuntimeRegistry:
    """Return the reviewed inventory that owns this exact fixture."""

    from backtrader_runtime.inventory import iteration41_runtime_registry

    return iteration41_runtime_registry()


@contextmanager
def _network_denied() -> Iterator[list[str]]:
    """Fail closed if the local fixture reaches a Python network entry point."""

    attempts: list[str] = []
    original_socket = socket.socket
    originals: dict[str, object] = {}

    def denied(label: str):
        def _denied(*args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            attempts.append(label)
            raise RuntimeError("local_backtest forbids network access")

        return _denied

    class DeniedSocket(original_socket):
        def connect(self, *args: Any, **kwargs: Any) -> Any:
            return denied("socket.connect")(*args, **kwargs)

        def connect_ex(self, *args: Any, **kwargs: Any) -> int:
            return denied("socket.connect_ex")(*args, **kwargs)

    socket.socket = DeniedSocket
    for name in (
        "create_connection",
        "getaddrinfo",
        "gethostbyaddr",
        "gethostbyname",
        "getnameinfo",
    ):
        if hasattr(socket, name):
            originals[name] = getattr(socket, name)
            setattr(socket, name, denied("socket.{0}".format(name)))
    try:
        yield attempts
    finally:
        socket.socket = original_socket
        for name, original in originals.items():
            setattr(socket, name, original)


def _require_local_backtest(
    runtime_dir: Optional[Path],
    registry: RuntimeRegistry,
    *,
    effective: Optional[EffectiveRuntimeConfig],
) -> EffectiveRuntimeConfig:
    """Recheck the only policy shape this runner can execute."""

    resolved = resolve_runner_effective_config(runtime_dir, registry, effective=effective)
    config = resolved.config
    registration = resolved.registration
    if not (
        config.strategy_id == STRATEGY_ID
        and config.mode == "backtest"
        and config.preset == "local_backtest"
        and config.secrets_ref == "none"
        and registration.runtime_id == STRATEGY_ID
        and registration.allowed_presets == ("local_backtest",)
        and not registration.capability_modules
        and not resolved.allows_network
        and not resolved.allows_external_writes
        and not resolved.allows_production_writes
        and not resolved.requires_approval
    ):
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the packaged local backtest fixture requires its exact offline registration",
            field_path="runtime.preset",
            reason="local_backtest_registration_required",
        )
    return resolved


def run_runtime(
    runtime_dir: Optional[Path],
    *,
    effective: Optional[EffectiveRuntimeConfig] = None,
    registry: Optional[RuntimeRegistry] = None,
    runtime_directory: object = None,
) -> dict[str, Any]:
    """Run four package-owned bars through Cerebro without creating an order."""

    del runtime_directory
    trusted_registry = runtime_registry() if registry is None else registry
    resolved = _require_local_backtest(runtime_dir, trusted_registry, effective=effective)
    data_path = Path(__file__).resolve().parent / "data" / "bars.csv"
    if not data_path.is_file():
        raise RuntimeError("packaged local-backtest CSV fixture is unavailable")

    with _network_denied() as network_attempts:
        import backtrader as bt

        class LocalBacktestStrategy(bt.Strategy):
            __module__ = _STRATEGY_CLASS_MODULE

            def __init__(self) -> None:
                self.bar_count = 0

            def next(self) -> None:
                self.bar_count += 1

        cerebro = bt.Cerebro(stdstats=False, runonce=False)
        cerebro.broker.setcash(10_000.0)
        cerebro.adddata(
            bt.feeds.GenericCSVData(
                dataname=str(data_path),
                dtformat="%Y-%m-%d",
            ),
            name="ITERATION41.LOCAL",
        )
        cerebro.addstrategy(LocalBacktestStrategy)
        strategies = cerebro.run()

    if network_attempts:
        raise RuntimeError("local-backtest fixture attempted network access")
    strategy = strategies[0]
    if strategy.bar_count != 4:
        raise RuntimeError("local-backtest fixture did not consume its four expected bars")
    return {
        "status": "LOCAL_BACKTEST_CEREBRO_PASS",
        "external_network_requests": 0,
        "external_write_requests": 0,
        "actual_fills": 0,
        "provider_submissions": 0,
        "actual_pnl": "NOT_APPLICABLE",
        "pnl_source": "local_backtest_no_orders",
        "data_bars": strategy.bar_count,
        "network_guard_attempts": network_attempts,
        "runtime_config": {
            "strategy_id": resolved.strategy_id,
            "mode": resolved.mode,
            "preset": resolved.preset,
            "environment": resolved.policy.environment,
            "allows_network": resolved.allows_network,
            "allows_external_writes": resolved.allows_external_writes,
            "allows_production_writes": resolved.allows_production_writes,
        },
    }


def main(argv: Optional[list[str]] = None) -> int:
    """Run the exact configured fixture or emit a redacted policy rejection."""

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    args = parser.parse_args(argv)
    try:
        report = dispatch_configured_runtime(args.runtime_dir, runtime_registry())
    except RuntimeConfigError as error:
        print(json.dumps({"status": "REJECTED", "error": error.as_dict()}, sort_keys=True))
        return 2
    print(json.dumps(report, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through package entrypoints
    raise SystemExit(main())
