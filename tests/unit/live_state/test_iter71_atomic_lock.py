"""Cross-platform FileLock verification (R72-BUG-10, real Windows + POSIX)."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from backtrader.live_state import atomic
from backtrader.live_state.atomic import FileLock, LiveStateError, LiveStateLocked


def test_file_lock_mutual_exclusion_and_release_reacquire(tmp_path):
    lock_path = tmp_path / "state.lock"
    first = FileLock(lock_path, timeout=0.05, poll_interval=0.01)
    second = FileLock(lock_path, timeout=0.05, poll_interval=0.01)

    assert first.try_acquire() is True
    assert first.held is True

    # Non-blocking contention fails immediately.
    t0 = time.monotonic()
    assert second.try_acquire() is False
    assert second.held is False
    assert (time.monotonic() - t0) < 0.5

    # Blocking acquire times out with LiveStateLocked.
    with pytest.raises(LiveStateLocked):
        second.acquire()
    assert second.held is False

    # Re-entry on the same held lock instance raises lock_reentry.
    with pytest.raises(LiveStateError) as exc_info:
        first.try_acquire()
    assert exc_info.value.code == "lock_reentry"

    # Releasing allows immediate re-acquisition by another FileLock instance.
    first.release()
    assert first.held is False
    assert second.try_acquire() is True
    assert second.held is True
    second.release()
    assert second.held is False


def test_file_lock_excludes_other_process_until_release(tmp_path):
    lock_path = tmp_path / "cross_proc.lock"
    holder = FileLock(lock_path, timeout=0.05, poll_interval=0.01)
    holder.acquire()
    probe_code = (
        "import sys; "
        "from backtrader.live_state.atomic import FileLock; "
        "lk = FileLock(sys.argv[1], timeout=0.05, poll_interval=0.01); "
        "acquired = lk.try_acquire(); "
        "lk.release() if acquired else None; "
        "sys.exit(0 if acquired else 3)"
    )
    try:
        contended = subprocess.run(
            [sys.executable, "-c", probe_code, str(lock_path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert contended.returncode == 3, contended.stderr
    finally:
        holder.release()

    after_release = subprocess.run(
        [sys.executable, "-c", probe_code, str(lock_path)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert after_release.returncode == 0, after_release.stderr


def test_platform_lock_facade_does_not_swallow_bad_fd_as_contention(tmp_path):
    # A closed / invalid fd is an OS error (EBADF), never lock contention.
    lock_path = tmp_path / "bad_fd.lock"
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    os.close(fd)
    with pytest.raises(OSError):
        atomic.try_lock_fd(fd)


def test_platform_lock_facade_propagates_non_contention_oserror(tmp_path, monkeypatch):
    import errno

    backend = atomic.get_platform_file_lock_backend()
    assert backend.name == ("msvcrt" if os.name == "nt" else "fcntl")

    lock_path = tmp_path / "io_err.lock"
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        def raise_eio(*_args, **_kwargs):
            raise OSError(errno.EIO, "synthetic I/O error")

        if os.name == "nt":
            monkeypatch.setattr(backend._msvcrt, "locking", raise_eio)
        else:
            monkeypatch.setattr(backend._fcntl, "flock", raise_eio)
        with pytest.raises(OSError, match="synthetic I/O error"):
            atomic.try_lock_fd(fd)
    finally:
        os.close(fd)
