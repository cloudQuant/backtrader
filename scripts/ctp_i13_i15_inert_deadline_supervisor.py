"""Unregistered inert-only process supervisor for a fixed sleep guardian.

This candidate starts the existing inert guardian as a separate process in a
Windows Job that the supervisor owns.  The worker can block in its own backend
without blocking the supervisor's deadline loop.  The CLI accepts only a
bounded sleep and fixed receipt location; it has no command, config, marker,
provider, SDK, or network input.

This is a process-topology candidate, not a trusted host or an ordinary
preflight route.  It does not prove a deadline through a blocked kernel call
inside the supervisor itself, machine suspension, or OS failure.  At the
deadline it records UNKNOWN and requests Job termination; a receipt never
claims that process exit or Job emptiness was observed if the watchdog could
not observe those facts before its deadline.
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import sys
import time
from typing import Callable, Optional, Sequence

from scripts.ctp_i13_i15_outer_watchdog import FixedOuterCommand, run_outer_watchdog
from scripts.ctp_i13_i15_windows_guardian import (
    _result_payload,
    _validate_receipt_root,
    _write_receipt,
)
from scripts.ctp_i13_i15_windows_job_backend import WindowsJobBackend


_SCHEMA = "ctp_i13_i15_inert_deadline_supervisor_receipt.v1"
_MAX_CHILD_SECONDS = 300.0
_MAX_TOTAL_SECONDS = 310.0
_MIN_CLEANUP_RESERVE_SECONDS = 0.5
_RECEIPT_NAME = "guardian-supervisor-receipt.json"
_PARENT_STAGES = ("complete", "setup-block", "worker-block", "close-block", "receipt-fail")


class _TimedSession:
    """Capture watchdog call/observation times without changing Job ownership."""

    def __init__(self, session: object, *, times: dict[str, object], monotonic) -> None:
        self._session = session
        self._times = times
        self._monotonic = monotonic

    @property
    def process_created(self):
        return self._session.process_created

    @property
    def job_assignment_observed(self):
        return self._session.job_assignment_observed

    def _stamp(self, name: str) -> None:
        try:
            value = float(self._monotonic())
        except BaseException:
            value = None
        self._times.setdefault(name, value)

    def resume_launcher(self):
        self._stamp("launcher_resume_call_started_monotonic")
        result = self._session.resume_launcher()
        self._stamp("launcher_resume_call_returned_monotonic")
        return result

    def poll_launcher_exit_code(self):
        result = self._session.poll_launcher_exit_code()
        if result is not None:
            self._stamp("launcher_exit_observed_monotonic")
        return result

    def poll_job_empty(self):
        result = self._session.poll_job_empty()
        if result is True:
            self._stamp("job_empty_observed_monotonic")
        return result

    def terminate_job(self):
        self._stamp("job_termination_call_started_monotonic")
        result = self._session.terminate_job()
        self._stamp("job_termination_call_returned_monotonic")
        return result

    def terminate_launcher_process(self):
        self._stamp("launcher_termination_call_started_monotonic")
        result = self._session.terminate_launcher_process()
        self._stamp("launcher_termination_call_returned_monotonic")
        return result

    def release_controls(self):
        result = self._session.release_controls()
        if result is True:
            self._stamp("controls_released_monotonic")
        return result


class _TimedBackend:
    """Decorate the real backend to receipt only observed call timestamps."""

    def __init__(self, backend: object, *, times: dict[str, object], monotonic) -> None:
        self._backend = backend
        self._times = times
        self._monotonic = monotonic

    def _stamp(self, name: str) -> None:
        try:
            value = float(self._monotonic())
        except BaseException:
            value = None
        self._times.setdefault(name, value)

    def create_suspended_in_job(self, command, *, deadline_monotonic):
        self._stamp("process_creation_call_started_monotonic")
        session = self._backend.create_suspended_in_job(
            command, deadline_monotonic=deadline_monotonic
        )
        self._stamp("process_creation_call_returned_monotonic")
        return _TimedSession(session, times=self._times, monotonic=self._monotonic)

    def retain_controls(self, session):
        inner = session._session if type(session) is _TimedSession else session
        return self._backend.retain_controls(inner)


def _system_environment() -> dict[str, str]:
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return {
        "PATH": os.path.dirname(os.path.abspath(sys.executable)),
        "SYSTEMROOT": system_root,
        "WINDIR": os.environ.get("WINDIR", system_root),
    }


def _validate_deadlines(
    *,
    child_seconds: object,
    stop_deadline_monotonic: object,
    deadline_monotonic: object,
    now: float,
) -> tuple[float, float, float]:
    child = float(child_seconds) if type(child_seconds) in (int, float) else float("nan")
    stop = (
        float(stop_deadline_monotonic)
        if type(stop_deadline_monotonic) in (int, float)
        else float("nan")
    )
    deadline = (
        float(deadline_monotonic) if type(deadline_monotonic) in (int, float) else float("nan")
    )
    if not math.isfinite(child) or not 0.0 < child <= _MAX_CHILD_SECONDS:
        raise ValueError("supervisor_child_duration_invalid")
    if (
        not math.isfinite(stop)
        or not math.isfinite(deadline)
        or not now < stop
        or deadline - stop < _MIN_CLEANUP_RESERVE_SECONDS
        or deadline - now > _MAX_TOTAL_SECONDS
    ):
        raise ValueError("supervisor_deadline_invalid")
    return child, stop, deadline


def _deadline_receipt(
    result: object,
    *,
    deadline_monotonic: float,
    observed_times: dict[str, object],
) -> dict[str, object]:
    payload = _result_payload(result)
    deadline_requested = result.reason in {
        "outer_deadline_exceeded",
        "outer_worker_deadline_exceeded",
        "outer_clock_unavailable",
    }
    payload.update(
        {
            "schema": _SCHEMA,
            "state": "unknown",
            "reason": (
                "absolute_deadline_termination_requested"
                if deadline_requested
                else "supervisor_outcome_unverified"
            ),
            "supervisor_state": result.state,
            "supervisor_reason": result.reason,
            "supervisor_pid": os.getpid(),
            "deadline_monotonic": float(deadline_monotonic),
            "launcher_exit_code": result.evidence.launcher_exit_code,
            "process_creation_call_started_monotonic": observed_times.get(
                "process_creation_call_started_monotonic"
            ),
            "process_creation_call_returned_monotonic": observed_times.get(
                "process_creation_call_returned_monotonic"
            ),
            "launcher_resume_call_started_monotonic": observed_times.get(
                "launcher_resume_call_started_monotonic"
            ),
            "launcher_resume_call_returned_monotonic": observed_times.get(
                "launcher_resume_call_returned_monotonic"
            ),
            "job_termination_call_started_monotonic": observed_times.get(
                "job_termination_call_started_monotonic"
            ),
            "job_termination_call_returned_monotonic": observed_times.get(
                "job_termination_call_returned_monotonic"
            ),
            "launcher_exit_observed_monotonic": observed_times.get(
                "launcher_exit_observed_monotonic"
            ),
            "job_empty_observed_monotonic": observed_times.get("job_empty_observed_monotonic"),
            "controls_released_monotonic": observed_times.get("controls_released_monotonic"),
        }
    )
    return payload


def _supervise_fixed_command(
    command: FixedOuterCommand,
    *,
    receipt_root: str,
    deadline_monotonic: float,
    stop_deadline_monotonic: Optional[float] = None,
    backend: Optional[object] = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Run one fixed inert command under a separate process's outer Job.

    ``command`` and ``backend`` are internal seams used by process tests.  The
    CLI below never accepts a caller-provided command or executable.  Worker
    execution must stop at least ``_MIN_CLEANUP_RESERVE_SECONDS`` before the
    total deadline so Job cleanup and the value-free receipt have time to run.
    """

    if os.name != "nt":
        raise RuntimeError("windows_required")
    if not callable(monotonic) or not math.isfinite(float(deadline_monotonic)):
        raise ValueError("supervisor_deadline_invalid")
    now = float(monotonic())
    total_deadline = float(deadline_monotonic)
    effective_stop_deadline = (
        total_deadline
        if stop_deadline_monotonic is None
        else float(stop_deadline_monotonic)
    )
    if (
        not math.isfinite(now)
        or not math.isfinite(effective_stop_deadline)
        or not now < effective_stop_deadline
        or total_deadline - effective_stop_deadline < _MIN_CLEANUP_RESERVE_SECONDS
    ):
        raise ValueError("supervisor_cleanup_reserve_invalid")
    receipt_directory = Path(receipt_root)
    _validate_receipt_root(receipt_directory)
    receipt_path = receipt_directory / _RECEIPT_NAME
    if os.path.lexists(receipt_path):
        raise ValueError("supervisor_receipt_already_exists")

    observed_times: dict[str, object] = {}
    timed_backend = _TimedBackend(
        backend if backend is not None else WindowsJobBackend(),
        times=observed_times,
        monotonic=monotonic,
    )
    result = run_outer_watchdog(
        command,
        backend=timed_backend,
        stop_deadline_monotonic=(
            effective_stop_deadline
            if stop_deadline_monotonic is None
            else float(stop_deadline_monotonic)
        ),
        deadline_monotonic=total_deadline,
        monotonic=monotonic,
    )
    try:
        observed_times["supervisor_receipt_write_started_monotonic"] = float(monotonic())
    except BaseException:
        observed_times["supervisor_receipt_write_started_monotonic"] = None
    payload = _deadline_receipt(
        result,
        deadline_monotonic=float(deadline_monotonic),
        observed_times=observed_times,
    )
    payload["supervisor_receipt_write_started_monotonic"] = observed_times[
        "supervisor_receipt_write_started_monotonic"
    ]
    _write_receipt(
        receipt_path,
        payload,
    )
    return 2


def run_inert_deadline_supervisor(
    *,
    child_seconds: float,
    stop_deadline_monotonic: float,
    deadline_monotonic: float,
    receipt_root: str,
    stage: str = "complete",
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Supervise the fixed sleep guardian from this independent process."""

    child_seconds, stop_deadline, deadline = _validate_deadlines(
        child_seconds=child_seconds,
        stop_deadline_monotonic=stop_deadline_monotonic,
        deadline_monotonic=deadline_monotonic,
        now=float(monotonic()),
    )
    if type(stage) is not str or stage not in _PARENT_STAGES:
        raise ValueError("supervisor_stage_invalid")
    parent_script = Path(__file__).with_name("ctp_i13_i15_inert_parent.py")
    command = FixedOuterCommand(
        [
            os.path.abspath(sys.executable),
            "-I",
            "-S",
            "-B",
            str(parent_script),
            "--inert-only",
            "--stage",
            stage,
            "--child-seconds",
            repr(child_seconds),
            "--stop-deadline-monotonic",
            repr(stop_deadline),
            "--deadline-monotonic",
            repr(deadline),
            "--receipt-root",
            str(Path(receipt_root)),
            "--supervisor-pid",
            str(os.getpid()),
        ],
        str(parent_script.parent),
        _system_environment(),
    )
    return _supervise_fixed_command(
        command,
        receipt_root=receipt_root,
        deadline_monotonic=deadline,
        stop_deadline_monotonic=stop_deadline,
        monotonic=monotonic,
    )


def _arguments(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--inert-only",
        action="store_true",
        help="required acknowledgement that the child is only a bounded sleep",
    )
    parser.add_argument("--child-seconds", type=float, required=True)
    parser.add_argument("--stop-deadline-monotonic", type=float, required=True)
    parser.add_argument("--deadline-monotonic", type=float, required=True)
    parser.add_argument("--receipt-root", required=True)
    parser.add_argument("--stage", choices=_PARENT_STAGES, default="complete")
    args = parser.parse_args(argv)
    if not args.inert_only:
        parser.error("--inert-only is required")
    if not os.path.isabs(args.receipt_root):
        parser.error("--receipt-root must be an absolute directory path")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _arguments(argv)
    try:
        return run_inert_deadline_supervisor(
            child_seconds=args.child_seconds,
            stop_deadline_monotonic=args.stop_deadline_monotonic,
            deadline_monotonic=args.deadline_monotonic,
            receipt_root=args.receipt_root,
            stage=args.stage,
        )
    except BaseException as error:
        reason = getattr(error, "reason", None)
        if type(reason) is not str or not reason.isascii() or not reason.isidentifier():
            reason = "inert_supervisor_failed"
        sys.stderr.write(reason + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_inert_deadline_supervisor"]
