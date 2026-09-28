"""Offline checks for the I9 provider-order projection boundary.

These tests use only local DTOs and structural fakes. They establish that
caller-provided target fields and local outbox projections do not supply native
order identity provenance; they do not exercise an SDK or provider.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import backtrader.stores.ctp_i9_managed_dispatch as i9_bridge_module
from backtrader.stores.ctp_i9_managed_dispatch import (
    CtpI9ManagedDispatchBridge,
    _validate_prepared,
)
from backtrader.stores.managed_execution import (
    CtpManagedExecutionProjection,
    CtpManagedProjectionState,
    ManagedExecutionAdapterError,
    ctp_managed_command_id,
)


@dataclass(frozen=True)
class _Scope:
    provider: str = "CTP"
    trading_day: str = "20260926"
    account_key: str = "account:" + "a" * 64
    key: str = "scope:" + "b" * 64


@dataclass(frozen=True)
class _Reservation:
    account_key: str
    trading_day: str
    scope_key: str
    managed_intent_id: str
    runtime_order_id: str
    order_ref: str
    created_at_ns: int


class _Store:
    def __init__(self, reservation):
        self.reservation = reservation
        self.identity_reads = []
        self.command_reads = []
        self.projection_reads = []

    def reserve_ctp_order_identity(self, *args):
        raise AssertionError("cancel validation must not allocate an OrderRef")

    def read_ctp_order_identity(self, scope, managed_intent_id):
        self.identity_reads.append((scope, managed_intent_id))
        return self.reservation

    def read_ctp_dispatch_command(self, *args):
        self.command_reads.append(args)
        raise AssertionError("cancel validation must reject before staging")

    def read_ctp_dispatch_projection(self, *args):
        self.projection_reads.append(args)
        raise AssertionError("cancel validation must reject before dispatch")


class _Worker:
    def __init__(self, store, scope):
        self._store = store
        self._scope = scope
        self.stage_calls = []
        self.receipt_calls = []
        self.dispatch_calls = []

    def stage_prepared_dispatch(self, prepared):
        self.stage_calls.append(prepared)
        raise AssertionError("cancel validation must reject before staging")

    def record_managed_queue_receipt(self, *args):
        self.receipt_calls.append(args)
        raise AssertionError("cancel validation must reject before queue receipt")

    async def dispatch_managed_command(self, *args):
        self.dispatch_calls.append(args)
        raise AssertionError("cancel validation must reject before dispatch")


class _Prepared:
    pass


class _Binding:
    pass


class _Projection:
    pass


class _Command:
    pass


def _valid_cancel(scope):
    managed_intent_id = "intent.i9.offline"
    runtime_order_id = "bt-managed-v1:" + "d" * 64
    order_ref = "000000000017"
    cancel_id = "cancel.intent.i9.offline"
    session_generation_id = "generation.i9.offline"
    front_id = 4
    session_id = 91
    reservation = _Reservation(
        account_key=scope.account_key,
        trading_day=scope.trading_day,
        scope_key=scope.key,
        managed_intent_id=managed_intent_id,
        runtime_order_id=runtime_order_id,
        order_ref=order_ref,
        created_at_ns=123,
    )
    request_payload = {
        "OrderRef": order_ref,
        "ExchangeID": "SHFE",
        "OrderSysID": "provider-order-17",
        "FrontID": front_id,
        "SessionID": session_id,
        "ActionFlag": "0",
        "LimitPrice": 0,
        "VolumeChange": 0,
    }
    prepared = _Prepared()
    prepared.operation = "cancel"
    prepared.command_id = ctp_managed_command_id(
        "cancel", managed_intent_id, runtime_order_id, cancel_id
    )
    prepared.managed_intent_id = managed_intent_id
    prepared.runtime_order_id = runtime_order_id
    prepared.order_ref = order_ref
    prepared.order_ref_reservation = reservation
    prepared.managed_cancel_intent_id = cancel_id
    prepared.cancel_target_exchange_id = "SHFE"
    prepared.cancel_target_order_sys_id = "provider-order-17"
    prepared.cancel_target_front_id = front_id
    prepared.cancel_target_session_id = session_id
    prepared.request_payload = request_payload
    prepared.session_generation_id = session_generation_id
    prepared.dispatch_front_id = front_id
    prepared.dispatch_session_id = session_id
    prepared.native_request_id = 102
    prepared.local_queue_receipt_id = "b" * 32
    prepared.session_binding = {
        "session_generation_id": session_generation_id,
        "dispatch_front_id": front_id,
        "dispatch_session_id": session_id,
    }
    return reservation, prepared


def test_complete_caller_cancel_target_still_rejects_before_i9_staging(monkeypatch):
    scope = _Scope()
    reservation, prepared = _valid_cancel(scope)
    store = _Store(reservation)
    worker = _Worker(store, scope)
    trusted_types = (
        _Scope,
        _Store,
        _Reservation,
        _Worker,
        _Prepared,
        _Binding,
        _Projection,
        _Command,
    )
    monkeypatch.setattr(i9_bridge_module, "_trusted_i9_types", lambda: trusted_types)
    bridge = CtpI9ManagedDispatchBridge(
        scope=scope,
        identity_port=store,
        single_worker=worker,
    )

    with pytest.raises(
        ManagedExecutionAdapterError,
        match="trusted typed order-projection provenance",
    ):
        bridge.stage_prepared_dispatch(prepared)

    assert store.identity_reads == [(scope, prepared.managed_intent_id)]
    assert store.command_reads == []
    assert store.projection_reads == []
    assert worker.stage_calls == []
    assert worker.receipt_calls == []
    assert worker.dispatch_calls == []


def test_local_execution_projection_contains_no_provider_order_identity():
    projection = CtpManagedExecutionProjection(
        operation="submit",
        state=CtpManagedProjectionState.PENDING,
        durable_projection_id="i9-command-offline",
        managed_intent_id="intent.i9.offline",
        runtime_order_id="bt-managed-v1:" + "d" * 64,
    )

    assert projection.state is CtpManagedProjectionState.PENDING
    assert not hasattr(projection, "order_sys_id")
    assert not hasattr(projection, "front_id")
    assert not hasattr(projection, "session_id")
    assert not hasattr(projection, "provider_ack")


@pytest.mark.parametrize("target_form", ("order_sys_id", "order_ref_session"))
def test_sdk_supported_single_target_form_stays_closed_at_current_i9_boundary(target_form):
    """The SDK OR forms remain unusable until a trusted target issuer exists."""

    scope = _Scope()
    reservation, prepared = _valid_cancel(scope)
    if target_form == "order_sys_id":
        # Generic TraderClient accepts OrderSysID + ExchangeID without the
        # FrontID/SessionID pair. I9's current DTO still rejects that shape.
        prepared.cancel_target_front_id = None
        prepared.cancel_target_session_id = None
        prepared.request_payload["FrontID"] = None
        prepared.request_payload["SessionID"] = None
    else:
        # The live Feed can target by OrderRef + FrontID + SessionID without
        # OrderSysID. The I9 DTO still requires OrderSysID too.
        prepared.cancel_target_order_sys_id = None
        prepared.request_payload["OrderSysID"] = None

    with pytest.raises(ManagedExecutionAdapterError, match="exact binding"):
        _validate_prepared(prepared, reservation, scope)


def test_cancel_target_must_not_mix_incomplete_native_identity_forms():
    scope = _Scope()
    reservation, prepared = _valid_cancel(scope)
    prepared.cancel_target_order_sys_id = None
    prepared.cancel_target_session_id = None
    prepared.request_payload["OrderSysID"] = None
    prepared.request_payload["SessionID"] = None

    # No OrderSysID+ExchangeID form, and no complete OrderRef+FrontID+SessionID
    # form: accepting fragments from each would identify no exact native order.
    with pytest.raises(ManagedExecutionAdapterError, match="exact binding"):
        _validate_prepared(prepared, reservation, scope)
