"""Fake-only source contract tests for the unregistered CTP parent DTO builder."""

from __future__ import annotations

import hashlib
import importlib
from importlib.metadata import PackageNotFoundError, version
import json
from dataclasses import replace

import pytest

from backtrader.stores.ctp_i9_managed_dispatch import CtpI9ManagedDispatchBridge
from backtrader.stores.ctp_i9_parent_request_builder import (
    CtpI9ParentRequestBuilder,
    CtpI9ParentRequestBuilderError,
)


def _candidate_modules():
    try:
        if version("bt_api_execution") != "0.2.0" or version("bt_api_py") != "0.15.5":
            pytest.skip("fixed I9 0.2.0 and parent 0.15.5 source-only candidates are required")
    except PackageNotFoundError:
        pytest.skip("fixed I9 and parent source-only candidates are not on PYTHONPATH")
    return (
        importlib.import_module("bt_api_execution"),
        importlib.import_module("bt_api_execution.store"),
        importlib.import_module("bt_api_execution.ctp_single_worker_candidate"),
        importlib.import_module("bt_api_py.bt_api"),
        importlib.import_module("bt_api_py._contracts.models"),
        importlib.import_module("bt_api_py._execution_session"),
    )


class _OfflineAuthorityVerifier:
    """Test-only approval echo for I9 staging; it cannot call a sender."""

    def verify_action(self, command, *, now_ns):
        execution = importlib.import_module("bt_api_execution")
        return execution.CtpDispatchAuthority(
            authority_type="ctp_dispatch_authority.v1",
            command_binding_sha256=command.authority_binding_sha256,
            approval_use_id=command.approval_use_id,
            approval_digest=command.approval_digest,
            source_digest_sha256=hashlib.sha256(b"fake-builder-test").hexdigest(),
            verifier_id="fake-builder-test-verifier",
            verified_at_ns=now_ns,
            expires_at_ns=now_ns + 5_000_000_000,
        )


class _FakeParentSession:
    """Exact parent facade delegate with a test-local identity journal echo."""

    def __init__(self, store, scope, model_module, session_module):
        self.store = store
        self.scope = scope
        self.models = model_module
        self.session_models = session_module
        self.calls = []

    def consume_ctp_order_identity_reservation(
        self, exchange_name, *, scope, identity_store, managed_intent_id, runtime_order_id
    ):
        assert exchange_name == "CTP___FUTURE"
        assert scope is self.scope and identity_store is self.store
        row = self.store.read_ctp_order_identity(scope, managed_intent_id)
        assert row is not None and row.runtime_order_id == runtime_order_id
        self.calls.append(("order_mirror", managed_intent_id, runtime_order_id))
        return self.session_models.CtpOrderIdentityReservationMirror(
            account_key=row.account_key,
            trading_day=row.trading_day,
            scope_key=row.scope_key,
            managed_intent_id=row.managed_intent_id,
            runtime_order_id=row.runtime_order_id,
            order_ref=row.order_ref,
            created_at_ns=row.created_at_ns,
        )

    def consume_ctp_cancel_dispatch_command(
        self, exchange_name, *, scope, identity_store, command_id, request
    ):
        assert exchange_name == "CTP___FUTURE"
        assert scope is self.scope and identity_store is self.store
        assert request.ctp_cancel_identity is None
        command = self.store.read_ctp_dispatch_command(scope, command_id)
        projection = self.store.read_ctp_dispatch_projection(scope, command_id)
        assert command is not None and command.status == "READY"
        assert projection.cancel_action is not None
        correlation = command.correlation_key
        self.calls.append(("cancel_echo", command_id))
        return self.models.CtpCancelIdentityBinding(
            version=2,
            environment=scope.environment,
            account_id=scope.account_ref,
            instrument_id=request.symbol,
            account_key=command.account_key,
            trading_day=command.trading_day,
            scope_key=command.scope_key,
            managed_intent_id=correlation.reservation_managed_intent_id,
            runtime_order_id=correlation.runtime_order_id,
            order_ref=correlation.order_ref,
            command_id=command.command_id,
            request_payload_sha256=command.request_payload_sha256,
            managed_action_id=correlation.managed_action_id,
            approval_use_id=command.approval_use_id,
            approval_digest=command.approval_digest,
            session_binding_sha256=command.session_binding_sha256,
            session_generation_id=correlation.session_generation_id,
            dispatch_front_id=correlation.dispatch_front_id,
            dispatch_session_id=correlation.dispatch_session_id,
            native_request_id=correlation.native_request_id,
            native_action_ref=correlation.native_action_ref,
            cancel_target_order_ref=command.cancel_target_order_ref,
            cancel_target_exchange_id=command.cancel_target_exchange_id,
            cancel_target_order_sys_id=command.cancel_target_order_sys_id,
            cancel_target_front_id=command.cancel_target_front_id,
            cancel_target_session_id=command.cancel_target_session_id,
            native_request_payload_sha256=command.native_request_payload_sha256,
        )


def _candidate(tmp_path, suffix="main"):
    execution, store_module, worker_module, api_module, models, session_models = (
        _candidate_modules()
    )
    scope = execution.ExecutionScope(
        "CTP", "simulation", "acct.i9.builder." + suffix, "strategy.i9.builder", "20260926"
    )
    store = store_module.SqliteExecutionStore(tmp_path / ("i9-" + suffix + ".sqlite3"))
    lease = store.acquire_or_renew_lease(scope, "fake-builder-owner-" + suffix)
    source_digests = (
        ("backtrader_prototype", hashlib.sha256((suffix + "-a").encode()).hexdigest()),
        ("sdk_jsonl", hashlib.sha256((suffix + "-b").encode()).hexdigest()),
    )
    legacy_scope = execution.ExecutionScope(
        "CTP", "simulation", scope.account_ref, "strategy.legacy", "20260925"
    )
    legacy_mapping = execution.CtpOrderRefLegacyMapping(
        source_name="backtrader_prototype",
        account_key=scope.account_key,
        trading_day="20260925",
        scope_key=legacy_scope.key,
        managed_intent_id="legacy.intent." + suffix,
        runtime_order_id="legacy.runtime." + suffix,
        order_ref="000000000012",
    )
    proof = execution.CtpOrderRefSeedProof(
        trading_day=scope.trading_day,
        native_max_order_ref="000000000010",
        legacy_ledger_max_order_ref="000000000012",
        legacy_ledger_sha256=execution.payload_sha256(dict(source_digests)),
        account_key=scope.account_key,
        scope_key=scope.key,
        session_generation_id="generation.fake." + suffix,
        native_front_id=4,
        native_session_id=91,
        existing_native_order_refs=("000000000009", "000000000010"),
        legacy_source_sha256=source_digests,
        legacy_mappings=(legacy_mapping,),
    )
    intent = "intent.i9.builder." + suffix
    runtime_order_id = "bt-managed-v1:" + hashlib.sha256(intent.encode("ascii")).hexdigest()
    reservation = store.seed_ctp_order_ref_and_reserve_identity(
        scope, proof, intent, runtime_order_id, writer_lease=lease
    )
    worker = worker_module.CtpManagedSingleWorkerCandidate(
        store, scope, lease, _OfflineAuthorityVerifier()
    )
    bridge = CtpI9ManagedDispatchBridge(scope=scope, identity_port=store, single_worker=worker)
    api = object.__new__(api_module.BtApi)
    parent_session = _FakeParentSession(store, scope, models, session_models)
    api._execution_session = parent_session
    builder = CtpI9ParentRequestBuilder(
        bridge=bridge,
        parent_api=api,
        exchange_name="CTP___FUTURE",
    )
    return {
        "execution": execution,
        "store_module": store_module,
        "worker_module": worker_module,
        "models": models,
        "scope": scope,
        "store": store,
        "worker": worker,
        "bridge": bridge,
        "builder": builder,
        "parent_session": parent_session,
        "reservation": reservation,
        "intent": intent,
        "runtime_order_id": runtime_order_id,
    }


def _session_binding():
    return {
        "session_identity": "opaque.fake.session",
        "session_generation_id": "generation.fake.main",
        "dispatch_front_id": 4,
        "dispatch_session_id": 91,
    }


def _submit_payload(order_ref, **changes):
    payload = {
        "BrokerID": "9999",
        "InvestorID": "fake-user",
        "UserID": "fake-user",
        "InstrumentID": "rb2710",
        "ExchangeID": "SHFE",
        "OrderRef": order_ref,
        "OrderPriceType": "2",
        "Direction": "0",
        "CombOffsetFlag": "0",
        "CombHedgeFlag": "2",
        "LimitPrice": 100.0,
        "VolumeTotalOriginal": 1,
        "TimeCondition": "3",
        "VolumeCondition": "1",
        "MinVolume": 1,
        "ContingentCondition": "1",
        "StopPrice": 0.0,
        "ForceCloseReason": "0",
        "IsAutoSuspend": 0,
        "UserForceClose": 0,
        "RequestID": 101,
    }
    payload.update(changes)
    return payload


def _prepared_submit(candidate, payload=None, *, intent=None, runtime_order_id=None):
    worker_module = candidate["worker_module"]
    reservation = candidate["reservation"]
    intent = intent or candidate["intent"]
    runtime_order_id = runtime_order_id or candidate["runtime_order_id"]
    return worker_module.CtpManagedPreparedDispatch(
        operation="submit",
        command_id=worker_module.stable_managed_command_id(
            "submit", intent, runtime_order_id, None
        ),
        managed_intent_id=intent,
        runtime_order_id=runtime_order_id,
        order_ref=reservation.order_ref,
        request_payload=payload or _submit_payload(reservation.order_ref),
        order_ref_reservation=reservation,
        approval_use_id="approval.fake.submit." + intent,
        approval_digest=hashlib.sha256(("approval:" + intent).encode()).hexdigest(),
        session_binding=_session_binding(),
        session_generation_id="generation.fake.main",
        dispatch_front_id=4,
        dispatch_session_id=91,
        native_request_id=101,
        local_queue_receipt_id=hashlib.sha256(("receipt:" + intent).encode()).hexdigest()[:32],
    )


def test_submit_builder_stages_exact_payload_and_returns_non_dispatch_parent_echo(
    tmp_path, monkeypatch
):
    candidate = _candidate(tmp_path)
    sender_calls = []
    monkeypatch.setattr(
        candidate["worker"],
        "dispatch_managed_command",
        lambda *_args, **_kwargs: sender_calls.append("dispatch"),
    )
    prepared = _prepared_submit(candidate)

    contract = candidate["builder"].build_submit_request(
        prepared, canonical_facts=dict(prepared.request_payload)
    )

    command = candidate["store"].read_ctp_dispatch_command(candidate["scope"], prepared.command_id)
    assert contract.operation == "submit"
    assert contract.dispatch_authorized is False
    assert contract.prepared_dispatch.command_id == prepared.command_id
    assert contract.i9_dispatch_binding.command_id == prepared.command_id
    assert contract.i9_dispatch_binding.request_payload_sha256 == contract.request_payload_sha256
    assert command.status == "READY"
    assert command.local_queue_receipt_queued is None
    assert dict(command.request_payload) == dict(prepared.request_payload)
    assert contract.parent_request.client_order_id == candidate["reservation"].order_ref
    assert contract.parent_request.ctp_order_identity.managed_intent_id == candidate["intent"]
    assert contract.parent_request.ctp_order_identity.dispatch_authorized is False
    assert contract.parent_request.quantity == 1
    assert contract.parent_request.offset == "open"
    canonical = json.loads(contract.canonical_request_payload_json)
    assert canonical["CombHedgeFlag"] == "2"
    assert candidate["parent_session"].calls == [
        ("order_mirror", candidate["intent"], candidate["runtime_order_id"])
    ]
    assert sender_calls == []
    candidate["store"].close()


def test_submit_builder_rejects_typed_staged_row_with_changed_approval_correlation(
    tmp_path, monkeypatch
):
    candidate = _candidate(tmp_path)
    prepared = _prepared_submit(candidate)
    store_type = type(candidate["store"])
    original_read = store_type.read_ctp_dispatch_command
    reads = 0
    changed_digest = hashlib.sha256(b"different approval echo").hexdigest()

    def tamper_final_readback(store, scope, command_id):
        nonlocal reads
        row = original_read(store, scope, command_id)
        if command_id == prepared.command_id:
            reads += 1
            # The bridge reads once while staging. Tamper only the builder's
            # subsequent final readback, while keeping the command and its
            # typed correlation mutually consistent.
            if reads == 2:
                return replace(
                    row,
                    approval_digest=changed_digest,
                    correlation_key=replace(
                        row.correlation_key,
                        approval_digest=changed_digest,
                    ),
                )
        return row

    monkeypatch.setattr(store_type, "read_ctp_dispatch_command", tamper_final_readback)
    with pytest.raises(CtpI9ParentRequestBuilderError, match="staging/readback failed"):
        candidate["builder"].build_submit_request(
            prepared, canonical_facts=dict(prepared.request_payload)
        )

    command = original_read(candidate["store"], candidate["scope"], prepared.command_id)
    assert reads == 2
    assert command is not None and command.status == "READY"
    assert command.local_queue_receipt_queued is None
    assert candidate["parent_session"].calls == []
    candidate["store"].close()


def test_submit_builder_rejects_payload_mismatch_and_invalid_native_schema_before_stage(tmp_path):
    candidate = _candidate(tmp_path)
    prepared = _prepared_submit(candidate)
    changed_facts = dict(prepared.request_payload)
    changed_facts["LimitPrice"] = 101.0
    with pytest.raises(CtpI9ParentRequestBuilderError, match="canonical facts differ"):
        candidate["builder"].build_submit_request(prepared, canonical_facts=changed_facts)
    assert (
        candidate["store"].read_ctp_dispatch_command(candidate["scope"], prepared.command_id)
        is None
    )

    malformed = _prepared_submit(
        candidate,
        payload=_submit_payload(candidate["reservation"].order_ref, CombHedgeFlag=True),
    )
    with pytest.raises(CtpI9ParentRequestBuilderError, match="schema has invalid CombHedgeFlag"):
        candidate["builder"].build_submit_request(
            malformed, canonical_facts=dict(malformed.request_payload)
        )
    assert (
        candidate["store"].read_ctp_dispatch_command(candidate["scope"], malformed.command_id)
        is None
    )
    assert candidate["parent_session"].calls == []

    changed_hedge = _prepared_submit(
        candidate,
        payload=_submit_payload(candidate["reservation"].order_ref, CombHedgeFlag="3"),
    )
    old_hedge_facts = dict(changed_hedge.request_payload)
    old_hedge_facts["CombHedgeFlag"] = "2"
    with pytest.raises(CtpI9ParentRequestBuilderError, match="canonical facts differ"):
        candidate["builder"].build_submit_request(changed_hedge, canonical_facts=old_hedge_facts)
    assert (
        candidate["store"].read_ctp_dispatch_command(candidate["scope"], changed_hedge.command_id)
        is None
    )

    wrong_ref_payload = _submit_payload(
        "000000000099",
    )
    wrong_ref = _prepared_submit(candidate, payload=wrong_ref_payload)
    with pytest.raises(CtpI9ParentRequestBuilderError, match="OrderRef differs from reservation"):
        candidate["builder"].build_submit_request(
            wrong_ref, canonical_facts=dict(wrong_ref.request_payload)
        )
    assert (
        candidate["store"].read_ctp_dispatch_command(candidate["scope"], wrong_ref.command_id)
        is None
    )
    candidate["store"].close()


def test_submit_builder_rejects_row_from_another_i9_store(tmp_path):
    candidate = _candidate(tmp_path, "owner")
    other = _candidate(tmp_path, "other")
    prepared = _prepared_submit(candidate)
    with pytest.raises(CtpI9ParentRequestBuilderError, match="reservation readback differs"):
        other["builder"].build_submit_request(
            prepared, canonical_facts=dict(prepared.request_payload)
        )
    assert other["store"].read_ctp_dispatch_command(other["scope"], prepared.command_id) is None
    assert other["parent_session"].calls == []
    candidate["store"].close()
    other["store"].close()


def test_submit_builder_detaches_canonical_facts_before_stage_mutation(tmp_path, monkeypatch):
    candidate = _candidate(tmp_path)
    prepared = _prepared_submit(candidate)
    facts = dict(prepared.request_payload)
    stage = candidate["bridge"].stage_prepared_dispatch

    def mutate_caller_facts_then_stage(detached):
        facts["InstrumentID"] = "caller-mutated-after-check"
        return stage(detached)

    monkeypatch.setattr(
        candidate["bridge"], "stage_prepared_dispatch", mutate_caller_facts_then_stage
    )
    contract = candidate["builder"].build_submit_request(prepared, canonical_facts=facts)
    command = candidate["store"].read_ctp_dispatch_command(candidate["scope"], prepared.command_id)
    assert command.request_payload["InstrumentID"] == "rb2710"
    assert json.loads(contract.canonical_request_payload_json)["InstrumentID"] == "rb2710"
    assert contract.request_payload_sha256 == command.request_payload_sha256
    candidate["store"].close()


class _FakeTargetVerifier:
    def __init__(self, projection_type, overrides=None):
        self.projection_type = projection_type
        self.overrides = dict(overrides or {})

    def verify_order_target(self, scope, reservation, evidence, *, now_ns):
        assert evidence == {"test_only": True}
        digest = hashlib.sha256(b"fake-target-evidence").hexdigest()
        values = {
            "account_key": reservation.account_key,
            "scope_key": reservation.scope_key,
            "trading_day": reservation.trading_day,
            "managed_intent_id": reservation.managed_intent_id,
            "runtime_order_id": reservation.runtime_order_id,
            "order_ref": reservation.order_ref,
            "account_fingerprint_sha256": digest,
            "registration_digest": digest,
            "instrument_id": "rb2710",
            "exchange_id": "SHFE",
            "session_generation_id": "generation.fake.main",
            "connection_generation": 1,
            "query_front_id": 4,
            "query_session_id": 91,
            "query_request_id": 202,
            "query_filters_sha256": digest,
            "query_records_sha256": digest,
            "source_evidence_sha256": digest,
            "query_record_count": 1,
            "query_match_count": 1,
            "query_complete": True,
            "query_terminal": True,
            "query_timed_out": False,
            "query_error_id": 0,
            "late_callback_count": 0,
            "order_sys_id": "native-sys-2710",
            "front_id": 8,
            "session_id": 13,
            "provider_state": "OPEN",
            "quantity": 1,
            "traded_quantity": 0,
            "remaining_quantity": 1,
            "verifier_id": "test-only-fake-target-verifier",
            "verified_at_ns": now_ns,
            "expires_at_ns": now_ns + 2_000_000_000,
        }
        values.update(self.overrides)
        return self.projection_type(**values)


class _FakeCallbackVerifier:
    """Test-only callback evidence; it performs no provider or SDK access."""

    def __init__(self, execution, projection_state):
        self.execution = execution
        self.projection_state = projection_state

    def verify_callback(self, command, callback, callback_payload, *, now_ns):
        return self.execution.CtpVerifiedCallbackEvidence(
            evidence_type="ctp_verified_callback.v1",
            callback_key=callback,
            callback_payload_sha256=self.execution.payload_sha256(callback_payload),
            projection_state=self.projection_state,
            source_digest_sha256=hashlib.sha256(b"fake callback source").hexdigest(),
            verifier_id="test-only-fake-callback-verifier",
            verified_at_ns=now_ns,
            expires_at_ns=now_ns + 5_000_000_000,
        )


def _persist_fake_submit_order_projection(candidate, prepared, projection_state):
    """Create an I9 callback projection using local SQLite APIs only."""

    execution = candidate["execution"]
    store = candidate["store"]
    scope = candidate["scope"]
    command = store.read_ctp_dispatch_command(scope, prepared.command_id)
    assert command is not None and command.status == "READY"
    store.record_ctp_dispatch_queue_receipt(
        scope,
        prepared.command_id,
        {
            "kind": "command_receipt",
            "command": "submit",
            "receipt_id": prepared.local_queue_receipt_id,
            "queued": True,
        },
        writer_lease=candidate["worker"]._writer_lease,
    )
    claimed = store.claim_ctp_dispatch_command(
        scope,
        prepared.command_id,
        writer_lease=candidate["worker"]._writer_lease,
        authority_verifier=_OfflineAuthorityVerifier(),
    )
    assert claimed is not None and claimed.status == "CLAIMED"
    store.complete_ctp_dispatch_command(
        scope,
        execution.CtpDispatchReceipt(
            receipt_type="ctp_dispatch_receipt.v2",
            command_id=claimed.command_id,
            account_key=claimed.account_key,
            scope_key=claimed.scope_key,
            trading_day=claimed.trading_day,
            operation=claimed.operation,
            request_payload_sha256=claimed.request_payload_sha256,
            reservation_managed_intent_id=claimed.reservation_managed_intent_id,
            order_ref=claimed.order_ref,
            cancel_target_order_ref=claimed.cancel_target_order_ref,
            cancel_target_exchange_id=claimed.cancel_target_exchange_id,
            cancel_target_order_sys_id=claimed.cancel_target_order_sys_id,
            cancel_target_front_id=claimed.cancel_target_front_id,
            cancel_target_session_id=claimed.cancel_target_session_id,
            approval_use_id=claimed.approval_use_id,
            approval_digest=claimed.approval_digest,
            session_binding_sha256=claimed.session_binding_sha256,
            outcome="QUEUED",
            native_receipt_payload={"queue_code": 0},
            correlation_key=claimed.correlation_key,
            local_queue_receipt_id=claimed.local_queue_receipt_id,
        ),
        writer_lease=candidate["worker"]._writer_lease,
    )
    callback = execution.CtpDispatchCallbackKey(
        version=claimed.correlation_key.version,
        correlation_key=claimed.correlation_key,
        callback_family="ORDER",
        stream_id="fake-test-td-callback-stream",
        event_id="fake-test-submit-order-event",
        native_request_id=claimed.correlation_key.native_request_id,
        native_action_ref=claimed.correlation_key.native_action_ref,
        order_ref=claimed.correlation_key.order_ref,
    )
    store.apply_ctp_verified_dispatch_callback(
        scope,
        claimed.command_id,
        callback,
        {"event": "fake-order-callback"},
        writer_lease=candidate["worker"]._writer_lease,
        callback_verifier=_FakeCallbackVerifier(execution, projection_state),
    )


def _prepared_cancel(candidate, *, cancel_suffix=None, request_id=102):
    worker_module = candidate["worker_module"]
    reservation = candidate["reservation"]
    intent = candidate["intent"]
    runtime_order_id = candidate["runtime_order_id"]
    cancel_intent = cancel_suffix or ("cancel." + intent)
    payload = {
        "InstrumentID": "rb2710",
        "OrderRef": reservation.order_ref,
        "ExchangeID": "SHFE",
        "OrderSysID": "native-sys-2710",
        "FrontID": 8,
        "SessionID": 13,
        "ActionFlag": "0",
        "LimitPrice": 0,
        "VolumeChange": 0,
        "RequestID": request_id,
    }
    return worker_module.CtpManagedPreparedDispatch(
        operation="cancel",
        command_id=worker_module.stable_managed_command_id(
            "cancel", intent, runtime_order_id, cancel_intent
        ),
        managed_intent_id=intent,
        runtime_order_id=runtime_order_id,
        order_ref=reservation.order_ref,
        request_payload=payload,
        order_ref_reservation=reservation,
        approval_use_id="approval.fake.cancel." + intent,
        approval_digest=hashlib.sha256(("cancel-approval:" + intent).encode()).hexdigest(),
        session_binding=_session_binding(),
        session_generation_id="generation.fake.main",
        dispatch_front_id=4,
        dispatch_session_id=91,
        native_request_id=request_id,
        local_queue_receipt_id=hashlib.sha256(
            ("cancel-receipt:" + cancel_intent).encode()
        ).hexdigest()[:32],
        managed_cancel_intent_id=cancel_intent,
        cancel_target_exchange_id="SHFE",
        cancel_target_order_sys_id="native-sys-2710",
        cancel_target_front_id=8,
        cancel_target_session_id=13,
    )


def test_cancel_builder_requires_fake_only_fresh_same_store_target_and_stays_unqueued(
    tmp_path, monkeypatch
):
    candidate = _candidate(tmp_path)
    prepared = _prepared_cancel(candidate)
    payload = dict(prepared.request_payload)
    with pytest.raises(candidate["execution"].ContractValidationError, match="verification failed"):
        candidate["store"].issue_ctp_order_target_projection(
            candidate["scope"], candidate["intent"], {"test_only": True}
        )
    with pytest.raises(CtpI9ParentRequestBuilderError, match="fresh same-store"):
        candidate["builder"].build_cancel_request(
            prepared, canonical_facts=payload, target_handle=object()
        )
    assert (
        candidate["store"].read_ctp_dispatch_command(candidate["scope"], prepared.command_id)
        is None
    )

    projection_type = importlib.import_module(
        "bt_api_execution.store"
    ).CtpVerifiedOrderTargetProjection
    target = candidate["store"].issue_ctp_order_target_projection(
        candidate["scope"],
        candidate["intent"],
        {"test_only": True},
        verifier=_FakeTargetVerifier(projection_type),
    )
    sender_calls = []
    monkeypatch.setattr(
        candidate["worker"],
        "dispatch_managed_command",
        lambda *_args, **_kwargs: sender_calls.append("dispatch"),
    )
    contract = candidate["builder"].build_cancel_request(
        prepared,
        canonical_facts=payload,
        target_handle=target,
    )
    command = candidate["store"].read_ctp_dispatch_command(candidate["scope"], prepared.command_id)
    assert contract.dispatch_authorized is False
    assert contract.operation == "cancel"
    assert contract.parent_request.ctp_cancel_identity.dispatch_authorized is False
    assert contract.parent_request.ctp_cancel_identity.command_id == prepared.command_id
    assert contract.parent_request.order_id == "native-sys-2710"
    assert contract.parent_request.client_order_id == candidate["reservation"].order_ref
    assert command.status == "READY"
    assert command.local_queue_receipt_queued is None
    assert candidate["parent_session"].calls == [
        ("order_mirror", candidate["intent"], candidate["runtime_order_id"]),
        ("cancel_echo", prepared.command_id),
    ]
    assert sender_calls == []

    replay = _prepared_cancel(
        candidate,
        cancel_suffix="cancel.replay." + candidate["intent"],
        request_id=103,
    )
    with pytest.raises(CtpI9ParentRequestBuilderError, match="I9 cancel staging/readback"):
        candidate["builder"].build_cancel_request(
            replay,
            canonical_facts=dict(replay.request_payload),
            target_handle=target,
        )
    assert (
        candidate["store"].read_ctp_dispatch_command(candidate["scope"], replay.command_id) is None
    )
    assert command.local_queue_receipt_queued is None
    assert sender_calls == []
    candidate["store"].close()


@pytest.mark.parametrize(
    ("order_projection_state", "target_provider_state", "target_quantity", "traded"),
    [
        ("ACKNOWLEDGED", "OPEN", 1, 0),
        ("PARTIALLY_FILLED", "PARTIAL", 2, 1),
    ],
)
def test_cancel_builder_accepts_persisted_nonterminal_order_state_matching_fresh_target(
    tmp_path, monkeypatch, order_projection_state, target_provider_state, target_quantity, traded
):
    candidate = _candidate(tmp_path)
    submit = _prepared_submit(candidate)
    candidate["builder"].build_submit_request(submit, canonical_facts=dict(submit.request_payload))
    _persist_fake_submit_order_projection(candidate, submit, order_projection_state)
    prepared = _prepared_cancel(candidate)
    target_store_type = importlib.import_module("bt_api_execution.store")
    target = candidate["store"].issue_ctp_order_target_projection(
        candidate["scope"],
        candidate["intent"],
        {"test_only": True},
        verifier=_FakeTargetVerifier(
            target_store_type.CtpVerifiedOrderTargetProjection,
            {
                "provider_state": target_provider_state,
                "quantity": target_quantity,
                "traded_quantity": traded,
                "remaining_quantity": target_quantity - traded,
            },
        ),
    )
    sender_calls = []
    monkeypatch.setattr(
        candidate["worker"],
        "dispatch_managed_command",
        lambda *_args, **_kwargs: sender_calls.append("dispatch"),
    )

    contract = candidate["builder"].build_cancel_request(
        prepared,
        canonical_facts=dict(prepared.request_payload),
        target_handle=target,
    )

    projection = candidate["store"].read_ctp_dispatch_projection(
        candidate["scope"], prepared.command_id
    )
    assert contract.dispatch_authorized is False
    assert (
        projection.cancel_action.target_order.order_state.provider_state == order_projection_state
    )
    assert projection.cancel_action.target_order.order_state.terminal is False
    assert sender_calls == []
    assert candidate["parent_session"].calls[-1] == ("cancel_echo", prepared.command_id)
    candidate["store"].close()


@pytest.mark.parametrize(
    "order_projection_state",
    ["FILLED", "PARTIALLY_FILLED"],
)
def test_cancel_builder_rejects_terminal_or_contradictory_persisted_order_state(
    tmp_path, order_projection_state
):
    candidate = _candidate(tmp_path)
    submit = _prepared_submit(candidate)
    candidate["builder"].build_submit_request(submit, canonical_facts=dict(submit.request_payload))
    _persist_fake_submit_order_projection(candidate, submit, order_projection_state)
    prepared = _prepared_cancel(candidate)
    target_store_type = importlib.import_module("bt_api_execution.store")
    target = candidate["store"].issue_ctp_order_target_projection(
        candidate["scope"],
        candidate["intent"],
        {"test_only": True},
        verifier=_FakeTargetVerifier(target_store_type.CtpVerifiedOrderTargetProjection),
    )
    with pytest.raises(CtpI9ParentRequestBuilderError, match="terminal|conflicts"):
        candidate["builder"].build_cancel_request(
            prepared,
            canonical_facts=dict(prepared.request_payload),
            target_handle=target,
        )
    assert candidate["parent_session"].calls == [
        ("order_mirror", candidate["intent"], candidate["runtime_order_id"])
    ]
    assert (
        candidate["store"].read_ctp_dispatch_command(candidate["scope"], prepared.command_id).status
        == "READY"
    )
    candidate["store"].close()


def test_cancel_builder_rejects_typed_staged_row_with_changed_approval_correlation(
    tmp_path, monkeypatch
):
    candidate = _candidate(tmp_path)
    prepared = _prepared_cancel(candidate)
    projection_type = importlib.import_module(
        "bt_api_execution.store"
    ).CtpVerifiedOrderTargetProjection
    target = candidate["store"].issue_ctp_order_target_projection(
        candidate["scope"],
        candidate["intent"],
        {"test_only": True},
        verifier=_FakeTargetVerifier(projection_type),
    )
    store_type = type(candidate["store"])
    original_read = store_type.read_ctp_dispatch_command
    changed_digest = hashlib.sha256(b"different cancel approval echo").hexdigest()

    def tamper_final_readback(store, scope, command_id):
        row = original_read(store, scope, command_id)
        if command_id == prepared.command_id and row is not None:
            return replace(
                row,
                approval_digest=changed_digest,
                correlation_key=replace(
                    row.correlation_key,
                    approval_digest=changed_digest,
                ),
            )
        return row

    monkeypatch.setattr(store_type, "read_ctp_dispatch_command", tamper_final_readback)
    with pytest.raises(CtpI9ParentRequestBuilderError, match="I9 cancel staging/readback"):
        candidate["builder"].build_cancel_request(
            prepared,
            canonical_facts=dict(prepared.request_payload),
            target_handle=target,
        )

    command = original_read(candidate["store"], candidate["scope"], prepared.command_id)
    assert command is not None and command.status == "READY"
    assert command.local_queue_receipt_queued is None
    assert candidate["parent_session"].calls == []
    candidate["store"].close()


def test_cancel_builder_rejects_same_store_handle_for_another_reservation(tmp_path):
    candidate = _candidate(tmp_path)
    other_intent = "intent.i9.builder.other-target"
    other_runtime = "bt-managed-v1:" + hashlib.sha256(other_intent.encode()).hexdigest()
    other_reservation = candidate["store"].reserve_ctp_order_identity(
        candidate["scope"], other_intent, other_runtime
    )
    prepared = _prepared_cancel(candidate)
    projection_type = importlib.import_module(
        "bt_api_execution.store"
    ).CtpVerifiedOrderTargetProjection
    target_for_other_row = candidate["store"].issue_ctp_order_target_projection(
        candidate["scope"],
        other_intent,
        {"test_only": True},
        verifier=_FakeTargetVerifier(projection_type),
    )
    assert target_for_other_row.projection.order_ref == other_reservation.order_ref
    with pytest.raises(CtpI9ParentRequestBuilderError, match="differs from prepared cancel action"):
        candidate["builder"].build_cancel_request(
            prepared,
            canonical_facts=dict(prepared.request_payload),
            target_handle=target_for_other_row,
        )
    assert (
        candidate["store"].read_ctp_dispatch_command(candidate["scope"], prepared.command_id)
        is None
    )
    assert candidate["parent_session"].calls == []
    candidate["store"].close()
