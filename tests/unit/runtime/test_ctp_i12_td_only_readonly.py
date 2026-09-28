"""Offline fake-only contracts for the isolated I12 TD-only candidate."""

from __future__ import annotations

import hashlib
import ast
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backtrader_runtime import ctp_artifact_provenance as artifact_provenance
from backtrader_runtime import ctp_i12_td_only_latch as latch_module
from backtrader_runtime import ctp_i12_td_only_readonly as i12
from backtrader_runtime.ctp_front_pair_probe import (
    CtpConfiguredFrontPair,
    CtpFrontPairSelection,
)
from backtrader_runtime.ctp_preflight import (
    CTP_PROVIDER,
    REQUIRED_CTP_READ_ONLY_QUERIES,
    CtpReadOnlyQuerySnapshot,
    CtpReadOnlySessionIdentity,
    CtpReadOnlySessionRequest,
)
from backtrader_runtime.ctp_readonly_job_supervisor import (
    FixedChildCommand,
    ProcessEvidence,
    SupervisedResult,
)
from backtrader_runtime.ctp_sdk_readonly import CtpSdkReadOnlyCloseEvidence


_ACCOUNT_FP = hashlib.sha256(b"i12-synthetic-account").hexdigest()
_TD_FRONT = "tcp://192.0.2.71:41001"
_MD_FRONT = "tcp://192.0.2.72:41002"


def _identity() -> CtpReadOnlySessionIdentity:
    return CtpReadOnlySessionIdentity(
        provider=CTP_PROVIDER,
        environment="simnow",
        account_fingerprint_sha256=_ACCOUNT_FP,
        trading_day="20260925",
        connection_generation=7,
    )


def _snapshot() -> CtpReadOnlyQuerySnapshot:
    return CtpReadOnlyQuerySnapshot.from_query_digests(
        _identity(),
        tuple(
            (name, hashlib.sha256(name.encode("ascii")).hexdigest())
            for name in REQUIRED_CTP_READ_ONLY_QUERIES
        ),
        native_certificate_sha256=hashlib.sha256(b"synthetic-native-certificate").hexdigest(),
        rate_exchange_scopes=(
            ("commission_rates", "unverified"),
            ("margin_rates", "unverified"),
        ),
    )


def _request() -> CtpReadOnlySessionRequest:
    return CtpReadOnlySessionRequest(
        provider=CTP_PROVIDER,
        environment="simnow",
        account_fingerprint_sha256=_ACCOUNT_FP,
        valid_until=1_800_000_000.0,
    )


class _FakeSession:
    def __init__(self, *, close: Any, query_error: bool = False) -> None:
        self.close_evidence = close
        self.query_error = query_error
        self.calls: list[str] = []

    def read_identity(self) -> CtpReadOnlySessionIdentity:
        self.calls.append("read_identity")
        return _identity()

    def read_query_snapshot(self) -> CtpReadOnlyQuerySnapshot:
        self.calls.append("read_query_snapshot")
        if self.query_error:
            raise RuntimeError("synthetic-private-query-payload-must-not-escape")
        return _snapshot()

    def close_read_only_with_evidence(self) -> CtpSdkReadOnlyCloseEvidence:
        self.calls.append("close_read_only_with_evidence")
        if isinstance(self.close_evidence, BaseException):
            raise self.close_evidence
        return self.close_evidence

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unexpected session call: {name}")


class _FakeFactory:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.calls: list[str] = []

    def open_read_only(self, request: CtpReadOnlySessionRequest) -> _FakeSession:
        assert type(request) is CtpReadOnlySessionRequest
        self.calls.append("open_read_only")
        return self.session


def _complete_close() -> CtpSdkReadOnlyCloseEvidence:
    return CtpSdkReadOnlyCloseEvidence(
        "complete",
        native_released=True,
        join_required=True,
        join_completed=True,
        thread_alive=False,
        timed_out=False,
        client_stop_returned=True,
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


def _child_result(evidence: Any) -> SupervisedResult:
    fields = evidence.as_child_fields(stage="td_session")
    return SupervisedResult(
        "child_exited",
        "child_process_exited",
        fields,
        _process_evidence(),
    )


def _artifact_preflight_result(*, verified: bool) -> SupervisedResult:
    receipt = {
        "credential_resolver_invoked": False,
        "native_join_pending": False,
        "reason": "artifact_verified" if verified else "artifact_rejected",
        "sdk_imported": False,
        "status": "verified" if verified else "rejected",
    }
    return SupervisedResult(
        "child_exited",
        "child_process_exited",
        receipt,
        _process_evidence(),
    )


def test_i12_schema_accepts_only_fixed_value_free_receipt_fields() -> None:
    assert not hasattr(i12, "run_i12_td_only_session_candidate")
    assert "_run_i12_td_only_session_candidate" not in i12.__all__

    session = _FakeSession(close=_complete_close())
    evidence = i12._run_i12_td_only_session_candidate(_FakeFactory(session), _request())
    fields = evidence.as_child_fields(stage="td_session")

    parsed = i12.parse_i12_child_receipt(
        (i12.json.dumps(fields, sort_keys=True, separators=(",", ":")) + "\n").encode()
    )

    assert evidence.status == "td_readonly_complete"
    assert parsed == fields
    assert all(fields[name] == "complete" for name in i12._QUERY_FIELD_NAMES.values())
    assert fields["write_counts_state"] == "zero"
    assert fields["account_ready"] is False
    assert fields["settlement_confirmation_called"] is False
    assert fields["trading_ready"] is False
    assert fields["order_submission_authorized"] is False
    assert fields["margin_rate_exchange_scope"] == "unverified"
    assert fields["commission_rate_exchange_scope"] == "unverified"
    assert "account_fingerprint" not in parsed
    assert "synthetic-private-query-payload-must-not-escape" not in str(parsed)
    assert session.calls == [
        "read_identity",
        "read_query_snapshot",
        "read_identity",
        "close_read_only_with_evidence",
    ]

    extra = dict(fields)
    extra["raw_account"] = "synthetic-secret"
    assert i12._receipt_fields_complete(extra) is None


def test_i12_only_projects_explicit_native_join_pending() -> None:
    pending = CtpSdkReadOnlyCloseEvidence(
        "native_join_pending",
        native_released=True,
        join_required=True,
        join_completed=False,
    )
    evidence = i12._run_i12_td_only_session_candidate(
        _FakeFactory(_FakeSession(close=pending)), _request()
    )
    fields = evidence.as_child_fields(stage="td_session")

    assert evidence.status == "incomplete"
    assert evidence.reason == "native_join_pending"
    assert fields["native_join_pending"] is True
    assert fields["close_state"] == "native_join_pending"
    assert i12._parent_confirms_i12_readonly(_child_result(evidence)) is False


@pytest.mark.parametrize(
    "close",
    (
        CtpSdkReadOnlyCloseEvidence("unknown"),
        RuntimeError("synthetic-close-error-must-not-escape"),
    ),
)
def test_i12_unknown_or_exceptional_close_never_becomes_join_pending(close: Any) -> None:
    evidence = i12._run_i12_td_only_session_candidate(
        _FakeFactory(_FakeSession(close=close)), _request()
    )
    fields = evidence.as_child_fields(stage="td_session")

    assert evidence.status == "incomplete"
    assert evidence.reason == "session_close_unknown"
    assert fields["close_state"] == "unknown"
    assert fields["native_join_pending"] is None
    assert fields["join_completed"] is None
    assert i12._parent_confirms_i12_readonly(_child_result(evidence)) is False


def test_i12_query_failure_with_complete_close_does_not_claim_readonly_complete() -> None:
    session = _FakeSession(close=_complete_close(), query_error=True)
    evidence = i12._run_i12_td_only_session_candidate(_FakeFactory(session), _request())
    fields = evidence.as_child_fields(stage="td_session")

    assert evidence.status == "incomplete"
    assert evidence.reason == "query_bundle_unverified"
    assert fields["query_bundle_complete"] is False
    assert fields["write_counts_state"] == "unavailable"
    assert fields["close_state"] == "complete"


def test_i12_parent_requires_full_close_and_contained_zero_exit() -> None:
    complete = i12._run_i12_td_only_session_candidate(
        _FakeFactory(_FakeSession(close=_complete_close())), _request()
    )
    assert i12._parent_confirms_i12_readonly(_child_result(complete)) is True

    incomplete_fields = complete.as_child_fields(stage="td_session")
    incomplete_fields["join_completed"] = None
    incomplete = SupervisedResult(
        "child_exited",
        "child_process_exited",
        incomplete_fields,
        _process_evidence(),
    )
    assert i12._parent_confirms_i12_readonly(incomplete) is False

    wrong_exit = SupervisedResult(
        "child_exited",
        "child_process_exited",
        complete.as_child_fields(stage="td_session"),
        ProcessEvidence(True, True, True, True, 3, False, None, True, "verified"),
    )
    assert i12._parent_confirms_i12_readonly(wrong_exit) is False


def test_i12_pins_are_independent_from_the_i10_md_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    i10 = artifact_provenance.CTP_I10_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS
    i12_pins = artifact_provenance.CTP_I12_TD_ONLY_READONLY_ARTIFACT_PINS

    assert i12_pins is not i10
    assert dict(i12_pins) == dict(i10)
    assert all(i12_pins[name] is not i10[name] for name in i10)

    checked: list[object] = []
    monkeypatch.setattr(
        artifact_provenance,
        "_validate_exact_tcp_front_pair",
        lambda **kwargs: checked.append(("pair", kwargs)),
    )
    monkeypatch.setattr(
        artifact_provenance,
        "_verify_pinned_sdk_distributions",
        lambda modules, *, pins: checked.append((tuple(modules), pins)),
    )

    artifact_provenance.verify_ctp_i12_td_only_readonly_artifact_provenance_for_fronts(
        td_front=_TD_FRONT,
        md_front=_MD_FRONT,
    )

    assert checked == [
        ("pair", {"td_front": _TD_FRONT, "md_front": _MD_FRONT}),
        (("bt_api_base", "bt_api_ctp"), i12_pins),
    ]


def test_i12_fresh_child_binding_is_exact_config_and_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    from backtrader_runtime import ctp_simnow_operator

    effective = SimpleNamespace(
        effective_digest="a" * 64,
        registration=SimpleNamespace(digest="b" * 64),
    )
    pair = {"md_front": _MD_FRONT, "td_front": _TD_FRONT}
    front_pairs = (pair,)
    monkeypatch.setattr(
        i12,
        "_load_sealed_context",
        lambda: (effective, object(), object(), object(), front_pairs),
    )

    def select(pairs: Any) -> CtpFrontPairSelection:
        current = pairs[0]
        return CtpFrontPairSelection(
            CtpConfiguredFrontPair(current["md_front"], current["td_front"]),
            0,
            1.0,
            (),
            3.0,
            1,
        )

    monkeypatch.setattr(ctp_simnow_operator, "_select_configured_front_pair", select)
    expected = i12._front_binding_digest(
        effective_digest=effective.effective_digest,
        registration_digest=effective.registration.digest,
        config_index=0,
        md_front=_MD_FRONT,
        td_front=_TD_FRONT,
    )
    monkeypatch.setenv(i12._I12_PRECHECK_INDEX_ENV, "0")
    monkeypatch.setenv(i12._I12_PRECHECK_BINDING_ENV, expected.binding_sha256)

    assert i12._child_recheck_precheck_binding() == expected
    assert i12._I12_PRECHECK_INDEX_ENV not in os.environ
    assert i12._I12_PRECHECK_BINDING_ENV not in os.environ

    changed = {"md_front": _MD_FRONT, "td_front": "tcp://192.0.2.73:41003"}
    monkeypatch.setattr(
        i12,
        "_load_sealed_context",
        lambda: (effective, object(), object(), object(), (changed,)),
    )
    monkeypatch.setenv(i12._I12_PRECHECK_INDEX_ENV, "0")
    monkeypatch.setenv(i12._I12_PRECHECK_BINDING_ENV, expected.binding_sha256)
    with pytest.raises(ValueError, match="front_precheck_binding_mismatch"):
        i12._child_recheck_precheck_binding()


def test_i12_diagnostic_routes_exact_typed_pair_after_artifact_gate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from contextlib import nullcontext

    events: list[str] = []
    effective = SimpleNamespace(
        effective_digest="a" * 64,
        registration=SimpleNamespace(digest="b" * 64),
    )
    front_pairs = ({"md_front": _MD_FRONT, "td_front": _TD_FRONT},)
    private = SimpleNamespace(
        instrument_id="SYNTHETIC",
        exchange_id="EX",
        hedge_flag="1",
    )
    precheck = i12._front_binding_digest(
        effective_digest=effective.effective_digest,
        registration_digest=effective.registration.digest,
        config_index=0,
        md_front=_MD_FRONT,
        td_front=_TD_FRONT,
    )
    routed: list[tuple[object, int]] = []

    class FakeBinding:
        def _route(
            self,
            _effective: object,
            _registry: object,
            *,
            selected_front_pair: object,
            selected_config_index: int,
        ) -> tuple[object, object]:
            events.append("route")
            routed.append((selected_front_pair, selected_config_index))
            raise i12.RuntimeConfigError(
                i12.PRESET_POLICY_VIOLATION,
                "synthetic route detail must be redacted",
                field_path="runtime.preset",
                reason="synthetic_route_rejection",
            )

    binding = FakeBinding()

    def load_sealed_context() -> tuple[object, object, object, object, tuple[object, ...]]:
        events.append("sealed_context")
        return effective, object(), binding, private, front_pairs

    def verify_artifact(*, md_front: str, td_front: str) -> None:
        events.append("artifact")
        assert (md_front, td_front) == (_MD_FRONT, _TD_FRONT)

    monkeypatch.setattr(i12.sys, "argv", ["i12-child"])
    monkeypatch.setattr(i12.logging, "disable", lambda _level: None)
    monkeypatch.setattr(i12, "_has_supervised_i12_attempt_context", lambda: True)

    def recheck_precheck() -> i12.I12FrontPrecheckBinding:
        events.append("precheck")
        return precheck

    monkeypatch.setattr(i12, "_child_recheck_precheck_binding", recheck_precheck)
    monkeypatch.setattr(i12, "_load_sealed_context", load_sealed_context)
    monkeypatch.setattr(
        i12,
        "trusted_installed_capability_import_context",
        lambda _modules: nullcontext(),
    )
    monkeypatch.setattr(
        i12,
        "verify_ctp_i12_td_only_readonly_artifact_provenance_for_fronts",
        verify_artifact,
    )

    assert i12._run_diagnostic_impl() == 2

    raw_receipt = capsys.readouterr().out
    receipt = i12.parse_i12_child_receipt(raw_receipt.encode("utf-8"))
    assert events == ["precheck", "sealed_context", "artifact", "route"]
    assert len(routed) == 1
    selected_pair, selected_index = routed[0]
    assert type(selected_pair) is CtpConfiguredFrontPair
    assert (selected_pair.md_front, selected_pair.td_front) == (_MD_FRONT, _TD_FRONT)
    assert selected_index == 0
    assert receipt is not None
    assert receipt["status"] == "rejected"
    assert receipt["stage"] == "route_binding"
    assert receipt["reason"] == "route_binding_rejected"
    assert receipt["login_state"] == "not_observed"
    assert receipt["query_bundle_complete"] is False
    assert "synthetic route detail must be redacted" not in raw_receipt
    assert "synthetic_route_rejection" not in raw_receipt


def test_i12_selects_one_exact_configured_pair_through_bounded_tcp_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backtrader_runtime import ctp_front_pair_probe

    configured = (
        {"md_front": "tcp://192.0.2.81:41101", "td_front": "tcp://192.0.2.82:41102"},
        {"md_front": _MD_FRONT, "td_front": _TD_FRONT},
    )
    calls: list[tuple[Any, ...]] = []

    def fake_probe(
        pairs: Any,
        *,
        timeout_seconds: float,
        max_pairs: int,
        repeated_samples: int,
    ) -> CtpFrontPairSelection:
        calls.append((pairs, timeout_seconds, max_pairs, repeated_samples))
        selected = CtpConfiguredFrontPair(_MD_FRONT, _TD_FRONT)
        return CtpFrontPairSelection(selected, 1, 2.0, (), timeout_seconds, repeated_samples)

    monkeypatch.setattr(ctp_front_pair_probe, "select_ctp_front_pair", fake_probe)
    selected = i12._select_configured_front_pair(configured)

    assert selected.config_index == 1
    assert (selected.pair.md_front, selected.pair.td_front) == (_MD_FRONT, _TD_FRONT)
    assert len(calls) == 1
    pairs, timeout_seconds, max_pairs, repeated_samples = calls[0]
    assert pairs == configured
    assert all("md_front" in pair and "td_front" in pair for pair in pairs)
    assert 0.0 < timeout_seconds <= 10.0
    assert max_pairs == 8
    assert 1 <= repeated_samples <= 5


def test_i12_front_selector_receives_deadline_in_its_monotonic_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backtrader_runtime import ctp_front_pair_probe

    configured = ({"md_front": _MD_FRONT, "td_front": _TD_FRONT},)
    calls: list[dict[str, Any]] = []

    def fake_probe(pairs: Any, **kwargs: Any) -> CtpFrontPairSelection:
        calls.append(kwargs)
        selected = CtpConfiguredFrontPair(_MD_FRONT, _TD_FRONT)
        return CtpFrontPairSelection(selected, 0, 1.0, (), 3.0, 3)

    monkeypatch.setattr(i12.time, "monotonic", lambda: 40.0)
    monkeypatch.setattr(i12.time, "perf_counter", lambda: 1000.0)
    monkeypatch.setattr(ctp_front_pair_probe, "select_ctp_front_pair", fake_probe)

    selected = i12._select_configured_front_pair(
        configured, deadline_monotonic=65.0
    )

    assert selected.config_index == 0
    assert len(calls) == 1
    assert calls[0]["deadline_monotonic"] == 1025.0
    assert calls[0]["timeout_seconds"] == i12._I12_FRONT_PROBE_TIMEOUT_SECONDS
    assert calls[0]["max_pairs"] == i12._I12_FRONT_PROBE_MAX_PAIRS
    assert calls[0]["repeated_samples"] == i12._I12_FRONT_PROBE_SAMPLES


def test_i12_td_worker_has_no_md_sdk_import_or_construction() -> None:
    source_path = Path(i12.__file__)
    syntax = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(syntax)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    child = next(
        node
        for node in syntax.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_run_diagnostic_impl"
    )
    names = {node.id for node in ast.walk(child) if isinstance(node, ast.Name)}

    assert "ctp_sdk_market_readonly" not in imports
    assert "MdClient" not in names
    assert "CtpSdkReadOnlySessionFactory" in names


def test_i12_precheck_failure_has_no_resolver_import_or_marker_access_in_isolated_process() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    code = f"""
import sys
from pathlib import Path

sys.path.insert(0, {str(repo_root)!r})
import backtrader_runtime.ctp_i12_td_only_readonly as i12

for name in (
    'backtrader_runtime.credential_resolver',
    'backtrader_runtime.ctp_sdk_readonly',
    'backtrader_runtime.ctp_preflight',
    'backtrader_runtime.ctp_sandbox_readonly_admission',
    'backtrader_runtime.ctp_i12_td_only_latch',
):
    assert name not in sys.modules, name

marker_calls = []
class FakeLatch:
    def is_tripped(self):
        marker_calls.append('read')
        return False
    def begin_attempt(self):
        marker_calls.append('write')
        return True
    def trip(self, reason):
        marker_calls.append('trip')
        return True

def fail_precheck():
    raise RuntimeError('synthetic precheck rejection')

result = i12._supervise_i12_child(
    FakeLatch(),
    precheck=fail_precheck,
    command_builder=lambda _binding: None,
    runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('runner called')),
)
assert result.status == 'rejected'
assert marker_calls == []
for name in (
    'backtrader_runtime.credential_resolver',
    'backtrader_runtime.ctp_sdk_readonly',
    'backtrader_runtime.ctp_preflight',
    'backtrader_runtime.ctp_sandbox_readonly_admission',
    'backtrader_runtime.ctp_i12_td_only_latch',
):
    assert name not in sys.modules, name
print('I12_IMPORT_ORDER_AND_PRECHECK_PASS')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, f"isolated I12 import probe failed: {result.stderr[-800:]}"
    assert result.stdout.strip() == "I12_IMPORT_ORDER_AND_PRECHECK_PASS"


class _CountingLatch:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_tripped(self) -> bool:
        self.calls.append("read")
        return False

    def begin_attempt(self) -> bool:
        self.calls.append("begin")
        return True

    def trip(self, _reason: str) -> bool:
        self.calls.append("trip")
        return True


def test_i12_supervisor_needs_positive_queries_and_close_before_success() -> None:
    latch = _CountingLatch()
    binding = i12.I12FrontPrecheckBinding(0, "c" * 64)
    command = FixedChildCommand((sys.executable,), Path.cwd(), {})
    complete = i12._run_i12_td_only_session_candidate(
        _FakeFactory(_FakeSession(close=_complete_close())), _request()
    )
    runner_calls: list[str] = []

    def runner(*_args: Any, **kwargs: Any) -> SupervisedResult:
        runner_calls.append("artifact" if kwargs["receipt_schema"] is i12._I12_ARTIFACT_PREFLIGHT_SCHEMA else "run")
        if kwargs["receipt_schema"] is i12._I12_ARTIFACT_PREFLIGHT_SCHEMA:
            return _artifact_preflight_result(verified=True)
        return _child_result(complete)

    result = i12._supervise_i12_child(
        latch,
        precheck=lambda: binding,
        command_builder=lambda received: command if received == binding else None,
        artifact_command_builder=lambda worker: worker,
        runner=runner,
    )

    assert result.status == "td_readonly_complete"
    assert runner_calls == ["artifact", "run"]
    assert latch.calls == ["read", "begin"]


def test_i12_supervisor_shares_one_deadline_with_precheck_artifact_and_td_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [20.0]
    monkeypatch.setattr(i12.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(i12, "_I12_TOTAL_DEADLINE_SECONDS", 10.0)
    latch = _CountingLatch()
    binding = i12.I12FrontPrecheckBinding(0, "e" * 64)
    command = FixedChildCommand((sys.executable,), Path.cwd(), {})
    complete = i12._run_i12_td_only_session_candidate(
        _FakeFactory(_FakeSession(close=_complete_close())), _request()
    )
    precheck_deadlines: list[float] = []
    job_deadlines: list[tuple[str, float]] = []

    def precheck(*, deadline_monotonic: float) -> i12.I12FrontPrecheckBinding:
        precheck_deadlines.append(deadline_monotonic)
        return binding

    def runner(*_args: Any, **kwargs: Any) -> SupervisedResult:
        job_deadlines.append((
            "artifact"
            if kwargs["receipt_schema"] is i12._I12_ARTIFACT_PREFLIGHT_SCHEMA
            else "td",
            kwargs["deadline_monotonic"],
        ))
        now[0] += 2.0
        if kwargs["receipt_schema"] is i12._I12_ARTIFACT_PREFLIGHT_SCHEMA:
            return _artifact_preflight_result(verified=True)
        return _child_result(complete)

    monkeypatch.setattr(i12, "_parent_credential_free_precheck", precheck)
    result = i12._supervise_i12_child(
        latch,
        command_builder=lambda received: command if received == binding else None,
        artifact_command_builder=lambda worker: worker,
        runner=runner,
    )

    assert result.status == "td_readonly_complete"
    assert precheck_deadlines == [30.0]
    assert job_deadlines == [("artifact", 30.0), ("td", 30.0)]
    assert latch.calls == ["read", "begin"]


def test_i12_deadline_expiring_during_precheck_stops_before_latch_or_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [20.0]
    monkeypatch.setattr(i12.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(i12, "_I12_TOTAL_DEADLINE_SECONDS", 5.0)
    latch = _CountingLatch()
    binding = i12.I12FrontPrecheckBinding(0, "f" * 64)
    builder_calls: list[str] = []

    def precheck(*, deadline_monotonic: float) -> i12.I12FrontPrecheckBinding:
        assert deadline_monotonic == 25.0
        now[0] = deadline_monotonic
        return binding

    monkeypatch.setattr(i12, "_parent_credential_free_precheck", precheck)
    result = i12._supervise_i12_child(
        latch,
        command_builder=lambda _binding: builder_calls.append("command"),
        runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("deadline-expired operation must not start a Job")
        ),
    )

    assert result.status == "timed_out"
    assert result.reason == "child_deadline_exceeded"
    assert builder_calls == []
    assert latch.calls == []


def test_i12_artifact_pin_rejection_precedes_i12_marker_read_and_write() -> None:
    latch = _CountingLatch()
    binding = i12.I12FrontPrecheckBinding(0, "d" * 64)
    command = FixedChildCommand((sys.executable,), Path.cwd(), {})

    result = i12._supervise_i12_child(
        latch,
        precheck=lambda: binding,
        command_builder=lambda _binding: command,
        artifact_command_builder=lambda worker: worker,
        runner=lambda *_args, **_kwargs: _artifact_preflight_result(verified=False),
    )

    assert result.status == "rejected"
    assert result.reason == "sdk_artifact_rejected"
    assert latch.calls == []


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


def test_i12_latch_is_one_shot_and_uses_only_its_synthetic_marker(tmp_path: Path) -> None:
    state = tmp_path / "state"
    _protect_test_directory(state)
    synthetic_other_markers = {
        "i10": state / "synthetic-i10-marker-do-not-read.latch",
        "i11": state / "synthetic-i11-marker-do-not-read.latch",
    }
    original = {
        name: ("synthetic-{0}-sentinel\n".format(name)).encode("ascii")
        for name in synthetic_other_markers
    }
    for name, path in synthetic_other_markers.items():
        path.write_bytes(original[name])
    path = state / "i12-test-only.latch"

    first = latch_module.PersistentI12TdOnlyAttemptLatch(path)
    assert first.begin_attempt() is True
    assert first.is_tripped() is False
    assert path.read_bytes() == latch_module.I12_LATCH_CONTENT
    for name, other_path in synthetic_other_markers.items():
        assert other_path.read_bytes() == original[name]

    restarted = latch_module.PersistentI12TdOnlyAttemptLatch(path)
    assert restarted.is_tripped() is True
    assert restarted.begin_attempt() is False
    for name, other_path in synthetic_other_markers.items():
        assert other_path.read_bytes() == original[name]
