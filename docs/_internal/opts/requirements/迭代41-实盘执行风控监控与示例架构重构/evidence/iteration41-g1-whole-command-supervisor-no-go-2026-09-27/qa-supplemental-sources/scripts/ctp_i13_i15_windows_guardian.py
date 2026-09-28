"""Unregistered, inert-only Windows guardian process candidate.

This executable accepts no strategy, config, SDK, or provider arguments. Its
sole purpose is to prove that a separate long-lived process can own the Job
and process handles for a deterministic sleeping child after its creator exits.
It is not a trusted launcher or a hard-deadline guarantee: the caller that
creates this guardian and native APIs inside it can still block.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Optional, Sequence

from scripts.ctp_i13_i15_outer_watchdog import FixedOuterCommand, run_outer_watchdog
from scripts.ctp_i13_i15_windows_job_backend import WindowsJobBackend


_SCHEMA = "ctp_i13_i15_inert_guardian_receipt.v1"
_MAX_CHILD_SECONDS = 300.0
_REPARSE_POINT = 0x400


def _validate_receipt_root(path: Path) -> None:
    if not path.is_absolute():
        raise ValueError("guardian_receipt_root_invalid")
    current = Path(path.anchor)
    for index, part in enumerate(path.parts[1:]):
        current = current / part
        try:
            details = os.lstat(current)
        except OSError:
            raise ValueError("guardian_receipt_root_invalid") from None
        if stat.S_ISLNK(details.st_mode) or bool(
            getattr(details, "st_file_attributes", 0) & _REPARSE_POINT
        ):
            raise ValueError("guardian_receipt_root_reparse_point")
        if index < len(path.parts[1:]) - 1 and not stat.S_ISDIR(details.st_mode):
            raise ValueError("guardian_receipt_root_invalid")
    if not path.is_dir():
        raise ValueError("guardian_receipt_root_invalid")


def _arguments(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--inert-only",
        action="store_true",
        help="required acknowledgement that this candidate only launches sleep",
    )
    parser.add_argument("--child-seconds", type=float, required=True)
    parser.add_argument("--stop-deadline-monotonic", type=float, required=True)
    parser.add_argument("--deadline-monotonic", type=float, required=True)
    parser.add_argument("--receipt-root", required=True)
    args = parser.parse_args(argv)
    if not args.inert_only:
        parser.error("--inert-only is required")
    if (
        not math.isfinite(args.child_seconds)
        or not 0.0 < args.child_seconds <= _MAX_CHILD_SECONDS
    ):
        parser.error("--child-seconds is outside the inert probe bound")
    if not math.isfinite(args.deadline_monotonic) or args.deadline_monotonic <= 0.0:
        parser.error("--deadline-monotonic is invalid")
    if (
        not math.isfinite(args.stop_deadline_monotonic)
        or args.stop_deadline_monotonic <= 0.0
        or args.stop_deadline_monotonic > args.deadline_monotonic
    ):
        parser.error("--stop-deadline-monotonic is invalid")
    if not os.path.isabs(args.receipt_root):
        parser.error("--receipt-root must be an absolute directory path")
    return args


def _system_environment() -> dict[str, str]:
    """Pass only the Windows variables needed to start a local Python child."""

    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return {
        "PATH": os.path.dirname(os.path.abspath(sys.executable)),
        "SYSTEMROOT": system_root,
        "WINDIR": os.environ.get("WINDIR", system_root),
    }


def _result_payload(result: object) -> dict[str, object]:
    evidence = result.evidence
    return {
        "schema": _SCHEMA,
        "state": result.state,
        "reason": result.reason,
        "process_created": evidence.process_created,
        "job_assignment_observed": evidence.job_assignment_observed,
        "launcher_resumed": evidence.launcher_resumed,
        "launcher_exit_observed": evidence.launcher_exit_observed,
        "job_termination_requested": evidence.job_termination_requested,
        "job_termination_call_succeeded": evidence.job_termination_call_succeeded,
        "job_empty_observed": evidence.job_empty_observed,
        "containment": evidence.containment,
        "controls_retained": evidence.controls_retained,
    }


def _write_receipt(path: Path, payload: dict[str, object]) -> None:
    """Create a new value-free receipt without replacing an existing file."""

    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def run_inert_guardian(
    *,
    child_seconds: float,
    stop_deadline_monotonic: float,
    deadline_monotonic: float,
    receipt_root: str,
) -> int:
    """Run the only permitted child shape and write its containment receipt."""

    if os.name != "nt":
        raise RuntimeError("windows_required")
    if (
        type(child_seconds) not in (int, float)
        or not math.isfinite(float(child_seconds))
        or not 0.0 < float(child_seconds) <= _MAX_CHILD_SECONDS
    ):
        raise ValueError("inert_child_duration_invalid")
    if (
        type(deadline_monotonic) not in (int, float)
        or not math.isfinite(float(deadline_monotonic))
        or float(deadline_monotonic) <= 0.0
    ):
        raise ValueError("guardian_deadline_invalid")
    if (
        type(stop_deadline_monotonic) not in (int, float)
        or not math.isfinite(float(stop_deadline_monotonic))
        or not 0.0 < float(stop_deadline_monotonic) <= float(deadline_monotonic)
    ):
        raise ValueError("guardian_stop_deadline_invalid")
    receipt_directory = Path(receipt_root)
    _validate_receipt_root(receipt_directory)
    receipt = receipt_directory / "guardian-receipt.json"
    if os.path.lexists(receipt):
        raise ValueError("guardian_receipt_already_exists")

    child_source = "import time; time.sleep({})".format(repr(float(child_seconds)))
    command = FixedOuterCommand(
        [os.path.abspath(sys.executable), "-I", "-S", "-B", "-c", child_source],
        os.path.dirname(os.path.abspath(__file__)),
        _system_environment(),
    )
    result = run_outer_watchdog(
        command,
        backend=WindowsJobBackend(),
        deadline_monotonic=float(deadline_monotonic),
        stop_deadline_monotonic=float(stop_deadline_monotonic),
    )
    _write_receipt(receipt, _result_payload(result))
    evidence = result.evidence
    if (
        result.state == "timed_out"
        and evidence.containment == "verified"
        and evidence.launcher_exit_observed is True
        and evidence.job_empty_observed is True
        and evidence.controls_retained is False
    ):
        return 0
    return 2


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _arguments(argv)
    try:
        return run_inert_guardian(
            child_seconds=args.child_seconds,
            stop_deadline_monotonic=args.stop_deadline_monotonic,
            deadline_monotonic=args.deadline_monotonic,
            receipt_root=args.receipt_root,
        )
    except BaseException as error:
        reason = getattr(error, "reason", None)
        if type(reason) is not str or not reason.isascii() or not reason.isidentifier():
            reason = "guardian_failed"
        sys.stderr.write(reason + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_inert_guardian"]
