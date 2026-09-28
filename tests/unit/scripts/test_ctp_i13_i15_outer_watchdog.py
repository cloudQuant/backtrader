"""Fake-only tests for the offline I13/I15 outer watchdog contract."""

from __future__ import annotations

import importlib.util
import gc
from pathlib import Path
import sys
import weakref

import pytest


_MODULE_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "ctp_i13_i15_outer_watchdog.py"
)
_SPEC = importlib.util.spec_from_file_location("i13_i15_outer_watchdog_test_module", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
watchdog = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = watchdog
_SPEC.loader.exec_module(watchdog)

_FAKE_HOST_CUSTODIAN: dict[str, "_FakeSession"] = {}


class _Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert 0.0 <= seconds <= 0.25
        self.sleeps.append(seconds)
        self.now += seconds


class _FakeSession:
    process_created = True

    def __init__(
        self,
        clock: _Clock,
        *,
        exit_at: float | None,
        exit_code: int = 0,
        job_empty: bool | None = True,
        assigned: bool | None = True,
        termination_succeeds: bool = True,
        job_termination_succeeds: bool | None = None,
        launcher_termination_succeeds: bool | None = None,
        release_succeeds: bool = True,
        resume_succeeds: bool = True,
    ) -> None:
        self.clock = clock
        self.exit_at = exit_at
        self.exit_code = exit_code
        self.empty = job_empty
        self.job_assignment_observed = assigned
        self.termination_succeeds = termination_succeeds
        self.job_termination_succeeds = (
            termination_succeeds
            if job_termination_succeeds is None
            else job_termination_succeeds
        )
        self.launcher_termination_succeeds = (
            termination_succeeds
            if launcher_termination_succeeds is None
            else launcher_termination_succeeds
        )
        self.release_succeeds = release_succeeds
        self.resume_succeeds = resume_succeeds
        self.resumed = False
        self.termination_calls = 0
        self.launcher_termination_calls = 0
        self.release_calls = 0

    def resume_launcher(self) -> bool:
        self.resumed = self.resume_succeeds
        return self.resume_succeeds

    def poll_launcher_exit_code(self) -> int | None:
        if self.exit_at is not None and self.clock.now >= self.exit_at:
            return self.exit_code
        return None

    def poll_job_empty(self) -> bool | None:
        if self.empty is None:
            return None
        return self.empty

    def terminate_job(self) -> bool:
        self.termination_calls += 1
        if self.job_termination_succeeds:
            self.exit_at = self.clock.now
            self.empty = True
            return True
        return False

    def terminate_launcher_process(self) -> bool:
        self.launcher_termination_calls += 1
        if self.launcher_termination_succeeds:
            self.exit_at = self.clock.now
            return True
        return False

    def release_controls(self) -> bool:
        self.release_calls += 1
        return self.release_succeeds


class _FakeBackend:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.calls = 0
        self.deadlines: list[float] = []

    def create_suspended_in_job(
        self, _command: object, *, deadline_monotonic: float
    ) -> _FakeSession:
        self.calls += 1
        self.deadlines.append(deadline_monotonic)
        return self.session

    def retain_controls(self, session: _FakeSession) -> str:
        token = "fake-host-escrow-" + str(id(session))
        _FAKE_HOST_CUSTODIAN[token] = session
        return token


class _EscrowOnlyBackend:
    """Use a host custodian independent of the ephemeral backend's lifetime."""

    def __init__(
        self,
        clock: _Clock,
        *,
        escrow_succeeds: bool = True,
        escrow_raises: bool = False,
        resume_succeeds: bool = True,
    ) -> None:
        self.clock = clock
        self.escrow_succeeds = escrow_succeeds
        self.escrow_raises = escrow_raises
        self.resume_succeeds = resume_succeeds
        self.session_ref: weakref.ReferenceType[_FakeSession] | None = None

    def create_suspended_in_job(
        self, _command: object, *, deadline_monotonic: float
    ) -> _FakeSession:
        del deadline_monotonic
        session = _FakeSession(
            self.clock,
            exit_at=None,
            job_empty=None,
            termination_succeeds=False,
            resume_succeeds=self.resume_succeeds,
        )
        self.session_ref = weakref.ref(session)
        return session

    def retain_controls(self, session: _FakeSession) -> str | None:
        if not self.escrow_succeeds:
            if self.escrow_raises:
                raise KeyboardInterrupt("fake escrow interruption")
            return None
        token = "host-escrow-" + str(id(session))
        _FAKE_HOST_CUSTODIAN[token] = session
        return token


class _OrphanCreationBackend:
    """Model a native create failure after an orphan Job reached host escrow."""

    def __init__(self, *, escrow_orphan: bool) -> None:
        self.escrow_orphan = escrow_orphan
        self.session_ref: weakref.ReferenceType[_FakeSession] | None = None
        self.token: str | None = None

    def create_suspended_in_job(
        self, _command: object, *, deadline_monotonic: float
    ) -> _FakeSession:
        del deadline_monotonic
        session = _FakeSession(_Clock(), exit_at=None, job_empty=None)
        self.session_ref = weakref.ref(session)
        if self.escrow_orphan:
            self.token = "orphan-escrow-" + str(id(session))
            _FAKE_HOST_CUSTODIAN[self.token] = session
        raise watchdog.OuterBackendCreationError(
            "process_creation_state_unknown", retention_token=self.token
        )

    def retain_controls(self, _session: _FakeSession) -> str | None:
        return None


class _SleepInterruptedClock(_Clock):
    def sleep(self, seconds: float) -> None:
        assert 0.0 <= seconds <= 0.25
        self.sleeps.append(seconds)
        raise KeyboardInterrupt("fake watchdog sleep interruption")


class _MonotonicInterruptedClock(_Clock):
    def __init__(self, now: float = 0.0, *, fail_on_call: int = 3) -> None:
        super().__init__(now)
        self.calls = 0
        self.fail_on_call = fail_on_call

    def monotonic(self) -> float:
        self.calls += 1
        if self.calls >= self.fail_on_call:
            raise KeyboardInterrupt("fake monotonic source interrupted")
        return self.now


def _command() -> object:
    return watchdog.FixedOuterCommand(("python.exe", "captured-launcher"), str(Path.cwd()), {})


def test_exited_launcher_requires_empty_job_and_keeps_outer_result_non_authorizing() -> None:
    clock = _Clock(10.0)
    session = _FakeSession(clock, exit_at=10.04, exit_code=7)
    backend = _FakeBackend(session)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=10.2,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.state == "exited"
    assert result.reason == "launcher_exited_job_empty"
    assert result.evidence.launcher_exit_code == 7
    assert result.evidence.containment == "verified"
    assert result.evidence.job_empty_observed is True
    assert result.evidence.job_termination_requested is False
    assert result.evidence.controls_retained is False
    assert result.evidence.retention_token is None
    assert session.release_calls == 1
    assert "success" not in result.state


def test_before_resume_runs_only_after_job_assignment_and_before_worker_start() -> None:
    clock = _Clock(10.0)
    session = _FakeSession(clock, exit_at=10.04, exit_code=0)
    backend = _FakeBackend(session)
    events = []

    def before_resume():
        events.append(("before_resume", session.job_assignment_observed, session.resumed))

    original_resume = session.resume_launcher

    def resume_launcher():
        events.append(("resume", session.job_assignment_observed, session.resumed))
        return original_resume()

    session.resume_launcher = resume_launcher
    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=10.2,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        before_resume=before_resume,
    )

    assert result.state == "exited"
    assert events == [("before_resume", True, False), ("resume", True, False)]


@pytest.mark.parametrize("failure_kind", ["reason", "exception", "invalid"])
def test_before_resume_failure_cleans_job_without_resuming(failure_kind) -> None:
    clock = _Clock(10.0)
    session = _FakeSession(clock, exit_at=None, job_empty=False)
    backend = _FakeBackend(session)

    def before_resume():
        if failure_kind == "reason":
            return "worker_stdio_parent_close_failed"
        if failure_kind == "exception":
            raise KeyboardInterrupt("synthetic handle close interruption")
        return "has spaces"

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=10.2,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        before_resume=before_resume,
    )

    expected = {
        "reason": "worker_stdio_parent_close_failed",
        "exception": "outer_before_resume_check_failed",
        "invalid": "outer_before_resume_reason_invalid",
    }[failure_kind]
    assert result.state == "unknown"
    assert result.reason == expected
    assert session.resumed is False
    assert session.termination_calls == 1
    assert session.release_calls == 1
    assert result.evidence.job_empty_observed is True
    assert result.evidence.controls_retained is False


def test_before_resume_is_not_called_when_job_assignment_is_unconfirmed() -> None:
    clock = _Clock(10.0)
    session = _FakeSession(clock, exit_at=None, assigned=None)
    backend = _FakeBackend(session)
    called = []

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=10.2,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        before_resume=lambda: called.append(True),
    )

    assert result.state == "unknown"
    assert result.reason == "job_assignment_unconfirmed"
    assert called == []
    assert session.resumed is False


def test_after_resume_runs_once_before_the_first_poll() -> None:
    clock = _Clock(10.0)
    session = _FakeSession(clock, exit_at=10.04, exit_code=0)
    backend = _FakeBackend(session)
    events = []
    original_resume = session.resume_launcher
    original_poll = session.poll_launcher_exit_code

    def resume_launcher():
        events.append("resume")
        return original_resume()

    def after_resume():
        events.append(("after_resume", session.resumed))

    def abort_requested():
        events.append("abort_poll")

    def poll_launcher_exit_code():
        events.append("launcher_poll")
        return original_poll()

    session.resume_launcher = resume_launcher
    session.poll_launcher_exit_code = poll_launcher_exit_code
    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=10.2,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        abort_requested=abort_requested,
        after_resume=after_resume,
    )

    assert result.state == "exited"
    assert events[0] == "resume"
    assert events[1] == ("after_resume", True)
    assert events[2] == "abort_poll"
    assert events[3] == "launcher_poll"
    assert events.count(("after_resume", True)) == 1


@pytest.mark.parametrize("failure_kind", ["reason", "exception", "invalid"])
def test_after_resume_failure_terminates_job_and_returns_unknown(failure_kind) -> None:
    clock = _Clock(10.0)
    session = _FakeSession(clock, exit_at=None, job_empty=False)
    backend = _FakeBackend(session)
    called = []

    def after_resume():
        called.append(session.resumed)
        if failure_kind == "reason":
            return "token_bootstrap_send_failed"
        if failure_kind == "exception":
            raise KeyboardInterrupt("synthetic token-channel interruption")
        return False

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=10.2,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        after_resume=after_resume,
    )

    expected_reason = {
        "reason": "token_bootstrap_send_failed",
        "exception": "outer_after_resume_check_failed",
        "invalid": "outer_after_resume_reason_invalid",
    }[failure_kind]
    assert result.state == "unknown"
    assert result.reason == expected_reason
    assert called == [True]
    assert session.termination_calls == 1
    assert session.release_calls == 1
    assert result.evidence.job_empty_observed is True
    assert result.evidence.controls_retained is False


def test_expired_deadline_after_resume_skips_after_resume_and_cleans_up() -> None:
    clock = _Clock(0.0)
    session = _FakeSession(clock, exit_at=None, job_empty=False)
    backend = _FakeBackend(session)
    after_calls = []
    original_resume = session.resume_launcher

    def resume_at_deadline():
        result = original_resume()
        clock.now = 1.0
        return result

    session.resume_launcher = resume_at_deadline
    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=1.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        after_resume=lambda: after_calls.append(True),
    )

    assert result.state == "timed_out"
    assert result.reason == "outer_deadline_exceeded"
    assert after_calls == []
    assert session.termination_calls == 1
    assert session.release_calls == 1
    assert result.evidence.job_empty_observed is True
    assert result.evidence.controls_retained is False


def test_expired_deadline_during_after_resume_hook_cleans_without_normal_poll() -> None:
    clock = _Clock(0.0)
    session = _FakeSession(clock, exit_at=None, job_empty=False)
    backend = _FakeBackend(session)
    events = []

    def after_resume():
        events.append(("after_resume", session.resumed))
        clock.now = 1.0

    def abort_requested():
        events.append("abort_poll")

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=1.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        abort_requested=abort_requested,
        after_resume=after_resume,
    )

    assert result.state == "timed_out"
    assert result.reason == "outer_deadline_exceeded"
    assert events == [("after_resume", True)]
    assert session.termination_calls == 1
    assert session.release_calls == 1
    assert result.evidence.job_empty_observed is True
    assert result.evidence.controls_retained is False


def test_deadline_kills_complete_job_and_still_reports_timeout() -> None:
    clock = _Clock(0.0)
    session = _FakeSession(clock, exit_at=None, job_empty=False)
    backend = _FakeBackend(session)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=0.1,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        poll_interval_seconds=0.05,
    )

    assert result.state == "timed_out"
    assert result.reason == "outer_deadline_exceeded"
    assert result.evidence.job_termination_requested is True
    assert result.evidence.job_termination_call_succeeded is True
    assert result.evidence.launcher_exit_observed is True
    assert result.evidence.job_empty_observed is True
    assert result.evidence.containment == "verified"
    assert result.evidence.controls_retained is False
    assert result.evidence.retention_token is None
    assert session.termination_calls == 1
    assert session.release_calls == 1
    assert clock.now == pytest.approx(0.1)


def test_timeout_with_unconfirmed_termination_or_tree_state_fails_closed() -> None:
    clock = _Clock(2.0)
    session = _FakeSession(
        clock,
        exit_at=None,
        job_empty=None,
        termination_succeeds=False,
    )
    backend = _FakeBackend(session)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=2.05,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        poll_interval_seconds=0.05,
    )

    assert result.state == "timed_out"
    assert result.evidence.job_termination_call_succeeded is False
    assert result.evidence.launcher_exit_observed is None
    assert result.evidence.job_empty_observed is None
    assert result.evidence.containment == "unknown"
    assert result.evidence.controls_retained is True
    assert result.evidence.retention_token is not None
    assert _FAKE_HOST_CUSTODIAN[result.evidence.retention_token] is session
    assert session.release_calls == 0
    _FAKE_HOST_CUSTODIAN.pop(result.evidence.retention_token)


def test_unresolved_controls_are_owned_by_backend_escrow_after_runner_returns() -> None:
    clock = _Clock(0.0)
    backend = _EscrowOnlyBackend(clock)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=0.05,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        poll_interval_seconds=0.05,
    )

    token = result.evidence.retention_token
    assert result.state == "timed_out"
    assert result.evidence.containment == "unknown"
    assert result.evidence.controls_retained is True
    assert token is not None
    assert backend.session_ref is not None
    assert backend.session_ref() is _FAKE_HOST_CUSTODIAN[token]
    assert token not in repr(result)
    session_ref = backend.session_ref
    del backend
    gc.collect()
    assert session_ref() is not None
    _FAKE_HOST_CUSTODIAN.pop(token)
    gc.collect()
    assert session_ref() is None


@pytest.mark.parametrize("escrow_raises", [False, True])
def test_unconfirmed_escrow_never_claims_controls_retained(escrow_raises) -> None:
    clock = _Clock(0.0)
    backend = _EscrowOnlyBackend(
        clock, escrow_succeeds=False, escrow_raises=escrow_raises
    )

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=0.05,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        poll_interval_seconds=0.05,
    )

    assert result.state == "timed_out"
    assert result.evidence.containment == "unknown"
    assert result.evidence.controls_retained is None
    assert result.evidence.retention_token is None
    assert backend.session_ref is not None
    assert backend.session_ref() is None


@pytest.mark.parametrize("resume_succeeds", [True, False])
def test_sleep_interrupt_terminates_and_escrows_without_escaping(resume_succeeds) -> None:
    clock = _SleepInterruptedClock(0.0)
    backend = _EscrowOnlyBackend(clock, resume_succeeds=resume_succeeds)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=10.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        poll_interval_seconds=0.05,
    )

    assert result.state == "unknown"
    assert result.reason == "watchdog_wait_interrupted"
    assert result.evidence.containment == "unknown"
    assert result.evidence.job_termination_requested is True
    assert result.evidence.job_termination_call_succeeded is False
    assert result.evidence.controls_retained is True
    token = result.evidence.retention_token
    assert token is not None
    assert _FAKE_HOST_CUSTODIAN[token] is not None
    _FAKE_HOST_CUSTODIAN.pop(token)


def test_monotonic_failure_after_creation_terminates_and_escrows() -> None:
    clock = _MonotonicInterruptedClock(0.0, fail_on_call=3)
    backend = _EscrowOnlyBackend(clock)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=10.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        poll_interval_seconds=0.05,
    )

    assert result.state == "timed_out"
    assert result.reason == "outer_clock_unavailable"
    assert result.evidence.containment == "unknown"
    assert result.evidence.job_termination_requested is True
    assert result.evidence.controls_retained is True
    token = result.evidence.retention_token
    assert token is not None
    assert _FAKE_HOST_CUSTODIAN[token] is not None
    _FAKE_HOST_CUSTODIAN.pop(token)


@pytest.mark.parametrize("escrow_orphan", [True, False])
def test_partial_creation_error_reports_only_confirmed_orphan_custody(
    escrow_orphan,
) -> None:
    clock = _Clock(0.0)
    backend = _OrphanCreationBackend(escrow_orphan=escrow_orphan)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=10.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.state == "unknown"
    assert result.reason == "process_creation_state_unknown"
    assert backend.session_ref is not None
    if escrow_orphan:
        token = result.evidence.retention_token
        assert token is not None
        assert token == backend.token
        assert result.evidence.controls_retained is True
        assert _FAKE_HOST_CUSTODIAN[token] is backend.session_ref()
        session_ref = backend.session_ref
        del backend
        gc.collect()
        assert session_ref() is not None
        _FAKE_HOST_CUSTODIAN.pop(token)
        gc.collect()
        assert session_ref() is None
    else:
        assert result.evidence.retention_token is None
        assert result.evidence.controls_retained is None
        assert backend.session_ref() is None


def test_unconfirmed_control_release_escrows_before_return() -> None:
    clock = _Clock(0.0)
    session = _FakeSession(
        clock,
        exit_at=0.0,
        job_empty=True,
        release_succeeds=False,
    )
    backend = _FakeBackend(session)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=1.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.state == "unknown"
    assert result.reason == "control_release_unconfirmed"
    assert result.evidence.containment == "unknown"
    assert result.evidence.controls_retained is True
    assert result.evidence.retention_token is not None
    assert _FAKE_HOST_CUSTODIAN[result.evidence.retention_token] is session
    _FAKE_HOST_CUSTODIAN.pop(result.evidence.retention_token)


def test_launcher_exit_with_a_live_descendant_terminates_job_and_fails_closed() -> None:
    clock = _Clock(5.0)
    session = _FakeSession(clock, exit_at=5.02, exit_code=0, job_empty=False)
    backend = _FakeBackend(session)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=6.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.state == "failed"
    assert result.reason == "descendant_or_job_state_unconfirmed"
    assert result.evidence.job_termination_requested is True
    assert result.evidence.job_termination_call_succeeded is True
    assert result.evidence.job_empty_observed is True
    assert result.evidence.containment == "verified"


def test_unconfirmed_atomic_assignment_stops_job_and_launcher_but_stays_unknown() -> None:
    clock = _Clock(7.0)
    session = _FakeSession(clock, exit_at=None, job_empty=True, assigned=None)
    backend = _FakeBackend(session)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=8.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.state == "unknown"
    assert result.reason == "job_assignment_unconfirmed"
    assert result.evidence.launcher_resumed is False
    assert result.evidence.launcher_termination_requested is True
    assert result.evidence.launcher_termination_call_succeeded is True
    assert result.evidence.job_termination_requested is True
    assert result.evidence.job_termination_call_succeeded is True
    assert result.evidence.launcher_exit_observed is True
    assert result.evidence.containment == "unknown"
    assert result.evidence.controls_retained is False
    assert session.resumed is False
    assert session.termination_calls == 1
    assert session.launcher_termination_calls == 1
    assert session.release_calls == 1


def test_unconfirmed_assignment_keeps_controls_if_job_is_not_empty() -> None:
    clock = _Clock(7.0)
    session = _FakeSession(
        clock,
        exit_at=None,
        job_empty=False,
        assigned=None,
        job_termination_succeeds=False,
        launcher_termination_succeeds=True,
    )
    backend = _FakeBackend(session)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=7.1,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.state == "unknown"
    assert result.reason == "job_assignment_unconfirmed"
    assert result.evidence.job_termination_requested is True
    assert result.evidence.job_termination_call_succeeded is False
    assert result.evidence.launcher_termination_call_succeeded is True
    assert result.evidence.launcher_exit_observed is True
    assert result.evidence.job_empty_observed is False
    assert result.evidence.controls_retained is True
    assert session.release_calls == 0
    _FAKE_HOST_CUSTODIAN.pop(result.evidence.retention_token)


def test_expired_absolute_deadline_does_not_create_a_launcher() -> None:
    clock = _Clock(11.0)
    session = _FakeSession(clock, exit_at=None)
    backend = _FakeBackend(session)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=11.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.state == "not_started"
    assert result.evidence.process_created is None
    assert result.evidence.containment == "not_started"
    assert backend.calls == 0


def test_worker_stop_deadline_leaves_hard_deadline_for_job_cleanup() -> None:
    clock = _Clock(20.0)
    session = _FakeSession(clock, exit_at=None, job_empty=False)
    backend = _FakeBackend(session)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=22.0,
        stop_deadline_monotonic=21.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert backend.deadlines == [22.0]
    assert result.state == "timed_out"
    assert result.reason == "outer_worker_deadline_exceeded"
    assert result.evidence.job_termination_requested is True
    assert result.evidence.job_termination_call_succeeded is True
    assert result.evidence.launcher_exit_observed is True
    assert result.evidence.job_empty_observed is True
    assert result.evidence.containment == "verified"
    assert result.evidence.controls_retained is False


def test_abort_signal_terminates_job_and_preserves_unknown_state():
    clock = _Clock(25.0)
    session = _FakeSession(clock, exit_at=None, job_empty=False)
    backend = _FakeBackend(session)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=backend,
        deadline_monotonic=30.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        abort_requested=lambda: "worker_output_limit_exceeded",
    )

    assert result.state == "unknown"
    assert result.reason == "worker_output_limit_exceeded"
    assert result.evidence.job_termination_requested is True
    assert result.evidence.job_termination_call_succeeded is True
    assert result.evidence.launcher_exit_observed is True
    assert result.evidence.job_empty_observed is True
    assert result.evidence.containment == "verified"
    assert result.evidence.controls_retained is False


def test_abort_check_interruption_cleans_up_and_stays_unknown():
    clock = _Clock(35.0)
    session = _FakeSession(clock, exit_at=None, job_empty=False)

    def interrupted_abort_check():
        raise KeyboardInterrupt("test interruption")

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=_FakeBackend(session),
        deadline_monotonic=40.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        abort_requested=interrupted_abort_check,
    )

    assert result.state == "unknown"
    assert result.reason == "outer_abort_check_failed"
    assert result.evidence.job_termination_requested is True
    assert result.evidence.job_empty_observed is True


def test_abort_check_rejects_non_string_reason_without_success_fallback():
    clock = _Clock(45.0)
    session = _FakeSession(clock, exit_at=None, job_empty=False)

    result = watchdog.run_outer_watchdog(
        _command(),
        backend=_FakeBackend(session),
        deadline_monotonic=50.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        abort_requested=lambda: True,
    )

    assert result.state == "unknown"
    assert result.reason == "outer_abort_reason_invalid"
    assert result.evidence.job_termination_call_succeeded is True
    assert result.evidence.job_empty_observed is True


def test_worker_stop_deadline_cannot_exceed_the_hard_deadline() -> None:
    clock = _Clock(30.0)
    session = _FakeSession(clock, exit_at=None)

    with pytest.raises(ValueError, match="outer_stop_deadline_invalid"):
        watchdog.run_outer_watchdog(
            _command(),
            backend=_FakeBackend(session),
            deadline_monotonic=32.0,
            stop_deadline_monotonic=33.0,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )


def test_outer_command_snapshots_arguments_and_environment() -> None:
    environment = {"PATH": "fake-path"}
    command = watchdog.FixedOuterCommand(("python.exe", "captured-launcher"), str(Path.cwd()), environment)
    environment["PATH"] = "changed"

    assert command.env["PATH"] == "fake-path"
    with pytest.raises(TypeError):
        command.env["PATH"] = "mutated"  # type: ignore[index]


def test_outer_command_rejects_duplicate_windows_environment_keys() -> None:
    with pytest.raises(ValueError, match="outer_command_environment_invalid"):
        watchdog.FixedOuterCommand(
            ("python.exe",), str(Path.cwd()), {"Path": "a", "PATH": "b"}
        )
