"""Fake-only safety contracts for the unregistered I11 MD composition."""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backtrader_runtime import ctp_i11_oneshot_md_diagnostic as diagnostic
from backtrader_runtime.ctp_i10_oneshot_md_readonly import (
    CtpI10OneShotMdProgressEvidence,
)
from backtrader_runtime.ctp_readonly_job_supervisor import (
    FixedChildCommand,
    ProcessEvidence,
    SupervisedResult,
)


CONFIG_DIGEST = "a" * 64


def _pair_result(
    *,
    index: int = 0,
    md_connected: int = 3,
    td_connected: int = 3,
    secret_marker: str | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "config_index": index,
        "md_connected_count": md_connected,
        "md_sample_count": 3,
        "status": "reachable"
        if md_connected == 3 and td_connected == 3
        else "partial"
        if md_connected or td_connected
        else "unreachable",
        "td_connected_count": td_connected,
        "td_sample_count": 3,
    }
    if secret_marker is not None:
        value["secret_marker"] = secret_marker
    return value


def _front_check(*, index: int = 0, pair_count: int = 1) -> SimpleNamespace:
    pairs = tuple(_pair_result(index=i) for i in range(pair_count))
    return SimpleNamespace(
        configured_pair_count=pair_count,
        pairs=pairs,
        selected_config_index=index,
        status="selected",
    )


def _complete_receipt(*, index: int = 0, **changes: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "account_ready": False,
        "client_stop_returned": True,
        "close_state": "verified_closed",
        "credential_resolver_invoked": True,
        "effective_config_digest_match": True,
        "login_identity_state": "identity_unverified",
        "market_login_ready": False,
        "matching_tick_observed": True,
        "native_join_pending": False,
        "order_submission_authorized": False,
        "probe_session_closed": True,
        "reason": "matching_tick_observed",
        "same_trading_day_observed": True,
        "sdk_imported": True,
        "selected_pair_index": f"pair_{index}",
        "settlement_writes": "zero",
        "stage": "market_data",
        "status": "diagnostic_complete",
        "subscription_acknowledged": True,
        "trading_ready": False,
        "trading_writes": "zero",
    }
    receipt.update(changes)
    return receipt


def _complete_evidence(**changes: object) -> ProcessEvidence:
    values: dict[str, object] = {
        "process_created": True,
        "job_assignment_observed": True,
        "process_resumed": True,
        "process_exit_observed": True,
        "process_exit_code": 0,
        "job_termination_requested": False,
        "job_termination_call_succeeded": None,
        "job_empty_observed": True,
        "containment": "verified",
    }
    values.update(changes)
    return ProcessEvidence(**values)  # type: ignore[arg-type]


def _artifact_result() -> SupervisedResult:
    return SupervisedResult(
        "child_exited",
        "child_process_exited",
        {
            "credential_resolver_invoked": False,
            "native_join_pending": False,
            "reason": "artifact_verified",
            "sdk_imported": False,
            "status": "verified",
        },
        _complete_evidence(),
    )


def test_front_precheck_failure_does_not_build_commands_or_reserve_i11(monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(diagnostic, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(
        diagnostic,
        "require_effective_runtime_config_seal",
        lambda *_args: events.append("seal"),
    )
    latch_factory = lambda _path: events.append("latch")  # noqa: E731
    command_factory = lambda **_kwargs: events.append("command")  # noqa: E731
    runner = lambda *_args, **_kwargs: events.append("runner")  # noqa: E731

    failed = _front_check(index=0, pair_count=2)
    failed.status = "no_pair_reachable"
    failed.selected_config_index = None
    failed.pairs = (
        _pair_result(index=0, md_connected=0, td_connected=0),
        _pair_result(index=1, md_connected=0, td_connected=0),
    )
    report = diagnostic._supervise_i11_child(
        registry=object(),
        effective=SimpleNamespace(effective_digest=CONFIG_DIGEST),
        front_check=lambda *_args: events.append("front_check") or failed,
        latch_factory=latch_factory,
        command_factory=command_factory,
        runner=runner,
    )

    assert report.status == "rejected"
    assert report.reason == "front_precheck_failed"
    assert report.attempt_reserved is False
    assert events == ["seal", "front_check"]
    public = report.as_public_dict()
    assert [item["config_index"] for item in public["front_precheck"]["pairs"]] == [0, 1]
    assert public["front_precheck"]["reachable_pair_count"] == 0


def test_safe_front_precheck_projects_only_fixed_value_free_fields():
    check = {
        "configured_pair_count": 1,
        "pairs": (_pair_result(index=0, secret_marker="front-account-secret"),),
        "selected_config_index": 0,
        "status": "selected",
    }

    safe = diagnostic._safe_front_precheck(check)

    assert safe["status"] == "selected"
    assert safe["selected_config_index"] == 0
    assert safe["pairs"] == [_pair_result(index=0)]
    assert "secret_marker" not in json.dumps(safe)


def test_safe_front_precheck_rejects_bad_counts_or_unreachable_selection():
    two_samples = _pair_result(index=0)
    two_samples["md_sample_count"] = 2
    malformed = {
        "configured_pair_count": 1,
        "pairs": (two_samples,),
        "selected_config_index": 0,
        "status": "selected",
    }
    unreachable = {
        "configured_pair_count": 1,
        "pairs": (_pair_result(index=0, md_connected=0, td_connected=0),),
        "selected_config_index": 0,
        "status": "selected",
    }
    incomplete_candidate_set = {
        "configured_pair_count": 2,
        "pairs": (
            _pair_result(index=0),
            {
                "config_index": 1,
                "md_connected_count": 0,
                "md_sample_count": 0,
                "status": "unavailable",
                "td_connected_count": 0,
                "td_sample_count": 0,
            },
        ),
        "selected_config_index": 0,
        "status": "selected",
    }

    assert diagnostic._safe_front_precheck(malformed)["status"] == "rejected"
    assert diagnostic._safe_front_precheck(unreachable)["status"] == "rejected"
    assert diagnostic._safe_front_precheck(incomplete_candidate_set)["status"] == "rejected"


def test_parent_runs_fixed_venv_artifact_job_then_reserves_latch_then_worker(monkeypatch):
    events: list[object] = []
    monkeypatch.setattr(diagnostic, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(
        diagnostic,
        "require_effective_runtime_config_seal",
        lambda *_args: events.append("sealed"),
    )
    monkeypatch.setattr(
        diagnostic,
        "_require_exact_child_scope",
        lambda *_args: (None, None, None, None, ({"td_front": "x", "md_front": "y"},)),
    )

    worker_command: FixedChildCommand | None = None

    def command_factory(**kwargs: object) -> FixedChildCommand:
        nonlocal worker_command
        events.append(("worker_command", kwargs))
        assert kwargs == {
            "expected_config_digest": CONFIG_DIGEST,
            "expected_config_index": 0,
        }
        worker_command = FixedChildCommand(
            (r"D:\temp\i10-runtime-env-20260925\Scripts\python.exe", "-c", "worker"),
            Path(r"D:\source_code\backtrader"),
            {
                diagnostic._I11_PARENT_CONFIG_DIGEST_ENV: CONFIG_DIGEST,
                diagnostic._I11_PARENT_SELECTED_INDEX_ENV: "0",
                "PATH": r"D:\fixed-venv\Scripts",
            },
            job_handle_env_name=diagnostic._I11_JOB_HANDLE_ENV,
        )
        return worker_command

    class _Latch:
        def begin_attempt(self) -> bool:
            events.append(("begin_attempt", diagnostic.I11_LATCH_PATH))
            return True

    def runner(command: FixedChildCommand, parser, **kwargs: object) -> SupervisedResult:
        events.append(("run", command, kwargs))
        if kwargs["receipt_schema"] is diagnostic._ARTIFACT_PREFLIGHT_SCHEMA:
            assert command.argv[0] == str(diagnostic._I11_INTERPRETER)
            assert command.argv[1] == "-I"
            assert command.argv[2] == "-B"
            assert diagnostic._I11_PARENT_CONFIG_DIGEST_ENV not in command.env
            assert diagnostic._I11_PARENT_SELECTED_INDEX_ENV not in command.env
            assert diagnostic._EXPECTED_I10_SDK_SOURCE_COMMIT in command.argv[4]
            assert diagnostic._EXPECTED_I10_WHEEL_SHA256 in command.argv[4]
            return _artifact_result()
        assert command is worker_command
        assert command.env[diagnostic._I11_PARENT_CONFIG_DIGEST_ENV] == CONFIG_DIGEST
        assert command.env[diagnostic._I11_PARENT_SELECTED_INDEX_ENV] == "0"
        return SupervisedResult(
            "child_exited",
            "child_process_exited",
            _complete_receipt(index=0),
            _complete_evidence(),
        )

    report = diagnostic._supervise_i11_child(
        registry=object(),
        effective=SimpleNamespace(effective_digest=CONFIG_DIGEST),
        front_check=lambda *_args: events.append("front_check") or _front_check(),
        latch_factory=lambda _path: _Latch(),
        command_factory=command_factory,
        runner=runner,
    )

    labels = [entry[0] if isinstance(entry, tuple) else entry for entry in events]
    assert labels.index("sealed") < labels.index("front_check") < labels.index("worker_command")
    artifact_run, worker_run = [
        entry for entry in events if isinstance(entry, tuple) and entry[0] == "run"
    ]
    assert artifact_run[2]["deadline_seconds"] == 10.0
    assert artifact_run[2]["termination_grace_seconds"] == 2.0
    assert worker_run[2]["deadline_seconds"] == diagnostic._I11_TOTAL_DEADLINE_SECONDS == 45.0
    assert worker_run[2]["termination_grace_seconds"] == diagnostic._I11_TERMINATION_GRACE_SECONDS
    begin_at = labels.index("begin_attempt")
    runs_at = [index for index, label in enumerate(labels) if label == "run"]
    assert runs_at[0] < begin_at < runs_at[1]
    assert (
        next(
            entry[1] for entry in events if isinstance(entry, tuple) and entry[0] == "begin_attempt"
        )
        == diagnostic.I11_LATCH_PATH
    )
    assert report.status == "diagnostic_complete"
    assert report.attempt_reserved is True
    assert report.as_public_dict()["sdk_receipt"]["login_identity_state"] == "identity_unverified"
    assert report.as_public_dict()["sdk_receipt"]["account_ready"] is False


def test_artifact_pin_preflight_failure_keeps_i11_marker_unconsumed(monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(diagnostic, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(diagnostic, "require_effective_runtime_config_seal", lambda *_args: None)
    monkeypatch.setattr(
        diagnostic,
        "_require_exact_child_scope",
        lambda *_args: (None, None, None, None, ({"td_front": "x", "md_front": "y"},)),
    )
    command = FixedChildCommand(
        (r"D:\fixed-venv\Scripts\python.exe", "-c", "worker"),
        Path(r"D:\source_code\backtrader"),
        {
            diagnostic._I11_PARENT_CONFIG_DIGEST_ENV: CONFIG_DIGEST,
            diagnostic._I11_PARENT_SELECTED_INDEX_ENV: "0",
        },
    )

    def runner(_command, _parser, **_kwargs):
        events.append("artifact_job")
        return SupervisedResult(
            "child_exited",
            "child_process_exited",
            {
                "credential_resolver_invoked": False,
                "native_join_pending": False,
                "reason": "artifact_rejected",
                "sdk_imported": False,
                "status": "rejected",
            },
            _complete_evidence(),
        )

    report = diagnostic._supervise_i11_child(
        registry=object(),
        effective=SimpleNamespace(effective_digest=CONFIG_DIGEST),
        front_check=lambda *_args: _front_check(),
        latch_factory=lambda _path: events.append("latch"),
        command_factory=lambda **_kwargs: command,
        runner=runner,
    )

    assert report.attempt_reserved is False
    assert report.artifact_pin_verified is False
    assert events == ["artifact_job"]


@pytest.mark.parametrize(
    ("runner_status", "evidence_changes"),
    [
        (
            "timed_out",
            {
                "process_exit_observed": False,
                "process_exit_code": None,
                "job_termination_requested": True,
                "job_termination_call_succeeded": True,
                "job_empty_observed": True,
                "containment": "verified",
            },
        ),
        (
            "supervisor_error",
            {
                "job_assignment_observed": False,
                "process_resumed": False,
                "job_empty_observed": None,
                "containment": "uncertain",
            },
        ),
        (
            "supervisor_error",
            {
                "job_empty_observed": None,
                "containment": "uncertain",
            },
        ),
    ],
    ids=("artifact-job-timeout", "job-assignment-missing", "job-empty-unknown"),
)
def test_artifact_job_containment_failures_do_not_consume_marker_or_start_worker(
    monkeypatch, runner_status, evidence_changes
):
    events: list[str] = []
    monkeypatch.setattr(diagnostic, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(diagnostic, "require_effective_runtime_config_seal", lambda *_args: None)
    monkeypatch.setattr(
        diagnostic,
        "_require_exact_child_scope",
        lambda *_args: (None, None, None, None, ({"td_front": "x", "md_front": "y"},)),
    )
    command = FixedChildCommand(
        (r"D:\fixed-venv\Scripts\python.exe", "-c", "worker"),
        Path(r"D:\source_code\backtrader"),
        {
            diagnostic._I11_PARENT_CONFIG_DIGEST_ENV: CONFIG_DIGEST,
            diagnostic._I11_PARENT_SELECTED_INDEX_ENV: "0",
        },
    )
    artifact_result = SupervisedResult(
        runner_status,
        "artifact_job_incomplete",
        None,
        _complete_evidence(**evidence_changes),
    )

    def runner(_command, _parser, **_kwargs):
        events.append("artifact_job")
        return artifact_result

    report = diagnostic._supervise_i11_child(
        registry=object(),
        effective=SimpleNamespace(effective_digest=CONFIG_DIGEST),
        front_check=lambda *_args: _front_check(),
        latch_factory=lambda _path: events.append("latch"),
        command_factory=lambda **_kwargs: command,
        runner=runner,
    )

    assert report.attempt_reserved is False
    assert report.artifact_pin_verified is False
    assert events == ["artifact_job"]


def test_parent_rejects_child_receipt_for_different_pair_or_config_digest():
    result = SupervisedResult(
        "child_exited",
        "child_process_exited",
        _complete_receipt(index=1),
        _complete_evidence(),
    )

    assert diagnostic._parent_confirms_i11_diagnostic(result, 1) is True
    assert diagnostic._parent_confirms_i11_diagnostic(result, 0) is False
    wrong_digest_receipt = _complete_receipt(index=1, effective_config_digest_match=False)
    wrong_digest = SupervisedResult(
        "child_exited", "child_process_exited", wrong_digest_receipt, _complete_evidence()
    )
    assert diagnostic._parent_confirms_i11_diagnostic(wrong_digest, 1) is False


def test_child_config_digest_mismatch_rejects_before_scope_or_credentials(monkeypatch, capsys):
    events: list[str] = []
    monkeypatch.setattr(diagnostic, "_has_supervised_i11_attempt_context", lambda: True)
    monkeypatch.setattr(
        diagnostic,
        "iteration41_runtime_registry",
        lambda: events.append("registry") or object(),
    )
    monkeypatch.setattr(
        diagnostic,
        "validate_runtime_config",
        lambda *_args: SimpleNamespace(effective_digest="b" * 64),
    )
    monkeypatch.setattr(
        diagnostic,
        "require_effective_runtime_config_seal",
        lambda *_args: events.append("seal"),
    )
    monkeypatch.setattr(
        diagnostic,
        "_require_exact_child_scope",
        lambda *_args: events.append("scope"),
    )
    monkeypatch.setenv(diagnostic._I11_PARENT_CONFIG_DIGEST_ENV, CONFIG_DIGEST)
    monkeypatch.setenv(diagnostic._I11_PARENT_SELECTED_INDEX_ENV, "0")

    assert diagnostic._run_i11_child_impl(()) == 2
    receipt = diagnostic.parse_i11_child_receipt(capsys.readouterr().out.encode("utf-8"))
    assert receipt is not None
    assert receipt["reason"] == "configuration_rejected"
    assert receipt["effective_config_digest_match"] is False
    assert receipt["credential_resolver_invoked"] is False
    assert "scope" not in events


def test_child_changed_selected_pair_rejects_before_credentials(monkeypatch, capsys):
    from backtrader_runtime import capability_imports, ctp_artifact_provenance
    from backtrader_runtime import ctp_configured_front_check

    events: list[object] = []
    monkeypatch.setattr(diagnostic, "_has_supervised_i11_attempt_context", lambda: True)
    effective = SimpleNamespace(effective_digest=CONFIG_DIGEST)
    monkeypatch.setattr(diagnostic, "iteration41_runtime_registry", lambda: object())
    monkeypatch.setattr(diagnostic, "validate_runtime_config", lambda *_args: effective)
    monkeypatch.setattr(diagnostic, "require_effective_runtime_config_seal", lambda *_args: None)
    pairs = (
        {"td_front": "tcp://127.0.0.1:10130", "md_front": "tcp://127.0.0.1:10131"},
        {"td_front": "tcp://127.0.0.1:10132", "md_front": "tcp://127.0.0.1:10133"},
    )
    monkeypatch.setattr(
        diagnostic,
        "_require_exact_child_scope",
        lambda *_args: (None, None, None, SimpleNamespace(), pairs),
    )
    monkeypatch.setattr(
        capability_imports,
        "trusted_installed_capability_import_context",
        lambda modules: _null_context(events)(modules),
    )
    monkeypatch.setattr(
        ctp_artifact_provenance,
        "verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts",
        lambda **kwargs: events.append(("artifact", kwargs["td_front"], kwargs["md_front"])),
    )
    monkeypatch.setattr(
        ctp_configured_front_check,
        "check_configured_ctp_fronts",
        lambda *_args: SimpleNamespace(succeeded=True, selected_config_index=1),
    )
    monkeypatch.setenv(diagnostic._I11_PARENT_CONFIG_DIGEST_ENV, CONFIG_DIGEST)
    monkeypatch.setenv(diagnostic._I11_PARENT_SELECTED_INDEX_ENV, "0")

    assert diagnostic._run_i11_child_impl(()) == 2
    receipt = diagnostic.parse_i11_child_receipt(capsys.readouterr().out.encode("utf-8"))
    assert receipt is not None
    assert receipt["reason"] == "front_selection_rejected"
    assert receipt["selected_pair_index"] == "pair_1"
    assert receipt["effective_config_digest_match"] is True
    assert receipt["credential_resolver_invoked"] is False
    assert events[0] == "capability_context"
    assert events[-1] == ("artifact", pairs[0]["td_front"], pairs[0]["md_front"])
    assert len(events) == 2


def test_child_success_pipeline_orders_selected_artifact_credentials_and_i10_adapter(
    monkeypatch, capsys
):
    from backtrader_runtime import (
        capability_imports,
        credential_resolver,
        ctp_artifact_provenance,
        ctp_configured_front_check,
        ctp_i10_oneshot_md_readonly,
        ctp_simnow_readonly_runtime,
    )

    events: list[object] = []
    pairs = (
        {"td_front": "tcp://192.0.2.10:10130", "md_front": "tcp://192.0.2.11:10131"},
        {"td_front": "tcp://192.0.2.12:10132", "md_front": "tcp://192.0.2.13:10133"},
    )
    private = SimpleNamespace(instrument_id="IF2612", exchange_id="CFFEX", hedge_flag="1")
    admission = SimpleNamespace(
        td_front=pairs[1]["td_front"],
        md_front=pairs[1]["md_front"],
        instrument_id=private.instrument_id,
        exchange_id=private.exchange_id,
        hedge_flag=private.hedge_flag,
        account_fingerprint_sha256="b" * 64,
    )
    registry = object()
    effective = SimpleNamespace(effective_digest=CONFIG_DIGEST)
    monkeypatch.setattr(diagnostic, "_has_supervised_i11_attempt_context", lambda: True)
    monkeypatch.setattr(diagnostic, "iteration41_runtime_registry", lambda: registry)
    monkeypatch.setattr(diagnostic, "validate_runtime_config", lambda *_args: effective)
    monkeypatch.setattr(diagnostic, "require_effective_runtime_config_seal", lambda *_args: None)
    monkeypatch.setattr(
        diagnostic,
        "_require_exact_child_scope",
        lambda *_args: (None, None, SimpleNamespace(), private, pairs),
    )
    monkeypatch.setattr(
        capability_imports,
        "trusted_installed_capability_import_context",
        lambda modules: _null_context(events)(modules),
    )
    monkeypatch.setattr(
        ctp_artifact_provenance,
        "verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts",
        lambda **kwargs: events.append(("artifact", kwargs["td_front"], kwargs["md_front"])),
    )
    monkeypatch.setattr(
        ctp_configured_front_check,
        "check_configured_ctp_fronts",
        lambda *_args: (
            events.append("front_selection")
            or SimpleNamespace(succeeded=True, selected_config_index=1)
        ),
    )

    class _Binding:
        def _route(self, *_args, **kwargs):
            events.append(("route", kwargs["selected_config_index"]))
            return admission, object()

    monkeypatch.setattr(
        diagnostic,
        "_require_exact_child_scope",
        lambda *_args: (None, None, _Binding(), private, pairs),
    )
    monkeypatch.setattr(
        credential_resolver,
        "resolve_runtime_credentials",
        lambda *_args: events.append("credential_resolver") or object(),
    )
    monkeypatch.setattr(
        credential_resolver,
        "require_resolved_runtime_credentials_seal",
        lambda *_args: events.append("credential_seal"),
    )

    class _CredentialSource:
        def __init__(self, *_args):
            events.append("credential_source")

    monkeypatch.setattr(
        ctp_simnow_readonly_runtime, "_SealedCtpCredentialSource", _CredentialSource
    )
    monkeypatch.setattr(
        diagnostic,
        "importlib",
        SimpleNamespace(
            import_module=lambda name: (
                events.append(("sdk_import", name))
                or SimpleNamespace(
                    OneShotMdDiagnosticClient=object,
                    CtpNativeStopReceipt=object,
                )
            )
        ),
    )
    observation = ctp_i10_oneshot_md_readonly.CtpI10OneShotMdObservation(
        md_front_sha256=hashlib.sha256(admission.md_front.encode()).hexdigest(),
        account_fingerprint_sha256=admission.account_fingerprint_sha256,
        instrument_id=admission.instrument_id,
        exchange_id=admission.exchange_id,
        connection_generation=3,
        login_identity_state="identity_unverified",
        subscription_acknowledged=True,
        matching_tick_observed=True,
        same_trading_day_observed=True,
        client_stop_returned=True,
        native_join_pending=False,
    )
    monkeypatch.setattr(
        ctp_i10_oneshot_md_readonly,
        "probe_i10_oneshot_md_readonly",
        lambda **kwargs: events.append(("i10_probe", kwargs["timeout_seconds"])) or observation,
    )
    monkeypatch.setenv(diagnostic._I11_PARENT_CONFIG_DIGEST_ENV, CONFIG_DIGEST)
    monkeypatch.setenv(diagnostic._I11_PARENT_SELECTED_INDEX_ENV, "1")

    assert diagnostic._run_i11_child_impl(()) == 0
    receipt = diagnostic.parse_i11_child_receipt(capsys.readouterr().out.encode("utf-8"))

    assert receipt is not None
    assert receipt["status"] == "diagnostic_complete"
    assert receipt["selected_pair_index"] == "pair_1"
    assert receipt["effective_config_digest_match"] is True
    assert receipt["login_identity_state"] == "identity_unverified"
    assert receipt["account_ready"] is False
    labels = [entry[0] if isinstance(entry, tuple) else entry for entry in events]
    artifact_positions = [index for index, label in enumerate(labels) if label == "artifact"]
    assert len(artifact_positions) == 2
    assert labels.index("front_selection") < labels.index("route")
    assert labels.index("route") < labels.index("credential_resolver")
    assert artifact_positions[1] < labels.index("credential_resolver")
    assert labels.index("credential_resolver") < labels.index("credential_seal")
    assert labels.index("credential_seal") < labels.index("sdk_import")
    assert labels.index("sdk_import") < labels.index("i10_probe")


def test_child_i10_error_receipt_keeps_verified_progress_and_join_state(monkeypatch, capsys):
    from backtrader_runtime.ctp_sdk_market_readonly import CtpSdkMarketReadOnlyError

    # Exercise the narrow redaction projection independently from provider code.
    progress = CtpI10OneShotMdProgressEvidence(
        login_identity_state="verified",
        subscription_acknowledged=True,
        matching_tick_observed=True,
        same_trading_day_observed=True,
    )
    error = CtpSdkMarketReadOnlyError(
        "market_client_stop_failed",
        close_state="native_join_pending",
        client_stop_returned=True,
    )
    error.i10_progress_evidence = progress
    safe = diagnostic._safe_i10_progress(error.i10_progress_evidence)
    diagnostic._emit_i11(
        status="incomplete",
        reason="native_join_pending",
        stage="market_data",
        close_state=error.close_state,
        login_identity_state=safe["login_identity_state"],
        credential_resolver_invoked=True,
        effective_config_digest_match=True,
        sdk_imported=True,
        selected_pair_index=1,
        client_stop_returned=error.client_stop_returned,
        matching_tick_observed=safe["matching_tick_observed"],
        native_join_pending=True,
        subscription_acknowledged=safe["subscription_acknowledged"],
        same_trading_day_observed=safe["same_trading_day_observed"],
    )
    receipt = diagnostic.parse_i11_child_receipt(capsys.readouterr().out.encode("utf-8"))

    assert receipt is not None
    assert receipt["close_state"] == "native_join_pending"
    assert receipt["client_stop_returned"] is True
    assert receipt["subscription_acknowledged"] is True
    assert receipt["matching_tick_observed"] is True
    assert receipt["same_trading_day_observed"] is True


def _null_context(events: list[object]):
    from contextlib import contextmanager

    @contextmanager
    def context(_modules: object):
        events.append("capability_context")
        yield

    return context


def test_failure_progress_receipt_preserves_only_confirmed_callback_facts(capsys):
    progress = CtpI10OneShotMdProgressEvidence(
        login_identity_state="identity_unverified",
        subscription_acknowledged=True,
        matching_tick_observed=None,
        same_trading_day_observed=None,
    )
    safe = diagnostic._safe_i10_progress(progress)
    diagnostic._emit_i11(
        status="incomplete",
        reason="market_observation_incomplete",
        stage="market_data",
        close_state="native_join_pending",
        login_identity_state=safe["login_identity_state"],
        credential_resolver_invoked=True,
        effective_config_digest_match=True,
        sdk_imported=True,
        selected_pair_index=2,
        client_stop_returned=True,
        matching_tick_observed=safe["matching_tick_observed"],
        native_join_pending=True,
        subscription_acknowledged=safe["subscription_acknowledged"],
    )
    receipt = diagnostic.parse_i11_child_receipt(capsys.readouterr().out.encode("utf-8"))

    assert receipt is not None
    assert receipt["close_state"] == "native_join_pending"
    assert receipt["subscription_acknowledged"] is True
    assert receipt["matching_tick_observed"] is None
    assert receipt["same_trading_day_observed"] is None
    assert receipt["login_identity_state"] == "identity_unverified"
    assert receipt["selected_pair_index"] == "pair_2"


def test_fresh_python_i_child_entry_without_job_or_marker_stops_before_dependencies():
    repository = Path(__file__).resolve().parents[3]
    script = (
        "import os, sys\n"
        f"sys.path.insert(0, {str(repository)!r})\n"
        "from backtrader_runtime import ctp_i11_oneshot_md_diagnostic as d\n"
        "calls = []\n"
        "class NeverTouchMarker:\n"
        "    def __init__(self, *args, **kwargs): calls.append('marker')\n"
        "d.PersistentI11OneShotAttemptLatch = NeverTouchMarker\n"
        "os.environ.pop(d._I11_JOB_HANDLE_ENV, None)\n"
        "result = d._run_child_entry()\n"
        "assert result == 2\n"
        "assert calls == []\n"
        "assert not any(name.endswith('.credential_resolver') for name in sys.modules)\n"
        "assert not any(name == 'bt_api_ctp' or name.startswith('bt_api_ctp.') for name in sys.modules)\n"
    )
    completed = subprocess.run(
        (sys.executable, "-I", "-B", "-c", script),
        cwd=repository,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, "fresh child import/context fence failed"
    receipt = diagnostic.parse_i11_child_receipt(completed.stdout)
    assert receipt is not None
    assert receipt["reason"] == "supervisor_context_required"
    assert receipt["credential_resolver_invoked"] is False
    assert receipt["sdk_imported"] is False
