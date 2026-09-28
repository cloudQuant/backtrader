"""Fail-closed boundary tests for the optional, offline I9 bridge.

These intentionally use structural fakes. They prove that matching fake DTOs
and even the same fake store object do not authorize reservation, staging,
queue receipt persistence, dispatch, or projection reads. They are not evidence
of an SDK integration or provider behavior.
"""

from __future__ import annotations

import asyncio
import hashlib
import heapq
from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
import backtrader.stores.ctp_i9_managed_dispatch as i9_bridge_module
from backtrader.stores.managed_execution import ManagedExecutionAdapterError
from backtrader.stores.ctp_i9_managed_dispatch import (
    CtpI9ManagedDispatchBridge,
    CtpI9ManagedDispatchHandle,
)


@dataclass(frozen=True)
class _FakeScope:
    provider: str = "CTP"
    trading_day: str = "20260926"
    account_key: str = "account:" + "a" * 64
    key: str = "scope:" + "b" * 64


class _FakeIdentityStore:
    def __init__(self):
        self.reserve_calls = []
        self.identity_reads = []
        self.command_reads = []
        self.projection_reads = []

    def reserve_ctp_order_identity(self, *args):
        self.reserve_calls.append(args)
        raise AssertionError("untrusted fake reservation port must not be called")

    def read_ctp_order_identity(self, *args):
        self.identity_reads.append(args)
        raise AssertionError("untrusted fake reservation port must not be called")

    def read_ctp_dispatch_command(self, *args):
        self.command_reads.append(args)
        raise AssertionError("untrusted fake command port must not be called")

    def read_ctp_dispatch_projection(self, *args):
        self.projection_reads.append(args)
        raise AssertionError("untrusted fake projection port must not be called")


class _FakeWorker:
    def __init__(self, store, scope):
        # Matching these object references still must not authorize the bridge.
        self._store = store
        self._scope = scope
        self.stage_calls = []
        self.receipt_calls = []
        self.dispatch_calls = []

    def stage_prepared_dispatch(self, prepared):
        self.stage_calls.append(prepared)
        raise AssertionError("untrusted fake worker must not be called")

    def record_managed_queue_receipt(self, *args):
        self.receipt_calls.append(args)
        raise AssertionError("untrusted fake worker must not be called")

    async def dispatch_managed_command(self, *args):
        self.dispatch_calls.append(args)
        raise AssertionError("untrusted fake worker must not be called")


class _FakeReservation:
    pass


class _FakePrepared:
    pass


class _FakeBinding:
    pass


class _FakeProjection:
    pass


class _FakeCommand:
    pass


def test_structural_same_object_fakes_cannot_enable_any_bridge_side_effect():
    scope = _FakeScope()
    identity_store = _FakeIdentityStore()
    worker = _FakeWorker(identity_store, scope)
    bridge = CtpI9ManagedDispatchBridge(
        scope=scope,
        identity_port=identity_store,
        single_worker=worker,
    )
    sender_calls = []

    def sender(command):
        sender_calls.append(command)
        return SimpleNamespace(outcome="QUEUED")

    calls = (
        lambda: bridge.reserve_submit_order_identity("intent.fake", "bt-managed-v1:" + "d" * 64),
        lambda: bridge.read_cancel_order_identity(
            "intent.fake", "bt-managed-v1:" + "d" * 64, "000000000017"
        ),
        lambda: bridge.stage_prepared_dispatch(SimpleNamespace(operation="submit")),
        lambda: bridge.read_projection(SimpleNamespace(command_id="fake-command")),
        lambda: bridge.queue_ports(None, sender=sender),
    )

    for call in calls:
        with pytest.raises(ManagedExecutionAdapterError, match="trusted I9 same-store"):
            call()

    assert identity_store.reserve_calls == []
    assert identity_store.identity_reads == []
    assert identity_store.command_reads == []
    assert identity_store.projection_reads == []
    assert worker.stage_calls == []
    assert worker.receipt_calls == []
    assert worker.dispatch_calls == []
    assert sender_calls == []


def test_fake_cancel_projection_or_reservation_cannot_authorize_cancel():
    scope = _FakeScope()
    identity_store = _FakeIdentityStore()
    worker = _FakeWorker(identity_store, scope)
    bridge = CtpI9ManagedDispatchBridge(
        scope=scope,
        identity_port=identity_store,
        single_worker=worker,
    )

    # A shape-compatible target and projection are still untrusted. The bridge
    # rejects before reading them, so neither can become cancel provenance.
    fake_target = SimpleNamespace(
        managed_intent_id="intent.fake",
        runtime_order_id="bt-managed-v1:" + "d" * 64,
        order_ref="000000000017",
        exchange_id="SHFE",
        order_sys_id="sys.fake",
        front_id=3,
        session_id=7,
        provider_state="ACCEPTED",
    )
    with pytest.raises(ManagedExecutionAdapterError, match="trusted I9 same-store"):
        bridge.read_cancel_order_identity(
            fake_target.managed_intent_id,
            fake_target.runtime_order_id,
            fake_target.order_ref,
        )
    with pytest.raises(ManagedExecutionAdapterError, match="trusted I9 same-store"):
        bridge.read_projection(
            SimpleNamespace(
                command_id="fake-command",
                provider_state="ACCEPTED",
                fill_quantity=1,
            )
        )
    assert identity_store.identity_reads == []
    assert identity_store.projection_reads == []
    assert worker.dispatch_calls == []


def test_explicit_eight_type_tuple_smoke_checks_same_store_guard_only(monkeypatch):
    """Test the guard's tuple shape, not real SDK integration or authorization."""

    scope = _FakeScope()
    identity_store = _FakeIdentityStore()
    worker = _FakeWorker(identity_store, scope)
    bridge = CtpI9ManagedDispatchBridge(
        scope=scope,
        identity_port=identity_store,
        single_worker=worker,
    )
    reviewed_type_tuple = (
        _FakeScope,
        _FakeIdentityStore,
        _FakeReservation,
        _FakeWorker,
        _FakePrepared,
        _FakeBinding,
        _FakeProjection,
        _FakeCommand,
    )
    monkeypatch.setattr(i9_bridge_module, "_trusted_i9_types", lambda: reviewed_type_tuple)

    assert len(bridge._require_same_store_authority()) == 8
    assert bridge._require_same_store_authority() == reviewed_type_tuple
    assert identity_store.reserve_calls == []
    assert identity_store.identity_reads == []
    assert worker.stage_calls == []
    assert worker.receipt_calls == []
    assert worker.dispatch_calls == []


def _store_queue_receipt(**changes):
    receipt = {
        "kind": "command_receipt",
        "command": "submit",
        "receipt_id": "a" * 32,
        "bt_order_ref": 17,
        "client_order_id": "000000000017",
        "status": "submitted",
        "queued": True,
        "priority": "open",
        "queue_depth": 1,
    }
    receipt.update(changes)
    return receipt


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"client_order_id": "000000000018"}, "client OrderRef"),
        ({"status": "rejected"}, "status conflicts"),
        ({"priority": "cancel"}, "priority is invalid"),
        ({"queue_depth": True}, "depth is invalid"),
    ),
)
def test_store_receipt_must_match_i9_orderref_and_typed_queue_outcome(changes, message):
    with pytest.raises(ManagedExecutionAdapterError, match=message):
        i9_bridge_module._validate_store_queue_receipt(
            _store_queue_receipt(**changes),
            operation="submit",
            order_ref="000000000017",
            receipt_id="a" * 32,
        )


def test_valid_store_queue_rejection_is_typed_and_terminal_before_publication():
    assert (
        i9_bridge_module._validate_store_queue_receipt(
            _store_queue_receipt(
                status="rejected",
                queued=False,
                priority="close",
                queue_depth=0,
                error_code="command_queue_full",
                error_msg="SDK command queue cannot safely accept this command",
            ),
            operation="submit",
            order_ref="000000000017",
            receipt_id="a" * 32,
        )
        is False
    )


def test_valid_store_queue_acceptance_uses_the_reserved_orderref():
    assert (
        i9_bridge_module._validate_store_queue_receipt(
            _store_queue_receipt(),
            operation="submit",
            order_ref="000000000017",
            receipt_id="a" * 32,
        )
        is True
    )


def test_orderref_mismatch_is_rejected_before_i9_receipt_commit(monkeypatch):
    scope = _FakeScope()
    identity_store = _FakeIdentityStore()
    worker = _FakeWorker(identity_store, scope)
    bridge = CtpI9ManagedDispatchBridge(
        scope=scope,
        identity_port=identity_store,
        single_worker=worker,
    )
    monkeypatch.setattr(
        i9_bridge_module,
        "_trusted_i9_types",
        lambda: (
            _FakeScope,
            _FakeIdentityStore,
            _FakeReservation,
            _FakeWorker,
            _FakePrepared,
            _FakeBinding,
            _FakeProjection,
            _FakeCommand,
        ),
    )
    binding = SimpleNamespace(
        operation="submit",
        order_ref="000000000017",
        local_queue_receipt_id="a" * 32,
        local_queue_receipt_queued=None,
    )
    prepared = SimpleNamespace(operation="submit")
    handle = CtpI9ManagedDispatchHandle(binding, object(), prepared)
    bridge._issued_handles.append(handle)

    record_receipt, _dispatch = bridge.queue_ports(handle, sender=lambda _command: None)
    with pytest.raises(ManagedExecutionAdapterError, match="client OrderRef"):
        record_receipt(_store_queue_receipt(client_order_id="000000000018"))

    assert worker.receipt_calls == []
    assert worker.dispatch_calls == []


def test_isolated_i9_store_queue_handoff_and_forged_cancel_gate(tmp_path, monkeypatch):
    """Smoke the real I9 source classes locally; no native/provider call is made.

    Set ``BT_API_EXECUTION_I9_SOURCE`` to the isolated package ``src`` (or its
    checkout root). The test reads the source package metadata, then imports
    those exact classes and uses a temporary SQLite store plus fake seed facts.
    It proves one local I9 reservation/command/claim and the Store v2 queue
    handoff with a fake sender. It does not prove trusted authorization or
    provider integration.
    """

    source_setting = os.environ.get("BT_API_EXECUTION_I9_SOURCE")
    if not source_setting:
        pytest.skip("set BT_API_EXECUTION_I9_SOURCE to run the isolated I9 source smoke")
    source_root = Path(source_setting)
    source_dir = source_root if source_root.name == "src" else source_root / "src"
    pyproject = source_dir.parent / "pyproject.toml"
    if not (source_dir / "bt_api_execution").is_dir() or not pyproject.is_file():
        pytest.skip("isolated I9 source checkout is unavailable")
    metadata = pyproject.read_text(encoding="utf-8")
    assert 'name = "bt_api_execution"' in metadata
    assert 'version = "0.2.0"' in metadata
    assert 'requires-python = ">=3.11"' in metadata

    # Prevent a previously imported SDK from shadowing the explicitly selected
    # isolated source tree. Restore those module objects after this smoke.
    original_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "bt_api_execution" or name.startswith("bt_api_execution.")
    }
    for name in original_modules:
        sys.modules.pop(name, None)
    monkeypatch.syspath_prepend(str(source_dir))
    monkeypatch.setattr(i9_bridge_module, "version", lambda _name: "0.2.0")
    try:
        execution = importlib.import_module("bt_api_execution")
        store_module = importlib.import_module("bt_api_execution.store")
        worker_module = importlib.import_module("bt_api_execution.ctp_single_worker_candidate")

        class OfflineAuthorityVerifier:
            """Test-only approval/source result; never reads external state."""

            def verify_action(self, command, *, now_ns):
                return execution.CtpDispatchAuthority(
                    authority_type="ctp_dispatch_authority.v1",
                    command_binding_sha256=command.authority_binding_sha256,
                    approval_use_id=command.approval_use_id,
                    approval_digest=command.approval_digest,
                    source_digest_sha256=hashlib.sha256(b"offline fake source").hexdigest(),
                    verifier_id="offline-fake-verifier",
                    verified_at_ns=now_ns,
                    expires_at_ns=now_ns + 5_000_000_000,
                )

        class QueueOnlyApi:
            exchange_kwargs = {"CTP": {}}

            def __init__(self):
                self.binding_reads = 0
                self.binding_reservations = 0
                self.sdk_submissions = 0

            def poll_event(self):
                return None

            def get_runtime_order_bindings(self, *_args, **_kwargs):
                self.binding_reads += 1
                return []

            def new_runtime_order_binding(self, *_args, **_kwargs):
                self.binding_reservations += 1
                raise AssertionError("the SDK OrderRef allocator must not run")

            async def async_make_order(self, *_args, **_kwargs):
                self.sdk_submissions += 1
                raise AssertionError("the generic SDK submit path must not run")

        class QueueOnlyManagedAdapter:
            ctp_managed_execution_version = 1

            def submit_order(self, *_args, **_kwargs):
                raise AssertionError("this smoke uses the queue seam directly")

            def cancel_order(self, *_args, **_kwargs):
                raise AssertionError("this smoke does not enable cancellation")

        scope = execution.ExecutionScope(
            "CTP", "simulation", "acct.i9.bridge.smoke", "strategy.bridge.smoke", "20260926"
        )
        database_path = tmp_path / "i9-bridge.sqlite3"
        store = store_module.SqliteExecutionStore(database_path)
        try:
            lease = store.acquire_or_renew_lease(scope, "offline-bridge-smoke")
            source_digests = (
                ("backtrader_prototype", hashlib.sha256(b"fixture-a").hexdigest()),
                ("sdk_jsonl", hashlib.sha256(b"fixture-b").hexdigest()),
            )
            legacy_scope = execution.ExecutionScope(
                "CTP", "simulation", "acct.i9.bridge.smoke", "strategy.legacy", "20260925"
            )
            legacy_mapping = execution.CtpOrderRefLegacyMapping(
                source_name="backtrader_prototype",
                account_key=scope.account_key,
                trading_day="20260925",
                scope_key=legacy_scope.key,
                managed_intent_id="legacy.intent",
                runtime_order_id="legacy.runtime",
                order_ref="000000000012",
            )
            proof = execution.CtpOrderRefSeedProof(
                trading_day=scope.trading_day,
                native_max_order_ref="000000000010",
                legacy_ledger_max_order_ref="000000000012",
                legacy_ledger_sha256=execution.payload_sha256(dict(source_digests)),
                account_key=scope.account_key,
                scope_key=scope.key,
                session_generation_id="generation.offline",
                native_front_id=4,
                native_session_id=91,
                existing_native_order_refs=("000000000009", "000000000010"),
                legacy_source_sha256=source_digests,
                legacy_mappings=(legacy_mapping,),
            )
            intent_id = "intent.i9.bridge.smoke"
            runtime_order_id = (
                "bt-managed-v1:" + hashlib.sha256(intent_id.encode("ascii")).hexdigest()
            )
            reservation = store.seed_ctp_order_ref_and_reserve_identity(
                scope,
                proof,
                intent_id,
                runtime_order_id,
                writer_lease=lease,
            )
            # Restart between OrderRef allocation and dispatch staging. The
            # same exact reservation must be the only identity the resumed
            # bridge can use; no SDK-local allocator is consulted.
            store.close()
            store = store_module.SqliteExecutionStore(database_path)
            lease = store.acquire_or_renew_lease(scope, "offline-bridge-smoke")
            assert store.read_ctp_order_identity(scope, intent_id) == reservation
            worker = worker_module.CtpManagedSingleWorkerCandidate(
                store, scope, lease, OfflineAuthorityVerifier()
            )
            bridge = CtpI9ManagedDispatchBridge(
                scope=scope, identity_port=store, single_worker=worker
            )
            assert bridge.reserve_submit_order_identity(intent_id, runtime_order_id) == reservation
            assert bridge.reserve_submit_order_identity(intent_id, runtime_order_id) == reservation
            assert store.read_ctp_order_identity(scope, intent_id) == reservation
            conflicting_runtime_order_id = (
                "bt-managed-v1:" + hashlib.sha256(b"conflicting-runtime-order-id").hexdigest()
            )
            with pytest.raises(ManagedExecutionAdapterError, match="OrderRef reservation failed"):
                bridge.reserve_submit_order_identity(intent_id, conflicting_runtime_order_id)
            assert store.read_ctp_order_identity(scope, intent_id) == reservation
            session_generation = "generation.offline"
            session_binding = {
                "session_identity": "opaque-offline-session",
                "session_generation_id": session_generation,
                "dispatch_front_id": 4,
                "dispatch_session_id": 91,
            }
            request_id = 101
            prepared_type = worker_module.CtpManagedPreparedDispatch
            command_id = worker_module.stable_managed_command_id(
                "submit", intent_id, runtime_order_id, None
            )
            submit = prepared_type(
                operation="submit",
                command_id=command_id,
                managed_intent_id=intent_id,
                runtime_order_id=runtime_order_id,
                order_ref=reservation.order_ref,
                request_payload={
                    "InstrumentID": "rb2710",
                    "OrderRef": reservation.order_ref,
                    "Direction": "0",
                    "CombOffsetFlag": "0",
                    "LimitPrice": 100.0,
                    "VolumeTotalOriginal": 1,
                },
                order_ref_reservation=reservation,
                approval_use_id="approval.offline.submit",
                approval_digest=hashlib.sha256(b"offline approval").hexdigest(),
                session_binding=session_binding,
                session_generation_id=session_generation,
                dispatch_front_id=4,
                dispatch_session_id=91,
                native_request_id=request_id,
                local_queue_receipt_id="a" * 32,
            )

            mismatched_request = prepared_type(
                operation="submit",
                command_id=command_id,
                managed_intent_id=intent_id,
                runtime_order_id=runtime_order_id,
                order_ref=reservation.order_ref,
                request_payload={
                    "InstrumentID": "rb2710",
                    "OrderRef": "000000000099",
                    "Direction": "0",
                    "CombOffsetFlag": "0",
                    "LimitPrice": 100.0,
                    "VolumeTotalOriginal": 1,
                },
                order_ref_reservation=reservation,
                approval_use_id="approval.offline.submit",
                approval_digest=hashlib.sha256(b"offline approval").hexdigest(),
                session_binding=session_binding,
                session_generation_id=session_generation,
                dispatch_front_id=4,
                dispatch_session_id=91,
                native_request_id=request_id,
                local_queue_receipt_id="a" * 32,
            )
            with pytest.raises(ManagedExecutionAdapterError, match="does not echo OrderRef"):
                bridge.stage_prepared_dispatch(mismatched_request)
            assert store.read_ctp_dispatch_command(scope, command_id) is None

            handle = bridge.stage_prepared_dispatch(submit)
            command_row = store.read_ctp_dispatch_command(scope, command_id)
            assert command_row is not None
            assert not hasattr(command_row, "runtime_order_id")
            assert command_row.correlation_key.runtime_order_id == runtime_order_id
            assert handle.binding.command_id == command_id
            assert handle.binding.order_ref == reservation.order_ref
            assert handle.binding.runtime_order_id == runtime_order_id
            assert command_row.local_queue_receipt_queued is None

            sender_calls = []
            other_bridge = CtpI9ManagedDispatchBridge(
                scope=scope, identity_port=store, single_worker=worker
            )
            with pytest.raises(ManagedExecutionAdapterError, match="issued by this bridge"):
                other_bridge.queue_ports(
                    handle, sender=lambda command: sender_calls.append(command)
                )
            assert (
                store.read_ctp_dispatch_command(scope, command_id).local_queue_receipt_queued
                is None
            )

            # The normal request builder remains closed: it has no parameter
            # for consuming the I9 reservation and refuses before consulting
            # the separate SDK allocator. The v2 queue hook below only proves
            # that the lower-level Store/I9 handoff seam composes offline.
            queue_api = QueueOnlyApi()
            bt_store = BtApiStore(
                provider="btapi",
                api=queue_api,
                config={
                    "exchange_kwargs": {"CTP": {}},
                    "execution_config": {
                        "market_data_only": False,
                        "strategy_id": "strategy.bridge.smoke",
                    },
                },
                managed_execution_adapter=QueueOnlyManagedAdapter(),
            )
            bt_store._sdk_command_types = {
                "OrderRequest": lambda **_kwargs: None,
                "OrderType": lambda value: value,
                "Side": lambda value: value,
            }
            bt_store._sdk_account_id = lambda *_args, **_kwargs: "offline-account"
            bt_store._validate_managed_ctp_identity_scope = lambda *_args, **_kwargs: None
            with pytest.raises(BtApiStoreError, match="single execution outbox"):
                bt_store._sdk_order_request(
                    "CTP___FUTURE",
                    {
                        "symbol": "rb2710",
                        "bt_order_ref": 17,
                        "side": "buy",
                        "size": 1,
                        "price": 100,
                        "order_type": "limit",
                        "runtime_order_id": runtime_order_id,
                        "managed_intent_id": intent_id,
                        "hedge_flag": "2",
                    },
                )
            assert queue_api.binding_reads == queue_api.binding_reservations == 0

            sender_order_refs = []
            queue_events = []

            def fake_sender(claimed_command):
                row = store.read_ctp_dispatch_command(scope, command_id)
                assert row is not None
                assert row.status == "CLAIMED"
                assert row.local_queue_receipt_queued is True
                assert claimed_command.order_ref == reservation.order_ref
                assert claimed_command.request_payload["OrderRef"] == reservation.order_ref
                sender_order_refs.append(claimed_command.order_ref)
                queue_events.append("fake_sender")
                return worker_module.CtpNativeDispatchResult(
                    "QUEUED", {"kind": "fake-native-return", "return_code": 0}
                )

            receipt_writer, dispatcher = bridge.queue_ports(handle, sender=fake_sender)
            original_binding = handle.binding
            with pytest.raises(ManagedExecutionAdapterError, match="receipt-ready binding"):
                asyncio.run(dispatcher(original_binding))
            assert sender_order_refs == []
            assert (
                store.read_ctp_dispatch_command(scope, command_id).local_queue_receipt_queued
                is None
            )

            def commit_before_publish(receipt):
                assert bt_store._command_heap == []
                assert receipt["client_order_id"] == reservation.order_ref
                committed = receipt_writer(receipt)
                row = store.read_ctp_dispatch_command(scope, command_id)
                assert row is not None
                assert row.local_queue_receipt_queued is True
                queue_events.append("receipt_committed")
                return committed

            store_receipt = bt_store._enqueue_sdk_command(
                {
                    "operation": "submit",
                    "venue": "CTP___FUTURE",
                    "symbol": "rb2710",
                    "request": SimpleNamespace(execution_role=None),
                    "bt_order_ref": 17,
                    "client_order_id": reservation.order_ref,
                },
                priority_name="open",
                managed_ctp_binding=original_binding,
                managed_ctp_receipt_writer=commit_before_publish,
                managed_ctp_dispatcher=dispatcher,
            )
            assert store_receipt["queued"] is True
            assert store_receipt["client_order_id"] == reservation.order_ref
            assert len(bt_store._command_heap) == 1
            _priority, _sequence, queued_command = heapq.heappop(bt_store._command_heap)
            assert queued_command["managed_ctp_binding"].local_queue_receipt_queued is True
            queue_events.append("published")

            completion = asyncio.run(bt_store._execute_sdk_command(queued_command))
            assert completion["success"] is True
            assert completion["response"]["state"] == "PENDING"
            assert queue_events == ["receipt_committed", "published", "fake_sender"]
            assert sender_order_refs == [reservation.order_ref]
            assert queue_api.binding_reads == queue_api.binding_reservations == 0
            assert queue_api.sdk_submissions == 0

            replay = asyncio.run(
                queued_command["managed_ctp_dispatcher"](queued_command["managed_ctp_binding"])
            )
            assert replay.state.value == "PENDING"
            assert sender_order_refs == [reservation.order_ref]

            # A sender exception after I9 has claimed the command is UNKNOWN,
            # durable, and never replayed. The Store receipt still commits
            # before this second command is published to its heap.
            unknown_intent_id = "intent.i9.bridge.unknown"
            unknown_runtime_order_id = (
                "bt-managed-v1:" + hashlib.sha256(unknown_intent_id.encode("ascii")).hexdigest()
            )
            unknown_reservation = bridge.reserve_submit_order_identity(
                unknown_intent_id, unknown_runtime_order_id
            )
            unknown_command_id = worker_module.stable_managed_command_id(
                "submit", unknown_intent_id, unknown_runtime_order_id, None
            )
            unknown_prepared = prepared_type(
                operation="submit",
                command_id=unknown_command_id,
                managed_intent_id=unknown_intent_id,
                runtime_order_id=unknown_runtime_order_id,
                order_ref=unknown_reservation.order_ref,
                request_payload={
                    "InstrumentID": "rb2710",
                    "OrderRef": unknown_reservation.order_ref,
                    "Direction": "0",
                    "CombOffsetFlag": "0",
                    "LimitPrice": 100.0,
                    "VolumeTotalOriginal": 1,
                },
                order_ref_reservation=unknown_reservation,
                approval_use_id="approval.offline.unknown",
                approval_digest=hashlib.sha256(b"offline unknown approval").hexdigest(),
                session_binding=session_binding,
                session_generation_id=session_generation,
                dispatch_front_id=4,
                dispatch_session_id=91,
                native_request_id=103,
                local_queue_receipt_id="c" * 32,
            )
            unknown_handle = bridge.stage_prepared_dispatch(unknown_prepared)
            unknown_sender_calls = []

            def unknown_sender(claimed_command):
                row = store.read_ctp_dispatch_command(scope, unknown_command_id)
                assert row is not None
                assert row.status == "CLAIMED"
                assert row.local_queue_receipt_queued is True
                assert claimed_command.order_ref == unknown_reservation.order_ref
                unknown_sender_calls.append(claimed_command.order_ref)
                unknown_queue_events.append("fake_sender")
                raise TimeoutError("offline fake sender outcome is ambiguous")

            unknown_receipt_writer, unknown_dispatcher = bridge.queue_ports(
                unknown_handle, sender=unknown_sender
            )
            unknown_queue_events = []

            def commit_unknown_receipt_before_publish(receipt):
                assert bt_store._command_heap == []
                committed = unknown_receipt_writer(receipt)
                assert (
                    store.read_ctp_dispatch_command(
                        scope, unknown_command_id
                    ).local_queue_receipt_queued
                    is True
                )
                unknown_queue_events.append("receipt_committed")
                return committed

            unknown_store_receipt = bt_store._enqueue_sdk_command(
                {
                    "operation": "submit",
                    "venue": "CTP___FUTURE",
                    "symbol": "rb2710",
                    "request": SimpleNamespace(execution_role=None),
                    "bt_order_ref": 18,
                    "client_order_id": unknown_reservation.order_ref,
                },
                priority_name="open",
                managed_ctp_binding=unknown_handle.binding,
                managed_ctp_receipt_writer=commit_unknown_receipt_before_publish,
                managed_ctp_dispatcher=unknown_dispatcher,
            )
            assert unknown_store_receipt["queued"] is True
            _priority, _sequence, unknown_command = heapq.heappop(bt_store._command_heap)
            unknown_queue_events.append("published")
            unknown_completion = asyncio.run(bt_store._execute_sdk_command(unknown_command))
            assert unknown_completion["success"] is False
            assert unknown_completion["status"] == "unknown"
            assert unknown_completion["execution_unknown"] is True
            assert unknown_queue_events == ["receipt_committed", "published", "fake_sender"]
            assert unknown_sender_calls == [unknown_reservation.order_ref]
            unknown_row = store.read_ctp_dispatch_command(scope, unknown_command_id)
            assert unknown_row.status == "UNKNOWN"
            assert unknown_row.local_queue_receipt_queued is True
            replay_unknown = asyncio.run(
                unknown_command["managed_ctp_dispatcher"](unknown_command["managed_ctp_binding"])
            )
            assert replay_unknown.state.value == "UNKNOWN"
            assert unknown_sender_calls == [unknown_reservation.order_ref]

            cancel_id = "cancel." + intent_id
            cancel_command_id = worker_module.stable_managed_command_id(
                "cancel", intent_id, runtime_order_id, cancel_id
            )
            cancel = prepared_type(
                operation="cancel",
                command_id=cancel_command_id,
                managed_intent_id=intent_id,
                runtime_order_id=runtime_order_id,
                order_ref=reservation.order_ref,
                request_payload={
                    "InstrumentID": "rb2710",
                    "OrderRef": reservation.order_ref,
                    "ExchangeID": "SHFE",
                    "OrderSysID": "fake-order-sys-id",
                    "FrontID": 4,
                    "SessionID": 91,
                    "ActionFlag": "0",
                    "LimitPrice": 0,
                    "VolumeChange": 0,
                },
                order_ref_reservation=reservation,
                approval_use_id="approval.offline.cancel",
                approval_digest=hashlib.sha256(b"offline cancel approval").hexdigest(),
                session_binding=session_binding,
                session_generation_id=session_generation,
                dispatch_front_id=4,
                dispatch_session_id=91,
                native_request_id=77,
                local_queue_receipt_id="b" * 32,
                managed_cancel_intent_id=cancel_id,
                cancel_target_exchange_id="SHFE",
                cancel_target_order_sys_id="fake-order-sys-id",
                cancel_target_front_id=4,
                cancel_target_session_id=91,
            )
            with pytest.raises(
                ManagedExecutionAdapterError,
                match="trusted typed order-projection provenance",
            ):
                bridge.stage_prepared_dispatch(cancel)
            assert store.read_ctp_dispatch_command(scope, cancel_command_id) is None

            # Reproduce an out-of-band SDK caller forging a typed handle after
            # staging a local cancel row. The bridge must not issue queue
            # callbacks, persist a receipt, or invoke the sender for that row.
            class OfflineTargetVerifier:
                """Fake-only current row; never evidence of a provider query."""

                def verify_order_target(
                    self, target_scope, target_reservation, evidence, *, now_ns
                ):
                    assert target_scope == scope
                    assert target_reservation == reservation
                    assert evidence == {"fake_only": True}
                    digest = hashlib.sha256(b"offline fake order target").hexdigest()
                    return store_module.CtpVerifiedOrderTargetProjection(
                        account_key=reservation.account_key,
                        scope_key=reservation.scope_key,
                        trading_day=reservation.trading_day,
                        managed_intent_id=reservation.managed_intent_id,
                        runtime_order_id=reservation.runtime_order_id,
                        order_ref=reservation.order_ref,
                        account_fingerprint_sha256=digest,
                        registration_digest=digest,
                        instrument_id="rb2710",
                        exchange_id="SHFE",
                        session_generation_id=session_generation,
                        connection_generation=1,
                        query_front_id=4,
                        query_session_id=91,
                        query_request_id=202,
                        query_filters_sha256=digest,
                        query_records_sha256=digest,
                        source_evidence_sha256=digest,
                        query_record_count=1,
                        query_match_count=1,
                        query_complete=True,
                        query_terminal=True,
                        query_timed_out=False,
                        query_error_id=0,
                        late_callback_count=0,
                        order_sys_id="fake-order-sys-id",
                        front_id=4,
                        session_id=91,
                        provider_state="OPEN",
                        quantity=1,
                        traded_quantity=0,
                        remaining_quantity=1,
                        verifier_id="offline-test-only",
                        verified_at_ns=now_ns,
                        expires_at_ns=now_ns + 2_000_000_000,
                    )

            cancel_target = store.issue_ctp_order_target_projection(
                scope,
                intent_id,
                {"fake_only": True},
                verifier=OfflineTargetVerifier(),
            )
            candidate_cancel_binding = worker.stage_prepared_dispatch(
                cancel,
                cancel_target_projection=cancel_target,
            )
            cancel_binding = i9_bridge_module._binding_from_i9(candidate_cancel_binding)
            forged_cancel_handle = CtpI9ManagedDispatchHandle(
                cancel_binding, candidate_cancel_binding, cancel
            )
            with pytest.raises(ManagedExecutionAdapterError, match="issued by this bridge"):
                bridge.queue_ports(
                    forged_cancel_handle, sender=lambda command: sender_calls.append(command)
                )
            cancel_row = store.read_ctp_dispatch_command(scope, cancel_command_id)
            assert cancel_row is not None
            assert cancel_row.local_queue_receipt_queued is None
            assert cancel_row.status == "READY"
            assert sender_calls == []
        finally:
            store.close()
    finally:
        for name in tuple(sys.modules):
            if name == "bt_api_execution" or name.startswith("bt_api_execution."):
                sys.modules.pop(name, None)
        sys.modules.update(original_modules)
