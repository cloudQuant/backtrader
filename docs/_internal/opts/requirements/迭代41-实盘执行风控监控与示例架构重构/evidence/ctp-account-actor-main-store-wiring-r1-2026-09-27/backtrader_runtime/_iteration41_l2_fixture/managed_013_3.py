#!/usr/bin/env python
"""Offline managed-execution L2 fixture for the 013_3 example.

This runner is deliberately separate from the candidate's normal replay and
SimNow paths.  A code-owned registration must opt into
``offline_managed_execution`` before this module can compose the managed SDK
stack.  It accepts only schema-v4 ``simulation/replay`` and routes every
fixture order to an in-process fake provider while a socket guard rejects
network I/O.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from decimal import Decimal
import importlib
import importlib.metadata
import json
from pathlib import Path
import socket
import tempfile
from typing import Any, Iterator, Optional

from backtrader_runtime.errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
from backtrader_runtime.policy import MANAGED_WRITE_CAPABILITIES
from backtrader_runtime.registry import (
    EffectiveRuntimeConfig,
    RuntimeRegistry,
)
from backtrader_runtime.runner import (
    dispatch_configured_runtime,
    resolve_runner_effective_config,
)


DEFAULT_RUNTIME_DIR = Path(__file__).resolve().parent / "runtimes" / "managed_013_3"
STRATEGY_ID = "example.013_3.sa_midfreq_simnow"
_FAKE_PROVIDER = "iteration41_managed_replay_fake_provider"
_FAKE_ACCOUNT = "iteration41_managed_replay_fake_account"
_FAKE_INSTRUMENT = "ITERATION41.FAKE"
_FAKE_METADATA_VERSION = "iteration41.managed-replay.metadata.v1"
_FAKE_METADATA_NOW_NS = 1_750_000_000_000_000_000
_FAKE_TRADING_DAY = "20260922"
_RESEARCH_STATUS = "RESEARCH_NOT_ESTABLISHED"
_CAPABILITY_VERSIONS = {
    "bt_api_execution": "0.2.0",
    "bt_api_risk": "0.1.0",
    "bt_api_monitor": "0.1.0",
}
# The trusted runner loader preserves the canonical ``__name__`` for policy
# checks while the actual import spec remains private.  Backtrader's class
# factory looks up ``sys.modules[cls.__module__]`` during dynamic Strategy
# construction, so these local fixture Strategies must retain the private
# spec spelling when loaded through that boundary.
_STRATEGY_CLASS_MODULE = __spec__.name if __spec__ is not None else __name__


def runtime_registry() -> RuntimeRegistry:
    """Return the isolated package fixture registry, never a scanned directory."""

    from backtrader_runtime.inventory import iteration41_l2_fixture_registry

    return iteration41_l2_fixture_registry()


@contextmanager
def _network_denied() -> Iterator[list[str]]:
    """Reject socket connection attempts while the offline fixture is active."""

    attempts: list[str] = []
    original_socket = socket.socket
    original_create_connection = socket.create_connection

    class DeniedSocket(original_socket):
        def connect(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            attempts.append("socket.connect")
            raise RuntimeError("offline managed replay forbids network access")

        def connect_ex(self, *args: Any, **kwargs: Any) -> int:
            del args, kwargs
            attempts.append("socket.connect_ex")
            raise RuntimeError("offline managed replay forbids network access")

    def denied_create_connection(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        attempts.append("socket.create_connection")
        raise RuntimeError("offline managed replay forbids network access")

    socket.socket = DeniedSocket
    socket.create_connection = denied_create_connection
    try:
        yield attempts
    finally:
        socket.socket = original_socket
        socket.create_connection = original_create_connection


def _capability_version(distribution: str) -> str:
    """Pin source-checkout capabilities without accepting an installed mismatch."""

    fallback = _CAPABILITY_VERSIONS.get(distribution)
    if fallback is None:
        raise ValueError("unrecognized managed replay capability distribution")
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        # This L2 fixture is intentionally usable against the checked-out SDK
        # packages during repository acceptance.  The source package version
        # is still a per-distribution reviewed constant rather than an ambient
        # import result.
        return fallback


def _require_managed_replay(
    runtime_dir: Optional[Path],
    registry: RuntimeRegistry,
    *,
    effective: Optional[EffectiveRuntimeConfig] = None,
) -> EffectiveRuntimeConfig:
    """Resolve and recheck the one code-owned offline managed shape."""

    effective = resolve_runner_effective_config(runtime_dir, registry, effective=effective)
    config = effective.config
    registration = effective.registration
    valid_shape = (
        config.strategy_id == STRATEGY_ID
        and (config.mode, config.preset) == ("simulation", "replay")
        and config.parameters == {}
        and config.secrets_ref == "none"
        and registration.offline_managed_execution is True
        and registration.allowed_presets == ("replay",)
        and registration.allowed_secrets_refs == ("none",)
        and registration.available_capabilities == MANAGED_WRITE_CAPABILITIES
        and registration.sandbox_write_policy == "deny"
        and registration.approval_receipt_digest is None
        and effective.order_route == "managed_execution"
        and effective.account_access == "fake_provider"
        and effective.required_capabilities == MANAGED_WRITE_CAPABILITIES
        and not effective.allows_network
        and not effective.allows_external_writes
        and not effective.allows_production_writes
        and not effective.requires_approval
    )
    if not valid_shape:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "this runner requires its reviewed offline managed replay registration",
            field_path="runtime.preset",
            reason="offline_managed_registration_required",
        )
    return effective


class _FakeProvider:
    """In-process provider port used only by the managed replay fixture."""

    def __init__(self) -> None:
        self.connected = False
        self.submissions: list[dict[str, Any]] = []
        self.cancellations: list[tuple[Any, Any]] = []
        self.return_unknown_once = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def get_balance(self) -> dict[str, float]:
        return {"cash": 100000.0, "value": 100000.0}

    def get_positions(self) -> list[dict[str, Any]]:
        return []

    def get_open_orders(self) -> list[dict[str, Any]]:
        return []

    def submit_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        if payload.get("symbol") != _FAKE_INSTRUMENT:
            raise RuntimeError("managed replay fake provider received an unexpected instrument")
        self.submissions.append(payload)
        if self.return_unknown_once:
            self.return_unknown_once = False
            # A provider response without a stable provider identity must
            # remain UNKNOWN and freeze later openings.
            return {"status": "accepted"}
        return {"status": "accepted", "id": "fake." + str(payload["bt_order_ref"])}

    def cancel_order(self, order_ref: Any, *, dataname: Optional[str] = None) -> dict[str, Any]:
        self.cancellations.append((order_ref, dataname))
        return {"status": "cancelled", "id": order_ref}


def _managed_info(intent_id: str, metadata_digest: str) -> dict[str, Any]:
    """Return the complete immutable identity required by the strict bridge."""

    return {
        "managed_order_type": "LIMIT",
        "managed_intent_id": intent_id,
        "managed_signal_id": "signal." + intent_id,
        "managed_instrument": _FAKE_INSTRUMENT,
        "managed_position_effect": "OPEN",
        "managed_metadata_version": _FAKE_METADATA_VERSION,
        "managed_instrument_metadata_digest": metadata_digest,
        # These are not cosmetic annotations: the strict managed bridge checks
        # them against the exact legacy Store payload before risk admission and
        # again immediately before the fake provider port can run.
        "offset": "open",
        "reduce_only": False,
    }


def _fixture_data(pandas: Any) -> Any:
    return pandas.DataFrame(
        {
            "open": (10.0, 10.0, 10.0),
            "high": (10.0, 10.0, 10.0),
            "low": (10.0, 10.0, 10.0),
            "close": (10.0, 10.0, 10.0),
            "volume": (1.0, 1.0, 1.0),
        },
        index=pandas.date_range("2024-01-01", periods=3, freq="min"),
    )


def _run_cerebro_stage(
    bt: Any,
    pandas: Any,
    *,
    store: Any,
    broker: Any,
    stage: str,
    metadata_digest: str,
) -> dict[str, str]:
    """Run one real Cerebro/Broker stage against the pre-bound fake provider."""

    class SubmitAndCancel(bt.Strategy):
        __module__ = _STRATEGY_CLASS_MODULE

        def __init__(self) -> None:
            self.cancel_target = None
            self.replay_target = None

        def next(self) -> None:
            if len(self) == 1:
                self.cancel_target = self.buy(
                    size=1,
                    price=10.0,
                    exectype=bt.Order.Limit,
                    **_managed_info("l2.cancel", metadata_digest),
                )
                self.replay_target = self.buy(
                    size=1,
                    price=10.0,
                    exectype=bt.Order.Limit,
                    **_managed_info("l2.restart", metadata_digest),
                )
            elif len(self) == 2:
                self.cancel(self.cancel_target)

    class ReplayAfterRestart(bt.Strategy):
        __module__ = _STRATEGY_CLASS_MODULE

        def __init__(self) -> None:
            self.order = None

        def next(self) -> None:
            if len(self) == 1:
                self.order = self.buy(
                    size=1,
                    price=10.0,
                    exectype=bt.Order.Limit,
                    **_managed_info("l2.after_restart", metadata_digest),
                )

    class UnknownSubmit(bt.Strategy):
        __module__ = _STRATEGY_CLASS_MODULE

        def __init__(self) -> None:
            self.order = None

        def next(self) -> None:
            if len(self) == 1:
                self.order = self.buy(
                    size=1,
                    price=10.0,
                    exectype=bt.Order.Limit,
                    **_managed_info("l2.unknown", metadata_digest),
                )

    class BlockedAfterRestart(bt.Strategy):
        __module__ = _STRATEGY_CLASS_MODULE

        def __init__(self) -> None:
            self.order = None

        def next(self) -> None:
            if len(self) == 1:
                self.order = self.buy(
                    size=1,
                    price=10.0,
                    exectype=bt.Order.Limit,
                    **_managed_info("l2.blocked", metadata_digest),
                )

    strategies = {
        "submit_cancel": SubmitAndCancel,
        "restart_recovery": ReplayAfterRestart,
        "unknown": UnknownSubmit,
        "blocked": BlockedAfterRestart,
    }
    try:
        strategy_type = strategies[stage]
    except KeyError as error:
        raise ValueError("unknown managed replay stage") from error

    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    data = bt.feeds.PandasData(dataname=_fixture_data(pandas))
    cerebro.adddata(data, name=_FAKE_INSTRUMENT)
    cerebro.setbroker(broker)
    cerebro.addstrategy(strategy_type)
    result = cerebro.run()
    strategy = result[0]
    report: dict[str, str] = {}
    for name in ("cancel_target", "replay_target", "order"):
        order = getattr(strategy, name, None)
        if order is not None:
            report[name] = order.getstatusname()
    if not store.managed_execution_active:
        raise RuntimeError("Cerebro stage lost its managed Store binding")
    return report


def _compose_runtime(effective: Any, state_directory: Path, writer_id: str) -> tuple[Any, Any, str]:
    """Load the exact execution/risk/monitor packages after policy acceptance."""

    from bt_api_py.runtime_plugins import (
        CAPABILITY_EXECUTION,
        CAPABILITY_MONITOR,
        CAPABILITY_RISK,
        CapabilityCatalog,
        CapabilityPin,
        RuntimeCapabilityContract,
        SealedNormalizedInstrumentMetadataSnapshot,
        compose_managed_execution,
    )

    contract = RuntimeCapabilityContract.from_effective_public_dict(effective.as_public_dict())
    catalog = CapabilityCatalog(
        (
            CapabilityPin(
                CAPABILITY_EXECUTION,
                "bt_api_execution",
                "bt_api_execution",
                _CAPABILITY_VERSIONS["bt_api_execution"],
            ),
            CapabilityPin(
                CAPABILITY_RISK,
                "bt_api_risk",
                "bt_api_risk",
                _CAPABILITY_VERSIONS["bt_api_risk"],
            ),
            CapabilityPin(
                CAPABILITY_MONITOR,
                "bt_api_monitor",
                "bt_api_monitor",
                _CAPABILITY_VERSIONS["bt_api_monitor"],
            ),
        ),
        importer=importlib.import_module,
        version_getter=_capability_version,
    )
    loaded = catalog.load(contract)
    snapshot = SealedNormalizedInstrumentMetadataSnapshot.from_normalized_payload(
        {
            "provider": _FAKE_PROVIDER,
            "environment": "offline",
            "account_ref": _FAKE_ACCOUNT,
            "trading_day": _FAKE_TRADING_DAY,
            "metadata_version": _FAKE_METADATA_VERSION,
            "as_of_ns": 1_700_000_000_000_000_000,
            "expires_at_ns": 1_800_000_000_000_000_000,
            "account_currency": "USD",
            "instruments": [
                {
                    "instrument": _FAKE_INSTRUMENT,
                    "tick_size": "0.1",
                    "lot_size": "1",
                    "contract_multiplier": "1",
                    "max_gross_notional_account": "1000",
                    "quote_currency": "USD",
                    "fee_currency": "USD",
                    "quote_to_account_fx": "1",
                    "fee_to_account_fx": "1",
                    "taker_fee_bps": "0",
                    "fixed_fee": "0",
                    "max_slippage_bps": "0",
                    "min_quantity": "1",
                    "max_quantity": "8",
                }
            ],
        }
    )
    runtime = compose_managed_execution(
        loaded,
        state_directory=state_directory,
        provider=_FAKE_PROVIDER,
        environment="offline",
        account_ref=_FAKE_ACCOUNT,
        strategy_id=effective.strategy_id,
        writer_id=writer_id,
        policy_id="iteration41.managed_replay.l2",
        max_increase_notional=Decimal("1000"),
        max_increase_count=8,
        permit_ttl_seconds=5.0,
        trading_day=_FAKE_TRADING_DAY,
        instrument_metadata_snapshot=snapshot,
        instrument_clock_ns=lambda: _FAKE_METADATA_NOW_NS,
    )
    admission = runtime.instrument_admission
    if admission is None:
        raise RuntimeError("managed composition did not install the sealed metadata admission")
    return (
        runtime,
        loaded.require(CAPABILITY_MONITOR),
        admission.metadata_digest_for(_FAKE_INSTRUMENT),
    )


def _make_store_and_broker(provider: _FakeProvider) -> tuple[Any, Any]:
    """Create one direct Store/Broker pair before the managed adapter binds it."""

    from backtrader.brokers.btapibroker import BtApiBroker
    from backtrader.stores.btapistore import BtApiStore

    store = BtApiStore(
        provider="btapi",
        api=provider,
        account_cache_ttl=3600.0,
        positions_cache_ttl=3600.0,
        open_orders_cache_ttl=3600.0,
    )
    broker = BtApiBroker(
        store=store,
        provider="btapi",
        cash=100000.0,
        value=100000.0,
        validation_enabled=False,
        cash_check_enabled=False,
        cancel_wait_remote=True,
        flatten_on_stop=False,
    )
    return store, broker


def _consume_monitor(monitor: Any, runtime: Any) -> list[str]:
    """Advance the local durable monitor cursor through an in-process sink."""

    delivered: list[str] = []

    def record(event: Any) -> None:
        delivered.append(str(event.event.event_id))

    consumer = monitor.DurableOutboxConsumer(
        runtime.outbox,
        "iteration41-managed-replay-l2-monitor",
        runtime.scope.key,
        record,
    )
    consumer.consume()
    return delivered


def run_runtime(
    runtime_dir: Optional[Path] = DEFAULT_RUNTIME_DIR,
    *,
    registry: Optional[RuntimeRegistry] = None,
    effective: Optional[EffectiveRuntimeConfig] = None,
    runtime_directory: Optional[object] = None,
) -> dict[str, Any]:
    """Exercise managed submit/cancel/UNKNOWN/restart with zero network I/O."""

    trusted_registry = runtime_registry() if registry is None else registry
    effective = _require_managed_replay(runtime_dir, trusted_registry, effective=effective)
    with _network_denied() as network_attempts, tempfile.TemporaryDirectory(
        prefix="backtrader-iteration41-managed-replay-"
    ) as temporary_root:
        import backtrader as bt
        import pandas

        from backtrader_runtime.managed_execution import bind_managed_execution

        state_directory = Path(temporary_root) / "managed-state"
        provider = _FakeProvider()
        monitor_events: list[str] = []

        first, monitor, metadata_digest = _compose_runtime(
            effective, state_directory, "l2.writer.one"
        )
        try:
            store, broker = _make_store_and_broker(provider)
            bind_managed_execution(store, effective, first)
            first_stage = _run_cerebro_stage(
                bt,
                pandas,
                store=store,
                broker=broker,
                stage="submit_cancel",
                metadata_digest=metadata_digest,
            )
            monitor_events.extend(_consume_monitor(monitor, first))
            cancel_record = first.execution_store.get_cancel("cancel.l2.cancel", scope=first.scope)
            if cancel_record is None or cancel_record.state.value != "CANCELLED":
                raise RuntimeError("managed cancellation did not reach a durable CANCELLED state")
            persisted = first.execution_store.get_intent("l2.cancel", scope=first.scope)
            if (
                persisted is None
                or persisted.tags.get("instrument_metadata_digest") != metadata_digest
            ):
                raise RuntimeError("managed intent did not carry the fixed fake metadata digest")
        finally:
            first.close()

        restarted, monitor, restarted_metadata_digest = _compose_runtime(
            effective, state_directory, "l2.writer.two"
        )
        try:
            if restarted_metadata_digest != metadata_digest:
                raise RuntimeError("fixed fake instrument metadata is not restart-stable")
            recovered = restarted.execution_store.get("l2.restart", scope=restarted.scope)
            if recovered is None or recovered.state.value != "ACKED":
                raise RuntimeError("managed restart did not recover the durable accepted intent")
            store, broker = _make_store_and_broker(provider)
            bind_managed_execution(store, effective, restarted)
            restart_stage = _run_cerebro_stage(
                bt,
                pandas,
                store=store,
                broker=broker,
                stage="restart_recovery",
                metadata_digest=metadata_digest,
            )
            provider.return_unknown_once = True
            store, broker = _make_store_and_broker(provider)
            bind_managed_execution(store, effective, restarted)
            unknown_stage = _run_cerebro_stage(
                bt,
                pandas,
                store=store,
                broker=broker,
                stage="unknown",
                metadata_digest=metadata_digest,
            )
            monitor_events.extend(_consume_monitor(monitor, restarted))
            unknown_record = restarted.execution_store.get("l2.unknown", scope=restarted.scope)
            if unknown_record is None or unknown_record.state.value != "UNKNOWN":
                raise RuntimeError("ambiguous fake-provider response did not remain UNKNOWN")
        finally:
            restarted.close()

        after_unknown, monitor, after_unknown_metadata_digest = _compose_runtime(
            effective, state_directory, "l2.writer.three"
        )
        try:
            if after_unknown_metadata_digest != metadata_digest:
                raise RuntimeError("fixed fake instrument metadata is not restart-stable")
            store, broker = _make_store_and_broker(provider)
            bind_managed_execution(store, effective, after_unknown)
            blocked_stage = _run_cerebro_stage(
                bt,
                pandas,
                store=store,
                broker=broker,
                stage="blocked",
                metadata_digest=metadata_digest,
            )
            monitor_events.extend(_consume_monitor(monitor, after_unknown))
            blocked_record = after_unknown.execution_store.get(
                "l2.blocked", scope=after_unknown.scope
            )
            if blocked_record is None or blocked_record.state.value != "BLOCKED":
                raise RuntimeError("unknown execution did not persist the restart safety block")
        finally:
            after_unknown.close()

    if network_attempts:
        raise RuntimeError("offline managed replay attempted network I/O")
    if len(provider.submissions) != 4 or len(provider.cancellations) != 1:
        raise RuntimeError("managed replay provider dispatch count is not deterministic")
    if provider.submissions[0].get("symbol") != _FAKE_INSTRUMENT:
        raise RuntimeError("managed replay provider did not receive the fixture instrument")

    return {
        "status": "LOCAL_MANAGED_FAKE_PROVIDER_L2_PASS",
        "admission_status": "RESEARCH_NOT_ESTABLISHED",
        "external_network_requests": 0,
        "external_write_requests": 0,
        "actual_fills": 0,
        "provider_submissions": len(provider.submissions),
        "provider_cancellations": len(provider.cancellations),
        "monitor_events": len(monitor_events),
        "fake_instrument_metadata_digest": metadata_digest,
        "stages": {
            "submit_cancel": first_stage,
            "restart_recovery": restart_stage,
            "unknown": unknown_stage,
            "blocked_after_restart": blocked_stage,
        },
        "runtime_config": {
            "strategy_id": effective.strategy_id,
            "mode": effective.mode,
            "preset": effective.preset,
            "scope": "OFFLINE_MANAGED_FAKE_PROVIDER_L2",
            "evidence_boundary": "FAKE_PROVIDER_L2_ONLY_NOT_SIMNOW_OR_PROFITABILITY_EVIDENCE",
            "research_status": _RESEARCH_STATUS,
            "allows_network": effective.allows_network,
            "allows_external_writes": effective.allows_external_writes,
            "allows_production_writes": effective.allows_production_writes,
        },
    }


def main(argv: Optional[list[str]] = None) -> int:
    """Run the exact registered offline fixture or print a redacted rejection."""

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


if __name__ == "__main__":
    raise SystemExit(main())
