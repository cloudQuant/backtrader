from pathlib import Path

import pytest

from backtrader_agent.canonical import atomic_write_json, hash_object
from backtrader_agent.errors import AgentError
from backtrader_agent.report import METRIC_NAMES
from backtrader_agent.roots import RootRegistry
from backtrader_agent.runner import ControlledRunner
from backtrader_agent.sessions import SessionStore
from backtrader_agent.tokens import TokenAuthority


def _running_session(store: SessionStore, session_id: str, subject: str, effect_id: str) -> None:
    store.create(session_id)
    for state in (
        "DATA_READY",
        "SPEC_DRAFT",
        "SPEC_APPROVED",
        "SOURCES_SELECTED",
        "DRAFT_READY",
        "VALIDATED",
        "APPLY_PREPARED",
    ):
        store.transition(session_id, state, state.lower(), {"input": state})
    store.transition(
        session_id,
        "APPLIED",
        "changes-apply",
        {"applied": "a" * 64},
        approval_token_id="tok-change",
    )
    store.transition(
        session_id,
        "RUN_APPROVED",
        "run-approve",
        {"run": subject},
        approval_token_id="tok-run",
    )
    store.transition(
        session_id,
        "RUNNING",
        "controlled-run-start",
        {"run": subject},
        idempotency_key="run-effect",
        approval_token_id="tok-run",
        effect_references={
            "run_subject_hash": subject,
            "run_effect_id": effect_id,
        },
    )


def test_partial_report_and_paused_session_resume_same_effect(tmp_path: Path) -> None:
    state = tmp_path / "state"
    subject = "a" * 64
    effect_id = "b" * 64
    sessions = SessionStore(state)
    _running_session(sessions, "session-resume", subject, effect_id)
    assert sessions.recover("session-resume")["state"] == "PAUSED"

    with pytest.raises(AgentError, match="BTAG-RUN-SESSION"):
        ControlledRunner._begin_or_resume_session(
            sessions,
            session_id="session-resume",
            subject=subject,
            effect_id="c" * 64,
            idempotency_key="run-effect",
            run_token={"token_id": "tok-run"},
        )

    result = {
        "schema_version": "run-result-v1",
        "run_id": "run-" + subject[:20],
        "status": "passed",
        "metrics": dict.fromkeys(METRIC_NAMES, 1),
        "diagnostics": [],
        "artifacts": [],
        "extensions": {
            "backtrader_agent": {
                "mode": "runonce",
                "dataset_manifest_hash": "d" * 64,
                "applied_artifact_hash": "e" * 64,
                "manifest_hash": "f" * 64,
                "validation_token_id": "tok-validation",
                "run_token_id": "tok-run",
                "limitations": [],
            }
        },
    }
    result["result_hash"] = hash_object(result)
    run_root = state / "runs" / result["run_id"]
    run_root.mkdir(parents=True)
    atomic_write_json(run_root / "run-result.json", result, create_only=True)

    runner = ControlledRunner(RootRegistry(state), state, TokenAuthority(state))
    reports = runner._render_reports_resumable(run_root, result)
    assert (run_root / "report.md").is_file()
    assert (run_root / "report.html").is_file()

    runner._finish_successful_session(
        sessions,
        session_id="session-resume",
        subject=subject,
        effect_id=effect_id,
        idempotency_key="run-effect",
        run_token={"token_id": "tok-run"},
        result=result,
        report_hash=reports["report_hash"],
    )
    assert sessions.load("session-resume")["state"] == "COMPLETED"
