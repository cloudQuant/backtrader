"""Explicit local Gateway identity preparation; no trading authorization."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

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
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        _write_marker_windows(directory, strategy_uuid)
        return
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
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        _trust_dir_windows(state.paths.state_dir, owner_only=False)
        _write_marker_at(state.paths.state_dir, state.strategy_uuid)
        return
    directory = _setup_directory(state)
    try:
        _write_marker_at(directory, state.strategy_uuid)
    finally:
        os.close(directory)


def _verify_new_identity_marker_windows(state):
    """Windows parity of the marker verification (no-follow + owner + TOCTOU)."""
    from bt_api_py._win32_security import (
        Win32SecurityUnavailable,
        read_bounded_windows,
    )
    path = Path(state.paths.state_dir) / _SETUP_MARKER
    try:
        data = read_bounded_windows(path, 512, protected=True)
    except (Win32SecurityUnavailable, OSError):
        raise RuntimeError("STATE_SETUP_MARKER_INVALID") from None
    try:
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
    except (ValueError, TypeError, KeyError, UnicodeDecodeError):
        raise RuntimeError("STATE_SETUP_MARKER_INVALID") from None


def _verify_new_identity_marker(state):
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        return _verify_new_identity_marker_windows(state)
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


_WIN_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_WIN_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_WIN_GENERIC_WRITE = 0x40000000
_WIN_SHARE_ALL = 0x00000007
_WIN_OPEN_EXISTING = 3
_WIN_ERROR_FILE_EXISTS = 80
_WIN_ERROR_ALREADY_EXISTS = 183


def _owner_only_security_attributes(*, inherit: bool = False):
    """Build a Win32 SECURITY_ATTRIBUTES granting GENERIC_ALL only to current user."""
    from bt_api_py._win32_security import Win32SecurityUnavailable

    try:
        import pywintypes
        import win32api
        import win32con
        import win32security
    except ImportError:
        raise Win32SecurityUnavailable("OWNER_UNAVAILABLE") from None

    try:
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
        )
        try:
            owner = win32security.GetTokenInformation(
                token, win32security.TokenUser
            )[0]
        finally:
            win32api.CloseHandle(token)
        sd = win32security.SECURITY_DESCRIPTOR()
        dacl = win32security.ACL()
        if inherit:
            flags = (
                win32security.OBJECT_INHERIT_ACE
                | win32security.CONTAINER_INHERIT_ACE
            )
            dacl.AddAccessAllowedAceEx(
                win32security.ACL_REVISION, flags, win32con.GENERIC_ALL, owner
            )
        else:
            dacl.AddAccessAllowedAce(
                win32security.ACL_REVISION, win32con.GENERIC_ALL, owner
            )
        sd.SetSecurityDescriptorDacl(1, dacl, 0)
        sd.SetSecurityDescriptorControl(
            win32security.SE_DACL_PROTECTED, win32security.SE_DACL_PROTECTED
        )
        sa = win32security.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR = sd
        return sa
    except pywintypes.error:
        raise Win32SecurityUnavailable("OWNER_UNAVAILABLE") from None


def _flush_dir_windows(path) -> bool:
    """Best-effort Windows directory flush via CreateFileW + FlushFileBuffers."""
    import ctypes
    import ctypes.wintypes as wintypes
    from bt_api_py._win32_security import Win32SecurityUnavailable, is_reparse_point

    try:
        if is_reparse_point(path):
            return False
    except (Win32SecurityUnavailable, OSError):
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel32.FlushFileBuffers.restype = wintypes.BOOL
    kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    invalid = ctypes.c_void_p(-1).value
    handle = kernel32.CreateFileW(
        os.fspath(path),
        _WIN_GENERIC_WRITE,
        _WIN_SHARE_ALL,
        None,
        _WIN_OPEN_EXISTING,
        _WIN_FILE_FLAG_BACKUP_SEMANTICS | _WIN_FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if not handle or handle == invalid:
        return False
    try:
        return bool(kernel32.FlushFileBuffers(handle))
    finally:
        kernel32.CloseHandle(handle)


def _mkdir_owner_only_windows(path) -> None:
    """Create a directory atomically with an owner-only protected DACL."""
    from bt_api_py._win32_security import Win32SecurityUnavailable

    try:
        import pywintypes
        import win32file
    except ImportError:
        raise Win32SecurityUnavailable("OWNER_UNAVAILABLE") from None

    sa = _owner_only_security_attributes(inherit=True)
    try:
        win32file.CreateDirectory(os.fspath(path), sa)
    except pywintypes.error as exc:
        if exc.winerror == _WIN_ERROR_ALREADY_EXISTS:
            raise FileExistsError(exc.strerror) from None
        raise OSError(exc.winerror, exc.strerror) from None


def _create_exclusive_owner_only_file_windows(path, *, data: bytes = b"") -> tuple:
    """Create a new file with CREATE_NEW and owner-only DACL, flush, return stamp."""
    from bt_api_py._win32_security import Win32SecurityUnavailable, handle_stamp

    try:
        import pywintypes
        import win32file
    except ImportError:
        raise Win32SecurityUnavailable("OWNER_UNAVAILABLE") from None

    sa = _owner_only_security_attributes(inherit=False)
    try:
        handle = win32file.CreateFile(
            os.fspath(path),
            win32file.GENERIC_WRITE,
            win32file.FILE_SHARE_READ | win32file.FILE_SHARE_DELETE,
            sa,
            win32file.CREATE_NEW,
            win32file.FILE_ATTRIBUTE_NORMAL | _WIN_FILE_FLAG_OPEN_REPARSE_POINT,
            None,
        )
    except pywintypes.error as exc:
        if exc.winerror in (_WIN_ERROR_FILE_EXISTS, _WIN_ERROR_ALREADY_EXISTS):
            raise FileExistsError(exc.strerror) from None
        raise OSError(exc.winerror, exc.strerror) from None

    try:
        if data:
            view = memoryview(data)
            while view:
                err, written = win32file.WriteFile(handle, bytes(view))
                if err != 0 or written <= 0:
                    raise RuntimeError("STATE_SETUP_MARKER_WRITE_FAILED")
                view = view[written:]
        win32file.FlushFileBuffers(handle)
        return handle_stamp(int(handle))
    except pywintypes.error as exc:
        raise OSError(exc.winerror, exc.strerror) from None
    finally:
        win32file.CloseHandle(handle)


def _trust_dir_windows(path, *, owner_only: bool) -> tuple[int, int]:
    """Validate a Windows directory (no reparse, real dir, owner/DACL) and return stamp."""
    from bt_api_py._win32_security import (
        Win32SecurityUnavailable,
        inspect_owner,
        is_reparse_point,
    )

    try:
        if is_reparse_point(path):
            raise RuntimeError("STATE_SETUP_DIRECTORY_UNTRUSTED")
        st = os.stat(path, follow_symlinks=False)
        if not stat.S_ISDIR(st.st_mode):
            raise RuntimeError("STATE_SETUP_DIRECTORY_UNTRUSTED")
        owner = inspect_owner(path, others_may_write_check=owner_only)
        if not owner.is_current_user or (owner_only and owner.others_writable):
            raise RuntimeError("STATE_SETUP_DIRECTORY_UNTRUSTED")
        return (st.st_dev, st.st_ino)
    except (Win32SecurityUnavailable, OSError):
        raise RuntimeError("STATE_SETUP_DIRECTORY_UNTRUSTED") from None


def _check_bound_dir_windows(path, expected_stamp: tuple[int, int], *, owner_only: bool) -> None:
    """Refuse a swapped or untrusted Windows directory."""
    from bt_api_py._win32_security import Win32SecurityUnavailable, is_reparse_point

    try:
        if is_reparse_point(path):
            raise RuntimeError("STATE_SETUP_DIRECTORY_CHANGED")
        st = os.stat(path, follow_symlinks=False)
    except (Win32SecurityUnavailable, OSError):
        raise RuntimeError("STATE_SETUP_DIRECTORY_CHANGED") from None
    if not stat.S_ISDIR(st.st_mode) or (st.st_dev, st.st_ino) != expected_stamp:
        raise RuntimeError("STATE_SETUP_DIRECTORY_CHANGED")
    _trust_dir_windows(path, owner_only=owner_only)


def _check_reservation_windows(path, expected_stamp: tuple) -> None:
    """Refuse a deleted, replaced, reparse, non-empty, linked, or untrusted reservation."""
    from bt_api_py._win32_security import (
        Win32SecurityUnavailable,
        handle_stamp,
        inspect_owner,
        is_reparse_point,
        open_nofollow,
    )

    try:
        if is_reparse_point(path):
            raise RuntimeError("STATE_SETUP_RESERVATION_CHANGED")
        fd, handle = open_nofollow(path, share_delete=True)
        try:
            current = handle_stamp(handle)
        finally:
            os.close(fd)
        if (not stat.S_ISREG(current[2]) or current[4] != 1 or current[5] != 0
                or current != expected_stamp):
            raise RuntimeError("STATE_SETUP_RESERVATION_CHANGED")
        owner = inspect_owner(path, others_may_write_check=True)
        if not owner.is_current_user or owner.others_writable:
            raise RuntimeError("STATE_SETUP_RESERVATION_CHANGED")
    except (Win32SecurityUnavailable, OSError):
        raise RuntimeError("STATE_SETUP_RESERVATION_CHANGED") from None


def _write_marker_windows(state_dir, strategy_uuid) -> None:
    """Create the owner-only setup marker exclusively on Windows and flush it."""
    from bt_api_py._win32_security import Win32SecurityUnavailable, is_reparse_point

    marker = os.path.join(state_dir, _SETUP_MARKER)
    data = json.dumps(
        {"version": 1, "strategy_uuid": strategy_uuid},
        sort_keys=True, separators=(",", ":"),
    ).encode("ascii")
    try:
        _create_exclusive_owner_only_file_windows(marker, data=data)
        if is_reparse_point(marker):
            raise RuntimeError("STATE_SETUP_MARKER_INVALID")
    except (Win32SecurityUnavailable, OSError):
        raise RuntimeError("STATE_SETUP_MARKER_INVALID") from None
    _flush_dir_windows(state_dir)


def _prepare_gateway_state_windows(paths):
    """Windows parity of the POSIX fd-walk initializer.

    Windows has no ``dir_fd``/``O_NOFOLLOW``.  The same safety contract is
    enforced with Win32 security descriptors at creation time and the SDK's
    hardened primitives: no reparse point on the strategy/state directories or
    reservation/marker files, current-user ownership with an owner-only DACL
    from birth on state/reservations/marker, empty-state precondition, TOCTOU
    identity stamp re-checks across every phase, two exclusive reservation
    files that survive failure, and explicit ``verify_gateway_preparation``
    before returning.  All failures are finite; no path or identity is exposed.
    """
    from bt_api_py._win32_security import Win32SecurityUnavailable

    strategy_dir = paths.strategy_dir
    state_dir = paths.state_dir
    strategy_stamp = _trust_dir_windows(strategy_dir, owner_only=False)
    root_reserve = os.path.join(strategy_dir, _ROOT_RESERVATION)
    state_reserve = os.path.join(state_dir, _RESERVATION)

    # Refuse a reparse/untrusted/nonempty state directory before creating any reservation.
    if os.path.lexists(state_dir):
        _trust_dir_windows(state_dir, owner_only=True)
        try:
            if os.listdir(state_dir):
                raise RuntimeError("STATE_SETUP_NOT_EMPTY")
        except OSError:
            raise RuntimeError("STATE_SETUP_DIRECTORY_UNTRUSTED") from None

    # Root reservation: exclusive empty owner-only file, survives failure.
    try:
        root_reserve_stamp = _create_exclusive_owner_only_file_windows(root_reserve)
    except FileExistsError:
        raise RuntimeError("STATE_SETUP_ALREADY_ATTEMPTED") from None
    except (Win32SecurityUnavailable, OSError):
        raise RuntimeError("STATE_SETUP_RESERVATION_CHANGED") from None
    _flush_dir_windows(strategy_dir)

    def check_root():
        _check_bound_dir_windows(strategy_dir, strategy_stamp, owner_only=False)
        _check_reservation_windows(root_reserve, root_reserve_stamp)

    check_root()

    # Create the state directory atomically with an owner-only DACL (no window).
    try:
        _mkdir_owner_only_windows(state_dir)
        _flush_dir_windows(strategy_dir)
    except FileExistsError:
        pass
    except Win32SecurityUnavailable:
        raise RuntimeError("STATE_SETUP_DIRECTORY_UNTRUSTED") from None

    state_stamp = _trust_dir_windows(state_dir, owner_only=True)

    def check_binding():
        check_root()
        _check_bound_dir_windows(state_dir, state_stamp, owner_only=True)

    check_binding()
    try:
        if os.listdir(state_dir):
            raise RuntimeError("STATE_SETUP_NOT_EMPTY")
    except OSError:
        raise RuntimeError("STATE_SETUP_DIRECTORY_UNTRUSTED") from None

    # State reservation: exclusive empty owner-only file, survives failure.
    try:
        state_reserve_stamp = _create_exclusive_owner_only_file_windows(state_reserve)
    except FileExistsError:
        raise RuntimeError("STATE_SETUP_ALREADY_ATTEMPTED") from None
    except (Win32SecurityUnavailable, OSError):
        raise RuntimeError("STATE_SETUP_RESERVATION_CHANGED") from None
    _flush_dir_windows(state_dir)

    def check_reservation():
        _check_reservation_windows(state_reserve, state_reserve_stamp)

    check_binding()
    check_reservation()
    try:
        entries = set(os.listdir(state_dir))
    except OSError:
        raise RuntimeError("STATE_SETUP_DIRECTORY_UNTRUSTED") from None
    if entries != {_RESERVATION}:
        raise RuntimeError("STATE_SETUP_NOT_EMPTY")

    state = StrategyStateDir.initialize(strategy_dir)
    check_binding()
    check_reservation()
    _write_marker_at(state_dir, state.strategy_uuid)
    check_binding()
    check_reservation()
    verify_gateway_preparation(state)
    check_binding()
    check_reservation()
    return state


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
        return _prepare_gateway_state_windows(paths)
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
