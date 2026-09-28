"""Fake-only contracts for the independent I15 TD-only candidate."""

from __future__ import annotations

import os
import sys
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backtrader_runtime import ctp_i12_td_only_latch as i12_latch
from backtrader_runtime import ctp_i12_td_only_readonly as i12
from backtrader_runtime import ctp_i15_td_only_readonly as i15
from backtrader_runtime.ctp_i15_source_identity import I15SourceIdentityBinding
from backtrader_runtime.ctp_front_pair_probe import CtpConfiguredFrontPair
from backtrader_runtime.ctp_readonly_job_supervisor import (
    FixedChildCommand,
    ProcessEvidence,
    SupervisedResult,
)
from backtrader_runtime.ctp_sdk_readonly import CtpSdkReadOnlyCloseEvidence


_I15_TEST_SOURCE_DIGEST = "9" * 64
_REAL_PARENT_SOURCE_IDENTITY_CHECK = i15._verify_i15_parent_source_identity


@pytest.fixture(autouse=True)
def _bind_fake_reviewed_i15_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i15, "_I15_PINNED_SOURCE_DIGEST", _I15_TEST_SOURCE_DIGEST)
    monkeypatch.setattr(
        i15,
        "_verify_i15_parent_source_identity",
        lambda: I15SourceIdentityBinding(_I15_TEST_SOURCE_DIGEST, 27),
    )


def _process_evidence() -> ProcessEvidence:
    return ProcessEvidence(
        process_created=True,
        job_assignment_observed=True,
        process_resumed=True,
        process_exit_observed=True,
        process_exit_code=0,
        job_termination_requested=False,
        job_termination_call_succeeded=None,
        job_empty_observed=True,
        containment="verified",
    )


def _artifact_result(
    *, verified: bool, source_digest: str = _I15_TEST_SOURCE_DIGEST
) -> SupervisedResult:
    token_hi, token_lo = i15._source_digest_tokens(source_digest)
    return SupervisedResult(
        "child_exited",
        "child_process_exited",
        {
            "credential_resolver_invoked": False,
            "native_join_pending": False,
            "reason": "artifact_verified" if verified else "artifact_rejected",
            "sdk_imported": False,
            "candidate_id": i15.I15_CANDIDATE_ID,
            "source_identity": "verified",
            "source_manifest_token_hi": token_hi,
            "source_manifest_token_lo": token_lo,
            "status": "verified" if verified else "rejected",
        },
        _process_evidence(),
    )


class _MemoryLatch:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.tripped = False

    def is_tripped(self) -> bool:
        self.calls.append("read")
        return self.tripped

    def begin_attempt(self) -> bool:
        self.calls.append("begin")
        if self.tripped:
            return False
        self.tripped = True
        return True

    def trip(self, _reason: str) -> bool:
        self.calls.append("trip")
        self.tripped = True
        return True


def _i15_receipt(*, complete: bool) -> dict[str, object]:
    receipt = i12._initial_receipt(
        reason="td_readonly_query_bundle_closed" if complete else "native_join_pending",
        stage="td_session",
    )
    receipt.update(candidate_id=i15.I15_CANDIDATE_ID, marker_scope="i15_unique")
    token_hi, token_lo = i15._source_digest_tokens(_I15_TEST_SOURCE_DIGEST)
    receipt.update(
        source_identity="verified",
        source_manifest_token_hi=token_hi,
        source_manifest_token_lo=token_lo,
    )
    if complete:
        receipt.update(
            status="td_readonly_complete",
            login_state="verified",
            query_bundle_complete=True,
            query_values_redacted=True,
            write_counts_state="zero",
            margin_rate_exchange_scope="unverified",
            commission_rate_exchange_scope="unverified",
            close_state="complete",
            native_join_pending=False,
            native_release_complete=True,
            join_required=True,
            join_completed=True,
            client_stop_returned=True,
        )
        for key in (
            "query_account_state",
            "query_positions_state",
            "query_orders_state",
            "query_trades_state",
            "query_instruments_state",
            "query_margin_rate_state",
            "query_commission_rate_state",
        ):
            receipt[key] = "complete"
    else:
        receipt.update(
            status="incomplete",
            close_state="native_join_pending",
            native_join_pending=True,
            native_release_complete=True,
            join_required=True,
            join_completed=False,
            client_stop_returned=True,
        )
    return receipt


def _child_result(*, complete: bool) -> SupervisedResult:
    return SupervisedResult(
        "child_exited" if complete else "pending_native_join",
        "child_process_exited" if complete else "native_join_pending",
        _i15_receipt(complete=complete),
        _process_evidence(),
    )


def _protect_test_directory(path: Path) -> None:
    path.mkdir()
    if os.name == "nt":
        from backtrader_runtime.ctp_private_config_setup import (
            _protect_target_directory,
            _verified_target_directory,
        )

        with _verified_target_directory(path) as descriptor:
            _protect_target_directory(descriptor)
    else:
        path.chmod(0o700)


def test_i15_marker_is_unique_one_shot_and_does_not_touch_synthetic_i12_marker(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    _protect_test_directory(state)
    synthetic_i12 = state / "synthetic-i12-marker-do-not-use.latch"
    synthetic_i12_bytes = b"i12-already-consumed-sentinel\n"
    synthetic_i12.write_bytes(synthetic_i12_bytes)
    marker = state / "i15-test-only.latch"

    first = i15.PersistentI15TdOnlyAttemptLatch(marker)
    assert first.begin_attempt() is True
    assert marker.read_bytes() == i15._I15_MARKER_CONTENT
    assert synthetic_i12.read_bytes() == synthetic_i12_bytes

    restarted = i15.PersistentI15TdOnlyAttemptLatch(marker)
    assert restarted.is_tripped() is True
    assert restarted.begin_attempt() is False
    assert synthetic_i12.read_bytes() == synthetic_i12_bytes
    assert i15.I15_LATCH_PATH != i12_latch.I12_LATCH_PATH
    assert i15._I15_MARKER_CONTENT != i12_latch.I12_LATCH_CONTENT


def test_i15_child_context_reads_only_its_job_and_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _OnlyI15Latch:
        def __init__(self, path: Path) -> None:
            assert path == i15.I15_LATCH_PATH

        def is_tripped(self) -> bool:
            calls.append("i15_marker")
            return True

    monkeypatch.setattr(
        i15, "_is_current_process_in_i15_job", lambda: calls.append("i15_job") or True
    )
    monkeypatch.setattr(i15, "PersistentI15TdOnlyAttemptLatch", _OnlyI15Latch)
    assert i15._has_supervised_i15_attempt_context() is True
    assert calls == ["i15_job", "i15_marker"]
    assert not hasattr(i15, "PersistentI12TdOnlyAttemptLatch")


def test_i15_fixed_command_binds_i12_selected_pair_and_uses_i15_job_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = i12.I12FrontPrecheckBinding(2, "a" * 64)
    base = FixedChildCommand(
        (sys.executable, "-c", "old-entry"),
        Path.cwd(),
        {i12._I12_PRECHECK_INDEX_ENV: "2", i12._I12_PRECHECK_BINDING_ENV: "a" * 64},
        job_handle_env_name=i12._I12_JOB_HANDLE_ENV,
    )
    monkeypatch.setattr(
        i12, "_fixed_i12_child_command", lambda received: base if received == binding else None
    )
    monkeypatch.setattr(i12, "_is_concrete_path", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(i15, "render_i15_source_verifier_bootstrap", lambda **_kwargs: "bootstrap")

    command = i15._fixed_i15_child_command(binding)

    assert command is not None
    assert command.argv[:5] == (sys.executable, "-I", "-S", "-B", "-X")
    assert command.argv[5].startswith("pycache_prefix=")
    assert command.argv[6] == "-c"
    assert "_I15_SOURCE_EXPECTED" in command.argv[7]
    assert "_install_i15_sealed_importer()" in command.argv[7]
    assert "_i15_add_fixed_install_root()" in command.argv[7]
    assert "_i15_bind_fixed_artifact_install_root()" in command.argv[7]
    assert "_verify_i15_import_origins()" in command.argv[7]
    assert "sys.path.insert(0," not in command.argv[7]
    assert command.env[i12._I12_PRECHECK_INDEX_ENV] == "2"
    assert command.env[i12._I12_PRECHECK_BINDING_ENV] == "a" * 64
    assert command.env[i15.I15_SOURCE_MANIFEST_ENV] == _I15_TEST_SOURCE_DIGEST
    assert command.job_handle_env_name == i15._I15_JOB_HANDLE_ENV


def test_i15_metadata_command_binds_same_source_digest_and_cache_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    worker = FixedChildCommand(
        (sys.executable, "-I", "-B", "-c", "worker"),
        Path.cwd(),
        {i12._I12_PRECHECK_INDEX_ENV: "0"},
    )
    metadata_code = f"sys.path.insert(0, {str(Path.cwd())!r})\n" "payload = {}\n"
    metadata = FixedChildCommand(
        (sys.executable, "-I", "-B", "-c", metadata_code),
        Path.cwd(),
        dict(worker.env),
    )
    monkeypatch.setattr(i12, "_fixed_i12_artifact_preflight_command", lambda _worker: metadata)
    monkeypatch.setattr(i12, "_is_concrete_path", lambda *_args, **_kwargs: True)
    prefix = tmp_path / "unused-cache-prefix"
    monkeypatch.setattr(i15, "_new_i15_pycache_prefix", lambda: prefix)
    monkeypatch.setattr(i15, "render_i15_source_verifier_bootstrap", lambda **_kwargs: "bootstrap")

    command = i15._fixed_i15_artifact_preflight_command(
        worker, source_digest=_I15_TEST_SOURCE_DIGEST
    )

    assert command is not None
    assert command.argv[:7] == (
        sys.executable,
        "-I",
        "-S",
        "-B",
        "-X",
        "pycache_prefix=" + str(prefix),
        "-c",
    )
    assert "source_manifest_token_hi" in command.argv[7]
    assert "_install_i15_sealed_importer()" in command.argv[7]
    assert "_i15_add_fixed_install_root()" in command.argv[7]
    assert "_i15_bind_fixed_artifact_install_root()" in command.argv[7]
    assert "sys.path.insert(0," not in command.argv[7]
    assert command.env[i15.I15_SOURCE_MANIFEST_ENV] == _I15_TEST_SOURCE_DIGEST


def test_i15_source_identity_failure_precedes_precheck_job_and_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    latch = _MemoryLatch()
    monkeypatch.setattr(i15.os, "name", "nt")
    monkeypatch.setattr(i15, "_I15_PINNED_SOURCE_DIGEST", None)
    monkeypatch.setattr(i15, "_verify_i15_parent_source_identity", lambda: None)

    report = i15._supervise_i15_child(
        precheck=lambda _deadline: calls.append("precheck"),
        command_builder=lambda _binding, _digest: calls.append("worker"),
        artifact_command_builder=lambda _worker, _digest: calls.append("metadata"),
        latch_factory=lambda _path: latch,
        runner=lambda *_args, **_kwargs: calls.append("job"),
    )

    assert report.status == "rejected"
    assert report.reason == "source_identity_unavailable"
    assert calls == []
    assert latch.calls == []


def test_parent_source_identity_rejects_import_origin_outside_pinned_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    monkeypatch.setattr(
        i15, "_verify_i15_parent_source_identity", _REAL_PARENT_SOURCE_IDENTITY_CHECK
    )
    package = root / "backtrader_runtime"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    candidate_file = package / "ctp_i15_td_only_readonly.py"
    candidate_file.write_text("", encoding="utf-8")
    pin_file = package / "ctp_i15_source_identity_pin.py"
    pin_file.write_text("", encoding="utf-8")
    source_files = (
        "backtrader_runtime/__init__.py",
        "backtrader_runtime/ctp_i15_td_only_readonly.py",
    )
    monkeypatch.setattr(i15, "__file__", str(candidate_file))
    monkeypatch.setattr(i15, "discover_i15_source_files", lambda _root: source_files)
    monkeypatch.setattr(
        i15,
        "verify_i15_source_identity",
        lambda _root, *, expected_manifest_sha256: I15SourceIdentityBinding(
            expected_manifest_sha256, len(source_files)
        ),
    )
    for name in tuple(sys.modules):
        if name == "backtrader_runtime" or name.startswith("backtrader_runtime."):
            monkeypatch.delitem(sys.modules, name, raising=False)
        if name == "backtrader" or name.startswith("backtrader."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(
        sys.modules,
        "backtrader_runtime",
        SimpleNamespace(
            __file__=str(package / "__init__.py"),
            __path__=[str(package)],
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "backtrader_runtime.ctp_i15_td_only_readonly",
        SimpleNamespace(__file__=str(candidate_file)),
    )
    monkeypatch.setitem(
        sys.modules,
        "backtrader_runtime.ctp_i15_source_identity_pin",
        SimpleNamespace(__file__=str(pin_file)),
    )

    assert i15._verify_i15_parent_source_identity() == I15SourceIdentityBinding(
        _I15_TEST_SOURCE_DIGEST, len(source_files)
    )

    monkeypatch.setitem(
        sys.modules,
        "backtrader_runtime.ctp_i15_td_only_readonly",
        SimpleNamespace(__file__=str(tmp_path / "foreign" / "ctp_i15_td_only_readonly.py")),
    )
    assert i15._verify_i15_parent_source_identity() is None


def test_i15_child_rechecks_same_sealed_pair_and_constructs_typed_route_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    md_front = "tcp://192.0.2.101:41001"
    td_front = "tcp://192.0.2.102:41002"
    pair_mapping = {"md_front": md_front, "td_front": td_front}
    expected_binding = i12.I12FrontPrecheckBinding(0, "b" * 64)
    effective = SimpleNamespace(
        effective_digest="c" * 64,
        registration=SimpleNamespace(digest="d" * 64),
    )
    calls: list[object] = []
    emitted: list[dict[str, object]] = []
    admission = SimpleNamespace(
        environment="simnow",
        sdk_profile="config_front_pair",
        md_front=md_front,
        td_front=td_front,
        account_fingerprint_sha256="e" * 64,
        instrument_id="rb2710",
        exchange_id="SHFE",
        hedge_flag="1",
        session_ttl_seconds=10.0,
    )

    class _Binding:
        def _route(
            self,
            received_effective: object,
            received_registry: object,
            *,
            selected_front_pair: object,
            selected_config_index: int,
        ) -> tuple[object, object]:
            calls.append(("route", received_effective, selected_front_pair, selected_config_index))
            assert received_effective is effective
            assert type(selected_front_pair) is CtpConfiguredFrontPair
            assert (selected_front_pair.md_front, selected_front_pair.td_front) == (
                md_front,
                td_front,
            )
            assert selected_config_index == 0
            return admission, object()

    private = SimpleNamespace(instrument_id="rb2710", exchange_id="SHFE", hedge_flag="1")
    monkeypatch.setattr(sys, "argv", ["i15-child"])
    monkeypatch.setattr(i15, "_has_supervised_i15_attempt_context", lambda: True)
    monkeypatch.setenv(i15.I15_SOURCE_MANIFEST_ENV, _I15_TEST_SOURCE_DIGEST)
    monkeypatch.setattr(
        i15,
        "verify_i15_source_identity",
        lambda _root, *, expected_manifest_sha256: I15SourceIdentityBinding(
            expected_manifest_sha256, 27
        ),
    )
    monkeypatch.setattr(i12, "I12_SDK_SOURCE_COMMIT", "a6253a58b1ebca11f58c8836fbed757d0daf7582")
    monkeypatch.setattr(i12, "_child_recheck_precheck_binding", lambda: expected_binding)
    monkeypatch.setattr(
        i12,
        "_load_sealed_context",
        lambda: (effective, object(), _Binding(), private, (pair_mapping,)),
    )
    monkeypatch.setattr(
        i12,
        "_front_binding_digest",
        lambda **_kwargs: expected_binding,
    )
    monkeypatch.setattr(
        i12,
        "trusted_installed_capability_import_context",
        lambda _names: nullcontext(),
    )
    monkeypatch.setattr(
        i12,
        "verify_ctp_i12_td_only_readonly_artifact_provenance_for_fronts",
        lambda **kwargs: calls.append(("artifact", kwargs["md_front"], kwargs["td_front"])),
    )
    monkeypatch.setattr(
        i12,
        "_validate_bound_scope",
        lambda _private, _admission, index, pairs: calls.append(
            ("scope", index, pairs[index]["md_front"], pairs[index]["td_front"])
        ),
    )

    import backtrader_runtime.ctp_sandbox_readonly_admission as readonly_admission
    import backtrader_runtime.credential_resolver as credential_resolver
    import backtrader_runtime.ctp_sdk_readonly as sdk_readonly
    import backtrader_runtime.ctp_preflight as preflight

    monkeypatch.setattr(
        readonly_admission,
        "require_ctp_sandbox_readonly_runtime_contract",
        lambda _effective, _registry, value: value,
    )
    monkeypatch.setattr(credential_resolver, "resolve_runtime_credentials", lambda *_args: object())
    monkeypatch.setattr(
        credential_resolver,
        "require_resolved_runtime_credentials_seal",
        lambda *_args: None,
    )

    class _Factory:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            calls.append("factory")

    monkeypatch.setattr(sdk_readonly, "CtpSdkReadOnlySessionFactory", _Factory)
    evidence = i12.I12TdOnlySessionEvidence(
        "td_readonly_complete",
        "td_readonly_query_bundle_closed",
        "verified",
        True,
        "unverified",
        "unverified",
        "zero",
        CtpSdkReadOnlyCloseEvidence(
            "complete",
            native_released=True,
            join_required=True,
            join_completed=True,
            thread_alive=False,
            timed_out=False,
            client_stop_returned=True,
        ),
    )
    monkeypatch.setattr(i12, "_run_i12_td_only_session_candidate", lambda *_args: evidence)
    monkeypatch.setattr(i15, "_emit_i15", lambda fields: emitted.append(dict(fields)))
    monkeypatch.setattr(preflight, "CTP_PROVIDER", "ctp")

    exit_code = i15._run_i15_child_diagnostic()

    assert exit_code == 0, (emitted[0].get("stage"), emitted[0].get("reason"), calls)
    assert calls[0] == ("artifact", md_front, td_front)
    assert calls[1][0] == "route"
    assert calls[2] == ("scope", 0, md_front, td_front)
    assert calls[3] == "factory"
    assert emitted[0]["candidate_id"] == i15.I15_CANDIDATE_ID
    assert emitted[0]["marker_scope"] == "i15_unique"
    assert emitted[0]["order_submission_authorized"] is False
    assert emitted[0]["settlement_confirmation_called"] is False


def test_i15_artifact_rejection_does_not_read_or_reserve_i15_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = i12.I12FrontPrecheckBinding(0, "f" * 64)
    command = FixedChildCommand((sys.executable,), Path.cwd(), {})
    latch = _MemoryLatch()
    calls: list[str] = []
    monkeypatch.setattr(i15.os, "name", "nt")
    report = i15._supervise_i15_child(
        precheck=lambda _deadline: binding,
        command_builder=lambda _binding, _digest: command,
        artifact_command_builder=lambda _worker, _digest: command,
        latch_factory=lambda _path: latch,
        runner=lambda *_args, **_kwargs: calls.append("job") or _artifact_result(verified=False),
    )

    assert report.status == "rejected"
    assert report.reason == "sdk_artifact_rejected"
    assert report.artifact_pin_verified is False
    assert calls == ["job"]
    assert latch.calls == []


def test_i15_deadline_expiry_during_precheck_precedes_latch_and_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [10.0]
    monkeypatch.setattr(i15.os, "name", "nt")
    monkeypatch.setattr(i15.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(i15, "_I15_TOTAL_DEADLINE_SECONDS", 5.0)
    binding = i12.I12FrontPrecheckBinding(0, "f" * 64)
    latch = _MemoryLatch()
    calls: list[str] = []

    def precheck(deadline: float) -> i12.I12FrontPrecheckBinding:
        assert deadline == 15.0
        now[0] = deadline
        return binding

    report = i15._supervise_i15_child(
        precheck=precheck,
        command_builder=lambda _binding, _digest: calls.append("command"),
        artifact_command_builder=lambda _worker, _digest: calls.append("artifact_command"),
        latch_factory=lambda _path: latch,
        runner=lambda *_args, **_kwargs: calls.append("job"),
    )

    assert report.status == "incomplete"
    assert report.reason == "child_deadline_exceeded"
    assert calls == []
    assert latch.calls == []


def test_i15_native_join_pending_stays_incomplete_after_reserved_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = i12.I12FrontPrecheckBinding(0, "f" * 64)
    command = FixedChildCommand((sys.executable,), Path.cwd(), {})
    latch = _MemoryLatch()
    runner_calls: list[str] = []
    command_digests: list[str] = []
    metadata_digests: list[str] = []
    schema_tokens: list[tuple[frozenset[str], frozenset[str]]] = []

    def worker_builder(_binding: object, digest: str) -> FixedChildCommand:
        command_digests.append(digest)
        return command

    def metadata_builder(_worker: FixedChildCommand, digest: str) -> FixedChildCommand:
        metadata_digests.append(digest)
        return command

    def runner(*_args: object, **kwargs: Any) -> SupervisedResult:
        if "marker_scope" not in kwargs["receipt_schema"].enum_fields:
            runner_calls.append("artifact")
            schema_tokens.append(
                (
                    kwargs["receipt_schema"].enum_fields["source_manifest_token_hi"],
                    kwargs["receipt_schema"].enum_fields["source_manifest_token_lo"],
                )
            )
            return _artifact_result(verified=True)
        runner_calls.append("td")
        schema_tokens.append(
            (
                kwargs["receipt_schema"].enum_fields["source_manifest_token_hi"],
                kwargs["receipt_schema"].enum_fields["source_manifest_token_lo"],
            )
        )
        return _child_result(complete=False)

    monkeypatch.setattr(i15.os, "name", "nt")
    report = i15._supervise_i15_child(
        precheck=lambda _deadline: binding,
        command_builder=worker_builder,
        artifact_command_builder=metadata_builder,
        latch_factory=lambda _path: latch,
        runner=runner,
    )

    assert report.status == "incomplete", (report.reason, report.as_dict(), schema_tokens)
    assert report.reason == "native_join_pending"
    assert report.attempt_reserved is True
    assert runner_calls == ["artifact", "td"]
    assert command_digests == [_I15_TEST_SOURCE_DIGEST]
    assert metadata_digests == [_I15_TEST_SOURCE_DIGEST]
    expected_tokens = i15._source_digest_tokens(_I15_TEST_SOURCE_DIGEST)
    assert len(schema_tokens) == 2
    assert all(
        expected_tokens[0] in high and expected_tokens[1] in low for high, low in schema_tokens
    )
    assert latch.calls == ["read", "begin"]
    assert report.as_dict()["sdk_receipt"]["candidate_id"] == i15.I15_CANDIDATE_ID


def test_i15_complete_requires_its_receipt_identity_and_i12_close_predicate() -> None:
    complete = _child_result(complete=True)
    report = i15._report_from_child(
        complete,
        artifact_containment="verified",
        attempt_reserved=True,
        source_digest=_I15_TEST_SOURCE_DIGEST,
    )

    assert report.status == "td_readonly_complete"
    assert report.reason == "td_readonly_query_bundle_closed"
    assert report.as_dict()["artifact_pin_source"] == i15.I15_ARTIFACT_PIN_SOURCE

    wrong_candidate = dict(complete.sdk_receipt)
    wrong_candidate["candidate_id"] = "i12_td_only"
    rejected = i15._report_from_child(
        SupervisedResult(
            complete.status,
            complete.reason,
            wrong_candidate,
            complete.process_evidence,
        ),
        artifact_containment="verified",
        attempt_reserved=True,
        source_digest=_I15_TEST_SOURCE_DIGEST,
    )
    assert rejected.status == "supervisor_error"


@pytest.mark.parametrize("complete", [True, False])
def test_i15_receipt_requires_its_own_candidate_and_marker_scope(complete: bool) -> None:
    receipt = _i15_receipt(complete=complete)
    raw = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"

    assert i15.parse_i15_child_receipt(raw) == receipt
    receipt["marker_scope"] = "i12_reused"
    bad = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    assert i15.parse_i15_child_receipt(bad) is None
