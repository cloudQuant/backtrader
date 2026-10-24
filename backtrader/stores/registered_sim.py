"""Opt-in registered-simulation adapter for direct CTP sessions.

This module keeps the ordinary :class:`BtApiStore` CTP route closed.  A
``RegisteredSimStore`` can open a short, instrument-scoped dispatch window only
after the CTP SDK returns its native registered-simulation capability.  The
SDK wrapper is composed lazily when the Store first creates its API client;
importing Backtrader or this module does not import a provider package.

The default ``allow_writes=False`` is a permanent shadow-mode switch for this
Store instance.  Setting it to ``True`` only enables the explicit admission
methods: it does not create or replace the SDK capability.  An ambiguous
native outcome freezes the wrapper and Store.  This version intentionally has
no unfreeze operation; only a future, separately proven reconciliation path
may reopen the native gate.

This module is the framework-owned adapter for the new opt-in route. The six
existing ``simnow_direct.py`` example copies keep their example-local classes
and behavior in this round; they are not imports or runtime dependencies of
this module.
"""

from __future__ import annotations

import collections
import copy
import math
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from .btapistore import BtApiStore, BtApiStoreError

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_REGISTERED_SIM_TICK_SOURCE = "ctp-native-live"
_QUERY_METHODS = {
    "account_result": "query_account_result",
    "positions_result": "query_positions_result",
    "orders_result": "query_orders_result",
    "trades_result": "query_trades_result",
    "instruments_result": "query_instruments_result",
    "instrument_margin_rate_result": "query_instrument_margin_rate_result",
    "instrument_commission_rate_result": "query_instrument_commission_rate_result",
}
_QUERY_REQUEST_TYPES = {
    "account_result": "account",
    "positions_result": "positions",
    "orders_result": "orders",
    "trades_result": "trades",
    "instruments_result": "instruments",
    "instrument_margin_rate_result": "margin_rate",
    "instrument_commission_rate_result": "commission_rate",
}
_REQUIRED_QUERY_FAMILIES = frozenset(
    {"account_result", "positions_result", "orders_result", "trades_result"}
)
_TERMINAL_ORDER_STATUSES = frozenset({"0", "4", "5", "a"})
_UNOBSERVED = object()
_QUERY_SNAPSHOT_LIMIT = 512


class RegisteredSimExecutionUnknown(BtApiStoreError):
    """A native insert/cancel may have reached CTP and must not be retried."""

    execution_unknown = True

    def __init__(self, evidence: "RegisteredSimDispatchEvidence") -> None:
        self.evidence = evidence
        operation = evidence.operation.lower()
        self.code = "registered_sim_{}_unknown".format(operation)
        super().__init__(
            "registered-sim {} outcome is unknown; native gate frozen".format(operation)
        )


@dataclass(frozen=True)
class RegisteredSimDispatchEvidence:
    """One native dispatch result; diagnostic only and never a retry command.

    ``status`` is ``KNOWN`` only when the SDK method returned its documented
    integer success code (zero). Any exception or other return is ``UNKNOWN``.
    The Store never automatically resends a native method, including when the
    outcome is UNKNOWN. UNKNOWN evidence is retained until the process ends.
    """

    sequence: int
    operation: str
    status: str
    request_id: int
    instrument_id: str
    exchange_id: str
    order_ref: Optional[str]
    order_sys_id: Optional[str]
    front_id: Optional[int]
    session_id: Optional[int]
    broker_id: Optional[str]
    investor_id: Optional[str]
    user_id: Optional[str]
    native_return_code: Optional[int]
    error_type: Optional[str]
    observed_at_utc: str

    @property
    def resend_permitted(self) -> bool:
        """Native requests are never automatically safe to replay."""
        return False


@dataclass(frozen=True)
class RegisteredSimRouteEligibility:
    """Read-only route facts; these fields do not grant native permission.

    Unknown order IDs describe only this wrapper's observed in-process
    dispatches. They do not claim a complete account reconciliation; callers
    must separately require the source-owned full-scope query facts.
    """

    route_name: str
    instrument_id: str
    exchange_id: str
    account_fingerprint: Optional[str]
    connection_generation: Optional[int]
    trading_day: Optional[str]
    allow_writes: bool
    frozen: bool
    sdk_frozen: Optional[bool]
    unknown_order_ids: Optional[Tuple[str, ...]]
    unknown_order_count: Optional[int]
    dispatching_order_ids: Optional[Tuple[str, ...]]
    capability_observed: bool
    sdk_capability_managed: Optional[bool]
    sdk_capability_armed: Optional[bool]
    sdk_capability_instrument: Optional[str]
    sdk_authorized_instruments: Optional[Tuple[str, ...]]
    capability_matches_route: Optional[bool]
    instrument_query_complete: bool
    instrument_eligible: Optional[bool]
    reason_codes: Tuple[str, ...]
    native_admission_required: bool = True


def _exact_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("{} must be non-empty exact text".format(field))
    return value


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _read_fact(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _query_error_is_clear(value: Any) -> bool:
    if value is None:
        return True
    if type(value) is int:
        return value == 0
    return type(value) is str and value in ("", "0")


def _is_aware_datetime(value: Any) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _freeze_query_filter(value: Any) -> Any:
    """Build a type-sensitive, immutable key for public query kwargs."""
    value_type = type(value)
    if value is None or value_type in (str, bool, int):
        return (value_type.__name__, value)
    if value_type is float:
        if not math.isfinite(value):
            raise ValueError("query filters must not contain non-finite floats")
        return ("float", value)
    if value_type in (tuple, list):
        return (value_type.__name__, tuple(_freeze_query_filter(item) for item in value))
    if isinstance(value, Mapping):
        items = []
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("query filter mapping keys must be exact strings")
            items.append((key, _freeze_query_filter(item)))
        return ("mapping", tuple(sorted(items)))
    raise TypeError("query filters must contain only immutable public values")


def _query_snapshot_key(family: str, filters: Mapping) -> Tuple[Any, ...]:
    return (
        family,
        tuple(
            (key, _freeze_query_filter(value))
            for key, value in sorted(filters.items())
            if type(key) is str
        ),
    )


def _public_query_snapshot(facts: Mapping) -> Dict[str, Any]:
    """Return detached query facts without the opaque source-issuer token."""
    return {
        key: copy.deepcopy(value)
        for key, value in facts.items()
        if isinstance(key, str) and not key.startswith("_")
    }


def _instrument_is_trading(row: Mapping) -> Optional[bool]:
    raw = row.get("IsTrading", row.get("is_trading"))
    if raw is True or type(raw) is int and raw == 1:
        return True
    if type(raw) is str and raw.strip().lower() in {"1", "true", "yes"}:
        return True
    if raw is False or type(raw) is int and raw == 0:
        return False
    if type(raw) is str and raw.strip().lower() in {"0", "false", "no"}:
        return False
    return None


def _instrument_eligibility_from_rows(
    rows: Any, instrument_id: str, exchange_id: str
) -> Optional[bool]:
    """Project one exact route from a complete, well-shaped instrument set."""
    if not isinstance(rows, list):
        return None
    matching = []
    for row in rows:
        if not isinstance(row, Mapping):
            return None
        instrument = row.get("InstrumentID", row.get("instrument_id"))
        exchange = row.get("ExchangeID", row.get("exchange_id"))
        trading = _instrument_is_trading(row)
        if (
            not isinstance(instrument, str)
            or not instrument
            or not isinstance(exchange, str)
            or not exchange
            or trading is None
        ):
            return None
        if instrument == instrument_id and exchange == exchange_id:
            matching.append(trading)
    if not matching:
        return False
    if any(value is not matching[0] for value in matching[1:]):
        return None
    return matching[0]


def _query_result_facts(
    result: Any, family: str, attempt: int, expected_scope: Any
) -> Dict[str, Any]:
    """Copy completion facts only from the current SDK's sealed query source."""
    records = _read_fact(result, "records")
    if records is None:
        records = _read_fact(result, "rows")
    public_rows = None
    if isinstance(records, (list, tuple)):
        public_rows = [BtApiStore._ctp_query_record_to_public(row) for row in records]
    source = _read_fact(result, "query_source")
    expected_issuer = _read_fact(expected_scope, "issuer")
    error_code = _read_fact(result, "error_code", _UNOBSERVED)
    error_message = _read_fact(result, "error_message", _UNOBSERVED)
    unsupported = _read_fact(result, "unsupported", _UNOBSERVED)
    late_callback_count = _read_fact(result, "late_callback_count", _UNOBSERVED)
    submit_code = _read_fact(result, "submit_code", _UNOBSERVED)
    started_at = _read_fact(result, "started_at_utc", _UNOBSERVED)
    request_type = _read_fact(result, "request_type")
    facts = {
        "family": family,
        "request_type": request_type,
        "expected_request_type": _QUERY_REQUEST_TYPES.get(family),
        "rows": public_rows,
        "complete": _read_fact(result, "complete"),
        "is_last_seen": _read_fact(result, "is_last_seen"),
        "timed_out": _read_fact(result, "timed_out"),
        "error_code": None if error_code is _UNOBSERVED else error_code,
        "error_code_observed": error_code is not _UNOBSERVED,
        "error_message": None if error_message is _UNOBSERVED else error_message,
        "unsupported": None if unsupported is _UNOBSERVED else unsupported,
        "late_callback_count": (
            None if late_callback_count is _UNOBSERVED else late_callback_count
        ),
        "submit_code": None if submit_code is _UNOBSERVED else submit_code,
        "submit_code_observed": submit_code is not _UNOBSERVED,
        "started_at_utc": None if started_at is _UNOBSERVED else started_at,
        "request_id": _read_fact(result, "request_id"),
        "connection_generation": _read_fact(result, "connection_generation"),
        "account_fingerprint": _read_fact(result, "account_fingerprint"),
        "completed_at_utc": _read_fact(result, "completed_at_utc"),
        "source_owned": False,
        "trading_day": None,
        "source_explicit_request_filters": None,
        "source_expires_monotonic": None,
        "source_started_monotonic": None,
        "source_completed_monotonic": None,
        "attempt": attempt,
    }
    completed_at = facts["completed_at_utc"]
    source_expiry = _read_fact(source, "trusted_expires_monotonic", _UNOBSERVED)
    source_filters = _read_fact(source, "explicit_request_filters", _UNOBSERVED)
    source_digest = _read_fact(source, "records_sha256", _UNOBSERVED)
    source_started = _read_fact(source, "started_at_utc", _UNOBSERVED)
    source_completed = _read_fact(source, "completed_at_utc", _UNOBSERVED)
    source_started_monotonic = _read_fact(source, "started_monotonic", _UNOBSERVED)
    source_completed_monotonic = _read_fact(source, "completed_monotonic", _UNOBSERVED)
    source_generation = _read_fact(source, "connection_generation", _UNOBSERVED)
    source_request_id = _read_fact(source, "request_id", _UNOBSERVED)
    source_account = _read_fact(source, "account_fingerprint", _UNOBSERVED)
    source_request_type = _read_fact(source, "request_type", _UNOBSERVED)
    source_trading_day = _read_fact(source, "trading_day", _UNOBSERVED)
    scope_generation = _read_fact(expected_scope, "connection_generation", _UNOBSERVED)
    scope_account = _read_fact(expected_scope, "account_fingerprint", _UNOBSERVED)
    scope_trading_day = _read_fact(expected_scope, "trading_day", _UNOBSERVED)
    monotonic_now = time.monotonic()
    source_owned = bool(
        source is not None
        and expected_scope is not None
        and _read_fact(expected_scope, "read_only_ready") is True
        and expected_issuer is not None
        and _read_fact(source, "issuer") is expected_issuer
        and source_request_type == facts["expected_request_type"]
        and source_request_id == facts["request_id"]
        and source_generation == facts["connection_generation"]
        and source_account == facts["account_fingerprint"]
        and source_started == facts["started_at_utc"]
        and source_completed == facts["completed_at_utc"]
        and isinstance(source_trading_day, str)
        and re.fullmatch(r"[0-9]{8}", source_trading_day) is not None
        and source_generation == scope_generation
        and source_account == scope_account
        and source_trading_day == scope_trading_day
        and _positive_int(scope_generation)
        and isinstance(scope_account, str)
        and bool(scope_account)
        and isinstance(scope_trading_day, str)
        and re.fullmatch(r"[0-9]{8}", scope_trading_day) is not None
        and _is_aware_datetime(source_started)
        and _is_aware_datetime(source_completed)
        and type(source_started_monotonic) in (int, float)
        and type(source_completed_monotonic) in (int, float)
        and math.isfinite(source_started_monotonic)
        and math.isfinite(source_completed_monotonic)
        and source_started_monotonic <= source_completed_monotonic <= monotonic_now
        and type(source_expiry) in (int, float)
        and math.isfinite(source_expiry)
        and monotonic_now < source_expiry
        and isinstance(source_filters, tuple)
        and all(type(name) is str for name in source_filters)
        and isinstance(source_digest, str)
        and _HASH_RE.fullmatch(source_digest) is not None
    )
    facts["source_owned"] = source_owned
    facts["trading_day"] = source_trading_day if source_owned else None
    facts["source_explicit_request_filters"] = source_filters if source_owned else None
    facts["source_expires_monotonic"] = source_expiry if source_owned else None
    facts["source_started_monotonic"] = source_started_monotonic if source_owned else None
    facts["source_completed_monotonic"] = source_completed_monotonic if source_owned else None
    facts["_source_issuer"] = expected_issuer if source_owned else None
    submit_code_clear = submit_code is None or (type(submit_code) is int and submit_code == 0)
    records_are_public = isinstance(public_rows, list) and all(
        isinstance(row, Mapping) and bool(row) for row in public_rows
    )
    facts["query_complete"] = bool(
        facts["complete"] is True
        and facts["is_last_seen"] is True
        and facts["timed_out"] is False
        and facts["error_code_observed"] is True
        and _query_error_is_clear(error_code)
        and type(facts["error_message"]) is str
        and facts["error_message"] == ""
        and facts["unsupported"] is False
        and type(facts["late_callback_count"]) is int
        and facts["late_callback_count"] == 0
        and facts["submit_code_observed"] is True
        and submit_code_clear
        and _positive_int(facts["request_id"])
        and _positive_int(facts["connection_generation"])
        and facts["request_type"] == facts["expected_request_type"]
        and isinstance(facts["account_fingerprint"], str)
        and bool(facts["account_fingerprint"])
        and _is_aware_datetime(facts["started_at_utc"])
        and _is_aware_datetime(completed_at)
        and facts["started_at_utc"] <= completed_at
        and source_owned
        and records_are_public
    )
    return facts


class RegisteredSimWrapper:
    """Mixin for the stock direct CTP client wrapper.

    The CTP base is supplied lazily by ``RegisteredSimStore``.  Keeping this
    class provider-neutral also makes the admission and locking contracts
    testable with fake SDK leaves.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        allow_writes = kwargs.pop("registered_sim_allow_writes", False)
        history_limit = kwargs.pop("registered_sim_history_limit", 64)
        terminal_limit = kwargs.pop("registered_sim_terminal_order_limit", 512)
        if type(allow_writes) is not bool:
            raise TypeError("registered_sim_allow_writes must be bool")
        if type(history_limit) is not int or history_limit <= 0:
            raise ValueError("registered_sim_history_limit must be a positive int")
        if type(terminal_limit) is not int or terminal_limit <= 0:
            raise ValueError("registered_sim_terminal_order_limit must be a positive int")
        super().__init__(*args, **kwargs)
        self._registered_sim_allow_writes = allow_writes
        self._registered_sim_lock = threading.RLock()
        self._registered_sim_observation_lock = threading.Lock()
        self._registered_sim_capability = None
        self._registered_sim_state: Dict[str, Any] = {}
        self._registered_sim_frozen = False
        self._registered_sim_freeze_reason = ""
        self._registered_sim_arm_templates: Dict[Tuple[str, str], Dict[str, str]] = {}
        self._registered_sim_armed_key: Optional[Tuple[str, str]] = None
        self._registered_sim_arm_history = collections.deque(maxlen=history_limit)
        self._registered_sim_dispatch_history = collections.deque(maxlen=history_limit)
        self._registered_sim_unknown_dispatch: Optional[RegisteredSimDispatchEvidence] = None
        self._registered_sim_dispatch_sequence = 0
        self._registered_sim_terminal_order_limit = terminal_limit
        self._order_state = collections.OrderedDict()
        self._dispatching_order_ids = set()

    @property
    def registered_sim_allow_writes(self) -> bool:
        """The immutable constructor-time shadow/write switch."""
        return self._registered_sim_allow_writes

    def configure_registered_sim_arm_templates(self, templates: Mapping) -> None:
        """Set exact ``(InstrumentID, ExchangeID)`` admission templates."""
        if not isinstance(templates, Mapping) or not templates:
            raise ValueError("registered-sim arm templates must be a non-empty mapping")
        prepared: Dict[Tuple[str, str], Dict[str, str]] = {}
        for raw_key, raw_value in templates.items():
            if not isinstance(raw_key, tuple) or len(raw_key) != 2:
                raise ValueError("each registered-sim arm key must be an instrument/exchange pair")
            if not isinstance(raw_value, Mapping):
                raise ValueError("each registered-sim arm template must be a mapping")
            instrument = _exact_text(raw_key[0], "InstrumentID")
            exchange = _exact_text(raw_key[1], "ExchangeID")
            template = {
                "md_front": _exact_text(raw_value.get("md_front"), "md_front"),
                "strategy_identity_sha256": _exact_text(
                    raw_value.get("strategy_identity_sha256"), "strategy_identity_sha256"
                ),
                "execution_cycle_id": _exact_text(
                    raw_value.get("execution_cycle_id"), "execution_cycle_id"
                ),
                "preflight_sha256": _exact_text(
                    raw_value.get("preflight_sha256"), "preflight_sha256"
                ),
            }
            if _HASH_RE.fullmatch(template["strategy_identity_sha256"]) is None:
                raise ValueError("strategy_identity_sha256 must be lowercase SHA-256")
            if _HASH_RE.fullmatch(template["preflight_sha256"]) is None:
                raise ValueError("preflight_sha256 must be lowercase SHA-256")
            prepared[(instrument, exchange)] = template
        with self._registered_sim_lock:
            self._require_armable_locked()
            if self._registered_sim_capability is not None:
                raise BtApiStoreError("disarm before changing registered-sim arm templates")
            self._registered_sim_arm_templates = prepared
            self._registered_sim_armed_key = None

    def _require_armable_locked(self) -> None:
        if not self._registered_sim_allow_writes:
            raise BtApiStoreError("registered-sim writes are disabled in shadow mode")
        if self._registered_sim_frozen:
            raise BtApiStoreError("registered-sim native gate is frozen")

    def _resolve_gate_exchange(self, instrument: Any, exchange_id: Any) -> str:
        """Resolve only the exact currently armed spelling when exchange is omitted.

        The stock CTP wrapper uses an upper-cased instrument lookup key. This
        route intentionally avoids that alias so case-sensitive SDK identity
        is preserved through the native admission check.
        """
        if exchange_id or not instrument:
            return exchange_id
        with self._registered_sim_lock:
            key = self._registered_sim_armed_key
            if key is not None and instrument == key[0]:
                return key[1]
        return ""

    def _arm_locked(
        self,
        instrument_id: str,
        exchange_id: str,
        *,
        md_front: str,
        strategy_identity_sha256: str,
        execution_cycle_id: str,
        preflight_sha256: str,
        switched: bool,
    ) -> Dict[str, Any]:
        self._require_armable_locked()
        client = getattr(self, "trader_client", None)
        if client is None or getattr(client, "is_ready", None) is not True:
            raise BtApiStoreError("CTP trader client is not ready")
        arm = getattr(client, "arm_execution_for_registered_sim", None)
        if not callable(arm):
            raise BtApiStoreError("SDK registered-simulation admission is unavailable")
        try:
            admitted = arm(
                instrument_id=instrument_id,
                exchange_id=exchange_id,
                md_front=md_front,
                strategy_identity_sha256=strategy_identity_sha256,
                execution_cycle_id=execution_cycle_id,
                preflight_sha256=preflight_sha256,
            )
        except Exception as exc:
            self._registered_sim_frozen = True
            self._registered_sim_freeze_reason = "native_admission_outcome_unknown"
            self._registered_sim_capability = None
            self._registered_sim_armed_key = None
            raise BtApiStoreError(
                "SDK registered-simulation admission failed ({})".format(type(exc).__name__)
            ) from None
        if not isinstance(admitted, tuple) or len(admitted) != 2 or admitted[0] is None:
            self._registered_sim_frozen = True
            self._registered_sim_freeze_reason = "native_admission_result_unobserved"
            self._registered_sim_capability = None
            self._registered_sim_armed_key = None
            raise BtApiStoreError("SDK registered-simulation admission returned no capability")
        capability, state = admitted
        if (
            not isinstance(state, Mapping)
            or state.get("managed") is not True
            or state.get("armed") is not True
        ):
            self._registered_sim_frozen = True
            self._registered_sim_freeze_reason = "native_admission_state_unobserved"
            self._registered_sim_capability = capability
            self._registered_sim_armed_key = (instrument_id, exchange_id)
            try:
                self._disarm_locked(self._registered_sim_freeze_reason)
            except Exception:
                pass
            raise BtApiStoreError("SDK registered-simulation admission state is not armed")
        key = (instrument_id, exchange_id)
        self._registered_sim_capability = capability
        self._registered_sim_armed_key = key
        self._registered_sim_state = dict(state) if isinstance(state, Mapping) else {}
        self._registered_sim_arm_history.append(
            {"instrument": instrument_id, "exchange": exchange_id, "at_epoch": time.time()}
        )
        return {
            "armed": True,
            "instrument": instrument_id,
            "exchange_id": exchange_id,
            "switched": switched,
            "state": dict(self._registered_sim_state),
        }

    def arm_registered_sim_execution(
        self,
        instrument_id: str,
        exchange_id: str = "",
        md_front: str = "",
        *,
        strategy_identity_sha256: str,
        execution_cycle_id: str,
        preflight_sha256: str,
    ) -> Dict[str, Any]:
        """Obtain the SDK's native capability for one exact instrument."""
        instrument_id = _exact_text(instrument_id, "InstrumentID")
        exchange_id = _exact_text(exchange_id, "ExchangeID")
        md_front = _exact_text(md_front, "md_front")
        strategy_identity_sha256 = _exact_text(strategy_identity_sha256, "strategy_identity_sha256")
        execution_cycle_id = _exact_text(execution_cycle_id, "execution_cycle_id")
        preflight_sha256 = _exact_text(preflight_sha256, "preflight_sha256")
        if _HASH_RE.fullmatch(strategy_identity_sha256) is None:
            raise ValueError("strategy_identity_sha256 must be lowercase SHA-256")
        if _HASH_RE.fullmatch(preflight_sha256) is None:
            raise ValueError("preflight_sha256 must be lowercase SHA-256")
        with self._registered_sim_lock:
            if self._registered_sim_capability is not None:
                raise BtApiStoreError("disarm the current instrument before explicit re-arm")
            return self._arm_locked(
                instrument_id,
                exchange_id,
                md_front=md_front,
                strategy_identity_sha256=strategy_identity_sha256,
                execution_cycle_id=execution_cycle_id,
                preflight_sha256=preflight_sha256,
                switched=False,
            )

    def _disarm_locked(self, reason: str) -> Dict[str, Any]:
        client = getattr(self, "trader_client", None)
        capability = self._registered_sim_capability
        self._registered_sim_capability = None
        self._registered_sim_armed_key = None
        if capability is None:
            return {"disarmed": True, "reason": reason, "native": False}
        disarm = getattr(client, "disarm_execution_gate", None) if client is not None else None
        if not callable(disarm):
            self._registered_sim_frozen = True
            self._registered_sim_freeze_reason = "native_disarm_unavailable"
            raise BtApiStoreError("SDK native disarm is unavailable; gate frozen")
        try:
            state = disarm(capability, reason)
        except Exception as exc:
            self._registered_sim_frozen = True
            self._registered_sim_freeze_reason = "native_disarm_failed"
            raise BtApiStoreError(
                "SDK native disarm failed ({})".format(type(exc).__name__)
            ) from None
        return {"disarmed": True, "reason": reason, "native": True, "state": state}

    def disarm_registered_sim_execution(
        self, reason: str = "registered_sim_disarmed"
    ) -> Dict[str, Any]:
        with self._registered_sim_lock:
            return self._disarm_locked(str(reason))

    def freeze_registered_sim_execution(self, reason: str) -> Dict[str, Any]:
        """Permanently close this wrapper after ambiguity or operator freeze."""
        with self._registered_sim_lock:
            self._registered_sim_frozen = True
            self._registered_sim_freeze_reason = str(reason)
            try:
                result = self._disarm_locked(str(reason))
            except BtApiStoreError:
                raise
            return {"frozen": True, "reason": str(reason), "native": result["native"]}

    def ensure_registered_sim_arm_for(self, instrument: Any, exchange: Any) -> Dict[str, Any]:
        """Switch the native single-instrument capability under one lock."""
        instrument_id = _exact_text(instrument, "InstrumentID")
        exchange_id = _exact_text(exchange, "ExchangeID")
        key = (instrument_id, exchange_id)
        with self._registered_sim_lock:
            self._require_armable_locked()
            if not self._registered_sim_arm_templates:
                raise BtApiStoreError("registered-sim arm templates are not configured")
            template = self._registered_sim_arm_templates.get(key)
            if template is None:
                raise BtApiStoreError("registered-sim arm template is missing for outbound leg")
            if (
                self._registered_sim_capability is not None
                and self._registered_sim_armed_key == key
            ):
                return {"armed": True, "instrument": instrument_id, "switched": False}
            switched = self._registered_sim_capability is not None
            if switched:
                self._disarm_locked("registered_sim_instrument_switch")
            return self._arm_locked(
                instrument_id,
                exchange_id,
                md_front=template["md_front"],
                strategy_identity_sha256=template["strategy_identity_sha256"],
                execution_cycle_id=template["execution_cycle_id"],
                preflight_sha256=template["preflight_sha256"],
                switched=switched,
            )

    def registered_sim_arm_history(self):
        with self._registered_sim_lock:
            return [dict(item) for item in self._registered_sim_arm_history]

    def registered_sim_dispatch_history(self):
        """Return bounded native-result evidence, including pinned UNKNOWN."""
        with self._registered_sim_lock:
            entries = list(self._registered_sim_dispatch_history)
            if self._registered_sim_unknown_dispatch is not None:
                entries.append(self._registered_sim_unknown_dispatch)
            return tuple(sorted(entries, key=lambda item: item.sequence))

    def reserve_registered_sim_order_ref(self) -> str:
        """Reserve one SDK-monotonic OrderRef without making a provider call."""
        with self._registered_sim_lock:
            client = getattr(self, "trader_client", None)
            reserve = getattr(client, "next_order_ref", None) if client is not None else None
            if not callable(reserve):
                raise BtApiStoreError("SDK monotonic CTP OrderRef allocator is unavailable")
            value = reserve()
            if not isinstance(value, str) or re.fullmatch(r"[1-9][0-9]*", value) is None:
                raise BtApiStoreError("SDK returned an invalid monotonic CTP OrderRef")
            return value

    def _outbound_key_locked(self, field: Any) -> Tuple[str, str]:
        key = (
            _exact_text(getattr(field, "InstrumentID", None), "outbound InstrumentID"),
            _exact_text(getattr(field, "ExchangeID", None), "outbound ExchangeID"),
        )
        if self._registered_sim_arm_templates:
            template = self._registered_sim_arm_templates.get(key)
            if template is None:
                raise BtApiStoreError("outbound leg has no exact registered-sim arm template")
            self.ensure_registered_sim_arm_for(*key)
        if self._registered_sim_capability is None:
            raise BtApiStoreError("registered-sim native capability is not armed")
        if self._registered_sim_armed_key != key:
            raise BtApiStoreError("registered-sim capability does not match outbound instrument")
        return key

    def _remember_order_state_locked(self, order_ref: str, state: str) -> None:
        if not order_ref:
            return
        current = self._order_state.get(order_ref)
        # Callback delivery is evidence, but it cannot reconcile a native
        # UNKNOWN outcome. Preserve that identity until a future explicit path.
        if current == "unknown" and state != "unknown":
            return
        if current == "terminal" and state == "active":
            return
        self._order_state[order_ref] = state
        self._order_state.move_to_end(order_ref)
        terminal = [key for key, value in self._order_state.items() if value == "terminal"]
        while len(terminal) > self._registered_sim_terminal_order_limit:
            evict = terminal.pop(0)
            self._order_state.pop(evict, None)

    @staticmethod
    def _optional_exact_field(field: Any, name: str) -> Optional[str]:
        value = getattr(field, name, None)
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _optional_integer_field(field: Any, name: str) -> Optional[int]:
        value = getattr(field, name, None)
        return value if type(value) is int else None

    def _make_dispatch_evidence_locked(
        self,
        operation: str,
        status: str,
        field: Any,
        req_id: int,
        instrument_id: str,
        exchange_id: str,
        *,
        native_return_code: Optional[int] = None,
        error_type: Optional[str] = None,
    ) -> RegisteredSimDispatchEvidence:
        self._registered_sim_dispatch_sequence += 1
        return RegisteredSimDispatchEvidence(
            sequence=self._registered_sim_dispatch_sequence,
            operation=operation,
            status=status,
            request_id=req_id,
            instrument_id=instrument_id,
            exchange_id=exchange_id,
            order_ref=self._optional_exact_field(field, "OrderRef"),
            order_sys_id=self._optional_exact_field(field, "OrderSysID"),
            front_id=self._optional_integer_field(field, "FrontID"),
            session_id=self._optional_integer_field(field, "SessionID"),
            broker_id=self._optional_exact_field(field, "BrokerID"),
            investor_id=self._optional_exact_field(field, "InvestorID"),
            user_id=self._optional_exact_field(field, "UserID"),
            native_return_code=native_return_code,
            error_type=error_type,
            observed_at_utc=datetime.now(timezone.utc).isoformat(),
        )

    def _freeze_after_unknown_locked(
        self, evidence: RegisteredSimDispatchEvidence, state_ref: str
    ) -> None:
        self._registered_sim_unknown_dispatch = evidence
        self._remember_order_state_locked(state_ref, "unknown")
        self._registered_sim_frozen = True
        self._registered_sim_freeze_reason = "{}_outcome_unknown".format(evidence.operation)
        # Set the local capability to None before calling the SDK. Even if
        # revocation reports an error, this wrapper can never reuse the token.
        try:
            self._disarm_locked(self._registered_sim_freeze_reason)
        except BtApiStoreError:
            pass

    def _send_registered_sim_native(self, operation: str, field: Any, req_id: int) -> Any:
        with self._registered_sim_lock:
            raw_order_ref = getattr(field, "OrderRef", None)
            order_ref = raw_order_ref if isinstance(raw_order_ref, str) else ""
            if order_ref and order_ref != order_ref.strip():
                raise BtApiStoreError("native OrderRef must preserve exact text")
            if operation == "insert" and not order_ref:
                raise BtApiStoreError("native insert requires an exact OrderRef")
            if (
                type(req_id) is not int
                or req_id <= 0
                or getattr(field, "RequestID", None) != req_id
            ):
                raise BtApiStoreError("native request identity does not match outbound field")
            state_ref = order_ref or "UNKNOWN-{}-{}".format(operation, req_id)
            key = self._outbound_key_locked(field)
            capability = self._registered_sim_capability
            client = getattr(self, "trader_client", None)
            method_name = "submit_order_insert" if operation == "insert" else "submit_order_action"
            method = getattr(client, method_name, None) if client is not None else None
            if not callable(method):
                raise BtApiStoreError("SDK native {} capability is unavailable".format(operation))
            with self._registered_sim_observation_lock:
                self._dispatching_order_ids.add(state_ref)
            try:
                result = method(field, req_id, execution_capability=capability)
            except Exception as exc:
                evidence = self._make_dispatch_evidence_locked(
                    operation,
                    "UNKNOWN",
                    field,
                    req_id,
                    key[0],
                    key[1],
                    error_type=type(exc).__name__,
                )
                self._freeze_after_unknown_locked(evidence, state_ref)
                raise RegisteredSimExecutionUnknown(evidence) from None
            finally:
                with self._registered_sim_observation_lock:
                    self._dispatching_order_ids.discard(state_ref)
            if type(result) is not int or result != 0:
                evidence = self._make_dispatch_evidence_locked(
                    operation,
                    "UNKNOWN",
                    field,
                    req_id,
                    key[0],
                    key[1],
                    native_return_code=result if type(result) is int else None,
                )
                self._freeze_after_unknown_locked(evidence, state_ref)
                raise RegisteredSimExecutionUnknown(evidence)
            self._registered_sim_dispatch_history.append(
                self._make_dispatch_evidence_locked(
                    operation, "KNOWN", field, req_id, key[0], key[1], native_return_code=0
                )
            )
            if operation == "insert":
                self._remember_order_state_locked(state_ref, "active")
            return result

    def _send_native_order_insert(self, field: Any, req_id: int) -> Any:
        return self._send_registered_sim_native("insert", field, req_id)

    def _send_native_order_action(self, field: Any, req_id: int) -> Any:
        return self._send_registered_sim_native("cancel", field, req_id)

    def _handle_order(self, payload: Any) -> Any:
        try:
            return super()._handle_order(payload)
        finally:
            if isinstance(payload, Mapping):
                order_ref = str(payload.get("OrderRef") or "").strip()
                status = str(payload.get("OrderStatus") or "").strip()
            else:
                order_ref = str(getattr(payload, "OrderRef", "") or "").strip()
                status = str(getattr(payload, "OrderStatus", "") or "").strip()
            if order_ref and status:
                next_state = "terminal" if status in _TERMINAL_ORDER_STATUSES else "active"
                with self._registered_sim_lock:
                    self._remember_order_state_locked(order_ref, next_state)

    def registered_sim_execution_facts(self) -> Dict[str, Any]:
        with self._registered_sim_observation_lock:
            dispatching = sorted(self._dispatching_order_ids)
        if dispatching:
            # Do not wait behind the in-flight native call just to observe it.
            # Other execution facts are explicitly unknown in this projection.
            return {
                "observed": True,
                "unknown_ids": None,
                "active_order_ids": None,
                "dispatching_order_ids": dispatching,
                "terminal_order_ids": None,
                "frozen": None,
                "armed_key": None,
            }
        with self._registered_sim_lock:
            with self._registered_sim_observation_lock:
                dispatching = sorted(self._dispatching_order_ids)
            if dispatching:
                return {
                    "observed": True,
                    "unknown_ids": None,
                    "active_order_ids": None,
                    "dispatching_order_ids": dispatching,
                    "terminal_order_ids": None,
                    "frozen": None,
                    "armed_key": None,
                }
            unknown_ids = [
                order_ref for order_ref, state in self._order_state.items() if state == "unknown"
            ]
            active_ids = [
                order_ref for order_ref, state in self._order_state.items() if state == "active"
            ]
            return {
                "observed": True,
                "unknown_ids": unknown_ids,
                "active_order_ids": active_ids,
                "dispatching_order_ids": sorted(self._dispatching_order_ids),
                "terminal_order_ids": [
                    order_ref
                    for order_ref, state in self._order_state.items()
                    if state == "terminal"
                ],
                "frozen": self._registered_sim_frozen,
                "armed_key": self._registered_sim_armed_key,
            }


def _make_api_factory(allow_writes: bool, history_limit: int, terminal_limit: int, api_cls: Any):
    """Return a callable that composes the provider wrapper only on first use."""

    def factory(**kwargs: Any) -> Any:
        base = api_cls
        if base is None:
            # This private factory performs the provider import. Keeping it
            # inside the callable preserves import-time and construction-time
            # isolation for ordinary/read-only users.
            from . import btapistore as _btapistore

            base = _btapistore._create_ctp_wrapper_class()
        if not isinstance(base, type):
            raise TypeError("registered-sim api_cls must be a client class")
        if issubclass(base, RegisteredSimWrapper):
            wrapper_cls = base
        else:
            wrapper_cls = type(
                "RegisteredSimClient",
                (RegisteredSimWrapper, base),
                {"__module__": __name__},
            )
        return wrapper_cls(
            registered_sim_allow_writes=allow_writes,
            registered_sim_history_limit=history_limit,
            registered_sim_terminal_order_limit=terminal_limit,
            **kwargs,
        )

    return factory


class RegisteredSimStore(BtApiStore):
    """CTP Store with explicit SDK admission and default-closed writes.

    ``allow_writes`` is immutable after construction and defaults to ``False``.
    Even with ``allow_writes=True``, writes remain blocked until the SDK grants
    a scoped native capability through :meth:`registered_sim_arm` (or the
    corresponding arm-template operation).
    """

    registered_sim_route_id = "simnow-registered-v1"

    def __init__(
        self,
        *,
        allow_writes: bool = False,
        provider: str = "ctp",
        backend: str = "direct",
        api: Any = None,
        api_cls: Any = None,
        arm_history_limit: int = 64,
        terminal_order_limit: int = 512,
        **kwargs: Any,
    ) -> None:
        if type(allow_writes) is not bool:
            raise TypeError("allow_writes must be bool")
        if provider != "ctp":
            raise ValueError("RegisteredSimStore supports only provider='ctp'")
        if backend != "direct":
            raise ValueError("RegisteredSimStore supports only backend='direct'")
        if type(arm_history_limit) is not int or arm_history_limit <= 0:
            raise ValueError("arm_history_limit must be a positive int")
        if type(terminal_order_limit) is not int or terminal_order_limit <= 0:
            raise ValueError("terminal_order_limit must be a positive int")
        if kwargs.get("managed_execution_adapter") is not None:
            raise ValueError("RegisteredSimStore does not accept a managed execution adapter")
        self._registered_sim_allow_writes = allow_writes
        self._registered_sim_arm_history_limit = arm_history_limit
        self._registered_sim_terminal_order_limit = terminal_order_limit
        super().__init__(provider=provider, backend=backend, api=api, api_cls=None, **kwargs)
        if api is None:
            self._api_cls = _make_api_factory(
                allow_writes,
                arm_history_limit,
                terminal_order_limit,
                api_cls,
            )
        elif not isinstance(api, RegisteredSimWrapper):
            raise TypeError("injected api must be a RegisteredSimWrapper")
        self._registered_sim_gate_lock = threading.RLock()
        self._registered_sim_gate = {
            "armed": False,
            "frozen": False,
            "reason": "",
            "execution_cycle_id": "",
        }
        self._ctp_query_result_lock = threading.RLock()
        self._ctp_query_results: Dict[str, Dict[str, Any]] = {}
        self._ctp_query_snapshots = collections.OrderedDict()
        self._ctp_query_instrument_rows: Dict[Tuple[str, str], Dict[str, Any]] = {}

    @property
    def allow_writes(self) -> bool:
        """Constructor-time write switch; intentionally has no setter."""
        return self._registered_sim_allow_writes

    @property
    def registered_sim_tick_source(self) -> str:
        """Immutable source identity for ticks consumed on this direct CTP route."""
        return _REGISTERED_SIM_TICK_SOURCE

    def _stamp_registered_sim_tick_source(self, tick: Any) -> Any:
        """Stamp a detached tick with the Store-owned route identity."""
        if tick is None:
            return None
        if isinstance(tick, Mapping):
            result = dict(tick)
        else:
            result = copy.copy(tick)
        try:
            source = self.registered_sim_tick_source
        except AttributeError:
            return result
        if type(source) is not str or not source or source != source.strip():
            return result
        if isinstance(result, Mapping):
            result["source"] = source
            return result
        try:
            setattr(result, "source", source)
        except Exception:
            raise BtApiStoreError("registered-sim tick source cannot be stamped") from None
        return result

    def poll_tick(self, dataname: str):
        """Consume a direct CTP tick and stamp the returned event by route."""
        return self._stamp_registered_sim_tick_source(super().poll_tick(dataname))

    def get_latest_tick_snapshot(self, dataname: str):
        """Read a detached consumed tick stamped with this Store's route identity."""
        return self._stamp_registered_sim_tick_source(super().get_latest_tick_snapshot(dataname))

    @staticmethod
    def _order_route_from_info(order: Any) -> Optional[Tuple[str, str]]:
        info = getattr(order, "info", None)
        get_info = getattr(info, "get", None)
        if not callable(get_info):
            return None
        instrument_value = get_info("instrument_id")
        exchange_value = get_info("exchange_id")
        if instrument_value in (None, "") and exchange_value in (None, ""):
            return None
        instrument = _exact_text(instrument_value, "order.info.instrument_id")
        exchange = _exact_text(exchange_value, "order.info.exchange_id")
        data_name_value = BtApiStore._extract_dataname(getattr(order, "data", None))
        if not isinstance(data_name_value, str) or data_name_value != data_name_value.strip():
            raise BtApiStoreError("registered-sim order data identity is not exact text")
        matches = data_name_value == instrument
        for separator in (".", "_"):
            parts = data_name_value.split(separator)
            if len(parts) == 2:
                matches = (
                    matches
                    or (parts[0].upper() == exchange and parts[1] == instrument)
                    or (parts[1].upper() == exchange and parts[0] == instrument)
                )
        if not matches:
            raise BtApiStoreError("order.info route identity does not match its data feed")
        return instrument, exchange

    def _order_to_payload(self, order):
        payload = super()._order_to_payload(order)
        route = self._order_route_from_info(order)
        if route is not None:
            instrument, exchange = route
            qualified = "{}.{}".format(exchange, instrument)
            payload.update(
                {
                    "symbol": qualified,
                    "data_name": qualified,
                    "instrument_id": instrument,
                    "exchange_id": exchange,
                }
            )
        return payload

    @property
    def sdk_api(self) -> Any:
        """Do not expose the provider client as a raw framework API."""
        return None

    def _is_ctp_write_provider(self) -> bool:
        with getattr(self, "_registered_sim_gate_lock", threading.RLock()):
            gate = getattr(self, "_registered_sim_gate", {})
            return not (
                self._registered_sim_allow_writes
                and gate.get("armed") is True
                and gate.get("frozen") is False
            )

    def registered_sim_arm(
        self,
        *,
        instrument: str,
        exchange: str,
        md_front: str,
        strategy_identity_sha256: str,
        execution_cycle_id: str,
        preflight_sha256: str,
    ) -> Dict[str, Any]:
        """Ask the SDK to issue the only capability accepted by native writes."""
        if not self._registered_sim_allow_writes:
            raise BtApiStoreError("registered-sim writes are disabled in shadow mode")
        instrument = _exact_text(instrument, "InstrumentID")
        exchange = _exact_text(exchange, "ExchangeID")
        with self._registered_sim_gate_lock:
            if self._registered_sim_gate["frozen"]:
                raise BtApiStoreError("registered-sim gate is frozen; reconciliation is required")
            api = self._ensure_api_ready()
            arm = getattr(api, "arm_registered_sim_execution", None)
            if not callable(arm):
                raise BtApiStoreError("registered-sim admission capability is unavailable")
            try:
                result = arm(
                    instrument,
                    exchange,
                    md_front=md_front,
                    strategy_identity_sha256=strategy_identity_sha256,
                    execution_cycle_id=execution_cycle_id,
                    preflight_sha256=preflight_sha256,
                )
            except Exception:
                self._sync_gate_after_arm_failure_locked(api, "native_admission_failed")
                raise
            self._registered_sim_gate.update(
                {
                    "armed": True,
                    "frozen": False,
                    "reason": "",
                    "execution_cycle_id": execution_cycle_id,
                    "instrument": instrument,
                    "exchange": exchange,
                }
            )
            return dict(result)

    def registered_sim_configure_arm_templates(self, templates: Mapping) -> None:
        if not self._registered_sim_allow_writes:
            raise BtApiStoreError("registered-sim writes are disabled in shadow mode")
        with self._registered_sim_gate_lock:
            if self._registered_sim_gate["frozen"]:
                raise BtApiStoreError("registered-sim gate is frozen")
            api = self._ensure_api_ready()
            method = getattr(api, "configure_registered_sim_arm_templates", None)
            if not callable(method):
                raise BtApiStoreError("registered-sim multi-instrument arming is unavailable")
            method(templates)

    def registered_sim_ensure_arm(self, instrument: str, exchange: str) -> Dict[str, Any]:
        if not self._registered_sim_allow_writes:
            raise BtApiStoreError("registered-sim writes are disabled in shadow mode")
        instrument = _exact_text(instrument, "InstrumentID")
        exchange = _exact_text(exchange, "ExchangeID")
        with self._registered_sim_gate_lock:
            if self._registered_sim_gate["frozen"]:
                raise BtApiStoreError("registered-sim gate is frozen")
            api = self._ensure_api_ready()
            ensure = getattr(api, "ensure_registered_sim_arm_for", None)
            if not callable(ensure):
                raise BtApiStoreError("registered-sim multi-instrument arming is unavailable")
            try:
                result = dict(ensure(instrument, exchange))
            except Exception:
                self._sync_gate_after_arm_failure_locked(api, "native_arm_switch_failed")
                raise
            self._registered_sim_gate.update(
                {
                    "armed": result.get("armed") is True,
                    "reason": "",
                    "instrument": instrument,
                    "exchange": exchange,
                }
            )
            return result

    def _sync_gate_after_arm_failure_locked(self, api: Any, reason: str) -> None:
        facts_method = getattr(api, "registered_sim_execution_facts", None)
        facts = facts_method() if callable(facts_method) else None
        if not isinstance(facts, Mapping):
            return
        if facts.get("frozen") is True or facts.get("armed_key") is None:
            self._registered_sim_gate.update({"armed": False, "reason": reason})
        if facts.get("frozen") is True:
            self._registered_sim_gate.update({"frozen": True, "armed": False, "reason": reason})

    def registered_sim_disarm(self, reason: str = "operator_disarm") -> Dict[str, Any]:
        with self._registered_sim_gate_lock:
            self._registered_sim_gate.update({"armed": False, "reason": str(reason)})
            api = self._api
            if api is None:
                return {"disarmed": True, "reason": str(reason), "native": False}
            method = getattr(api, "disarm_registered_sim_execution", None)
            if not callable(method):
                self._registered_sim_gate.update(
                    {"frozen": True, "reason": "native_disarm_unavailable"}
                )
                raise BtApiStoreError("SDK native disarm is unavailable; Store gate frozen")
            try:
                result = dict(method(str(reason)))
            except Exception as exc:
                self._registered_sim_gate.update({"frozen": True, "reason": "native_disarm_failed"})
                raise BtApiStoreError(
                    "SDK native disarm failed ({})".format(type(exc).__name__)
                ) from None
            return result

    def registered_sim_freeze(self, reason: str) -> Dict[str, Any]:
        """Permanently latch the Store closed and serialize native revocation."""
        with self._registered_sim_gate_lock:
            self._registered_sim_gate.update(
                {"armed": False, "frozen": True, "reason": str(reason)}
            )
            api = self._api
            if api is None:
                return {"frozen": True, "reason": str(reason), "native": False}
            method = getattr(api, "freeze_registered_sim_execution", None)
            if not callable(method):
                self._registered_sim_gate["reason"] = "native_freeze_unavailable"
                raise BtApiStoreError("SDK native freeze is unavailable")
            result = dict(method(str(reason)))
            return {"frozen": True, "reason": str(reason), "native": result.get("native") is True}

    def registered_sim_status(self) -> Dict[str, Any]:
        with self._registered_sim_gate_lock:
            return {**self._registered_sim_gate, "allow_writes": self._registered_sim_allow_writes}

    def sanitize_exception(self, exc: BaseException) -> BaseException:
        """Redact diagnostics while preserving the typed UNKNOWN receipt."""
        evidence = exc.evidence if isinstance(exc, RegisteredSimExecutionUnknown) else None
        result = super().sanitize_exception(exc)
        if evidence is not None:
            exc.evidence = evidence
        return result

    def _require_registered_sim_not_frozen(self) -> None:
        with self._registered_sim_gate_lock:
            if self._registered_sim_gate.get("frozen") is True:
                raise BtApiStoreError("registered-sim Store gate is frozen")

    def registered_sim_route_eligibility(
        self, instrument: str, exchange: str
    ) -> RegisteredSimRouteEligibility:
        """Return read-only route facts without opening the API or granting writes.

        ``sdk_capability_matches_route`` and ``instrument_eligible`` are
        observations only. Native submission still requires the SDK's scoped
        capability at each write boundary.
        """
        instrument = _exact_text(instrument, "InstrumentID")
        exchange = _exact_text(exchange, "ExchangeID")
        with self._registered_sim_gate_lock:
            gate = dict(self._registered_sim_gate)
            api = self._api
            wrapper_facts = None
            sdk_gate = None
            if api is not None:
                wrapper_facts_method = getattr(api, "registered_sim_execution_facts", None)
                sdk_client = getattr(api, "trader_client", None)
                sdk_state_method = getattr(sdk_client, "get_execution_gate_state", None)
                wrapper_facts = wrapper_facts_method() if callable(wrapper_facts_method) else None
                has_dispatching_ids = (
                    isinstance(wrapper_facts, Mapping)
                    and isinstance(wrapper_facts.get("dispatching_order_ids"), list)
                    and bool(wrapper_facts.get("dispatching_order_ids"))
                )
                if not has_dispatching_ids:
                    sdk_gate = sdk_state_method() if callable(sdk_state_method) else None

        wrapper_observed = (
            isinstance(wrapper_facts, Mapping) and wrapper_facts.get("observed") is True
        )
        sdk_gate_observed = (
            isinstance(sdk_gate, Mapping)
            and type(sdk_gate.get("managed")) is bool
            and type(sdk_gate.get("armed")) is bool
        )
        unknown_ids_value = wrapper_facts.get("unknown_ids") if wrapper_observed else None
        dispatching_value = wrapper_facts.get("dispatching_order_ids") if wrapper_observed else None
        unknown_ids = (
            tuple(unknown_ids_value)
            if isinstance(unknown_ids_value, list)
            and all(isinstance(value, str) for value in unknown_ids_value)
            else None
        )
        dispatching_ids = (
            tuple(dispatching_value)
            if isinstance(dispatching_value, list)
            and all(isinstance(value, str) for value in dispatching_value)
            else None
        )
        sdk_managed = sdk_gate.get("managed") if sdk_gate_observed else None
        sdk_armed = sdk_gate.get("armed") if sdk_gate_observed else None
        sdk_frozen_value = (
            wrapper_facts.get("frozen")
            if wrapper_observed and type(wrapper_facts.get("frozen")) is bool
            else None
        )
        sdk_instrument_value = sdk_gate.get("instrument") if sdk_gate_observed else None
        sdk_instrument = sdk_instrument_value if isinstance(sdk_instrument_value, str) else None
        authorized_value = sdk_gate.get("authorized_instruments") if sdk_gate_observed else None
        authorized_instruments = (
            tuple(authorized_value)
            if isinstance(authorized_value, list)
            and all(isinstance(value, str) for value in authorized_value)
            else None
        )
        adapter_key = wrapper_facts.get("armed_key") if wrapper_observed else None
        sdk_capability_matches_route = None
        if wrapper_observed and sdk_gate_observed:
            if (
                sdk_managed is not True
                or sdk_armed is not True
                or adapter_key != (instrument, exchange)
                or (sdk_instrument is not None and sdk_instrument != instrument)
            ):
                sdk_capability_matches_route = False
            elif authorized_instruments is not None:
                sdk_capability_matches_route = instrument in authorized_instruments

        instrument_query_complete = self.supports_complete_ctp_queries(include_reference_data=True)
        with self._ctp_query_result_lock:
            instrument_facts = self._ctp_query_results.get("instruments_result")
        instrument_eligible = None
        if instrument_query_complete:
            instrument_eligible = _instrument_eligibility_from_rows(
                instrument_facts.get("rows") if isinstance(instrument_facts, Mapping) else None,
                instrument,
                exchange,
            )
        unknown_order_count = len(unknown_ids) if unknown_ids is not None else None
        account_fingerprint = None
        connection_generation = None
        trading_day = None
        if instrument_query_complete and isinstance(instrument_facts, Mapping):
            account_value = instrument_facts.get("account_fingerprint")
            generation_value = instrument_facts.get("connection_generation")
            day_value = instrument_facts.get("trading_day")
            account_fingerprint = account_value if isinstance(account_value, str) else None
            connection_generation = generation_value if _positive_int(generation_value) else None
            trading_day = day_value if isinstance(day_value, str) else None
        reason_codes = []
        if not self._registered_sim_allow_writes:
            reason_codes.append("shadow_mode")
        if gate.get("frozen") is True or sdk_frozen_value is True:
            reason_codes.append("frozen")
        if unknown_order_count is None:
            reason_codes.append("unknown_orders_unobserved")
        elif unknown_order_count:
            reason_codes.append("unknown_orders_present")
        if dispatching_ids is None:
            reason_codes.append("dispatch_state_unobserved")
        elif dispatching_ids:
            reason_codes.append("dispatch_in_progress")
        if not sdk_gate_observed:
            reason_codes.append("sdk_capability_unobserved")
        elif sdk_capability_matches_route is False:
            reason_codes.append("sdk_capability_route_mismatch")
        elif sdk_capability_matches_route is None:
            reason_codes.append("sdk_capability_route_match_unobserved")
        if not instrument_query_complete:
            reason_codes.append("instrument_query_incomplete")
        elif instrument_eligible is None:
            reason_codes.append("instrument_eligibility_unobserved")
        elif instrument_eligible is False:
            reason_codes.append("instrument_not_eligible")
        return RegisteredSimRouteEligibility(
            route_name="ctp/direct/registered-sim",
            instrument_id=instrument,
            exchange_id=exchange,
            account_fingerprint=account_fingerprint,
            connection_generation=connection_generation,
            trading_day=trading_day,
            allow_writes=self._registered_sim_allow_writes,
            frozen=gate.get("frozen") is True or sdk_frozen_value is True,
            sdk_frozen=sdk_frozen_value,
            unknown_order_ids=unknown_ids,
            unknown_order_count=unknown_order_count,
            dispatching_order_ids=dispatching_ids,
            capability_observed=sdk_gate_observed,
            sdk_capability_managed=sdk_managed,
            sdk_capability_armed=sdk_armed,
            sdk_capability_instrument=sdk_instrument,
            sdk_authorized_instruments=authorized_instruments,
            capability_matches_route=sdk_capability_matches_route,
            instrument_query_complete=instrument_query_complete,
            instrument_eligible=instrument_eligible,
            reason_codes=tuple(reason_codes),
        )

    def registered_sim_arm_history(self):
        api = self._api
        method = getattr(api, "registered_sim_arm_history", None) if api is not None else None
        return list(method()) if callable(method) else None

    def registered_sim_dispatch_history(self):
        """Return bounded adapter evidence; an absent wrapper stays unobserved."""
        api = self._api
        method = getattr(api, "registered_sim_dispatch_history", None) if api is not None else None
        return tuple(method()) if callable(method) else None

    def registered_sim_reserve_order_ref(self) -> str:
        """Reserve one exact SDK OrderRef before a journal prepares dispatch.

        This uses the already selected wrapper and never creates an API client,
        arms the native gate, queries the provider, or dispatches an order.
        The SDK's monotonic allocator is called exactly once under the same
        wrapper lock used by native dispatch.
        """
        with self._registered_sim_gate_lock:
            if self._registered_sim_gate.get("frozen") is True:
                raise BtApiStoreError("registered-sim Store gate is frozen")
            api = self._api
            if not isinstance(api, RegisteredSimWrapper):
                raise BtApiStoreError("registered-sim CTP wrapper is unavailable")
            reserve = getattr(api, "reserve_registered_sim_order_ref", None)
            if not callable(reserve):
                raise BtApiStoreError("registered-sim OrderRef reservation is unavailable")
            return reserve()

    def registered_sim_write_health(self) -> Dict[str, Any]:
        gate = self.registered_sim_status()
        api = self._api
        facts_method = (
            getattr(api, "registered_sim_execution_facts", None) if api is not None else None
        )
        facts = facts_method() if callable(facts_method) else None
        if not isinstance(facts, Mapping) or facts.get("observed") is not True:
            active_orders = None
            unknown_order_count = None
            unknown_ids = None
            dispatching_ids = None
        else:
            active_ids = facts.get("active_order_ids")
            unknown_ids = facts.get("unknown_ids")
            dispatching_ids = facts.get("dispatching_order_ids")
            active_orders = len(active_ids) if isinstance(active_ids, list) else None
            unknown_order_count = (
                len(unknown_ids)
                if isinstance(unknown_ids, list)
                and isinstance(dispatching_ids, list)
                and not dispatching_ids
                else None
            )
        return {
            "armed": gate["armed"],
            "frozen": gate["frozen"],
            "allow_writes": self._registered_sim_allow_writes,
            "active_orders": active_orders,
            "unknown_order_count": unknown_order_count,
            "unknown_ids": list(unknown_ids) if isinstance(unknown_ids, list) else None,
            "dispatching_order_ids": (
                list(dispatching_ids) if isinstance(dispatching_ids, list) else None
            ),
        }

    def get_execution_summary(self) -> Dict[str, Any]:
        health = self.registered_sim_write_health()
        query_health = self.get_ctp_query_health()
        unknown_ids = health["unknown_ids"]
        active_orders = health["active_orders"]
        unmatched = query_health.get("unmatched_trade_count")
        facts_observed = (
            type(health.get("unknown_order_count")) is int
            and isinstance(active_orders, int)
            and health.get("dispatching_order_ids") == []
        )
        complete = bool(
            facts_observed
            and query_health.get("evidence_complete") is True
            and type(unmatched) is int
        )
        gate = self.registered_sim_status()
        return {
            "session_enabled": gate["armed"] is True and gate["frozen"] is False,
            "armed": gate["armed"] is True,
            "market_data_only": self._registered_sim_allow_writes is False,
            "trading_blocked": (
                gate["armed"] is not True
                or gate["frozen"] is True
                or not self._registered_sim_allow_writes
                or not complete
                or bool(unknown_ids)
                or unmatched != 0
            ),
            "unknown_ids": list(unknown_ids) if isinstance(unknown_ids, list) else None,
            "unknown_intent_count": query_health.get("unknown_intent_count"),
            "unmatched_trade_count": unmatched,
            "active_orders": active_orders,
            "evidence_complete": complete,
            "evidence_errors": []
            if complete
            else ["registered_sim_query_or_execution_facts_unobserved"],
            "source": "backtrader.registered_sim_execution_summary.v1",
        }

    def registered_sim_wait_ready(self, timeout: float) -> bool:
        try:
            timeout = float(timeout)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("timeout must be finite and nonnegative") from None
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and nonnegative")
        api = self._ensure_api_ready()
        client = getattr(api, "trader_client", None)
        method = getattr(client, "wait_ready", None) if client is not None else None
        if not callable(method):
            raise BtApiStoreError("CTP trader wait_ready is unavailable")
        return method(timeout=timeout) is True

    def registered_sim_login_facts(self) -> Dict[str, Any]:
        api = self._ensure_api_ready()
        client = getattr(api, "trader_client", None)
        if client is None:
            raise BtApiStoreError("CTP trader client is unavailable")
        return {
            "front_id": getattr(client, "_front_id", None),
            "session_id": getattr(client, "_session_id", None),
            "trading_day": getattr(client, "_trading_day", None),
            "connection_generation": getattr(client, "_connection_generation", None),
            "read_only_ready": getattr(client, "is_read_only_ready", None),
            "trading_ready": getattr(client, "is_trading_ready", None),
        }

    def registered_sim_account_fingerprint(self) -> Optional[str]:
        api = self._ensure_api_ready()
        client = getattr(api, "trader_client", None)
        if client is None:
            raise BtApiStoreError("CTP trader client is unavailable")
        value = getattr(client, "_account_fingerprint", None)
        return value if isinstance(value, str) and value else None

    def _query_result_is_current(self, family: str) -> bool:
        with self._ctp_query_result_lock:
            facts = self._ctp_query_results.get(family)
        return bool(
            isinstance(facts, Mapping)
            and facts.get("query_complete") is True
            and facts.get("scope_complete") is True
        )

    def get_registered_sim_query_snapshot(self, family: str, **filters: Any):
        """Return a detached, current sealed query result without issuing I/O.

        Filter kwargs must exactly match the kwargs used by the corresponding
        :meth:`registered_sim_query` call. The query cache is bounded; an
        absent, incomplete, expired, or stale result is reported as ``None``.
        This method does not create an API client. Its only SDK interaction is
        the public in-process session-scope read used to revalidate issuer and
        account/generation/day identity.
        """
        if not isinstance(family, str) or family not in _QUERY_METHODS:
            raise ValueError("unsupported registered-sim query family")
        cache_key = _query_snapshot_key(family, filters)
        with self._ctp_query_result_lock:
            facts = self._ctp_query_snapshots.get(cache_key)
        if not isinstance(facts, Mapping):
            return None

        expiry = facts.get("source_expires_monotonic")
        completed_at = facts.get("completed_at_utc")
        issuer = facts.get("_source_issuer")
        if not (
            facts.get("query_complete") is True
            and facts.get("source_owned") is True
            and _positive_int(facts.get("request_id"))
            and _positive_int(facts.get("connection_generation"))
            and isinstance(facts.get("account_fingerprint"), str)
            and bool(facts.get("account_fingerprint"))
            and isinstance(facts.get("trading_day"), str)
            and re.fullmatch(r"[0-9]{8}", facts.get("trading_day")) is not None
            and _is_aware_datetime(completed_at)
            and isinstance(facts.get("source_explicit_request_filters"), tuple)
            and type(expiry) in (int, float)
            and math.isfinite(expiry)
            and time.monotonic() < expiry
            and issuer is not None
        ):
            return None

        api = self._api
        client = getattr(api, "trader_client", None) if api is not None else None
        scope_getter = getattr(client, "get_query_session_scope", None)
        if not callable(scope_getter):
            return None
        try:
            current_scope = scope_getter()
        except Exception:
            return None
        if not (
            _read_fact(current_scope, "read_only_ready") is True
            and _read_fact(current_scope, "issuer") is issuer
            and _read_fact(current_scope, "connection_generation")
            == facts.get("connection_generation")
            and _read_fact(current_scope, "account_fingerprint") == facts.get("account_fingerprint")
            and _read_fact(current_scope, "trading_day") == facts.get("trading_day")
            and time.monotonic() < expiry
        ):
            return None

        detached = _public_query_snapshot(facts)
        detached["query_filters"] = copy.deepcopy(dict(filters))
        return detached

    def _record_instrument_rows(self, facts: Mapping, filters: Mapping) -> None:
        requested_instrument = filters.get("instrument_id")
        requested_exchange = filters.get("exchange_id")
        for row in facts.get("rows") or ():
            if not isinstance(row, Mapping):
                continue
            instrument = row.get("InstrumentID", row.get("instrument_id"))
            exchange = row.get("ExchangeID", row.get("exchange_id"))
            if not isinstance(instrument, str) or not instrument:
                continue
            if not isinstance(exchange, str) or not exchange:
                continue
            if requested_instrument and instrument != requested_instrument:
                continue
            if requested_exchange and exchange != requested_exchange:
                continue
            is_trading = _instrument_is_trading(row)
            if is_trading is None:
                continue
            self._ctp_query_instrument_rows[(exchange, instrument)] = {
                "instrument_id": instrument,
                "exchange_id": exchange,
                "is_trading": is_trading,
            }

    def registered_sim_query(
        self,
        family: str,
        timeout: float = 8.0,
        attempts: int = 2,
        **filters: Any,
    ) -> Dict[str, Any]:
        """Run a bounded typed query; absent completion facts remain unknown."""
        method_name = _QUERY_METHODS.get(family) if isinstance(family, str) else None
        if method_name is None:
            raise ValueError("unsupported registered-sim query family")
        snapshot_key = _query_snapshot_key(family, filters)
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("timeout must be finite and positive") from None
        if not math.isfinite(timeout_value) or timeout_value <= 0:
            raise ValueError("timeout must be finite and positive")
        if type(attempts) is not int or attempts <= 0:
            raise ValueError("attempts must be a positive int")
        api = self._ensure_api_ready()
        method = getattr(api, method_name, None)
        if not callable(method):
            raise BtApiStoreError("CTP query family is unavailable")
        effective_timeout = timeout_value
        facts: Dict[str, Any] = {"family": family, "query_complete": False, "rows": None}
        if family == "instruments_result":
            with self._ctp_query_result_lock:
                self._ctp_query_instrument_rows.clear()
        for attempt in range(1, attempts + 1):
            try:
                result = method(timeout=effective_timeout, **filters)
                api_client = getattr(api, "trader_client", None)
                scope_getter = getattr(api_client, "get_query_session_scope", None)
                scope = scope_getter() if callable(scope_getter) else None
                facts = _query_result_facts(result, family, attempt, scope)
                facts["scope_complete"] = bool(
                    not filters
                    and facts.get("source_owned") is True
                    and facts.get("source_explicit_request_filters") == ()
                )
            except Exception as exc:
                facts = {
                    "family": family,
                    "query_complete": False,
                    "scope_complete": False,
                    "rows": None,
                    "attempt": attempt,
                    "error_code": "query_exception_" + type(exc).__name__,
                }
            with self._ctp_query_result_lock:
                self._ctp_query_results[family] = facts
                if facts.get("query_complete") is True and facts.get("source_owned") is True:
                    previous = self._ctp_query_snapshots.get(snapshot_key)
                    previous_completed = (
                        previous.get("completed_at_utc") if isinstance(previous, Mapping) else None
                    )
                    previous_request_id = (
                        previous.get("request_id") if isinstance(previous, Mapping) else None
                    )
                    completed_at = facts.get("completed_at_utc")
                    request_id = facts.get("request_id")
                    is_newer = (
                        previous is None
                        or not _is_aware_datetime(previous_completed)
                        or completed_at > previous_completed
                        or (
                            completed_at == previous_completed
                            and type(request_id) is int
                            and type(previous_request_id) is int
                            and request_id > previous_request_id
                        )
                    )
                    if is_newer:
                        self._ctp_query_snapshots[snapshot_key] = facts
                        self._ctp_query_snapshots.move_to_end(snapshot_key)
                        while len(self._ctp_query_snapshots) > _QUERY_SNAPSHOT_LIMIT:
                            self._ctp_query_snapshots.popitem(last=False)
            if facts.get("query_complete") is True:
                if family == "instruments_result":
                    with self._ctp_query_result_lock:
                        self._record_instrument_rows(facts, filters)
                return _public_query_snapshot(facts)
            if attempt < attempts:
                time.sleep(min(1.5 * attempt, 3.0))
                effective_timeout = max(effective_timeout * 1.5, effective_timeout + 1.0)
        raise BtApiStoreError("registered-sim query completion is unobserved or incomplete")

    def supports_complete_ctp_queries(self, include_reference_data: bool = False) -> bool:
        required = set(_REQUIRED_QUERY_FAMILIES)
        if include_reference_data:
            required.add("instruments_result")
        with self._ctp_query_result_lock:
            if not all(
                isinstance(self._ctp_query_results.get(family), Mapping)
                and self._ctp_query_results[family].get("query_complete") is True
                and self._ctp_query_results[family].get("scope_complete") is True
                for family in required
            ):
                return False
            facts = [self._ctp_query_results[family] for family in required]
        generations = {item.get("connection_generation") for item in facts}
        fingerprints = {item.get("account_fingerprint") for item in facts}
        trading_days = {item.get("trading_day") for item in facts}
        api = self._api
        client = getattr(api, "trader_client", None) if api is not None else None
        scope_getter = getattr(client, "get_query_session_scope", None)
        if not callable(scope_getter):
            return False
        try:
            current_scope = scope_getter()
        except Exception:
            return False
        current_generation = _read_fact(current_scope, "connection_generation")
        current_fingerprint = _read_fact(current_scope, "account_fingerprint")
        current_trading_day = _read_fact(current_scope, "trading_day")
        current_issuer = _read_fact(current_scope, "issuer")
        current_expiry = time.monotonic()
        required_scope = all(item.get("scope_complete") is True for item in facts)
        return bool(
            _read_fact(current_scope, "read_only_ready") is True
            and len(generations) == 1
            and len(fingerprints) == 1
            and len(trading_days) == 1
            and bool(next(iter(trading_days), None))
            and all(item.get("_source_issuer") is current_issuer for item in facts)
            and all(
                type(item.get("source_expires_monotonic")) in (int, float)
                and math.isfinite(item.get("source_expires_monotonic"))
                and current_expiry < item.get("source_expires_monotonic")
                for item in facts
            )
            and _positive_int(current_generation)
            and current_generation in generations
            and isinstance(current_fingerprint, str)
            and current_fingerprint
            and current_fingerprint in fingerprints
            and current_trading_day in trading_days
            and required_scope
        )

    def get_ctp_query_health(self) -> Dict[str, Any]:
        complete = self.supports_complete_ctp_queries(include_reference_data=True)
        execution = self.registered_sim_write_health()
        dispatching_ids = execution.get("dispatching_order_ids")
        unknown_count = (
            execution.get("unknown_order_count") if complete and dispatching_ids == [] else None
        )
        with self._ctp_query_result_lock:
            trade_facts = self._ctp_query_results.get("trades_result")
            order_query_facts = self._ctp_query_results.get("orders_result")
            instrument_facts = (
                list(self._ctp_query_instrument_rows.values())
                if self._query_result_is_current("instruments_result")
                else None
            )
        unmatched_trade_count = None
        if (
            complete
            and isinstance(trade_facts, Mapping)
            and isinstance(order_query_facts, Mapping)
            and isinstance(trade_facts.get("rows"), list)
            and isinstance(order_query_facts.get("rows"), list)
        ):
            trades = trade_facts["rows"]
            orders = order_query_facts["rows"]
            known_ids = set()
            for row in orders:
                if not isinstance(row, Mapping):
                    known_ids = None
                    break
                order_ref = row.get("OrderRef", row.get("order_ref"))
                if not isinstance(order_ref, str) or not order_ref:
                    known_ids = None
                    break
                known_ids.add(order_ref)
            if known_ids is not None:
                unmatched_trade_count = 0
                for row in trades:
                    if not isinstance(row, Mapping):
                        unmatched_trade_count = None
                        break
                    order_ref = row.get("OrderRef", row.get("order_ref"))
                    if (
                        not isinstance(order_ref, str)
                        or not order_ref
                        or order_ref not in known_ids
                    ):
                        unmatched_trade_count += 1
        return {
            "evidence_complete": bool(
                complete
                and type(unknown_count) is int
                and type(unmatched_trade_count) is int
                and dispatching_ids == []
            ),
            "supported": complete,
            "evidence_errors": (
                []
                if complete and type(unknown_count) is int and type(unmatched_trade_count) is int
                else ["registered_sim_query_or_execution_facts_unobserved"]
            ),
            "instruments": (
                copy.deepcopy(instrument_facts) if instrument_facts is not None else None
            ),
            "unknown_intent_count": unknown_count,
            "unmatched_trade_count": unmatched_trade_count,
        }

    def submit_order(self, order):
        self._require_registered_sim_not_frozen()
        try:
            return super().submit_order(order)
        except Exception as exc:
            if getattr(exc, "execution_unknown", False) is True:
                try:
                    self.registered_sim_freeze(getattr(exc, "code", "submit_unknown"))
                except Exception:
                    pass
            raise

    def cancel_order(self, order):
        self._require_registered_sim_not_frozen()
        route = self._order_route_from_info(order)
        if route is not None:
            info = getattr(order, "info", {})
            order_ref = (
                info.get("external_order_id")
                or info.get("ctp_order_ref")
                or getattr(order, "ref", None)
            )
            instrument, exchange = route
            dataname = "{}.{}".format(exchange, instrument)
            return self.cancel_order_ref(order_ref, dataname=dataname)
        try:
            return super().cancel_order(order)
        except Exception as exc:
            if getattr(exc, "execution_unknown", False) is True:
                try:
                    self.registered_sim_freeze(getattr(exc, "code", "cancel_unknown"))
                except Exception:
                    pass
            raise

    def cancel_order_ref(self, order_ref, dataname: Optional[str] = None):
        self._require_registered_sim_not_frozen()
        try:
            return super().cancel_order_ref(order_ref, dataname=dataname)
        except Exception as exc:
            if getattr(exc, "execution_unknown", False) is True:
                try:
                    self.registered_sim_freeze(getattr(exc, "code", "cancel_unknown"))
                except Exception:
                    pass
            raise


__all__ = [
    "RegisteredSimExecutionUnknown",
    "RegisteredSimDispatchEvidence",
    "RegisteredSimRouteEligibility",
    "RegisteredSimStore",
    "RegisteredSimWrapper",
]
