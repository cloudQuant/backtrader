from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, replace
from hashlib import sha256
from itertools import count

import pytest
from bt_api_execution import (
    CtpCancelTarget,
    CtpOrderRefSeedProof,
    CtpOrderTargetProjectionHandle,
    CtpVerifiedOrderTargetProjection,
    ExecutionScope,
    SqliteExecutionStore,
)
from bt_api_execution.ctp_identity_authority import (
    CtpActionRefSeedProof,
    CtpUnifiedOrderActionAuthority,
)
from bt_api_execution.ctp_single_worker_candidate import (
    CtpManagedPreparedDispatch,
    CtpManagedQueueReceipt,
    CtpManagedSingleWorkerCandidate,
    CtpNativeDispatchResult,
    stable_managed_command_id,
)
from bt_api_execution.errors import ContractValidationError, DurableStoreError


@dataclass(frozen=True)
class _SyntheticNativeOrderQueryEvidence:
    """Test-only opaque stand-in; this is not evidence from a native SDK query."""

    instrument_id: str
    exchange_id: str
    order_sys_id: str
    session_generation_id: str
    query_front_id: int
    query_session_id: int
    query_request_id: int
    front_id: int
    session_id: int
    provider_state: str = "OPEN"
    quantity: int = 1
    traded_quantity: int = 0


class _SyntheticOrderQueryVerifier:
    """Test-only fake verifier used to exercise the durable consumer contract."""

    def verify_order_target(self, scope, reservation, evidence, *, now_ns):
        if type(evidence) is not _SyntheticNativeOrderQueryEvidence:
            raise ContractValidationError("synthetic typed query evidence required")
        return CtpVerifiedOrderTargetProjection(
            account_key=reservation.account_key,
            scope_key=reservation.scope_key,
            trading_day=reservation.trading_day,
            managed_intent_id=reservation.managed_intent_id,
            runtime_order_id=reservation.runtime_order_id,
            order_ref=reservation.order_ref,
            account_fingerprint_sha256=sha256(b"synthetic account fingerprint").hexdigest(),
            registration_digest=sha256(b"synthetic registration").hexdigest(),
            instrument_id=evidence.instrument_id,
            exchange_id=evidence.exchange_id,
            session_generation_id=evidence.session_generation_id,
            connection_generation=1,
            query_front_id=evidence.query_front_id,
            query_session_id=evidence.query_session_id,
            query_request_id=evidence.query_request_id,
            query_filters_sha256=sha256(b"synthetic query filters").hexdigest(),
            query_records_sha256=sha256(b"synthetic query records").hexdigest(),
            source_evidence_sha256=sha256(b"synthetic source evidence").hexdigest(),
            query_record_count=1,
            query_match_count=1,
            query_complete=True,
            query_terminal=True,
            query_timed_out=False,
            query_error_id=0,
            late_callback_count=0,
            order_sys_id=evidence.order_sys_id,
            front_id=evidence.front_id,
            session_id=evidence.session_id,
            provider_state=evidence.provider_state,
            quantity=evidence.quantity,
            traded_quantity=evidence.traded_quantity,
            remaining_quantity=evidence.quantity - evidence.traded_quantity,
            verifier_id="test-only.synthetic-order-query-verifier",
            verified_at_ns=now_ns,
            expires_at_ns=now_ns + 5_000_000_000,
        )


_QUERY_REQUEST_IDS = count(11)


def _scope() -> ExecutionScope:
    return ExecutionScope("CTP", "simulation", "g5-worker", "strategy.worker", "20260927")


def _runtime_id(value: str) -> str:
    return "bt-managed-v1:" + sha256(value.encode("ascii")).hexdigest()


def _open(path, owner: str = "worker-owner"):
    store = SqliteExecutionStore(path)
    authority = CtpUnifiedOrderActionAuthority(store)
    scope = _scope()
    lease = store.acquire_or_renew_lease(scope, owner, ttl_ns=120_000_000_000)

    return store, authority, scope, lease


def _seed_order(authority, scope, lease):
    return authority.reserve_submit_order_identity(
        scope,
        CtpOrderRefSeedProof(
            "20260927",
            "000000000010",
            "000000000012",
            sha256(b"synthetic order seed").hexdigest(),
        ),
        "worker-intent",
        _runtime_id("worker-intent"),
        writer_lease=lease,
    )


def _prepared(order):
    target = CtpCancelTarget(order.order_ref, "SHFE", "SYS-WORKER", 17, 29)
    payload = {
        "InstrumentID": "rb2710",
        "OrderRef": target.order_ref,
        "ExchangeID": target.exchange_id,
        "OrderSysID": target.order_sys_id,
        "FrontID": target.front_id,
        "SessionID": target.session_id,
        "ActionFlag": "0",
        "LimitPrice": 0.0,
        "VolumeChange": 0,
    }
    action_id = "cancel-worker"
    return CtpManagedPreparedDispatch(
        operation="cancel",
        command_id=stable_managed_command_id(
            "cancel", "worker-intent", order.runtime_order_id, action_id
        ),
        managed_intent_id="worker-intent",
        runtime_order_id=order.runtime_order_id,
        order_ref=order.order_ref,
        request_payload=payload,
        order_ref_reservation=order,
        approval_use_id="approval-worker",
        approval_digest=sha256(b"synthetic approval").hexdigest(),
        session_binding={
            "session_generation_id": "generation-1",
            "dispatch_front_id": 17,
            "dispatch_session_id": 29,
        },
        session_generation_id="generation-1",
        dispatch_front_id=17,
        dispatch_session_id=29,
        native_request_id=5,
        local_queue_receipt_id="0123456789abcdef0123456789abcdef",
        managed_cancel_intent_id=action_id,
        cancel_target_exchange_id=target.exchange_id,
        cancel_target_order_sys_id=target.order_sys_id,
        cancel_target_front_id=target.front_id,
        cancel_target_session_id=target.session_id,
    )


def _prepared_submit(order):
    return CtpManagedPreparedDispatch(
        operation="submit",
        command_id=stable_managed_command_id(
            "submit", "worker-intent", order.runtime_order_id
        ),
        managed_intent_id="worker-intent",
        runtime_order_id=order.runtime_order_id,
        order_ref=order.order_ref,
        request_payload={"InstrumentID": "rb2710", "OrderRef": order.order_ref},
        order_ref_reservation=order,
        approval_use_id="approval-submit-worker",
        approval_digest=sha256(b"synthetic submit approval").hexdigest(),
        session_binding={
            "session_generation_id": "generation-1",
            "dispatch_front_id": 17,
            "dispatch_session_id": 29,
        },
        session_generation_id="generation-1",
        dispatch_front_id=17,
        dispatch_session_id=29,
        native_request_id=6,
        local_queue_receipt_id="1123456789abcdef0123456789abcdef",
    )


def _reserve_action(authority, scope, lease, order):
    return authority.reserve_cancel_action_identity(
        scope,
        "cancel-worker",
        "worker-intent",
        order.runtime_order_id,
        order.order_ref,
        legacy_seed=CtpActionRefSeedProof(
            "20260927", 41, sha256(b"synthetic action seed").hexdigest()
        ),
        writer_lease=lease,
    )


def _queue(binding, command):
    return CtpManagedQueueReceipt(
        command_id=command.command_id,
        request_payload_sha256=command.request_payload_sha256,
        operation=command.operation,
        receipt_id=binding.local_queue_receipt_id,
        queued=True,
    )


def _target_projection(store, order, prepared, *, exchange_id=None):
    evidence = _SyntheticNativeOrderQueryEvidence(
        instrument_id=prepared.request_payload["InstrumentID"],
        exchange_id=exchange_id or prepared.cancel_target_exchange_id,
        order_sys_id=prepared.cancel_target_order_sys_id,
        session_generation_id=prepared.session_generation_id,
        query_front_id=prepared.dispatch_front_id,
        query_session_id=prepared.dispatch_session_id,
        query_request_id=next(_QUERY_REQUEST_IDS),
        front_id=prepared.cancel_target_front_id,
        session_id=prepared.cancel_target_session_id,
    )
    return store.issue_ctp_order_target_projection(
        _scope(), order.managed_intent_id, evidence, verifier=_SyntheticOrderQueryVerifier()
    )


def test_action_identity_is_typed_staged_and_echoed_through_worker_to_sdk_fake(tmp_path):
    store, authority, scope, lease = _open(tmp_path / "worker.sqlite3")
    try:
        order = _seed_order(authority, scope, lease)
        action = _reserve_action(authority, scope, lease, order)
        prepared = _prepared(order)
        worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)

        signature = inspect.signature(worker.stage_prepared_dispatch)
        assert "cancel_target_projection" in signature.parameters
        assert "action_identity" in signature.parameters
        projection_handle = _target_projection(store, order, prepared)
        assert type(projection_handle) is CtpOrderTargetProjectionHandle
        projection_row = store._connection.execute(
            "SELECT projection_payload_json, projection_sha256 FROM ctp_order_target_projections "
            "WHERE account_key = ? AND projection_id = ?",
            (scope.account_key, projection_handle.projection_id),
        ).fetchone()
        assert projection_row is not None
        assert json.loads(projection_row["projection_payload_json"]) == (
            projection_handle.projection.to_payload()
        )
        assert projection_row["projection_sha256"] == projection_handle.projection_sha256
        binding = worker.stage_prepared_dispatch(
            prepared,
            cancel_target_projection=projection_handle,
            action_identity=action,
        )
        staged = store.read_ctp_dispatch_command(scope, prepared.command_id)
        assert staged is not None
        assert staged.request_payload["OrderActionRef"] == action.native_action_ref
        assert staged.request_payload["OrderRef"] == order.order_ref
        assert staged.request_payload_sha256 == sha256(
            json.dumps(
                dict(staged.request_payload),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
        ).hexdigest()
        assert binding.native_action_ref == action.native_action_ref
        assert binding.native_request_payload["OrderActionRef"] == action.native_action_ref
        handoff = store._connection.execute(
            "SELECT action_identity_json, action_ref, state FROM g5_ctp_worker_handoffs "
            "WHERE account_key = ? AND command_id = ?",
            (scope.account_key, prepared.command_id),
        ).fetchone()
        assert json.loads(handoff["action_identity_json"])["native_action_ref"] == (
            action.native_action_ref
        )
        assert handoff["action_ref"] == action.native_action_ref
        assert handoff["state"] == "STAGED"
        consumption = store._connection.execute(
            "SELECT projection_id, command_id FROM ctp_order_target_projection_consumptions "
            "WHERE account_key = ? AND command_id = ?",
            (scope.account_key, prepared.command_id),
        ).fetchone()
        assert consumption["projection_id"] == projection_handle.projection_id

        queued_binding = worker.record_managed_queue_receipt(
            prepared.command_id, binding, _queue(binding, staged)
        )
        seen = []

        def sdk_fake(command):
            seen.append(dict(command.request_payload))
            return CtpNativeDispatchResult(
                "QUEUED", {"queue_code": 0, "provider_ack": False}
            )

        result = worker.dispatch_managed_command(
            prepared.command_id, queued_binding, sdk_fake
        )
        assert result.worker_state == "COMPLETED"
        assert result.sender_called is True
        assert seen == [dict(staged.request_payload)]
        assert seen[0]["OrderActionRef"] == action.native_action_ref
        assert result.command.native_receipt_payload == {
            "kind": "sdk_fake_dispatch",
            "outcome": "QUEUED",
        }
        assert "provider_ack" not in result.command.native_receipt_payload
        assert worker.dispatch_managed_command(
            prepared.command_id, queued_binding, sdk_fake
        ).sender_called is False
        assert len(seen) == 1
    finally:
        store.close()


def test_submit_keeps_one_argument_worker_call_and_has_no_action_identity(tmp_path):
    store, authority, scope, lease = _open(tmp_path / "submit-one-argument.sqlite3")
    try:
        order = _seed_order(authority, scope, lease)
        prepared = _prepared_submit(order)
        worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)
        binding = worker.stage_prepared_dispatch(prepared)
        command = store.read_ctp_dispatch_command(scope, prepared.command_id)
        assert command is not None
        assert command.operation == "SUBMIT"
        assert command.request_payload == dict(prepared.request_payload)
        assert "OrderActionRef" not in command.request_payload
        assert binding.native_action_ref is None
        row = store._connection.execute(
            "SELECT action_identity_json, action_ref FROM g5_ctp_worker_handoffs "
            "WHERE account_key = ? AND command_id = ?",
            (scope.account_key, prepared.command_id),
        ).fetchone()
        assert row["action_identity_json"] is None
        assert row["action_ref"] is None
    finally:
        store.close()


def test_reserved_action_without_stage_is_retryable_only_as_same_identity(tmp_path):
    store, authority, scope, lease = _open(tmp_path / "reserved-before-stage.sqlite3")
    try:
        order = _seed_order(authority, scope, lease)
        action = _reserve_action(authority, scope, lease, order)
        prepared = _prepared(order)
        worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)
        with pytest.raises(ContractValidationError, match="typed Store-issued ActionRef"):
            worker.stage_prepared_dispatch(
                prepared,
                cancel_target_projection=_target_projection(store, order, prepared),
                action_identity=None,
            )
        assert store.read_ctp_dispatch_command(scope, prepared.command_id) is None
        assert store._connection.execute(
            "SELECT COUNT(*) FROM g5_ctp_worker_handoffs"
        ).fetchone()[0] == 0

        current_action = authority.read_cancel_action_identity(scope, action.managed_action_id)
        assert current_action == action
        binding = worker.stage_prepared_dispatch(
            prepared,
            cancel_target_projection=_target_projection(store, order, prepared),
            action_identity=current_action,
        )
        staged = store.read_ctp_dispatch_command(scope, prepared.command_id)
        assert staged is not None and staged.status == "READY"
        assert staged.request_payload["OrderActionRef"] == action.native_action_ref
        assert binding.native_action_ref == action.native_action_ref
    finally:
        store.close()


def test_cancel_target_requires_exact_fields_and_same_store_handle_readback(tmp_path):
    store, authority, scope, lease = _open(tmp_path / "target-projection.sqlite3")
    try:
        order = _seed_order(authority, scope, lease)
        action = _reserve_action(authority, scope, lease, order)
        prepared = _prepared(order)
        worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)

        issued = _target_projection(store, order, prepared)
        forged = replace(issued)
        with pytest.raises(ContractValidationError, match="same-store CTP target handle"):
            worker.stage_prepared_dispatch(
                prepared,
                cancel_target_projection=forged,
                action_identity=action,
            )
        assert store.read_ctp_dispatch_command(scope, prepared.command_id) is None

        wrong_target = _target_projection(store, order, prepared, exchange_id="DCE")
        with pytest.raises(ContractValidationError, match="projection differs: exchange_id"):
            worker.stage_prepared_dispatch(
                prepared,
                cancel_target_projection=wrong_target,
                action_identity=action,
            )
        assert store.read_ctp_dispatch_command(scope, prepared.command_id) is None
    finally:
        store.close()


def test_default_target_verifier_rejects_caller_mapping_and_persists_nothing(tmp_path):
    store, authority, scope, lease = _open(tmp_path / "reject-untrusted-query.sqlite3")
    try:
        order = _seed_order(authority, scope, lease)
        with pytest.raises(ContractValidationError, match="query verification failed"):
            store.issue_ctp_order_target_projection(
                scope,
                order.managed_intent_id,
                {"OrderRef": order.order_ref, "OrderStatus": "OPEN"},
            )
        assert store._connection.execute(
            "SELECT COUNT(*) FROM ctp_order_target_projections"
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_store_rejects_cancel_action_ref_without_candidate_authority_row(tmp_path):
    store, authority, scope, lease = _open(tmp_path / "reject-unissued-action-ref.sqlite3")
    try:
        order = _seed_order(authority, scope, lease)
        prepared = _prepared(order)
        handle = _target_projection(store, order, prepared)
        target = CtpCancelTarget(
            order.order_ref,
            prepared.cancel_target_exchange_id,
            prepared.cancel_target_order_sys_id,
            prepared.cancel_target_front_id,
            prepared.cancel_target_session_id,
        )
        with pytest.raises(
            ContractValidationError,
            match="not issued by the candidate same-Store authority",
        ):
            store.stage_ctp_dispatch_command(
                scope,
                "cancel-with-unissued-ref",
                "CANCEL",
                {**dict(prepared.request_payload), "OrderActionRef": 2_147_000_000},
                approval_use_id="approval-unissued-ref",
                approval_digest=sha256(b"test approval").hexdigest(),
                session_binding=dict(prepared.session_binding),
                writer_lease=lease,
                cancel_target=target,
                cancel_target_projection=handle,
            )
        assert store.read_ctp_dispatch_command(scope, "cancel-with-unissued-ref") is None
        assert store._connection.execute(
            "SELECT COUNT(*) FROM ctp_order_target_projection_consumptions"
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_projection_row_tamper_fails_hash_and_reopen_does_not_revive_handle(tmp_path):
    path = tmp_path / "projection-reopen.sqlite3"
    store, authority, scope, lease = _open(path)
    order = _seed_order(authority, scope, lease)
    prepared = _prepared(order)
    handle = _target_projection(store, order, prepared)
    assert store.read_ctp_order_target_projection(scope, handle) == handle.projection
    with pytest.raises(DurableStoreError, match="transaction failed"):
        with store._transaction() as cursor:
            cursor.execute(
                "UPDATE ctp_order_target_projections SET projection_payload_json = ? "
                "WHERE account_key = ? AND projection_id = ?",
                ("{}", scope.account_key, handle.projection_id),
            )
    # Exercise the reader's hash/schema defense after simulating out-of-band
    # schema-owner tampering that bypasses the immutability trigger.
    store._connection.execute("DROP TRIGGER ctp_order_target_projections_immutable_update")
    with store._transaction() as cursor:
        cursor.execute(
            "UPDATE ctp_order_target_projections SET projection_payload_json = ? "
            "WHERE account_key = ? AND projection_id = ?",
            ("{}", scope.account_key, handle.projection_id),
        )
    with pytest.raises(ContractValidationError, match="projection payload is invalid"):
        store.read_ctp_order_target_projection(scope, handle)
    store.close()

    reopened = SqliteExecutionStore(path)
    scope2 = _scope()
    try:
        assert reopened._connection.execute(
            "SELECT COUNT(*) FROM ctp_order_target_projections WHERE account_key = ?",
            (scope2.account_key,),
        ).fetchone()[0] == 1
        with pytest.raises(ContractValidationError, match="same-store CTP target handle"):
            reopened.read_ctp_order_target_projection(scope2, handle)
    finally:
        reopened.close()


def test_projection_expiry_after_claim_blocks_sender_and_fences_unknown(tmp_path):
    store, authority, scope, lease = _open(tmp_path / "expires-before-send.sqlite3")
    try:
        clock = {"now": 1_000_000_000}
        store._monotonic_now_ns = lambda: clock["now"]
        order = _seed_order(authority, scope, lease)
        action = _reserve_action(authority, scope, lease, order)
        prepared = _prepared(order)
        worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)
        handle = _target_projection(store, order, prepared)
        expires_at_ns = handle.projection.expires_at_ns
        binding = worker.stage_prepared_dispatch(
            prepared, cancel_target_projection=handle, action_identity=action
        )
        command = store.read_ctp_dispatch_command(scope, prepared.command_id)
        assert command is not None
        binding = worker.record_managed_queue_receipt(
            prepared.command_id, binding, _queue(binding, command)
        )

        set_state = worker._set_state

        def expire_after_claim(command_id, state, *, from_states=None):
            result = set_state(command_id, state, from_states=from_states)
            if state == "CLAIMED":
                clock["now"] = expires_at_ns
            return result

        worker._set_state = expire_after_claim
        sender_calls = []
        result = worker.dispatch_managed_command(
            prepared.command_id, binding, lambda value: sender_calls.append(value)
        )
        assert result.worker_state == "UNKNOWN"
        assert result.sender_called is False
        assert result.command.status == "UNKNOWN"
        assert sender_calls == []
        retry = worker.dispatch_managed_command(
            prepared.command_id, binding, lambda value: sender_calls.append(value)
        )
        assert retry.worker_state == "UNKNOWN"
        assert retry.sender_called is False
        assert sender_calls == []
    finally:
        store.close()


def test_awaitable_sender_is_rejected_before_claim_and_not_entered(tmp_path):
    store, authority, scope, lease = _open(tmp_path / "awaitable-sender-rejected.sqlite3")
    try:
        order = _seed_order(authority, scope, lease)
        action = _reserve_action(authority, scope, lease, order)
        prepared = _prepared(order)
        worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)
        binding = worker.stage_prepared_dispatch(
            prepared,
            cancel_target_projection=_target_projection(store, order, prepared),
            action_identity=action,
        )
        command = store.read_ctp_dispatch_command(scope, prepared.command_id)
        assert command is not None
        binding = worker.record_managed_queue_receipt(
            prepared.command_id, binding, _queue(binding, command)
        )
        sender_calls = []

        async def delayed_sender(value):
            sender_calls.append(value)
            return CtpNativeDispatchResult("QUEUED", {"queued": True})

        with pytest.raises(ContractValidationError, match="awaitable SDK sender is unsupported"):
            worker.dispatch_managed_command(prepared.command_id, binding, delayed_sender)
        assert sender_calls == []
        persisted = store.read_ctp_dispatch_command(scope, prepared.command_id)
        assert persisted is not None and persisted.status == "READY"
    finally:
        store.close()


def test_uncertain_sender_receipt_is_unknown_and_never_replayed_after_reopen(tmp_path):
    path = tmp_path / "uncertain.sqlite3"
    store, authority, scope, lease = _open(path)
    order = _seed_order(authority, scope, lease)
    action = _reserve_action(authority, scope, lease, order)
    prepared = _prepared(order)
    worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)
    binding = worker.stage_prepared_dispatch(
        prepared,
        cancel_target_projection=_target_projection(store, order, prepared),
        action_identity=action,
    )
    command = store.read_ctp_dispatch_command(scope, prepared.command_id)
    assert command is not None
    binding = worker.record_managed_queue_receipt(
        prepared.command_id, binding, _queue(binding, command)
    )
    sender_calls = []

    def uncertain_send(_command):
        sender_calls.append("possibly sent")
        raise TimeoutError("fake SDK lost its local receipt")

    try:
        first = worker.dispatch_managed_command(prepared.command_id, binding, uncertain_send)
        assert first.worker_state == "UNKNOWN"
        assert first.sender_called is True
        assert first.command.status == "UNKNOWN"
        assert sender_calls == ["possibly sent"]
        assert store.release_lease(scope, lease.owner_id, fencing_token=lease.fencing_token)
    finally:
        store.close()

    reopened, authority2, scope2, lease2 = _open(path, "worker-restarted")
    try:
        worker2 = CtpManagedSingleWorkerCandidate(reopened, scope2, lease2, authority2)
        persisted = reopened.read_ctp_dispatch_command(scope2, prepared.command_id)
        assert persisted is not None and persisted.status == "UNKNOWN"
        second = worker2.dispatch_managed_command(
            prepared.command_id, binding, lambda command: sender_calls.append("replayed")
        )
        assert second.worker_state == "UNKNOWN"
        assert second.sender_called is False
        assert sender_calls == ["possibly sent"]
    finally:
        reopened.close()


def test_claimed_crash_recovers_to_unknown_before_new_worker_can_send(tmp_path):
    path = tmp_path / "crash-after-claim.sqlite3"
    store, authority, scope, lease = _open(path)
    order = _seed_order(authority, scope, lease)
    action = _reserve_action(authority, scope, lease, order)
    prepared = _prepared(order)
    worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)
    binding = worker.stage_prepared_dispatch(
        prepared,
        cancel_target_projection=_target_projection(store, order, prepared),
        action_identity=action,
    )
    command = store.read_ctp_dispatch_command(scope, prepared.command_id)
    assert command is not None
    binding = worker.record_managed_queue_receipt(
        prepared.command_id, binding, _queue(binding, command)
    )
    claimed = store.claim_ctp_dispatch_command(scope, prepared.command_id, writer_lease=lease)
    assert claimed is not None and claimed.status == "CLAIMED"
    # This models process death after the durable claim but before sender entry.
    assert store.release_lease(scope, lease.owner_id, fencing_token=lease.fencing_token)
    store.close()

    reopened, authority2, scope2, lease2 = _open(path, "worker-restarted")
    try:
        worker2 = CtpManagedSingleWorkerCandidate(reopened, scope2, lease2, authority2)
        recovered = worker2.recover_claimed_after_restart()
        assert len(recovered) == 1
        assert recovered[0].command_id == prepared.command_id
        assert recovered[0].status == "UNKNOWN"
        calls = []
        result = worker2.dispatch_managed_command(
            prepared.command_id,
            binding,
            lambda value: calls.append(value),
        )
        assert result.worker_state == "UNKNOWN"
        assert result.sender_called is False
        assert calls == []
    finally:
        reopened.close()


def test_queue_receipt_write_failure_keeps_sender_unentered(tmp_path):
    store, authority, scope, lease = _open(tmp_path / "receipt-failure.sqlite3")
    try:
        order = _seed_order(authority, scope, lease)
        action = _reserve_action(authority, scope, lease, order)
        prepared = _prepared(order)
        worker = CtpManagedSingleWorkerCandidate(store, scope, lease, authority)
        binding = worker.stage_prepared_dispatch(
            prepared,
            cancel_target_projection=_target_projection(store, order, prepared),
            action_identity=action,
        )
        command = store.read_ctp_dispatch_command(scope, prepared.command_id)
        assert command is not None
        store._connection.execute(
            """CREATE TRIGGER reject_g5_queue_receipt
               BEFORE UPDATE OF queue_receipt_json ON g5_ctp_worker_handoffs
               BEGIN SELECT RAISE(ABORT, 'receipt persistence rejected'); END"""
        )
        with pytest.raises(DurableStoreError, match="transaction failed"):
            worker.record_managed_queue_receipt(
                prepared.command_id, binding, _queue(binding, command)
            )
        calls = []
        with pytest.raises(ContractValidationError, match="not durably accepted"):
            worker.dispatch_managed_command(
                prepared.command_id, binding, lambda value: calls.append(value)
            )
        assert calls == []
        durable = store.read_ctp_dispatch_command(scope, prepared.command_id)
        assert durable is not None and durable.status == "READY"
    finally:
        store.close()
