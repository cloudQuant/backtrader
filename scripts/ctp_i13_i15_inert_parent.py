"""Fixed, inert parent/setup/worker/close chain for supervisor process tests.

This helper is not registered with the runtime and accepts no command, SDK,
provider, account, configuration, or marker path.  Its only child is a bounded
Python sleep worker.  The finite ``--stage`` choices are deterministic fault
injections used to verify the outer process Job.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Optional, Sequence


_MAX_CHILD_SECONDS = 300.0
_WORKER_SOURCE = (
    "import json, os, sys, time; "
    "from pathlib import Path; "
    "Path(sys.argv[1]).write_text(json.dumps({'pid': os.getpid()}), encoding='ascii'); "
    "time.sleep(float(sys.argv[2]))"
)
_STAGES = ("complete", "setup-block", "worker-block", "close-block", "receipt-fail")


def _write_exclusive(path: Path, payload: object) -> None:
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


def _arguments(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--inert-only", action="store_true", required=True)
    parser.add_argument("--child-seconds", type=float, required=True)
    parser.add_argument("--stop-deadline-monotonic", type=float, required=True)
    parser.add_argument("--deadline-monotonic", type=float, required=True)
    parser.add_argument("--receipt-root", required=True)
    parser.add_argument("--supervisor-pid", type=int, required=True)
    parser.add_argument("--stage", choices=_STAGES, default="complete")
    args = parser.parse_args(argv)
    if not math.isfinite(args.child_seconds) or not 0.0 < args.child_seconds <= _MAX_CHILD_SECONDS:
        parser.error("--child-seconds is outside the inert worker bound")
    if (
        not math.isfinite(args.stop_deadline_monotonic)
        or not math.isfinite(args.deadline_monotonic)
        or args.stop_deadline_monotonic <= 0.0
        or args.stop_deadline_monotonic > args.deadline_monotonic
    ):
        parser.error("the absolute deadline is invalid")
    if not os.path.isabs(args.receipt_root) or args.supervisor_pid <= 0:
        parser.error("the fixed inert process binding is invalid")
    return args


def _write_stage(path: Path, *, stage: str, supervisor_pid: int, worker_pid: object = None) -> None:
    _write_exclusive(
        path,
        {
            "schema": "ctp_i13_i15_inert_parent_stage.v1",
            "stage": stage,
            "parent_pid": os.getpid(),
            "supervisor_pid": supervisor_pid,
            "worker_pid": worker_pid,
            "observed_monotonic": time.monotonic(),
        },
    )


def run_inert_parent(
    *,
    child_seconds: float,
    stop_deadline_monotonic: float,
    deadline_monotonic: float,
    receipt_root: str,
    supervisor_pid: int,
    stage: str = "complete",
) -> int:
    """Execute the fixed inert phases; the external Job owns this whole tree."""

    if os.name != "nt":
        raise RuntimeError("windows_required")
    if type(stage) is not str or stage not in _STAGES:
        raise ValueError("inert_parent_stage_invalid")
    if (
        type(child_seconds) not in (int, float)
        or not math.isfinite(float(child_seconds))
        or not 0.0 < float(child_seconds) <= _MAX_CHILD_SECONDS
    ):
        raise ValueError("inert_parent_child_duration_invalid")
    if (
        type(stop_deadline_monotonic) not in (int, float)
        or type(deadline_monotonic) not in (int, float)
        or not math.isfinite(float(stop_deadline_monotonic))
        or not math.isfinite(float(deadline_monotonic))
        or not 0.0 < float(stop_deadline_monotonic) <= float(deadline_monotonic)
    ):
        raise ValueError("inert_parent_deadline_invalid")
    if type(supervisor_pid) is not int or supervisor_pid <= 0:
        raise ValueError("inert_parent_supervisor_pid_invalid")

    root = Path(receipt_root)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("inert_parent_receipt_root_invalid")

    setup_path = root / "inert-parent-setup.json"
    worker_path = root / "inert-parent-worker.json"
    close_path = root / "inert-parent-close.json"
    worker_pid_path = root / "inert-parent-worker-pid.json"
    receipt_path = root / "inert-parent-receipt.json"
    _write_stage(setup_path, stage="setup", supervisor_pid=supervisor_pid)
    if stage == "setup-block":
        time.sleep(_MAX_CHILD_SECONDS)
        return 2

    if stage == "worker-block":
        worker_seconds = _MAX_CHILD_SECONDS
    elif stage == "close-block":
        worker_seconds = min(float(child_seconds), 0.2)
    else:
        worker_seconds = float(child_seconds)
    worker_code = _WORKER_SOURCE
    worker_command = [
        os.path.abspath(sys.executable),
        "-I",
        "-S",
        "-B",
        "-c",
        worker_code,
        str(worker_pid_path),
        repr(worker_seconds),
    ]
    worker = subprocess.Popen(
        worker_command,
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={
            "PATH": os.path.dirname(os.path.abspath(sys.executable)),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
            "WINDIR": os.environ.get("WINDIR", os.environ.get("SYSTEMROOT", r"C:\Windows")),
        },
    )
    _write_exclusive(
        worker_path,
        {
            "schema": "ctp_i13_i15_inert_parent_stage.v1",
            "stage": "worker",
            "parent_pid": os.getpid(),
            "supervisor_pid": supervisor_pid,
            "worker_launcher_pid": worker.pid,
            "observed_monotonic": time.monotonic(),
        },
    )
    if stage == "worker-block":
        worker.wait()
        return 2

    worker.wait()
    worker_pid = None
    try:
        worker_pid = json.loads(worker_pid_path.read_text(encoding="ascii"))["pid"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    _write_stage(
        close_path,
        stage="close",
        supervisor_pid=supervisor_pid,
        worker_pid=worker_pid,
    )
    if stage == "close-block":
        time.sleep(_MAX_CHILD_SECONDS)
        return 2

    if stage == "receipt-fail":
        # This is an intentional collision with a pre-existing test sentinel.
        # O_EXCL must preserve that file and make this process fail closed.
        time.sleep(0.5)
        _write_exclusive(receipt_path, {"schema": "inert-parent-receipt.v1", "state": "done"})

    _write_exclusive(
        receipt_path,
        {
            "schema": "ctp_i13_i15_inert_parent_receipt.v1",
            "state": "completed",
            "parent_pid": os.getpid(),
            "worker_pid": worker_pid,
            "supervisor_pid": supervisor_pid,
            "stop_deadline_monotonic": float(stop_deadline_monotonic),
            "deadline_monotonic": float(deadline_monotonic),
        },
    )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _arguments(argv)
    try:
        return run_inert_parent(
            child_seconds=args.child_seconds,
            stop_deadline_monotonic=args.stop_deadline_monotonic,
            deadline_monotonic=args.deadline_monotonic,
            receipt_root=args.receipt_root,
            supervisor_pid=args.supervisor_pid,
            stage=args.stage,
        )
    except BaseException:
        sys.stderr.write("inert_parent_failed\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "run_inert_parent"]
