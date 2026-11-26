"""Strict resources, cross-process identity gate, and private run receipt.

The loader reads only gateway/market_connection.json and the three exact key
files under gateway/keys. POSIX execution deliberately fails closed in this
round; the Windows branch uses the SDK's no-follow bounded reader and the
existing 007 owner-only DACL verifier.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backtrader.live_state.atomic import FileLock, atomic_write_bytes, fsync_directory


class MarketOnlyResourceError(RuntimeError):
    """Value-free local resource or identity-gate failure."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


_GENERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ENDPOINT_RE = re.compile(r"^tcp://127\.0\.0\.1:([0-9]{1,5})$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_CONNECTION_BYTES = 8192
_MAX_RECEIPT_BYTES = 65536
_FIXED_KEY_FILES = {
    "server_public_key": ("server.public", False),
    "client_public_key": ("client.public", False),
    "client_secret_key": ("client.secret", True),
}
_RETAINED_LEASES: list["GlobalMarketIdentityLease"] = []


@dataclass(frozen=True)
class LoadedMarketConnection:
    resource_root: Path
    generation_id: str
    connection: Any = field(repr=False)
    connection_json_sha256: str


def _local_resource_module():
    name = "_market_only_gateway_local_resources"
    module = sys.modules.get(name)
    if module is not None:
        return module
    path = Path(__file__).resolve().with_name("gateway_local_resources.py")
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise MarketOnlyResourceError("RESOURCE_SECURITY_HELPER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _windows_supported() -> bool:
    return os.name == "nt"


def _windows_security():
    if not _windows_supported():
        raise MarketOnlyResourceError("RESOURCE_PLATFORM_UNSUPPORTED")
    try:
        from bt_api_py import _win32_security
    except Exception:
        raise MarketOnlyResourceError("RESOURCE_SECURITY_UNAVAILABLE") from None
    if not _win32_security.WINDOWS or not _win32_security.has_privileges_available():
        raise MarketOnlyResourceError("RESOURCE_SECURITY_UNAVAILABLE")
    return _win32_security


def _path_is_reparse_point_or_absent(path: Path, security: Any) -> bool:
    """Return True if path is a reparse point; treat genuinely absent paths as False.

    On Windows, ``bt_api_py._win32_security.is_reparse_point`` raises
    ``Win32SecurityUnavailable`` when ``GetFileAttributesW`` returns
    ``INVALID_FILE_ATTRIBUTES`` for a path that does not exist yet. Confirm
    absence via ``lstat()`` (which still succeeds for dangling symlinks/junctions)
    and re-raise on any present entry or non-ENOENT error (fail-closed).
    """
    try:
        return bool(security.is_reparse_point(path))
    except Exception:
        try:
            path.lstat()
        except FileNotFoundError:
            return False
        raise


def _narrow_private_acl_windows(path: Path, security: Any | None = None) -> None:
    """Narrow a freshly created local file/directory to owner-only DACL before verification."""
    sec = security if security is not None else _windows_security()
    narrow = getattr(sec, "_set_owner_only_acl", None)
    if callable(narrow):
        narrow(path)


def _secure_windows_directory(path: Path, *, create: bool = False) -> None:
    security = _windows_security()
    try:
        security.ensure_directory_chain(path, create=create)
        owner = security.inspect_owner(path)
        if not owner.is_current_user or owner.others_writable or security.is_reparse_point(path):
            raise MarketOnlyResourceError("RESOURCE_DIRECTORY_UNTRUSTED")
        _local_resource_module()._assert_private_dacl_windows(path)
    except MarketOnlyResourceError:
        raise
    except Exception:
        raise MarketOnlyResourceError("RESOURCE_DIRECTORY_UNTRUSTED") from None


def _secure_created_windows_directory(path: Path) -> None:
    """Narrow and verify a freshly created directory on Windows."""
    security = _windows_security()
    try:
        if security.is_reparse_point(path):
            raise MarketOnlyResourceError("RESOURCE_DIRECTORY_UNTRUSTED")
        _narrow_private_acl_windows(path, security)
    except MarketOnlyResourceError:
        raise
    except Exception:
        raise MarketOnlyResourceError("RESOURCE_DIRECTORY_UNTRUSTED") from None
    _secure_windows_directory(path)


def _canonical_resource_root(value: str | os.PathLike[str]) -> tuple[Path, str]:
    try:
        raw = os.fspath(value)
        if type(raw) is not str or not raw or raw != raw.strip() or "\x00" in raw:
            raise ValueError
        path = Path(raw)
        if not path.is_absolute() or ".." in path.parts or raw != os.path.normpath(raw):
            raise ValueError
        if os.name == "nt" and (raw.startswith("\\\\") or any(":" in p for p in path.parts[1:])):
            raise ValueError
        resolved = path.resolve(strict=True)
        if os.path.normcase(str(resolved)) != os.path.normcase(os.path.abspath(raw)):
            raise ValueError
        generation = resolved.name
        if not _GENERATION_RE.fullmatch(generation):
            raise ValueError
        return resolved, generation
    except Exception:
        raise MarketOnlyResourceError("RESOURCE_ROOT_INVALID") from None


def _validate_resource_tree(root: Path) -> None:
    _secure_windows_directory(root)
    _secure_windows_directory(root / "gateway")
    _secure_windows_directory(root / "gateway" / "keys")


def _read_private_json(path: Path) -> bytes:
    security = _windows_security()
    try:
        _local_resource_module()._assert_private_dacl_windows(path)
        raw = security.read_bounded_windows(path, _MAX_CONNECTION_BYTES, protected=True)
        _local_resource_module()._assert_private_dacl_windows(path)
    except Exception:
        raise MarketOnlyResourceError("CONNECTION_FILE_UNTRUSTED") from None
    if type(raw) is not bytes or not raw or len(raw) > _MAX_CONNECTION_BYTES:
        raise MarketOnlyResourceError("CONNECTION_FILE_INVALID")
    return raw


def _read_key_file(path: Path, *, private: bool) -> bytes:
    security = _windows_security()
    try:
        if private:
            _local_resource_module()._assert_private_dacl_windows(path)
        raw = security.read_bounded_windows(path, 40, protected=True)
        if private:
            _local_resource_module()._assert_private_dacl_windows(path)
    except Exception:
        raise MarketOnlyResourceError("KEY_FILE_UNTRUSTED") from None
    if type(raw) is not bytes or len(raw) != 40:
        raise MarketOnlyResourceError("KEY_LENGTH_INVALID")
    try:
        from zmq.utils import z85

        if len(z85.decode(raw)) != 32:
            raise ValueError
    except Exception:
        raise MarketOnlyResourceError("KEY_FORMAT_INVALID") from None
    return raw


def _json_no_duplicates(pairs):
    output = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate")
        output[key] = value
    return output


def _expected_refs(ctp_profile: str) -> tuple[str, str]:
    try:
        from bt_api_py.ctp_account_process import ctp_simnow_gateway_refs

        refs = ctp_simnow_gateway_refs(ctp_profile)
        return refs.market_source_ref, refs.market_entitlement_ref
    except Exception:
        raise MarketOnlyResourceError("GATEWAY_PROFILE_INVALID") from None


def validate_market_connection_document(
    document: Any, *, generation_id: str
) -> dict[str, str]:
    """Validate the exact non-secret market connection schema."""
    if (
        type(document) is not dict
        or set(document) != {"schema_version", "generation_id", "gateway"}
        or type(document.get("schema_version")) is not int
        or document["schema_version"] != 1
        or document.get("generation_id") != generation_id
        or type(document.get("gateway")) is not dict
    ):
        raise MarketOnlyResourceError("CONNECTION_SCHEMA_INVALID")
    gateway = document["gateway"]
    if set(gateway) != {
        "ctp_profile",
        "rpc_endpoint",
        "market_endpoint",
        "source_ref",
        "entitlement_ref",
    }:
        raise MarketOnlyResourceError("CONNECTION_SCHEMA_INVALID")
    profile = gateway["ctp_profile"]
    if type(profile) is not str or not 0 < len(profile) <= 48:
        raise MarketOnlyResourceError("GATEWAY_PROFILE_INVALID")
    expected_source, expected_entitlement = _expected_refs(profile)
    if (
        gateway["source_ref"] != expected_source
        or gateway["entitlement_ref"] != expected_entitlement
    ):
        raise MarketOnlyResourceError("GATEWAY_REFERENCE_MISMATCH")
    endpoints = []
    for field_name in ("rpc_endpoint", "market_endpoint"):
        value = gateway[field_name]
        match = _ENDPOINT_RE.fullmatch(value) if type(value) is str else None
        if match is None or not 1 <= int(match.group(1)) <= 65535:
            raise MarketOnlyResourceError("GATEWAY_ENDPOINT_INVALID")
        endpoints.append(value)
    if endpoints[0] == endpoints[1]:
        raise MarketOnlyResourceError("GATEWAY_ENDPOINT_INVALID")
    return {
        "ctp_profile": profile,
        "rpc_endpoint": endpoints[0],
        "market_endpoint": endpoints[1],
        "source_ref": expected_source,
        "entitlement_ref": expected_entitlement,
    }


def load_market_connection(resource_root: str | os.PathLike[str]) -> LoadedMarketConnection:
    """Read one bounded non-secret document and exactly three fixed key files."""
    root, generation_id = _canonical_resource_root(resource_root)
    _validate_resource_tree(root)
    config_path = root / "gateway" / "market_connection.json"
    raw = _read_private_json(config_path)
    try:
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_no_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except Exception:
        raise MarketOnlyResourceError("CONNECTION_JSON_INVALID") from None
    gateway = validate_market_connection_document(document, generation_id=generation_id)
    key_dir = root / "gateway" / "keys"
    keys = {}
    for field_name, (filename, private) in _FIXED_KEY_FILES.items():
        keys[field_name] = _read_key_file(key_dir / filename, private=private)
    try:
        import zmq

        if zmq.curve_public(keys["client_secret_key"]) != keys["client_public_key"]:
            raise ValueError
        from bt_api_py.ctp_gateway_composition import GatewayClientConnection

        connection = GatewayClientConnection(
            rpc_endpoint=gateway["rpc_endpoint"],
            market_endpoint=gateway["market_endpoint"],
            source_ref=gateway["source_ref"],
            entitlement_ref=gateway["entitlement_ref"],
            **keys,
        )
    except Exception:
        raise MarketOnlyResourceError("CLIENT_KEY_PAIR_INVALID") from None
    return LoadedMarketConnection(
        root,
        generation_id,
        connection,
        hashlib.sha256(raw).hexdigest(),
    )


def default_identity_state_root() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA", "")
        if not base or not Path(base).is_absolute():
            raise MarketOnlyResourceError("IDENTITY_STATE_ROOT_UNAVAILABLE")
        return Path(base) / "bt_api_py" / "market_only"
    base = os.environ.get("XDG_STATE_HOME", "")
    parent = Path(base) if base else Path.home() / ".local" / "state"
    if not parent.is_absolute():
        raise MarketOnlyResourceError("IDENTITY_STATE_ROOT_UNAVAILABLE")
    return parent / "bt_api_py" / "market_only"


class GlobalMarketIdentityLease:
    """Cross-process exclusive gate for the SDK's fixed strategy identity."""

    def __init__(self, state_root: str | os.PathLike[str] | None = None):
        self.state_root = Path(state_root) if state_root is not None else default_identity_state_root()
        if not self.state_root.is_absolute():
            raise MarketOnlyResourceError("IDENTITY_STATE_ROOT_UNAVAILABLE")
        self.lock_path = self.state_root / "identity.lock"
        self.marker_path = self.state_root / "cleanup-marker.json"
        self._lock: FileLock | None = None
        self._marker_identity: tuple[int, int] | None = None
        self.active = False
        self.retained = False

    @property
    def held(self) -> bool:
        return self._lock is not None and self._lock.held

    def acquire(self) -> None:
        if not _windows_supported():
            raise MarketOnlyResourceError("IDENTITY_LOCK_PLATFORM_UNSUPPORTED")
        _secure_windows_directory(self.state_root, create=True)
        security = _windows_security()
        try:
            if _path_is_reparse_point_or_absent(self.lock_path, security):
                raise ValueError
            if not self.lock_path.exists():
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
                fd = os.open(self.lock_path, flags, 0o600)
                try:
                    os.write(fd, b" ")
                    os.fsync(fd)
                finally:
                    os.close(fd)
                _narrow_private_acl_windows(self.lock_path, security)
            details = self.lock_path.lstat()
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
                or details.st_size != 1
                or security.is_reparse_point(self.lock_path)
            ):
                raise ValueError
            _local_resource_module()._assert_private_dacl_windows(self.lock_path)
            lock = FileLock(self.lock_path, timeout=0)
            if not lock.try_acquire():
                raise MarketOnlyResourceError("MARKET_IDENTITY_ALREADY_LOCKED")
            self._lock = lock
            held_details = os.fstat(lock._fd)
            path_details = self.lock_path.lstat()
            if (
                not stat.S_ISREG(held_details.st_mode)
                or held_details.st_size != 1
                or held_details.st_nlink != 1
                or (held_details.st_dev, held_details.st_ino)
                != (path_details.st_dev, path_details.st_ino)
                or path_details.st_size != 1
            ):
                raise ValueError
            _local_resource_module()._assert_private_dacl_windows(self.lock_path)
            if self.marker_path.exists() or _path_is_reparse_point_or_absent(self.marker_path, security):
                self._validate_marker_path()
                self.release_unstarted()
                raise MarketOnlyResourceError("MARKET_IDENTITY_CLEANUP_UNCERTAIN")
        except MarketOnlyResourceError:
            self.release_unstarted()
            raise
        except Exception:
            self.release_unstarted()
            raise MarketOnlyResourceError("MARKET_IDENTITY_LOCK_UNAVAILABLE") from None

    def _assert_lock_identity(self) -> None:
        if not self.held or self._lock is None or self._lock._fd is None:
            raise MarketOnlyResourceError("MARKET_IDENTITY_LEASE_INVALID")
        security = _windows_security()
        if security.is_reparse_point(self.lock_path):
            raise MarketOnlyResourceError("MARKET_IDENTITY_LOCK_UNTRUSTED")
        opened = os.fstat(self._lock._fd)
        visible = self.lock_path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size != 1
            or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
            or visible.st_size != 1
        ):
            raise MarketOnlyResourceError("MARKET_IDENTITY_LOCK_UNTRUSTED")
        _local_resource_module()._assert_private_dacl_windows(self.lock_path)

    def _validate_marker_path(self) -> None:
        security = _windows_security()
        details = self.marker_path.lstat()
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or not 0 < details.st_size <= 512
            or security.is_reparse_point(self.marker_path)
        ):
            raise MarketOnlyResourceError("MARKET_IDENTITY_MARKER_UNTRUSTED")
        _local_resource_module()._assert_private_dacl_windows(self.marker_path)

    def mark_active(self, *, generation_id: str, run_id: str) -> None:
        if (
            not self.held
            or self.active
            or type(generation_id) is not str
            or not _GENERATION_RE.fullmatch(generation_id)
            or type(run_id) is not str
            or not _RUN_ID_RE.fullmatch(run_id)
        ):
            raise MarketOnlyResourceError("MARKET_IDENTITY_LEASE_INVALID")
        self._assert_lock_identity()
        payload = json.dumps(
            {"schema_version": 1, "status": "active", "generation_id": generation_id, "run_id": run_id},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            fd = os.open(self.marker_path, flags, 0o600)
            try:
                view = memoryview(payload)
                while view:
                    view = view[os.write(fd, view):]
                os.fsync(fd)
                opened = os.fstat(fd)
            finally:
                os.close(fd)
            _narrow_private_acl_windows(self.marker_path)
            _local_resource_module()._assert_private_dacl_windows(self.marker_path)
            details = self.marker_path.lstat()
            if (
                (opened.st_dev, opened.st_ino) != (details.st_dev, details.st_ino)
                or opened.st_size != len(payload)
                or details.st_size != len(payload)
            ):
                raise ValueError
            self._marker_identity = (details.st_dev, details.st_ino)
            self.active = True
        except Exception:
            self.retained = True
            _RETAINED_LEASES.append(self)
            raise MarketOnlyResourceError("MARKET_IDENTITY_MARKER_WRITE_FAILED") from None

    def _write_uncertain_marker(self) -> None:
        self._assert_lock_identity()
        payload = b'{"schema_version":1,"status":"uncertain"}\n'
        if self.marker_path.exists():
            self._validate_marker_path()
            before = self.marker_path.lstat()
            if (
                self._marker_identity is None
                or self._marker_identity != (before.st_dev, before.st_ino)
            ):
                raise MarketOnlyResourceError("MARKET_IDENTITY_MARKER_UNTRUSTED")
            atomic_write_bytes(self.marker_path, payload)
            _narrow_private_acl_windows(self.marker_path)
            after = self.marker_path.lstat()
            if (
                (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
                or after.st_size != len(payload)
            ):
                raise MarketOnlyResourceError("MARKET_IDENTITY_MARKER_REPLACE_FAILED")
            _local_resource_module()._assert_private_dacl_windows(self.marker_path)
            self._marker_identity = (after.st_dev, after.st_ino)
        else:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            fd = os.open(self.marker_path, flags, 0o600)
            try:
                os.write(fd, payload)
                os.fsync(fd)
                opened = os.fstat(fd)
            finally:
                os.close(fd)
            _narrow_private_acl_windows(self.marker_path)
            _local_resource_module()._assert_private_dacl_windows(self.marker_path)
            details = self.marker_path.lstat()
            if (
                (opened.st_dev, opened.st_ino) != (details.st_dev, details.st_ino)
                or details.st_size != len(payload)
            ):
                raise ValueError
            self._marker_identity = (details.st_dev, details.st_ino)

    def mark_uncertain(self) -> None:
        try:
            self._write_uncertain_marker()
        except Exception:
            # The prior ACTIVE marker is already a durable fail-closed signal.
            pass
        self.retained = True
        if self not in _RETAINED_LEASES:
            _RETAINED_LEASES.append(self)

    def clear_active_marker(self) -> None:
        if self.active:
            try:
                self._assert_lock_identity()
                self._validate_marker_path()
                details = self.marker_path.lstat()
                if self._marker_identity != (details.st_dev, details.st_ino):
                    raise ValueError
                self.marker_path.unlink()
                if self.marker_path.exists() or _path_is_reparse_point_or_absent(
                    self.marker_path, _windows_security()
                ):
                    raise ValueError
                fsync_directory(self.state_root)
                self.active = False
            except Exception:
                self.mark_uncertain()
                raise MarketOnlyResourceError("MARKET_IDENTITY_CLEANUP_UNCERTAIN") from None

    def release_clean(self) -> None:
        if self.active or self.retained:
            raise MarketOnlyResourceError("MARKET_IDENTITY_CLEANUP_UNCERTAIN")
        try:
            self._assert_lock_identity()
        except Exception:
            self.mark_uncertain()
            raise MarketOnlyResourceError("MARKET_IDENTITY_CLEANUP_UNCERTAIN") from None
        lock, self._lock = self._lock, None
        if lock is not None:
            lock.release()

    def mark_clean(self) -> None:
        """Compatibility helper for callers that do not need a receipt barrier."""
        self.clear_active_marker()
        self.release_clean()

    def release_unstarted(self) -> None:
        if self.active or self.retained:
            return
        lock, self._lock = self._lock, None
        if lock is not None:
            lock.release()


class MarketOnlyReceiptSink:
    """Atomically rewrite a bounded receipt using only non-secret observations."""

    def __init__(
        self,
        receipt_path: str | os.PathLike[str],
        *,
        generation_id: str,
        run_id: str,
        connection_json_sha256: str,
    ):
        if (
            type(generation_id) is not str
            or not _GENERATION_RE.fullmatch(generation_id)
            or type(run_id) is not str
            or not _RUN_ID_RE.fullmatch(run_id)
            or type(connection_json_sha256) is not str
            or not _SHA256_RE.fullmatch(connection_json_sha256)
        ):
            raise MarketOnlyResourceError("RECEIPT_IDENTITY_INVALID")
        self.receipt_path = Path(receipt_path)
        self._document = {
            "schema_version": 1,
            "generation_id": generation_id,
            "run_id": run_id,
            "connection_json_sha256": connection_json_sha256,
            "events": [],
            "ticks": {},
        }

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def _persist(self) -> None:
        raw = json.dumps(self._document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(raw) > _MAX_RECEIPT_BYTES:
            raise MarketOnlyResourceError("RECEIPT_LIMIT_EXCEEDED")
        atomic_write_bytes(self.receipt_path, raw)
        if _windows_supported():
            _narrow_private_acl_windows(self.receipt_path)
            _local_resource_module()._assert_private_dacl_windows(self.receipt_path)

    def record_start(self, *, generation_id: str, run_id: str, strategy: str, instruments: list):
        if (
            generation_id != self._document["generation_id"]
            or run_id != self._document["run_id"]
            or type(strategy) is not str
            or re.fullmatch(r"[a-z0-9_]{1,64}", strategy) is None
            or type(instruments) is not list
            or not 1 <= len(instruments) <= 2
            or any(
                type(item) is not tuple
                or len(item) != 2
                or any(type(part) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,32}", part) is None for part in item)
                for item in instruments
            )
        ):
            raise MarketOnlyResourceError("RECEIPT_START_INVALID")
        self._document["events"].append({
            "type": "start",
            "generation_id": generation_id,
            "run_id": run_id,
            "strategy": strategy,
            "instruments": [{"symbol": symbol, "venue": venue} for symbol, venue in instruments],
            "at_utc": self._now(),
        })
        self._persist()

    def record_tick(self, tick: Any) -> None:
        cursor = getattr(getattr(tick, "source_event", None), "cursor", None)
        symbol = getattr(tick, "symbol", None)
        event_time = getattr(tick, "event_time", None)
        if (
            type(symbol) is not str
            or not 0 < len(symbol) <= 32
            or cursor is None
            or type(cursor.sequence) is not int
            or cursor.sequence <= 0
            or not isinstance(event_time, datetime)
            or event_time.tzinfo is None
            or event_time.utcoffset() != timezone.utc.utcoffset(event_time)
        ):
            raise MarketOnlyResourceError("RECEIPT_TICK_CURSOR_INVALID")
        item = self._document["ticks"].get(symbol)
        if item is None:
            item = {
                "count": 0,
                "first_event_time": event_time.isoformat(),
                "first_sequence": cursor.sequence,
                "last_event_time": event_time.isoformat(),
                "last_sequence": cursor.sequence,
            }
            self._document["ticks"][symbol] = item
        elif cursor.sequence != item["last_sequence"] + 1:
            raise MarketOnlyResourceError("RECEIPT_TICK_SEQUENCE_INVALID")
        item["count"] += 1
        item["last_event_time"] = event_time.isoformat()
        item["last_sequence"] = cursor.sequence
        self._persist()

    def record_zero_write_scope(self, metrics: dict[str, Any]) -> None:
        counter_names = {
            "strategy_order_attempts",
            "strategy_order_rejections",
            "strategy_cancel_attempts",
            "strategy_cancel_rejections",
            "broker_order_attempts",
            "broker_order_rejections",
            "broker_cancel_attempts",
            "broker_cancel_rejections",
            "account_read_attempts",
        }
        operations = [
            "market.subscribe",
            "market.unsubscribe",
            "market.snapshot",
            "market.head",
            "market.read_after",
        ]
        if (
            type(metrics) is not dict
            or set(metrics) != counter_names | {
                "market_operation_allowlist",
                "market_operation_counts_instrumented",
                "global_zero_write_claim",
            }
            or metrics.get("market_operation_allowlist") != operations
            or metrics.get("market_operation_counts_instrumented") is not False
            or metrics.get("global_zero_write_claim") is not False
            or any(type(metrics.get(name)) is not int or metrics[name] < 0 for name in counter_names)
        ):
            raise MarketOnlyResourceError("RECEIPT_WRITE_SCOPE_INVALID")
        safe_metrics = {
            "market_operation_allowlist": operations,
            "market_operation_counts_instrumented": False,
            "global_zero_write_claim": False,
            **{name: metrics[name] for name in counter_names},
        }
        self._document["events"].append({
            "type": "zero_write_scope",
            "metrics": safe_metrics,
            "global_zero_write_claim": False,
            "at_utc": self._now(),
        })
        self._persist()

    def record_cleanup(self, *, status: str) -> None:
        if status not in {"clean", "uncertain"}:
            raise MarketOnlyResourceError("RECEIPT_CLEANUP_STATUS_INVALID")
        self._document["events"].append({"type": "cleanup", "status": status, "at_utc": self._now()})
        self._persist()
