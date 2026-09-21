"""Focused fail-closed tests for the Iteration 22 bounded-session supervisor."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO / "examples" / "013_3_sa_midfreq_simnow" / "pilot_supervisor.py"
SPEC = importlib.util.spec_from_file_location("iter22_pilot_supervisor", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
supervisor = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = supervisor
SPEC.loader.exec_module(supervisor)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clock() -> datetime:
    return datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc)


def _source_components() -> dict:
    components = {
        name: {
            "module": module,
            "version": "1.0",
            "path": "D:/safe/{}.py".format(name),
            "sha256": "a" * 64,
            "found": True,
        }
        for name, module in supervisor._BASE_COMPONENT_MODULES.items()
    }
    components["bt_api_ctp"] = {
        "module": "bt_api_ctp",
        "version": "1.0",
        "path": "D:/safe/bt_api_ctp/__init__.py",
        "sha256": "b" * 64,
        "package_manifest": [],
        "package_manifest_verified": True,
        "native_files": [],
        "native_loaded": True,
    }
    return components


def _evidence_counts() -> dict:
    return dict.fromkeys(supervisor.EVIDENCE_STREAMS, 0)


def _write_success_manifest(
    output: Path,
    *,
    mode: str = "shadow",
    receipt: Path | None = None,
    unknown_field: bool = False,
    trading_day: str = "20260921",
    connection_generation: int = 7,
    account_fingerprint: str = "acct_0123456789abcdef",
    environment: str = "simnow_first_group1",
    environment_profile: str = "set1_group1",
) -> None:
    """Create the exact sealed runner contract without invoking live CTP."""

    output.mkdir(parents=True, exist_ok=False)
    hashes = {}
    if mode == "shadow":
        pending_json = {
            "g3_gate_status": supervisor.FIRST_SET_G3_PENDING_MANIFEST_SEAL,
            "observation_evidence": {
                "g3_gate_status": supervisor.FIRST_SET_G3_PENDING_MANIFEST_SEAL
            },
            "manifest_seal_status": "PENDING",
            "g3_verdict_source": "manifest.json",
        }
        for name in ("daily_report.json", "reconciliation.json"):
            path = output / name
            path.write_text(json.dumps(pending_json, sort_keys=True), encoding="utf-8")
            hashes[name] = _sha256(path)
        markdown = output / "daily_report.md"
        markdown.write_text("# sealed pending G3 artifacts\n", encoding="utf-8")
        hashes[markdown.name] = _sha256(markdown)

    network_identity = {
        "provider": "btapi",
        "exchange": "CTP___FUTURE",
        "schema_version": "ctp.quote.v2",
        "account_fingerprint": account_fingerprint,
        "environment_profile": environment_profile,
        "trading_day": trading_day,
        "connection_generation": connection_generation,
        "instrument": "SA701",
        "native_sha256": "2" * 64,
        "ctp_package_sha256": "3" * 64,
    }
    common = {
        "schema_version": supervisor.MANIFEST_SCHEMA_VERSION,
        "iteration": 22,
        "run_id": "iter22-{}-20260921T040000Z-1234abcd".format(mode),
        "purpose": "observation" if mode == "shadow" else "natural_signal",
        "mode": mode,
        "environment": environment,
        "candidate_id": "iter22-sa-v0",
        "config_hash": "c" * 64,
        "code_hash": "d" * 64,
        "data_hash": supervisor._sha256_json(network_identity),
        "account_fingerprint": account_fingerprint,
        "instrument_id": "SA701",
        "trading_day": trading_day,
        "started_at_utc": "2026-09-21T04:00:00Z",
        "ended_at_utc": "2026-09-21T05:00:00Z",
        "fee_source": "account_query",
        "execution_basis": "none" if mode == "shadow" else "simnow_native",
        "hypothetical_fills": False,
        "research_status": "RESEARCH_NOT_ESTABLISHED" if mode == "shadow" else "RESEARCH_ADMITTED",
        "runtime": {
            "python": "3.11.5",
            "executable": "D:/safe/python.exe",
            "platform": "Windows",
            "architecture": "AMD64",
        },
        "exit_status": "PASS_SHADOW_G3" if mode == "shadow" else "COMPLETE_STOPPED_FLAT",
        "environment_profile": environment_profile,
        "profile_basis": environment,
        "market_alignment": "actual_market_hours",
        "admission_receipt_sha256": None if receipt is None else _sha256(receipt),
        "source_components": _source_components(),
        "engineering_strategy_observation": False,
        "g3_gate_status": "PASS" if mode == "shadow" else "NOT_RUN",
        "g4_gate_status": "NOT_RUN" if mode == "shadow" else "INCOMPLETE",
        "retention": {
            "status": "NOT_APPLICABLE_EXPLICIT_OUTPUT_DIRECTORY",
            "retain_trading_days": 20,
        },
        "preflight_sha256": "f" * 64,
        "startup_account_observation_sha256": "1" * 64,
        "network_data_identity": network_identity,
        "controlled_drain": {
            "status": "PASS",
            "remote_flat_proven": True,
            "store_shutdown_state": "PASS",
            "active_order_count": 0,
            "local_position_count": 0,
            "remote_position_count": 0,
            "unknown_intent_count": 0,
            "unmatched_trade_count": 0,
        },
        "observation_evidence": {"g3_gate_status": "PASS" if mode == "shadow" else "NOT_RUN"},
        "evidence_counts": _evidence_counts(),
        "evidence_enqueued_counts": _evidence_counts(),
        "evidence_dropped_counts": _evidence_counts(),
        "evidence_pending_counts": _evidence_counts(),
        "evidence_max_pending_counts": _evidence_counts(),
        "evidence_max_pending_total": 0,
        "evidence_rotations": _evidence_counts(),
        "evidence_health": {"complete": True, "failure_reason": None, "queue_limit": 20},
    }
    if mode == "shadow":
        common["first_set_g3_artifact_seal"] = {
            "schema_version": supervisor.FIRST_SET_G3_ARTIFACT_SEAL_SCHEMA,
            "verdict_source": "manifest.json",
            "artifact_state": supervisor.FIRST_SET_G3_PENDING_MANIFEST_SEAL,
            "artifact_sha256": hashes,
        }
    else:
        common["execution_authorization_sha256"] = "4" * 64
        common["execution_arming_sha256"] = "5" * 64
    if unknown_field:
        common["future_unreviewed_field"] = "must-fail-closed"
    assert set(common) == supervisor._expected_manifest_fields(mode) | (
        {"future_unreviewed_field"} if unknown_field else set()
    )
    (output / "manifest.json").write_text(json.dumps(common, sort_keys=True), encoding="utf-8")


def _journal(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_default_is_dry_run_and_never_invokes_a_child(tmp_path):
    calls = []
    instance = supervisor.PilotSupervisor(
        state_directory=tmp_path / "state",
        output_root=tmp_path / "reports",
        runner=lambda *args: calls.append(args) or 0,
        clock=_clock,
        run_name_factory=lambda index, _now: "pilot-run-{:02d}".format(index),
    )

    result = instance.run(supervisor.SessionPlan(), execute=False)

    assert result.executed is False
    assert result.completed_sessions == 0
    assert calls == []
    records = _journal(tmp_path / "state" / "journal.jsonl")
    assert [record["event"] for record in records] == ["DRY_RUN"]
    assert records[0]["mode"] == "shadow"
    assert records[0]["purpose"] == "observation"
    assert list((tmp_path / "reports").iterdir()) == []


def test_only_a_valid_receipt_path_unlocks_the_explicit_simnow_shape(tmp_path):
    receipt = tmp_path / "admission.json"
    receipt.write_text("{}", encoding="utf-8")
    calls = []

    def runner(command, output, _timeout):
        calls.append(command)
        _write_success_manifest(output, mode="simnow", receipt=receipt)
        return 0

    instance = supervisor.PilotSupervisor(
        state_directory=tmp_path / "state",
        output_root=tmp_path / "reports",
        runner=runner,
        clock=_clock,
        run_name_factory=lambda index, _now: "pilot-run-{:02d}".format(index),
    )
    plan = supervisor.SessionPlan(
        mode="simnow",
        purpose="natural_signal",
        admission_receipt=receipt,
        restart_delay_seconds=0,
    )

    result = instance.run(plan, execute=True)

    assert result.completed_sessions == 1
    command = calls[0]
    assert command[command.index("--mode") + 1] == "simnow"
    assert command[command.index("--purpose") + 1] == "natural_signal"
    assert command[command.index("--admission-receipt") + 1] == str(receipt.resolve())
    assert all(
        str(receipt.resolve()) not in line
        for line in (tmp_path / "state" / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    )
    with pytest.raises(supervisor.InvocationError):
        instance.run(supervisor.SessionPlan(mode="simnow", purpose="observation"), execute=False)


def test_restart_is_authorized_only_after_each_exact_sealed_manifest(tmp_path):
    calls = []
    pauses = []

    def runner(_command, output, _timeout):
        calls.append(output)
        _write_success_manifest(output)
        return 0

    instance = supervisor.PilotSupervisor(
        state_directory=tmp_path / "state",
        output_root=tmp_path / "reports",
        runner=runner,
        clock=_clock,
        sleeper=pauses.append,
        run_name_factory=lambda index, _now: "pilot-run-{:02d}".format(index),
    )
    result = instance.run(
        supervisor.SessionPlan(max_sessions=2, restart_delay_seconds=2.5), execute=True
    )

    assert result.completed_sessions == 2
    assert len(calls) == 2
    assert pauses == [2.5]
    records = _journal(tmp_path / "state" / "journal.jsonl")
    assert [record["event"] for record in records].count("SESSION_SEALED_SUCCESS") == 2
    assert [record["event"] for record in records].count("RESTART_AUTHORIZED") == 1
    assert not (tmp_path / "state" / "stop-latch.json").exists()


def test_unknown_manifest_field_lock_stops_before_any_restart(tmp_path):
    calls = []

    def runner(_command, output, _timeout):
        calls.append(output)
        _write_success_manifest(output, unknown_field=True)
        return 0

    instance = supervisor.PilotSupervisor(
        state_directory=tmp_path / "state",
        output_root=tmp_path / "reports",
        runner=runner,
        clock=_clock,
        run_name_factory=lambda index, _now: "pilot-run-{:02d}".format(index),
    )

    with pytest.raises(supervisor.SupervisorStopped):
        instance.run(supervisor.SessionPlan(max_sessions=2, restart_delay_seconds=0), execute=True)

    assert len(calls) == 1
    stop = json.loads((tmp_path / "state" / "stop-latch.json").read_text(encoding="utf-8"))
    assert stop["reason"] == "SEALED_MANIFEST_REJECTED"
    records = _journal(tmp_path / "state" / "journal.jsonl")
    assert any(record["event"] == "SESSION_MANIFEST_REJECTED" for record in records)
    assert any(record["event"] == "LOCK_STOP" for record in records)
    with pytest.raises(supervisor.SupervisorStopped):
        instance.run(supervisor.SessionPlan(), execute=False)
    assert len(calls) == 1


def test_bounded_child_timeout_creates_a_no_restart_latch(tmp_path):
    seen_timeouts = []

    def runner(_command, _output, timeout):
        seen_timeouts.append(timeout)
        raise supervisor.RunnerTimeout("test timeout")

    instance = supervisor.PilotSupervisor(
        state_directory=tmp_path / "state",
        output_root=tmp_path / "reports",
        runner=runner,
        clock=_clock,
        run_name_factory=lambda index, _now: "pilot-run-{:02d}".format(index),
    )

    with pytest.raises(supervisor.SupervisorStopped):
        instance.run(
            supervisor.SessionPlan(session_seconds=120, grace_seconds=30, restart_delay_seconds=0),
            execute=True,
        )

    assert seen_timeouts == [150.0]
    stop = json.loads((tmp_path / "state" / "stop-latch.json").read_text(encoding="utf-8"))
    assert stop["reason"] == "SUBPROCESS_TIMEOUT"


def test_unexpected_manifest_validator_error_also_lock_stops(tmp_path, monkeypatch):
    def runner(_command, _output, _timeout):
        return 0

    def broken_validator(*_args, **_kwargs):
        raise RuntimeError("synthetic validator defect")

    monkeypatch.setattr(supervisor, "validate_sealed_success_manifest", broken_validator)
    instance = supervisor.PilotSupervisor(
        state_directory=tmp_path / "state",
        output_root=tmp_path / "reports",
        runner=runner,
        clock=_clock,
        run_name_factory=lambda index, _now: "pilot-run-{:02d}".format(index),
    )

    with pytest.raises(supervisor.SupervisorStopped):
        instance.run(supervisor.SessionPlan(restart_delay_seconds=0), execute=True)

    stop = json.loads((tmp_path / "state" / "stop-latch.json").read_text(encoding="utf-8"))
    assert stop["reason"] == "SUPERVISOR_INTERNAL_FAILURE"


@pytest.mark.parametrize(
    "second_identity",
    (
        {"account_fingerprint": "acct_fedcba9876543210"},
        {"trading_day": "20260922"},
        {"connection_generation": 8},
        {"environment": "simnow_first_group2", "environment_profile": "set1_group2"},
    ),
)
def test_identity_change_between_sealed_sessions_lock_stops_before_a_third(
    tmp_path, second_identity
):
    calls = []

    def runner(_command, output, _timeout):
        calls.append(output)
        _write_success_manifest(
            output,
            **({} if len(calls) == 1 else second_identity),
        )
        return 0

    instance = supervisor.PilotSupervisor(
        state_directory=tmp_path / "state",
        output_root=tmp_path / "reports",
        runner=runner,
        clock=_clock,
        run_name_factory=lambda index, _now: "pilot-run-{:02d}".format(index),
    )

    with pytest.raises(supervisor.SupervisorStopped):
        instance.run(supervisor.SessionPlan(max_sessions=3, restart_delay_seconds=0), execute=True)

    assert len(calls) == 2
    stop = json.loads((tmp_path / "state" / "stop-latch.json").read_text(encoding="utf-8"))
    assert stop["reason"] == "SESSION_IDENTITY_CHANGED"
    records = _journal(tmp_path / "state" / "journal.jsonl")
    assert any(record["event"] == "SESSION_IDENTITY_CHANGED" for record in records)


def test_exclusive_lock_never_steals_an_active_or_stale_owner(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    lock = supervisor.ExclusiveSupervisorLock(state / "supervisor.lock", clock=_clock)
    lock.acquire()
    try:
        instance = supervisor.PilotSupervisor(
            state_directory=state,
            output_root=tmp_path / "reports",
            clock=_clock,
        )
        with pytest.raises(supervisor.SupervisorLockError):
            instance.run(supervisor.SessionPlan(), execute=False)
    finally:
        lock.release()


def test_append_only_journal_redacts_sensitive_values(tmp_path):
    journal = tmp_path / "journal.jsonl"
    supervisor.append_sanitized_journal(
        journal,
        {
            "event": "TEST_EVENT",
            "password": "operator-password-should-not-appear",
            "nested": {"approval_token": "approval-token-should-not-appear"},
        },
    )
    supervisor.append_sanitized_journal(journal, {"event": "SECOND_EVENT"})

    text = journal.read_text(encoding="utf-8")
    assert "operator-password-should-not-appear" not in text
    assert "approval-token-should-not-appear" not in text
    assert len(_journal(journal)) == 2
