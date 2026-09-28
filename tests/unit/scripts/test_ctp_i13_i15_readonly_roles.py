"""Strict contract tests for the bootstrap-dispatched readonly service roles."""

from __future__ import annotations

import hashlib
import json
import ctypes
import os
import threading
import time
import uuid
from ctypes import wintypes

import pytest

from scripts import (
    ctp_i13_i15_readonly_receipt_writer as receipt_writer,
    ctp_i13_i15_readonly_request_coordinator as coordinator,
    ctp_i13_i15_readonly_token_bootstrap as token_bootstrap,
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _deployment():
    return {
        key: _sha(key.encode("ascii"))
        for key in (
            "descriptor_sha256",
            "source_manifest_sha256",
            "runtime_manifest_sha256",
            "dependency_manifest_sha256",
            "python_sha256",
            "i13_pin_sha256",
            "i15_pin_sha256",
            "bootstrap_sha256",
            "worker_sha256",
            "coordinator_sha256",
            "receipt_writer_sha256",
            "token_bootstrap_sha256",
        )
    }


def _job_facts(**overrides):
    value = {
        "process_created": True,
        "job_assignment_observed": True,
        "launcher_resumed": True,
        "launcher_exit_observed": True,
        "launcher_exit_code": 0,
        "job_termination_requested": False,
        "job_termination_call_succeeded": None,
        "job_empty_observed": True,
        "containment": "verified",
        "controls_retained": False,
    }
    value.update(overrides)
    return value


def _worker_summary():
    names = (
        "account",
        "commission_rates",
        "instruments",
        "margin_rates",
        "orders",
        "positions",
        "trades",
    )
    return {
        "schema": "ctp_i13_i15_readonly_worker_summary.v1",
        "identity": {
            "account_scope": "redacted",
            "provider": "ctp",
            "environment": "simnow",
            "trading_day": "20260926",
            "connection_generation": 1,
        },
        "query_digests": [[name, _sha(name.encode("ascii"))] for name in names],
        "snapshot_sha256": _sha(b"snapshot"),
    }


def _coordinator_binding(**overrides):
    value = {
        "schema": coordinator.COORDINATOR_BINDING_SCHEMA,
        "request_id": "a" * 32,
        "deadline_monotonic_ns": 900,
        "deployment": _deployment(),
        "identities": {
            "service_sid": "S-1-5-80-100-200-300-400-500",
            "owner_sid": "S-1-5-21-1-2-3-1001",
        },
        "supervisor_output_channel": {"nonce": "b" * 32, "server_pid": 100},
        "token_control_channel": {"nonce": "c" * 32, "server_pid": 100},
    }
    value.update(overrides)
    return value


def _work_result(**overrides):
    value = {
        "schema": coordinator.COORDINATOR_OUTPUT_SCHEMA,
        "request_id": "a" * 32,
        "state": "observed",
        "reason": "completed",
        "worker_observation": _worker_summary(),
        "worker_facts": _job_facts(),
    }
    value.update(overrides)
    return value


def _receipt_binding(**overrides):
    value = {
        "schema": receipt_writer.RECEIPT_BINDING_SCHEMA,
        "request_id": "a" * 32,
        "deadline_monotonic_ns": 900,
        "deployment": _deployment(),
        "work_result": _work_result(),
        "coordinator_job": _job_facts(),
        "receipt_output_channel": {"nonce": "d" * 32, "server_pid": 100},
    }
    value.update(overrides)
    return value


def _token_frame(**overrides):
    value = {
        "schema": token_bootstrap.TOKEN_BOOTSTRAP_SCHEMA,
        "request_id": "a" * 32,
        "nonce": "b" * 32,
        "remote_primary_token_handle": 1234,
        "owner_sid": "S-1-5-21-1-2-3-1001",
        "authentication_id": {"high": 2, "low": 3},
        "source_session_id": 7,
        "token_facts_sha256": _sha(b"stable token facts"),
    }
    value.update(overrides)
    return value


def test_coordinator_binding_rejects_bool_and_unknown_or_caller_selected_fields():
    with pytest.raises(coordinator.CoordinatorError, match="deadline_invalid"):
        coordinator.parse_coordinator_binding(_coordinator_binding(deadline_monotonic_ns=True))
    with pytest.raises(coordinator.CoordinatorError, match="supervisor_channel_invalid"):
        coordinator.parse_coordinator_binding(
            _coordinator_binding(supervisor_output_channel={"nonce": "b" * 32, "server_pid": True})
        )
    with pytest.raises(coordinator.CoordinatorError, match="coordinator_binding_fields_invalid"):
        coordinator.parse_coordinator_binding(_coordinator_binding(path="C:\\caller"))
    with pytest.raises(coordinator.CoordinatorError, match="request_identity_invalid"):
        coordinator.parse_coordinator_binding(
            _coordinator_binding(
                identities={
                    "service_sid": "S-1-5-80-100-200-300-400-500",
                    "owner_sid": "S-1-5-80-100-200-300-400-500",
                }
            )
        )


def test_coordinator_output_requires_independent_complete_worker_facts():
    valid = _work_result()
    parsed = coordinator.parse_coordinator_output(valid, expected_request_id="a" * 32)
    assert parsed["state"] == "observed"
    with pytest.raises(coordinator.CoordinatorError, match="coordinator_output_success_unproven"):
        coordinator.parse_coordinator_output(
            _work_result(worker_facts=_job_facts(job_empty_observed=False)),
            expected_request_id="a" * 32,
        )
    with pytest.raises(coordinator.CoordinatorError, match="worker_facts_invalid"):
        coordinator.parse_coordinator_output(
            _work_result(worker_facts=_job_facts(launcher_exit_code=True)),
            expected_request_id="a" * 32,
        )
    secret_observation = _worker_summary()
    secret_observation["password"] = "SYNTHETIC_SECRET_MARKER"
    with pytest.raises(coordinator.CoordinatorError, match="worker_observation_invalid"):
        coordinator.parse_coordinator_output(
            _work_result(worker_observation=secret_observation),
            expected_request_id="a" * 32,
        )
    encoded = coordinator.encode_coordinator_output(valid, request_id="a" * 32)
    assert json.loads(encoded) == valid


def test_coordinator_frame_is_canonical_and_bound_to_request_and_channel_nonce():
    output = _work_result()
    raw = coordinator.encode_coordinator_frame(output, request_id="a" * 32, nonce="b" * 32)
    parsed = coordinator.parse_coordinator_frame(
        raw, expected_request_id="a" * 32, expected_nonce="b" * 32
    )
    assert parsed["state"] == "observed"
    with pytest.raises(coordinator.CoordinatorError, match="coordinator_frame_binding_invalid"):
        coordinator.parse_coordinator_frame(
            raw, expected_request_id="a" * 32, expected_nonce="c" * 32
        )
    with pytest.raises(coordinator.CoordinatorError, match="coordinator_frame_binding_invalid"):
        coordinator.parse_coordinator_frame(
            raw, expected_request_id="c" * 32, expected_nonce="b" * 32
        )
    with pytest.raises(coordinator.CoordinatorError, match="coordinator_frame_fields_invalid"):
        extra = json.loads(raw.decode("ascii"))
        extra["path"] = "C:\\caller"
        coordinator.parse_coordinator_frame(
            json.dumps(extra, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "ascii"
            ),
            expected_request_id="a" * 32,
            expected_nonce="b" * 32,
        )


class _CoordinatorApi:
    def __init__(self, *, now=100, fail=None):
        self.now = now
        self.fail = fail
        self.events = []
        self.output = None

    def monotonic_ns(self):
        self.events.append("clock")
        return self.now

    def verify_deployment(self, deployment):
        self.events.append("verify")
        if self.fail == "verify":
            raise RuntimeError("synthetic")

    def receive_and_set_owner_token_session_zero(self, binding):
        self.events.append("token")
        if self.fail == "token":
            raise RuntimeError("synthetic")

    def run_fixed_worker(self, binding):
        self.events.append("worker")
        if self.fail == "worker":
            raise RuntimeError("synthetic")
        if self.fail == "fatal":
            raise KeyboardInterrupt()
        return _worker_summary(), _job_facts()

    def write_supervisor_output(self, binding, output):
        self.events.append("write")
        self.output = output


def test_coordinator_orders_fixed_stages_and_emits_only_after_worker_cleanup_facts():
    api = _CoordinatorApi()
    assert coordinator.run_request_coordinator(_coordinator_binding(), api=api) == 0
    assert api.events == ["clock", "verify", "token", "clock", "worker", "clock", "write"]
    assert api.output["state"] == "observed"
    assert api.output["worker_facts"]["job_empty_observed"] is True


def test_coordinator_emits_unknown_frame_for_an_allowed_failure_reason():
    api = _CoordinatorApi(fail="worker")
    assert coordinator.run_request_coordinator(_coordinator_binding(), api=api) == 2
    assert api.output is not None
    assert api.output["state"] == "unknown"
    assert api.output["reason"] == "worker_failed"
    assert api.output["worker_observation"] is None
    assert api.output["worker_facts"]["process_created"] is False


def test_coordinator_deadline_and_fatal_identity_cleanup_fail_closed():
    late = _CoordinatorApi(now=900)
    assert coordinator.run_request_coordinator(_coordinator_binding(), api=late) == 2
    assert late.events == ["clock"]
    assert late.output is None

    fatal = _CoordinatorApi(fail="fatal")
    with pytest.raises(KeyboardInterrupt):
        coordinator.run_request_coordinator(_coordinator_binding(), api=fatal)
    assert "write" not in fatal.events


def test_receipt_writer_requires_observed_coordinator_job_and_never_self_attests():
    binding = receipt_writer.parse_receipt_writer_binding(_receipt_binding())
    payload, state, reason = receipt_writer._receipt_payload(binding)
    assert state == "observed" and reason == "completed"
    assert "receipt_writer_job" not in payload

    with pytest.raises(receipt_writer.ReceiptWriterError, match="coordinator_cleanup_unverified"):
        receipt_writer.parse_receipt_writer_binding(
            _receipt_binding(coordinator_job=_job_facts(job_empty_observed=False))
        )

    # UNKNOWN work may be recorded after independently proven cleanup, even
    # when the coordinator was terminated and exited nonzero.
    unknown_work = _work_result(
        state="unknown",
        reason="worker_failed",
        worker_observation=None,
        worker_facts=_job_facts(
            job_termination_requested=True,
            job_termination_call_succeeded=True,
            launcher_exit_code=1,
        ),
    )
    unknown_binding = receipt_writer.parse_receipt_writer_binding(
        _receipt_binding(
            work_result=unknown_work,
            coordinator_job=_job_facts(
                job_termination_requested=True,
                job_termination_call_succeeded=True,
                launcher_exit_code=1,
            ),
        )
    )
    unknown_payload, state, reason = receipt_writer._receipt_payload(unknown_binding)
    assert state == "unknown" and reason == "worker_failed"
    assert unknown_payload["state"] == "unknown"


def test_receipt_writer_binding_rejects_bool_and_invalid_success_claims():
    with pytest.raises(receipt_writer.ReceiptWriterError, match="receipt_facts_invalid"):
        receipt_writer.parse_receipt_writer_binding(
            _receipt_binding(
                coordinator_job=_job_facts(job_empty_observed=True, launcher_exit_code=True)
            )
        )
    with pytest.raises(receipt_writer.ReceiptWriterError, match="receipt_output_channel_invalid"):
        receipt_writer.parse_receipt_writer_binding(
            _receipt_binding(receipt_output_channel={"nonce": "d" * 32, "server_pid": True})
        )
    with pytest.raises(receipt_writer.ReceiptWriterError, match="work_result_success_unproven"):
        receipt_writer.parse_receipt_writer_binding(
            _receipt_binding(
                work_result=_work_result(worker_facts=_job_facts(job_empty_observed=False))
            )
        )
    secret_observation = _worker_summary()
    secret_observation["password"] = "SYNTHETIC_SECRET_MARKER"
    with pytest.raises(receipt_writer.ReceiptWriterError, match="work_result_invalid"):
        receipt_writer.parse_receipt_writer_binding(
            _receipt_binding(work_result=_work_result(worker_observation=secret_observation))
        )


def test_receipt_writer_frame_is_canonical_and_bound_to_request_and_nonce():
    output = {
        "schema": receipt_writer.RECEIPT_OUTPUT_SCHEMA,
        "request_id": "a" * 32,
        "state": "unknown",
        "reason": "worker_failed",
        "receipt_created": True,
        "receipt_sha256": _sha(b"receipt"),
    }
    raw = receipt_writer.encode_receipt_writer_frame(output, request_id="a" * 32, nonce="d" * 32)
    parsed = receipt_writer.parse_receipt_writer_frame(
        raw, expected_request_id="a" * 32, expected_nonce="d" * 32
    )
    assert parsed["state"] == "unknown"
    with pytest.raises(receipt_writer.ReceiptWriterError, match="receipt_frame_binding_invalid"):
        receipt_writer.parse_receipt_writer_frame(
            raw, expected_request_id="a" * 32, expected_nonce="e" * 32
        )
    with pytest.raises(receipt_writer.ReceiptWriterError, match="receipt_frame_fields_invalid"):
        extra = json.loads(raw.decode("ascii"))
        extra["path"] = "C:\\caller"
        receipt_writer.parse_receipt_writer_frame(
            json.dumps(extra, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "ascii"
            ),
            expected_request_id="a" * 32,
            expected_nonce="d" * 32,
        )


def test_receipt_writer_output_is_bound_and_cannot_claim_unproven_persistence():
    valid = {
        "schema": receipt_writer.RECEIPT_OUTPUT_SCHEMA,
        "request_id": "a" * 32,
        "state": "observed",
        "reason": "completed",
        "receipt_created": True,
        "receipt_sha256": _sha(b"receipt"),
    }
    assert (
        receipt_writer.parse_receipt_writer_output(valid, expected_request_id="a" * 32)["state"]
        == "observed"
    )
    invalid = dict(valid, receipt_created=False)
    with pytest.raises(receipt_writer.ReceiptWriterError, match="receipt_output_digest_invalid"):
        receipt_writer.parse_receipt_writer_output(invalid, expected_request_id="a" * 32)
    with pytest.raises(receipt_writer.ReceiptWriterError, match="receipt_output_binding_invalid"):
        receipt_writer.parse_receipt_writer_output(valid, expected_request_id="b" * 32)


class _ReceiptApi:
    def __init__(self, *, now=100, close_error=False, close_advance=0):
        self.now = now
        self.close_error = close_error
        self.close_advance = close_advance
        self.raw = None
        self.output = None
        self.events = []

    def monotonic_ns(self):
        return self.now

    def verify_deployment(self, deployment):
        self.events.append("verify")

    def close_execution(self):
        self.events.append("close_execution")
        self.now += self.close_advance
        if self.close_error:
            raise RuntimeError("synthetic close failure")

    def persist_fixed_receipt(self, request_id, raw):
        self.events.append("persist")
        self.raw = raw

    def write_supervisor_output(self, binding, output):
        self.events.append("output")
        self.output = output


def test_receipt_writer_emits_hash_of_persisted_canonical_receipt():
    api = _ReceiptApi()
    assert receipt_writer.run_receipt_writer(_receipt_binding(), api=api) == 0
    assert api.raw is not None
    parsed = json.loads(api.raw)
    assert parsed["state"] == "observed"
    assert "receipt_writer_job" not in parsed
    assert api.output["receipt_sha256"] == _sha(api.raw)
    assert api.events == ["verify", "close_execution", "persist", "output"]


def test_receipt_writer_persists_unknown_if_execution_lease_close_fails():
    api = _ReceiptApi(close_error=True)
    assert receipt_writer.run_receipt_writer(_receipt_binding(), api=api) == 2
    assert api.raw is not None
    parsed = json.loads(api.raw)
    assert parsed["state"] == "unknown"
    assert parsed["reason"] == "deployment_execution_lease_close_failed"
    assert api.output["state"] == "unknown"
    assert api.output["reason"] == "deployment_execution_lease_close_failed"
    assert api.output["receipt_sha256"] == _sha(api.raw)
    assert api.events == ["verify", "close_execution", "persist", "output"]


def test_receipt_writer_does_not_start_receipt_or_channel_io_after_deadline():
    api = _ReceiptApi(now=900)
    assert receipt_writer.run_receipt_writer(_receipt_binding(), api=api) == 2
    assert api.raw is None
    assert api.output is None


def test_receipt_writer_does_not_persist_when_execution_close_returns_after_deadline():
    api = _ReceiptApi(close_advance=800)
    assert receipt_writer.run_receipt_writer(_receipt_binding(), api=api) == 2
    assert api.events == ["verify", "close_execution"]
    assert api.raw is None
    assert api.output is None


class _TokenApi:
    def __init__(self, *, fail=None):
        self.fail = fail
        self.session_id = 7
        self.events = []
        self.restored = False
        self.fatal_reason = None
        self.session_mismatch = False

    def query_token_facts(self, token_handle):
        self.events.append(("query", token_handle, self.session_id))
        if (self.fail == "query_after_set" and self.session_id == 0) or self.session_mismatch:
            return {
                "token_type": "primary",
                "user_sid": "S-1-5-21-1-2-3-1001",
                "authentication_id": {"high": 2, "low": 3},
                "session_id": 1,
                "stable_facts_sha256": _sha(b"stable token facts"),
            }
        return {
            "token_type": "primary",
            "user_sid": "S-1-5-21-1-2-3-1001",
            "authentication_id": {"high": 2, "low": 3},
            "session_id": self.session_id,
            "stable_facts_sha256": _sha(b"stable token facts"),
        }

    def enable_se_tcb_privilege(self):
        self.events.append("enable")
        if self.fail == "enable":
            raise KeyboardInterrupt()
        return {"previous": "disabled"}

    def set_token_session_id(self, token_handle, session_id):
        self.events.append(("set", token_handle, session_id))
        if self.fail == "set":
            raise OSError("synthetic")
        self.session_id = session_id

    def restore_se_tcb_privilege(self, previous_state):
        self.events.append("restore")
        if self.fail == "restore":
            raise OSError("synthetic")
        self.restored = True

    def fail_stop_current_process(self, reason):
        self.fatal_reason = reason


def test_token_control_frame_is_canonical_and_bound_to_os_authenticated_facts():
    raw = token_bootstrap.encode_token_bootstrap_frame(_token_frame())
    parsed = token_bootstrap.parse_token_bootstrap_frame(
        raw,
        expected_request_id="a" * 32,
        expected_nonce="b" * 32,
        expected_owner_sid="S-1-5-21-1-2-3-1001",
    )
    assert parsed.remote_primary_token_handle == 1234
    assert parsed.authentication_id == (2, 3)
    with pytest.raises(token_bootstrap.TokenBootstrapError, match="token_frame_binding_mismatch"):
        token_bootstrap.parse_token_bootstrap_frame(
            token_bootstrap.encode_token_bootstrap_frame(_token_frame(owner_sid="S-1-5-18")),
            expected_request_id="a" * 32,
            expected_nonce="b" * 32,
            expected_owner_sid="S-1-5-21-1-2-3-1001",
        )
    with pytest.raises(
        token_bootstrap.TokenBootstrapError, match="token_authentication_id_invalid"
    ):
        token_bootstrap.parse_token_bootstrap_frame(
            token_bootstrap.encode_token_bootstrap_frame(
                _token_frame(authentication_id={"high": True, "low": 3})
            ),
            expected_request_id="a" * 32,
            expected_nonce="b" * 32,
            expected_owner_sid="S-1-5-21-1-2-3-1001",
        )


def test_token_session_transition_is_literal_zero_and_restores_se_tcb():
    transfer = token_bootstrap.parse_token_bootstrap_frame(
        token_bootstrap.encode_token_bootstrap_frame(_token_frame()),
        expected_request_id="a" * 32,
        expected_nonce="b" * 32,
        expected_owner_sid="S-1-5-21-1-2-3-1001",
    )
    api = _TokenApi()
    facts = token_bootstrap.apply_owner_token_session_zero(transfer, api=api)
    assert facts.source_session_id == 7 and facts.target_session_id == 0
    assert api.events == [
        ("query", 1234, 7),
        "enable",
        ("set", 1234, 0),
        ("query", 1234, 0),
        "restore",
    ]
    assert api.restored is True


def test_token_session_failure_restores_privilege_and_restore_failure_is_fatal():
    transfer = token_bootstrap.parse_token_bootstrap_frame(
        token_bootstrap.encode_token_bootstrap_frame(_token_frame()),
        expected_request_id="a" * 32,
        expected_nonce="b" * 32,
        expected_owner_sid="S-1-5-21-1-2-3-1001",
    )
    set_failure = _TokenApi(fail="set")
    with pytest.raises(token_bootstrap.TokenBootstrapError, match="token_session_change_failed"):
        token_bootstrap.apply_owner_token_session_zero(transfer, api=set_failure)
    assert set_failure.restored is True

    restore_failure = _TokenApi(fail="restore")
    with pytest.raises(token_bootstrap.FatalPrivilegeRestore):
        token_bootstrap.apply_owner_token_session_zero(transfer, api=restore_failure)
    assert restore_failure.fatal_reason == "se_tcb_restore_failed"

    enable_failure = _TokenApi(fail="enable")
    with pytest.raises(token_bootstrap.FatalPrivilegeRestore):
        token_bootstrap.apply_owner_token_session_zero(transfer, api=enable_failure)
    assert enable_failure.fatal_reason == "se_tcb_enable_state_unknown"


def test_token_helper_rejects_directly_constructed_bool_handle_and_token_readback_change():
    transfer = token_bootstrap.parse_token_bootstrap_frame(
        token_bootstrap.encode_token_bootstrap_frame(_token_frame()),
        expected_request_id="a" * 32,
        expected_nonce="b" * 32,
        expected_owner_sid="S-1-5-21-1-2-3-1001",
    )
    forged = token_bootstrap.OwnerTokenTransfer(
        request_id=transfer.request_id,
        nonce=transfer.nonce,
        remote_primary_token_handle=True,
        owner_sid=transfer.owner_sid,
        authentication_id=transfer.authentication_id,
        source_session_id=transfer.source_session_id,
        token_facts_sha256=transfer.token_facts_sha256,
    )
    with pytest.raises(token_bootstrap.TokenBootstrapError, match="token_transfer_invalid"):
        token_bootstrap.apply_owner_token_session_zero(forged, api=_TokenApi())

    changed = _TokenApi()
    changed.session_mismatch = True
    with pytest.raises(token_bootstrap.TokenBootstrapError, match="token_transfer_binding_changed"):
        token_bootstrap.apply_owner_token_session_zero(transfer, api=changed)
    assert changed.events == [("query", 1234, 7)]


def test_token_sid_parser_rejects_forged_or_truncated_pointers_before_dereference():
    api = object.__new__(token_bootstrap.WindowsTokenSessionApi)
    storage = ctypes.create_string_buffer(64)
    base = ctypes.addressof(storage)
    sid_bytes = (
        bytes((1, 4))
        + (5).to_bytes(6, "big")
        + b"".join(value.to_bytes(4, "little") for value in (21, 77, 88, 1001))
    )
    ctypes.memmove(base + 16, sid_bytes, len(sid_bytes))
    valid = token_bootstrap._TokenInformationBuffer(storage, 16 + len(sid_bytes))
    assert api._sid_string(ctypes.c_void_p(base + 16), valid) == "S-1-5-21-77-88-1001"

    with pytest.raises(token_bootstrap.TokenBootstrapError, match="token_sid_invalid"):
        api._sid_string(ctypes.c_void_p(base + 1024), valid)

    truncated_storage = ctypes.create_string_buffer(32)
    truncated_base = ctypes.addressof(truncated_storage)
    ctypes.memmove(truncated_base + 7, bytes((1, 1, 0, 0, 0, 0, 0, 5)), 8)
    truncated = token_bootstrap._TokenInformationBuffer(truncated_storage, 15)
    with pytest.raises(token_bootstrap.TokenBootstrapError, match="token_sid_invalid"):
        api._sid_string(ctypes.c_void_p(truncated_base + 7), truncated)


@pytest.mark.skipif(os.name != "nt", reason="requires local Windows token APIs")
def test_windows_token_session_api_current_process_query_only_smoke():
    api = token_bootstrap.WindowsTokenSessionApi()
    open_token = api._advapi32.OpenProcessToken
    open_token.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    open_token.restype = wintypes.BOOL
    get_current = api._kernel32.GetCurrentProcess
    get_current.argtypes = []
    get_current.restype = wintypes.HANDLE
    token = wintypes.HANDLE()
    assert open_token(get_current(), 0x0008, ctypes.byref(token))
    try:
        facts = [api.query_token_facts(int(token.value)) for _ in range(64)]
        assert all(item["token_type"] == "primary" for item in facts)
        assert all(type(item["user_sid"]) is str for item in facts)
        assert all(type(item["session_id"]) is int for item in facts)
        assert all(len(item["stable_facts_sha256"]) == 64 for item in facts)
        assert len({item["stable_facts_sha256"] for item in facts}) == 1
    finally:
        close = api._kernel32.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        assert close(token)


@pytest.mark.skipif(os.name != "nt", reason="requires local Windows named pipes")
def test_token_control_pipe_reader_uses_real_server_pid_and_one_frame_eof():
    from scripts import ctp_i13_i15_windows_guardian_service as guardian_service

    _connect_readonly_pipe_server = guardian_service._connect_readonly_pipe_server
    _write_readonly_pipe_message = guardian_service._write_readonly_pipe_message

    nonce = uuid.uuid4().hex
    address = token_bootstrap._TOKEN_BOOTSTRAP_PIPE_PREFIX + nonce
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_pipe = kernel32.CreateNamedPipeW
    create_pipe.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    create_pipe.restype = wintypes.HANDLE
    handle = create_pipe(
        address,
        0x00000003 | 0x40000000 | 0x00080000,
        0x00000004 | 0x00000002 | 0x00000008,
        1,
        4100,
        4100,
        0,
        None,
    )
    server_handle = int(handle)
    assert server_handle > 0
    request_id = uuid.uuid4().hex
    client_result = {}
    client_error = {}

    def read_client():
        try:
            client_result["transfer"] = token_bootstrap.read_token_bootstrap_frame_from_pipe(
                {"nonce": nonce, "server_pid": os.getpid()},
                expected_request_id=request_id,
                expected_owner_sid="S-1-5-21-1-2-3-1001",
                deadline_monotonic_ns=time.monotonic_ns() + 5_000_000_000,
            )
        except BaseException as error:  # preserve assertion context without secret values
            client_error["type"] = type(error).__name__
            client_error["reason"] = getattr(error, "args", (None,))[0]

    thread = threading.Thread(target=read_client, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        _connect_readonly_pipe_server(server_handle, deadline_monotonic=deadline)
        body = token_bootstrap.encode_token_bootstrap_frame(
            _token_frame(request_id=request_id, nonce=nonce)
        )
        _write_readonly_pipe_message(
            server_handle,
            len(body).to_bytes(4, "big") + body,
            max_bytes=4100,
            deadline_monotonic=deadline,
        )
        assert guardian_service._wait_token_pipe_message_consumed(
            server_handle, time.monotonic_ns() + 5_000_000_000
        )
    finally:
        close = kernel32.CloseHandle
        close.argtypes = [wintypes.HANDLE]
        close.restype = wintypes.BOOL
        assert close(wintypes.HANDLE(server_handle))
    thread.join(5.0)
    assert not thread.is_alive()
    assert client_error == {}
    assert client_result["transfer"].request_id == request_id
    assert client_result["transfer"].nonce == nonce
