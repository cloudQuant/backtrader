"""Opt-in composition of the I9 outbox, SDK ingress, and session claim.

This candidate is deliberately unregistered. It accepts only the exact
source-candidate Store, worker, adapter, and SDK types. It creates the durable
callback owner before constructing the client, installs the fixed ingress
ports before supervised start, and never calls a native request without a
Store-issued session claim and SDK lease.

There is no production lifecycle supervisor in this repository. Callers must
provide an explicitly reviewed supervisor implementation; tests use a
fake-only implementation. This in-process composition is not a boundary
against hostile Python code and does not authorize a provider account.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable


class CtpI9AccountSessionCandidateError(RuntimeError):
    """Fixed, redacted failure from the opt-in session composition."""


@dataclass(frozen=True)
class CtpI9DispatchDeferred:
    """A claim was proven not to commit and its exact READY item remains queued."""

    command_id: str
    reason: str = "claim_not_committed"


class CtpI9NativeLifecycleSupervisor(ABC):
    """Explicit lifecycle seam; this project supplies no real implementation."""

    @abstractmethod
    def start_client(self, client: Any) -> None:
        """Start and supervise one client, returning only after readiness."""

    @abstractmethod
    def stop_client(self, client: Any) -> None:
        """Stop and supervise one client within the implementation's bound."""


def _native_field_after_admission(candidate: Any, binding: Any, payload: Mapping[str, Any]) -> Any:
    """Run the CANCEL final gate before allowing native action field creation."""

    if binding.operation == "CANCEL":
        if not callable(candidate._native_call_admission):
            raise CtpI9AccountSessionCandidateError("CANCEL requires final native-call admission")
        # The client's lease acquisition repeats this gate at the SDK boundary,
        # so a change between these checks still fails closed before ReqOrderAction.
        candidate._verify_native_call(candidate._owner, binding)
    return candidate._native_field_factory(binding.operation, MappingProxyType(dict(payload)))


def _trusted_candidate_types() -> tuple[type, ...] | None:
    """Load only the reviewed local source-candidate API versions."""

    if sys.version_info < (3, 11):
        return None
    try:
        import bt_api_ctp
        import bt_api_execution

        if _candidate_package_version("bt_api_execution", bt_api_execution) != "0.2.0":
            return None
        if _candidate_package_version("bt_api_ctp", bt_api_ctp) != "2.0.4+iteration41.i9":
            return None
        from bt_api_execution.contracts import ExecutionScope
        from bt_api_execution.ctp_callback_session import CtpCallbackSessionStoreAdapter
        from bt_api_execution.ctp_single_worker_candidate import (
            CtpManagedPreparedDispatch,
            CtpManagedSingleWorkerCandidate,
        )
        from bt_api_execution.store import (
            CtpCallbackSessionBindingV1,
            CtpCallbackSessionOwnerHandle,
            CtpCallbackSessionPoisonCommit,
            CtpDispatchCommand,
            CtpDispatchReceipt,
            CtpManagedNativeCallBindingV2,
            CtpSessionNativeCallClaim,
            CtpTraderCallbackIngressPoisonAckV2,
            CtpVerifiedOrderTargetProjection,
            CtpOrderTargetProjectionHandle,
            SqliteExecutionStore,
            WriterLease,
        )
        from bt_api_ctp.ctp.callback_ingress import (
            CtpTraderCallbackIngressAckV2,
            CtpTraderCallbackIngressRecordV2,
        )
        from bt_api_ctp.ctp.client import TraderClient
    except Exception:
        return None
    return (
        ExecutionScope,
        SqliteExecutionStore,
        WriterLease,
        CtpManagedSingleWorkerCandidate,
        CtpManagedPreparedDispatch,
        CtpCallbackSessionStoreAdapter,
        CtpCallbackSessionOwnerHandle,
        CtpCallbackSessionBindingV1,
        CtpDispatchReceipt,
        CtpManagedNativeCallBindingV2,
        CtpSessionNativeCallClaim,
        CtpVerifiedOrderTargetProjection,
        CtpOrderTargetProjectionHandle,
        CtpTraderCallbackIngressAckV2,
        CtpTraderCallbackIngressRecordV2,
        TraderClient,
        CtpDispatchCommand,
        CtpCallbackSessionPoisonCommit,
        CtpTraderCallbackIngressPoisonAckV2,
    )


def _candidate_package_version(package_name: str, module: Any) -> str | None:
    """Read the exact version declared by an adjacent source-candidate pyproject."""

    if sys.version_info < (3, 11):
        return None
    import tomllib

    source = getattr(module, "__file__", None)
    if type(source) is str:
        project_file = Path(source).resolve().parents[2] / "pyproject.toml"
        try:
            project = tomllib.loads(project_file.read_text(encoding="utf-8"))["project"]
        except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
            project = None
        if isinstance(project, Mapping) and project.get("name") == package_name:
            project_version = project.get("version")
            return project_version if type(project_version) is str else None
    return None


def _session_payload(binding: Any) -> dict[str, Any]:
    """Snapshot the exact Store-issued active session without adding authority."""

    names = (
        "owner_intent_id",
        "account_key",
        "scope_key",
        "trading_day",
        "session_generation_id",
        "dispatch_front_id",
        "dispatch_session_id",
        "source_instance_id",
        "native_client_epoch",
        "native_api_source_id",
        "native_spi_source_id",
        "native_api_generation",
        "source_connection_generation",
        "connection_generation",
        "source_high_watermark",
        "session_binding_sha256",
    )
    return {name: getattr(binding, name) for name in names}


def _queue_priority(prepared: Any) -> str:
    if prepared.operation == "cancel":
        return "cancel"
    flags = prepared.request_payload.get("CombOffsetFlag")
    if type(flags) is not str or not flags:
        raise CtpI9AccountSessionCandidateError(
            "submit queue priority cannot be derived from the prepared offset"
        )
    if flags[0] == "0":
        return "open"
    if flags[0] in {"1", "3", "4"}:
        return "close"
    raise CtpI9AccountSessionCandidateError(
        "submit queue priority has an unsupported prepared offset"
    )


def _claimed_native_payload(binding: Any, binding_type: type) -> Mapping[str, Any]:
    """Return only the exact post-stage native mapping bound by the Store claim."""

    if type(binding) is not binding_type:
        raise CtpI9AccountSessionCandidateError("exact Store-issued native binding V2 is required")
    names = (
        "operation",
        "request_payload_json",
        "request_payload_sha256",
        "native_request_payload_json",
        "native_request_payload_sha256",
        "native_request_id",
        "native_action_ref",
    )
    try:
        (
            operation,
            logical_json,
            logical_digest,
            native_json,
            native_digest,
            request_id,
            action_ref,
        ) = (getattr(binding, name) for name in names)
        binding_payload = binding.to_payload()
        logical = json.loads(logical_json)
        native = json.loads(native_json)
    except Exception:
        raise CtpI9AccountSessionCandidateError(
            "Store-issued binding payload is unreadable"
        ) from None
    if (
        type(binding_payload) is not dict
        or binding_payload.get("binding_type") != "ctp_managed_native_call_binding.v2"
        or binding_payload.get("request_payload_json") != logical_json
        or binding_payload.get("request_payload_sha256") != logical_digest
        or binding_payload.get("native_request_payload_json") != native_json
        or binding_payload.get("native_request_payload_sha256") != native_digest
        or (
            binding_payload.get("native_action_ref") is not None
            and type(binding_payload.get("native_action_ref")) is not int
        )
        or binding_payload.get("native_action_ref") != action_ref
        or type(binding_payload.get("native_request_id")) is not int
        or binding_payload.get("native_request_id") != request_id
        or type(binding_payload.get("operation")) is not str
        or binding_payload.get("operation") != operation
    ):
        raise CtpI9AccountSessionCandidateError("Store-issued binding is not the exact V2 contract")
    if type(logical) is not dict or type(native) is not dict:
        raise CtpI9AccountSessionCandidateError("Store-issued payloads must be exact mappings")
    if "OrderActionRef" in logical:
        raise CtpI9AccountSessionCandidateError("logical request must not include OrderActionRef")
    if "RequestID" in logical and (
        type(logical["RequestID"]) is not int or logical["RequestID"] != request_id
    ):
        raise CtpI9AccountSessionCandidateError(
            "logical RequestID differs from the Store-bound native request id"
        )
    if (
        type(request_id) is not int
        or request_id <= 0
        or request_id > 2_147_483_647
        or type(logical_digest) is not str
        or type(native_digest) is not str
    ):
        raise CtpI9AccountSessionCandidateError("Store-issued native binding scalars are invalid")
    try:
        from bt_api_execution.contracts import canonical_json, payload_sha256

        if (
            canonical_json(logical) != logical_json
            or canonical_json(native) != native_json
            or payload_sha256(logical) != logical_digest
            or payload_sha256(native) != native_digest
        ):
            raise CtpI9AccountSessionCandidateError("Store-issued payload digest does not match")
    except CtpI9AccountSessionCandidateError:
        raise
    except Exception:
        raise CtpI9AccountSessionCandidateError(
            "Store-issued payload digest is unavailable"
        ) from None

    expected = dict(logical)
    if operation == "SUBMIT":
        if action_ref is not None:
            raise CtpI9AccountSessionCandidateError("submit binding must not carry ActionRef")
    elif operation == "CANCEL":
        if type(action_ref) is not int or action_ref <= 0 or action_ref > 2_147_483_647:
            raise CtpI9AccountSessionCandidateError("cancel ActionRef binding is invalid")
        expected["OrderActionRef"] = action_ref
    else:
        raise CtpI9AccountSessionCandidateError("unsupported Store-issued native operation")
    if native != expected:
        raise CtpI9AccountSessionCandidateError("native payload differs from Store binding")
    return MappingProxyType(native)


class CtpI9AccountSessionCandidate:
    """Single-session fakeable composition; no default runtime registration."""

    def __init__(
        self,
        *,
        scope: Any,
        store: Any,
        writer_lease: Any,
        worker: Any,
        client_factory: Callable[[], Any],
        lifecycle_supervisor: CtpI9NativeLifecycleSupervisor,
        native_field_factory: Callable[[str, Mapping[str, Any]], Any],
        callback_verifier: Any,
        trade_fact_verifier: Any,
        native_call_admission: Callable[[Any, Any, Any], None] | None = None,
    ) -> None:
        types = _trusted_candidate_types()
        if types is None:
            raise CtpI9AccountSessionCandidateError(
                "reviewed I9 and SDK source-candidate packages are unavailable"
            )
        (
            scope_type,
            store_type,
            lease_type,
            worker_type,
            prepared_type,
            adapter_type,
            owner_type,
            session_type,
            receipt_type,
            native_binding_type,
            claim_type,
            verified_target_type,
            target_handle_type,
            acknowledgement_type,
            callback_record_type,
            client_type,
            dispatch_command_type,
            poison_commit_type,
            poison_ack_type,
        ) = types
        del prepared_type, receipt_type, native_binding_type, claim_type
        del verified_target_type, target_handle_type, dispatch_command_type

        if (
            type(scope) is not scope_type
            or type(store) is not store_type
            or type(writer_lease) is not lease_type
            or type(worker) is not worker_type
            or getattr(worker, "_store", None) is not store
            or getattr(worker, "_scope", None) != scope
            or getattr(worker, "_writer_lease", None) is not writer_lease
            or not callable(client_factory)
            or not isinstance(lifecycle_supervisor, CtpI9NativeLifecycleSupervisor)
            or not callable(native_field_factory)
            or callback_verifier is None
            or trade_fact_verifier is None
            or (native_call_admission is not None and not callable(native_call_admission))
        ):
            raise CtpI9AccountSessionCandidateError(
                "exact Store, worker, supervisor, and verifier dependencies are required"
            )
        self._scope = scope
        self._store = store
        self._writer_lease = writer_lease
        self._worker = worker
        self._client_factory = client_factory
        self._lifecycle_supervisor = lifecycle_supervisor
        self._native_field_factory = native_field_factory
        self._callback_verifier = callback_verifier
        self._trade_fact_verifier = trade_fact_verifier
        self._native_call_admission = native_call_admission
        self._types = types
        self._client_type = client_type
        self._adapter_type = adapter_type
        self._owner_type = owner_type
        self._session_type = session_type
        self._acknowledgement_type = acknowledgement_type
        self._callback_record_type = callback_record_type
        self._poison_commit_type = poison_commit_type
        self._poison_ack_type = poison_ack_type
        self._client = None
        self._adapter = None
        self._owner = None
        self._session = None
        self._started = False
        self._stopped = False
        self._start_attempted = False
        self._queue: queue.Queue[str] = queue.Queue(maxsize=1)
        self._bindings: dict[str, Any] = {}
        self._actor_thread_id: int | None = None
        self._inflight_command_id: str | None = None
        self._durable_owner_state = "UNOBSERVED"

    @property
    def owner_handle(self) -> Any:
        return self._owner

    @property
    def active_session(self) -> Any:
        return self._session

    @property
    def client(self) -> Any:
        return self._client

    @property
    def durable_owner_state(self) -> str:
        """Last exact poison-commit status; UNKNOWN means persistence was not proved."""

        return self._durable_owner_state

    def start(self) -> Any:
        """Persist owner, construct client, install ingress, then supervised start."""

        self._require_actor_thread(allow_unset=True)
        if self._started or self._start_attempted or self._owner is not None or self._stopped:
            raise CtpI9AccountSessionCandidateError("session candidate is one-shot")
        self._start_attempted = True
        try:
            self._owner = self._store.create_ctp_callback_session_owner(
                self._scope, writer_lease=self._writer_lease
            )
            if type(self._owner) is not self._owner_type:
                raise CtpI9AccountSessionCandidateError("Store returned an untyped callback owner")
            self._adapter = self._adapter_type(
                self._store,
                self._scope,
                self._owner,
                self._writer_lease,
                self._acknowledgement_type,
                self._callback_record_type,
            )
            client = self._client_factory()
            if type(client) is not self._client_type:
                raise CtpI9AccountSessionCandidateError(
                    "client factory returned a TraderClient outside the source candidate"
                )
            client.install_callback_ingress_sink(
                self._owner,
                self._adapter.sink,
                self._adapter.bind_session,
                self._verify_native_call,
            )
            self._client = client
            self._lifecycle_supervisor.start_client(client)
            session = self._store._active_ctp_callback_sessions.get(self._owner.owner_intent_id)
            ingress = getattr(client, "_callback_ingress", None)
            if (
                type(session) is not self._session_type
                or ingress is None
                or getattr(ingress, "owner_handle", None) is not self._owner
                or getattr(ingress, "phase", None) != "ACTIVE"
                or getattr(ingress, "active_session", None) is not session
                or session.owner_intent_id != self._owner.owner_intent_id
                or session.account_key != self._scope.account_key
                or session.scope_key != self._scope.key
                or session.trading_day != self._scope.trading_day
            ):
                raise CtpI9AccountSessionCandidateError(
                    "SDK did not bind the exact Store login session"
                )
            self._session = session
            self._started = True
            return client
        except BaseException as start_error:
            self._poison("candidate_composition_failure")
            if self._client is not None:
                try:
                    self._lifecycle_supervisor.stop_client(self._client)
                except BaseException:
                    pass
            if not isinstance(start_error, Exception):
                raise
            raise self._durable_failure(
                "supervised callback session start failed closed ("
                + type(start_error).__name__
                + ")"
            ) from None

    def _verify_native_call(self, owner_handle: Any, binding: Any) -> Any:
        """Check Store's native lease binding, then the optional sealed admission."""

        if self._adapter is None:
            raise CtpI9AccountSessionCandidateError("active callback adapter is unavailable")
        verified = self._adapter.verify_native_call(owner_handle, binding)
        admission = self._native_call_admission
        if admission is not None:
            admission(owner_handle, binding, verified)
        return verified

    def stage_and_queue(self, prepared: Any, *, cancel_target: Any = None) -> Any:
        """Stage an exact I9 prepared command, persist its local receipt, then queue it."""

        self._require_actor_thread()
        self._require_active()
        types = self._types
        prepared_type = types[4]
        target_handle_type = types[12]
        verified_target_type = types[11]
        if type(prepared) is not prepared_type:
            raise CtpI9AccountSessionCandidateError("exact I9 prepared dispatch is required")
        if self._queue.full():
            raise CtpI9AccountSessionCandidateError(
                "single-worker local queue already contains a command"
            )
        if self._adapter.read_next_ingress() is not None:
            raise CtpI9AccountSessionCandidateError(
                "prior callback inbox event must be applied before staging"
            )
        if (
            prepared.session_generation_id != self._session.session_generation_id
            or prepared.dispatch_front_id != self._session.dispatch_front_id
            or prepared.dispatch_session_id != self._session.dispatch_session_id
            or prepared.session_binding.get("session_generation_id")
            != self._session.session_generation_id
            or prepared.session_binding.get("dispatch_front_id") != self._session.dispatch_front_id
            or prepared.session_binding.get("dispatch_session_id")
            != self._session.dispatch_session_id
        ):
            raise CtpI9AccountSessionCandidateError(
                "prepared command differs from the active callback session"
            )
        priority = _queue_priority(prepared)
        target_projection = None
        if prepared.operation == "submit":
            if cancel_target is not None:
                raise CtpI9AccountSessionCandidateError(
                    "submit command cannot carry a cancel target"
                )
        elif prepared.operation == "cancel":
            if type(cancel_target) is not target_handle_type:
                raise CtpI9AccountSessionCandidateError(
                    "cancel requires a fresh typed Store target handle"
                )
            projection = self._store.read_ctp_order_target_projection(self._scope, cancel_target)
            if type(projection) is not verified_target_type:
                raise CtpI9AccountSessionCandidateError(
                    "cancel target is not a verified same-Store projection"
                )
            target_projection = cancel_target
        else:
            raise CtpI9AccountSessionCandidateError("unsupported I9 command operation")
        receipt = {
            "kind": "command_receipt",
            "command": prepared.operation,
            "receipt_id": prepared.local_queue_receipt_id,
            "queued": True,
            "status": "submitted",
            "priority": priority,
            "queue_depth": 1,
            "error_code": "",
            "error_msg": "",
        }
        source_binding = None
        failure_code = "post_stage_failure"
        try:
            source_binding = self._worker.stage_prepared_dispatch(
                prepared, cancel_target_projection=target_projection
            )
            if getattr(source_binding, "command_id", None) != prepared.command_id:
                raise CtpI9AccountSessionCandidateError(
                    "staged command identity differs from prepared command"
                )
            failure_code = "queue_receipt_failure"
            recorded = self._worker.record_managed_queue_receipt(
                prepared.command_id, source_binding, receipt
            )
            if (
                getattr(recorded, "command_id", None) != prepared.command_id
                or getattr(recorded, "local_queue_receipt_queued", None) is not True
                or getattr(recorded, "local_queue_receipt_id", None)
                != prepared.local_queue_receipt_id
            ):
                raise CtpI9AccountSessionCandidateError(
                    "I9 queue receipt readback differs from staged command"
                )
            # This is a single-thread actor; publish the complete binding first.
            self._bindings[prepared.command_id] = recorded
            failure_code = "queue_publish_failure"
            self._queue.put_nowait(prepared.command_id)
            return recorded
        except BaseException as error:
            self._bindings.pop(prepared.command_id, None)
            # The stage call may have committed before a later readback or
            # queue-receipt step raised. Convert only the exact durable READY
            # row through the Store's fail-before-native transaction; if the
            # typed operation is missing or fails, keep the owner fenced and
            # leave the row's actual durable status untouched.
            resolved = self._fail_staged_before_native(
                prepared.command_id, failure_code=failure_code
            )
            if not resolved:
                self._poison("dispatch_stage_ambiguous")
            if not isinstance(error, Exception):
                raise
            raise self._durable_failure("staged command could not be safely published") from None

    def dispatch_next(self) -> Any:
        """Claim and invoke one exact SDK lease, then commit the local receipt."""

        self._require_actor_thread()
        self._require_active()
        try:
            command_id = self._queue.get_nowait()
        except queue.Empty:
            return None
        source_binding = self._bindings.get(command_id)
        if source_binding is None:
            self._poison("owner_binding_mismatch")
            raise self._durable_failure("queued command binding is unavailable")
        claim_method = getattr(self._store, "claim_ctp_dispatch_command_for_session", None)
        if not callable(claim_method):
            self._poison("dispatch_claim_failure")
            raise self._durable_failure("session-bound Store claim is unavailable")
        try:
            claim = claim_method(
                self._scope,
                command_id,
                owner_handle=self._owner,
                writer_lease=self._writer_lease,
                authority_verifier=self._worker._authority_verifier,
                required_local_queue_receipt_id=source_binding.local_queue_receipt_id,
            )
        except BaseException as error:
            resolution = self._resolve_claim_failure(command_id, source_binding=source_binding)
            if resolution == "DEFERRED":
                if isinstance(error, Exception):
                    return CtpI9DispatchDeferred(command_id)
                raise
            self._bindings.pop(command_id, None)
            if not isinstance(error, Exception):
                raise
            raise self._durable_failure("session-bound Store claim failed") from None
        if claim is None or type(claim) is not self._types[10]:
            resolution = self._resolve_claim_failure(command_id, source_binding=source_binding)
            if resolution == "DEFERRED":
                return CtpI9DispatchDeferred(command_id)
            self._bindings.pop(command_id, None)
            raise self._durable_failure("Store did not issue a typed claim")
        command = claim.command
        binding = claim.binding
        if (
            type(binding) is not self._types[9]
            or binding.owner_intent_id != self._owner.owner_intent_id
            or binding.command_id != command_id
            or command.command_id != command_id
            or command.status != "CLAIMED"
        ):
            self._resolve_claim_failure(command_id, source_binding=source_binding)
            self._bindings.pop(command_id, None)
            raise self._durable_failure("Store-issued claim differs from queue")

        self._bindings.pop(command_id, None)

        self._inflight_command_id = command_id
        outcome = "UNKNOWN"
        result = None
        native_base_exception: BaseException | None = None
        try:
            payload = dict(_claimed_native_payload(binding, self._types[9]))
            if binding.operation == "CANCEL" and "RequestID" not in payload:
                # CTP's action field has a RequestID getter in addition to the
                # method argument. It is a separate Store-bound identity, not
                # added to logical/native digests when it was not present.
                payload["RequestID"] = binding.native_request_id
            field = _native_field_after_admission(self, binding, payload)
            lease = self._client.acquire_managed_native_call_lease(self._owner, binding)
            if binding.operation == "SUBMIT":
                result = self._client.submit_order_insert_with_lease(
                    lease, field, binding.native_request_id
                )
            elif binding.operation == "CANCEL":
                result = self._client.submit_order_action_with_lease(
                    lease, field, binding.native_request_id
                )
            if (
                type(result) is int
                and result == 0
                and not getattr(self._client._callback_ingress, "poisoned", False)
            ):
                outcome = "QUEUED"
        except BaseException as error:
            self._poison("native_call_ambiguous")
            outcome = "UNKNOWN"
            if not isinstance(error, Exception):
                native_base_exception = error

        if outcome == "UNKNOWN":
            self._poison("native_call_ambiguous")
        try:
            receipt = self._dispatch_receipt(command, outcome)
        except BaseException as error:
            self._poison("native_call_receipt_mismatch")
            self._inflight_command_id = None
            if native_base_exception is not None:
                raise native_base_exception from None
            if not isinstance(error, Exception):
                raise
            raise self._durable_failure("native call receipt could not be constructed") from None
        try:
            completed = self._adapter.complete_native_receipt(receipt)
        except BaseException as error:
            self._poison("native_call_receipt_mismatch")
            self._inflight_command_id = None
            if native_base_exception is not None:
                raise native_base_exception from None
            if not isinstance(error, Exception):
                raise
            raise self._durable_failure("native call receipt could not be committed") from None
        if getattr(completed, "command_id", None) != command_id or getattr(
            completed, "status", None
        ) != ("COMPLETED" if outcome == "QUEUED" else "UNKNOWN"):
            self._poison("native_call_receipt_mismatch")
            self._inflight_command_id = None
            raise self._durable_failure("native call receipt readback differs")
        if outcome != "QUEUED":
            self._inflight_command_id = None
            if native_base_exception is not None:
                raise native_base_exception
            raise self._durable_failure("native call outcome is unknown; account remains fenced")
        self._inflight_command_id = None
        return completed

    def apply_next_ingress(self) -> Any:
        """Apply one callback through the execution candidate's reviewed inbox adapter."""

        self._require_actor_thread()
        self._require_active()
        if self._inflight_command_id is not None:
            return None
        if self._adapter.read_next_ingress() is None:
            return None
        apply_method = getattr(self._adapter, "apply_next_ingress", None)
        if not callable(apply_method):
            raise CtpI9AccountSessionCandidateError(
                "routeable callback inbox application is unavailable"
            )
        try:
            result = apply_method(
                callback_verifier=self._callback_verifier,
                trade_fact_verifier=self._trade_fact_verifier,
            )
        except BaseException as error:
            self._poison("callback_apply_failure")
            if not isinstance(error, Exception):
                raise
            raise self._durable_failure("durable callback application failed closed") from None
        if result is None and self._adapter.read_next_ingress() is not None:
            self._poison("callback_apply_failure")
            raise self._durable_failure("callback inbox remains unapplied after receipt completion")
        return result

    def apply_pending_ingress(self, *, limit: int = 128) -> tuple[Any, ...]:
        """Drain a bounded inbox prefix; never silently leave a source event pending."""

        self._require_actor_thread()
        if type(limit) is not int or limit <= 0 or limit > 1024:
            raise CtpI9AccountSessionCandidateError("invalid callback apply bound")
        applied = []
        for _ in range(limit):
            event = self._adapter.read_next_ingress()
            if event is None:
                return tuple(applied)
            result = self.apply_next_ingress()
            if result is None:
                return tuple(applied)
            applied.append(result)
        if self._adapter.read_next_ingress() is not None:
            self._poison("callback_apply_failure")
            raise self._durable_failure("callback inbox exceeds the bounded apply prefix")
        return tuple(applied)

    def stop(self) -> None:
        """Fence the one-shot owner before supervised client shutdown."""

        if self._owner is None or self._stopped:
            return
        poison_committed = self._poison("owner_stop")
        client = self._client
        if client is not None:
            try:
                self._lifecycle_supervisor.stop_client(client)
            except Exception:
                raise CtpI9AccountSessionCandidateError(
                    "supervised client stop did not complete; "
                    + self._durable_owner_state_description()
                ) from None
        if not poison_committed:
            raise CtpI9AccountSessionCandidateError(
                "candidate stop could not prove its durable owner fence; "
                + self._durable_owner_state_description()
            )
        self._stopped = True
        self._started = False

    def _require_active(self) -> None:
        if (
            not self._started
            or self._stopped
            or self._client is None
            or self._adapter is None
            or self._owner is None
            or self._session is None
            or getattr(self._client._callback_ingress, "poisoned", False)
        ):
            raise CtpI9AccountSessionCandidateError("active managed callback session is required")

    def _fail_staged_before_native(self, command_id: str, *, failure_code: str) -> bool:
        """Atomically fence a pre-native failure when the Store API is available."""

        fail_before_native = getattr(self._store, "fail_ctp_dispatch_command_before_native", None)
        read_staged = getattr(self._store, "read_ctp_staged_command_for_session", None)
        if not callable(fail_before_native) or not callable(read_staged):
            return False
        try:
            staged = read_staged(
                self._scope,
                command_id,
                owner_handle=self._owner,
                writer_lease=self._writer_lease,
            )
            command_type = self._types[16]
            if (
                type(staged) is not command_type
                or staged.command_id != command_id
                or staged.status != "READY"
            ):
                return False
            failed = fail_before_native(
                self._scope,
                staged,
                owner_handle=self._owner,
                writer_lease=self._writer_lease,
                failure_code=failure_code,
            )
            resolved = (
                type(failed) is command_type
                and failed.command_id == command_id
                and failed.status == "UNKNOWN"
            )
            if resolved:
                self._poison("dispatch_stage_ambiguous")
            return resolved
        except BaseException:
            return False

    def _resolve_claim_failure(self, command_id: str, *, source_binding: Any = None) -> str:
        """Defer only a proven unclaimed READY row; fence every ambiguous state."""

        read_command = getattr(self._store, "read_ctp_dispatch_command", None)
        if not callable(read_command):
            self._poison("dispatch_claim_failure")
            return "FENCED"
        try:
            command = read_command(self._scope, command_id)
        except BaseException:
            self._poison("dispatch_claim_failure")
            return "FENCED"
        if type(command) is not self._types[16] or command.command_id != command_id:
            self._poison("dispatch_claim_failure")
            return "FENCED"
        if command.status == "READY":
            if self._ready_claim_is_safe_to_defer(command, source_binding):
                try:
                    self._queue.put_nowait(command_id)
                except queue.Full:
                    self._poison("dispatch_claim_failure")
                    return "FENCED"
                return "DEFERRED"
            self._poison("dispatch_claim_failure")
            return "FENCED"
        if command.status == "CLAIMED":
            self._poison("dispatch_claim_failure")
            try:
                receipt = self._dispatch_receipt(command, "UNKNOWN")
                completed = self._adapter.complete_native_receipt(receipt)
                resolved = (
                    type(completed) is self._types[16]
                    and completed.command_id == command_id
                    and completed.status == "UNKNOWN"
                )
            except BaseException:
                resolved = False
            if not resolved:
                self._poison("native_call_receipt_mismatch")
            return "RESOLVED" if resolved else "FENCED"
        self._poison("dispatch_claim_failure")
        return "FENCED"

    def _ready_claim_is_safe_to_defer(self, command: Any, source_binding: Any) -> bool:
        """Prove no claim/native call occurred before retaining a READY item.

        The Store claim atomically changes READY to CLAIMED and consumes the
        authority use.  A same-Store READY readback plus the exact queued row,
        active session, and writer lease therefore proves that a failed claim
        made no local dispatch attempt.  Any readback failure is ambiguous and
        remains a poison/fence condition.
        """

        try:
            from bt_api_execution.ctp_single_worker_candidate import (
                CtpManagedDispatchBinding,
            )
        except Exception:
            return False
        if type(source_binding) is not CtpManagedDispatchBinding:
            return False
        read_staged = getattr(self._store, "read_ctp_staged_command_for_session", None)
        read_session = getattr(self._store, "read_ctp_callback_session_context_facts", None)
        assert_lease = getattr(self._store, "assert_writer_lease", None)
        if not callable(read_staged) or not callable(read_session) or not callable(assert_lease):
            return False
        try:
            staged = read_staged(
                self._scope,
                command.command_id,
                owner_handle=self._owner,
                writer_lease=self._writer_lease,
            )
            session_binding, broker_id, user_id = read_session(self._owner)
            assert_lease(self._scope, self._writer_lease)
        except BaseException:
            return False
        ingress = getattr(self._client, "_callback_ingress", None)
        return bool(
            type(staged) is self._types[16]
            and staged.correlation_key is not None
            and staged.native_request_payload is not None
            and staged.session_binding is not None
            and staged == command
            and source_binding.version == 2
            and source_binding.command_id == staged.command_id
            and source_binding.account_key == staged.account_key
            and source_binding.scope_key == staged.scope_key
            and source_binding.trading_day == staged.trading_day
            and source_binding.operation == staged.operation.lower()
            and source_binding.managed_intent_id
            == staged.correlation_key.reservation_managed_intent_id
            and source_binding.runtime_order_id == staged.correlation_key.runtime_order_id
            and source_binding.managed_action_id == staged.correlation_key.managed_action_id
            and source_binding.order_ref == staged.order_ref
            and source_binding.request_payload_sha256 == staged.request_payload_sha256
            and source_binding.approval_use_id == staged.approval_use_id
            and source_binding.approval_digest == staged.approval_digest
            and source_binding.session_binding_sha256 == staged.session_binding_sha256
            and source_binding.session_generation_id == staged.correlation_key.session_generation_id
            and source_binding.dispatch_front_id == staged.correlation_key.dispatch_front_id
            and source_binding.dispatch_session_id == staged.correlation_key.dispatch_session_id
            and source_binding.native_request_id == staged.correlation_key.native_request_id
            and source_binding.native_action_ref == staged.correlation_key.native_action_ref
            and source_binding.cancel_target_exchange_id == staged.cancel_target_exchange_id
            and source_binding.cancel_target_order_sys_id == staged.cancel_target_order_sys_id
            and source_binding.cancel_target_front_id == staged.cancel_target_front_id
            and source_binding.cancel_target_session_id == staged.cancel_target_session_id
            and source_binding.local_queue_receipt_id == staged.local_queue_receipt_id
            and source_binding.local_queue_receipt_queued is True
            and source_binding.request_payload_sha256 == staged.request_payload_sha256
            and dict(source_binding.request_payload) == dict(staged.request_payload)
            and dict(source_binding.native_request_payload) == dict(staged.native_request_payload)
            and source_binding.native_request_payload_sha256 == staged.native_request_payload_sha256
            and dict(source_binding.session_binding) == dict(staged.session_binding)
            and type(source_binding.order_ref_reservation_created_at_ns) is int
            and source_binding.order_ref_reservation_created_at_ns > 0
            and staged.command_id == command.command_id
            and staged.status == "READY"
            and staged.local_queue_receipt_queued is True
            and type(staged.local_queue_receipt_id) is str
            and staged.local_queue_receipt_id
            and type(session_binding) is self._session_type
            and session_binding == self._session
            and session_binding.owner_intent_id == self._owner.owner_intent_id
            and session_binding.account_key == self._scope.account_key
            and session_binding.scope_key == self._scope.key
            and session_binding.trading_day == self._scope.trading_day
            and type(broker_id) is str
            and bool(broker_id)
            and type(user_id) is str
            and bool(user_id)
            and ingress is not None
            and getattr(ingress, "owner_handle", None) is self._owner
            and getattr(ingress, "active_session", None) is self._session
            and getattr(ingress, "phase", None) == "ACTIVE"
            and getattr(ingress, "poisoned", False) is False
        )

    def _require_actor_thread(self, *, allow_unset: bool = False) -> None:
        """Require serialized caller-side mutations without holding locks over native calls."""

        current = threading.get_ident()
        if self._actor_thread_id is None and allow_unset:
            self._actor_thread_id = current
            return
        if self._actor_thread_id is None or current != self._actor_thread_id:
            raise CtpI9AccountSessionCandidateError(
                "candidate mutations must stay on the creating actor thread"
            )

    def _poison(self, reason: str) -> bool:
        if self._owner is None:
            self._durable_owner_state = "UNKNOWN"
            self._started = False
            return False
        try:
            if self._adapter is not None:
                result = self._adapter.sink.poison_ingress(self._owner, reason)
                result_type = self._poison_ack_type
            else:
                result = self._store.poison_ctp_callback_session_owner(self._owner, reason)
                result_type = self._poison_commit_type
            committed = (
                type(result) is result_type
                and result.owner_intent_id == self._owner.owner_intent_id
                and result.durable_state == "POISONED"
                and result.committed is True
            )
            self._durable_owner_state = "POISONED" if committed else "UNKNOWN"
        except BaseException:
            # Do not expose exception detail or claim a durable fence without
            # the exact Store/SDK poison acknowledgement.
            self._durable_owner_state = "UNKNOWN"
        finally:
            self._started = False
        return self._durable_owner_state == "POISONED"

    def _durable_failure(self, message: str) -> CtpI9AccountSessionCandidateError:
        return CtpI9AccountSessionCandidateError(
            message + "; " + self._durable_owner_state_description()
        )

    def _durable_owner_state_description(self) -> str:
        if self._durable_owner_state == "POISONED":
            return "durable owner state is POISONED"
        return "candidate is locally fenced; durable owner state is UNKNOWN"

    def _dispatch_receipt(self, command: Any, outcome: str) -> Any:
        return self._types[8](
            receipt_type="ctp_dispatch_receipt.v2",
            command_id=command.command_id,
            account_key=command.account_key,
            scope_key=command.scope_key,
            trading_day=command.trading_day,
            operation=command.operation,
            request_payload_sha256=command.request_payload_sha256,
            reservation_managed_intent_id=command.reservation_managed_intent_id,
            order_ref=command.order_ref,
            cancel_target_order_ref=command.cancel_target_order_ref,
            cancel_target_exchange_id=command.cancel_target_exchange_id,
            cancel_target_order_sys_id=command.cancel_target_order_sys_id,
            cancel_target_front_id=command.cancel_target_front_id,
            cancel_target_session_id=command.cancel_target_session_id,
            approval_use_id=command.approval_use_id,
            approval_digest=command.approval_digest,
            session_binding_sha256=command.session_binding_sha256,
            outcome=outcome,
            native_receipt_payload={"kind": "native_dispatch", "outcome": outcome},
            correlation_key=command.correlation_key,
            local_queue_receipt_id=command.local_queue_receipt_id,
        )


__all__ = [
    "CtpI9AccountSessionCandidate",
    "CtpI9AccountSessionCandidateError",
    "CtpI9DispatchDeferred",
    "CtpI9NativeLifecycleSupervisor",
]
