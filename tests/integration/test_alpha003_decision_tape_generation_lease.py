"""Local-process checks for the opt-in 028 tape generation lease.

All tape bytes and process activity in this file are synthetic and confined to
pytest temporary directories.  The tests exercise the real DecisionTapeWriter
and OS lock implementation, without provider, account, Journal, or live-runner
calls.
"""

from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import signal
import threading
import time

import pytest

from tests.integration import test_alpha003_decision_tape_capacity as capacity


_RUNNER = capacity._RUNNER
_LOCK_SUFFIX = _RUNNER._DECISION_TAPE_GENERATION_LEASE_SUFFIX


def _writer(
    path: Path,
    *,
    generation_lease: bool = True,
    calendar_id: str = "synthetic-generation-calendar",
):
    return _RUNNER.DecisionTapeWriter(
        path,
        2 * 1024 * 1024,
        mode="live",
        factor_mode="native",
        direction=1,
        targets=("i", "rb"),
        calendar_id=calendar_id,
        grid_sha256="a" * 64,
        source_snapshot_id="synthetic-generation-source",
        cross_process_generation_lease=generation_lease,
    )


def _identity(path: Path):
    metadata = path.stat()
    return int(metadata.st_dev), int(metadata.st_ino)


def _recv(connection, timeout: float = 15.0):
    if not connection.poll(timeout):
        raise AssertionError("child process did not report within the test deadline")
    return connection.recv()


def _spawn(target, *args):
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=True)
    process = context.Process(target=target, args=(child, *args))
    process.start()
    child.close()
    return process, parent


def _finish(process, connection, command: str = "stop"):
    for _ in range(2):
        if not process.is_alive():
            break
        try:
            connection.send(command)
        except (BrokenPipeError, EOFError, OSError):
            break
        process.join(0.5)
    process.join(15)
    if process.is_alive():
        process.terminate()
        process.join(5)
    connection.close()
    if not process.is_alive():
        process.close()


def _leased_writer_owner(connection, tape_path: str):
    try:
        writer = _writer(Path(tape_path))
    except BaseException as error:
        connection.send(("error", getattr(error, "code", type(error).__name__)))
        connection.close()
        return
    lease = writer._generation_lease
    connection.send(
        (
            "ready",
            os.get_inheritable(lease._file.fileno()),
            os.get_inheritable(writer._handle.fileno()),
            lease._identity,
        )
    )
    command = connection.recv()
    if command == "crash":
        connection.send(("crashing",))
        os._exit(37)
    try:
        writer.close()
    except BaseException as error:
        connection.send(("close_error", getattr(error, "code", type(error).__name__)))
    else:
        connection.send(("closed", writer._handle.closed, lease.held))
    connection.close()


def _idle_child(connection):
    connection.send(("ready", os.getpid()))
    while connection.recv() != "stop":
        pass
    connection.send(("stopped",))
    connection.close()


def _fork_child_probe(connection, writer):
    connection.send(
        (
            "ready",
            writer._handle.closed,
            writer._generation_lease.held,
            writer._closed,
        )
    )
    while connection.recv() != "stop":
        pass
    connection.send(("stopped",))
    connection.close()


def _deferred_lease_probe(connection, tape_path: str):
    connection.send(("ready", os.getpid()))
    while True:
        command = connection.recv()
        if command == "stop":
            connection.send(("stopped",))
            connection.close()
            return
        if command != "attempt":
            connection.send(("error", "unknown_command"))
            continue
        lease = _RUNNER._DecisionTapeGenerationLease(Path(tape_path))
        try:
            lease.acquire()
        except _RUNNER.RunnerError as error:
            connection.send(("blocked", error.code))
            continue
        connection.send(("acquired", os.get_inheritable(lease._file.fileno())))
        release_command = connection.recv()
        try:
            lease.release()
        except _RUNNER.RunnerError as error:
            connection.send(("release_error", error.code))
            return
        connection.send(("released", release_command))


@pytest.mark.integration
def test_live_owner_rejects_second_process_after_elapsed_wait_interval(tmp_path):
    """A live owner has no TTL takeover; its lock file remains the same object."""
    tape_path = tmp_path / "live-owner.jsonl"
    owner, owner_connection = _spawn(_leased_writer_owner, str(tape_path))
    try:
        ready = _recv(owner_connection)
        assert ready[0] == "ready", ready
        assert ready[1:3] == (False, False)
        lock_path = Path(str(tape_path) + _LOCK_SUFFIX)
        lock_identity = _identity(lock_path)
        tape_before = tape_path.read_bytes()

        # The implementation has no expiry timestamp or takeover path.  Keep
        # the real owner alive across an elapsed interval, then use another
        # process to verify that the kernel lock still rejects acquisition.
        nominal_expiry_interval = 1.0  # There is no production TTL or stale-owner takeover.
        time.sleep(nominal_expiry_interval + 0.1)
        contender, contender_connection = _spawn(_deferred_lease_probe, str(tape_path))
        try:
            assert _recv(contender_connection)[0] == "ready"
            contender_connection.send("attempt")
            assert _recv(contender_connection) == (
                "blocked",
                "DECISION_TAPE_GENERATION_LEASE_BUSY",
            )
            assert owner.is_alive()
            assert tape_path.read_bytes() == tape_before
            assert _identity(lock_path) == lock_identity
        finally:
            _finish(contender, contender_connection)

        owner_connection.send("close")
        assert _recv(owner_connection) == ("closed", True, False)
        owner.join(15)
        assert owner.exitcode == 0
        assert lock_path.exists()
        assert _identity(lock_path) == lock_identity
    finally:
        _finish(owner, owner_connection, "close")


@pytest.mark.integration
def test_spawned_child_does_not_keep_parent_generation_lock_open(tmp_path):
    """A spawned child remains alive after the parent's non-inheritable lease closes."""
    tape_path = tmp_path / "spawn-inheritance.jsonl"
    writer = _writer(tape_path)
    child, connection = _spawn(_idle_child)
    try:
        child_ready = _recv(connection)
        assert child_ready[0] == "ready"
        writer.close()
        assert child.is_alive()

        reacquired = _RUNNER._DecisionTapeGenerationLease(tape_path).acquire()
        assert reacquired.held
        reacquired.release()
        assert child.is_alive()
    finally:
        if not writer._closed:
            writer.close()
        connection.send("stop")
        assert _recv(connection) == ("stopped",)
        child.join(15)
        assert child.exitcode == 0
        connection.close()
        child.close()


@pytest.mark.integration
@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "fork"),
    reason="POSIX fork descriptor inheritance check",
)
def test_posix_fork_child_closes_inherited_tape_and_lease_handles(tmp_path):
    tape_path = tmp_path / "fork-inheritance.jsonl"
    writer = _writer(tape_path)
    context = multiprocessing.get_context("fork")
    parent, child_connection = context.Pipe(duplex=True)
    child = context.Process(target=_fork_child_probe, args=(child_connection, writer))
    child.start()
    child_connection.close()
    try:
        assert _recv(parent) == ("ready", True, False, True)
        assert child.is_alive()

        writer.close()
        reacquired = _RUNNER._DecisionTapeGenerationLease(tape_path).acquire()
        assert reacquired.held
        reacquired.release()
        assert child.is_alive()

        parent.send("stop")
        assert _recv(parent) == ("stopped",)
        child.join(15)
        assert child.exitcode == 0
    finally:
        if not writer._closed:
            writer.close()
        _finish(child, parent)


@pytest.mark.integration
def test_normal_owner_close_releases_os_lock_but_never_reopens_old_tape(tmp_path):
    tape_path = tmp_path / "normal-close.jsonl"
    owner, connection = _spawn(_leased_writer_owner, str(tape_path))
    try:
        ready = _recv(connection)
        assert ready[0] == "ready", ready
        lock_path = Path(str(tape_path) + _LOCK_SUFFIX)
        lock_identity = _identity(lock_path)
        tape_before = tape_path.read_bytes()

        connection.send("close")
        assert _recv(connection) == ("closed", True, False)
        owner.join(15)
        assert owner.exitcode == 0

        lease = _RUNNER._DecisionTapeGenerationLease(tape_path).acquire()
        assert lease.held
        assert lease._identity == lock_identity
        lease.release()
        assert lock_path.exists()
        assert _identity(lock_path) == lock_identity

        with pytest.raises(_RUNNER.RunnerError) as rejected:
            _writer(tape_path)
        assert rejected.value.code == "DECISION_TAPE_CREATE_FAILED"
        assert tape_path.read_bytes() == tape_before
    finally:
        _finish(owner, connection, "close")


@pytest.mark.integration
def test_abnormal_owner_exit_releases_kernel_lock_without_tape_recovery(tmp_path):
    tape_path = tmp_path / "abnormal-close.jsonl"
    owner, connection = _spawn(_leased_writer_owner, str(tape_path))
    try:
        ready = _recv(connection)
        assert ready[0] == "ready", ready
        lock_path = Path(str(tape_path) + _LOCK_SUFFIX)
        lock_identity = _identity(lock_path)
        tape_before = tape_path.read_bytes()

        connection.send("crash")
        assert _recv(connection) == ("crashing",)
        owner.join(15)
        assert owner.exitcode == 37

        lease = _RUNNER._DecisionTapeGenerationLease(tape_path).acquire()
        assert lease.held
        assert lease._identity == lock_identity
        lease.release()
        assert lock_path.exists()
        assert _identity(lock_path) == lock_identity

        with pytest.raises(_RUNNER.RunnerError) as rejected:
            _writer(tape_path)
        assert rejected.value.code == "DECISION_TAPE_CREATE_FAILED"
        assert tape_path.read_bytes() == tape_before
    finally:
        _finish(owner, connection, "close")


@pytest.mark.integration
def test_close_waits_for_inflight_fsync_and_releases_only_after_data_close(tmp_path, monkeypatch):
    tape_path = tmp_path / "close-order.jsonl"
    writer = _writer(tape_path)
    lease = writer._generation_lease
    lock_path = Path(str(tape_path) + _LOCK_SUFFIX)
    lock_identity = _identity(lock_path)
    probe, connection = _spawn(_deferred_lease_probe, str(tape_path))
    assert _recv(connection)[0] == "ready"

    fsync_entered = threading.Event()
    release_fsync = threading.Event()
    release_observations = []
    thread_errors = []
    original_fsync = _RUNNER.os.fsync
    original_release = lease.release
    data_fd = writer._handle.fileno()
    held_once = threading.Event()

    def blocked_fsync(fd):
        if fd == data_fd and not held_once.is_set():
            held_once.set()
            fsync_entered.set()
            if not release_fsync.wait(10):
                raise AssertionError("test did not release the fsync barrier")
        return original_fsync(fd)

    def checked_release():
        release_observations.append(writer._handle.closed)
        return original_release()

    monkeypatch.setattr(_RUNNER.os, "fsync", blocked_fsync)
    lease.release = checked_release

    def run_thread(function):
        try:
            function()
        except BaseException as error:
            thread_errors.append(error)

    append_thread = threading.Thread(
        target=run_thread,
        args=(lambda: writer._append(b'{"type":"SYNTHETIC"}\n', count_record=True),),
    )
    close_thread = threading.Thread(target=run_thread, args=(writer.close,))
    try:
        append_thread.start()
        assert fsync_entered.wait(10)
        close_thread.start()
        time.sleep(0.1)
        assert close_thread.is_alive()

        connection.send("attempt")
        assert _recv(connection) == (
            "blocked",
            "DECISION_TAPE_GENERATION_LEASE_BUSY",
        )
        assert writer._handle.closed is False

        release_fsync.set()
        append_thread.join(10)
        close_thread.join(10)
        assert not append_thread.is_alive()
        assert not close_thread.is_alive()
        assert thread_errors == []
        assert writer._handle.closed
        assert writer._closed
        assert release_observations == [True]
        assert lease.held is False
        assert _identity(lock_path) == lock_identity

        connection.send("attempt")
        acquired = _recv(connection)
        assert acquired == ("acquired", False)
        connection.send("release")
        assert _recv(connection) == ("released", "release")
    finally:
        release_fsync.set()
        append_thread.join(10)
        if close_thread.ident is not None:
            close_thread.join(10)
        if not writer._closed:
            writer.close()
        _finish(probe, connection)


@pytest.mark.integration
def test_header_serialization_failure_precedes_tape_and_lease_allocation(tmp_path, monkeypatch):
    tape_path = tmp_path / "header-serialization-failure.jsonl"
    lock_path = Path(str(tape_path) + _LOCK_SUFFIX)
    before_owners = set(_RUNNER._DECISION_TAPE_GENERATION_LOCAL_OWNERS)
    acquire_calls = []
    data_open_calls = []
    original_acquire = _RUNNER._DecisionTapeGenerationLease.acquire
    original_open = Path.open

    def observe_acquire(lease):
        acquire_calls.append(lease)
        return original_acquire(lease)

    def observe_data_open(path, *args, **kwargs):
        if path.resolve(strict=False) == tape_path.resolve(strict=False):
            data_open_calls.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(_RUNNER._DecisionTapeGenerationLease, "acquire", observe_acquire)
    monkeypatch.setattr(Path, "open", observe_data_open)

    with pytest.raises(_RUNNER.RunnerError) as rejected:
        _writer(tape_path, calendar_id=object())

    assert rejected.value.code == "DECISION_TAPE_VALUE_INVALID"
    assert acquire_calls == []
    assert data_open_calls == []
    assert not tape_path.exists()
    assert not lock_path.exists()
    assert set(_RUNNER._DECISION_TAPE_GENERATION_LOCAL_OWNERS) == before_owners


@pytest.mark.integration
@pytest.mark.parametrize("failure_point", ["write", "fsync"])
def test_header_io_failure_closes_data_handle_and_releases_under_fork_lock(
    tmp_path, monkeypatch, failure_point
):
    tape_path = tmp_path / f"header-{failure_point}-failure.jsonl"
    lock_path = Path(str(tape_path) + _LOCK_SUFFIX)
    before_owners = set(_RUNNER._DECISION_TAPE_GENERATION_LOCAL_OWNERS)
    opened_handles = []
    release_observations = []
    original_open = Path.open
    original_fsync = _RUNNER.os.fsync
    original_release = _RUNNER._DecisionTapeGenerationLease.release
    tape_fd = []
    failure_observed = False

    class FailFirstWrite:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self._failed = False

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        def __enter__(self):
            self._wrapped.__enter__()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return self._wrapped.__exit__(exc_type, exc_value, traceback)

        def write(self, raw):
            nonlocal failure_observed
            if not self._failed:
                self._failed = True
                failure_observed = True
                raise OSError("synthetic header write failure")
            return self._wrapped.write(raw)

    def observe_data_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        if path.resolve(strict=False) == tape_path.resolve(strict=False):
            tape_fd.append(handle.fileno())
            if failure_point == "write":
                handle = FailFirstWrite(handle)
            opened_handles.append(handle)
        return handle

    def fail_data_fsync_once(fd):
        nonlocal failure_observed
        if failure_point == "fsync" and tape_fd and fd == tape_fd[0] and not failure_observed:
            failure_observed = True
            raise OSError("synthetic header fsync failure")
        return original_fsync(fd)

    def observe_release(lease):
        if lease._tape_handle is not None:
            release_observations.append(
                (_RUNNER._DECISION_TAPE_GENERATION_FORK_LOCK._is_owned(), lease._tape_handle.closed)
            )
        return original_release(lease)

    monkeypatch.setattr(Path, "open", observe_data_open)
    monkeypatch.setattr(_RUNNER.os, "fsync", fail_data_fsync_once)
    monkeypatch.setattr(_RUNNER._DecisionTapeGenerationLease, "release", observe_release)

    with pytest.raises(_RUNNER.RunnerError) as rejected:
        _writer(tape_path)

    assert rejected.value.code == "DECISION_TAPE_WRITE_FAILED"
    assert failure_observed
    assert len(opened_handles) == 1
    assert opened_handles[0].closed
    assert release_observations == [(True, True)]
    assert set(_RUNNER._DECISION_TAPE_GENERATION_LOCAL_OWNERS) == before_owners
    assert tape_path.read_bytes() == b""
    assert lock_path.exists()

    reacquired = _RUNNER._DecisionTapeGenerationLease(tape_path).acquire()
    assert reacquired.held
    reacquired.release()


@pytest.mark.integration
@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "fork"),
    reason="POSIX concurrent fork/constructor cleanup regression",
)
def test_posix_fork_waits_for_failed_header_cleanup_before_forking(tmp_path, monkeypatch):
    tape_path = tmp_path / "header-cleanup-fork.jsonl"
    close_entered = threading.Event()
    allow_parent_close = threading.Event()
    fork_attempting = threading.Event()
    fork_returned = threading.Event()
    opened_handles = []
    errors = []
    forked_pid = []
    original_open = Path.open
    original_fsync = _RUNNER.os.fsync
    tape_fd = []
    failed_once = False
    owner_pid = os.getpid()

    class BufferedCloseBarrier:
        """Model a buffered file's internal lock while close is in flight."""

        def __init__(self, wrapped):
            self._wrapped = wrapped
            self._buffer_close_lock = threading.Lock()

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        def close(self):
            if os.getpid() == owner_pid:
                self._buffer_close_lock.acquire()
                try:
                    close_entered.set()
                    if not allow_parent_close.wait(10):
                        raise AssertionError("test did not release the header cleanup barrier")
                    self._wrapped.close()
                finally:
                    self._buffer_close_lock.release()
                return

            # If a broken implementation forks during the parent's close,
            # this lock is inherited as owned by a vanished thread, matching
            # the BufferedWriter deadlock condition without hanging the suite.
            self._buffer_close_lock.acquire()
            try:
                self._wrapped.close()
            finally:
                self._buffer_close_lock.release()

    def observe_data_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        if path.resolve(strict=False) == tape_path.resolve(strict=False):
            wrapped = BufferedCloseBarrier(handle)
            opened_handles.append(wrapped)
            tape_fd.append(handle.fileno())
            return wrapped
        return handle

    def fail_data_fsync_once(fd):
        nonlocal failed_once
        if tape_fd and fd == tape_fd[0] and not failed_once:
            failed_once = True
            raise OSError("synthetic header fsync failure")
        return original_fsync(fd)

    monkeypatch.setattr(Path, "open", observe_data_open)
    monkeypatch.setattr(_RUNNER.os, "fsync", fail_data_fsync_once)

    def construct_writer():
        try:
            _writer(tape_path)
        except BaseException as error:
            errors.append(error)

    def fork_probe():
        fork_attempting.set()
        child_pid = os.fork()
        if child_pid == 0:
            os._exit(0)
        forked_pid.append(child_pid)
        fork_returned.set()

    constructor_thread = threading.Thread(target=construct_writer)
    fork_thread = threading.Thread(target=fork_probe)
    constructor_thread.start()
    child_status = None
    try:
        assert close_entered.wait(10)
        fork_thread.start()
        assert fork_attempting.wait(10)
        assert not fork_returned.wait(0.2)

        allow_parent_close.set()
        constructor_thread.join(10)
        fork_thread.join(10)
        assert not constructor_thread.is_alive()
        assert not fork_thread.is_alive()
        assert failed_once
        assert len(errors) == 1
        assert isinstance(errors[0], _RUNNER.RunnerError)
        assert errors[0].code == "DECISION_TAPE_WRITE_FAILED"
        assert len(opened_handles) == 1
        assert opened_handles[0].closed
        assert fork_returned.is_set()

        _, child_status = os.waitpid(forked_pid[0], 0)
        assert os.WIFEXITED(child_status)
        assert os.WEXITSTATUS(child_status) == 0
    finally:
        allow_parent_close.set()
        constructor_thread.join(10)
        if fork_thread.ident is not None:
            fork_thread.join(10)
        if forked_pid and child_status is None:
            try:
                os.kill(forked_pid[0], signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(forked_pid[0], 0)
            except ChildProcessError:
                pass


@pytest.mark.integration
def test_path_replacement_is_denied_or_detected_before_tape_append(tmp_path):
    tape_path = tmp_path / "path-identity.jsonl"
    writer = _writer(tape_path)
    lease = writer._generation_lease
    lock_path = Path(str(tape_path) + _LOCK_SUFFIX)
    original_tape = tape_path.read_bytes()
    lock_identity = _identity(lock_path)

    moved_lock = tmp_path / "moved-generation.lock"
    try:
        try:
            os.replace(lock_path, moved_lock)
        except OSError as error:
            # Win32 opens the lease handle without FILE_SHARE_DELETE, so the
            # OS itself refuses a cooperative rename while it is held.
            assert os.name == "nt"
            assert getattr(error, "winerror", None) in {5, 32, 33}
            assert _identity(lock_path) == lock_identity
            writer._append(b'{"type":"AFTER_DENIED_REPLACE"}\n', count_record=True)
        else:
            replacement_lock = lock_path
            replacement_lock.write_bytes(b"replacement lock object")
            with pytest.raises(_RUNNER.RunnerError) as rejected:
                writer._append(b'{"type":"AFTER_REPLACED_LOCK"}\n', count_record=True)
            assert rejected.value.code == "DECISION_TAPE_GENERATION_LEASE_IDENTITY_MISMATCH"
            assert tape_path.read_bytes() == original_tape
            replacement_lock.unlink()
            os.replace(moved_lock, lock_path)
            with pytest.raises(_RUNNER.RunnerError) as failed_close:
                writer.close()
            assert failed_close.value.code == "DECISION_TAPE_CLOSE_FAILED"
            assert tape_path.read_bytes() == original_tape
            return
    finally:
        if moved_lock.exists():
            if lock_path.exists():
                lock_path.unlink()
            os.replace(moved_lock, lock_path)
        if not writer._closed:
            writer.close()
    assert lease.held is False


@pytest.mark.integration
def test_tape_path_replacement_is_denied_or_detected_before_append(tmp_path):
    tape_path = tmp_path / "tape-path-identity.jsonl"
    writer = _writer(tape_path)
    original_tape = tape_path.read_bytes()
    displaced = tmp_path / "displaced-original.jsonl"
    replacement = b"synthetic replacement path\n"
    try:
        try:
            os.replace(tape_path, displaced)
        except OSError as error:
            # A filesystem may deny rename while the data handle is open.
            assert os.name == "nt"
            assert getattr(error, "winerror", None) in {5, 32, 33}
            assert tape_path.read_bytes() == original_tape
            writer._append(b'{"type":"AFTER_DENIED_TAPE_REPLACE"}\n', count_record=True)
            writer.close()
            return

        tape_path.write_bytes(replacement)
        with pytest.raises(_RUNNER.RunnerError) as rejected:
            writer._append(b'{"type":"AFTER_REPLACED_TAPE"}\n', count_record=True)
        assert rejected.value.code == "DECISION_TAPE_GENERATION_TAPE_IDENTITY_MISMATCH"
        assert tape_path.read_bytes() == replacement
        tape_path.unlink()
        os.replace(displaced, tape_path)
        with pytest.raises(_RUNNER.RunnerError) as failed_close:
            writer.close()
        assert failed_close.value.code == "DECISION_TAPE_CLOSE_FAILED"
        assert tape_path.read_bytes() == original_tape
    finally:
        if displaced.exists():
            if tape_path.exists():
                tape_path.unlink()
            os.replace(displaced, tape_path)
        if not writer._closed:
            writer.close()


def test_unsupported_filesystem_type_fails_closed_before_writer_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(_RUNNER, "_linux_local_filesystem_type", lambda _path: "nfs")
    with pytest.raises(_RUNNER.RunnerError) as rejected:
        _RUNNER._require_local_generation_lease_filesystem(tmp_path, platform_name="posix")
    assert rejected.value.code == "DECISION_TAPE_GENERATION_LEASE_FILESYSTEM_UNSUPPORTED"


def test_default_writer_keeps_legacy_no_sidecar_behavior(tmp_path):
    tape_path = tmp_path / "default-writer.jsonl"
    writer = _writer(tape_path, generation_lease=False)
    try:
        assert writer._generation_lease is None
        writer._append(b'{"type":"LEGACY_DEFAULT"}\n', count_record=True)
        assert writer.close()["closed"] is True
        assert not Path(str(tape_path) + _LOCK_SUFFIX).exists()
    finally:
        if not writer._closed:
            writer.close()
