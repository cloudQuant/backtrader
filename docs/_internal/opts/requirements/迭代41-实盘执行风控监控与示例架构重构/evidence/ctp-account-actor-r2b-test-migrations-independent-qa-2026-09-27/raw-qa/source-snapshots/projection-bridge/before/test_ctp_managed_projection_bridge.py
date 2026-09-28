"""Fake-only checks for the managed CTP Store outbox bridge contract."""

from __future__ import annotations

from enum import Enum
import hashlib
import heapq
import json
from types import SimpleNamespace
from dataclasses import replace

import pytest

from backtrader.order import OrderBase
from backtrader.brokers.btapibroker import parse_ctp_managed_execution_projection
from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from backtrader.stores.managed_execution import (
    CtpManagedDispatchBinding,
    CtpManagedExecutionProjection,
    CtpManagedProjectionState,
    ManagedExecutionAdapterError,
    ctp_managed_command_id,
)
from backtrader.stores.ctp_managed_projection_bridge import (
    CtpManagedExecutionProjectionAdapter,
    CtpManagedOutboxReservation,
    _stable_command_id,
)
from backtrader_runtime.ctp_simulation_execution import CtpSimulationExecutionSession


class _Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class _PositionEffect(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CLOSE_TODAY = "CLOSE_TODAY"
    CLOSE_YESTERDAY = "CLOSE_YESTERDAY"


class _OrderIntent:
    @staticmethod
    def limit(**kwargs):
        return SimpleNamespace(**kwargs)


class _Runtime:
    class execution:
        Side = _Side
        PositionEffect = _PositionEffect
        OrderIntent = _OrderIntent

    def __init__(self):
        self.scope = SimpleNamespace(
            provider="CTP",
            strategy_id="fixture",
            environment="sandbox",
            key="scope:" + ("c" * 64),
        )


class _Order:
    def __init__(self, intent_id="intent.bridge"):
        self.ref = 17
        self.exectype = OrderBase.Limit
        self.size = 2
        self.price = 3500
        self.pricelimit = None
        self.valid = None
        self.tradeid = 0
        self.data = SimpleNamespace(_name="rb")
        self.created = SimpleNamespace(price=3500)
        self.info = {
            "managed_intent_id": intent_id,
            "managed_order_type": "LIMIT",
            "managed_signal_id": "signal." + intent_id,
            "managed_instrument": "rb",
            "managed_position_effect": "OPEN",
            "managed_metadata_version": "metadata.v1",
            "managed_instrument_metadata_digest": "a" * 64,
            "offset": "open",
            "reduce_only": False,
        }

    def isbuy(self):
        return True

    def issell(self):
        return False


class _Api:
    exchange_kwargs = {"CTP": {}}

    def __init__(self):
        self.submissions = []
        self.cancellations = []

    def submit_order(self, payload):
        self.submissions.append(payload)
        return {"status": "accepted", "id": "legacy"}

    def cancel_order(self, order_ref, *, dataname=None):
        self.cancellations.append((order_ref, dataname))
        return {"status": "accepted", "id": str(order_ref)}


def _queue_receipt(operation, *, bt_order_ref=17, client_order_id="000000000017"):
    return {
        "kind": "command_receipt",
        "command": operation,
        "receipt_id": ("a" if operation == "submit" else "b") * 32,
        "bt_order_ref": bt_order_ref,
        "client_order_id": client_order_id,
        "status": "submitted",
        "queued": True,
        "priority": "cancel" if operation == "cancel" else "open",
        "queue_depth": 1,
    }


def _dispatch_binding(*, operation="submit", queued=None):
    intent_id = "intent.bridge.worker"
    runtime_order_id = "bt-managed-v1:" + ("d" * 64)
    cancel_id = "cancel." + intent_id if operation == "cancel" else None
    action_id = cancel_id or intent_id
    request_payload = {"OrderRef": "000000000017", "InstrumentID": "rb"}
    if operation == "cancel":
        request_payload.update(
            ExchangeID="SHFE",
            OrderSysID="sys.worker.1",
            FrontID=3,
            SessionID=7,
        )
    native_action_ref = 21 if operation == "cancel" else None
    native_request_payload = dict(request_payload)
    if native_action_ref is not None:
        native_request_payload["OrderActionRef"] = native_action_ref
    session_binding = {
        "session_generation_id": "generation.worker.1",
        "dispatch_front_id": 3,
        "dispatch_session_id": 7,
    }
    canonical = lambda value: json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")
    return CtpManagedDispatchBinding(
        operation=operation,
        command_id=ctp_managed_command_id(operation, intent_id, runtime_order_id, cancel_id),
        account_key="account.worker",
        scope_key="scope:" + ("e" * 64),
        trading_day="20260926",
        managed_intent_id=intent_id,
        runtime_order_id=runtime_order_id,
        managed_action_id=action_id,
        order_ref="000000000017",
        cancel_target_order_ref="000000000017" if operation == "cancel" else None,
        request_payload_sha256=hashlib.sha256(canonical(request_payload)).hexdigest(),
        request_payload=request_payload,
        native_request_payload_sha256=hashlib.sha256(canonical(native_request_payload)).hexdigest(),
        native_request_payload=native_request_payload,
        approval_use_id="approval.worker.1",
        approval_digest="f" * 64,
        session_binding_sha256=hashlib.sha256(canonical(session_binding)).hexdigest(),
        session_binding=session_binding,
        session_generation_id="generation.worker.1",
        dispatch_front_id=3,
        dispatch_session_id=7,
        native_request_id=19,
        native_action_ref=native_action_ref,
        local_queue_receipt_id="c" * 32,
        order_ref_reservation_created_at_ns=1_790_000_000_000_000_000,
        local_queue_receipt_queued=queued,
        managed_cancel_intent_id=cancel_id,
        cancel_target_exchange_id="SHFE" if operation == "cancel" else None,
        cancel_target_order_sys_id="sys.worker.1" if operation == "cancel" else None,
        cancel_target_front_id=3 if operation == "cancel" else None,
        cancel_target_session_id=7 if operation == "cancel" else None,
    )


class _FakeOutboxAuthority:
    """In-memory fixture; it does not claim crash or process durability."""

    def __init__(self):
        self.rows = {}
        self.freezes = []
        self.events = []

    def reserve_managed_dispatch(self, *, command_id, operation, identity):
        row = self.rows.get(command_id)
        if row is not None:
            self.events.append("reserve_replay")
            return CtpManagedOutboxReservation(
                command_id=command_id,
                dispatch_claimed=False,
                projection=row.get("projection"),
            )
        self.rows[command_id] = {
            "operation": operation,
            "identity": identity,
            "projection": None,
            "receipt": None,
        }
        self.events.append("reserve")
        return CtpManagedOutboxReservation(command_id, True)

    def record_managed_queue_receipt(self, *, command_id, operation, identity, queue_receipt):
        row = self.rows[command_id]
        self.events.append("record_receipt")
        assert row["operation"] == operation
        assert row["identity"].managed_intent_id == identity.managed_intent_id
        row["receipt"] = dict(queue_receipt)
        state = (
            CtpManagedProjectionState.PENDING
            if queue_receipt["queued"]
            else CtpManagedProjectionState.LOCAL_REJECTED
        )
        row["projection"] = self._projection(command_id, operation, identity, queue_receipt, state)

    def mark_managed_unknown(self, *, command_id, operation, identity, queue_receipt, reason):
        self.freezes.append((command_id, operation, reason))
        row = self.rows.setdefault(
            command_id,
            {"operation": operation, "identity": identity, "projection": None},
        )
        row["projection"] = self._projection(
            command_id,
            operation,
            identity,
            queue_receipt,
            CtpManagedProjectionState.UNKNOWN,
        )

    def read_managed_projection(self, *, command_id):
        row = self.rows.get(command_id)
        return None if row is None else row.get("projection")

    @staticmethod
    def _projection(command_id, operation, identity, receipt, state):
        queue_receipt_id = None if receipt is None else receipt.get("receipt_id")
        return CtpManagedExecutionProjection(
            operation=operation,
            state=state,
            durable_projection_id=command_id,
            managed_intent_id=identity.managed_intent_id,
            runtime_order_id=identity.runtime_order_id,
            managed_cancel_intent_id=getattr(identity, "managed_cancel_intent_id", None),
            local_queue_receipt_id=queue_receipt_id,
            error_code=(
                "command_queue_rejected"
                if state is CtpManagedProjectionState.LOCAL_REJECTED
                else None
            ),
        )


def _store(adapter):
    api = _Api()
    store = BtApiStore(
        provider="btapi",
        api=api,
        config={
            "exchange_kwargs": {"CTP": {}},
            "execution_config": {"market_data_only": False, "strategy_id": "fixture"},
        },
        managed_execution_adapter=adapter,
    )
    store._sdk_mode = True
    store._sdk_exchanges = {"CTP": {}}
    store._sdk_account_id = lambda venue, supplied=None: "account"
    store._validate_managed_ctp_identity_scope = lambda venue, account_id: None
    store._enqueue_order_command = lambda order, *, ctp_managed_identity: (
        order.info.__setitem__("client_order_id", "000000000017") or _queue_receipt("submit")
    )
    store._enqueue_ctp_managed_cancel = lambda identity, dataname: _queue_receipt(
        "cancel", bt_order_ref=17
    )
    return store, api


def test_store_uses_outbox_projection_for_submit_and_cancel_without_legacy_fallback():
    authority = _FakeOutboxAuthority()
    adapter = CtpManagedExecutionProjectionAdapter(_Runtime(), authority=authority, hedge_flag="2")
    store, api = _store(adapter)
    order = _Order()

    def enqueue_submit(dispatched_order, *, ctp_managed_identity):
        authority.events.append("sdk_queue_submit")
        dispatched_order.info["client_order_id"] = "000000000017"
        return _queue_receipt("submit")

    def enqueue_cancel(identity, dataname):
        authority.events.append("sdk_queue_cancel")
        return _queue_receipt("cancel", bt_order_ref=17)

    store._enqueue_order_command = enqueue_submit
    store._enqueue_ctp_managed_cancel = enqueue_cancel

    submitted = store.submit_order(order)
    repeated = store.submit_order(_Order())
    cancelled = store.cancel_order(order)

    assert submitted["kind"] == "managed_execution_projection"
    assert submitted["state"] == "PENDING"
    assert submitted["projection_id"].startswith("ctp-outbox-v1:")
    assert submitted["local_queue_receipt_id"] == "a" * 32
    assert (
        parse_ctp_managed_execution_projection(submitted, expected_operation="submit").state
        is CtpManagedProjectionState.PENDING
    )
    assert repeated == submitted
    assert cancelled["kind"] == "managed_execution_projection"
    assert cancelled["operation"] == "cancel"
    assert cancelled["state"] == "PENDING"
    assert cancelled["managed_cancel_intent_id"] == "cancel.intent.bridge"
    assert cancelled["local_queue_receipt_id"] == "b" * 32
    assert authority.events == [
        "reserve",
        "sdk_queue_submit",
        "record_receipt",
        "reserve_replay",
        "reserve",
        "sdk_queue_cancel",
        "record_receipt",
    ]
    assert api.submissions == []
    assert api.cancellations == []


def test_ambiguous_sdk_handoff_reads_back_unknown_and_does_not_retry():
    authority = _FakeOutboxAuthority()
    adapter = CtpManagedExecutionProjectionAdapter(_Runtime(), authority=authority, hedge_flag="2")
    store, api = _store(adapter)
    dispatches = []

    def uncertain_dispatch(order, *, ctp_managed_identity):
        dispatches.append(ctp_managed_identity)
        order.info["client_order_id"] = "000000000017"
        raise OSError("queue handoff response was lost")

    store._enqueue_order_command = uncertain_dispatch
    first = store.submit_order(_Order("intent.uncertain"))
    second = store.submit_order(_Order("intent.uncertain"))

    assert first["kind"] == "managed_execution_projection"
    assert first["state"] == "UNKNOWN"
    assert first["execution_unknown"] is True
    assert (
        parse_ctp_managed_execution_projection(first, expected_operation="submit").state
        is CtpManagedProjectionState.UNKNOWN
    )
    assert second == first
    assert len(dispatches) == 1
    assert len(authority.freezes) == 1
    assert api.submissions == []
    assert api.cancellations == []


def test_current_simulation_session_does_not_satisfy_store_outbox_port():
    """The native session's string return/private journal cannot be bridged."""

    session = object.__new__(CtpSimulationExecutionSession)
    runtime = _Runtime()

    with pytest.raises(ManagedExecutionAdapterError, match="durable Store outbox"):
        CtpManagedExecutionProjectionAdapter(
            runtime,
            authority=session,
            hedge_flag="2",
        )

    # Its synchronous methods target the native port and return status strings;
    # the Store bridge requires a separate atomic reserve/receipt/read API.
    assert not callable(getattr(session, "reserve_managed_dispatch", None))
    assert not callable(getattr(session, "record_managed_queue_receipt", None))
    assert not callable(getattr(session, "read_managed_projection", None))


def test_command_key_is_stable_for_restarts_and_changes_for_cancels():
    runtime = _Runtime()
    adapter = CtpManagedExecutionProjectionAdapter(
        runtime, authority=_FakeOutboxAuthority(), hedge_flag="2"
    )
    order = _Order("intent.key")
    submit_identity = adapter._identity(order)
    cancel_identity = adapter._identity(order, cancel=True)

    assert _stable_command_id("submit", submit_identity) == _stable_command_id(
        "submit", adapter._identity(_Order("intent.key"))
    )
    assert _stable_command_id("submit", submit_identity) != _stable_command_id(
        "cancel", cancel_identity
    )


def test_queue_receipt_commit_is_before_publication_and_worker_uses_typed_outbox_only():
    store, api = _store(None)
    binding = _dispatch_binding()
    persisted = []
    dispatches = []
    native_calls = []

    async def forbidden_generic_sender(*args, **kwargs):
        native_calls.append((args, kwargs))
        raise AssertionError("managed CTP fell through to generic SDK sender")

    store._invoke_sdk_command = forbidden_generic_sender

    def persist(receipt):
        # The condition is held, and the command must still be invisible.
        assert len(store._command_heap) == 0
        persisted.append(dict(receipt))
        return replace(binding, local_queue_receipt_queued=receipt["queued"])

    def read_from_reserved_outbox(exact_binding):
        dispatches.append(exact_binding.command_id)
        return CtpManagedExecutionProjection(
            operation="submit",
            state=CtpManagedProjectionState.PENDING,
            durable_projection_id=exact_binding.command_id,
            managed_intent_id=exact_binding.managed_intent_id,
            runtime_order_id=exact_binding.runtime_order_id,
            local_queue_receipt_id=exact_binding.local_queue_receipt_id,
            dispatch_binding=exact_binding,
            version=2,
        )

    receipt = store._enqueue_sdk_command(
        {"operation": "submit", "venue": "CTP", "symbol": "rb"},
        priority_name="open",
        managed_ctp_binding=binding,
        managed_ctp_receipt_writer=persist,
        managed_ctp_dispatcher=read_from_reserved_outbox,
    )

    assert receipt["queued"] is True
    assert receipt["receipt_id"] == binding.local_queue_receipt_id
    assert persisted[0]["queued"] is True
    assert len(store._command_heap) == 1
    command = heapq.heappop(store._command_heap)[2]

    import asyncio

    completion = asyncio.run(store._execute_sdk_command(command))
    assert completion["success"] is True
    assert completion["response"]["state"] == "PENDING"
    assert (
        parse_ctp_managed_execution_projection(
            completion["response"], expected_operation="submit"
        ).dispatch_binding
        == command["managed_ctp_binding"]
    )
    assert dispatches == [binding.command_id]
    assert native_calls == []
    assert api.submissions == []
    assert api.cancellations == []


def test_receipt_writer_failure_leaves_managed_command_invisible_and_unsent():
    store, api = _store(None)
    binding = _dispatch_binding()
    dispatches = []
    native_calls = []

    async def generic_sender(*args, **kwargs):
        native_calls.append((args, kwargs))

    store._invoke_sdk_command = generic_sender

    def fail_receipt_write(_receipt):
        assert len(store._command_heap) == 0
        raise OSError("outbox receipt transaction failed")

    with pytest.raises(BtApiStoreError, match="receipt could not be committed before publication"):
        store._enqueue_sdk_command(
            {"operation": "submit", "venue": "CTP", "symbol": "rb"},
            priority_name="open",
            managed_ctp_binding=binding,
            managed_ctp_receipt_writer=fail_receipt_write,
            managed_ctp_dispatcher=lambda value: dispatches.append(value),
        )

    assert len(store._command_heap) == 0
    assert dispatches == []
    assert native_calls == []
    assert api.submissions == []
    assert api.cancellations == []


def test_managed_worker_without_single_dispatch_port_never_calls_generic_sender():
    store, api = _store(None)
    binding = replace(_dispatch_binding(), local_queue_receipt_queued=True)
    native_calls = []

    async def generic_sender(*args, **kwargs):
        native_calls.append((args, kwargs))

    store._invoke_sdk_command = generic_sender
    command = {
        "operation": "submit",
        "venue": "CTP",
        "receipt_id": binding.local_queue_receipt_id,
        "priority": "open",
        "managed_ctp_binding": binding,
    }
    import asyncio

    completion = asyncio.run(store._execute_sdk_command(command))
    assert completion["execution_unknown"] is True
    assert completion["status"] == "unknown"
    assert native_calls == []
    assert api.submissions == []
    assert api.cancellations == []


def test_local_queue_rejection_is_durable_and_never_calls_outbox_dispatcher():
    store, api = _store(None)
    binding = _dispatch_binding()
    written = []
    dispatches = []
    with store._command_condition:
        store._command_stop_requested = True

    def persist(receipt):
        written.append(dict(receipt))
        return replace(binding, local_queue_receipt_queued=receipt["queued"])

    receipt = store._enqueue_sdk_command(
        {"operation": "submit", "venue": "CTP", "symbol": "rb"},
        priority_name="open",
        managed_ctp_binding=binding,
        managed_ctp_receipt_writer=persist,
        managed_ctp_dispatcher=lambda value: dispatches.append(value),
    )

    assert receipt["queued"] is False
    assert receipt["status"] == "rejected"
    assert written[0]["queued"] is False
    assert store._command_heap == []
    assert dispatches == []
    assert api.submissions == []
    assert api.cancellations == []


@pytest.mark.parametrize(
    "changes",
    (
        {"cancel_target_order_ref": "000000000018"},
        {"cancel_target_front_id": 4},
        {"cancel_target_session_id": 8},
        {"native_request_id": 0},
        {"native_action_ref": ""},
        {"local_queue_receipt_id": "not-a-receipt"},
    ),
)
def test_typed_cancel_handoff_rejects_incomplete_target_and_native_identity(changes):
    binding = _dispatch_binding(operation="cancel")
    with pytest.raises(ManagedExecutionAdapterError):
        replace(binding, **changes)


def test_typed_cancel_binding_keeps_managed_request_and_store_native_ids_separate():
    binding = _dispatch_binding(operation="cancel")
    restored = CtpManagedDispatchBinding.from_store_payload(binding.to_store_payload())

    assert restored == binding
    assert restored.version == 2
    assert restored.native_request_id == 19
    assert restored.native_action_ref == 21
    assert "OrderActionRef" not in restored.request_payload
    assert restored.native_request_payload["OrderActionRef"] == 21


@pytest.mark.parametrize(
    "changes",
    (
        {"native_action_ref": 19},
        {"native_request_payload_sha256": "0" * 64},
        {"native_request_payload": {"OrderRef": "000000000017"}},
        {"request_payload": {"OrderRef": "000000000017", "OrderActionRef": 21}},
        {"version": 1},
    ),
)
def test_typed_cancel_binding_rejects_caller_payload_or_action_ref_mutation(changes):
    binding = _dispatch_binding(operation="cancel")
    with pytest.raises(ManagedExecutionAdapterError):
        replace(binding, **changes)


@pytest.mark.parametrize("recovery_armed", [False, True])
def test_managed_ctp_raw_enqueue_cancel_is_rejected_before_queue_or_sdk(
    monkeypatch, recovery_armed
):
    adapter = CtpManagedExecutionProjectionAdapter(
        _Runtime(), authority=_FakeOutboxAuthority(), hedge_flag="2"
    )
    store, api = _store(adapter)
    store._ctp_execution_recovery_armed = recovery_armed
    side_effects = {"worker": 0, "enqueue": 0, "request": 0}

    def count(name):
        def called(*args, **kwargs):
            side_effects[name] += 1
            raise AssertionError(f"managed CTP raw cancel reached {name}")

        return called

    monkeypatch.setattr(store, "_start_command_worker", count("worker"))
    monkeypatch.setattr(store, "_enqueue_sdk_command", count("enqueue"))
    monkeypatch.setattr(store, "_sdk_cancel_request", count("request"))

    with pytest.raises(BtApiStoreError, match="cannot use the generic SDK queue"):
        store.enqueue_cancel("000000000017", dataname="rb")

    assert side_effects == {"worker": 0, "enqueue": 0, "request": 0}
    assert store._command_heap == []
    assert store._command_inflight == 0
    assert api.cancellations == []


@pytest.mark.parametrize("operation", ["submit", "cancel"])
@pytest.mark.parametrize(
    "port_case",
    ["missing_all", "binding_only", "missing_writer", "missing_dispatcher", "wrong_operation"],
)
def test_managed_ctp_private_enqueue_requires_complete_matching_v2_binding(
    monkeypatch, operation, port_case
):
    adapter = CtpManagedExecutionProjectionAdapter(
        _Runtime(), authority=_FakeOutboxAuthority(), hedge_flag="2"
    )
    store, api = _store(adapter)
    side_effects = {"worker": 0, "sender": 0}

    def count(name):
        def called(*args, **kwargs):
            side_effects[name] += 1
            raise AssertionError(f"managed CTP command reached {name}")

        return called

    monkeypatch.setattr(store, "_start_command_worker", count("worker"))
    monkeypatch.setattr(store, "_invoke_sdk_command", count("sender"))
    monkeypatch.setattr(store, "_execute_sdk_command", count("sender"))

    binding = None
    writer = None
    dispatcher = None
    if port_case != "missing_all":
        binding_operation = (
            "cancel"
            if port_case == "wrong_operation" and operation == "submit"
            else "submit"
            if port_case == "wrong_operation"
            else operation
        )
        binding = _dispatch_binding(operation=binding_operation)
    if port_case in {"missing_writer", "wrong_operation"}:
        writer = lambda receipt: replace(binding, local_queue_receipt_queued=receipt["queued"])
    if port_case in {"missing_dispatcher", "wrong_operation"}:
        dispatcher = lambda _binding: None

    command = {"operation": operation, "venue": "CTP", "symbol": "rb"}
    health_before = dict(store._command_health)
    with pytest.raises(
        BtApiStoreError,
        match="complete v2 outbox binding and dispatch ports",
    ) as raised:
        store._enqueue_sdk_command(
            command,
            priority_name="open" if operation == "submit" else "cancel",
            managed_ctp_binding=binding,
            managed_ctp_receipt_writer=writer,
            managed_ctp_dispatcher=dispatcher,
        )

    assert raised.value.managed_local_reject is True
    assert raised.value.definite_reject is True
    assert raised.value.code == "managed_ctp_v2_outbox_binding_required"
    assert command == {"operation": operation, "venue": "CTP", "symbol": "rb"}
    assert side_effects == {"worker": 0, "sender": 0}
    assert store._command_heap == []
    assert store._command_inflight == 0
    assert store._command_health == health_before
    assert api.submissions == []
    assert api.cancellations == []
