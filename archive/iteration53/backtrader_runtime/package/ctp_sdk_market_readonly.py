"""Bounded CTP market-data probe with no trader or execution client.

This module is intentionally separate from the private-account query session.
It accepts only the exact, already-reviewed SimNow admission produced by the
runtime route, and passes that admission's ``md_front`` value unchanged to the
SDK's ``MdClient``.  The SDK profile map is validated by the admission type;
it is never used here to select or replace an endpoint.

The probe subscribes to exactly one admitted instrument.  Successful market
login and a successful subscription acknowledgement are required.  Receiving
a tick is reported as an observation only because a quiet contract/session can
legitimately produce no tick during a short probe window.  Its account lease
coordinates only other invocations of this probe; existing ``MdClient`` and
``CtpMarketStream`` sessions do not participate and must not run concurrently
for the same account during this probe. A tick observation requires the exact
instrument and exchange, finite positive LastPrice, and non-negative integer
Volume after the exact subscription acknowledgement and inside the optional
bounded observation window. Accepted callbacks are bound to the sealed
account/front/contract and connection generation. This remains local callback
evidence, not independent native-data QA or proof of real-market readiness.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import stat
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .ctp_sandbox_readonly_admission import CtpSandboxReadOnlyRegistration


_MD_LOGIN_BROKER_ID_SHAPES = frozenset(
    {
        "not_observed",
        "unreadable",
        "empty",
        "ascii_mismatch",
        "nonascii_or_replacement",
        "whitespace_or_control",
        "exact_match",
    }
)
_MD_LOGIN_USER_ID_SHAPES = frozenset(
    {
        "not_observed",
        "unreadable",
        "empty",
        "ascii_mismatch",
        "nonascii_or_replacement",
        "whitespace_or_control",
        "exact_match",
    }
)
_MD_LOGIN_TRADING_DAY_SHAPES = frozenset(
    {
        "not_observed",
        "unreadable",
        "empty",
        "invalid_format",
        "invalid_calendar",
        "valid",
    }
)
_MD_LOGIN_NATIVE_FIELD_SHAPES = frozenset(
    {
        "not_observed",
        "unreadable",
        "empty",
        "nonempty_terminated",
        "unterminated",
    }
)


class CtpSdkMarketReadOnlyError(ValueError):
    """A redacted failure from the bounded market-data-only probe."""

    def __init__(
        self,
        reason: str,
        *,
        close_state: str = "not_started",
        primary_reason: str | None = None,
        front_callback_observed: bool | None = None,
        login_callback_count: int | None = None,
        login_callback_disposition: str | None = None,
        login_request_id_relation: str | None = None,
        login_response_error_status: str | None = None,
        login_failure_category: str | None = None,
        login_broker_id_shape: str | None = None,
        login_user_id_shape: str | None = None,
        login_trading_day_shape: str | None = None,
        native_broker_id_shape: str | None = None,
        native_user_id_shape: str | None = None,
        client_stop_returned: bool | None = None,
    ) -> None:
        self.reason = reason
        self.close_state = close_state
        self.primary_reason = primary_reason
        self.front_callback_observed = front_callback_observed
        self.login_callback_count = login_callback_count
        self.login_callback_disposition = login_callback_disposition
        self.login_request_id_relation = login_request_id_relation
        self.login_response_error_status = login_response_error_status
        self.login_failure_category = login_failure_category
        self.login_broker_id_shape = (
            login_broker_id_shape
            if type(login_broker_id_shape) is str
            and login_broker_id_shape in _MD_LOGIN_BROKER_ID_SHAPES
            else None
        )
        self.login_user_id_shape = (
            login_user_id_shape
            if type(login_user_id_shape) is str and login_user_id_shape in _MD_LOGIN_USER_ID_SHAPES
            else None
        )
        self.login_trading_day_shape = (
            login_trading_day_shape
            if type(login_trading_day_shape) is str
            and login_trading_day_shape in _MD_LOGIN_TRADING_DAY_SHAPES
            else None
        )
        self.native_broker_id_shape = (
            native_broker_id_shape
            if type(native_broker_id_shape) is str
            and native_broker_id_shape in _MD_LOGIN_NATIVE_FIELD_SHAPES
            else None
        )
        self.native_user_id_shape = (
            native_user_id_shape
            if type(native_user_id_shape) is str
            and native_user_id_shape in _MD_LOGIN_NATIVE_FIELD_SHAPES
            else None
        )
        self.client_stop_returned = (
            client_stop_returned if type(client_stop_returned) is bool else None
        )
        super().__init__("CTP market-data read-only probe failed ({0})".format(reason))


class CtpMarketCredentialSource(Protocol):
    """Already-resolved credentials scoped to the admitted CTP account."""

    def require_credential(self, name: str) -> str:
        """Return one credential value without exposing it in diagnostics."""


@dataclass(frozen=True)
class CtpSdkMarketTickBinding:
    """Pathless identity binding for one or more accepted MD tick callbacks."""

    account_fingerprint_sha256: str = field(repr=False)
    md_front_sha256: str
    instrument_id: str
    exchange_id: str
    connection_generation: int

    def as_public_dict(self) -> dict[str, Any]:
        """Expose only the sealed identity scope, never raw provider values."""

        return {
            "account_bound": True,
            "connection_generation": self.connection_generation,
            "exchange_id": self.exchange_id,
            "instrument_id": self.instrument_id,
            "md_front_sha256": self.md_front_sha256,
        }


@dataclass(frozen=True)
class CtpSdkMarketReadOnlyObservation:
    """Non-authoritative MD readiness and optional first-tick observation.

    ``tick_observation_count`` counts callbacks received after the exact
    subscription acknowledgement, during the bounded optional observation
    window, and matching the admitted instrument/exchange with minimally valid
    price/volume fields. ``tick_binding`` records the callback's account, front,
    instrument, exchange, and connection generation. This is local SDK callback
    evidence, not independent native-data QA or proof of real-market readiness.

    ``client_stop_returned`` means the SDK stop method returned. The account
    lease is released only by an exact, complete, same-generation native stop
    receipt. An incomplete or unavailable receipt keeps the client and lease
    pinned until process exit; a Join thread exit alone is not proof that
    native release completed. The lease does not coordinate legacy or
    application-owned ``MdClient`` sessions. This value grants no account
    acceptance or execution authority.
    """

    md_front_sha256: str
    account_fingerprint_sha256: str = field(repr=False)
    instrument_id: str
    exchange_id: str
    market_login_ready: bool
    subscription_acknowledged: bool
    tick_observation_count: int
    tick_binding: CtpSdkMarketTickBinding | None
    connection_generation: int | None
    client_stop_returned: bool
    native_join_pending: bool

    @property
    def first_tick_observed(self) -> bool:
        """Whether at least one matching tick callback was observed."""

        return self.tick_observation_count > 0

    @property
    def probe_session_closed(self) -> bool:
        """Whether stop returned and no native Join remains pending/unknown."""

        return self.client_stop_returned and not self.native_join_pending

    @property
    def market_path_ready(self) -> bool:
        """Whether login and the exact single-instrument subscription passed."""

        return self.market_login_ready and self.subscription_acknowledged

    @property
    def order_submission_authorized(self) -> bool:
        """This market-data-only observation never carries order authority."""

        return False

    @property
    def trading_writes(self) -> int:
        """Market-data login/subscription performs no trading requests."""

        return 0

    @property
    def settlement_writes(self) -> int:
        """The market-data client has no settlement-write interface."""

        return 0

    def as_public_dict(self) -> dict[str, Any]:
        """Expose no raw account ID, credential, front, or provider payload."""

        return {
            "client_stop_returned": self.client_stop_returned,
            "connection_generation": self.connection_generation,
            "account_probe_lock_scope": "cooperating_probe_invocations_only",
            "account_scope_bound": bool(self.account_fingerprint_sha256),
            "exchange_id": self.exchange_id,
            "first_tick_observed": self.first_tick_observed,
            "instrument_id": self.instrument_id,
            "market_login_ready": self.market_login_ready,
            "market_path_ready": self.market_path_ready,
            "md_front_sha256": self.md_front_sha256,
            "native_join_pending": self.native_join_pending,
            "order_submission_authorized": False,
            "probe_session_closed": self.probe_session_closed,
            "subscription_acknowledged": self.subscription_acknowledged,
            "settlement_writes": self.settlement_writes,
            "tick_binding": (
                None if self.tick_binding is None else self.tick_binding.as_public_dict()
            ),
            "tick_observation_count": self.tick_observation_count,
            "trading_writes": self.trading_writes,
        }


_MAX_TIMEOUT_SECONDS = 60.0
_MAX_NATIVE_JOIN_WAIT_SECONDS = 1.0
_LOCK_DIRECTORY_NAME = "backtrader-runtime-ctp-md-probe"
_PROCESS_LOCKS: dict[str, threading.Lock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()
_PENDING_LEASES: dict[str, tuple["_AccountLease", Any, Any]] = {}
_PENDING_LEASES_GUARD = threading.Lock()
_MD_LOGIN_CALLBACK_DISPOSITIONS = frozenset(
    {
        "none",
        "stale_spi",
        "generation_mismatch",
        "request_id_type_invalid",
        "request_id_mismatch",
        "nonterminal",
        "accepted",
        "provider_rejected",
        "identity_rejected",
    }
)
_MD_LOGIN_REQUEST_ID_RELATIONS = frozenset(
    {"not_observed", "invalid", "zero", "lower", "equal", "higher"}
)
_MD_LOGIN_RESPONSE_ERROR_STATUSES = frozenset(
    {"not_observed", "missing", "invalid", "zero", "nonzero"}
)


def _md_login_callback_diagnostic(
    client: Any,
) -> tuple[int, str, str | None, str | None, str | None, str | None] | None:
    """Copy only the installed SDK's fixed MD callback disposition and count.

    This is a diagnostic observation, never login or write admission. Unknown
    SDK/fake shapes are omitted instead of exposing a provider payload.
    """

    try:
        diagnostic = client.login_callback_diagnostic
        count = diagnostic.callback_count
        disposition = diagnostic.disposition.value
    except Exception:
        return None
    if (
        type(count) is not int
        or not 0 <= count <= 1_000_000
        or type(disposition) is not str
        or disposition not in _MD_LOGIN_CALLBACK_DISPOSITIONS
    ):
        return None
    # Missing or unknown callback classifications cannot be interpreted as
    # provider evidence.
    try:
        relation = diagnostic.request_id_relation.value
        error_status = diagnostic.response_error_status.value
    except Exception:
        relation = error_status = None
    if (
        type(relation) is not str
        or relation not in _MD_LOGIN_REQUEST_ID_RELATIONS
        or type(error_status) is not str
        or error_status not in _MD_LOGIN_RESPONSE_ERROR_STATUSES
    ):
        relation = error_status = None
    native_shapes: list[str | None] = []
    for field_name in ("native_broker_id_shape", "native_user_id_shape"):
        try:
            shape = getattr(diagnostic, field_name).value
        except Exception:
            shape = None
        if type(shape) is not str or shape not in _MD_LOGIN_NATIVE_FIELD_SHAPES:
            shape = None
        native_shapes.append(shape)
    return count, disposition, relation, error_status, native_shapes[0], native_shapes[1]


def _reject(
    reason: str,
    *,
    close_state: str = "not_started",
    primary_reason: str | None = None,
    front_callback_observed: bool | None = None,
    login_callback_count: int | None = None,
    login_callback_disposition: str | None = None,
    login_request_id_relation: str | None = None,
    login_response_error_status: str | None = None,
    login_failure_category: str | None = None,
    login_broker_id_shape: str | None = None,
    login_user_id_shape: str | None = None,
    login_trading_day_shape: str | None = None,
    native_broker_id_shape: str | None = None,
    native_user_id_shape: str | None = None,
    client_stop_returned: bool | None = None,
) -> None:
    raise CtpSdkMarketReadOnlyError(
        reason,
        close_state=close_state,
        primary_reason=primary_reason,
        front_callback_observed=front_callback_observed,
        login_callback_count=login_callback_count,
        login_callback_disposition=login_callback_disposition,
        login_request_id_relation=login_request_id_relation,
        login_response_error_status=login_response_error_status,
        login_failure_category=login_failure_category,
        login_broker_id_shape=login_broker_id_shape,
        login_user_id_shape=login_user_id_shape,
        login_trading_day_shape=login_trading_day_shape,
        native_broker_id_shape=native_broker_id_shape,
        native_user_id_shape=native_user_id_shape,
        client_stop_returned=client_stop_returned,
    )


def _account_lock_root() -> Path:
    """Return a stable, per-OS-user lock directory independent of TMP/TEMP.

    Environment-selected temporary directories are unsuitable for a process
    lock: two invocations for the same user can inherit different TMP/TEMP
    values and silently acquire different files. Resolve the account's home
    directory from the OS account database on POSIX and its LocalAppData known
    folder on Windows instead.
    """

    if os.name == "nt":
        base = _windows_local_app_data()
        base_info = os.lstat(str(base))
        if _is_reparse_or_link(base_info) or not stat.S_ISDIR(base_info.st_mode):
            _reject("account_probe_lock_unavailable")
    else:
        import pwd

        uid = os.getuid()
        home = pwd.getpwuid(uid).pw_dir
        if type(home) is not str or not os.path.isabs(home):
            _reject("account_probe_lock_unavailable")
        base = Path(home)
        base_info = os.lstat(str(base))
        if (
            _is_reparse_or_link(base_info)
            or not stat.S_ISDIR(base_info.st_mode)
            or base_info.st_uid != uid
            or stat.S_IMODE(base_info.st_mode) & 0o022
        ):
            _reject("account_probe_lock_unavailable")
    return base / _LOCK_DIRECTORY_NAME


def _windows_local_app_data() -> Path:
    """Read LocalAppData through Windows known-folder APIs, not environment."""

    import ctypes
    from ctypes import wintypes

    class _Guid(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    # FOLDERID_LocalAppData = {F1B32785-6FBA-4FCF-9D55-7B8E7F157091}
    folder_id = _Guid(
        0xF1B32785,
        0x6FBA,
        0x4FCF,
        (ctypes.c_ubyte * 8)(0x9D, 0x55, 0x7B, 0x8E, 0x7F, 0x15, 0x70, 0x91),
    )
    result = ctypes.c_wchar_p()
    shell32 = ctypes.windll.shell32
    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_Guid),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    hr = shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(result))
    try:
        if hr != 0 or not result.value:
            _reject("account_probe_lock_unavailable")
        return Path(result.value)
    finally:
        if result:
            ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(result, ctypes.c_void_p))


def _validated_admission(value: Any) -> CtpSandboxReadOnlyRegistration:
    """Revalidate the selected admission without deriving a route by profile.

    The composition root verifies that this exact TD/MD pair belongs to the
    sealed config's candidate set before calling the market probe. This
    adapter preserves the pair verbatim and does not select or normalize it.
    """

    if type(value) is not CtpSandboxReadOnlyRegistration:
        _reject("admission_required")
    try:
        admission = CtpSandboxReadOnlyRegistration(
            runtime_registration=value.runtime_registration,
            environment=value.environment,
            sdk_profile=value.sdk_profile,
            account_fingerprint_sha256=value.account_fingerprint_sha256,
            allowed_secrets_ref=value.allowed_secrets_ref,
            instrument_id=value.instrument_id,
            exchange_id=value.exchange_id,
            hedge_flag=value.hedge_flag,
            td_front=value.td_front,
            md_front=value.md_front,
            session_ttl_seconds=value.session_ttl_seconds,
        )
    except Exception:
        _reject("admission_invalid")
    # Rebuild above validates the complete configured pair but intentionally
    # does not canonicalize, remap, or replace either endpoint.
    if admission.md_front != value.md_front or admission.instrument_id != value.instrument_id:
        _reject("admission_invalid")
    return admission


def _timeout(value: Any, *, allow_zero: bool = False) -> float:
    if type(value) not in (int, float):
        _reject("invalid_timeout")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        _reject("invalid_timeout")
    minimum_ok = normalized >= 0.0 if allow_zero else normalized > 0.0
    if not math.isfinite(normalized) or not minimum_ok or normalized > _MAX_TIMEOUT_SECONDS:
        _reject("invalid_timeout")
    return normalized


def _read_credential(source: CtpMarketCredentialSource, name: str) -> str:
    try:
        value = source.require_credential(name)
    except Exception:
        _reject("credential_unavailable")
    if type(value) is not str or not value or value != value.strip():
        _reject("credential_invalid")
    return value


def _account_lock_key(account_fingerprint_sha256: str) -> str:
    return hashlib.sha256(
        ("ctp-md-probe-v1:" + account_fingerprint_sha256).encode("ascii")
    ).hexdigest()


def _md_client_snapshot(client: Any) -> tuple[Any, ...] | None:
    """Read the SDK's mutable MD binding/readiness under its state lock.

    The pinned ``MdClient`` has no public readiness snapshot, so the probe
    reads the small set of fields maintained by its SPI while holding the
    SDK's reentrant state lock. A changed or unrecognized client shape fails
    closed rather than producing a login observation from stale callback
    state.
    """

    try:
        state_lock = getattr(client, "_state_lock")
        with state_lock:
            front = getattr(client, "front")
            broker_id = getattr(client, "broker_id")
            user_id = getattr(client, "user_id")
            generation = getattr(client, "connection_generation")
            connected = getattr(client, "_connected")
            logged_in = getattr(client, "_loggedin")
    except Exception:
        return None
    if (
        type(front) is not str
        or type(broker_id) is not str
        or type(user_id) is not str
        or type(generation) is not int
        or generation < 0
        or type(connected) is not bool
        or type(logged_in) is not bool
    ):
        return None
    return (front, broker_id, user_id, generation, connected, logged_in)


def _client_state_error(
    snapshot: tuple[Any, ...] | None,
    *,
    front: str,
    broker_id: str,
    user_id: str,
) -> str | None:
    if snapshot is None:
        return "market_session_state_unavailable"
    current_front, current_broker, current_user, generation, connected, logged_in = snapshot
    if current_front != front:
        return "market_front_binding_mismatch"
    if current_broker != broker_id or current_user != user_id:
        return "market_client_identity_mismatch"
    if generation < 1 or connected is not True or logged_in is not True:
        return "market_session_not_ready"
    return None


class _AccountLease:
    """Process and OS-level exclusive lease for one CTP MD flow directory."""

    def __init__(self, account_key: str) -> None:
        self.account_key = account_key
        with _PROCESS_LOCKS_GUARD:
            self._thread_lock = _PROCESS_LOCKS.setdefault(account_key, threading.Lock())
        self._fd: int | None = None
        self._released = False
        self._release_guard = threading.Lock()

    def acquire(self) -> None:
        if not self._thread_lock.acquire(blocking=False):
            _reject("account_probe_busy")
        try:
            root = _account_lock_root()
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            root_info = os.lstat(str(root))
            if _is_reparse_or_link(root_info) or not stat.S_ISDIR(root_info.st_mode):
                _reject("account_probe_lock_unavailable")
            if os.name != "nt":
                if root_info.st_uid != os.getuid() or stat.S_IMODE(root_info.st_mode) & 0o077:
                    _reject("account_probe_lock_unavailable")

            lock_path = root / (self.account_key + ".lock")
            try:
                path_info = os.lstat(str(lock_path))
            except FileNotFoundError:
                path_info = None
            if path_info is not None and (
                _is_reparse_or_link(path_info) or not stat.S_ISREG(path_info.st_mode)
            ):
                _reject("account_probe_lock_unavailable")
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(str(lock_path), flags, 0o600)
            try:
                opened_info = os.fstat(fd)
                current_info = os.lstat(str(lock_path))
                if (
                    _is_reparse_or_link(current_info)
                    or not stat.S_ISREG(opened_info.st_mode)
                    or not _same_file_identity(opened_info, current_info)
                ):
                    _reject("account_probe_lock_unavailable")
                if os.name != "nt" and (
                    opened_info.st_uid != os.getuid() or stat.S_IMODE(opened_info.st_mode) & 0o077
                ):
                    _reject("account_probe_lock_unavailable")
                if os.name == "nt":
                    if opened_info.st_size == 0:
                        os.write(fd, b"\0")
                    os.lseek(fd, 0, os.SEEK_SET)
                    import msvcrt

                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except CtpSdkMarketReadOnlyError:
                os.close(fd)
                raise
            except (OSError, ImportError):
                os.close(fd)
                _reject("account_probe_busy")
            self._fd = fd
        except CtpSdkMarketReadOnlyError:
            self._thread_lock.release()
            raise
        except Exception:
            self._thread_lock.release()
            _reject("account_probe_lock_unavailable")

    def release(self) -> None:
        with self._release_guard:
            if self._released:
                return
            self._released = True
            fd = self._fd
            self._fd = None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        self._thread_lock.release()


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _is_reparse_or_link(value: os.stat_result) -> bool:
    if stat.S_ISLNK(value.st_mode):
        return True
    attributes = getattr(value, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse)


def _hold_lease_unknown(lease: _AccountLease, client: Any, join_thread: Any) -> None:
    """Pin the client and account lease until process exit if stop is uncertified."""

    with _PENDING_LEASES_GUARD:
        _PENDING_LEASES[lease.account_key] = (lease, client, join_thread)


def _native_stop_receipt_type() -> type[Any]:
    """Load the SDK's public shutdown receipt only for clients that expose it."""

    from bt_api_ctp.ctp.client import CtpNativeStopReceipt

    return CtpNativeStopReceipt


def _validated_native_stop_receipt(
    receipt: Any,
    *,
    expected_generation: int | None,
) -> tuple[bool, bool | None] | None:
    """Return ``(complete, thread_alive)`` for an exact, coherent SDK receipt.

    Unknown receipt types and malformed or contradictory field combinations
    cannot release the account lease.  Keep this import lazy so the legacy
    source/editable SDK and offline fake clients remain usable.
    """

    try:
        receipt_type = _native_stop_receipt_type()
    except Exception:
        return None
    if type(receipt) is not receipt_type:
        return None
    try:
        generation = receipt.connection_generation
        join_required = receipt.join_required
        join_completed = receipt.join_completed
        native_released = receipt.native_released
        thread_alive = receipt.thread_alive
        timed_out = receipt.timed_out
        complete = receipt.complete
    except Exception:
        return None
    if (
        type(generation) is not int
        or generation < 0
        or type(expected_generation) is not int
        or generation != expected_generation
        or type(join_required) is not bool
        or type(join_completed) is not bool
        or type(native_released) is not bool
        or (thread_alive is not None and type(thread_alive) is not bool)
        or type(timed_out) is not bool
        or type(complete) is not bool
    ):
        return None
    if join_completed and thread_alive is not False:
        return None
    derived_complete = (
        native_released and (not join_required or join_completed) and thread_alive is False
    )
    if complete is not derived_complete or (timed_out and complete):
        return None
    return complete, thread_alive


def _error_id(response: Any) -> int:
    if response is None:
        return 0
    try:
        return int(getattr(response, "ErrorID", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return -1


def _instrument_text(response: Any) -> str:
    if response is None:
        return ""
    try:
        value = getattr(response, "InstrumentID", "")
    except Exception:
        return ""
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return ""
    if type(value) is not str:
        return ""
    # Native fixed-width C fields may expose right padding; the configured
    # instrument itself has already passed the strict admission validator.
    return value.rstrip("\x00 ")


def _field_text(response: Any, name: str) -> str:
    try:
        value = getattr(response, name, "")
    except Exception:
        return ""
    if isinstance(value, bytes):
        try:
            value = value.decode("ascii")
        except UnicodeDecodeError:
            return ""
    if type(value) is not str:
        return ""
    return value.rstrip("\x00 ")


def _valid_tick(tick: Any, instrument: str, exchange: str) -> bool:
    if _instrument_text(tick) != instrument or _field_text(tick, "ExchangeID") != exchange:
        return False
    try:
        last_price = getattr(tick, "LastPrice", None)
        volume = getattr(tick, "Volume", None)
    except Exception:
        return False
    if type(last_price) not in (int, float) or type(volume) is not int or volume < 0:
        return False
    try:
        return math.isfinite(float(last_price)) and last_price > 0
    except (OverflowError, TypeError, ValueError):
        return False


def _probe_ctp_market_readonly(
    *,
    admission: CtpSandboxReadOnlyRegistration,
    credential_source: CtpMarketCredentialSource,
    client_type: Any,
    timeout_seconds: float = 15.0,
    tick_observation_seconds: float = 0.0,
) -> CtpSdkMarketReadOnlyObservation:
    """Verify one admitted CTP market route with an injected client type.

    ``timeout_seconds`` is one monotonic deadline for login, subscription ack,
    and any optional tick observation.  A missing tick never causes address
    selection or failure after login and subscription have succeeded.

    This private helper has no default SDK import or route of its own.  Its
    reviewed composition must inject the real ``MdClient`` only after sealed
    registry/config, artifact provenance, and credential gates pass.  Offline
    callers inject a fake.  The account lease serializes cooperating
    invocations of this helper only.  Call it in an isolated preflight process
    while no legacy or application-owned market-data session for this account
    is active.
    """

    admitted = _validated_admission(admission)
    if not callable(client_type):
        _reject("market_client_type_required")
    timeout = _timeout(timeout_seconds)
    tick_window = _timeout(tick_observation_seconds, allow_zero=True)
    if tick_window > timeout:
        _reject("invalid_timeout")

    front = admitted.md_front
    instrument = admitted.instrument_id
    exchange = admitted.exchange_id
    deadline = time.monotonic() + timeout
    lease = _AccountLease(_account_lock_key(admitted.account_fingerprint_sha256))
    lease.acquire()

    client = None
    client_started = False
    close_state = "not_started"
    client_stop_returned = False
    stop_failed = False
    primary_error: str | None = None
    observation: CtpSdkMarketReadOnlyObservation | None = None
    join_thread = None
    condition: threading.Condition | None = None
    state: dict[str, Any] | None = None
    initial_generation: int | None = None
    front_callback_observed: bool | None = None
    login_callback_diagnostic: tuple[int, str, str | None, str | None] | None = None
    try:
        broker_id = _read_credential(credential_source, "broker_id")
        user_id = _read_credential(credential_source, "user_id")
        password = _read_credential(credential_source, "password")
        account_digest = hashlib.sha256(
            "{0}:{1}".format(broker_id, user_id).encode("utf-8")
        ).hexdigest()
        if not hmac.compare_digest(account_digest, admitted.account_fingerprint_sha256):
            _reject("credential_account_mismatch")
        if time.monotonic() >= deadline:
            _reject("probe_deadline_expired")

        # Pass the exact immutable admission string.  Do not call a profile map,
        # normalize the URL, probe alternatives, or fall back to environment.
        client = client_type(front, broker_id, user_id, password)
        initial_snapshot = _md_client_snapshot(client)
        if initial_snapshot is None:
            _reject("market_client_state_unavailable")
        if initial_snapshot[0] != front:
            _reject("market_front_binding_mismatch")
        if initial_snapshot[1] != broker_id or initial_snapshot[2] != user_id:
            _reject("market_client_identity_mismatch")
        initial_generation = initial_snapshot[3]
        condition = threading.Condition()
        state = {
            "closed": False,
            "error": None,
            "login": False,
            "login_generation": None,
            "subscription_ack": False,
            "subscription_generation": None,
            "tick_observation_deadline": None,
            "tick_observation_count": 0,
            "tick_binding": None,
        }

        def record_error(reason: str) -> None:
            with condition:
                if not state["closed"] and state["error"] is None:
                    state["error"] = reason
                    condition.notify_all()

        def on_login(login_field: Any) -> None:
            snapshot = _md_client_snapshot(client)
            session_error = _client_state_error(
                snapshot,
                front=front,
                broker_id=broker_id,
                user_id=user_id,
            )
            if session_error is not None:
                record_error(session_error)
                return
            try:
                login_broker_id = getattr(login_field, "BrokerID")
                login_user_id = getattr(login_field, "UserID")
            except Exception:
                record_error("market_login_identity_unavailable")
                return
            if type(login_broker_id) is not str or type(login_user_id) is not str:
                record_error("market_login_identity_unavailable")
                return
            if login_broker_id != broker_id or login_user_id != user_id:
                record_error("market_login_identity_mismatch")
                return
            assert snapshot is not None
            with condition:
                if not state["closed"] and state["error"] is None:
                    state["login"] = True
                    state["login_generation"] = snapshot[3]
                    condition.notify_all()

        def on_error(response: Any) -> None:
            error_id = _error_id(response)
            if error_id != 0:
                record_error("market_front_rejected")
                return
            # The pinned MD client can report a login identity mismatch via
            # on_error with the original zero-error response.  A callback in
            # either pending phase is still a rejection signal; do not let an
            # ErrorID of zero turn it into a successful readiness observation.
            with condition:
                if state["closed"] or state["error"] is not None:
                    return
                if state["login"] and state["subscription_ack"]:
                    return
                reason = (
                    "market_login_identity_mismatch"
                    if not state["login"]
                    else "market_subscription_rejected"
                )
                state["error"] = reason
                condition.notify_all()

        def on_disconnect(_reason: Any) -> None:
            with condition:
                if not state["closed"]:
                    state["error"] = state["error"] or "market_front_disconnected"
                    condition.notify_all()

        def on_subscribe(specific_instrument: Any, response: Any) -> None:
            if _instrument_text(specific_instrument) != instrument:
                return
            if _error_id(response) != 0:
                record_error("market_subscription_rejected")
                return
            snapshot = _md_client_snapshot(client)
            session_error = _client_state_error(
                snapshot,
                front=front,
                broker_id=broker_id,
                user_id=user_id,
            )
            if session_error is not None:
                record_error(session_error)
                return
            assert snapshot is not None
            with condition:
                if state["closed"] or state["error"] is not None:
                    return
                login_generation = state["login_generation"]
                if login_generation is None or snapshot[3] != login_generation:
                    state["error"] = "market_connection_generation_changed"
                    condition.notify_all()
                    return
                if not state["closed"]:
                    if not state["subscription_ack"]:
                        state["subscription_ack"] = True
                        state["subscription_generation"] = snapshot[3]
                        if tick_window > 0.0:
                            state["tick_observation_deadline"] = min(
                                deadline, time.monotonic() + tick_window
                            )
                    condition.notify_all()

        def on_tick(tick: Any) -> None:
            if tick_window <= 0.0:
                return
            if not _valid_tick(tick, instrument, exchange):
                return
            snapshot = _md_client_snapshot(client)
            session_error = _client_state_error(
                snapshot,
                front=front,
                broker_id=broker_id,
                user_id=user_id,
            )
            if session_error is not None:
                record_error(session_error)
                return
            assert snapshot is not None
            with condition:
                if state["closed"] or state["error"] is not None:
                    return
                login_generation = state["login_generation"]
                subscription_generation = state["subscription_generation"]
                tick_deadline = state["tick_observation_deadline"]
                if not state["subscription_ack"] or tick_deadline is None:
                    # Depth callbacks can race a subscription response. Such
                    # a tick is not evidence that the acknowledged scope was
                    # observed, so wait for a later post-ACK callback.
                    return
                if (
                    login_generation is None
                    or subscription_generation != login_generation
                    or snapshot[3] != login_generation
                ):
                    state["error"] = "market_connection_generation_changed"
                    condition.notify_all()
                    return
                if time.monotonic() > tick_deadline:
                    return
                state["tick_observation_count"] += 1
                if state["tick_binding"] is None:
                    state["tick_binding"] = CtpSdkMarketTickBinding(
                        account_fingerprint_sha256=admitted.account_fingerprint_sha256,
                        md_front_sha256=hashlib.sha256(front.encode("utf-8")).hexdigest(),
                        instrument_id=instrument,
                        exchange_id=exchange,
                        connection_generation=snapshot[3],
                    )
                condition.notify_all()

        client.on_login = on_login
        client.on_error = on_error
        client.on_disconnect = on_disconnect
        client.on_subscribe = on_subscribe
        client.on_tick = on_tick

        # MdClient defers this single request until its login response.
        client.subscribe([instrument])
        client.start(block=False)
        client_started = True

        with condition:
            # ``start`` is expected to return promptly, but it is a synchronous
            # SDK call.  Do not accept callbacks that only became visible
            # after the single monotonic deadline elapsed while that call was
            # in progress.
            if time.monotonic() >= deadline:
                _reject("probe_deadline_expired")
            while not (state["login"] and state["subscription_ack"]):
                if state["error"]:
                    _reject(state["error"])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = (
                        "market_login_timeout" if not state["login"] else "subscription_ack_timeout"
                    )
                    _reject(reason)
                condition.wait(remaining)

            tick_deadline = state["tick_observation_deadline"]
            while tick_deadline is not None:
                if state["error"]:
                    _reject(state["error"])
                remaining = tick_deadline - time.monotonic()
                if remaining <= 0:
                    break
                condition.wait(remaining)

            if state["error"]:
                _reject(state["error"])
            snapshot = _md_client_snapshot(client)
            session_error = _client_state_error(
                snapshot,
                front=front,
                broker_id=broker_id,
                user_id=user_id,
            )
            if session_error is not None:
                _reject(session_error)
            assert snapshot is not None
            login_generation = state["login_generation"]
            subscription_generation = state["subscription_generation"]
            if (
                login_generation is None
                or subscription_generation != login_generation
                or snapshot[3] != login_generation
            ):
                _reject("market_connection_generation_changed")
            observation = CtpSdkMarketReadOnlyObservation(
                md_front_sha256=hashlib.sha256(front.encode("utf-8")).hexdigest(),
                account_fingerprint_sha256=admitted.account_fingerprint_sha256,
                instrument_id=instrument,
                exchange_id=exchange,
                market_login_ready=True,
                subscription_acknowledged=True,
                tick_observation_count=state["tick_observation_count"],
                tick_binding=state["tick_binding"],
                connection_generation=snapshot[3],
                client_stop_returned=False,
                native_join_pending=False,
            )
            # Define the observation point while callbacks are excluded; a
            # later teardown callback cannot retroactively make a stale
            # generation look ready.
            state["closed"] = True
    except CtpSdkMarketReadOnlyError as exc:
        primary_error = exc.reason
    except Exception:
        # Never include provider exceptions: native bindings can embed account,
        # front, or credential data in their messages.
        primary_error = "market_probe_failed"
    finally:
        if client is not None:
            final_snapshot = _md_client_snapshot(client)
            if final_snapshot is not None and initial_generation is not None:
                front_callback_observed = final_snapshot[3] > initial_generation
            # Read before stop resets SDK state or a late teardown callback.
            login_callback_diagnostic = _md_login_callback_diagnostic(client)
            try:
                join_thread = getattr(client, "_thread", None)
            except Exception:
                join_thread = None
            stop_and_wait = None
            stop_receipt_method_unknown = False
            try:
                stop_and_wait = getattr(client, "stop_and_wait", None)
            except Exception:
                stop_receipt_method_unknown = True

            stop_receipt_state: tuple[bool, bool | None] | None = None
            try:
                if condition is not None and state is not None:
                    with condition:
                        state["closed"] = True
                if stop_receipt_method_unknown:
                    stop_failed = True
                    close_state = "native_stop_method_unknown"
                elif stop_and_wait is not None:
                    if not callable(stop_and_wait):
                        stop_failed = True
                        close_state = "native_stop_method_invalid"
                    else:
                        # The public method calls stop internally.  Do not call
                        # stop a second time or infer completion from a return
                        # that lacks its exact public receipt.
                        pre_stop_snapshot = _md_client_snapshot(client)
                        # Teardown needs its own bounded grace after a probe
                        # timeout. A spent login deadline must not turn the
                        # native Join observation into a zero-second poll.
                        join_wait = _MAX_NATIVE_JOIN_WAIT_SECONDS
                        receipt = stop_and_wait(timeout=join_wait)
                        client_stop_returned = True
                        close_state = "stop_returned"
                        stop_receipt_state = _validated_native_stop_receipt(
                            receipt,
                            expected_generation=(
                                None if pre_stop_snapshot is None else pre_stop_snapshot[3]
                            ),
                        )
                        if stop_receipt_state is None:
                            stop_failed = True
                            close_state = "native_stop_receipt_unknown"
                else:
                    # A stop() return and captured Join thread cannot certify
                    # native Release. Without an exact public receipt, retain
                    # the lease through process exit.
                    client.stop()
                    client_stop_returned = True
                    stop_failed = True
                    close_state = "native_stop_receipt_unknown"
            except Exception:
                close_state = "stop_failed"
                stop_failed = True

            if stop_receipt_state is not None:
                receipt_complete, receipt_thread_alive = stop_receipt_state
                if receipt_complete:
                    close_state = "stop_returned"
                    lease.release()
                elif receipt_thread_alive is True and join_thread is not None:
                    # The public receipt confirms Join remains live.  Keep the
                    # client and lease pinned until that exact SDK thread exits.
                    try:
                        thread_alive = join_thread.is_alive()
                    except Exception:
                        thread_alive = None
                    if thread_alive is True:
                        stop_failed = True
                        close_state = "native_join_pending"
                        _hold_lease_unknown(lease, client, join_thread)
                    else:
                        stop_failed = True
                        close_state = "native_stop_receipt_inconsistent"
                        _hold_lease_unknown(lease, client, join_thread)
                else:
                    # A dead/missing thread does not prove Release + Join when
                    # the receipt itself is incomplete or says liveness is
                    # unknown.  Do not release the account lease.
                    stop_failed = True
                    close_state = (
                        "native_join_pending"
                        if receipt_thread_alive is True
                        else "native_stop_incomplete"
                    )
                    _hold_lease_unknown(lease, client, join_thread)
            else:
                pending = False
                if join_thread is not None:
                    try:
                        join_remaining = _MAX_NATIVE_JOIN_WAIT_SECONDS
                        # Legacy stop() can return before its native Join
                        # observer exits.  Give it a bounded opportunity to
                        # finish and keep the lease while it remains pending.
                        join_thread.join(join_remaining)
                        pending = bool(join_thread.is_alive())
                    except Exception:
                        pending = True
                try:
                    join_tracking_unknown = client_started and not hasattr(client, "_thread")
                except Exception:
                    join_tracking_unknown = True
                if pending:
                    close_state = "native_join_pending"
                    _hold_lease_unknown(lease, client, join_thread)
                elif join_tracking_unknown:
                    close_state = "native_join_state_unknown"
                    _hold_lease_unknown(lease, client, join_thread)
                elif stop_failed:
                    # Keep the client and lock alive indefinitely when shutdown
                    # is uncertain; another same-account MD API must fail closed.
                    _hold_lease_unknown(lease, client, join_thread)
                else:
                    lease.release()
        else:
            lease.release()

    if stop_failed:
        _reject(
            "market_client_stop_failed",
            close_state=close_state,
            primary_reason=primary_error,
            front_callback_observed=front_callback_observed,
            login_callback_count=(
                None if login_callback_diagnostic is None else login_callback_diagnostic[0]
            ),
            login_callback_disposition=(
                None if login_callback_diagnostic is None else login_callback_diagnostic[1]
            ),
            login_request_id_relation=(
                None if login_callback_diagnostic is None else login_callback_diagnostic[2]
            ),
            login_response_error_status=(
                None if login_callback_diagnostic is None else login_callback_diagnostic[3]
            ),
            native_broker_id_shape=(
                None if login_callback_diagnostic is None else login_callback_diagnostic[4]
            ),
            native_user_id_shape=(
                None if login_callback_diagnostic is None else login_callback_diagnostic[5]
            ),
            client_stop_returned=client_stop_returned,
        )
    if primary_error is not None:
        _reject(
            primary_error,
            close_state=close_state,
            front_callback_observed=front_callback_observed,
            login_callback_count=(
                None if login_callback_diagnostic is None else login_callback_diagnostic[0]
            ),
            login_callback_disposition=(
                None if login_callback_diagnostic is None else login_callback_diagnostic[1]
            ),
            login_request_id_relation=(
                None if login_callback_diagnostic is None else login_callback_diagnostic[2]
            ),
            login_response_error_status=(
                None if login_callback_diagnostic is None else login_callback_diagnostic[3]
            ),
            native_broker_id_shape=(
                None if login_callback_diagnostic is None else login_callback_diagnostic[4]
            ),
            native_user_id_shape=(
                None if login_callback_diagnostic is None else login_callback_diagnostic[5]
            ),
            client_stop_returned=client_stop_returned,
        )
    assert observation is not None
    return CtpSdkMarketReadOnlyObservation(
        md_front_sha256=observation.md_front_sha256,
        account_fingerprint_sha256=observation.account_fingerprint_sha256,
        instrument_id=observation.instrument_id,
        exchange_id=observation.exchange_id,
        market_login_ready=observation.market_login_ready,
        subscription_acknowledged=observation.subscription_acknowledged,
        tick_observation_count=observation.tick_observation_count,
        tick_binding=observation.tick_binding,
        connection_generation=observation.connection_generation,
        client_stop_returned=client_stop_returned,
        native_join_pending=close_state == "native_join_pending",
    )


__all__ = [
    "CtpSdkMarketReadOnlyError",
    "CtpSdkMarketReadOnlyObservation",
    "CtpSdkMarketTickBinding",
]
