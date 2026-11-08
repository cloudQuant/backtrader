"""Strategy instance identity stored at ``state/identity.json`` (D62-04c).

One strategy directory is one strategy instance with a random UUID4 created by
an explicit first initialization and kept across restarts, code and parameter
changes.  The identity also records the host name and the resolved directory
path so that a copied or moved directory is detected
(:class:`LiveStateIdentityMismatch`) instead of silently sharing an id.  An
optional account binding stores only ``exchange``, ``account_hash`` (SHA-256
hex of the account id, never the raw id) and an optional ``route``.

Initialization writes pristine ``sequence.json``, ``pending.json`` and
``waiting_orders.json`` first and ``identity.json`` last with exclusive
creation (``O_CREAT | O_EXCL``), all under ``state/identity.lock``.  A crash in
between leaves pristine companion files that a re-run may overwrite; any
non-pristine leftover state makes initialization fail
(``state_dir_not_empty``) because it may belong to a lost identity.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
from typing import Any, Dict, Mapping, Optional

from ._common import (
    StatePaths,
    current_hostname,
    get_logger,
    is_sha256_hex,
    is_strict_int,
    is_text,
    is_uuid4,
    new_uuid4,
    resolve_strategy_dir,
    same_directory,
    utc_compact,
    utc_now_iso,
)
from .atomic import (
    FileLock,
    LiveStateCorrupt,
    LiveStateError,
    LiveStateIdentityMismatch,
    LiveStateLocked,
    LiveStateNotInitialized,
    atomic_write_json,
    dumps_json,
    fsync_directory,
    read_json,
)
from .audit import append_audit

__all__ = (
    "IDENTITY_VERSION",
    "REBIND_MODES",
    "StrategyIdentity",
    "bind_account",
    "hash_account_id",
    "initialize_identity",
    "load_identity",
    "normalize_account_binding",
    "rebind_identity",
)

_log = get_logger(__name__)

IDENTITY_VERSION = 1
REBIND_MODES = frozenset({"move", "new_instance"})
_BINDING_KEYS = frozenset({"exchange", "account_hash", "route"})
_BINDING_REQUIRED = frozenset({"exchange", "account_hash"})
_IDENTITY_KEYS = frozenset(
    {"version", "strategy_uuid", "created_at_utc", "hostname", "strategy_dir", "account_binding"}
)


def hash_account_id(account_id: str) -> str:
    """SHA-256 hex digest of the UTF-8 account id (the only stored account form).

    The digest hides the raw value from files and logs; it is not secret
    against enumeration of short numeric ids.
    """
    if type(account_id) is not str or not account_id.strip():
        raise LiveStateError("account_binding_invalid", "account_id")
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()


def normalize_account_binding(binding: Any) -> Optional[Dict[str, str]]:
    """Validate an account binding; ``None`` stays ``None``.

    Allowed keys: ``exchange`` and ``account_hash`` (required) and ``route``.
    Any other key (for example a raw account id) is rejected with
    ``LiveStateError("account_binding_invalid")``.
    """
    if binding is None:
        return None
    if not isinstance(binding, Mapping):
        raise LiveStateError("account_binding_invalid", "not_mapping")
    keys = set(binding)
    if not keys <= _BINDING_KEYS:
        raise LiveStateError("account_binding_invalid", "unexpected_key")
    if not _BINDING_REQUIRED <= keys:
        raise LiveStateError("account_binding_invalid", "missing_key")
    out = {}
    for key in sorted(keys):
        value = binding[key]
        if not is_text(value, max_len=200):
            raise LiveStateError("account_binding_invalid", key)
        out[key] = value
    if not is_sha256_hex(out["account_hash"]):
        raise LiveStateError("account_binding_invalid", "account_hash")
    return out


@dataclasses.dataclass(frozen=True)
class StrategyIdentity:
    """Persistent identity of one strategy instance (one strategy directory)."""

    strategy_uuid: str
    created_at_utc: str
    hostname: str
    strategy_dir: str
    account_binding: Optional[Dict[str, str]] = None
    version: int = IDENTITY_VERSION

    def __post_init__(self) -> None:
        if not is_uuid4(self.strategy_uuid):
            raise ValueError("strategy_uuid")
        if not is_text(self.created_at_utc, max_len=64):
            raise ValueError("created_at_utc")
        if not is_text(self.hostname, max_len=255):
            raise ValueError("hostname")
        if not is_text(self.strategy_dir, max_len=4096) or not os.path.isabs(self.strategy_dir):
            raise ValueError("strategy_dir")
        if not is_strict_int(self.version) or self.version != IDENTITY_VERSION:
            raise ValueError("version")
        try:
            binding = normalize_account_binding(self.account_binding)
        except LiveStateError:
            raise ValueError("account_binding") from None
        object.__setattr__(self, "account_binding", binding)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "strategy_uuid": self.strategy_uuid,
            "created_at_utc": self.created_at_utc,
            "hostname": self.hostname,
            "strategy_dir": self.strategy_dir,
            "account_binding": None if self.account_binding is None else dict(self.account_binding),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "StrategyIdentity":
        if not isinstance(raw, Mapping) or set(raw) != _IDENTITY_KEYS:
            raise ValueError("keys")
        return cls(
            strategy_uuid=raw["strategy_uuid"],
            created_at_utc=raw["created_at_utc"],
            hostname=raw["hostname"],
            strategy_dir=raw["strategy_dir"],
            account_binding=raw["account_binding"],
            version=raw["version"],
        )


def _identity_from_file(path: str) -> StrategyIdentity:
    try:
        raw = read_json(path)
    except FileNotFoundError:
        raise LiveStateNotInitialized(path) from None
    if not isinstance(raw, dict):
        raise LiveStateCorrupt(path, "not_a_mapping")
    if raw.get("version") != IDENTITY_VERSION or type(raw.get("version")) is not int:
        raise LiveStateCorrupt(path, "version_unsupported")
    try:
        return StrategyIdentity.from_dict(raw)
    except ValueError as exc:
        raise LiveStateCorrupt(path, f"invalid_field:{exc}") from None


def _check_host_path(identity: StrategyIdentity, root: str) -> None:
    if identity.hostname != current_hostname():
        raise LiveStateIdentityMismatch("hostname_mismatch")
    if not same_directory(identity.strategy_dir, root):
        raise LiveStateIdentityMismatch("strategy_dir_mismatch")


def load_identity(strategy_dir: Any, *, check_host_path: bool = True) -> StrategyIdentity:
    """Load ``state/identity.json``.

    Raises :class:`LiveStateNotInitialized` if missing, :class:`LiveStateCorrupt`
    if invalid, and (when ``check_host_path``) :class:`LiveStateIdentityMismatch`
    with ``hostname_mismatch`` / ``strategy_dir_mismatch`` for a copied or
    moved directory.
    """
    paths = StatePaths(strategy_dir)
    identity = _identity_from_file(paths.identity)
    if check_host_path:
        _check_host_path(identity, paths.strategy_dir)
    return identity


def _companions(paths: StatePaths):
    from .pending import initial_pending_state, is_pristine_pending
    from .sequence import initial_sequence_state, is_pristine_sequence
    from .waiting import initial_waiting_state, is_pristine_waiting

    return (
        (paths.sequence, initial_sequence_state, is_pristine_sequence),
        (paths.pending, initial_pending_state, is_pristine_pending),
        (paths.waiting, initial_waiting_state, is_pristine_waiting),
    )


def _create_exclusive(path: str, text: str) -> None:
    data = text.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        raise LiveStateError("identity_already_initialized") from None
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    finally:
        os.close(fd)


def _initialize_locked(paths: StatePaths, binding: Optional[Dict[str, str]]) -> StrategyIdentity:
    """Create a fresh identity; caller holds ``identity.lock`` of ``paths``."""
    if os.path.lexists(paths.identity):
        raise LiveStateError("identity_already_initialized")
    companions = _companions(paths)
    for path, _initial, is_pristine in companions:
        if not os.path.lexists(path):
            continue
        try:
            raw = read_json(path)
        except (OSError, LiveStateError):
            raise LiveStateError("state_dir_not_empty", os.path.basename(path)) from None
        if not is_pristine(raw, path):
            raise LiveStateError("state_dir_not_empty", os.path.basename(path))
    if os.path.lexists(paths.audit) and os.path.getsize(paths.audit) > 0:
        raise LiveStateError("state_dir_not_empty", os.path.basename(paths.audit))
    identity = StrategyIdentity(
        strategy_uuid=new_uuid4(),
        created_at_utc=utc_now_iso(),
        hostname=current_hostname(),
        strategy_dir=paths.strategy_dir,
        account_binding=binding,
    )
    for path, initial, _is_pristine in companions:
        atomic_write_json(path, initial(identity.strategy_uuid))
    _create_exclusive(paths.identity, dumps_json(identity.to_dict()))
    fsync_directory(paths.state_dir)
    return identity


def _audit_best_effort(root: str, record: Mapping[str, Any]) -> None:
    try:
        append_audit(root, record)
    except Exception as exc:
        _log.warning("live_state audit append failed: %s", getattr(exc, "code", type(exc).__name__))


def initialize_identity(strategy_dir: Any, *, account_binding: Any = None) -> StrategyIdentity:
    """Explicit first initialization of a strategy directory.

    ``strategy_dir`` must already exist.  Creates ``state/`` and the initial
    state files; raises ``LiveStateError("identity_already_initialized")`` if
    an identity exists and ``("state_dir_not_empty")`` if non-pristine state
    without an identity is present.
    """
    root = resolve_strategy_dir(strategy_dir)
    if not os.path.isdir(root):
        raise LiveStateError("strategy_dir_missing")
    binding = normalize_account_binding(account_binding)
    paths = StatePaths(root)
    created_state_dir = not os.path.isdir(paths.state_dir)
    os.makedirs(paths.state_dir, exist_ok=True)
    if created_state_dir:
        fsync_directory(root)
    with FileLock(paths.identity_lock):
        identity = _initialize_locked(paths, binding)
    _audit_best_effort(
        root,
        {
            "event": "identity_initialized",
            "strategy_uuid": identity.strategy_uuid,
            "account_bound": binding is not None,
        },
    )
    return identity


def bind_account(strategy_dir: Any, account_binding: Mapping[str, str]) -> StrategyIdentity:
    """Bind the identity to an account once.

    No binding yet: store it (audited) and return the new identity.  Same
    binding: return the identity unchanged.  Different binding: raise
    ``LiveStateIdentityMismatch("account_binding_mismatch")``.  The host/path
    check of :func:`load_identity` applies.
    """
    binding = normalize_account_binding(account_binding)
    if binding is None:
        raise LiveStateError("account_binding_invalid", "none")
    paths = StatePaths(strategy_dir)
    with FileLock(paths.identity_lock):
        identity = load_identity(paths.strategy_dir, check_host_path=True)
        if identity.account_binding is not None:
            if identity.account_binding == binding:
                return identity
            raise LiveStateIdentityMismatch("account_binding_mismatch")
        updated = dataclasses.replace(identity, account_binding=binding)
        append_audit(
            paths.strategy_dir,
            {
                "event": "account_bound",
                "strategy_uuid": identity.strategy_uuid,
                "exchange": binding["exchange"],
                "account_hash_prefix": binding["account_hash"][:12],
            },
        )
        atomic_write_json(paths.identity, updated.to_dict())
        return updated


def _ensure_no_active_state(paths: StatePaths, strategy_uuid: str) -> None:
    from .pending import PendingCommandStore
    from .waiting import WaitingOrderStore

    pending = PendingCommandStore(paths.strategy_dir, strategy_uuid)
    if pending.active():
        raise LiveStateError("rebind_blocked_active_state", "pending_markers")
    pending_state = pending._load()
    if pending_state["version"] in (2, 3, 4):
        from .gateway_pending import has_unresolved_gateway_intents, has_unresolved_gateway_cancels
        if (has_unresolved_gateway_intents(pending_state)
                or has_unresolved_gateway_cancels(pending_state)):
            raise LiveStateError("rebind_blocked_active_state", "gateway_intents")
        if pending_state["version"] == 4:
            from .gateway_execution_state import has_unresolved_gateway_execution
            if has_unresolved_gateway_execution(pending_state):
                raise LiveStateError("rebind_blocked_active_state", "gateway_execution")
    if WaitingOrderStore(paths.strategy_dir, strategy_uuid).active():
        raise LiveStateError("rebind_blocked_active_state", "waiting_orders")


def rebind_identity(
    strategy_dir: Any, *, mode: str, operator: str, reason: str
) -> StrategyIdentity:
    """Explicit, audited answer to a host/path mismatch.

    ``mode="move"`` keeps the UUID and records the current host and path
    (``rebind_not_required`` if they already match).  ``mode="new_instance"``
    renames ``state/`` to ``state.archived-<utc>`` and initializes a fresh,
    unbound identity; it is refused (``rebind_blocked_active_state``) while
    the old state still has active pending markers or waiting orders, because
    archiving would silently drop UNKNOWN markers.  Corrupt old state also
    blocks it.  Both modes need the run lock (``LiveStateLocked`` if a live
    run holds it) and append an audit record before changing anything.
    """
    if mode not in REBIND_MODES:
        raise LiveStateError("rebind_invalid_mode")
    if not is_text(operator, max_len=200):
        raise LiveStateError("operator_required")
    if not is_text(reason, max_len=2000):
        raise LiveStateError("reason_required")
    paths = StatePaths(strategy_dir)
    root = paths.strategy_dir
    if not os.path.isdir(paths.state_dir):
        raise LiveStateNotInitialized(paths.state_dir, "state_dir_missing")
    run_lock = FileLock(paths.run_lock, timeout=0)
    if not run_lock.try_acquire():
        raise LiveStateLocked(paths.run_lock, "live_run_active")
    identity_lock = FileLock(paths.identity_lock)
    try:
        identity_lock.acquire()
        old = load_identity(root, check_host_path=False)
        host = current_hostname()
        base_record = {
            "event": "identity_rebind",
            "mode": mode,
            "operator": operator,
            "reason": reason,
            "strategy_uuid": old.strategy_uuid,
            "old_hostname": old.hostname,
            "new_hostname": host,
            "old_strategy_dir": old.strategy_dir,
            "new_strategy_dir": root,
        }
        if mode == "move":
            if old.hostname == host and same_directory(old.strategy_dir, root):
                raise LiveStateError("rebind_not_required")
            updated = dataclasses.replace(old, hostname=host, strategy_dir=root)
            append_audit(root, base_record)
            try:
                atomic_write_json(paths.identity, updated.to_dict())
            except BaseException:
                _audit_best_effort(root, {"event": "identity_rebind_failed", "mode": mode})
                raise
            return updated

        _ensure_no_active_state(paths, old.strategy_uuid)
        archive_name = f"{os.path.basename(paths.state_dir)}.archived-{utc_compact()}"
        archive_path = os.path.join(root, archive_name)
        append_audit(root, dict(base_record, archived_state_dir=archive_name))
        if os.name == "nt":  # pragma: no cover - open handles block a rename
            identity_lock.release()
            run_lock.release()
        os.rename(paths.state_dir, archive_path)
        fsync_directory(root)
        os.makedirs(paths.state_dir)
        with FileLock(paths.identity_lock):
            fresh = _initialize_locked(paths, None)
        _audit_best_effort(
            root,
            {
                "event": "identity_initialized",
                "via": "rebind_new_instance",
                "strategy_uuid": fresh.strategy_uuid,
                "previous_strategy_uuid": old.strategy_uuid,
                "archived_state_dir": archive_name,
                "operator": operator,
                "reason": reason,
                "account_bound": False,
            },
        )
        return fresh
    finally:
        identity_lock.release()
        run_lock.release()
