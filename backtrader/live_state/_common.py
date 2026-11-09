"""Shared helpers for :mod:`backtrader.live_state` (private).

Paths, UTC timestamps, strict value validators and the secret-key guard used by
every state file.  Nothing here touches an account or a provider.
"""

from __future__ import annotations

import datetime as _dt
import math
import os
import re
import socket
import uuid
from typing import Any, Mapping, Optional

try:  # pragma: no cover - exercised implicitly; fallback only outside backtrader
    from backtrader.utils.log_message import get_logger as _bt_get_logger
except Exception:  # pragma: no cover
    _bt_get_logger = None


def get_logger(name: str):
    """Return the backtrader logger for ``name`` (stdlib logging fallback)."""
    if _bt_get_logger is not None:
        return _bt_get_logger(name)
    import logging

    return logging.getLogger(name)


STATE_DIRNAME = "state"
LOGS_DIRNAME = "logs"

IDENTITY_FILE = "identity.json"
SEQUENCE_FILE = "sequence.json"
PENDING_FILE = "pending.json"
WAITING_FILE = "waiting_orders.json"
AUDIT_FILE = "audit.log"
RUN_LOCK_FILE = "run.lock"
# Strategy-root lock that state archiving never moves (E020, coordination.py).
COORDINATION_LOCK_FILE = ".state-coordination.lock"
SNAPSHOT_FILE = "current_position.yaml"

_MAX_DEPTH = 16


class StatePaths:
    """Every path of one strategy directory, resolved once."""

    __slots__ = (
        "strategy_dir",
        "state_dir",
        "logs_dir",
        "identity",
        "identity_lock",
        "sequence",
        "sequence_lock",
        "pending",
        "pending_lock",
        "waiting",
        "waiting_lock",
        "audit",
        "audit_lock",
        "run_lock",
        "coordination_lock",
        "snapshot",
        "snapshot_lock",
    )

    def __init__(self, strategy_dir: Any) -> None:
        root = resolve_strategy_dir(strategy_dir)
        state = os.path.join(root, STATE_DIRNAME)
        logs = os.path.join(root, LOGS_DIRNAME)
        self.strategy_dir = root
        self.state_dir = state
        self.logs_dir = logs
        self.identity = os.path.join(state, IDENTITY_FILE)
        self.identity_lock = os.path.join(state, "identity.lock")
        self.sequence = os.path.join(state, SEQUENCE_FILE)
        self.sequence_lock = os.path.join(state, "sequence.lock")
        self.pending = os.path.join(state, PENDING_FILE)
        self.pending_lock = os.path.join(state, "pending.lock")
        self.waiting = os.path.join(state, WAITING_FILE)
        self.waiting_lock = os.path.join(state, "waiting.lock")
        self.audit = os.path.join(state, AUDIT_FILE)
        self.audit_lock = os.path.join(state, "audit.lock")
        self.run_lock = os.path.join(state, RUN_LOCK_FILE)
        self.coordination_lock = os.path.join(root, COORDINATION_LOCK_FILE)
        self.snapshot = os.path.join(logs, SNAPSHOT_FILE)
        self.snapshot_lock = os.path.join(logs, ".current_position.lock")


def resolve_strategy_dir(strategy_dir: Any) -> str:
    """Return the absolute, symlink-resolved strategy directory path."""
    from .atomic import LiveStateError

    try:
        raw = os.fspath(strategy_dir)
    except TypeError:
        raise LiveStateError("invalid_strategy_dir", "path_type") from None
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    if not raw or raw != raw.strip():
        raise LiveStateError("invalid_strategy_dir", "empty_or_untrimmed")
    return os.path.realpath(os.path.abspath(raw))


def same_directory(stored: str, current: str) -> bool:
    """Whether ``stored`` and ``current`` name the same directory."""
    if os.path.normcase(stored) == os.path.normcase(current):
        return True
    try:
        return os.path.isdir(stored) and os.path.samefile(stored, current)
    except OSError:
        return False


def current_hostname() -> str:
    from .atomic import LiveStateError

    name = socket.gethostname()
    if type(name) is not str or not name.strip():
        raise LiveStateError("hostname_unavailable")
    return name.strip()


def utc_now_iso() -> str:
    """Current UTC time as ISO-8601 with microseconds and ``+00:00``."""
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="microseconds")


def utc_compact() -> str:
    """Current UTC time as a filesystem-safe compact stamp."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def is_uuid4(value: Any) -> bool:
    """Whether ``value`` is a canonical lowercase UUID4 string."""
    if type(value) is not str:
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def new_uuid4() -> str:
    return str(uuid.uuid4())


def is_strict_int(value: Any, *, minimum: Optional[int] = None) -> bool:
    if type(value) is not int:
        return False
    return minimum is None or value >= minimum


def is_finite_number(value: Any) -> bool:
    if type(value) is int:
        return True
    return type(value) is float and math.isfinite(value)


def is_text(value: Any, *, max_len: int = 1024) -> bool:
    """Non-empty, trimmed, bounded string."""
    return type(value) is str and bool(value) and value == value.strip() and len(value) <= max_len


_TRADING_DAY = re.compile(r"^[0-9]{8}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def is_trading_day(value: Any) -> bool:
    return type(value) is str and bool(_TRADING_DAY.match(value))


def is_sha256_hex(value: Any) -> bool:
    return type(value) is str and bool(_SHA256_HEX.match(value))


def parse_aware_iso(value: Any) -> Optional[_dt.datetime]:
    """Parse a timezone-aware ISO-8601 string (``Z`` accepted); else ``None``."""
    if type(value) is not str or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


# --- secret guard -----------------------------------------------------------
# Key-name guard only: it rejects records whose *keys* name a credential or a
# raw account identifier.  It cannot prove that free-text values are clean.
_FORBIDDEN_KEYS = frozenset(
    {
        "account",
        "accountid",
        "investorid",
        "userid",
        "uid",
        "clientid",
        "pwd",
    }
)
_FORBIDDEN_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "passphrase",
    "privatekey",
    "apikey",
    "accesskey",
    "authcode",
    "mnemonic",
)
_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _secret_key(key: str) -> bool:
    norm = _NON_ALNUM.sub("", key.lower())
    if norm in _FORBIDDEN_KEYS:
        return True
    return any(fragment in norm for fragment in _FORBIDDEN_FRAGMENTS)


def find_secret_key(obj: Any, _depth: int = 0) -> Optional[str]:
    """Return the first key that names a secret or raw account id, else ``None``."""
    if _depth > _MAX_DEPTH:
        return "<too_deep>"
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if type(key) is str and _secret_key(key):
                return key
            found = find_secret_key(value, _depth + 1)
            if found is not None:
                return found
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            found = find_secret_key(item, _depth + 1)
            if found is not None:
                return found
    return None


def ensure_no_secret_keys(obj: Any, where: str) -> None:
    from .atomic import LiveStateError

    found = find_secret_key(obj)
    if found is not None:
        raise LiveStateError("secret_field_rejected", f"{where}:{found}")


def json_safe_copy(obj: Any, where: str, _depth: int = 0) -> Any:
    """Deep-copy ``obj`` as plain JSON types or raise ``value_not_json_safe``.

    Accepts mappings with non-empty ``str`` keys, lists/tuples, ``str``,
    ``int``, ``bool``, finite ``float`` and ``None``.  Enum members with a
    ``str``/``int`` ``value`` are reduced to that value.
    """
    from .atomic import LiveStateError

    if _depth > _MAX_DEPTH:
        raise LiveStateError("value_not_json_safe", f"{where}:too_deep")
    if obj is None or type(obj) in (str, int, bool):
        return obj
    if type(obj) is float:
        if not math.isfinite(obj):
            raise LiveStateError("value_not_json_safe", f"{where}:non_finite")
        return obj
    if isinstance(obj, Mapping):
        out = {}
        for key, value in obj.items():
            if type(key) is not str or not key:
                raise LiveStateError("value_not_json_safe", f"{where}:key")
            out[key] = json_safe_copy(value, where, _depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [json_safe_copy(item, where, _depth + 1) for item in obj]
    enum_value = getattr(obj, "value", None)
    if (
        enum_value is not None
        and type(enum_value) in (str, int)
        and hasattr(type(obj), "__members__")
    ):
        return enum_value
    raise LiveStateError("value_not_json_safe", f"{where}:{type(obj).__name__}")


def scalar_mapping(value: Any, where: str) -> dict:
    """Copy a flat mapping of scalar values (str/int/bool/finite float/None)."""
    from .atomic import LiveStateError

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise LiveStateError("value_not_json_safe", f"{where}:not_mapping")
    out = {}
    for key, item in value.items():
        if type(key) is not str or not key:
            raise LiveStateError("value_not_json_safe", f"{where}:key")
        if item is not None and type(item) not in (str, int, bool, float):
            raise LiveStateError("value_not_json_safe", f"{where}:{key}")
        if type(item) is float and not math.isfinite(item):
            raise LiveStateError("value_not_json_safe", f"{where}:{key}")
        out[key] = item
    return out


def strict_equal(left: Any, right: Any) -> bool:
    """Type-strict equality (``1 != 1.0 != True`` and ``"1" != 1``)."""
    return type(left) is type(right) and left == right
