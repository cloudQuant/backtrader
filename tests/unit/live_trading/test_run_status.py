"""BT process contract: heartbeat status file, final summary, exit codes, budget.

Iteration 66, §5.2 B2/B3/B5.  Evidence: UNIT/FAKE — temporary strategy
directories, fakes for the Broker facts; no provider, account or network.
Every constructor argument is a *configuration* value of this process, never an
operational number taken from a private input.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid

import pytest

from backtrader import live_state as ls
from backtrader.live_trading import (
    EXIT_BLOCKED,
    EXIT_STOPPED,
    EXIT_STOPPED_WITH_WORKING_ORDERS,
    EXIT_STOPPED_WITH_WRITE_IN_FLIGHT,
    EXIT_UNEXPECTED,
    RunFacts,
    RunStatusError,
    RunStatusWriter,
    compute_stop_budget,
    derive_outcome,
    exit_code_for,
    read_run_status,
)
from backtrader.live_trading import run_status as status


def _uuid() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def strategy_dir(tmp_path):
    directory = tmp_path / "strategy"
    directory.mkdir()
    return directory


def _writer(strategy_dir, **kwargs):
    values = {"run_id": _uuid(), "strategy_uuid": _uuid(), "heartbeat_interval_s": 0.05}
    values.update(kwargs)
    return RunStatusWriter(strategy_dir, **values)


# ---------------------------------------------------------------------------
# B2: the status document
# ---------------------------------------------------------------------------
def test_status_document_is_the_strict_whitelist(strategy_dir):
    writer = _writer(strategy_dir)
    writer.start()
    try:
        document = read_run_status(writer.path)
    finally:
        writer.stop_heartbeat()
    assert set(document) == status.STATUS_KEYS
    assert document["schema"] == "bt_api_run_status/v1"
    assert document["pid"] == os.getpid()
    assert document["run_id"] == writer.run_id
    assert document["phase"] == "INITIALIZING"
    assert document["heartbeat_sequence"] >= 1
    assert document["heartbeat_interval_s"] == 0.05
    assert document["budget_proven"] is False and document["stop_budget_s"] is None
    assert document["stop_source"] is None and document["stop_requested_at_utc"] is None


def test_status_document_never_contains_symbol_names_or_secrets(strategy_dir):
    class Feed:
        def trade_qualification(self):
            return type("Q", (), {"ok": True})()

    writer = _writer(
        strategy_dir,
        feeds=[Feed(), Feed()],
        facts_provider=lambda: RunFacts(
            write_block_reasons=("account_password_123", "settlement_unconfirmed"),
            unknown_unresolved_count=2,
            active_order_count=1,
            last_error_code="Bad Code!",
        ),
    )
    writer.start()
    try:
        text = open(writer.path, "r", encoding="utf-8").read()
        document = read_run_status(writer.path)
    finally:
        writer.stop_heartbeat()
    assert "rb2701" not in text and "SimNow" not in text
    assert "password" not in text
    # A non-code reason is collapsed into one finite code, never published.
    assert document["write_block_reasons"] == ["settlement_unconfirmed", "unclassified"]
    assert document["unknown_unresolved_count"] == 2
    assert document["active_order_count"] == 1
    assert document["last_error_code"] is None  # "Bad Code!" is not a finite code
    assert document["datas"] == [
        {"index": 0, "state": "LIVE"},
        {"index": 1, "state": "LIVE"},
    ]


def test_unknown_facts_stay_null_and_never_zero():
    assert status._validate_facts(None) == RunFacts()
    facts = status._validate_facts(
        {
            "write_block_reasons": "not-a-sequence",
            "unknown_unresolved_count": -1,
            "last_error_code": "Account_password_1",
        }
    )
    assert facts.write_block_reasons is None
    assert facts.unknown_unresolved_count is None
    assert facts.active_order_count is None
    assert facts.last_error_code is None  # a secret-looking code is never published


def test_heartbeat_thread_advances_while_the_main_thread_is_blocked(strategy_dir):
    writer = _writer(strategy_dir, heartbeat_interval_s=0.05)
    writer.start()
    try:
        first = read_run_status(writer.path)
        writer.loop_progress()
        assert writer._write_status() is True
        progress = read_run_status(writer.path)["main_loop_last_progress_utc"]
        assert progress is not None
        blocked = threading.Event()

        def block():
            blocked.set()
            time.sleep(0.4)

        thread = threading.Thread(target=block)
        thread.start()
        blocked.wait(1.0)
        thread.join()
        later = read_run_status(writer.path)
        assert later["heartbeat_sequence"] >= first["heartbeat_sequence"] + 3
        assert later["updated_at_utc"] >= first["updated_at_utc"]
        assert later["main_loop_last_progress_utc"] == progress  # main loop did not advance
    finally:
        writer.stop_heartbeat()


@pytest.mark.parametrize(
    "interval", [0.0, -1, 0.01, 300.0001, float("inf"), float("nan"), True, "1"]
)
def test_heartbeat_interval_is_bounded(strategy_dir, interval):
    with pytest.raises(RunStatusError) as err:
        RunStatusWriter(strategy_dir, heartbeat_interval_s=interval)
    assert err.value.code == "invalid_interval"


def test_heartbeat_interval_bounds_accept_the_edges(strategy_dir):
    for interval in (status.MIN_HEARTBEAT_INTERVAL_S, status.MAX_HEARTBEAT_INTERVAL_S):
        writer = RunStatusWriter(strategy_dir, heartbeat_interval_s=interval)
        assert writer.heartbeat_interval_s == interval


def test_phase_and_data_state_are_validated(strategy_dir):
    writer = _writer(strategy_dir)
    with pytest.raises(RunStatusError):
        writer.set_phase("RUNNING")
    with pytest.raises(RunStatusError):
        writer.set_data_state(-1, "LIVE")
    with pytest.raises(RunStatusError):
        writer.set_data_state(256, "LIVE")
    with pytest.raises(RunStatusError):
        writer.set_data_state(0, "warmup")
    writer.set_phase("RECONCILING")
    writer.set_data_state(0, "WARMUP")
    writer.start()
    try:
        document = read_run_status(writer.path)
    finally:
        writer.stop_heartbeat()
    assert document["phase"] == "RECONCILING"
    assert document["datas"] == [{"index": 0, "state": "WARMUP"}]


def test_an_injected_crash_before_the_rename_leaves_the_previous_document(
    strategy_dir, monkeypatch
):
    from backtrader.live_state import atomic as atomic_module

    writer = _writer(strategy_dir, heartbeat_interval_s=300.0)
    writer.start()
    try:
        raw_before = open(writer.path, "rb").read()
        calls = {"n": 0}

        def fail_once(src, dst):
            calls["n"] += 1
            raise OSError("injected crash before the rename")

        monkeypatch.setattr(atomic_module, "_replace", fail_once)
        assert writer._write_status() is False
        # The previous document is intact and parseable, no half file remains.
        assert open(writer.path, "rb").read() == raw_before
        assert read_run_status(writer.path)["heartbeat_sequence"] >= 1
        assert [name for name in os.listdir(writer.state_dir) if name.endswith(".tmp")] == []
        assert writer._document()["last_error_code"] == "status_write_failed"
    finally:
        writer.stop_heartbeat()


def test_an_injected_crash_during_the_temp_write_leaves_the_previous_document(
    strategy_dir, monkeypatch
):
    from backtrader.live_state import atomic as atomic_module

    writer = _writer(strategy_dir, heartbeat_interval_s=300.0)
    writer.start()
    try:
        raw_before = open(writer.path, "rb").read()
        real_fsync = atomic_module.os.fsync
        state = {"failed": False}

        def fail_fsync(fd):
            if not state["failed"]:
                state["failed"] = True
                raise OSError("injected crash before fsync")
            return real_fsync(fd)

        monkeypatch.setattr(atomic_module.os, "fsync", fail_fsync)
        assert writer._write_status() is False
        assert open(writer.path, "rb").read() == raw_before
        assert [name for name in os.listdir(writer.state_dir) if name.endswith(".tmp")] == []
        assert writer._write_status() is True  # the next tick recovers
    finally:
        writer.stop_heartbeat()


def test_the_status_file_lives_in_the_live_state_state_dir(strategy_dir):
    ls.initialize_identity(str(strategy_dir))
    paths = ls.StrategyStateDir(str(strategy_dir)).paths
    assert os.path.dirname(status.run_status_path(str(strategy_dir))) == paths.state_dir
    assert os.path.dirname(status.last_run_path(str(strategy_dir))) == paths.state_dir
    assert status.STATUS_FILENAME == "run_status.json"
    assert status.LAST_RUN_FILENAME == "last_run.json"


def test_strategy_uuid_is_read_through_live_state(strategy_dir):
    writer = RunStatusWriter(strategy_dir, run_id=_uuid())
    writer.start()
    try:
        assert read_run_status(writer.path)["strategy_uuid"] is None  # not initialized yet
        identity = ls.initialize_identity(str(strategy_dir))
        document = read_run_status(writer.path)
        assert document["strategy_uuid"] is None  # no write happened yet
        assert writer._write_status() is True
        assert read_run_status(writer.path)["strategy_uuid"] == identity.strategy_uuid
    finally:
        writer.stop_heartbeat()


# ---------------------------------------------------------------------------
# stop request source and first time (B1-66.02)
# ---------------------------------------------------------------------------
def test_the_first_stop_request_is_recorded_once(strategy_dir):
    writer = _writer(strategy_dir)
    writer.note_stop_request("SIGTERM", "2026-11-15T10:00:00.000000+00:00")
    writer.note_stop_request("stop_file", "2026-11-15T10:00:05.000000+00:00")
    writer.start()
    try:
        document = read_run_status(writer.path)
    finally:
        writer.stop_heartbeat()
    assert document["stop_source"] == "SIGTERM"
    assert document["stop_requested_at_utc"] == "2026-11-15T10:00:00.000000+00:00"
    with pytest.raises(RunStatusError):
        writer.note_stop_request("CTRL_C")


def test_the_stop_request_provider_is_polled_by_the_heartbeat(strategy_dir):
    state = {"value": None}
    writer = _writer(strategy_dir, stop_request_provider=lambda: state["value"])
    writer.start()
    try:
        assert read_run_status(writer.path)["stop_source"] is None
        state["value"] = ("stop_file", "2026-11-15T10:00:00.000000+00:00")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            document = read_run_status(writer.path)
            if document["stop_source"]:
                break
            time.sleep(0.02)
        assert document["stop_source"] == "stop_file"
        assert document["stop_requested_at_utc"].startswith("2026-11-15T10:00:00")
    finally:
        writer.stop_heartbeat()


# ---------------------------------------------------------------------------
# B3: final summary and exit codes
# ---------------------------------------------------------------------------
def _finish(strategy_dir, **kwargs):
    summary = kwargs.pop("broker_summary", {"status": "STOPPED"})
    writer = _writer(strategy_dir)
    writer.start()
    result = writer.finish(broker_summary=summary, **kwargs)
    return writer, result


def test_last_run_is_exactly_the_runtime_summary_and_the_details_companion(strategy_dir):
    writer, result = _finish(
        strategy_dir, broker_summary={"status": "STOPPED", "cancelled_requested": 1}
    )
    summary = json.loads(open(writer.last_run_path, encoding="utf-8").read())
    assert set(summary) == {
        "schema",
        "strategy_uuid",
        "run_id",
        "process",
        "outcome",
        "stop_source",
        "stop_requested_at_utc",
        "working_orders_unresolved",
        "write_in_flight_unresolved",
        "unknown_unresolved",
        "startup_rejected",
        "rejection_code",
    }
    assert summary["schema"] == "bt_api_run_summary/v1"
    assert summary["strategy_uuid"] == writer._strategy_uuid
    assert str(uuid.UUID(summary["run_id"])) == summary["run_id"]
    assert set(summary["process"]) == {"pid", "create_time", "boot_id", "command_digest"}
    assert summary["process"]["pid"] == os.getpid()
    assert summary["outcome"] == "STOPPED"
    assert summary["stop_source"] == "UNKNOWN"
    assert result.exit_code == EXIT_STOPPED and result.summary_written is True

    details = json.loads(open(writer.last_run_details_path, encoding="utf-8").read())
    assert details["schema"] == "backtrader.run_details/v1"
    assert details["exit_code"] == EXIT_STOPPED
    assert details["broker_status"] == "STOPPED"
    assert details["broker_summary"] == {"status": "STOPPED", "cancelled_requested": 1}
    assert details["reason"] == "stopped_clean"
    assert details["heartbeat_sequence"] >= 1
    assert details["stop_budget"]["proven"] is False


@pytest.mark.parametrize(
    "broker_status,outcome,exit_code,flags",
    [
        ("STOPPED", "STOPPED", EXIT_STOPPED, (False, False, False)),
        ("NOT_STARTED", "STOPPED", EXIT_STOPPED, (False, False, False)),
        (
            "STOPPED_WITH_WORKING_ORDERS",
            "STOPPED_WITH_WORKING_ORDERS",
            EXIT_STOPPED_WITH_WORKING_ORDERS,
            (True, False, False),
        ),
        (
            "STOPPED_WITH_WRITE_IN_FLIGHT",
            "STOPPED_WITH_WRITE_IN_FLIGHT",
            EXIT_STOPPED_WITH_WRITE_IN_FLIGHT,
            (False, True, False),
        ),
        ("UNKNOWN", "UNKNOWN", EXIT_UNEXPECTED, (False, False, True)),
    ],
)
def test_each_summary_status_has_its_outcome_and_exit_code(
    strategy_dir, broker_status, outcome, exit_code, flags
):
    writer, result = _finish(strategy_dir, broker_summary={"status": broker_status})
    summary = json.loads(open(writer.last_run_path, encoding="utf-8").read())
    assert (summary["outcome"], result.exit_code) == (outcome, exit_code)
    assert (
        summary["working_orders_unresolved"],
        summary["write_in_flight_unresolved"],
        summary["unknown_unresolved"],
    ) == flags


def test_blocked_needs_a_finite_rejection_code(strategy_dir):
    class Refusal(RuntimeError):
        def __init__(self):
            self.code = "first_init_required"
            self.detail = "flat account required"

    writer, result = _finish(
        strategy_dir, broker_summary={"status": "NOT_STARTED"}, exception=Refusal()
    )
    summary = json.loads(open(writer.last_run_path, encoding="utf-8").read())
    assert summary["outcome"] == "BLOCKED"
    assert (
        summary["startup_rejected"] is True and summary["rejection_code"] == "first_init_required"
    )
    assert result.exit_code == EXIT_BLOCKED
    # A broker status that merely says BLOCKED proves no rejection: the
    # outcome stays UNKNOWN and exits 1, matching the runtime's
    # summarize_stop_state (INV66-04).
    outcome, flags = derive_outcome({"status": "BLOCKED"})
    assert outcome == "UNKNOWN" and flags["startup_rejected"] is False
    assert exit_code_for(outcome) == EXIT_UNEXPECTED


def test_a_stop_after_a_committed_start_write_is_unknown_not_not_started(strategy_dir):
    class DirectStartStopped(RuntimeError):
        def __init__(self):
            self.code = "stop_requested"
            self.detail = "after_settlement_step"

    writer, result = _finish(
        strategy_dir,
        broker_summary={
            "status": "UNKNOWN",
            "reason": "stop_requested_during_start",
            "startup_write": "committed",
        },
        exception=DirectStartStopped(),
    )
    summary = json.loads(open(writer.last_run_path, encoding="utf-8").read())
    assert summary["outcome"] == "UNKNOWN" and summary["unknown_unresolved"] is True
    assert summary["startup_rejected"] is False
    details = json.loads(open(writer.last_run_details_path, encoding="utf-8").read())
    assert details["reason"] == "stop_requested_during_start"
    assert result.exit_code == EXIT_UNEXPECTED


def test_a_provable_not_started_stop_is_clean(strategy_dir):
    class DirectStartStopped(RuntimeError):
        def __init__(self):
            self.code = "stop_requested"
            self.detail = "read_only_queries"

    writer, result = _finish(
        strategy_dir,
        broker_summary={"status": "NOT_STARTED", "reason": "stop_requested_during_start"},
        exception=DirectStartStopped(),
    )
    summary = json.loads(open(writer.last_run_path, encoding="utf-8").read())
    assert summary["outcome"] == "STOPPED" and result.exit_code == EXIT_STOPPED


def test_an_unexpected_exception_is_a_crash(strategy_dir):
    writer, result = _finish(strategy_dir, broker_summary=None, exception=ZeroDivisionError("x"))
    summary = json.loads(open(writer.last_run_path, encoding="utf-8").read())
    assert summary["outcome"] == "CRASHED" and result.exit_code == EXIT_UNEXPECTED
    details = json.loads(open(writer.last_run_details_path, encoding="utf-8").read())
    assert details["exception_type"] == "ZeroDivisionError"
    assert details["reason"] == "unexpected_exception"


def test_every_outcome_has_a_distinct_exit_code():
    assert exit_code_for("STOPPED") == 0
    assert exit_code_for("BLOCKED") == 2
    assert exit_code_for("STOPPED_WITH_WORKING_ORDERS") == 3
    assert exit_code_for("STOPPED_WITH_WRITE_IN_FLIGHT") == 4
    assert exit_code_for("CRASHED") == 1
    assert exit_code_for("UNKNOWN") == 1
    assert exit_code_for("not-an-outcome") == 1


def test_a_summary_without_a_strategy_uuid_is_not_a_clean_stop(strategy_dir):
    writer = RunStatusWriter(strategy_dir, run_id=_uuid(), heartbeat_interval_s=0.05)
    writer.start()
    result = writer.finish(broker_summary={"status": "STOPPED"})
    assert result.summary_written is False and result.exit_code == EXIT_UNEXPECTED
    assert not os.path.exists(writer.last_run_path)
    details = json.loads(open(writer.last_run_details_path, encoding="utf-8").read())
    assert details["summary_written"] is False
    assert details["write_error"] == "process_identity_unavailable"


def test_a_failed_summary_write_exits_non_zero(strategy_dir, monkeypatch):
    writer = _writer(strategy_dir)
    writer.start()

    def crash(_path, _document):
        raise OSError("disk full")

    monkeypatch.setattr(status, "atomic_write_json", crash)
    result = writer.finish(broker_summary={"status": "STOPPED"})
    assert result.summary_written is False
    assert result.exit_code == EXIT_UNEXPECTED


def test_finish_is_idempotent(strategy_dir):
    writer = _writer(strategy_dir)
    writer.start()
    first = writer.finish(broker_summary={"status": "STOPPED"})
    second = writer.finish(broker_summary={"status": "STOPPED_WITH_WORKING_ORDERS"})
    assert second is first
    assert writer.finished is True
    # The STOPPED status document is written once at the end.
    assert read_run_status(writer.path)["phase"] == "STOPPED"


def test_process_identity_is_well_formed_and_not_invented():
    identity = status.read_process_identity()
    assert set(identity) == {"pid", "create_time", "boot_id", "command_digest", "source"}
    assert identity["pid"] == os.getpid()
    for name in ("create_time", "boot_id", "command_digest", "source"):
        assert type(identity[name]) is str and identity[name]
    assert (
        identity["command_digest"].startswith("sha256:")
        or identity["command_digest"] == "unavailable"
    )


# ---------------------------------------------------------------------------
# B5: the stop budget
# ---------------------------------------------------------------------------
def test_budget_without_proven_phases_is_published_as_unproven():
    budget = compute_stop_budget(
        stop_cancel_timeout=10.0,
        direct_stop_write_timeout=35.0,
        startup_facts_attempts=3,
        direct_facts_timeout=10.0,
        startup_facts_retry_delay=2.0,
    )
    assert budget["proven"] is False and budget["total_seconds"] is None
    assert budget["unproven_phases"] == ["cancel_request", "start_in_progress", "tail"]
    assert budget["components"]["cancel_wait_s"] == 10.0
    assert budget["components"]["committed_write_wait_s"] == 35.0
    assert budget["components"]["startup_facts_retry_s"] == 34.0
    assert budget["parameters"]["direct_startup_facts_attempts"] == 3


def test_budget_with_every_proven_bound_is_the_serial_sum():
    budget = compute_stop_budget(
        stop_cancel_timeout=10.0,
        direct_stop_write_timeout=35.0,
        startup_facts_attempts=3,
        direct_facts_timeout=10.0,
        startup_facts_retry_delay=2.0,
        start_in_progress_bound_s=120.0,
        cancel_request_bound_s=5.0,
        tail_bound_s=15.0,
    )
    assert budget["proven"] is True
    assert budget["unproven_phases"] == []
    assert budget["total_seconds"] == 185.0
    assert budget["components"]["startup_facts_retry_s"] == 34.0  # not added again


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan"), "10", True])
def test_an_invalid_configuration_value_leaves_its_phase_unproven(value):
    budget = compute_stop_budget(stop_cancel_timeout=value, direct_stop_write_timeout=35.0)
    assert budget["components"]["cancel_wait_s"] is None
    assert "cancel_wait" in budget["unproven_phases"]
    assert budget["parameters"]["stop_cancel_timeout"] is None
    assert budget["proven"] is False


def test_budget_parameters_are_published_with_the_document(strategy_dir):
    budget = compute_stop_budget(stop_cancel_timeout=1.0, direct_stop_write_timeout=2.0)
    writer = _writer(strategy_dir, stop_budget=budget)
    writer.start()
    try:
        document = read_run_status(writer.path)
    finally:
        writer.stop_heartbeat()
    assert document["budget_proven"] is False and document["stop_budget_s"] is None
    assert document["stop_budget"] == budget


def test_a_malformed_budget_is_refused(strategy_dir):
    with pytest.raises(RunStatusError) as err:
        RunStatusWriter(strategy_dir, stop_budget={"proven": True})
    assert err.value.code == "invalid_budget"
    budget = compute_stop_budget(stop_cancel_timeout=1.0)
    budget["total_seconds"] = 5.0  # proven is False: contradictory
    with pytest.raises(RunStatusError):
        RunStatusWriter(strategy_dir, stop_budget=budget)


def test_direct_stop_budget_reads_the_broker_parameters():
    class Params:
        stop_cancel_timeout = 10.0
        direct_stop_write_timeout = 35.0
        direct_startup_facts_attempts = 3
        direct_facts_timeout = 10.0
        direct_startup_facts_retry_delay = 2.0

    class Broker:
        p = Params()

    budget = status.direct_stop_budget(Broker())
    assert budget["components"]["cancel_wait_s"] == 10.0
    assert budget["components"]["committed_write_wait_s"] == 35.0
    assert budget["unproven_phases"] == ["cancel_request", "start_in_progress", "tail"]
    proven = status.direct_stop_budget(
        Broker(), start_in_progress_bound_s=1.0, cancel_request_bound_s=1.0, tail_bound_s=1.0
    )
    assert proven["proven"] is True and proven["total_seconds"] == 48.0


# ---------------------------------------------------------------------------
# readers and mutation guards
# ---------------------------------------------------------------------------
def test_a_document_with_an_extra_key_is_refused(strategy_dir):
    writer = _writer(strategy_dir)
    writer.start()
    try:
        document = read_run_status(writer.path)
        document["account_number"] = "123456"
        ls.atomic_write_json(writer.path, document)
        with pytest.raises(RunStatusError) as err:
            read_run_status(writer.path)
        assert err.value.code in ("status_document_invalid", "value_not_json_safe")
    finally:
        writer.stop_heartbeat()


def test_set_last_error_accepts_only_finite_codes(strategy_dir):
    writer = _writer(strategy_dir)
    with pytest.raises(RunStatusError):
        writer.set_last_error("SimNow 12345 failed")
    writer.set_last_error("return_gap_reconcile")
    writer.start()
    try:
        assert read_run_status(writer.path)["last_error_code"] == "return_gap_reconcile"
    finally:
        writer.stop_heartbeat()


def test_a_run_id_must_be_a_uuid(strategy_dir):
    with pytest.raises(RunStatusError):
        RunStatusWriter(strategy_dir, run_id="run-1")
    writer = RunStatusWriter(strategy_dir, run_id=str(uuid.uuid4()).upper())
    assert writer.run_id == writer.run_id.lower()
