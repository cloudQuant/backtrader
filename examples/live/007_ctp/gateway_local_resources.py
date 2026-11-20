"""Local, explicitly initialized Gateway resources for the 007 examples.

This loader performs no account operations, service connection or admission.
It uses local state identity and separately protected CURVE key files.
"""
from __future__ import annotations

import os
import stat
import struct
from pathlib import Path

from backtrader.live_state.gateway_initialization import (
    _verify_new_identity_marker as _verify_new_identity_marker,
    _write_new_identity_marker as _write_new_identity_marker,
    prepare_gateway_state,
    verify_gateway_preparation,
)


class ResourceSetupRequired(RuntimeError):
    """A finite result requiring the operator to finish an explicit setup step."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


_WIN_PRIVILEGED_SIDS = frozenset({
    "S-1-5-18",      # SYSTEM
    "S-1-5-32-544",  # Administrators
})
_WIN_ACCESS_ALLOWED = 0x0
_WIN_ACCESS_DENIED = 0x1
# Read, write, execute, delete, and ACL-modification bits forbidden for
# non-owner, non-privileged principals on private key files (POSIX 0o077 parity).
_WIN_PRIVATE_OTHER_BITS = (
    0x10000000  # GENERIC_ALL
    | 0x80000000  # GENERIC_READ
    | 0x40000000  # GENERIC_WRITE
    | 0x20000000  # GENERIC_EXECUTE
    | 0x0001  # FILE_READ_DATA
    | 0x0002  # FILE_WRITE_DATA
    | 0x0004  # FILE_APPEND_DATA
    | 0x0008  # FILE_READ_EA
    | 0x0020  # FILE_EXECUTE
    | 0x0040  # FILE_DELETE_CHILD
    | 0x00010000  # DELETE
    | 0x00040000  # WRITE_DAC
    | 0x00080000  # WRITE_OWNER
)


def _decode_z85_key(value: bytes) -> bytes:
    """Validate one Z85-encoded 32-byte CURVE key uniformly across platforms."""
    value = value.removesuffix(b"\n").removesuffix(b"\r")
    try:
        from zmq.utils import z85
    except ImportError:
        raise RuntimeError("KEY_PLATFORM_UNSUPPORTED") from None
    try:
        if len(value) != 40 or len(z85.decode(value)) != 32:
            raise RuntimeError("KEY_FORMAT_INVALID")
    except (ValueError, TypeError, KeyError, struct.error):
        raise RuntimeError("KEY_FORMAT_INVALID") from None
    return value


def _assert_private_dacl_windows(path: Path) -> None:
    """Enforce POSIX 0o077 parity on Windows: no non-owner/non-privileged R/W/X."""
    from bt_api_py._win32_security import (
        WINDOWS,
        Win32SecurityUnavailable,
        current_user_sid,
        is_reparse_point,
    )

    if not WINDOWS:
        raise Win32SecurityUnavailable("FILE_UNAVAILABLE")
    try:
        import pywintypes
        import win32security
    except ImportError:
        raise Win32SecurityUnavailable("FILE_UNAVAILABLE") from None

    if is_reparse_point(path):
        raise RuntimeError("KEY_FILE_UNTRUSTED")
    try:
        sd = win32security.GetFileSecurity(
            str(path),
            win32security.OWNER_SECURITY_INFORMATION
            | win32security.DACL_SECURITY_INFORMATION,
        )
        owner = win32security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner())
        if owner != current_user_sid():
            raise RuntimeError("KEY_FILE_UNTRUSTED")
        dacl = sd.GetSecurityDescriptorDacl()
        if dacl is None:
            raise RuntimeError("KEY_FILE_UNTRUSTED")
        for i in range(dacl.GetAceCount()):
            ace = dacl.GetAce(i)
            ace_type = ace[0][0]
            mask = ace[1]
            sid_str = win32security.ConvertSidToStringSid(ace[2])
            if ace_type == _WIN_ACCESS_DENIED:
                continue
            if ace_type != _WIN_ACCESS_ALLOWED:
                raise RuntimeError("KEY_FILE_UNTRUSTED")
            if sid_str == owner or sid_str in _WIN_PRIVILEGED_SIDS:
                continue
            if mask & _WIN_PRIVATE_OTHER_BITS:
                raise RuntimeError("KEY_FILE_UNTRUSTED")
    except pywintypes.error:
        raise Win32SecurityUnavailable("FILE_UNAVAILABLE") from None


def _map_win32_key_error(exc) -> RuntimeError:
    code = getattr(exc, "code", "")
    if code in ("FILE_UNTRUSTED", "FILE_REPARSE", "FILE_REDIRECTED"):
        return RuntimeError("KEY_FILE_UNTRUSTED")
    if code == "FILE_CHANGED":
        return RuntimeError("KEY_FILE_CHANGED")
    return RuntimeError("KEY_FILE_UNAVAILABLE")


def _open_key_windows(path, *, private):
    """Windows parity via the SDK's hardened bounded reader and DACL grading.

    ``read_bounded_windows(protected=True)`` refuses reparse points on the
    whole chain, checks the canonical handle path, requires the current user
    to own the file with no others-writable ACE (POSIX 0o022 parity) and a
    single link, bounds the size to 64 bytes, and compares handle stamps
    before/after the read.  When ``private=True`` we additionally enforce POSIX
    0o077 parity (no read/write/execute ACE for any non-owner, non-privileged
    principal) before and after reading.  Any failure maps to a finite local
    error; no path or key material is exposed.
    """
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or not path.name:
        raise RuntimeError("KEY_PATH_INVALID")
    try:
        from bt_api_py._win32_security import (
            WINDOWS,
            Win32SecurityUnavailable,
            read_bounded_windows,
        )
    except ImportError:
        raise RuntimeError("KEY_PLATFORM_UNSUPPORTED") from None

    before_stamp = None
    try:
        if private:
            if not WINDOWS:
                raise Win32SecurityUnavailable("FILE_UNAVAILABLE")
            before_st = path.lstat()
            before_stamp = (
                before_st.st_dev, before_st.st_ino,
                before_st.st_mtime_ns, before_st.st_ctime_ns,
            )
            _assert_private_dacl_windows(path)
        value = read_bounded_windows(path, 64, protected=True)
        if private:
            after_st = path.lstat()
            after_stamp = (
                after_st.st_dev, after_st.st_ino,
                after_st.st_mtime_ns, after_st.st_ctime_ns,
            )
            if after_stamp != before_stamp:
                raise RuntimeError("KEY_FILE_CHANGED")
            _assert_private_dacl_windows(path)
    except Win32SecurityUnavailable as exc:
        raise _map_win32_key_error(exc) from None
    except OSError:
        raise RuntimeError("KEY_FILE_UNAVAILABLE") from None
    return _decode_z85_key(value)


def _open_key(path, *, private):
    """Read a bounded user-owned key without following symlinks or accepting swaps.

    POSIX uses the fd-walk below.  On Windows the equivalent guarantees are
    provided by ``bt_api_py._win32_security.read_bounded_windows`` (no-follow
    on every component, canonical handle path, no other-write DACL, link count
    1, bounded size and before/after TOCTOU identity checks) plus a private
    DACL check (POSIX 0o077 parity) when ``private=True``.  Both branches end
    with the same Z85 decode check; neither relaxes key validation.
    """
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        return _open_key_windows(path, private=private)
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or not path.name:
        raise RuntimeError("KEY_PATH_INVALID")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    file_flags = (os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
                  | getattr(os, "O_NONBLOCK", 0))
    opened = []
    directories = []
    uid = os.geteuid()
    try:
        parent = os.open("/", directory_flags)
        opened.append(parent)
        for part in path.parts[1:-1]:
            child = os.open(part, directory_flags, dir_fd=parent)
            opened.append(child)
            directories.append((parent, part, child))
            details = os.fstat(child)
            if not stat.S_ISDIR(details.st_mode) or details.st_uid not in (0, uid):
                raise RuntimeError("KEY_DIRECTORY_UNTRUSTED")
            if details.st_mode & 0o022 and not (
                details.st_uid == 0 and details.st_mode & stat.S_ISVTX
            ):
                raise RuntimeError("KEY_DIRECTORY_UNTRUSTED")
            parent = child
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != uid or before.st_nlink != 1
                or before.st_mode & (0o077 if private else 0o022) or before.st_size > 64):
            raise RuntimeError("KEY_FILE_UNTRUSTED")
        handle = os.open(path.name, file_flags, dir_fd=parent)
        opened.append(handle)
        current = os.fstat(handle)
        attrs = ("st_dev", "st_ino", "st_uid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (not stat.S_ISREG(current.st_mode) or current.st_uid != uid or current.st_nlink != 1
                or current.st_mode & (0o077 if private else 0o022)
                or any(getattr(before, key) != getattr(current, key) for key in attrs)):
            raise RuntimeError("KEY_FILE_UNTRUSTED")
        value = os.read(handle, 65)
        after = os.fstat(handle)
        visible = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (len(value) > 64 or any(getattr(current, key) != getattr(after, key) for key in attrs)
                or any(getattr(current, key) != getattr(visible, key) for key in attrs)):
            raise RuntimeError("KEY_FILE_CHANGED")
        for parent_fd, component, child_fd in directories:
            visible_dir = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
            opened_dir = os.fstat(child_fd)
            if any(getattr(visible_dir, key) != getattr(opened_dir, key)
                   for key in ("st_dev", "st_ino", "st_uid", "st_mode")):
                raise RuntimeError("KEY_DIRECTORY_CHANGED")
    except (OSError, ValueError, TypeError, KeyError):
        raise RuntimeError("KEY_FILE_UNAVAILABLE") from None
    finally:
        for handle in reversed(opened):
            os.close(handle)
    # ZMQ service_v2 decodes Z85 keys, so use one explicit portable format.
    return _decode_z85_key(value)


def validate_security_file_config(config, raw, strategy_dir):
    """Validate references only; do not open paths or inspect private files."""
    names = {item["security_profile_ref"] for item in config.client_config.communication["profiles"].values()}
    risk = getattr(config, "risk_selection", None)
    if risk is not None:
        # The Risk service has its own server key, under its own profile name.
        names.add(risk.security_profile_ref)
    execution = getattr(config, "execution_selection", None)
    if execution is not None:
        if execution.security_profile_ref in names:
            raise RuntimeError("SECURITY_PROFILES_INVALID")
        names.add(execution.security_profile_ref)
    if type(raw) is not dict or set(raw) != names:
        raise RuntimeError("SECURITY_PROFILES_INVALID")
    result = {}
    for name, item in raw.items():
        expected = {"server_public_key_file", "client_public_key_file", "client_secret_key_file"}
        if type(item) is not dict or set(item) != expected:
            raise RuntimeError("SECURITY_PROFILES_INVALID")
        paths = []
        for field in ("server_public_key_file", "client_public_key_file", "client_secret_key_file"):
            value = item[field]
            if type(value) is not str or not value or value != value.strip():
                raise RuntimeError("KEY_PATH_INVALID")
            key_path = Path(value).expanduser()
            if ".." in key_path.parts:
                raise RuntimeError("KEY_PATH_INVALID")
            if not key_path.is_absolute():
                key_path = strategy_dir / key_path
            paths.append(key_path)
        result[name] = paths
    if execution is not None:
        execution_paths = {os.path.abspath(path) for path in result[execution.security_profile_ref]}
        other_paths = {os.path.abspath(path) for name, paths in result.items()
                       if name != execution.security_profile_ref for path in paths}
        if len(execution_paths) != 3 or execution_paths & other_paths:
            raise RuntimeError("SECURITY_PROFILES_INVALID")
    return result


def _security_profiles(config, raw, strategy_dir):
    from bt_api_py.service_runtime import ClientCurveKeys
    import zmq

    result = {}
    for name, paths in validate_security_file_config(config, raw, strategy_dir).items():
        server = _open_key(paths[0], private=False)
        public = _open_key(paths[1], private=False)
        secret = _open_key(paths[2], private=True)
        if zmq.curve_public(secret) != public:
            raise RuntimeError("CURVE_KEY_PAIR_INVALID")
        result[name] = ClientCurveKeys(server, public, secret)
    return result


def load_local_resources(config, *, strategy_dir, first_init, upgrade_state, security_files):
    """Open existing strategy state and matching keys, or perform explicit setup."""
    strategy_dir = Path(strategy_dir)
    if first_init:
        if upgrade_state:
            raise RuntimeError("SETUP_OPTIONS_CONFLICT")
        prepare_gateway_state(strategy_dir)
        # Initialization generates UUID4. It must be registered at Gateway and
        # copied into the public route/binding before any session can be used.
        raise ResourceSetupRequired("LOCAL_STATE_INITIALIZED_CONFIGURE_IDENTITY")
    from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
    from backtrader.live_state.atomic import read_json
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from backtrader.live_state.pending import validate_pending_state
    from backtrader.live_state.state_dir import StrategyStateDir

    state = StrategyStateDir(strategy_dir)
    if state.strategy_uuid != config.binding.strategy_scope:
        raise RuntimeError("STRATEGY_IDENTITY_MISMATCH")
    host = GatewayPendingHost(strategy_dir, state.strategy_uuid, config.binding)
    if upgrade_state:
        lock = state.acquire_run_lock()
        try:
            path = state.pending.path
            pending = validate_pending_state(read_json(path), path, state.strategy_uuid)
            version = pending["version"]
            if version == 1:
                # A fresh local identity is not proof that the venue is flat.
                # Existing direct state may only migrate through the separately
                # authorized direct-to-Gateway reconciliation procedure.
                verify_gateway_preparation(state)
                sequence = state.sequence.read()
                if (state.identity.account_binding is not None or pending["active"] or pending["history"]
                        or sequence["local_seq"] != 0 or sequence["ref_high_water"] != 0
                        or state.waiting.active() or state.waiting.history()
                        or state.snapshot.read() is not None):
                    raise RuntimeError("DIRECT_STATE_MIGRATION_REQUIRED")
                host = GatewayPendingHost.upgrade_for_gateway(strategy_dir, state.strategy_uuid, config.binding)
                version = 2
            if version == 2:
                host = GatewayPendingHost.upgrade_for_cancellation(strategy_dir, state.strategy_uuid, config.binding)
                version = 3
            if version == 3:
                route, binding = config.route, config.binding
                consumer = gateway_execution_consumer_ref(
                    principal_ref=route.identity.principal_ref, actor_ref=route.identity.actor_ref,
                    execution_domain_ref=route.scope.execution_domain_ref,
                    account_scope=binding.account_scope, strategy_scope=binding.strategy_scope,
                )
                host = GatewayPendingHost.upgrade_for_execution(strategy_dir, state.strategy_uuid,
                                                                  binding, consumer_ref=consumer)
                version = 4
            if version == 4:
                host = GatewayPendingHost.upgrade_for_order_state(strategy_dir, state.strategy_uuid, config.binding)
                version = 5
            if version == 5:
                host.upgrade_for_local_notifications()
                version = 6
            if version not in (6, 7, 8) or (version == 8 and getattr(config, "execution_selection", None) is None):
                raise RuntimeError("GATEWAY_STATE_VERSION_UNSUPPORTED")
            host.load_execution_checkpoint()
            host.local_order_notifications()
        finally:
            lock.release()
        raise ResourceSetupRequired("LOCAL_STATE_UPGRADED")
    path = state.pending.path
    pending = validate_pending_state(read_json(path), path, state.strategy_uuid)
    if pending["version"] not in (6, 7, 8):
        raise RuntimeError("GATEWAY_STATE_UPGRADE_REQUIRED")
    if pending["version"] == 8 and getattr(config, "execution_selection", None) is None:
        raise RuntimeError("GATEWAY_STATE_EXECUTION_SELECTION_REQUIRED")
    host.load_execution_checkpoint()
    host.local_order_notifications()
    return host, _security_profiles(config, security_files, strategy_dir)
