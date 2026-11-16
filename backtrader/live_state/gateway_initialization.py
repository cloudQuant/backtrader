"""Explicit local Gateway identity preparation; no trading authorization."""
from __future__ import annotations

import json
import os
import stat

from ._common import StatePaths
from .state_dir import StrategyStateDir

__all__ = ("prepare_gateway_state", "verify_gateway_preparation")

_SETUP_MARKER = "gateway_example_init.json"


def _open_setup_directory(state_dir, *, dir_fd=None):
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        raise RuntimeError("STATE_SETUP_PLATFORM_UNSUPPORTED")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(state_dir, flags, dir_fd=dir_fd)
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        os.close(fd)
        raise RuntimeError("STATE_SETUP_DIRECTORY_UNTRUSTED")
    return fd


def _setup_directory(state):
    return _open_setup_directory(state.paths.state_dir)


def _write_marker_at(directory, strategy_uuid):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(_SETUP_MARKER, flags, 0o600, dir_fd=directory)
    try:
        data = json.dumps({"version": 1, "strategy_uuid": strategy_uuid},
                          sort_keys=True, separators=(",", ":")).encode("ascii")
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise RuntimeError("STATE_SETUP_MARKER_WRITE_FAILED")
            view = view[written:]
        os.fsync(fd)
        os.fsync(directory)
    finally:
        os.close(fd)


def _write_new_identity_marker(state):
    directory = _setup_directory(state)
    try:
        _write_marker_at(directory, state.strategy_uuid)
    finally:
        os.close(directory)


def _verify_new_identity_marker(state):
    directory = _setup_directory(state)
    fd = None
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
        before = os.stat(_SETUP_MARKER, dir_fd=directory, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_mode & 0o077 or before.st_nlink != 1 or before.st_size > 512):
            raise RuntimeError("STATE_SETUP_MARKER_INVALID")
        fd = os.open(_SETUP_MARKER, flags, dir_fd=directory)
        opened = os.fstat(fd)
        attrs = ("st_dev", "st_ino", "st_uid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, key) != getattr(opened, key) for key in attrs):
            raise RuntimeError("STATE_SETUP_MARKER_INVALID")
        data = os.read(fd, 513)
        after = os.fstat(fd)
        visible = os.stat(_SETUP_MARKER, dir_fd=directory, follow_symlinks=False)
        if (len(data) > 512 or any(getattr(opened, key) != getattr(after, key) for key in attrs)
                or any(getattr(opened, key) != getattr(visible, key) for key in attrs)):
            raise RuntimeError("STATE_SETUP_MARKER_INVALID")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result
        marker = json.loads(data, object_pairs_hook=unique)
        if (type(marker) is not dict or set(marker) != {"version", "strategy_uuid"}
                or type(marker["version"]) is not int or marker["version"] != 1
                or marker["strategy_uuid"] != state.strategy_uuid):
            raise RuntimeError("STATE_SETUP_MARKER_INVALID")
    except (OSError, ValueError, TypeError, KeyError, UnicodeDecodeError):
        raise RuntimeError("STATE_SETUP_MARKER_INVALID") from None
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)


_RESERVATION = "gateway_example_init.reserve"
_ROOT_RESERVATION = ".gateway_example_init.reserve"


def _check_bound_directory(path, directory):
    """Refuse a changed visible state directory before using path-based APIs."""
    opened = os.fstat(directory)
    visible = os.stat(path, follow_symlinks=False)
    attrs = ("st_dev", "st_ino", "st_uid", "st_mode")
    if any(getattr(opened, key) != getattr(visible, key) for key in attrs):
        raise RuntimeError("STATE_SETUP_DIRECTORY_CHANGED")


def prepare_gateway_state(strategy_dir):
    """Initialize once; any prior or interrupted state blocks another attempt.

    Persistent root and state reservations prevent retrying a partial
    initialization and are not proof of venue state or authorization. The
    marker is written only after StrategyStateDir.initialize has succeeded.
    """
    paths = StatePaths(strategy_dir)
    if not os.path.isdir(paths.strategy_dir):
        raise RuntimeError("STATE_SETUP_DIRECTORY_UNAVAILABLE")
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        raise RuntimeError("STATE_SETUP_PLATFORM_UNSUPPORTED")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    root = os.open(paths.strategy_dir, flags)
    try:
        _check_bound_directory(paths.strategy_dir, root)
        # Refuse existing nonempty state before creating any reservation.
        try:
            os.stat("state", dir_fd=root, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            existing = _open_setup_directory("state", dir_fd=root)
            try:
                _check_bound_directory(paths.state_dir, existing)
                if os.listdir(existing):
                    raise RuntimeError("STATE_SETUP_NOT_EMPTY")
            finally:
                os.close(existing)

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            root_reservation = os.open(_ROOT_RESERVATION, flags, 0o600, dir_fd=root)
        except FileExistsError:
            raise RuntimeError("STATE_SETUP_ALREADY_ATTEMPTED") from None
        try:
            os.fsync(root_reservation)
            os.fsync(root)

            def check_root():
                _check_bound_directory(paths.strategy_dir, root)
                opened = os.fstat(root_reservation)
                visible = os.stat(_ROOT_RESERVATION, dir_fd=root, follow_symlinks=False)
                attrs = ("st_dev", "st_ino", "st_uid", "st_mode", "st_nlink", "st_size")
                if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.geteuid()
                        or opened.st_mode & 0o077 or opened.st_nlink != 1 or opened.st_size != 0
                        or any(getattr(opened, key) != getattr(visible, key) for key in attrs)):
                    raise RuntimeError("STATE_SETUP_RESERVATION_CHANGED")

            check_root()
            try:
                os.mkdir("state", 0o700, dir_fd=root)
                os.fsync(root)
            except FileExistsError:
                pass
            directory = _open_setup_directory("state", dir_fd=root)
            try:
                def check_binding():
                    check_root()
                    _check_bound_directory(paths.state_dir, directory)
                    opened = os.fstat(directory)
                    visible = os.stat("state", dir_fd=root, follow_symlinks=False)
                    attrs = ("st_dev", "st_ino", "st_uid", "st_mode")
                    if any(getattr(opened, key) != getattr(visible, key) for key in attrs):
                        raise RuntimeError("STATE_SETUP_DIRECTORY_CHANGED")

                check_binding()
                if os.listdir(directory):
                    raise RuntimeError("STATE_SETUP_NOT_EMPTY")
                fd = os.open(_RESERVATION, flags, 0o600, dir_fd=directory)
                try:
                    os.fsync(fd)
                    os.fsync(directory)

                    def check_reservation():
                        opened = os.fstat(fd)
                        visible = os.stat(_RESERVATION, dir_fd=directory, follow_symlinks=False)
                        attrs = ("st_dev", "st_ino", "st_uid", "st_mode", "st_nlink", "st_size")
                        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.geteuid()
                                or opened.st_mode & 0o077 or opened.st_nlink != 1 or opened.st_size != 0
                                or any(getattr(opened, key) != getattr(visible, key) for key in attrs)):
                            raise RuntimeError("STATE_SETUP_RESERVATION_CHANGED")

                    check_binding()
                    check_reservation()
                    if set(os.listdir(directory)) != {_RESERVATION}:
                        raise RuntimeError("STATE_SETUP_NOT_EMPTY")
                    state = StrategyStateDir.initialize(paths.strategy_dir)
                    check_binding()
                    check_reservation()
                    _write_marker_at(directory, state.strategy_uuid)
                    check_binding()
                    check_reservation()
                    verify_gateway_preparation(state)
                    check_binding()
                    check_reservation()
                    return state
                finally:
                    os.close(fd)
            finally:
                os.close(directory)
        finally:
            os.close(root_reservation)
    finally:
        os.close(root)


def verify_gateway_preparation(state):
    """Verify the original 007 marker; this does not establish trading authority."""
    _verify_new_identity_marker(state)
