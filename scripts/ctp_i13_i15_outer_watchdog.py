"""Offline outer-process watchdog contract for the I13/I15 launcher review.

This module contains no Windows API implementation and is not an operator
entry point.  A future backend must create the parent launcher suspended and
atomically inside one Windows Job before it can run, then provide bounded,
non-blocking observations for that process and its complete Job.  The tests
exercise only injected fakes; they do not establish Windows Job behavior.

The absolute monotonic deadline is supplied by the caller that owns the whole
command.  The caller must capture it before any launcher preparation and pass
the same value through all later layers.  This module never reads runtime
configuration or markers, imports a provider/SDK, captures child output, or
decides whether an I13/I15 diagnostic succeeded.
"""

import math
import os
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Protocol, Sequence, Tuple


MAX_POLL_INTERVAL_SECONDS = 0.25


def _valid_retention_token(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value.isascii()
        and all(character.isalnum() or character in "._-" for character in value)
    )


class OuterBackendCreationError(RuntimeError):
    """Creation failed; an optional token proves orphan controls are escrowed."""

    def __init__(self, reason: str, *, retention_token: Optional[str] = None) -> None:
        if type(reason) is not str or not reason.isascii() or not reason.isidentifier():
            raise ValueError("outer_backend_creation_reason_invalid")
        if retention_token is not None and not _valid_retention_token(retention_token):
            raise ValueError("outer_backend_retention_token_invalid")
        self.reason = reason
        self.retention_token = retention_token
        super().__init__(reason)


class OuterWatchdogBackend(Protocol):
    """Injected process backend; the production Windows adapter is not present."""

    def create_suspended_in_job(
        self, command: "FixedOuterCommand", *, deadline_monotonic: float
    ) -> "OuterJobSession":
        """Create the launcher suspended, atomically assigned to its Job.

        A production implementation must not resume the process here.  It must
        return owning process/Job controls and observed assignment evidence, or
        fail with evidence sufficient to prove that no child escaped.  Calls
        must themselves be bounded by the same deadline; Python cannot enforce
        that property for a backend blocked inside a native API.  If creation
        fails after native controls were acquired, raise
        :class:`OuterBackendCreationError`. Include a retention token only if a
        long-lived host custodian has taken ownership; otherwise clean up the
        controls or leave their custody explicitly unconfirmed.
        """

    def retain_controls(self, session: "OuterJobSession") -> Optional[str]:
        """Escrow unresolved process/Job controls and return a custody token.

        Return a non-empty opaque identifier only after a long-lived,
        host-owned custodian independent of this backend adapter's lifetime has
        taken strong ownership of the session and its native controls. The
        custodian must remain reachable after this call and the result object
        are discarded. The identifier must not contain a path or raw native
        handle. Return ``None`` or raise when custody cannot be confirmed. This
        operation must itself be bounded; the runner cannot keep native
        controls alive after returning on the backend's behalf.
        """


class OuterJobSession(Protocol):
    """Narrow fakeable handle contract for the launcher process tree."""

    process_created: bool
    job_assignment_observed: Optional[bool]

    def resume_launcher(self) -> bool:
        """Resume only after verified in-Job creation."""

    def poll_launcher_exit_code(self) -> Optional[int]:
        """Return an exit code, or ``None`` while the launcher is still active."""

    def poll_job_empty(self) -> Optional[bool]:
        """Return Job-empty evidence, or ``None`` when it cannot be observed."""

    def terminate_job(self) -> Optional[bool]:
        """Request whole-Job termination; return ``None`` when the result is unknown."""

    def terminate_launcher_process(self) -> Optional[bool]:
        """Stop a still-suspended launcher if atomic Job assignment was unobserved."""

    def release_controls(self) -> bool:
        """Release handles only after process-exit and Job-empty evidence."""


@dataclass(frozen=True)
class FixedOuterCommand:
    """Immutable argv/cwd/environment snapshot for one launcher invocation."""

    argv: Tuple[str, ...]
    cwd: str
    env: Mapping[str, str]

    def __init__(self, argv: Sequence[str], cwd: str, env: Mapping[str, str]) -> None:
        if type(argv) not in (tuple, list) or not argv:
            raise ValueError("outer_command_argv_invalid")
        copied_argv = tuple(argv)
        if any(type(value) is not str or not value or "\0" in value for value in copied_argv):
            raise ValueError("outer_command_argv_invalid")
        if type(cwd) is not str or not cwd or "\0" in cwd or not os.path.isabs(cwd):
            raise ValueError("outer_command_cwd_invalid")
        if not isinstance(env, Mapping):
            raise ValueError("outer_command_environment_invalid")
        copied_env = {}
        seen = set()
        for key, value in env.items():
            if (
                type(key) is not str
                or type(value) is not str
                or not key
                or "=" in key
                or "\0" in key
                or "\0" in value
            ):
                raise ValueError("outer_command_environment_invalid")
            folded = key.casefold()
            if folded in seen:
                raise ValueError("outer_command_environment_invalid")
            seen.add(folded)
            copied_env[key] = value
        object.__setattr__(self, "argv", copied_argv)
        object.__setattr__(self, "cwd", cwd)
        object.__setattr__(self, "env", MappingProxyType(copied_env))


@dataclass(frozen=True)
class OuterProcessEvidence:
    process_created: Optional[bool]
    job_assignment_observed: Optional[bool]
    launcher_resumed: Optional[bool]
    launcher_exit_observed: Optional[bool]
    launcher_exit_code: Optional[int]
    launcher_termination_requested: bool
    launcher_termination_call_succeeded: Optional[bool]
    job_termination_requested: bool
    job_termination_call_succeeded: Optional[bool]
    job_empty_observed: Optional[bool]
    containment: str
    controls_retained: Optional[bool]
    retention_token: Optional[str] = field(repr=False)


@dataclass(frozen=True)
class OuterWatchdogResult:
    """Containment facts only; this result never means diagnostic success."""

    state: str
    reason: str
    evidence: OuterProcessEvidence


def _valid_deadline(value: object) -> bool:
    return (
        type(value) in (int, float)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


def _valid_interval(value: object) -> bool:
    return (
        type(value) in (int, float)
        and math.isfinite(float(value))
        and 0.0 < float(value) <= MAX_POLL_INTERVAL_SECONDS
    )


def run_outer_watchdog(
    command: FixedOuterCommand,
    *,
    backend: OuterWatchdogBackend,
    deadline_monotonic: float,
    stop_deadline_monotonic: Optional[float] = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    abort_requested: Optional[Callable[[], Optional[str]]] = None,
    before_resume: Optional[Callable[[], Optional[str]]] = None,
    after_resume: Optional[Callable[[], Optional[str]]] = None,
    poll_interval_seconds: float = 0.05,
) -> OuterWatchdogResult:
    """Supervise a launcher tree against one caller-owned absolute deadline.

    All backend observations are required to be non-blocking.  The only wait
    in this function is an injected sleep capped by the remaining budget.  A
    ``deadline_monotonic`` is the hard end of this call, including cleanup.
    The optional ``stop_deadline_monotonic`` ends worker execution earlier and
    leaves bounded time to terminate the Job and observe it empty. ``after_resume``
    runs once after confirmed resume and before the first abort or process poll;
    any callback I/O must use the same absolute deadline. Deadline expiry remains
    a failure even when termination is fully confirmed.
    Unknown creation, assignment, exit, Job-empty, termination, clock, sleep,
    or handle-release evidence never yields ``state='exited'``. Interruptions
    after session creation trigger termination and escrow attempts; they do
    not escape as exceptions from the runner.
    """

    if type(command) is not FixedOuterCommand:
        raise ValueError("outer_command_required")
    if not _valid_deadline(deadline_monotonic):
        raise ValueError("outer_deadline_invalid")
    if stop_deadline_monotonic is not None and (
        not _valid_deadline(stop_deadline_monotonic)
        or float(stop_deadline_monotonic) > float(deadline_monotonic)
    ):
        raise ValueError("outer_stop_deadline_invalid")
    if not callable(getattr(backend, "create_suspended_in_job", None)):
        raise ValueError("outer_backend_invalid")
    if not callable(getattr(backend, "retain_controls", None)):
        raise ValueError("outer_backend_invalid")
    if not callable(monotonic) or not callable(sleep) or not _valid_interval(poll_interval_seconds):
        raise ValueError("outer_clock_invalid")
    if abort_requested is not None and not callable(abort_requested):
        raise ValueError("outer_abort_check_invalid")
    if before_resume is not None and not callable(before_resume):
        raise ValueError("outer_before_resume_check_invalid")
    if after_resume is not None and not callable(after_resume):
        raise ValueError("outer_after_resume_check_invalid")

    deadline = float(deadline_monotonic)
    stop_deadline = (
        deadline
        if stop_deadline_monotonic is None
        else float(stop_deadline_monotonic)
    )
    interval = float(poll_interval_seconds)
    session = None
    process_created: Optional[bool] = None
    assigned: Optional[bool] = None
    resumed: Optional[bool] = None
    exit_code: Optional[int] = None
    exit_observed: Optional[bool] = None
    terminate_requested = False
    terminate_succeeded: Optional[bool] = None
    launcher_terminate_requested = False
    launcher_terminate_succeeded: Optional[bool] = None
    job_empty: Optional[bool] = None
    controls_retained = False
    retention_token: Optional[str] = None
    clock_failed = False

    def result(state: str, reason: str, containment: str) -> OuterWatchdogResult:
        return OuterWatchdogResult(
            state=state,
            reason=reason,
            evidence=OuterProcessEvidence(
                process_created=process_created,
                job_assignment_observed=assigned,
                launcher_resumed=resumed,
                launcher_exit_observed=exit_observed,
                launcher_exit_code=exit_code,
                launcher_termination_requested=launcher_terminate_requested,
                launcher_termination_call_succeeded=launcher_terminate_succeeded,
                job_termination_requested=terminate_requested,
                job_termination_call_succeeded=terminate_succeeded,
                job_empty_observed=job_empty,
                containment=containment,
                controls_retained=controls_retained,
                retention_token=retention_token,
            ),
        )

    def now_expired() -> bool:
        nonlocal clock_failed
        try:
            return monotonic() >= deadline
        except BaseException:
            clock_failed = True
            return True

    def remaining_budget() -> float:
        nonlocal clock_failed
        try:
            return max(0.0, deadline - monotonic())
        except BaseException:
            clock_failed = True
            return 0.0

    def stop_deadline_expired() -> bool:
        nonlocal clock_failed
        try:
            return monotonic() >= stop_deadline
        except BaseException:
            clock_failed = True
            return True

    def deadline_reason() -> str:
        return "outer_clock_unavailable" if clock_failed else "outer_deadline_exceeded"

    def requested_abort_reason() -> Optional[str]:
        if abort_requested is None:
            return None
        try:
            requested = abort_requested()
        except BaseException:
            return "outer_abort_check_failed"
        if requested is None:
            return None
        if (
            type(requested) is str
            and requested.isascii()
            and requested.isidentifier()
        ):
            return requested
        return "outer_abort_reason_invalid"

    def transfer_controls_to_escrow() -> bool:
        """Ask the backend to take custody before this call drops ``session``."""

        nonlocal controls_retained, retention_token
        if session is None:
            controls_retained = None
            return False
        try:
            token = backend.retain_controls(session)
        except BaseException:
            token = None
        if _valid_retention_token(token):
            retention_token = token
            controls_retained = True
            return True
        # A local reference is not durable custody evidence.  None means the
        # backend did not positively confirm ownership transfer.
        controls_retained = None
        retention_token = None
        return False

    def cleanup(
        state: str, reason: str, *, force_escrow: bool = False
    ) -> OuterWatchdogResult:
        nonlocal terminate_requested, terminate_succeeded
        nonlocal launcher_terminate_requested, launcher_terminate_succeeded
        nonlocal exit_code, exit_observed, job_empty, controls_retained
        if session is None:
            controls_retained = None
            return result("unknown", "process_creation_state_unknown", "unknown")

        assigned_to_job = assigned is True
        if assigned_to_job:
            terminate_requested = True
            try:
                terminate_succeeded = session.terminate_job()
            except BaseException:
                terminate_succeeded = None
        else:
            # Assignment is unknown, so neither the launcher nor the Job can
            # be assumed to own the whole process tree. Terminate both: the
            # launcher is still suspended, and the Job may contain members
            # that the assignment observation failed to account for.
            terminate_requested = True
            try:
                terminate_succeeded = session.terminate_job()
            except BaseException:
                terminate_succeeded = None
            launcher_terminate_requested = True
            try:
                launcher_terminate_succeeded = session.terminate_launcher_process()
            except BaseException:
                launcher_terminate_succeeded = None

        # Cleanup observations are immediate by contract.  Retry only while
        # the original command deadline still has budget; never add a fresh
        # cleanup deadline that would silently extend the whole-command cap.
        while True:
            try:
                observed_exit_code = session.poll_launcher_exit_code()
                if observed_exit_code is not None:
                    if type(observed_exit_code) is not int:
                        observed_exit_code = None
                    else:
                        exit_code = observed_exit_code
                        exit_observed = True
                observed_empty = session.poll_job_empty()
                if type(observed_empty) is bool:
                    job_empty = observed_empty
            except BaseException:
                pass

            safely_drained = exit_observed is True and (
                (assigned_to_job and job_empty is True and terminate_succeeded is True)
                or (
                    not assigned_to_job
                    and resumed is False
                    and job_empty is True
                )
            )
            if safely_drained:
                try:
                    released = session.release_controls()
                except BaseException:
                    released = False
                if released is True:
                    controls_retained = False
                    if assigned_to_job:
                        if state == "exited" and now_expired():
                            return result("timed_out", deadline_reason(), "verified")
                        return result(state, reason, "verified")
                    return result("unknown", "job_assignment_unconfirmed", "unknown")
                transfer_controls_to_escrow()
                return result("unknown", "control_release_unconfirmed", "unknown")

            if force_escrow or now_expired():
                transfer_controls_to_escrow()
                return result(state, reason, "unknown")
            remaining = remaining_budget()
            if remaining <= 0.0:
                continue
            try:
                sleep(min(interval, remaining))
            except BaseException:
                transfer_controls_to_escrow()
                return result("unknown", "watchdog_wait_interrupted", "unknown")

    if now_expired():
        reason = "clock_unavailable_before_start" if clock_failed else "deadline_expired_before_start"
        return result("not_started", reason, "not_started")
    if stop_deadline_expired():
        reason = (
            "outer_clock_unavailable"
            if clock_failed
            else "outer_worker_deadline_expired_before_start"
        )
        return result("not_started", reason, "not_started")

    try:
        session = backend.create_suspended_in_job(
            command, deadline_monotonic=deadline
        )
    except OuterBackendCreationError as error:
        token = error.retention_token
        if _valid_retention_token(token):
            controls_retained = True
            retention_token = token
        else:
            controls_retained = None
        return result("unknown", error.reason, "unknown")
    except BaseException:
        controls_retained = None
        return result("unknown", "process_creation_state_unknown", "unknown")

    # The backend contract says returned launchers are still suspended. This
    # runner has not yet allowed any launcher code to execute.
    resumed = False
    try:
        process_created = session.process_created
        assigned = session.job_assignment_observed
    except BaseException:
        return cleanup("unknown", "job_assignment_unobserved")
    if type(process_created) is not bool or process_created is not True:
        return cleanup("unknown", "process_creation_unconfirmed")
    if assigned is not True:
        return cleanup("unknown", "job_assignment_unconfirmed")
    if now_expired():
        return cleanup("timed_out", deadline_reason())
    if stop_deadline_expired():
        reason = (
            deadline_reason()
            if clock_failed
            else "outer_worker_deadline_exceeded"
        )
        return cleanup("timed_out", reason)

    if before_resume is not None:
        try:
            pre_resume_reason = before_resume()
        except BaseException:
            return cleanup("unknown", "outer_before_resume_check_failed")
        if pre_resume_reason is not None:
            if (
                type(pre_resume_reason) is not str
                or not pre_resume_reason.isascii()
                or not pre_resume_reason.isidentifier()
            ):
                pre_resume_reason = "outer_before_resume_reason_invalid"
            return cleanup("unknown", pre_resume_reason)
        if now_expired():
            return cleanup("timed_out", deadline_reason())
        if stop_deadline_expired():
            reason = (
                deadline_reason()
                if clock_failed
                else "outer_worker_deadline_exceeded"
            )
            return cleanup("timed_out", reason)

    try:
        resumed = session.resume_launcher()
    except BaseException:
        resumed = None
    if resumed is not True:
        return cleanup("failed", "launcher_resume_unconfirmed")
    if now_expired():
        return cleanup("timed_out", deadline_reason())
    if stop_deadline_expired():
        reason = (
            deadline_reason()
            if clock_failed
            else "outer_worker_deadline_exceeded"
        )
        return cleanup("timed_out", reason)

    if after_resume is not None:
        try:
            post_resume_reason = after_resume()
        except BaseException:
            return cleanup("unknown", "outer_after_resume_check_failed")
        if post_resume_reason is not None:
            if (
                type(post_resume_reason) is not str
                or not post_resume_reason.isascii()
                or not post_resume_reason.isidentifier()
            ):
                post_resume_reason = "outer_after_resume_reason_invalid"
            return cleanup("unknown", post_resume_reason)
        if now_expired():
            return cleanup("timed_out", deadline_reason())
        if stop_deadline_expired():
            reason = (
                deadline_reason()
                if clock_failed
                else "outer_worker_deadline_exceeded"
            )
            return cleanup("timed_out", reason)

    while True:
        abort_reason = requested_abort_reason()
        if abort_reason is not None:
            return cleanup("unknown", abort_reason)
        if now_expired():
            return cleanup("timed_out", deadline_reason())
        if stop_deadline_expired():
            reason = (
                deadline_reason()
                if clock_failed
                else "outer_worker_deadline_exceeded"
            )
            return cleanup("timed_out", reason)
        try:
            observed_exit_code = session.poll_launcher_exit_code()
        except BaseException:
            return cleanup("unknown", "launcher_exit_unobserved")
        if observed_exit_code is not None:
            if type(observed_exit_code) is not int:
                return cleanup("unknown", "launcher_exit_unobserved")
            exit_code = observed_exit_code
            exit_observed = True
            if now_expired():
                return cleanup("timed_out", deadline_reason())
            try:
                job_empty = session.poll_job_empty()
            except BaseException:
                job_empty = None
            if now_expired():
                if job_empty is True:
                    try:
                        released = session.release_controls()
                    except BaseException:
                        released = False
                    if released is True:
                        controls_retained = False
                        return result("timed_out", deadline_reason(), "verified")
                    transfer_controls_to_escrow()
                    return result("unknown", "control_release_unconfirmed", "unknown")
                return cleanup("timed_out", deadline_reason())
            if job_empty is not True:
                return cleanup("failed", "descendant_or_job_state_unconfirmed")
            try:
                released = session.release_controls()
            except BaseException:
                released = False
            if released is not True:
                transfer_controls_to_escrow()
                return result("unknown", "control_release_unconfirmed", "unknown")
            if now_expired():
                return result("timed_out", deadline_reason(), "verified")
            return result("exited", "launcher_exited_job_empty", "verified")

        if now_expired():
            return cleanup("timed_out", deadline_reason())
        remaining = remaining_budget()
        if remaining <= 0.0:
            return cleanup("timed_out", deadline_reason())
        try:
            sleep(min(interval, remaining))
        except BaseException:
            return cleanup(
                "unknown", "watchdog_wait_interrupted", force_escrow=True
            )


__all__ = [
    "FixedOuterCommand",
    "OuterBackendCreationError",
    "OuterProcessEvidence",
    "OuterWatchdogResult",
    "run_outer_watchdog",
]
