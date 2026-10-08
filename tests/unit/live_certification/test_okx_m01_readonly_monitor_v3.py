"""Fake-only contracts for the source-owned OKX M01 V3 route."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import struct
import time
from types import SimpleNamespace

import pytest


OKX_ROOT = (
    Path(__file__).resolve().parents[3] / "examples" / "000_live_certification" / "okx_penetration"
)
M01_CASE = OKX_ROOT / "cases" / "M01"
for _source_path in (str(OKX_ROOT), str(M01_CASE)):
    if _source_path not in sys.path:
        sys.path.insert(0, _source_path)

from _certification import m01_private_monitor_v2 as contract  # noqa: E402
from _m01_readonly_monitor_v2 import current_types, job_supervisor, worker  # noqa: E402
from _m01_readonly_monitor_v3 import current_reader, entry, issuer  # noqa: E402


class _LeaseSet:
    def __init__(self):
        self.closed = False
        self.private_api = object()

    def close(self):
        self.closed = True


class _FailingLeaseSet:
    def __init__(self):
        self.private_api = object()

    def close(self):
        raise OSError("synthetic-close-uncertain")


class _AuditDirectory:
    def __init__(self):
        self.path = Path("D:/temp/synthetic-m01-v3")
        self.documents = {}

    def verify(self):
        return None

    def write_json(self, _name, _document):
        self.documents[_name] = _document
        return "f" * 64


class _PrivateJournalWriter:
    def __init__(self, directory, _private_api, journal):
        self.directory = directory
        self.path = directory.path / "m01-private-events-v3.bin"
        self.parts = [journal]
        self.failed = False
        self.handle = object()

    def close(self):
        self.handle = None


def _parent_journal(events):
    output = bytearray(job_supervisor._PARENT_JOURNAL_MAGIC)
    for event in events:
        raw = event.raw_bytes
        output.extend(
            struct.pack(
                ">IQQI",
                event.sequence,
                event.received_utc_ms,
                event.received_monotonic_ns,
                len(raw),
            )
        )
        output.extend(raw)
        output.extend(bytes.fromhex(event.raw_sha256))
    return bytes(output)


def _case_material():
    base_ms = time.time_ns() // 1_000_000 - 10_000
    invocation = current_types.new_invocation(
        parent_pid=os.getpid(),
        started_ms=base_ms,
        source_map_sha256="a" * 64,
    )
    credentials = {
        "api_key": "synthetic-api-key",
        "expected_rest_uid": "12345678",
        "passphrase": "synthetic-passphrase",
        "secret_key": "synthetic-secret",
    }
    credential_packet = json.dumps(credentials, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )
    parsed_credentials = worker.parse_credentials(credential_packet)
    proof = current_types.mint_current_read_proof(
        invocation=invocation,
        receipt_sha256="b" * 64,
        account_scope_sha256=worker.account_scope_sha256(parsed_credentials),
        credential_binding_sha256=worker.credential_binding_sha256(parsed_credentials),
        expected_rest_uid=credentials["expected_rest_uid"],
        completed_ms=base_ms + 1_000,
        credential_packet=credential_packet,
        lease_set=_LeaseSet(),
        audit_directory=_AuditDirectory(),
    )
    current_types.consume_current_read_proof(proof, invocation, now_ms=base_ms + 1_100)

    connection_id = "synthetic-m01-connection"
    raw_events = (
        json.dumps(
            {"event": "login", "code": "0", "msg": "", "connId": connection_id},
            separators=(",", ":"),
        ).encode("ascii"),
        json.dumps(
            {
                "id": worker.SUBSCRIPTION_ID,
                "event": "subscribe",
                "arg": worker.BALANCE_POSITION_SUBSCRIPTION,
                "connId": connection_id,
            },
            separators=(",", ":"),
        ).encode("ascii"),
    )
    connection_event_id = contract._event_id(invocation.nonce, 1, raw_events[0])
    readiness_event_id = contract._event_id(invocation.nonce, 2, raw_events[1])
    event_times = (base_ms + 1_200, base_ms + 1_300)
    events = tuple(
        job_supervisor.PrivateEvent(
            sequence=index + 1,
            received_utc_ms=event_times[index],
            received_monotonic_ns=(index + 1) * 1_000_000,
            raw_sha256=hashlib.sha256(raw_events[index]).hexdigest(),
            raw_bytes=raw_events[index],
        )
        for index in range(2)
    )
    request = worker.LaunchRequest(
        run_nonce=invocation.nonce,
        parent_pid=invocation.parent_pid,
        worker_source_sha256=job_supervisor.PINNED_WORKER_SHA256,
        account_scope_sha256=proof.account_scope_sha256,
        credential_binding_sha256=proof.credential_binding_sha256,
        current_rest_read_receipt_sha256=proof.receipt_sha256,
        owner_invocation_sha256=proof.owner_invocation_sha256,
        event_timeout_ms=75_000,
        credential_packet=credential_packet,
    )
    context = object.__new__(job_supervisor.ObserverContext)
    context.request = request
    context._events = list(events)
    context._raw_events = list(raw_events)
    context._control = {"pid": 424_242}
    ready = job_supervisor.ObserverReady(
        run_nonce=invocation.nonce,
        parent_pid=invocation.parent_pid,
        worker_pid=424_242,
        worker_source_sha256=request.worker_source_sha256,
        account_scope_sha256=proof.account_scope_sha256,
        credential_binding_sha256=proof.credential_binding_sha256,
        current_rest_read_receipt_sha256=proof.receipt_sha256,
        owner_invocation_sha256=proof.owner_invocation_sha256,
        subscription_ack_ids=(worker.SUBSCRIPTION_ID,),
        connection_id_sha256=hashlib.sha256(connection_id.encode("ascii")).hexdigest(),
        connection_event_id=connection_event_id,
        readiness_event_id=readiness_event_id,
        balance_position_payload_count=0,
        balance_snapshot_observed=False,
    )
    context._ready = ready
    context._closed = True
    journal = worker.encode_journal(list(raw_events))
    journal_sha256 = hashlib.sha256(journal).hexdigest()
    quiet = job_supervisor.QuietWindow(
        run_nonce=invocation.nonce,
        command_id="c" * 32,
        cursor_before=2,
        cursor_after=2,
        quiet=True,
        partial_frame_clear=True,
        started_monotonic_ns=3_000_000_000,
        ended_monotonic_ns=8_000_000_000,
    )
    drain = job_supervisor.ObservationDrain(
        run_nonce=invocation.nonce,
        cursor=2,
        event_count=2,
        latest_event_sha256=events[-1].raw_sha256,
        event_journal_sha256=journal_sha256,
        events=events,
    )
    child = job_supervisor.ObserverWorkerReceipt(
        run_nonce=invocation.nonce,
        parent_pid=invocation.parent_pid,
        worker_pid=424_242,
        worker_source_sha256=request.worker_source_sha256,
        account_scope_sha256=proof.account_scope_sha256,
        credential_binding_sha256=proof.credential_binding_sha256,
        current_rest_read_receipt_sha256=proof.receipt_sha256,
        owner_invocation_sha256=proof.owner_invocation_sha256,
        connection_id_sha256=ready.connection_id_sha256,
        connection_event_id=connection_event_id,
        readiness_event_id=readiness_event_id,
        event_count=2,
        event_journal_sha256=journal_sha256,
        login_acknowledged=True,
        subscription_ack_ids=(worker.SUBSCRIPTION_ID,),
        balance_position_payload_count=0,
        balance_snapshot_observed=False,
        ready_sent=True,
        socket_closed=True,
        normal_websocket_close=True,
        control_thread_joined=True,
        reason="normal_close_requested",
        status=worker.CASE_STATUS,
    )
    context._worker_receipt = child
    close = job_supervisor.ObserverCloseReceipt(
        run_nonce=invocation.nonce,
        parent_pid=invocation.parent_pid,
        worker_pid=424_242,
        worker_source_sha256=request.worker_source_sha256,
        containment="windows_job",
        job_assigned_before_resume=True,
        process_resumed=True,
        stdin_closed=True,
        stdout_eof=True,
        stderr_eof=True,
        process_exit_observed=True,
        process_exit_code=0,
        job_active_count=0,
        drain_threads_joined=True,
        handles_closed=True,
        handle_close_failed=False,
        timed_out=False,
        forced_termination=False,
        termination_succeeded=None,
        socket_closed=True,
        normal_websocket_close=True,
        control_thread_joined=True,
        worker_receipt_valid=True,
        runtime_files_held_through_exit=True,
        runtime_files_closed=True,
        worker_receipt=child,
    )
    account_capture = current_reader.VerifiedAccountConfigurationRead(
        invocation=invocation,
        capture_id="synthetic-c01-account-capture",
        request_sha256="d" * 64,
        response_sha256="e" * 64,
        request_started_ms=base_ms + 100,
        response_received_ms=base_ms + 150,
        source_id_sha256="f" * 64,
        _seal=current_reader._CURRENT_READ_CAPABILITY,
    )
    with current_reader._CURRENT_READ_LOCK:
        current_reader._CURRENT_READ_EVIDENCE[id(proof)] = (proof, account_capture)
    summary = contract.validate_event_journal(
        raw_events,
        expected_rest_uid=proof.expected_rest_uid,
        run_nonce=invocation.nonce,
    )
    return {
        "proof": proof,
        "invocation": invocation,
        "request": request,
        "context": context,
        "ready": ready,
        "quiet": quiet,
        "drain": drain,
        "close": close,
        "raw_events": raw_events,
        "account_capture": account_capture,
        "summary": summary,
        "case_completed_ms": base_ms + 1_400,
    }


def _release_material(material):
    proof = material["proof"]
    try:
        current_reader.release_current_read_proof(proof)
    finally:
        with current_reader._CURRENT_READ_LOCK:
            current_reader._CURRENT_READ_EVIDENCE.pop(id(proof), None)


def test_v3_case_proof_passes_only_after_same_invocation_read_and_closed_owner():
    material = _case_material()
    try:
        models, action, receipt, observation, account_ref, session_id = issuer._validate_case_proof(
            **material
        )
        assert action.case_id == "M01"
        assert action.params["source_session_id"] == session_id
        assert session_id == "synthetic-m01-connection"
        assert action.binding.account_ref == account_ref
        assert receipt.operations[0].provider_request_id == material["account_capture"].capture_id
        assert observation.payload["connection_session_id"] == session_id
        assert observation.payload["readiness_session_id"] == session_id
        assert (
            observation.payload["connection_event_id"] != observation.payload["readiness_event_id"]
        )
        assert models.Status.PASS.value == "PASS"
    finally:
        _release_material(material)


def test_v3_case_proof_rejects_cross_session_ready_event():
    material = _case_material()
    try:
        wrong_session = json.dumps(
            {
                "id": worker.SUBSCRIPTION_ID,
                "event": "subscribe",
                "arg": worker.BALANCE_POSITION_SUBSCRIPTION,
                "connId": "another-session",
            },
            separators=(",", ":"),
        ).encode("ascii")
        raw_events = (material["raw_events"][0], wrong_session)
        material["raw_events"] = raw_events
        material["context"]._raw_events = list(raw_events)
        replacement_event = job_supervisor.PrivateEvent(
            sequence=2,
            received_utc_ms=material["case_completed_ms"] - 100,
            received_monotonic_ns=2_000_000,
            raw_sha256=hashlib.sha256(wrong_session).hexdigest(),
            raw_bytes=wrong_session,
        )
        material["context"]._events[1] = replacement_event
        material["drain"] = job_supervisor.ObservationDrain(
            run_nonce=material["invocation"].nonce,
            cursor=2,
            event_count=2,
            latest_event_sha256=replacement_event.raw_sha256,
            event_journal_sha256="0" * 64,
            events=tuple(material["context"]._events),
        )
        with pytest.raises((contract.CandidateError, issuer.IssuerError)):
            issuer._validate_case_proof(**material)
    finally:
        _release_material(material)


def test_v3_closure_requires_typed_worker_receipt_and_clean_exit():
    material = _case_material()
    try:
        assert issuer._close_ok(material["close"])
        forged = job_supervisor.ObserverCloseReceipt(
            **{
                **material["close"].__dict__,
                "worker_receipt": None,
            }
        )
        assert not issuer._close_ok(forged)
        forced = job_supervisor.ObserverCloseReceipt(
            **{
                **material["close"].__dict__,
                "forced_termination": True,
            }
        )
        assert not issuer._close_ok(forced)
    finally:
        _release_material(material)


def test_v3_entry_deployment_gate_precedes_c01_proof_factory(monkeypatch, capsys):
    called = []
    reader_relative = (
        "examples/000_live_certification/okx_penetration/"
        "_m01_readonly_monitor_v3/current_reader.py"
    )
    monkeypatch.setitem(
        entry._PINNED_PREIMPORTS,
        reader_relative,
        hashlib.sha256(
            current_reader.__file__ and Path(current_reader.__file__).read_bytes()
        ).hexdigest(),
    )
    monkeypatch.setattr(
        current_reader,
        "admit_source",
        lambda: (_ for _ in ()).throw(current_reader.CurrentReaderError("candidate_unregistered")),
    )
    monkeypatch.setattr(
        current_reader.C01CurrentReadFactory,
        "acquire",
        lambda *_args, **_kwargs: called.append("credential_read"),
    )
    issuer_name = "_m01_readonly_monitor_v3.issuer"
    package = sys.modules["_m01_readonly_monitor_v3"]
    cached_issuer = sys.modules.pop(issuer_name)
    cached_attribute = package.__dict__.pop("issuer", None)
    try:
        assert entry.main([]) == 2
        result = json.loads(capsys.readouterr().out)
        assert result["status"] == "BLOCKED"
        assert result["reason"] == "candidate_unregistered"
        assert called == []
    finally:
        sys.modules[issuer_name] = cached_issuer
        if cached_attribute is not None:
            package.issuer = cached_attribute


def test_v3_capture_reference_cannot_be_reconstructed_from_a_caller_token():
    material = _case_material()
    proof = material["proof"]
    invocation = material["invocation"]
    capture = material["account_capture"]
    try:
        spoof = current_reader.VerifiedAccountConfigurationRead(
            invocation=invocation,
            capture_id=capture.capture_id,
            request_sha256=capture.request_sha256,
            response_sha256=capture.response_sha256,
            request_started_ms=capture.request_started_ms,
            response_received_ms=capture.response_received_ms,
            source_id_sha256=capture.source_id_sha256,
            _seal=object(),
        )
        with current_reader._CURRENT_READ_LOCK:
            current_reader._CURRENT_READ_EVIDENCE[id(proof)] = (proof, spoof)
        with pytest.raises(current_reader.CurrentReaderError, match="not_factory_issued"):
            current_reader.verified_account_configuration_read(proof, invocation)
    finally:
        _release_material(material)


def test_v3_deployment_document_rejects_unreviewed_status_and_member_drift():
    pins = dict.fromkeys(current_reader.SOURCE_MAP_RELATIVES, "a" * 64)
    source_map = {
        "schema": current_reader.SOURCE_MAP_SCHEMA,
        "source_pins": pins,
    }
    source_map_raw = current_reader._canonical(source_map) + b"\n"
    admission = {
        "schema": current_reader.ADMISSION_SCHEMA,
        "status": "ADMITTED_SOURCE_PIN",
        "profile": current_reader.PROFILE,
        "source_map_sha256": hashlib.sha256(source_map_raw).hexdigest(),
        "review_ref": current_reader.SOURCE_REVIEW_REF,
    }
    admission_raw = current_reader._canonical(admission) + b"\n"
    loaded, loaded_pins, digest = current_reader._validate_deployment_documents(
        admission_raw, source_map_raw
    )
    assert loaded["status"] == "ADMITTED_SOURCE_PIN"
    assert loaded_pins == pins
    assert digest == admission["source_map_sha256"]

    unreviewed = {**admission, "status": "PENDING_REVIEW"}
    unreviewed_raw = current_reader._canonical(unreviewed) + b"\n"
    with pytest.raises(current_reader.CurrentReaderError, match="candidate_unregistered"):
        current_reader._validate_deployment_documents(unreviewed_raw, source_map_raw)

    drifted = {**source_map, "source_pins": {**pins, "unexpected.py": "b" * 64}}
    drifted_raw = current_reader._canonical(drifted) + b"\n"
    wrong_binding = {
        **admission,
        "source_map_sha256": hashlib.sha256(drifted_raw).hexdigest(),
    }
    wrong_binding_raw = current_reader._canonical(wrong_binding) + b"\n"
    with pytest.raises(current_reader.CurrentReaderError, match="source_map_members"):
        current_reader._validate_deployment_documents(wrong_binding_raw, drifted_raw)


@pytest.mark.skipif(os.name != "nt", reason="the production issuer requires a Windows Job")
def test_v3_full_issuer_returns_pass_only_after_audit_and_clean_lease_release(monkeypatch):
    material = _case_material()
    proof = material["proof"]
    invocation = material["invocation"]
    context = material["context"]
    directory = proof._audit_directory
    proof_lease = proof._lease_set
    admission_lease = _LeaseSet()
    private_module = SimpleNamespace()
    admission = current_reader.SourceAdmission(
        source_map_sha256=invocation.source_map_sha256,
        private_module=private_module,
        leases=admission_lease,
        _seal=current_reader._ADMISSION_CAPABILITY,
    )
    with current_reader._ADMISSION_LOCK:
        current_reader._ADMISSIONS[id(admission)] = admission

    context._deadline = time.monotonic() + 75.0
    context.events_since = lambda cursor: tuple(context._events[cursor:])
    context.wait_ready = lambda _deadline: material["ready"]
    context.assert_quiet = lambda *_args: material["quiet"]
    context.drain = lambda *_args: material["drain"]
    context.close = lambda *_args: material["close"]
    journal = _parent_journal(context._events)
    writer = _PrivateJournalWriter(directory, proof_lease.private_api, journal)
    monkeypatch.setattr(current_types, "new_invocation", lambda **_kwargs: invocation)
    monkeypatch.setattr(
        current_reader.C01CurrentReadFactory,
        "acquire",
        lambda _self, _invocation: proof,
    )
    monkeypatch.setattr(issuer, "_PrivateJournalWriter", lambda *_args: writer)
    monkeypatch.setattr(issuer.job_supervisor, "start_m01_monitor", lambda **_kwargs: context)
    monkeypatch.setattr(
        issuer,
        "_read_private_journal",
        lambda *_args: journal,
    )

    def read_audit(path, _private_module, *, maximum):
        assert maximum == 64 * 1024
        document = directory.documents[path.name]
        raw = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "ascii"
        )
        return raw, document, "synthetic-file-id"

    monkeypatch.setattr(current_reader, "_open_private_json", read_audit)
    try:
        result = issuer.run_m01_case_v3(admission)
        models = issuer.importlib.import_module("_certification.models")
        assert type(result) is models.CaseResult
        assert result.status is models.Status.PASS
        assert result.receipt_count == result.observation_count == 1
        assert writer.handle is None and writer.failed is False
        assert proof_lease.closed is True
        assert admission_lease.closed is True
        sealed_audits = [
            value
            for name, value in directory.documents.items()
            if name.startswith("m01-v3-case-seal-")
        ]
        assert len(sealed_audits) == 1
        assert sealed_audits[0]["pre_release_status"] == "PASS_SEALED_PENDING_CLEAN_RELEASE"
    finally:
        if id(proof) in current_types._ISSUED:
            current_reader.release_current_read_proof(proof)
        if id(admission) in current_reader._ADMISSIONS:
            current_reader.release_admission(admission)


@pytest.mark.skipif(os.name != "nt", reason="the production issuer requires a Windows Job")
def test_v3_uncertain_actor_close_retains_proof_and_deployment_leases(monkeypatch):
    material = _case_material()
    proof = material["proof"]
    invocation = material["invocation"]
    context = material["context"]
    proof_lease = proof._lease_set
    admission_lease = _LeaseSet()
    admission = current_reader.SourceAdmission(
        source_map_sha256=invocation.source_map_sha256,
        private_module=SimpleNamespace(),
        leases=admission_lease,
        _seal=current_reader._ADMISSION_CAPABILITY,
    )
    with current_reader._ADMISSION_LOCK:
        current_reader._ADMISSIONS[id(admission)] = admission

    context._deadline = time.monotonic() + 75.0
    context.events_since = lambda cursor: tuple(context._events[cursor:])
    context.wait_ready = lambda _deadline: material["ready"]
    context.assert_quiet = lambda *_args: material["quiet"]
    context.drain = lambda *_args: material["drain"]
    uncertain_close = job_supervisor.ObserverCloseReceipt(
        **{**material["close"].__dict__, "forced_termination": True}
    )
    context.close = lambda *_args: uncertain_close
    writer = _PrivateJournalWriter(
        proof._audit_directory, proof_lease.private_api, _parent_journal(context._events)
    )
    monkeypatch.setattr(current_types, "new_invocation", lambda **_kwargs: invocation)
    monkeypatch.setattr(
        current_reader.C01CurrentReadFactory,
        "acquire",
        lambda _self, _invocation: proof,
    )
    monkeypatch.setattr(issuer, "_PrivateJournalWriter", lambda *_args: writer)
    monkeypatch.setattr(issuer.job_supervisor, "start_m01_monitor", lambda **_kwargs: context)
    try:
        result = issuer.run_m01_case_v3(admission)
        models = issuer.importlib.import_module("_certification.models")
        assert result.status is models.Status.BLOCKED
        assert proof_lease.closed is False
        assert admission_lease.closed is False
        assert any(admission is item[0] for item in issuer._ORPHANED_CASE_CUSTODY if item)
    finally:
        issuer._ORPHANED_CASE_CUSTODY[:] = [
            item for item in issuer._ORPHANED_CASE_CUSTODY if not (item and item[0] is admission)
        ]
        if writer in issuer._ORPHANED_JOURNAL_WRITERS:
            issuer._ORPHANED_JOURNAL_WRITERS.remove(writer)
        if id(proof) in current_types._ISSUED:
            current_reader.release_current_read_proof(proof)
        if id(admission) in current_reader._ADMISSIONS:
            current_reader.release_admission(admission)


@pytest.mark.skipif(os.name != "nt", reason="the production issuer requires a Windows Job")
def test_v3_source_lease_close_failure_downgrades_sealed_candidate_to_blocked(monkeypatch):
    material = _case_material()
    proof = material["proof"]
    invocation = material["invocation"]
    context = material["context"]
    failing_lease = _FailingLeaseSet()
    object.__setattr__(proof, "_lease_set", failing_lease)
    admission_lease = _LeaseSet()
    admission = current_reader.SourceAdmission(
        source_map_sha256=invocation.source_map_sha256,
        private_module=SimpleNamespace(),
        leases=admission_lease,
        _seal=current_reader._ADMISSION_CAPABILITY,
    )
    with current_reader._ADMISSION_LOCK:
        current_reader._ADMISSIONS[id(admission)] = admission

    context._deadline = time.monotonic() + 75.0
    context.events_since = lambda cursor: tuple(context._events[cursor:])
    context.wait_ready = lambda _deadline: material["ready"]
    context.assert_quiet = lambda *_args: material["quiet"]
    context.drain = lambda *_args: material["drain"]
    context.close = lambda *_args: material["close"]
    directory = proof._audit_directory
    writer = _PrivateJournalWriter(
        directory, failing_lease.private_api, _parent_journal(context._events)
    )
    journal = writer.parts[0]
    monkeypatch.setattr(current_types, "new_invocation", lambda **_kwargs: invocation)
    monkeypatch.setattr(
        current_reader.C01CurrentReadFactory,
        "acquire",
        lambda _self, _invocation: proof,
    )
    monkeypatch.setattr(issuer, "_PrivateJournalWriter", lambda *_args: writer)
    monkeypatch.setattr(issuer.job_supervisor, "start_m01_monitor", lambda **_kwargs: context)
    monkeypatch.setattr(issuer, "_read_private_journal", lambda *_args: journal)

    def read_audit(path, _private_module, *, maximum):
        assert maximum == 64 * 1024
        document = directory.documents[path.name]
        raw = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
            "ascii"
        )
        return raw, document, "synthetic-file-id"

    monkeypatch.setattr(current_reader, "_open_private_json", read_audit)
    try:
        result = issuer.run_m01_case_v3(admission)
        models = issuer.importlib.import_module("_certification.models")
        assert result.status is models.Status.BLOCKED
        assert result.reason == "source_lease_close_uncertain"
        assert any(
            item and item[0] == "proof-release" and item[1] is proof
            for item in issuer._ORPHANED_CASE_CUSTODY
        )
    finally:
        issuer._ORPHANED_CASE_CUSTODY[:] = [
            item
            for item in issuer._ORPHANED_CASE_CUSTODY
            if not (
                item
                and (
                    item[0] == "proof-release"
                    and item[1] is proof
                    or item[0] == "admission-release"
                    and item[1] is admission
                )
            )
        ]
        with current_types._LOCK:
            current_types._ISSUED.pop(id(proof), None)
            current_types._CONSUMED.discard(id(proof))
        with current_reader._CURRENT_READ_LOCK:
            current_reader._CURRENT_READ_EVIDENCE.pop(id(proof), None)
        if id(admission) in current_reader._ADMISSIONS:
            current_reader.release_admission(admission)


def test_v3_entry_and_runner_have_no_unresolved_source_pins():
    runner_path = M01_CASE / "run.py"
    reader_relative = (
        "examples/000_live_certification/okx_penetration/"
        "_m01_readonly_monitor_v3/current_reader.py"
    )
    runner_source = runner_path.read_text(encoding="utf-8")
    reader_pin = entry._PINNED_PREIMPORTS[reader_relative]
    assert "PENDING_" not in reader_pin
    assert "PENDING_" not in runner_source
    assert hashlib.sha256(Path(current_reader.__file__).read_bytes()).hexdigest() == reader_pin
    assert hashlib.sha256(Path(entry.__file__).read_bytes()).hexdigest() in runner_source
    package_init = OKX_ROOT / "_m01_readonly_monitor_v3" / "__init__.py"
    assert hashlib.sha256(package_init.read_bytes()).hexdigest() in runner_source


@pytest.mark.parametrize(
    ("failure_stage", "expected_reason"),
    [
        ("admission", "source_admission_invalid"),
        ("current_read", "c01_account_uid_shape"),
    ],
)
def test_v3_missing_proof_preserves_first_failure_and_releases_admission(
    monkeypatch, failure_stage, expected_reason
):
    admission_lease = _LeaseSet()
    admission = current_reader.SourceAdmission(
        source_map_sha256="a" * 64,
        private_module=SimpleNamespace(),
        leases=admission_lease,
        _seal=current_reader._ADMISSION_CAPABILITY,
    )
    with current_reader._ADMISSION_LOCK:
        current_reader._ADMISSIONS[id(admission)] = admission

    monkeypatch.setattr(issuer, "os", SimpleNamespace(name="nt", getpid=os.getpid))
    monkeypatch.setattr(worker, "LIVE_TRANSPORT_ENABLEMENT", "ROOT_FIXED_ISSUER_ADMITTED")
    orphaned = []
    monkeypatch.setattr(issuer, "_ORPHANED_CASE_CUSTODY", orphaned)
    worker_starts = []
    monkeypatch.setattr(
        issuer.job_supervisor,
        "start_m01_monitor",
        lambda **_kwargs: worker_starts.append("started"),
    )
    acquire_calls = []
    release_calls = []
    original_release = current_reader.release_admission

    def fail_acquire(_factory, _invocation):
        acquire_calls.append("called")
        raise current_reader.CurrentReaderError(expected_reason)

    def release_once(token):
        release_calls.append(token)
        return original_release(token)

    if failure_stage == "admission":
        monkeypatch.setattr(
            current_reader,
            "consume_admission",
            lambda _token: (_ for _ in ()).throw(
                current_reader.CurrentReaderError(expected_reason)
            ),
        )
    else:
        monkeypatch.setattr(current_reader.C01CurrentReadFactory, "acquire", fail_acquire)
    monkeypatch.setattr(current_reader, "release_admission", release_once)

    try:
        result = issuer.run_m01_case_v3(admission)
        models = issuer.importlib.import_module("_certification.models")
        assert type(result) is models.CaseResult
        assert result.status is models.Status.BLOCKED
        assert result.reason == expected_reason
        assert result.receipt_count == result.observation_count == 0
        assert not worker_starts
        assert len(release_calls) == 1 and release_calls[0] is admission
        assert admission_lease.closed is True
        assert not orphaned
        assert acquire_calls == ([] if failure_stage == "admission" else ["called"])
        with current_reader._ADMISSION_LOCK:
            assert current_reader._ADMISSIONS.get(id(admission)) is not admission
            assert id(admission) not in current_reader._CONSUMED_ADMISSIONS
    finally:
        with current_reader._ADMISSION_LOCK:
            current_reader._ADMISSIONS.pop(id(admission), None)
            current_reader._CONSUMED_ADMISSIONS.discard(id(admission))


def test_v3_missing_proof_release_failure_reports_uncertainty_and_retains_custody(monkeypatch):
    admission_lease = _FailingLeaseSet()
    admission = current_reader.SourceAdmission(
        source_map_sha256="a" * 64,
        private_module=SimpleNamespace(),
        leases=admission_lease,
        _seal=current_reader._ADMISSION_CAPABILITY,
    )
    with current_reader._ADMISSION_LOCK:
        current_reader._ADMISSIONS[id(admission)] = admission

    monkeypatch.setattr(issuer, "os", SimpleNamespace(name="nt", getpid=os.getpid))
    monkeypatch.setattr(worker, "LIVE_TRANSPORT_ENABLEMENT", "ROOT_FIXED_ISSUER_ADMITTED")
    orphaned = []
    monkeypatch.setattr(issuer, "_ORPHANED_CASE_CUSTODY", orphaned)
    worker_starts = []
    monkeypatch.setattr(
        issuer.job_supervisor,
        "start_m01_monitor",
        lambda **_kwargs: worker_starts.append("started"),
    )
    monkeypatch.setattr(
        current_reader.C01CurrentReadFactory,
        "acquire",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            current_reader.CurrentReaderError("c01_account_uid_shape")
        ),
    )
    release_calls = []
    original_release = current_reader.release_admission

    def release_once(token):
        release_calls.append(token)
        return original_release(token)

    monkeypatch.setattr(current_reader, "release_admission", release_once)

    try:
        result = issuer.run_m01_case_v3(admission)
        models = issuer.importlib.import_module("_certification.models")
        assert type(result) is models.CaseResult
        assert result.status is models.Status.BLOCKED
        assert result.reason == "source_lease_close_uncertain"
        assert not worker_starts
        assert len(release_calls) == 1 and release_calls[0] is admission
        assert any(
            type(item) is tuple
            and len(item) == 5
            and item[0] == "admission-release"
            and item[1] is admission
            and item[2] is None
            and item[3] is None
            and item[4] is None
            for item in orphaned
        )
        with current_reader._ADMISSION_LOCK:
            assert current_reader._ADMISSIONS.get(id(admission)) is admission
            assert id(admission) in current_reader._CONSUMED_ADMISSIONS
    finally:
        with current_reader._ADMISSION_LOCK:
            current_reader._ADMISSIONS.pop(id(admission), None)
            current_reader._CONSUMED_ADMISSIONS.discard(id(admission))
