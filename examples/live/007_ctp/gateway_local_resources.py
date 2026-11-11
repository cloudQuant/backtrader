"""Local, explicitly initialized Gateway resources for the 007 examples.

This loader performs no account operations, service connection or admission.
It uses local state identity and separately protected CURVE key files.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path


class ResourceSetupRequired(RuntimeError):
    """A finite result requiring the operator to finish an explicit setup step."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


_SETUP_MARKER = "gateway_example_init.json"


def _setup_directory(state):
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        raise RuntimeError("STATE_SETUP_PLATFORM_UNSUPPORTED")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(state.paths.state_dir, flags)
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        os.close(fd)
        raise RuntimeError("STATE_SETUP_DIRECTORY_UNTRUSTED")
    return fd


def _write_new_identity_marker(state):
    directory = _setup_directory(state)
    fd = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(_SETUP_MARKER, flags, 0o600, dir_fd=directory)
        data = json.dumps({"version": 1, "strategy_uuid": state.strategy_uuid},
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
        if fd is not None:
            os.close(fd)
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


def _open_key(path, *, private):
    """Read a bounded user-owned key without following symlinks or accepting swaps."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
        raise RuntimeError("KEY_PLATFORM_UNSUPPORTED")
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
        # ZMQ service_v2 decodes Z85 keys, so use one explicit portable format.
        value = value.removesuffix(b"\n").removesuffix(b"\r")
        from zmq.utils import z85

        if len(value) != 40 or len(z85.decode(value)) != 32:
            raise RuntimeError("KEY_FORMAT_INVALID")
        return value
    except (OSError, ValueError, TypeError, KeyError):
        raise RuntimeError("KEY_FILE_UNAVAILABLE") from None
    finally:
        for handle in reversed(opened):
            os.close(handle)


def validate_security_file_config(config, raw, strategy_dir):
    """Validate references only; do not open paths or inspect private files."""
    names = {item["security_profile_ref"] for item in config.client_config.communication["profiles"].values()}
    risk = getattr(config, "risk_selection", None)
    if risk is not None:
        # The Risk service has its own server key, under its own profile name.
        names.add(risk.security_profile_ref)
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
    from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
    from backtrader.live_state.atomic import read_json
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from backtrader.live_state.pending import validate_pending_state
    from backtrader.live_state.state_dir import StrategyStateDir

    strategy_dir = Path(strategy_dir)
    if first_init:
        if upgrade_state:
            raise RuntimeError("SETUP_OPTIONS_CONFLICT")
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "geteuid"):
            raise RuntimeError("STATE_SETUP_PLATFORM_UNSUPPORTED")
        state = StrategyStateDir.initialize(strategy_dir)
        _write_new_identity_marker(state)
        # Initialization generates UUID4. It must be registered at Gateway and
        # copied into the public route/binding before any session can be used.
        raise ResourceSetupRequired("LOCAL_STATE_INITIALIZED_CONFIGURE_IDENTITY")
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
                _verify_new_identity_marker(state)
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
            if version != 6:
                raise RuntimeError("GATEWAY_STATE_VERSION_UNSUPPORTED")
            host.load_execution_checkpoint()
            host.local_order_notifications()
        finally:
            lock.release()
        raise ResourceSetupRequired("LOCAL_STATE_UPGRADED")
    path = state.pending.path
    pending = validate_pending_state(read_json(path), path, state.strategy_uuid)
    if pending["version"] != 6:
        raise RuntimeError("GATEWAY_STATE_UPGRADE_REQUIRED")
    host.load_execution_checkpoint()
    host.local_order_notifications()
    return host, _security_profiles(config, security_files, strategy_dir)
