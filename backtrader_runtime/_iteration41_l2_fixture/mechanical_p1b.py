#!/usr/bin/env python
"""Offline managed-execution L2 fixture for the CTP mechanical rail.

This entrypoint is deliberately separate from the SimNow operator and CTP
production paths.  It can only run after a reviewed schema-v4 replay
registration resolves to ``offline_managed_execution``.  It uses the real
Backtrader Cerebro/Broker/Store route and the existing three-leg
``MechanicalCycle`` state machine, but every provider interaction stays inside
one in-process fake provider.  It is evidence for a local fake-provider L2
fixture only; it is not a CTP, SimNow, or real-trading launcher.
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
from typing import Any, Iterator, Mapping, Optional

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


DEFAULT_RUNTIME_DIR = Path(__file__).resolve().parent / "runtimes" / "mechanical_p1b"
STRATEGY_ID = "example.ctp_options_simnow.mechanical_managed_replay_l2"
RUNTIME_ID = "example.ctp_options_simnow.mechanical_managed_replay_l2"
_SOURCE_COMPAT_RUNNER_MODULE = "examples.ctp_options_simnow_managed_replay_runtime"
_FAKE_PROVIDER = "iteration41_ctp_mechanical_fake_provider"
_FAKE_ACCOUNT = "iteration41_ctp_mechanical_fake_account"
_FAKE_INSTRUMENTS = (
    "DCE.M2401",
    "DCE.M2401-C-2500",
    "DCE.M2401-P-2500",
)
_FAKE_METADATA_VERSION = "iteration41.ctp-mechanical-replay.metadata.v1"
_FAKE_METADATA_NOW_NS = 1_750_000_000_000_000_000
_FAKE_TRADING_DAY = "20260922"
_CAPABILITY_VERSIONS = {
    "bt_api_execution": "0.2.0",
    "bt_api_risk": "0.1.0",
    "bt_api_monitor": "0.1.0",
}
_EVIDENCE_BOUNDARY = "FAKE_PROVIDER_L2_ONLY_NOT_CTP_SIMNOW_OR_REAL_TRADING_EVIDENCE"
# See the matching 013_3 fixture note: dynamic Strategy subclasses need the
# private import-spec spelling while a trusted loader keeps module.__name__
# canonical for the registration check below.
_STRATEGY_CLASS_MODULE = __spec__.name if __spec__ is not None else __name__


def runtime_registry() -> RuntimeRegistry:
    """Return the isolated package fixture registry, never a scanned directory."""

    from backtrader_runtime.inventory import iteration41_l2_fixture_registry

    return iteration41_l2_fixture_registry()


@contextmanager
def _network_denied() -> Iterator[list[str]]:
    """Reject every socket connection attempt made by this offline fixture."""

    attempts: list[str] = []
    original_socket = socket.socket
    original_create_connection = socket.create_connection

    class DeniedSocket(original_socket):
        def connect(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            attempts.append("socket.connect")
            raise RuntimeError("offline mechanical replay forbids network access")

        def connect_ex(self, *args: Any, **kwargs: Any) -> int:
            del args, kwargs
            attempts.append("socket.connect_ex")
            raise RuntimeError("offline mechanical replay forbids network access")

    def denied_create_connection(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        attempts.append("socket.create_connection")
        raise RuntimeError("offline mechanical replay forbids network access")

    socket.socket = DeniedSocket
    socket.create_connection = denied_create_connection
    try:
        yield attempts
    finally:
        socket.socket = original_socket
        socket.create_connection = original_create_connection


def _capability_version(distribution: str) -> str:
    """Pin source-checkout SDK capabilities without trusting ambient versions."""

    fallback = _CAPABILITY_VERSIONS.get(distribution)
    if fallback is None:
        raise ValueError("unrecognized mechanical replay capability distribution")
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return fallback


def _require_managed_replay(
    runtime_dir: Optional[Path],
    registry: RuntimeRegistry,
    *,
    effective: Optional[EffectiveRuntimeConfig] = None,
) -> EffectiveRuntimeConfig:
    """Resolve the one sealed offline managed shape before optional imports."""

    effective = resolve_runner_effective_config(runtime_dir, registry, effective=effective)
    config = effective.config
    registration = effective.registration
    valid_shape = (
        config.strategy_id == STRATEGY_ID
        and (config.mode, config.preset) == ("simulation", "replay")
        and config.parameters == {}
        and config.secrets_ref == "none"
        and registration.runtime_id == RUNTIME_ID
        and registration.offline_managed_execution is True
        and registration.allowed_presets == ("replay",)
        and registration.allowed_secrets_refs == ("none",)
        and registration.available_capabilities == MANAGED_WRITE_CAPABILITIES
        and registration.sandbox_write_policy == "deny"
        and registration.approval_receipt_digest is None
        # The source-tree compatibility wrapper intentionally delegates to
        # this package implementation.  Both module names are code-owned and
        # the enclosing dispatcher still requires an exact reviewed registry
        # binding before it imports either one.
        and registration.runner_module in (__name__, _SOURCE_COMPAT_RUNNER_MODULE)
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
            "this runner requires its reviewed offline mechanical replay registration",
            field_path="runtime.preset",
            reason="offline_managed_registration_required",
        )
    return effective


class _FakeProvider:
    """In-process provider port used only by this local mechanical fixture."""

    def __init__(self) -> None:
        self.connected = False
        self.submissions: list[dict[str, Any]] = []
        self.cancellations: list[tuple[Any, Any]] = []
        self.reject_once = False
        self.unknown_once = False

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
        if payload.get("symbol") not in _FAKE_INSTRUMENTS:
            raise RuntimeError("mechanical replay received an unexpected fake instrument")
        self.submissions.append(payload)
        if self.reject_once:
            self.reject_once = False
            return {"status": "rejected", "reason": "fixture_rejection"}
        if self.unknown_once:
            self.unknown_once = False
            # An apparent acknowledgement without stable provider identity is
            # intentionally UNKNOWN to the execution facade.
            return {"status": "accepted"}
        return {"status": "accepted", "id": "p1b.fake." + str(payload["bt_order_ref"])}

    def cancel_order(self, order_ref: Any, *, dataname: Optional[str] = None) -> dict[str, Any]:
        self.cancellations.append((order_ref, dataname))
        return {"status": "cancelled", "id": order_ref}


def _compose_runtime(
    effective: Any, state_directory: Path, writer_id: str
) -> tuple[Any, Any, dict[str, str]]:
    """Compose execution/risk/monitor only after the sealed replay check."""

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
                    "instrument": instrument,
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
                    "max_quantity": "1",
                }
                for instrument in _FAKE_INSTRUMENTS
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
        policy_id="iteration41.ctp-mechanical-replay.l2",
        max_increase_notional=Decimal("10000"),
        max_increase_count=24,
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
        {instrument: admission.metadata_digest_for(instrument) for instrument in _FAKE_INSTRUMENTS},
    )


def _make_store_and_broker(provider: _FakeProvider) -> tuple[Any, Any]:
    """Build one real Backtrader Store/Broker pair over the fake provider."""

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
    """Advance a durable local monitor cursor with an in-process sink."""

    delivered: list[str] = []

    def record(event: Any) -> None:
        delivered.append(str(event.event.event_id))

    consumer = monitor.DurableOutboxConsumer(
        runtime.outbox,
        "iteration41-ctp-mechanical-replay-monitor",
        runtime.scope.key,
        record,
    )
    consumer.consume()
    return delivered


def _proof(mechanical: Any) -> dict[str, Any]:
    """Return the fixed, reviewed fake reconciliation proof for one cycle."""

    snapshot = {
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "account_fingerprint": "iteration41-fake-ctp-account",
        "trading_day": "20990101",
        "connection_generation": 1,
        "flat": True,
        "active_order_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "nonzero_positions": [],
        "active_orders": [],
    }
    semantic = mechanical._semantic_hash(snapshot)
    return {
        "settlement_verified": True,
        "bundle_preflight": dict(snapshot),
        "reconciliation_rounds": (dict(snapshot), dict(snapshot)),
        "reconciliation_semantic_hashes": (semantic, semantic),
        "execution_authorization": {
            "armed": True,
            "account_fingerprint": snapshot["account_fingerprint"],
            "connection_generation": snapshot["connection_generation"],
        },
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


class _ManagedMechanicalBroker:
    """Public broker facade that binds every MechanicalCycle child to metadata.

    The cycle still sees only ``buy``, ``sell`` and ``cancel``.  This thin
    facade supplies the immutable managed-execution fields that the generic
    mechanical state machine deliberately does not know about, then delegates
    to the real ``BtApiBroker``.  It is local fixture wiring, not a second
    execution implementation.
    """

    def __init__(self, broker: Any, metadata_digests: Mapping[str, str]) -> None:
        self._broker = broker
        self._metadata_digests = dict(metadata_digests)

    @staticmethod
    def _data_name(data: Any) -> str:
        name = getattr(data, "_name", None)
        if not isinstance(name, str) or not name:
            raise RuntimeError("mechanical fake data has no registered instrument name")
        return name

    def _annotate(self, kwargs: Mapping[str, Any], *, side: str) -> dict[str, Any]:
        result = dict(kwargs)
        instrument = self._data_name(result.get("data"))
        digest = self._metadata_digests.get(instrument)
        if digest is None:
            raise RuntimeError("mechanical order uses an unreviewed fake instrument")
        intent_id = result.get("intent_id")
        if not isinstance(intent_id, str) or not intent_id:
            raise RuntimeError("mechanical order lacks its child intent identity")
        offset = result.get("offset")
        if offset not in {"open", "close"}:
            raise RuntimeError("mechanical order has an invalid offset")
        result.update(
            managed_order_type="LIMIT",
            managed_intent_id=intent_id,
            managed_signal_id="p1b.mechanical." + intent_id,
            managed_instrument=instrument,
            managed_position_effect="OPEN" if offset == "open" else "CLOSE",
            managed_metadata_version=_FAKE_METADATA_VERSION,
            managed_instrument_metadata_digest=digest,
            # Bind the framework-side offset/reduce semantics to the durable
            # managed intent; the bridge rejects any divergence before its
            # private fake-provider dispatcher is reached.
            reduce_only=offset != "open",
            execution_role="entry" if offset == "open" else "exit",
            mechanical_fixture_side=side,
        )
        return result

    def buy(self, **kwargs: Any) -> Any:
        return self._broker.buy(**self._annotate(kwargs, side="buy"))

    def sell(self, **kwargs: Any) -> Any:
        return self._broker.sell(**self._annotate(kwargs, side="sell"))

    def cancel(self, order: Any) -> Any:
        return self._broker.cancel(order)


def _order_info(order: Any, **values: Any) -> None:
    """Add only local synthetic callback fields needed by MechanicalCycle."""

    adder = getattr(order, "addinfo", None)
    if callable(adder):
        adder(**values)
        return
    info = getattr(order, "info", None)
    updater = getattr(info, "update", None)
    if callable(updater):
        updater(values)
        return
    raise RuntimeError("mechanical fixture cannot annotate a framework order")


def _mark_synthetic_native_fill(order: Any, *, trade_id: str) -> None:
    """Shape a local fake callback so MechanicalCycle can exercise its guard.

    This does not call a provider or change the fixture's ``actual_fills=0``
    evidence boundary.  It is a callback-shape double required to drive the
    pre-existing cycle's strict native-identity branch in a local test.
    """

    order.status = getattr(order, "Completed", 4)
    _order_info(
        order,
        ctp_order_ref="p1b-native-" + str(getattr(order, "ref", "unknown")),
        front_id=1,
        session_id=1,
        external_order_id="p1b-system-" + str(getattr(order, "ref", "unknown")),
        trade_id=trade_id,
        connection_generation=1,
        execution_fill_source="trade",
    )


def _mark_terminal_cancel(order: Any) -> None:
    """Ensure the already-dispatched local cancel reaches the cycle callback."""

    order.status = getattr(order, "Canceled", getattr(order, "Cancelled", 5))


def _cycle_report(cycle: Any) -> dict[str, Any]:
    return {
        "state": cycle.state,
        "phase": cycle.phase,
        "journal_statuses": [row["status"] for row in cycle.journal],
        "child_intent_hashes": [
            row["intent_id_hash"] for row in cycle.journal if row["status"] == "ORDER_SUBMITTED"
        ],
    }


def run_runtime(
    runtime_dir: Optional[Path] = DEFAULT_RUNTIME_DIR,
    *,
    registry: Optional[RuntimeRegistry] = None,
    effective: Optional[EffectiveRuntimeConfig] = None,
    runtime_directory: Optional[object] = None,
) -> dict[str, Any]:
    """Exercise P1-B three-leg mechanics through an offline managed L2 stack."""

    trusted_registry = runtime_registry() if registry is None else registry
    effective = _require_managed_replay(runtime_dir, trusted_registry, effective=effective)
    with _network_denied() as network_attempts, tempfile.TemporaryDirectory(
        prefix="backtrader-iteration41-ctp-mechanical-replay-"
    ) as temporary_root:
        import backtrader as bt
        import pandas

        from backtrader_runtime.managed_execution import bind_managed_execution

        state_directory = Path(temporary_root) / "managed-state"
        provider = _FakeProvider()

        # The generic MechanicalCycle has no writer authority. This
        # invocation-local subclass exists only after the sealed replay gate
        # and closes over the exact fake provider created above. Its broker
        # check is repeated before every submit/cancel, before method lookup.
        from backtrader.brokers.btapibroker import BtApiBroker
        from backtrader.stores.btapistore import BtApiStore
        from .mechanical_cycle import (
            MechanicalCycle as GenericMechanicalCycle,
            MechanicalCycleBlocked,
        )

        class _RegisteredFakeReplayCycle(GenericMechanicalCycle):
            def _require_dispatch_authority(self) -> None:
                if (
                    effective.registration.offline_managed_execution is not True
                    or effective.order_route != "managed_execution"
                    or effective.account_access != "fake_provider"
                    or effective.allows_network
                    or effective.allows_external_writes
                    or effective.allows_production_writes
                ):
                    raise MechanicalCycleBlocked("OFFLINE_REPLAY_ADMISSION_REQUIRED")
                facade = object.__getattribute__(self, "broker")
                if type(facade) is not _ManagedMechanicalBroker:
                    raise MechanicalCycleBlocked("CODE_OWNED_FAKE_BROKER_REQUIRED")
                facade_state = object.__getattribute__(facade, "__dict__")
                native_broker = facade_state.get("_broker")
                if type(native_broker) is not BtApiBroker:
                    raise MechanicalCycleBlocked("CODE_OWNED_FAKE_BROKER_REQUIRED")
                broker_state = object.__getattribute__(native_broker, "__dict__")
                store = broker_state.get("store")
                if type(store) is not BtApiStore:
                    raise MechanicalCycleBlocked("CODE_OWNED_FAKE_STORE_REQUIRED")
                store_state = object.__getattribute__(store, "__dict__")
                if store_state.get("_api") is not provider:
                    raise MechanicalCycleBlocked("INVOCATION_FAKE_PROVIDER_REQUIRED")

        def _run_mechanical_cerebro_stage(
            *,
            store: Any,
            broker: Any,
            metadata_digests: Mapping[str, str],
            stage: str,
        ) -> dict[str, Any]:
            """Run one real Cerebro stage through the unchanged mechanical state machine."""

            from . import mechanical_cycle as mechanical

            MechanicalCycle = _RegisteredFakeReplayCycle
            MechanicalCycleBlocked = mechanical.MechanicalCycleBlocked

            class MechanicalFixtureStrategy(bt.Strategy):
                __module__ = _STRATEGY_CLASS_MODULE

                def __init__(self) -> None:
                    self.stage_report: dict[str, Any] = {}
                    self._fixture_done = False

                def _cycle(self, label: str) -> Any:
                    facade = _ManagedMechanicalBroker(self.broker, metadata_digests)
                    cycle = MechanicalCycle(
                        broker=facade,
                        owner=self,
                        feeds={
                            instrument: self.getdatabyname(instrument) for instrument in _FAKE_INSTRUMENTS
                        },
                        cycle_id="iteration41-p1b-" + label,
                    )
                    cycle.arm(_proof(mechanical))
                    return cycle

                @staticmethod
                def _legs(mechanical: Any) -> list[Any]:
                    return [
                        mechanical.MechanicalLeg(instrument, "buy", 10.0, None)
                        for instrument in _FAKE_INSTRUMENTS
                    ]

                @staticmethod
                def _child_projection(order: Any) -> dict[str, Any]:
                    info = getattr(order, "info", {})
                    getter = getattr(info, "get", lambda _name, default=None: default)
                    return {
                        "intent_id": getter("managed_intent_id"),
                        "instrument": getter("managed_instrument"),
                        "offset": getter("offset"),
                        "metadata_bound": isinstance(getter("managed_instrument_metadata_digest"), str),
                    }

                def _complete_three_leg_cycle(self, cycle: Any, *, label: str) -> list[dict[str, Any]]:
                    entry_legs = self._legs(mechanical)
                    children: list[dict[str, Any]] = []
                    cycle.plan_entry(entry_legs, intent_id="p1b." + label + ".entry")
                    for index in range(3):
                        order = cycle.submit_next_entry()
                        children.append(self._child_projection(order))
                        _mark_synthetic_native_fill(order, trade_id="p1b-open-" + str(index))
                        cycle.on_order_update(order)
                    cycle.plan_exit(
                        [
                            mechanical.MechanicalLeg(leg.symbol, "sell", 10.0, leg.data)
                            for leg in entry_legs
                        ],
                        intent_id="p1b." + label + ".compensation",
                    )
                    for index in range(3):
                        order = cycle.submit_next_exit()
                        children.append(self._child_projection(order))
                        _mark_synthetic_native_fill(order, trade_id="p1b-close-" + str(index))
                        cycle.on_order_update(order)
                    stable = _proof(mechanical)["bundle_preflight"]
                    cycle.finalize_flat(dict(stable), dict(stable))
                    return children

                def _cancel_then_run_separate_clean_cycle(self) -> None:
                    """Show cancel fail-closed, then exercise a separate clean cycle.

                    The cancelled child has no confirmed native fill, so there is no
                    exposure from which this offline fixture could truthfully derive a
                    compensation plan.  The second cycle is intentionally independent:
                    it covers the existing three-leg open/close mechanics, not recovery
                    of the cancelled order.
                    """

                    cancelled = self._cycle("cancelled")
                    cancelled.plan_entry(self._legs(mechanical), intent_id="p1b.cancelled.entry")
                    pending = cancelled.submit_next_entry()
                    cancelled.cancel_pending()
                    _mark_terminal_cancel(pending)
                    try:
                        cancelled.on_order_update(pending)
                    except MechanicalCycleBlocked as error:
                        if str(error) != "ORDER_TERMINAL_WITHOUT_NATIVE_FILL":
                            raise
                    else:
                        raise RuntimeError("cancelled mechanical child was not fail-closed")
                    if cancelled.state != "RECOVERY_REQUIRED":
                        raise RuntimeError("cancelled mechanical cycle did not require recovery")

                    recovered = self._cycle("recovered")
                    children = self._complete_three_leg_cycle(recovered, label="recovered")
                    self.stage_report = {
                        "cancel_requires_recovery": _cycle_report(cancelled),
                        "separate_clean_cycle_compensation": _cycle_report(recovered),
                        "separate_clean_cycle_children": children,
                    }

                def _provider_rejected(self) -> None:
                    rejected = self._cycle("rejected")
                    rejected.plan_entry(self._legs(mechanical), intent_id="p1b.rejected.entry")
                    order = rejected.submit_next_entry()
                    try:
                        rejected.on_order_update(order)
                    except MechanicalCycleBlocked as error:
                        if str(error) != "ORDER_TERMINAL_WITHOUT_NATIVE_FILL":
                            raise
                    else:
                        raise RuntimeError("rejected mechanical child was not fail-closed")
                    self.stage_report = {"rejected": _cycle_report(rejected)}

                def _unknown(self) -> None:
                    unknown = self._cycle("unknown")
                    unknown.plan_entry(self._legs(mechanical), intent_id="p1b.unknown.entry")
                    order = unknown.submit_next_entry()
                    info = getattr(order, "info", {})
                    getter = getattr(info, "get", lambda _name, default=None: default)
                    if getter("execution_unknown") is not True:
                        raise RuntimeError("ambiguous fake-provider response was not marked UNKNOWN")
                    try:
                        unknown.timeout()
                    except MechanicalCycleBlocked as error:
                        if str(error) != "TIMEOUT_RECOVERY_REQUIRED":
                            raise
                    self.stage_report = {"unknown": _cycle_report(unknown)}

                def _blocked_after_restart(self) -> None:
                    blocked = self._cycle("blocked")
                    blocked.plan_entry(self._legs(mechanical), intent_id="p1b.blocked.entry")
                    order = blocked.submit_next_entry()
                    getstatusname = getattr(order, "getstatusname", None)
                    status = str(getstatusname() if callable(getstatusname) else "").casefold()
                    info = getattr(order, "info", {})
                    getter = getattr(info, "get", lambda _name, default=None: default)
                    # The persisted UNKNOWN dispatch freeze must be observed by the
                    # restarted risk gate before the fake-provider port can be called.
                    # A generic mechanical callback failure alone would not prove that
                    # this was a managed pre-dispatch block.
                    if status != "rejected" or getter("remote_error_code") != "managed_execution_blocked":
                        raise RuntimeError("restart unknown freeze did not reject before provider dispatch")
                    try:
                        blocked.on_order_update(order)
                    except MechanicalCycleBlocked as error:
                        if str(error) != "ORDER_TERMINAL_WITHOUT_NATIVE_FILL":
                            raise
                    else:
                        raise RuntimeError("restart safety block did not stop the mechanical child")
                    self.stage_report = {
                        "blocked_after_restart": _cycle_report(blocked),
                        "framework_status": status,
                        "managed_rejection": getter("remote_error_code"),
                    }

                def next(self) -> None:
                    if self._fixture_done or len(self) != 1:
                        return
                    self._fixture_done = True
                    if stage == "cancel_then_separate_clean_cycle":
                        self._cancel_then_run_separate_clean_cycle()
                    elif stage == "provider_rejected":
                        self._provider_rejected()
                    elif stage == "unknown":
                        self._unknown()
                    elif stage == "blocked_after_restart":
                        self._blocked_after_restart()
                    else:
                        raise RuntimeError("unknown mechanical replay stage")

            cerebro = bt.Cerebro(stdstats=False, runonce=False)
            for instrument in _FAKE_INSTRUMENTS:
                cerebro.adddata(bt.feeds.PandasData(dataname=_fixture_data(pandas)), name=instrument)
            cerebro.setbroker(broker)
            cerebro.addstrategy(MechanicalFixtureStrategy)
            result = cerebro.run()
            report = result[0].stage_report
            if not store.managed_execution_active:
                raise RuntimeError("Cerebro stage lost its managed Store binding")
            if not report:
                raise RuntimeError("Cerebro did not enter the mechanical fixture stage")
            return report

        monitor_events: list[str] = []
        synthetic_callback_fills = 0
        sdk_confirmed_fills = 0
        first, monitor, metadata_digests = _compose_runtime(
            effective, state_directory, "p1b.writer.one"
        )
        try:
            store, broker = _make_store_and_broker(provider)
            bind_managed_execution(store, effective, first)
            cancel_and_separate_clean_cycle = _run_mechanical_cerebro_stage(
                store=store,
                broker=broker,
                metadata_digests=metadata_digests,
                stage="cancel_then_separate_clean_cycle",
            )
            cancelled_intent = "p1b.cancelled.entry:open:0"
            cancel_record = first.execution_store.get_cancel(
                "cancel." + cancelled_intent, scope=first.scope
            )
            if cancel_record is None or cancel_record.state.value != "CANCELLED":
                raise RuntimeError("mechanical fixture cancellation was not durably confirmed")
            recovery_open_intents = (
                "p1b.recovered.entry:open:0",
                "p1b.recovered.entry:open:0:open:1",
                "p1b.recovered.entry:open:0:open:1:open:2",
            )
            recovery_close_intents = (
                "p1b.recovered.compensation:close:0",
                "p1b.recovered.compensation:close:0:close:1",
                "p1b.recovered.compensation:close:0:close:1:close:2",
            )
            recovery_intents = recovery_open_intents + recovery_close_intents
            synthetic_callback_fills = len(
                cancel_and_separate_clean_cycle["separate_clean_cycle_children"]
            )
            if synthetic_callback_fills != len(recovery_intents):
                raise RuntimeError("mechanical synthetic callback count is incomplete")
            for index, intent_id in enumerate(recovery_open_intents + recovery_close_intents):
                intent = first.execution_store.get_intent(intent_id, scope=first.scope)
                record = first.execution_store.get(intent_id, scope=first.scope)
                instrument = _FAKE_INSTRUMENTS[index % len(_FAKE_INSTRUMENTS)]
                if (
                    intent is None
                    or record is None
                    or intent.tags.get("instrument_metadata_digest") != metadata_digests[instrument]
                ):
                    raise RuntimeError(
                        "mechanical child lacks its fixed instrument metadata digest"
                    )
                if record.state.value == "FILLED":
                    sdk_confirmed_fills += 1
            if sdk_confirmed_fills != 0:
                raise RuntimeError("offline mechanical callbacks cannot become SDK fill evidence")

            provider.reject_once = True
            store, broker = _make_store_and_broker(provider)
            bind_managed_execution(store, effective, first)
            rejected = _run_mechanical_cerebro_stage(
                store=store,
                broker=broker,
                metadata_digests=metadata_digests,
                stage="provider_rejected",
            )

            provider.unknown_once = True
            store, broker = _make_store_and_broker(provider)
            bind_managed_execution(store, effective, first)
            unknown = _run_mechanical_cerebro_stage(
                store=store,
                broker=broker,
                metadata_digests=metadata_digests,
                stage="unknown",
            )
            monitor_events.extend(_consume_monitor(monitor, first))
            unknown_record = first.execution_store.get(
                "p1b.unknown.entry:open:0", scope=first.scope
            )
            if unknown_record is None or unknown_record.state.value != "UNKNOWN":
                raise RuntimeError(
                    "ambiguous mechanical fake-provider order did not remain UNKNOWN"
                )
        finally:
            first.close()

        restarted, monitor, restarted_digests = _compose_runtime(
            effective, state_directory, "p1b.writer.two"
        )
        try:
            if restarted_digests != metadata_digests:
                raise RuntimeError("fixed mechanical metadata changed across durable restart")
            unknown_freeze = "dispatch-inflight:p1b.unknown.entry:open:0"
            active_freezes = restarted.risk_gate.active_freeze_reasons(restarted.risk_scope)
            if unknown_freeze not in active_freezes:
                raise RuntimeError("durable UNKNOWN dispatch freeze was not restored on restart")
            restarted_unknown_record = restarted.execution_store.get(
                "p1b.unknown.entry:open:0", scope=restarted.scope
            )
            if (
                restarted_unknown_record is None
                or restarted_unknown_record.state.value != "UNKNOWN"
                or not restarted_unknown_record.review_required
                or restarted_unknown_record.dispatch_attempts != 1
            ):
                raise RuntimeError("durable UNKNOWN execution record changed across restart")
            provider_submissions_before_restart = len(provider.submissions)
            store, broker = _make_store_and_broker(provider)
            bind_managed_execution(store, effective, restarted)
            blocked = _run_mechanical_cerebro_stage(
                store=store,
                broker=broker,
                metadata_digests=restarted_digests,
                stage="blocked_after_restart",
            )
            if len(provider.submissions) != provider_submissions_before_restart:
                raise RuntimeError("restart UNKNOWN block reached the fake provider")
            monitor_events.extend(_consume_monitor(monitor, restarted))
            blocked_record = restarted.execution_store.get(
                "p1b.blocked.entry:open:0", scope=restarted.scope
            )
            if (
                blocked_record is None
                or blocked_record.state.value != "BLOCKED"
                or blocked_record.unknown_reason != "admission_gate_error"
                or blocked_record.dispatch_attempts != 0
            ):
                raise RuntimeError("durable UNKNOWN did not block the restart mechanical opening")
            blocked["durable_unknown_freeze"] = unknown_freeze
            blocked["provider_dispatch_prevented"] = True
            blocked["managed_block_reason"] = blocked_record.unknown_reason
            blocked["blocked_dispatch_attempts"] = blocked_record.dispatch_attempts
            blocked["unknown_dispatch_attempts"] = restarted_unknown_record.dispatch_attempts
            blocked["unknown_still_requires_review"] = restarted_unknown_record.review_required
        finally:
            restarted.close()

    if network_attempts:
        raise RuntimeError("offline mechanical replay attempted network I/O")
    if len(provider.submissions) != 9 or len(provider.cancellations) != 1:
        raise RuntimeError("mechanical fake provider dispatch count is not deterministic")

    return {
        "status": "LOCAL_CTP_MECHANICAL_MANAGED_FAKE_PROVIDER_L2_PASS",
        "admission_status": "NOT_CTP_OR_SIMNOW_ADMITTED",
        "external_network_requests": 0,
        "external_write_requests": 0,
        "actual_fills": 0,
        # These six callbacks exercise the pre-existing MechanicalCycle native
        # identity branch only.  They are not provider fills and never update
        # the durable SDK execution records to FILLED.
        "synthetic_callback_fills": synthetic_callback_fills,
        "sdk_confirmed_fills": sdk_confirmed_fills,
        "provider_submissions": len(provider.submissions),
        "provider_cancellations": len(provider.cancellations),
        "monitor_events": len(monitor_events),
        "metadata_bound_child_intents": 6,
        "fake_instrument_metadata_digests": dict(metadata_digests),
        "stages": {
            "cancel_and_separate_clean_cycle": cancel_and_separate_clean_cycle,
            "provider_rejected": rejected,
            "unknown": unknown,
            "blocked_after_restart": blocked,
        },
        "runtime_config": {
            "strategy_id": effective.strategy_id,
            "mode": effective.mode,
            "preset": effective.preset,
            "scope": "OFFLINE_CTP_MECHANICAL_FAKE_PROVIDER_L2",
            "evidence_boundary": _EVIDENCE_BOUNDARY,
            "allows_network": effective.allows_network,
            "allows_external_writes": effective.allows_external_writes,
            "allows_production_writes": effective.allows_production_writes,
        },
    }


def main(argv: Optional[list[str]] = None) -> int:
    """Run the registered local fixture or emit a redacted config rejection."""

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
