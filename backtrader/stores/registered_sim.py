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
import contextlib
import hashlib
import inspect
import json
import math
import re
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Dict, Optional, Tuple

from .btapistore import BtApiStore, BtApiStoreError, _ctp_order_route_invest_unit_id

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
_COMMISSION_QUERY_SNAPSHOT_LIMIT = 256
_REGISTERED_SIM_CAPACITY_ORDER_STATE_LIMIT = 100_000
_COMMISSION_REQUEST_FILTER_FIELDS = {
    "instrument_id": "InstrumentID",
    "exchange_id": "ExchangeID",
    "InstrumentID": "InstrumentID",
    "ExchangeID": "ExchangeID",
    "BrokerID": "BrokerID",
    "InvestorID": "InvestorID",
}


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
class RegisteredSimOrderIdentityQueryReceipt:
    """Current Store-owned complete orders query used for durable identity binding.

    This in-process receipt records a query that the Store revalidated against
    its live SDK session. It does not claim that the Journal independently
    authenticates a provider or the physical query source.
    """

    request_id: int
    connection_generation: int
    account_fingerprint: str
    trading_day: str
    started_at_utc: datetime
    completed_at_utc: datetime
    front_id: int
    session_id: int
    broker_id: str
    investor_id: str
    rows_sha256: str
    rows: Tuple[Mapping, ...]
    source_expires_monotonic: float
    _store: Any
    _issuer: Any


@dataclass(frozen=True)
class RegisteredSimCancelTarget:
    """Exact one-shot CTP target issued by a Journal-validated Store path."""

    order_ref: str
    order_sys_id: str
    instrument_id: str
    exchange_id: str
    broker_id: str
    investor_id: str
    front_id: int
    session_id: int
    account_fingerprint: str
    connection_generation: int
    trading_day: str
    query_request_id: int
    query_rows_sha256: str
    matched_row_sha256: str
    source_expires_monotonic: float
    _issuer: Any
    _seal: Any

    def __post_init__(self) -> None:
        for name in (
            "order_ref",
            "order_sys_id",
            "instrument_id",
            "exchange_id",
            "broker_id",
            "investor_id",
            "account_fingerprint",
            "query_rows_sha256",
            "matched_row_sha256",
        ):
            _exact_text(getattr(self, name), name)
        for name in (
            "front_id",
            "session_id",
            "connection_generation",
            "query_request_id",
        ):
            if not _positive_int(getattr(self, name)):
                raise ValueError("{} must be a positive int".format(name))
        if (
            type(self.trading_day) is not str
            or len(self.trading_day) != 8
            or not self.trading_day.isdigit()
        ):
            raise ValueError("trading_day must be an exact YYYYMMDD")
        if any(
            _HASH_RE.fullmatch(getattr(self, name)) is None
            for name in ("query_rows_sha256", "matched_row_sha256")
        ):
            raise ValueError("cancel target query digests must be lowercase SHA-256")
        if (
            type(self.source_expires_monotonic) not in (int, float)
            or not math.isfinite(self.source_expires_monotonic)
            or self.source_expires_monotonic <= 0
        ):
            raise ValueError("source_expires_monotonic must be a finite positive deadline")
        if self._issuer is None or self._seal is None:
            raise ValueError("cancel target requires its validated Store issuer")


@dataclass(frozen=True)
class RegisteredSimUnknownRetirement:
    """Result of retiring one exact, durably reconciled UNKNOWN insert."""

    status: str
    intent_id: str
    reconciliation_id: str
    disarmed: bool


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
    arm_template_configured: Optional[bool] = None
    arm_templates_configured: Optional[bool] = None
    arm_api_available: Optional[bool] = None
    current_session_account_fingerprint: Optional[str] = None
    current_session_connection_generation: Optional[int] = None
    current_session_trading_day: Optional[str] = None
    current_session_trading_ready: Optional[bool] = None
    current_session_front_id: Optional[int] = None
    current_session_id: Optional[int] = None
    current_session_read_only_ready: Optional[bool] = None
    native_admission_required: bool = True
    arm_template_membership: Optional[bool] = None


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


def _expected_session(value: Any) -> Dict[str, Any]:
    """Validate a decision's exact account/generation/day dispatch binding."""
    if not isinstance(value, Mapping):
        raise BtApiStoreError("registered-sim expected session identity is invalid")
    account = value.get("account_fingerprint")
    generation = value.get("connection_generation")
    trading_day = value.get("trading_day")
    if (
        not isinstance(account, str)
        or not account
        or account != account.strip()
        or type(generation) is not int
        or generation <= 0
        or not isinstance(trading_day, str)
        or re.fullmatch(r"[0-9]{8}", trading_day) is None
    ):
        raise BtApiStoreError("registered-sim expected session identity is invalid")
    front_id = value.get("front_id")
    session_id = value.get("session_id")
    if (front_id is None) != (session_id is None):
        raise BtApiStoreError("registered-sim expected session identity is invalid")
    if front_id is not None and (not _positive_int(front_id) or not _positive_int(session_id)):
        raise BtApiStoreError("registered-sim expected session identity is invalid")
    result = {
        "account_fingerprint": account,
        "connection_generation": generation,
        "trading_day": trading_day,
    }
    if front_id is not None:
        result.update({"front_id": front_id, "session_id": session_id})
    return result


def _canonical_sdk_session_getters(client: Any) -> Optional[Tuple[Any, Any, Any]]:
    """Return canonical session getters and their shared SDK lock, if exact."""
    module_name = type(client).__module__
    if module_name not in ("bt_api_ctp.ctp.client", "bt_api_py.ctp.client"):
        return None
    sdk_module = sys.modules.get(module_name)
    client_type = getattr(sdk_module, "TraderClient", None) if sdk_module else None
    if not isinstance(client_type, type) or type(client) is not client_type:
        return None
    scope_getter = getattr(client, "get_query_session_scope", None)
    state_getter = getattr(client, "get_session_state", None)
    if (
        not callable(scope_getter)
        or getattr(scope_getter, "__self__", None) is not client
        or getattr(scope_getter, "__func__", None)
        is not getattr(client_type, "get_query_session_scope", None)
        or not callable(state_getter)
        or getattr(state_getter, "__self__", None) is not client
        or getattr(state_getter, "__func__", None)
        is not getattr(client_type, "get_session_state", None)
    ):
        return None
    session_lock = getattr(client, "_query_state_lock", None)
    if (
        session_lock is None
        or type(session_lock) is not type(threading.RLock())
        or not callable(getattr(session_lock, "__enter__", None))
        or not callable(getattr(session_lock, "__exit__", None))
    ):
        return None
    return scope_getter, state_getter, session_lock


def _session_scope_state_snapshot(
    client: Any, *, require_canonical: bool = False
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Read detached scope/state projections as one session observation.

    The canonical SDK scope omits CTP FrontID/SessionID, so these must be
    paired with its session state under the same RLock used by the SDK login
    callback.  Non-SDK fake clients remain useful for ordinary, non-authority
    execution facts, but never satisfy ``require_canonical``.
    """
    canonical_module = type(client).__module__ in (
        "bt_api_ctp.ctp.client",
        "bt_api_py.ctp.client",
    )
    exact = _canonical_sdk_session_getters(client)
    if require_canonical and exact is None:
        return None
    if canonical_module and exact is None:
        return None
    if exact is not None:
        scope_method, state_method, session_lock = exact
        try:
            with session_lock:
                raw_scope = scope_method()
                raw_state = state_method()
                client_ready = getattr(client, "is_ready", None)
                scope = {
                    name: _read_fact(raw_scope, name)
                    for name in (
                        "account_fingerprint",
                        "connection_generation",
                        "trading_day",
                        "read_only_ready",
                        "issuer",
                        "broker_id",
                        "investor_id",
                        "user_id",
                    )
                }
                state = {
                    name: _read_fact(raw_state, name)
                    for name in (
                        "account_fingerprint",
                        "connection_generation",
                        "trading_day",
                        "trading_ready",
                        "read_only_ready",
                        "front_id",
                        "session_id",
                        "broker_id",
                        "investor_id",
                        "user_id",
                    )
                }
                state["client_is_ready"] = client_ready
        except Exception:
            return None
        return scope, state

    scope_method = getattr(client, "get_query_session_scope", None)
    state_method = getattr(client, "get_session_state", None)
    if not callable(scope_method) or not callable(state_method):
        return None
    try:
        raw_scope = scope_method()
        raw_state = state_method()
        scope = {
            name: _read_fact(raw_scope, name)
            for name in (
                "account_fingerprint",
                "connection_generation",
                "trading_day",
                "read_only_ready",
                "issuer",
                "broker_id",
                "investor_id",
                "user_id",
            )
        }
        state = {
            name: _read_fact(raw_state, name)
            for name in (
                "account_fingerprint",
                "connection_generation",
                "trading_day",
                "trading_ready",
                "read_only_ready",
                "front_id",
                "session_id",
                "broker_id",
                "investor_id",
                "user_id",
            )
        }
        state["client_is_ready"] = getattr(client, "is_ready", None)
    except Exception:
        return None
    return scope, state


def _empty_session_identity() -> Dict[str, Any]:
    return {
        "account_fingerprint": None,
        "connection_generation": None,
        "trading_day": None,
        "trading_ready": None,
        "read_only_ready": None,
        "front_id": None,
        "session_id": None,
    }


def _session_identity(client: Any) -> Dict[str, Any]:
    """Read the SDK's public live session identity without performing I/O."""
    snapshot = _session_scope_state_snapshot(client)
    if snapshot is None:
        return _empty_session_identity()
    scope, state = snapshot
    if not isinstance(scope, Mapping) or not isinstance(state, Mapping):
        return {
            **_empty_session_identity(),
        }
    scope_values = (
        _read_fact(scope, "account_fingerprint"),
        _read_fact(scope, "connection_generation"),
        _read_fact(scope, "trading_day"),
    )
    state_values = (
        _read_fact(state, "account_fingerprint"),
        _read_fact(state, "connection_generation"),
        _read_fact(state, "trading_day"),
    )
    values = scope_values if scope_values == state_values else (None, None, None)
    account, generation, trading_day = values
    identity_valid = (
        isinstance(account, str)
        and bool(account)
        and account == account.strip()
        and type(generation) is int
        and generation > 0
        and isinstance(trading_day, str)
        and re.fullmatch(r"[0-9]{8}", trading_day) is not None
    )
    ready = _read_fact(state, "trading_ready")
    front_id = _read_fact(state, "front_id")
    session_id = _read_fact(state, "session_id")
    return {
        "account_fingerprint": account if identity_valid else None,
        "connection_generation": generation if identity_valid else None,
        "trading_day": trading_day if identity_valid else None,
        "trading_ready": (
            ready
            if type(ready) is bool and _read_fact(state, "client_is_ready") is ready
            else None
        ),
        "read_only_ready": (
            _read_fact(scope, "read_only_ready")
            if type(_read_fact(scope, "read_only_ready")) is bool
            else None
        ),
        "front_id": front_id if _positive_int(front_id) else None,
        "session_id": session_id if _positive_int(session_id) else None,
    }


def _session_matches(
    current: Mapping, expected: Optional[Mapping], *, require_trading_ready: bool
) -> bool:
    if not isinstance(current, Mapping):
        return False
    if (
        not isinstance(current.get("account_fingerprint"), str)
        or not current.get("account_fingerprint")
        or type(current.get("connection_generation")) is not int
        or current.get("connection_generation") <= 0
        or not isinstance(current.get("trading_day"), str)
        or re.fullmatch(r"[0-9]{8}", current.get("trading_day", "")) is None
    ):
        return False
    if require_trading_ready and current.get("trading_ready") is not True:
        return False
    if expected is None:
        return True
    try:
        normalized = _expected_session(expected)
    except BtApiStoreError:
        return False
    return all(current.get(name) == value for name, value in normalized.items())


def _canonical_sdk_direct_grant_client(client: Any) -> Optional[Tuple[Any, Any]]:
    """Return the canonical SDK module/type for its one-contract direct grant."""
    module_name = type(client).__module__
    if module_name not in ("bt_api_ctp.ctp.client", "bt_api_py.ctp.client"):
        return None
    sdk_module = sys.modules.get(module_name)
    trader_client_type = getattr(sdk_module, "TraderClient", None) if sdk_module else None
    if not isinstance(trader_client_type, type) or type(client) is not trader_client_type:
        return None
    state_getter = getattr(client, "get_execution_gate_state", None)
    sdk_state_getter = getattr(trader_client_type, "get_execution_gate_state", None)
    scalar_armer = getattr(client, "arm_execution_for_registered_sim", None)
    sdk_scalar_armer = getattr(trader_client_type, "arm_execution_for_registered_sim", None)
    if (
        not callable(state_getter)
        or getattr(state_getter, "__func__", None) is not sdk_state_getter
        or not callable(sdk_scalar_armer)
        or getattr(scalar_armer, "__func__", None) is not sdk_scalar_armer
    ):
        return None
    return sdk_module, trader_client_type


def _canonical_sdk_route_instrument(
    client: Any,
    key: Tuple[str, str],
    *,
    bundle: bool,
) -> Optional[str]:
    canonical_client = _canonical_sdk_direct_grant_client(client)
    if canonical_client is None:
        return None
    sdk_module, _trader_client_type = canonical_client
    canonicalize = getattr(
        sdk_module,
        "canonical_ctp_bundle_instrument" if bundle else "canonical_ctp_instrument",
        None,
    )
    if not callable(canonicalize):
        return None
    try:
        result = canonicalize(key[0], key[1])
    except Exception:
        return None
    if type(result) is not str or not result or result != result.strip():
        return None
    return result


def _gate_state_snapshot(
    state: Any,
    key: Tuple[str, str],
    client: Any = None,
) -> Optional[Dict[str, Any]]:
    """Return an immutable route-bound snapshot of an armed SDK grant.

    The bundle contract keeps its full authorized-instrument set. The public
    direct registered-simulation SDK contract is a distinct single-contract
    grant; accept it only from the canonical TraderClient and only when its
    exchange-qualified SDK identity resolves to this exact Store route.
    """
    if (
        not isinstance(state, Mapping)
        or not isinstance(key, tuple)
        or len(key) != 2
        or not all(type(value) is str and value and value == value.strip() for value in key)
    ):
        return None

    authorized = state.get("authorized_instruments")
    scope_version = state.get("scope_version")
    sdk_instrument = state.get("instrument")
    canonical_client = _canonical_sdk_direct_grant_client(client)
    authorized_tuple: Optional[Tuple[str, ...]] = None
    grant_kind = "bundle"

    if scope_version is None and authorized is None:
        if canonical_client is None:
            return None
        expected_sdk_instrument = _canonical_sdk_route_instrument(
            client, key, bundle=False
        )
        if expected_sdk_instrument is None or sdk_instrument != expected_sdk_instrument:
            return None
        grant_kind = "direct_single_instrument"
    else:
        if not isinstance(authorized, (tuple, list)):
            return None
        authorized_tuple = tuple(authorized)
        if (
            not authorized_tuple
            or any(
                not isinstance(item, str) or not item or item != item.strip()
                for item in authorized_tuple
            )
            or len(set(authorized_tuple)) != len(authorized_tuple)
        ):
            return None
        expected_sdk_instrument = _canonical_sdk_route_instrument(
            client, key, bundle=True
        )
        if expected_sdk_instrument is None and canonical_client is None:
            expected_sdk_instrument = key[0]
        if expected_sdk_instrument is None:
            return None
        if (
            type(expected_sdk_instrument) is not str
            or not expected_sdk_instrument
            or sdk_instrument != expected_sdk_instrument
            or expected_sdk_instrument not in authorized_tuple
            or not isinstance(scope_version, str)
            or not scope_version
        ):
            return None

    proof_sha256 = state.get("proof_sha256")
    environment_profile = state.get("environment_profile")
    if (
        state.get("managed") is not True
        or state.get("armed") is not True
        or type(state.get("connection_generation")) is not int
        or state.get("connection_generation") <= 0
        or not isinstance(state.get("trading_day"), str)
        or re.fullmatch(r"[0-9]{8}", state.get("trading_day", "")) is None
        or not isinstance(proof_sha256, str)
        or _HASH_RE.fullmatch(proof_sha256) is None
        or not isinstance(environment_profile, str)
        or not environment_profile
        or "revocation_reason" not in state
        or state.get("revocation_reason") is not None
    ):
        return None

    # Keep the complete bundle scope. The scalar form is explicitly labelled
    # as one SDK-issued contract; no bundle scope or authorized list is
    # synthesized for it.
    return {
        "managed": True,
        "armed": True,
        "instrument": key[0],
        "sdk_instrument": sdk_instrument,
        "connection_generation": state["connection_generation"],
        "trading_day": state["trading_day"],
        "grant_kind": grant_kind,
        "scope_version": scope_version,
        "authorized_instruments": authorized_tuple,
        "environment_profile": environment_profile,
        "proof_sha256": proof_sha256,
        "revocation_reason": None,
    }


def _detached_gate_state(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Copy cached proof evidence without exposing its tuple-backed authority."""
    result = dict(snapshot)
    authorized = snapshot["authorized_instruments"]
    result["authorized_instruments"] = list(authorized) if authorized is not None else None
    return result


def _public_gate_projection(state: Any) -> Optional[Dict[str, Any]]:
    """Copy non-secret gate observations for a coherent Store facts snapshot."""
    if not isinstance(state, Mapping):
        return None
    authorized = state.get("authorized_instruments")
    if isinstance(authorized, (tuple, list)) and all(isinstance(item, str) for item in authorized):
        authorized = tuple(authorized)
    else:
        authorized = None
    return {
        "managed": state.get("managed") if type(state.get("managed")) is bool else None,
        "armed": state.get("armed") if type(state.get("armed")) is bool else None,
        "instrument": state.get("instrument") if isinstance(state.get("instrument"), str) else None,
        "connection_generation": state.get("connection_generation")
        if type(state.get("connection_generation")) is int
        else None,
        "trading_day": state.get("trading_day")
        if isinstance(state.get("trading_day"), str)
        else None,
        "authorized_instruments": authorized,
    }


def _order_expected_session(order: Any) -> Optional[Dict[str, Any]]:
    info = getattr(order, "info", {})
    getter = getattr(info, "get", None)
    if not callable(getter):
        return None
    factor_order = any(
        getter(name) is not None for name in ("factor_intent_id", "factor_cancel_intent_id")
    )
    fields = (
        getter("factor_session_account_fingerprint"),
        getter("factor_session_connection_generation"),
        getter("factor_session_trading_day"),
    )
    front_id = getter("factor_session_front_id")
    session_id = getter("factor_session_id")
    if all(value is None for value in fields):
        if factor_order:
            raise BtApiStoreError("factor order is missing its expected session identity")
        return None
    if factor_order and (not _positive_int(front_id) or not _positive_int(session_id)):
        raise BtApiStoreError("factor order is missing its expected session identity")
    expected = {
        "account_fingerprint": fields[0],
        "connection_generation": fields[1],
        "trading_day": fields[2],
    }
    if front_id is not None or session_id is not None:
        expected.update({"front_id": front_id, "session_id": session_id})
    return _expected_session(expected)


class _RegisteredSimPreDispatchRejected(BtApiStoreError):
    """A cancel was rejected before its native SDK call could start."""


def _supports_explicit_keyword(method: Any, name: str) -> bool:
    if not callable(method):
        return False
    try:
        parameter = inspect.signature(method).parameters.get(name)
    except (TypeError, ValueError):
        return False
    return parameter is not None and parameter.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )


def _mark_execution_unknown(error: BaseException, code: str) -> None:
    """Carry UNKNOWN through Store layers while preserving control exceptions."""

    try:
        setattr(error, "execution_unknown", True)
        setattr(error, "code", code)
    except BaseException:
        # The wrapper's frozen state is also checked by the Store boundary.
        pass


def _sdk_cancel_deadline_contract(client: Any, submit_method: Any = None) -> bool:
    """Require the exact SDK client and its native-boundary deadline contract.

    The contract is the canonical TraderClient implementation plus its typed
    deadline outcome/error API and explicit deadline arguments at both method
    boundaries. Duck-typed or instance-overridden methods are not a supported
    substitute, even when they accept a keyword with the same name.
    """

    module_name = type(client).__module__
    if module_name not in ("bt_api_ctp.ctp.client", "bt_api_py.ctp.client"):
        return False
    sdk_module = sys.modules.get(module_name)
    trader_client_type = getattr(sdk_module, "TraderClient", None) if sdk_module else None
    gate_error = getattr(sdk_module, "CtpExecutionGateError", None) if sdk_module else None
    deadline_error = (
        getattr(sdk_module, "_CtpNativeRequestDeadlineExpired", None) if sdk_module else None
    )
    dispatch_outcome_type = (
        getattr(sdk_module, "_CtpNativeRequestDispatchOutcome", None) if sdk_module else None
    )
    if (
        not isinstance(trader_client_type, type)
        or type(client) is not trader_client_type
        or not isinstance(gate_error, type)
        or gate_error.__module__ != module_name
        or not isinstance(deadline_error, type)
        or deadline_error.__module__ != module_name
        or not issubclass(deadline_error, gate_error)
        or not isinstance(dispatch_outcome_type, type)
        or dispatch_outcome_type.__module__ != module_name
        or "native_call_started"
        not in getattr(dispatch_outcome_type, "__dataclass_fields__", {})
    ):
        return False

    submit_method = (
        getattr(client, "submit_order_action", None)
        if submit_method is None
        else submit_method
    )
    sdk_submit = getattr(trader_client_type, "submit_order_action", None)
    getter = getattr(client, "get_order_action_evidence", None)
    sdk_getter = getattr(trader_client_type, "get_order_action_evidence", None)
    invoke = getattr(client, "_invoke_session_native_request", None)
    sdk_invoke = getattr(trader_client_type, "_invoke_session_native_request", None)
    if (
        not callable(sdk_submit)
        or getattr(submit_method, "__func__", None) is not sdk_submit
        or not _supports_explicit_keyword(submit_method, "deadline_monotonic")
        or not callable(sdk_getter)
        or getattr(getter, "__func__", None) is not sdk_getter
        or not callable(sdk_invoke)
        or getattr(invoke, "__func__", None) is not sdk_invoke
        or not _supports_explicit_keyword(invoke, "deadline_monotonic")
        or not _supports_explicit_keyword(invoke, "dispatch_outcome")
    ):
        return False

    return True


def _is_sdk_pre_dispatch_gate_error(
    error: BaseException,
    *,
    client: Any,
    request_id: Any,
    order_action_ref: Any,
) -> bool:
    """Accept canonical SDK gate failures only when its action row is absent.

    Class identity binds the error to the loaded SDK module; the evidence
    lookup distinguishes a gate rejection from the same exception escaping
    after ReqOrderAction was entered. Missing or unreadable evidence fails
    closed as ambiguous.
    """

    module_name = type(error).__module__
    if module_name not in ("bt_api_ctp.ctp.client", "bt_api_py.ctp.client"):
        return False
    sdk_module = sys.modules.get(module_name)
    gate_error = getattr(sdk_module, "CtpExecutionGateError", None) if sdk_module else None
    if (
        not isinstance(gate_error, type)
        or gate_error.__module__ != module_name
        or gate_error not in type(error).__mro__
        or not _sdk_cancel_deadline_contract(client)
        or type(request_id) is not int
        or request_id <= 0
        or type(order_action_ref) not in (int, str)
    ):
        return False
    evidence = client.get_order_action_evidence(
        request_id, order_action_ref=order_action_ref
    )
    return evidence is None


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


def _request_filter_map(value: Any) -> Optional[Dict[str, str]]:
    """Normalize immutable SDK request-filter pairs for an internal comparison."""

    if not isinstance(value, tuple):
        return None
    result = {}
    for pair in value:
        if (
            not isinstance(pair, tuple)
            or len(pair) != 2
            or type(pair[0]) is not str
            or type(pair[1]) is not str
        ):
            return None
        name = _COMMISSION_REQUEST_FILTER_FIELDS.get(pair[0])
        if name is None or name in result:
            return None
        result[name] = pair[1]
    return result


def _commission_request_filters_match(source: Any, scope: Any, filters: Mapping) -> bool:
    """Bind a fee result to the exact contract plus the current CTP identity."""

    instrument = filters.get("instrument_id")
    exchange = filters.get("exchange_id")
    broker_id = _read_fact(scope, "broker_id")
    investor_id = _read_fact(scope, "investor_id")
    if not all(
        isinstance(value, str) and value and value == value.strip()
        for value in (instrument, exchange, broker_id, investor_id)
    ):
        return False
    expected = {
        "InstrumentID": instrument,
        "ExchangeID": exchange,
        "BrokerID": broker_id,
        "InvestorID": investor_id,
    }
    intent = _request_filter_map(_read_fact(source, "request_intent_filters"))
    actual = _request_filter_map(_read_fact(source, "request_filters"))
    explicit = _read_fact(source, "explicit_request_filters")
    return bool(
        intent == expected
        and actual == expected
        and explicit == ()
    )


def _commission_rows_match_session(
    rows: Any, scope: Any, filters: Mapping
) -> bool:
    """Project only known CTP commission identities for the current session."""

    broker_id = _read_fact(scope, "broker_id")
    investor_id = _read_fact(scope, "investor_id")
    instrument = filters.get("instrument_id")
    exchange = filters.get("exchange_id")
    if not isinstance(rows, list) or not rows:
        return False
    for row in rows:
        if not isinstance(row, Mapping) or not (
            row.get("BrokerID") == broker_id
            and row.get("InstrumentID") == instrument
            and row.get("ExchangeID") == exchange
            and row.get("InvestUnitID") == ""
            and row.get("BizType") in {"1", "2"}
        ):
            return False
        investor_range = row.get("InvestorRange")
        row_investor = row.get("InvestorID")
        if investor_range == "1":
            if row_investor not in ("", "\x00", investor_id):
                return False
        elif investor_range == "3":
            if row_investor != investor_id:
                return False
        else:
            # Group membership and unknown range codes cannot be proved here.
            return False
    return True


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
    result: Any,
    family: str,
    attempt: int,
    expected_scope: Any,
    requested_filters: Optional[Mapping] = None,
) -> Dict[str, Any]:
    """Copy completion facts only from the current SDK's sealed query source."""
    records = _read_fact(result, "records")
    if records is None:
        records = _read_fact(result, "rows")
    public_rows = None
    if isinstance(records, (list, tuple)):
        public_rows = [
            BtApiStore._ctp_query_record_to_public(
                row,
                include_commission_fields=family == "instrument_commission_rate_result",
            )
            for row in records
        ]
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
        "source_session_identity_valid": False,
        "source_account_rows_identity_valid": False,
        "source_account_investor_mapping_valid": False,
        "source_request_filters_valid": None,
        "source_commission_rows_identity_valid": None,
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
    source_broker_id = _read_fact(source, "broker_id", _UNOBSERVED)
    source_investor_id = _read_fact(source, "investor_id", _UNOBSERVED)
    scope_generation = _read_fact(expected_scope, "connection_generation", _UNOBSERVED)
    scope_account = _read_fact(expected_scope, "account_fingerprint", _UNOBSERVED)
    scope_trading_day = _read_fact(expected_scope, "trading_day", _UNOBSERVED)
    scope_broker_id = _read_fact(expected_scope, "broker_id", _UNOBSERVED)
    scope_investor_id = _read_fact(expected_scope, "investor_id", _UNOBSERVED)
    source_session_identity_valid = bool(
        type(source_broker_id) is str
        and source_broker_id
        and source_broker_id == source_broker_id.strip()
        and source_broker_id == scope_broker_id
        and type(source_investor_id) is str
        and source_investor_id
        and source_investor_id == source_investor_id.strip()
        and source_investor_id == scope_investor_id
    )
    account_rows_identity_valid = bool(
        family == "account_result"
        and source_session_identity_valid
        and isinstance(public_rows, list)
        and public_rows
        and all(
            isinstance(row, Mapping)
            and row.get("BrokerID") == scope_broker_id
            and type(row.get("AccountID")) is str
            and bool(row.get("AccountID"))
            and row.get("AccountID") == row.get("AccountID").strip()
            for row in public_rows
        )
    )
    account_investor_mapping_valid = bool(
        account_rows_identity_valid
        and all(
            row.get("InvestorID") in (None, "", "\x00", scope_investor_id)
            for row in public_rows
        )
    )
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
    facts["source_records_sha256"] = source_digest if source_owned else None
    facts["source_expires_monotonic"] = source_expiry if source_owned else None
    facts["source_started_monotonic"] = source_started_monotonic if source_owned else None
    facts["source_completed_monotonic"] = source_completed_monotonic if source_owned else None
    facts["_source_issuer"] = expected_issuer if source_owned else None
    facts["source_session_identity_valid"] = source_session_identity_valid
    facts["source_account_rows_identity_valid"] = account_rows_identity_valid
    facts["source_account_investor_mapping_valid"] = account_investor_mapping_valid
    facts["source_request_filters_valid"] = (
        _commission_request_filters_match(source, expected_scope, requested_filters or {})
        if family == "instrument_commission_rate_result"
        else None
    )
    facts["source_commission_rows_identity_valid"] = (
        _commission_rows_match_session(public_rows, expected_scope, requested_filters or {})
        if family == "instrument_commission_rate_result"
        else None
    )
    facts["_source_broker_id"] = scope_broker_id if source_session_identity_valid else None
    facts["_source_investor_id"] = scope_investor_id if source_session_identity_valid else None
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
        self._registered_sim_arm_templates_sealed = False
        self._registered_sim_arm_templates_projection = (False, ())
        self._registered_sim_armed_key: Optional[Tuple[str, str]] = None
        self._registered_sim_expected_session: Optional[Dict[str, Any]] = None
        self._registered_sim_arm_history = collections.deque(maxlen=history_limit)
        self._registered_sim_dispatch_history = collections.deque(maxlen=history_limit)
        self._registered_sim_unknown_dispatch: Optional[RegisteredSimDispatchEvidence] = None
        # Targets are issued only by the Store after durable owner and current
        # complete-query checks.  Keep object identity, not dataclass equality,
        # as the one-shot authority so callers cannot reconstruct a target.
        self._registered_sim_cancel_targets: Dict[int, RegisteredSimCancelTarget] = {}
        self._registered_sim_active_cancel_target: Optional[RegisteredSimCancelTarget] = None
        self._registered_sim_retired_reconciliation_ids = collections.OrderedDict()
        self._registered_sim_dispatch_sequence = 0
        self._registered_sim_terminal_order_limit = terminal_limit
        self._order_state = collections.OrderedDict()
        self._dispatching_order_ids = set()

    @property
    def registered_sim_allow_writes(self) -> bool:
        """The immutable constructor-time shadow/write switch."""
        return self._registered_sim_allow_writes

    def configure_registered_sim_arm_templates(self, templates: Mapping) -> None:
        """Fix the wrapper-lifetime exact ``(InstrumentID, ExchangeID)`` allowlist."""
        if not isinstance(templates, Mapping):
            raise ValueError("registered-sim arm templates must be a mapping")
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
            if self._registered_sim_arm_templates_sealed:
                if prepared != self._registered_sim_arm_templates:
                    raise BtApiStoreError("registered-sim arm templates are immutable")
                return
            if self._registered_sim_capability is not None:
                raise BtApiStoreError("disarm before setting registered-sim arm templates")
            self._registered_sim_arm_templates = prepared
            self._registered_sim_arm_templates_sealed = True
            self._registered_sim_armed_key = None
            # Publish configuration state and its exact keys as one immutable
            # snapshot. Facts can read it while a native call holds the main
            # wrapper lock, without constructing an impossible bool/key pair.
            with self._registered_sim_observation_lock:
                self._registered_sim_arm_templates_projection = (True, tuple(prepared))

    def registered_sim_expected_session_scope(self, expected: Mapping):
        """Hold the wrapper lock while a write is bound to one query session."""
        expected_identity = _expected_session(expected)
        wrapper = self

        @contextlib.contextmanager
        def scope():
            with wrapper._registered_sim_lock:
                current = _session_identity(getattr(wrapper, "trader_client", None))
                if (
                    not _session_matches(current, expected_identity, require_trading_ready=True)
                    or current.get("read_only_ready") is not True
                ):
                    raise BtApiStoreError("registered-sim expected session identity is stale")
                prior = wrapper._registered_sim_expected_session
                if prior is not None and prior != expected_identity:
                    raise BtApiStoreError("registered-sim nested session identity conflicts")
                wrapper._registered_sim_expected_session = expected_identity
                try:
                    yield expected_identity
                finally:
                    wrapper._registered_sim_expected_session = prior

        return scope()

    def _require_expected_session_locked(self) -> Optional[Dict[str, Any]]:
        expected = self._registered_sim_expected_session
        if expected is None:
            return None
        current = _session_identity(getattr(self, "trader_client", None))
        if (
            not _session_matches(current, expected, require_trading_ready=True)
            or current.get("read_only_ready") is not True
        ):
            raise BtApiStoreError("registered-sim expected session identity changed")
        return expected

    def _sdk_gate_state_locked(self) -> Optional[Mapping]:
        client = getattr(self, "trader_client", None)
        try:
            method = (
                getattr(client, "get_execution_gate_state", None)
                if client is not None
                else None
            )
            if not callable(method):
                return None
            state = method()
        except BaseException as exc:
            reason = "native_gate_state_unobserved"
            self._registered_sim_frozen = True
            self._registered_sim_freeze_reason = reason
            try:
                self._disarm_locked(reason)
            except BaseException:
                # A failed observation already closed local admission. Preserve
                # the original SDK exception and never reuse the local token.
                pass
            if not isinstance(exc, Exception):
                raise
            return None
        return state if isinstance(state, Mapping) else None

    def _current_grant_matches_locked(
        self,
        key: Tuple[str, str],
        expected: Optional[Mapping],
        *,
        state: Any = _UNOBSERVED,
    ) -> bool:
        if not isinstance(key, tuple) or len(key) != 2:
            return False
        client = getattr(self, "trader_client", None)
        if state is _UNOBSERVED:
            state = self._sdk_gate_state_locked()
        cached_snapshot = _gate_state_snapshot(
            self._registered_sim_state, key, client=client
        )
        current_snapshot = _gate_state_snapshot(state, key, client=client)
        if (
            cached_snapshot is None
            or current_snapshot is None
            or cached_snapshot != current_snapshot
            or self._registered_sim_capability is None
            or self._registered_sim_armed_key != key
        ):
            return False
        current = _session_identity(client)
        if not _session_matches(current, expected, require_trading_ready=True):
            return False
        return current_snapshot["connection_generation"] == current.get(
            "connection_generation"
        ) and current_snapshot["trading_day"] == current.get("trading_day")

    def _require_armable_locked(self) -> None:
        if not self._registered_sim_allow_writes:
            raise BtApiStoreError("registered-sim writes are disabled in shadow mode")
        if self._registered_sim_frozen:
            raise BtApiStoreError("registered-sim native gate is frozen")

    def _freeze_after_admission_interruption_locked(self, reason: str) -> None:
        if not self._registered_sim_frozen or not self._registered_sim_freeze_reason:
            self._registered_sim_frozen = True
            self._registered_sim_freeze_reason = reason
        reason = self._registered_sim_freeze_reason
        if self._registered_sim_capability is not None:
            try:
                self._disarm_locked(reason)
            except BaseException:
                # Keep the original control exception and the local gate closed.
                pass

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
        expected = self._require_expected_session_locked()
        current = _session_identity(client)
        if not _session_matches(current, expected, require_trading_ready=True):
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
        except BaseException as exc:
            self._registered_sim_frozen = True
            self._registered_sim_freeze_reason = "native_admission_outcome_unknown"
            self._registered_sim_capability = None
            self._registered_sim_armed_key = None
            self._registered_sim_state = {}
            if not isinstance(exc, Exception):
                raise
            raise BtApiStoreError(
                "SDK registered-simulation admission failed ({})".format(type(exc).__name__)
            ) from None
        if not isinstance(admitted, tuple) or len(admitted) != 2 or admitted[0] is None:
            self._registered_sim_frozen = True
            self._registered_sim_freeze_reason = "native_admission_result_unobserved"
            self._registered_sim_capability = None
            self._registered_sim_armed_key = None
            self._registered_sim_state = {}
            raise BtApiStoreError("SDK registered-simulation admission returned no capability")
        capability, state = admitted
        route_key = (instrument_id, exchange_id)
        self._registered_sim_capability = capability
        self._registered_sim_armed_key = route_key
        try:
            admitted_snapshot = _gate_state_snapshot(state, route_key, client=client)
            if (
                admitted_snapshot is None
                or admitted_snapshot["connection_generation"]
                != current.get("connection_generation")
                or admitted_snapshot["trading_day"] != current.get("trading_day")
            ):
                self._registered_sim_frozen = True
                self._registered_sim_freeze_reason = "native_admission_state_unobserved"
                raise BtApiStoreError("SDK registered-simulation admission state is not armed")
            current_gate_state = self._sdk_gate_state_locked()
            current_gate_snapshot = _gate_state_snapshot(
                current_gate_state, route_key, client=client
            )
            if current_gate_snapshot != admitted_snapshot:
                self._registered_sim_frozen = True
                self._registered_sim_freeze_reason = "native_admission_proof_changed"
                raise BtApiStoreError("SDK registered-simulation proof changed during admission")
            current_after = _session_identity(client)
            if not _session_matches(current_after, current, require_trading_ready=True):
                self._registered_sim_frozen = True
                self._registered_sim_freeze_reason = "session_changed_during_native_admission"
                raise BtApiStoreError("CTP session changed during registered-sim admission")
            # Retain the provider's public state shape so the next revalidation
            # runs the same canonical identity check as the admission check. The
            # normalized snapshot is returned only as a detached observation.
            self._registered_sim_state = dict(current_gate_state)
            self._registered_sim_arm_history.append(
                {"instrument": instrument_id, "exchange": exchange_id, "at_epoch": time.time()}
            )
            return {
                "armed": True,
                "instrument": instrument_id,
                "exchange_id": exchange_id,
                "switched": switched,
                "state": _detached_gate_state(self._registered_sim_state),
            }
        except BaseException:
            if not self._registered_sim_frozen:
                self._registered_sim_frozen = True
                self._registered_sim_freeze_reason = "native_admission_verification_failed"
            if self._registered_sim_capability is not None:
                try:
                    self._disarm_locked(self._registered_sim_freeze_reason)
                except BaseException:
                    # Do not mask the admission/readback failure with revocation.
                    pass
            raise

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
            try:
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
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    self._freeze_after_admission_interruption_locked(
                        "native_admission_interrupted"
                    )
                raise

    def _disarm_locked(self, reason: str) -> Dict[str, Any]:
        client = getattr(self, "trader_client", None)
        capability = self._registered_sim_capability
        self._registered_sim_capability = None
        self._registered_sim_armed_key = None
        self._registered_sim_state = {}
        if capability is None:
            return {"disarmed": True, "reason": reason, "native": False}
        disarm = getattr(client, "disarm_execution_gate", None) if client is not None else None
        if not callable(disarm):
            self._registered_sim_frozen = True
            self._registered_sim_freeze_reason = "native_disarm_unavailable"
            raise BtApiStoreError("SDK native disarm is unavailable; gate frozen")
        try:
            state = disarm(capability, reason)
        except BaseException as exc:
            self._registered_sim_frozen = True
            self._registered_sim_freeze_reason = "native_disarm_failed"
            if not isinstance(exc, Exception):
                raise
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
            try:
                self._require_armable_locked()
                expected = self._require_expected_session_locked()
                current = _session_identity(getattr(self, "trader_client", None))
                if not _session_matches(current, expected, require_trading_ready=True):
                    raise BtApiStoreError("CTP trader session is not trading ready")
                templates_configured = self._registered_sim_arm_templates_sealed
                template = self._registered_sim_arm_templates.get(key)
                if templates_configured and template is None:
                    raise BtApiStoreError("registered-sim arm template is missing for outbound leg")
                if self._current_grant_matches_locked(key, expected):
                    return {"armed": True, "instrument": instrument_id, "switched": False}
                sdk_gate = self._sdk_gate_state_locked()
                if sdk_gate is None:
                    raise BtApiStoreError("SDK registered-simulation grant state is unobserved")
                sdk_armed = sdk_gate.get("armed")
                if sdk_armed is True:
                    if self._registered_sim_capability is None:
                        raise BtApiStoreError("SDK has an unowned registered-simulation grant")
                    local_key = self._registered_sim_armed_key
                    if not self._current_grant_matches_locked(local_key, expected):
                        raise BtApiStoreError("SDK registered-simulation grant is stale or mismatched")
                    switched = local_key != key
                    self._disarm_locked("registered_sim_instrument_switch")
                elif sdk_armed is False:
                    # An explicit unarmed observation means a local token may have
                    # been revoked by reconnect or SDK cleanup. Never reuse it.
                    switched = self._registered_sim_armed_key is not None
                    self._registered_sim_capability = None
                    self._registered_sim_armed_key = None
                    self._registered_sim_state = {}
                else:
                    raise BtApiStoreError("SDK registered-simulation grant state is malformed")
                if not templates_configured:
                    raise BtApiStoreError("no exact registered-sim template can arm this route")
                return self._arm_locked(
                    instrument_id,
                    exchange_id,
                    md_front=template["md_front"],
                    strategy_identity_sha256=template["strategy_identity_sha256"],
                    execution_cycle_id=template["execution_cycle_id"],
                    preflight_sha256=template["preflight_sha256"],
                    switched=switched,
                )
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    self._freeze_after_admission_interruption_locked(
                        "native_arm_switch_interrupted"
                    )
                raise

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

    def retire_registered_sim_unknown(
        self,
        intent_id: str,
        reconciliation_id: str,
        *,
        original_identity: Mapping[str, Any],
        expected_session: Mapping[str, Any],
        terminal_event: Optional[Mapping[str, Any]],
    ) -> RegisteredSimUnknownRetirement:
        """Retire only the matching UNKNOWN latch after durable query proof.

        The coordinator has already committed the terminal reconciliation and
        order-owner release. This method binds that receipt to the exact
        in-memory native attempt, keeps the SDK disarmed, and publishes a
        terminal no-fill update through the API event queue before retiring
        the UNKNOWN latch. It never calls a native order method or reconstructs
        an old Order.
        """
        intent_id = _exact_text(intent_id, "intent_id")
        reconciliation_id = _exact_text(reconciliation_id, "reconciliation_id")
        if not isinstance(original_identity, Mapping):
            raise BtApiStoreError("registered-sim original intent identity is invalid")
        original = dict(original_identity)
        expected = _expected_session(expected_session)
        if expected.get("front_id") is None or expected.get("session_id") is None:
            raise BtApiStoreError("registered-sim current session IDs are unavailable")
        order_ref = _exact_text(original.get("order_ref"), "original OrderRef")
        instrument = _exact_text(original.get("instrument_id"), "original InstrumentID")
        exchange = _exact_text(original.get("exchange_id"), "original ExchangeID")
        operation = original.get("operation")
        if operation not in ("insert", "cancel"):
            raise BtApiStoreError("registered-sim original operation is invalid")
        owner_intent_id = original.get("owner_intent_id")
        original_front = original.get("front_id")
        original_session = original.get("session_id")
        original_account = original.get("account_fingerprint")
        original_generation = original.get("connection_generation")
        original_day = original.get("trading_day")
        if (
            (
                operation == "cancel"
                and (
                    not isinstance(owner_intent_id, str)
                    or not owner_intent_id
                    or owner_intent_id != owner_intent_id.strip()
                )
            )
            or not isinstance(original_account, str)
            or not original_account
            or original_account != original_account.strip()
            or original_account != expected["account_fingerprint"]
            or not _positive_int(original_generation)
            or not isinstance(original_day, str)
            or re.fullmatch(r"[0-9]{8}", original_day) is None
            or original_day != expected["trading_day"]
            or not _positive_int(original_front)
            or not _positive_int(original_session)
        ):
            raise BtApiStoreError("registered-sim original native session IDs are invalid")
        if terminal_event is not None:
            if not isinstance(terminal_event, Mapping):
                raise BtApiStoreError("registered-sim terminal event is invalid")
            event = copy.deepcopy(dict(terminal_event))
            details = event.get("details")
            if not isinstance(details, Mapping):
                raise BtApiStoreError("registered-sim terminal event details are invalid")
            raw_status = details.get("OrderStatus")
            if operation == "cancel":
                terminal_status_matches = (
                    event.get("status") == "canceled"
                    and raw_status in ("5", "CANCELED", "canceled", "cancelled")
                    and event.get("factor_intent_id") == owner_intent_id
                    and event.get("factor_cancel_intent_id") == intent_id
                )
            else:
                terminal_status_matches = (
                    event.get("status") == "canceled"
                    and raw_status in ("5", "CANCELED", "canceled", "cancelled")
                ) or (
                    event.get("status") == "rejected"
                    and raw_status in ("4", "NO_TRADE_NOT_QUEUEING", "no_trade_not_queueing")
                )
            if (
                event.get("kind") != "order"
                or type(event.get("bt_order_ref")) is not int
                or event.get("bt_order_ref") != original.get("backtrader_order_ref")
                or event.get("order_ref") != order_ref
                or event.get("instrument") != instrument
                or event.get("exchange_id") != exchange
                or event.get("front_id") != original_front
                or event.get("session_id") != original_session
                or event.get("status")
                not in (("canceled",) if operation == "cancel" else ("canceled", "rejected"))
                or event.get("terminal_confirmed") is not True
                or event.get("execution_unknown") is not False
                or event.get("filled") != 0
                or type(event.get("size")) is not int
                or event.get("size") <= 0
                or event.get("remaining") != event.get("size")
                or details.get("OrderRef") != order_ref
                or details.get("InstrumentID") != instrument
                or details.get("ExchangeID") != exchange
                or details.get("FrontID") != original_front
                or details.get("SessionID") != original_session
                or not terminal_status_matches
                or details.get("VolumeTotalOriginal") != event.get("size")
                or details.get("VolumeTraded") != 0
                or details.get("VolumeTotal") != event.get("size")
            ):
                raise BtApiStoreError("registered-sim terminal event identity is invalid")
        else:
            event = None

        client = getattr(self, "trader_client", None)
        with self._registered_sim_lock:
            current = _session_identity(client)
            if (
                not _session_matches(current, expected, require_trading_ready=False)
                or current.get("read_only_ready") is not True
            ):
                raise BtApiStoreError("registered-sim recovery session identity is stale")
            sdk_gate = self._sdk_gate_state_locked()
            if not isinstance(sdk_gate, Mapping) or sdk_gate.get("armed") is not False:
                raise BtApiStoreError("registered-sim recovery requires an observed disarmed SDK")
            if (
                self._registered_sim_capability is not None
                or self._registered_sim_armed_key is not None
            ):
                raise BtApiStoreError("registered-sim recovery found an active local capability")
            if self._dispatching_order_ids:
                raise BtApiStoreError("registered-sim recovery is blocked by an active dispatch")
            retired_identity = (
                intent_id,
                operation,
                owner_intent_id,
                original_account,
                original_generation,
                original_day,
                instrument,
                exchange,
                order_ref,
                original_front,
                original_session,
            )
            previously_retired = self._registered_sim_retired_reconciliation_ids.get(
                reconciliation_id
            )
            if previously_retired is not None:
                if previously_retired != retired_identity:
                    raise BtApiStoreError("registered-sim retirement identity conflicts")
                unknown_ids = [
                    key for key, state in self._order_state.items() if state == "unknown"
                ]
                local_order_state = self._order_state.get(order_ref)
                if (
                    self._registered_sim_unknown_dispatch is not None
                    or self._registered_sim_frozen
                    or unknown_ids
                    or (event is not None and local_order_state not in (None, "terminal"))
                ):
                    raise BtApiStoreError("registered-sim recovery cannot clear another freeze")
                return RegisteredSimUnknownRetirement(
                    "ALREADY_ABSENT", intent_id, reconciliation_id, True
                )

            unknown = self._registered_sim_unknown_dispatch
            if unknown is None:
                unknown_ids = [
                    key for key, state in self._order_state.items() if state == "unknown"
                ]
                local_order_state = self._order_state.get(order_ref)
                if (
                    self._registered_sim_frozen
                    or unknown_ids
                    or (event is not None and local_order_state not in (None, "terminal"))
                ):
                    raise BtApiStoreError("registered-sim recovery cannot clear another freeze")
                # A fresh process has no historical Backtrader Order to update.
                # Never reconstruct or enqueue a historical event in that case.
                status = "ALREADY_ABSENT"
            else:
                if (
                    self._registered_sim_frozen is not True
                    or self._registered_sim_freeze_reason
                    != "registered_sim_{}_unknown".format(operation)
                    or unknown.operation != operation
                    or unknown.status != "UNKNOWN"
                    or unknown.order_ref != order_ref
                    or unknown.instrument_id != instrument
                    or unknown.exchange_id != exchange
                    # CThostFtdcInputOrderField has no FrontID/SessionID, so an
                    # UNKNOWN insert can only record what the SDK actually
                    # observed. Compare only recorded fields, matching the
                    # dispatch-lineage rule; a cancel (InputOrderActionField)
                    # still records and must match both exactly.
                    or (unknown.front_id is not None and unknown.front_id != original_front)
                    or (unknown.session_id is not None and unknown.session_id != original_session)
                    or unknown.resend_permitted is not False
                ):
                    raise BtApiStoreError("registered-sim UNKNOWN latch does not match proof")
                unknown_ids = [
                    key for key, state in self._order_state.items() if state == "unknown"
                ]
                if unknown_ids != [order_ref] or self._order_state.get(order_ref) != "unknown":
                    raise BtApiStoreError("registered-sim UNKNOWN order state is inconsistent")
                if event is not None:
                    updates = getattr(self, "_order_updates", None)
                    notifier = getattr(self, "_notify_live_bar_event", None)
                    if not isinstance(updates, collections.deque) or not callable(notifier):
                        raise BtApiStoreError("registered-sim Broker update queue is unavailable")
                    try:
                        updates.append(event)
                    except Exception as exc:
                        # Keep the exact UNKNOWN latch and freeze intact. The
                        # same durable reconciliation can safely retry enqueue.
                        raise BtApiStoreError(
                            "registered-sim Broker update enqueue failed ({})".format(
                                type(exc).__name__
                            )
                        ) from None
                    status = "QUEUED"
                else:
                    status = "ALREADY_ABSENT"
                self._registered_sim_dispatch_history.append(unknown)
                self._registered_sim_unknown_dispatch = None
                self._order_state.pop(order_ref, None)
                self._remember_order_state_locked(order_ref, "terminal")
                self._registered_sim_frozen = False
                self._registered_sim_freeze_reason = ""

            self._registered_sim_retired_reconciliation_ids[reconciliation_id] = retired_identity
            self._registered_sim_retired_reconciliation_ids.move_to_end(reconciliation_id)
            while len(self._registered_sim_retired_reconciliation_ids) > 4096:
                self._registered_sim_retired_reconciliation_ids.popitem(last=False)
            if status == "QUEUED":
                try:
                    notifier()
                except Exception:
                    # The exact terminal event remains in the normal poll
                    # queue; a wake failure cannot make it safe to enqueue twice.
                    pass
            return RegisteredSimUnknownRetirement(status, intent_id, reconciliation_id, True)

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
        expected = self._require_expected_session_locked()
        if self._registered_sim_arm_templates_sealed and expected is None:
            raise BtApiStoreError(
                "template-bound native dispatch requires decision session identity"
            )
        if self._registered_sim_arm_templates_sealed:
            template = self._registered_sim_arm_templates.get(key)
            if template is None:
                raise BtApiStoreError("outbound leg has no exact registered-sim arm template")
            self.ensure_registered_sim_arm_for(*key)
        if not self._current_grant_matches_locked(key, expected):
            raise BtApiStoreError(
                "registered-sim capability is not current for outbound instrument"
            )
        unit_id = getattr(field, "InvestUnitID", _UNOBSERVED)
        expected_unit_id = _ctp_order_route_invest_unit_id(*key)
        if unit_id is not _UNOBSERVED and (
            type(unit_id) is not str or unit_id != expected_unit_id
        ):
            raise BtApiStoreError("registered-sim outbound unit does not match its CTP route")
        return key

    def registered_sim_write_route_invest_unit_id(
        self, instrument_id: str, exchange_id: str
    ) -> Optional[str]:
        """Return the sealed target route's unit for source-owned fee queries.

        A sealed template authorizes one exact future route, while the SDK
        capability itself remains single-instrument and is checked again at
        native dispatch.  Fee reads may cover more than the currently armed
        route because the native InputOrder writer and this proof share the
        same fixed InvestUnitID helper.
        """

        try:
            key = (
                _exact_text(instrument_id, "InstrumentID"),
                _exact_text(exchange_id, "ExchangeID"),
            )
        except (TypeError, ValueError):
            return None
        with self._registered_sim_lock:
            if (
                not self._registered_sim_allow_writes
                or self._registered_sim_frozen
                or not self._registered_sim_arm_templates_sealed
                or key not in self._registered_sim_arm_templates
            ):
                return None
            try:
                expected = self._require_expected_session_locked()
                current = _session_identity(getattr(self, "trader_client", None))
                template = self._registered_sim_arm_templates[key]
                template_is_valid = (
                    isinstance(template, Mapping)
                    and type(template.get("md_front")) is str
                    and bool(template.get("md_front"))
                    and type(template.get("strategy_identity_sha256")) is str
                    and _HASH_RE.fullmatch(template["strategy_identity_sha256"]) is not None
                    and type(template.get("execution_cycle_id")) is str
                    and bool(template.get("execution_cycle_id"))
                    and type(template.get("preflight_sha256")) is str
                    and _HASH_RE.fullmatch(template["preflight_sha256"]) is not None
                )
                if (
                    not template_is_valid
                    or current.get("read_only_ready") is not True
                    or not _session_matches(current, expected, require_trading_ready=True)
                ):
                    return None
                unit_id = _ctp_order_route_invest_unit_id(*key)
                if type(unit_id) is not str:
                    return None
            except Exception:
                return None
            return unit_id

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
        except BaseException:
            pass

    def _discard_registered_sim_cancel_target(self, target: Any) -> None:
        with self._registered_sim_lock:
            if (
                type(target) is RegisteredSimCancelTarget
                and self._registered_sim_cancel_targets.get(id(target)) is target
            ):
                self._registered_sim_cancel_targets.pop(id(target), None)

    def cancel_order(
        self,
        order_ref: Any,
        dataname: Optional[str] = None,
        *,
        registered_sim_cancel_target: Any = None,
    ) -> Any:
        """Validate a one-shot Store target before entering the CTP client."""
        if registered_sim_cancel_target is None:
            return super().cancel_order(order_ref, dataname=dataname)
        target = registered_sim_cancel_target
        with self._registered_sim_lock:
            if (
                type(target) is not RegisteredSimCancelTarget
                or type(target._issuer) is not RegisteredSimStore
                or target._issuer._api is not self
                or target._seal is not target._issuer._registered_sim_cancel_target_seal
                or time.monotonic() >= target.source_expires_monotonic
                or self._registered_sim_cancel_targets.get(id(target)) is not target
                or type(order_ref) is not str
                or order_ref != target.order_ref
                or dataname != "{}.{}".format(target.exchange_id, target.instrument_id)
                or self._registered_sim_active_cancel_target is not None
            ):
                raise BtApiStoreError("registered-sim cancel target is not Store-issued")
            expected = self._require_expected_session_locked()
            if not isinstance(expected, Mapping) or any(
                expected.get(name) != getattr(target, name)
                for name in (
                    "account_fingerprint",
                    "connection_generation",
                    "trading_day",
                    "front_id",
                    "session_id",
                )
            ):
                raise BtApiStoreError("registered-sim cancel target session changed")
            key = (target.instrument_id, target.exchange_id)
            if not self._current_grant_matches_locked(key, expected):
                raise BtApiStoreError("registered-sim cancel target route grant changed")
            self._registered_sim_active_cancel_target = target
            try:
                return super().cancel_order(
                    order_ref,
                    dataname=dataname,
                    registered_sim_cancel_target=target,
                )
            finally:
                self._registered_sim_active_cancel_target = None
                self._registered_sim_cancel_targets.pop(id(target), None)

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
            target = self._registered_sim_active_cancel_target
            if operation == "cancel" and target is not None and not (
                type(target) is RegisteredSimCancelTarget
                and type(target._issuer) is RegisteredSimStore
                and target._issuer._api is self
                and target._seal is target._issuer._registered_sim_cancel_target_seal
                and time.monotonic() < target.source_expires_monotonic
                and getattr(field, "InstrumentID", None) == target.instrument_id
                and getattr(field, "ExchangeID", None) == target.exchange_id
                and getattr(field, "OrderRef", None) == target.order_ref
                and getattr(field, "OrderSysID", None) == target.order_sys_id
                and getattr(field, "FrontID", None) == target.front_id
                and getattr(field, "SessionID", None) == target.session_id
                and getattr(field, "BrokerID", None) == target.broker_id
                and getattr(field, "InvestorID", None) == target.investor_id
                and getattr(field, "OrderActionRef", None) == req_id
                and getattr(field, "ActionFlag", None) == "0"
                and getattr(self, "_registered_sim_cancel_targets", {}).get(id(target)) is target
                and (target.instrument_id, target.exchange_id) == self._outbound_key_locked(field)
            ):
                raise BtApiStoreError("native CTP Action differs from its verified cancel target")
            state_ref = order_ref or "UNKNOWN-{}-{}".format(operation, req_id)
            key = self._outbound_key_locked(field)
            capability = self._registered_sim_capability
            client = getattr(self, "trader_client", None)
            method_name = "submit_order_insert" if operation == "insert" else "submit_order_action"
            method = getattr(client, method_name, None) if client is not None else None
            if not callable(method):
                raise BtApiStoreError("SDK native {} capability is unavailable".format(operation))
            if operation == "cancel" and target is not None and not _sdk_cancel_deadline_contract(
                client, method
            ):
                raise BtApiStoreError(
                    "SDK native cancel does not explicitly support query deadlines "
                    "through the verified native boundary"
                )
            self._require_expected_session_locked()
            if not self._current_grant_matches_locked(key, self._registered_sim_expected_session):
                raise BtApiStoreError("registered-sim grant changed before native dispatch")
            with self._registered_sim_observation_lock:
                self._dispatching_order_ids.add(state_ref)
            try:
                if (
                    operation == "cancel"
                    and target is not None
                    and time.monotonic() >= target.source_expires_monotonic
                ):
                    raise _RegisteredSimPreDispatchRejected(
                        "registered-sim order query expired before native Action submission"
                    )
                if operation == "cancel" and target is not None:
                    result = method(
                        field,
                        req_id,
                        execution_capability=capability,
                        deadline_monotonic=target.source_expires_monotonic,
                    )
                else:
                    result = method(field, req_id, execution_capability=capability)
            except _RegisteredSimPreDispatchRejected:
                raise
            except BaseException as exc:
                if operation == "cancel" and target is not None:
                    try:
                        pre_dispatch_gate = _is_sdk_pre_dispatch_gate_error(
                            exc,
                            client=client,
                            request_id=req_id,
                            order_action_ref=getattr(field, "OrderActionRef", None),
                        )
                    except BaseException as proof_error:
                        evidence = self._make_dispatch_evidence_locked(
                            operation,
                            "UNKNOWN",
                            field,
                            req_id,
                            key[0],
                            key[1],
                            error_type=type(proof_error).__name__,
                        )
                        self._freeze_after_unknown_locked(evidence, state_ref)
                        if isinstance(proof_error, Exception):
                            raise RegisteredSimExecutionUnknown(evidence) from None
                        _mark_execution_unknown(
                            proof_error,
                            "registered_sim_{}_unknown".format(operation),
                        )
                        raise
                    if pre_dispatch_gate:
                        raise _RegisteredSimPreDispatchRejected(
                            "SDK rejected registered-sim session before native dispatch"
                        ) from None
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
                if isinstance(exc, Exception):
                    raise RegisteredSimExecutionUnknown(evidence) from None
                _mark_execution_unknown(
                    exc,
                    "registered_sim_{}_unknown".format(operation),
                )
                raise
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
        # Keep the dispatching fast path nonblocking while reading configuration
        # and keys as one atomically-published snapshot.
        with self._registered_sim_observation_lock:
            templates_configured, template_keys = self._registered_sim_arm_templates_projection
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
                "current_grant_matches_sdk": None,
                "sdk_gate_projection": None,
                "arm_templates_configured": templates_configured,
                "arm_template_keys": template_keys,
            }

        # Recheck after acquiring the main state lock. A dispatch may start
        # after the fast projection above; preserve the established lock order
        # and never expose order IDs from an in-flight transition.
        with self._registered_sim_lock:
            with self._registered_sim_observation_lock:
                templates_configured, template_keys = self._registered_sim_arm_templates_projection
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
                    "current_grant_matches_sdk": None,
                    "sdk_gate_projection": None,
                    "arm_templates_configured": templates_configured,
                    "arm_template_keys": template_keys,
                }
            unknown_ids = [
                order_ref for order_ref, state in self._order_state.items() if state == "unknown"
            ]
            sdk_gate_state = self._sdk_gate_state_locked()
            current_grant_matches = (
                self._current_grant_matches_locked(
                    self._registered_sim_armed_key, None, state=sdk_gate_state
                )
                if self._registered_sim_armed_key is not None
                else False
            )
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
                "current_grant_matches_sdk": current_grant_matches,
                "sdk_gate_projection": _public_gate_projection(sdk_gate_state),
                "arm_templates_configured": templates_configured,
                "arm_template_keys": template_keys,
            }

    def registered_sim_order_capacity_facts(self) -> Dict[str, Any]:
        """Project count-only order state under the existing state locks.

        The state lock is acquired without waiting so a sampler cannot stall a
        live callback behind an in-flight native call.  Dispatching identities
        are counted under their existing observation lock; no order IDs or
        provider payloads leave this method.
        """
        state_lock = getattr(self, "_registered_sim_lock", None)
        observation_lock = getattr(self, "_registered_sim_observation_lock", None)
        projection_schema = "backtrader.registered_sim_order_capacity.v1"
        if state_lock is None or observation_lock is None:
            return {
                "schema": projection_schema,
                "status": "UNAVAILABLE",
                "reason_code": "state_lock_missing",
            }
        if not state_lock.acquire(blocking=False):
            return {
                "schema": projection_schema,
                "status": "UNAVAILABLE",
                "reason_code": "state_lock_busy",
            }
        try:
            if not observation_lock.acquire(blocking=False):
                return {
                    "schema": projection_schema,
                    "status": "UNAVAILABLE",
                    "reason_code": "observation_lock_busy",
                }
            try:
                order_state = self._order_state
                dispatching = self._dispatching_order_ids
                terminal_limit = self._registered_sim_terminal_order_limit
                if not isinstance(order_state, collections.OrderedDict):
                    return {
                        "schema": projection_schema,
                        "status": "UNAVAILABLE",
                        "reason_code": "order_state_unavailable",
                    }
                if not isinstance(dispatching, set):
                    return {
                        "schema": projection_schema,
                        "status": "UNAVAILABLE",
                        "reason_code": "dispatch_state_unavailable",
                    }
                if len(dispatching) > 0:
                    return {
                        "schema": projection_schema,
                        "status": "UNAVAILABLE",
                        "reason_code": "native_dispatch_in_progress",
                        "dispatching_order_count": len(dispatching),
                    }
                if type(terminal_limit) is not int or terminal_limit <= 0:
                    return {
                        "schema": projection_schema,
                        "status": "UNAVAILABLE",
                        "reason_code": "terminal_limit_unavailable",
                    }
                if len(order_state) > _REGISTERED_SIM_CAPACITY_ORDER_STATE_LIMIT:
                    return {
                        "schema": projection_schema,
                        "status": "UNAVAILABLE",
                        "reason_code": "order_state_scan_bound_exceeded",
                    }
                counts = {"active": 0, "unknown": 0, "terminal": 0}
                for state in order_state.values():
                    if state not in counts:
                        return {
                            "schema": projection_schema,
                            "status": "UNAVAILABLE",
                            "reason_code": "unknown_order_state",
                        }
                    counts[state] += 1
                dispatching_count = len(dispatching)
                terminal_respected = counts["terminal"] <= terminal_limit
                return {
                    "schema": projection_schema,
                    "status": "OBSERVED" if terminal_respected else "UNSTABLE_OR_OVER_CAPACITY",
                    "active_order_count": counts["active"],
                    "unknown_order_count": counts["unknown"],
                    "terminal_order_count": counts["terminal"],
                    "dispatching_order_count": dispatching_count,
                    "active_unknown_limit": None,
                    "active_unknown_bounded": False,
                    "terminal_order_limit": terminal_limit,
                    "terminal_limit_respected": terminal_respected,
                }
            finally:
                observation_lock.release()
        finally:
            state_lock.release()


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
        self._registered_sim_cancel_target_seal = object()
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
        # The optional per-target commission sidecar has its own bounded LRU
        # so a wide target pool cannot evict one of the five core seal rows.
        self._ctp_commission_query_snapshots = collections.OrderedDict()
        self._ctp_query_instrument_rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # Live instrument queries are product-scoped.  Keep the latest facts
        # and contributed row keys per exact native (exchange, product) scope
        # so one product's refresh cannot erase another's observed metadata.
        self._ctp_query_instrument_scopes: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        self._ctp_query_instrument_scope_rows: Dict[
            Tuple[str, str], Tuple[Tuple[str, str], ...]
        ] = {}

    @staticmethod
    def _project_trade_driven_order(update: Any, *, order_row: bool = False) -> Any:
        """Bind order status projections to this route's CTP trade-fill contract.

        CTP order callbacks expose cumulative traded volume and the order's
        limit price, while the matching trade callback supplies the actual
        execution price and identity.  Consequently RegisteredSim orders must
        wait for trade callbacks before accounting fills.  Keep this
        classification at the provider-specific Store boundary so generic
        providers retain their own cumulative-fill semantics.
        """
        if not isinstance(update, Mapping):
            return update
        if not order_row and update.get("kind") != "order":
            return update

        source = update.get("execution_source")
        if source not in (None, "trades"):
            raise BtApiStoreError(
                "registered-sim CTP order execution source conflicts with trade callbacks"
            )
        projected = dict(update)
        projected["execution_source"] = "trades"
        return projected

    def poll_broker_update(self):
        """Return CTP broker updates with the RegisteredSim fill mode bound."""
        update = super().poll_broker_update()
        return self._project_trade_driven_order(update)

    def fetch_open_orders(self, force: bool = False, raise_errors: bool = False):
        """Return open-order rows with the RegisteredSim fill mode bound."""
        rows = super().fetch_open_orders(force=force, raise_errors=raise_errors)
        if not isinstance(rows, list):
            raise BtApiStoreError("registered-sim open-order projection is invalid")
        return [self._project_trade_driven_order(row, order_row=True) for row in rows]

    def get_ctp_reconciliation_snapshot(self, *, timeout: float = 5.0):
        """Preserve CTP query evidence and bind its order rows to trade fills."""
        snapshot = super().get_ctp_reconciliation_snapshot(timeout=timeout)
        if not isinstance(snapshot, Mapping):
            raise BtApiStoreError("registered-sim CTP reconciliation snapshot is invalid")
        projected = dict(snapshot)
        order_rows = snapshot.get("orders")
        if isinstance(order_rows, list):
            projected["orders"] = [
                self._project_trade_driven_order(row, order_row=True) for row in order_rows
            ]
        return projected

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

    def _order_route_from_info(self, order: Any) -> Optional[Tuple[str, str]]:
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
        data = getattr(order, "data", None)
        data_name_value = getattr(data, "_dataname", None)
        if not isinstance(data_name_value, str) or not data_name_value:
            raise BtApiStoreError("registered-sim subscribed feed instrument is unavailable")
        if data_name_value != data_name_value.strip():
            raise BtApiStoreError("registered-sim subscribed feed instrument is not exact text")
        # CTP feeds also support the documented raw dataname spellings
        # ``instrument.exchange`` and ``exchange.instrument`` (and the
        # historical underscore equivalents). Parse only this subscribed raw
        # value. In particular, ``data._name`` is a Cerebro display alias and
        # must never be accepted as contract identity.
        raw_parts = None
        for separator in (".", "_"):
            if data_name_value.count(separator) == 1:
                candidate = data_name_value.split(separator)
                if len(candidate) == 2 and all(candidate):
                    raw_parts = tuple(candidate)
                    break
        if data_name_value == instrument:
            raw_identity_matches = True
            subscribed_instrument = data_name_value
        elif raw_parts is not None:
            raw_identity_matches = raw_parts in (
                (instrument, exchange),
                (exchange, instrument),
            )
            subscribed_instrument = instrument if raw_identity_matches else None
        else:
            raw_identity_matches = False
            subscribed_instrument = None
        if not raw_identity_matches:
            raise BtApiStoreError("order.info instrument does not match the subscribed feed")

        info_bound_intent = any(
            get_info(name) is not None for name in ("factor_intent_id", "factor_cancel_intent_id")
        )
        # The display name selects one exact Broker contract-metadata row; it
        # never contributes to instrument identity. The raw feed dataname above
        # binds the subscription, and this row binds the exact route tuple.
        broker = getattr(self, "_broker", None)
        broker_routes = getattr(broker, "_contract_metadata", None)
        display_name = getattr(data, "_name", None)
        route_metadata = (
            broker_routes.get(display_name)
            if isinstance(broker_routes, Mapping)
            and isinstance(display_name, str)
            and display_name == display_name.strip()
            else None
        )
        if route_metadata is not None:
            if not isinstance(route_metadata, Mapping):
                raise BtApiStoreError("registered-sim Broker contract binding is invalid")
            try:
                bound_instrument = _exact_text(
                    route_metadata.get("instrument_id"), "Broker contract instrument_id"
                )
                bound_exchange = _exact_text(
                    route_metadata.get("exchange_id"), "Broker contract exchange_id"
                )
            except ValueError:
                raise BtApiStoreError("registered-sim Broker contract binding is invalid") from None
            if bound_instrument != subscribed_instrument or bound_exchange != exchange:
                raise BtApiStoreError(
                    "order.info route identity does not match the exact Broker contract binding"
                )
        elif info_bound_intent:
            raise BtApiStoreError("factor order has no exact Broker contract binding")

        feed_exchange = getattr(data, "_exchange_id", None)
        if feed_exchange is not None:
            if not isinstance(feed_exchange, str) or feed_exchange != feed_exchange.strip():
                raise BtApiStoreError("registered-sim subscribed feed exchange is not exact text")
            if feed_exchange != exchange:
                raise BtApiStoreError("order.info exchange does not match the subscribed feed")
        return instrument, exchange

    @staticmethod
    def _exact_cancel_row_field(row: Mapping, *names: str) -> Any:
        present = [name for name in names if name in row]
        if not present:
            return None
        values = [row[name] for name in present]
        return values[0] if all(value == values[0] for value in values[1:]) else None

    @classmethod
    def _exact_cancel_row_text(cls, row: Mapping, *names: str) -> Optional[str]:
        value = cls._exact_cancel_row_field(row, *names)
        if type(value) is str and value and value == value.strip():
            return value
        return None

    @classmethod
    def _exact_cancel_row_ref(cls, row: Mapping) -> Optional[str]:
        value = cls._exact_cancel_row_field(row, "OrderRef", "order_ref")
        if type(value) is str and value and value == value.strip():
            return value
        if type(value) is int and value >= 0:
            return str(value)
        return None

    @classmethod
    def _exact_cancel_row_positive_int(cls, row: Mapping, *names: str) -> Optional[int]:
        value = cls._exact_cancel_row_field(row, *names)
        return value if _positive_int(value) else None

    def _factor_cancel_journal_records(self, order: Any) -> Optional[Mapping[str, Any]]:
        """Read and validate Journal authority before taking Store/Wrapper locks."""
        info = getattr(order, "info", None)
        get = getattr(info, "get", None)
        if not callable(get):
            return None
        cancel_intent_id = get("factor_cancel_intent_id")
        owner_intent_id = get("factor_intent_id")
        factor_scope = get("factor_strategy_scope")
        factor_order = cancel_intent_id is not None or owner_intent_id is not None
        if not factor_order:
            return None
        if (
            type(cancel_intent_id) is not str
            or not cancel_intent_id
            or type(owner_intent_id) is not str
            or not owner_intent_id
            or type(factor_scope) is not str
            or not factor_scope
        ):
            raise BtApiStoreError("registered-sim factor cancel owner is incomplete")
        broker = getattr(self, "_broker", None)
        coordinator = getattr(broker, "factor_execution_coordinator", None)
        from .execution_decision_journal import ExecutionDecisionJournal
        from .factor_execution import FactorExecutionCoordinator

        if (
            not isinstance(coordinator, FactorExecutionCoordinator)
            or coordinator.broker is not broker
            or coordinator.store is not self
            or type(coordinator.journal) is not ExecutionDecisionJournal
            or coordinator.strategy_scope != factor_scope
        ):
            raise BtApiStoreError("registered-sim factor cancel coordinator is unavailable")
        journal = coordinator.journal
        records_getter = getattr(journal, "registered_sim_cancel_dispatch_records", None)
        if not callable(records_getter):
            raise BtApiStoreError("registered-sim durable cancel validator is unavailable")
        try:
            records = records_getter(cancel_intent_id)
        except Exception as error:
            raise BtApiStoreError("registered-sim durable cancel owner is not KNOWN") from error
        cancel = records.get("cancel") if isinstance(records, Mapping) else None
        owner = records.get("owner") if isinstance(records, Mapping) else None
        binding = records.get("binding") if isinstance(records, Mapping) else None
        if (
            cancel is None
            or owner is None
            or cancel.intent_id != cancel_intent_id
            or cancel.state != "DISPATCHING"
            or cancel.dispatch_state is not None
            or cancel.key.action != "CANCEL"
            or cancel.owner_intent_id != owner_intent_id
            or owner.intent_id != owner_intent_id
            or owner.state != "KNOWN"
            or owner.dispatch_state != "KNOWN"
            or owner.key.action != "SUBMIT"
            or owner.decision_key is None
            or owner.decision_key.account_scope != coordinator.account_scope
            or owner.decision_key.strategy_scope != coordinator.strategy_scope
            or cancel.decision_key is None
            or cancel.decision_key.account_scope != coordinator.account_scope
            or cancel.decision_key.strategy_scope != coordinator.strategy_scope
        ):
            raise BtApiStoreError("registered-sim durable cancel owner is mismatched")
        active_owner = journal.active_instrument_owner(
            coordinator.account_scope, owner.key.instrument
        )
        if (
            active_owner is None
            or active_owner.intent_id != owner_intent_id
            or active_owner.cancel_intent_id != cancel_intent_id
        ):
            raise BtApiStoreError("registered-sim cancel does not own the active order")
        return MappingProxyType(
            {
                "coordinator": coordinator,
                "journal": journal,
                "cancel": cancel,
                "owner": owner,
                "binding": binding,
            }
        )

    def _registered_sim_cancel_target_identity(
        self,
        order: Any,
        *,
        order_ref: str,
        instrument: str,
        exchange: str,
        expected_session: Mapping[str, Any],
        records: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Join durable owner identity to one current complete source row."""
        coordinator = records["coordinator"]
        cancel = records["cancel"]
        owner = records["owner"]
        binding = records["binding"]
        cancel_identity = cancel.original_identity
        parent_identity = owner.original_identity
        provider_identity = owner.provider_identity
        info = getattr(order, "info", {})
        get = getattr(info, "get", lambda name, default=None: default)
        order_ref_candidates = tuple(
            value
            for value in (
                get("external_order_ref"),
                get("external_order_id"),
                get("ctp_order_ref"),
                get("order_ref"),
            )
            if value not in (None, "")
        )
        local_front = get("front_id")
        local_session = get("session_id")
        if not (
            type(order_ref) is str
            and order_ref
            and order_ref == order_ref.strip()
            and order_ref_candidates
            and all(value == order_ref for value in order_ref_candidates)
            and get("order_sys_id") == cancel_identity.get("order_sys_id")
            and get("factor_session_account_fingerprint")
                == expected_session.get("account_fingerprint")
            and get("factor_session_connection_generation")
                == expected_session.get("connection_generation")
            and get("factor_session_trading_day") == expected_session.get("trading_day")
            and get("factor_session_front_id") == expected_session.get("front_id")
            and get("factor_session_id") == expected_session.get("session_id")
            and (local_front is None or local_front == expected_session.get("front_id"))
            and (local_session is None or local_session == expected_session.get("session_id"))
            and get("execution_unknown") is not True
            and type(getattr(order, "ref", None)) is int
            and cancel_identity.get("backtrader_order_ref") == order.ref
            and parent_identity.get("backtrader_order_ref") == order.ref
            and cancel_identity.get("owner_intent_id") == owner.intent_id
            and cancel_identity.get("operation") == "cancel"
            and parent_identity.get("operation") == "insert"
            and cancel_identity.get("order_ref") == order_ref
            and parent_identity.get("order_ref") == order_ref
            and cancel_identity.get("instrument_id") == instrument
            and parent_identity.get("instrument_id") == instrument
            and cancel_identity.get("exchange_id") == exchange
            and parent_identity.get("exchange_id") == exchange
            and cancel_identity.get("account_fingerprint")
                == expected_session.get("account_fingerprint")
            and parent_identity.get("account_fingerprint")
                == expected_session.get("account_fingerprint")
            and cancel_identity.get("connection_generation")
                == expected_session.get("connection_generation")
            and parent_identity.get("connection_generation")
                == expected_session.get("connection_generation")
            and cancel_identity.get("trading_day") == expected_session.get("trading_day")
            and parent_identity.get("trading_day") == expected_session.get("trading_day")
            and cancel_identity.get("front_id") == expected_session.get("front_id")
            and parent_identity.get("front_id") == expected_session.get("front_id")
            and cancel_identity.get("session_id") == expected_session.get("session_id")
            and parent_identity.get("session_id") == expected_session.get("session_id")
            and isinstance(provider_identity, Mapping)
            and provider_identity.get("order_ref") == order_ref
            and provider_identity.get("instrument_id") in (None, instrument)
            and provider_identity.get("exchange_id") in (None, exchange)
            and cancel.key.instrument == owner.key.instrument == instrument
            and cancel.economic_payload.get("exchange") == exchange
        ):
            raise BtApiStoreError("registered-sim cancel owner identity is incomplete or stale")
        if binding is not None:
            if not isinstance(binding, Mapping) or not (
                binding.get("intent_id") == owner.intent_id
                and binding.get("account_scope") == coordinator.account_scope
                and binding.get("strategy_scope") == coordinator.strategy_scope
                and binding.get("account_fingerprint")
                    == expected_session.get("account_fingerprint")
                and binding.get("connection_generation")
                    == expected_session.get("connection_generation")
                and binding.get("trading_day") == expected_session.get("trading_day")
                and binding.get("instrument") == instrument
                and binding.get("exchange") == exchange
                and binding.get("order_ref") == order_ref
                and binding.get("order_sys_id") == cancel_identity.get("order_sys_id")
                and binding.get("front_id") == expected_session.get("front_id")
                and binding.get("session_id") == expected_session.get("session_id")
                and _positive_int(binding.get("query_request_id"))
                and type(binding.get("query_rows_sha256")) is str
                and _HASH_RE.fullmatch(binding.get("query_rows_sha256")) is not None
                and type(binding.get("matched_row_sha256")) is str
                and _HASH_RE.fullmatch(binding.get("matched_row_sha256")) is not None
                and type(binding.get("broker_id")) is str
                and binding.get("broker_id") == binding.get("broker_id").strip()
                and type(binding.get("investor_id")) is str
                and binding.get("investor_id") == binding.get("investor_id").strip()
            ):
                raise BtApiStoreError("registered-sim immutable query binding conflicts")
            if provider_identity.get("order_sys_id") not in (
                None,
                "",
                binding.get("order_sys_id"),
            ):
                raise BtApiStoreError("registered-sim callback and query SysID conflict")
            expected_sys_id = binding.get("order_sys_id")
        else:
            callback_identity = provider_identity
            callback_sys_id = provider_identity.get("order_sys_id")
            if (
                type(callback_sys_id) is not str
                or not callback_sys_id
                or callback_sys_id != callback_sys_id.strip()
                or cancel_identity.get("order_sys_id") != callback_sys_id
                or parent_identity.get("order_sys_id") not in (None, "", callback_sys_id)
            ):
                raise BtApiStoreError("registered-sim KNOWN callback SysID is unavailable")
            expected_sys_id = callback_sys_id

        # The Journal locks precede Store locks.  This method is called only
        # after those reads complete; the caller holds _ctp_query_result_lock
        # through native dispatch so a new query cannot replace this source
        # epoch between validation and Action submission.
        receipt_factory = self.registered_sim_order_identity_query_receipt
        validator = self.registered_sim_validate_order_identity_query_receipt
        if (
            getattr(receipt_factory, "__func__", None)
            is not RegisteredSimStore.registered_sim_order_identity_query_receipt
            or getattr(validator, "__func__", None)
            is not RegisteredSimStore.registered_sim_validate_order_identity_query_receipt
        ):
            raise BtApiStoreError("registered-sim current order-query source is untrusted")
        receipt = receipt_factory()
        if (
            type(receipt) is not RegisteredSimOrderIdentityQueryReceipt
            or receipt._store is not self
            or validator(receipt) is not True
            or receipt.account_fingerprint != expected_session.get("account_fingerprint")
            or receipt.connection_generation != expected_session.get("connection_generation")
            or receipt.trading_day != expected_session.get("trading_day")
            or receipt.front_id != expected_session.get("front_id")
            or receipt.session_id != expected_session.get("session_id")
        ):
            raise BtApiStoreError("registered-sim current complete order query is stale")
        rows = tuple(receipt.rows)
        ref_rows = tuple(
            row
            for row in rows
            if isinstance(row, Mapping) and self._exact_cancel_row_ref(row) == order_ref
        )
        if len(ref_rows) != 1:
            raise BtApiStoreError("registered-sim current query OrderRef is missing or ambiguous")
        row = ref_rows[0]
        row_sys_id = self._exact_cancel_row_text(row, "OrderSysID", "order_sys_id")
        row_instrument = self._exact_cancel_row_text(row, "InstrumentID", "instrument_id")
        row_exchange = self._exact_cancel_row_text(row, "ExchangeID", "exchange_id")
        row_broker = self._exact_cancel_row_text(row, "BrokerID", "broker_id")
        row_investor = self._exact_cancel_row_text(row, "InvestorID", "investor_id")
        row_day = self._exact_cancel_row_text(row, "TradingDay", "trading_day")
        row_front = self._exact_cancel_row_positive_int(row, "FrontID", "front_id")
        row_session = self._exact_cancel_row_positive_int(row, "SessionID", "session_id")
        status = self._exact_cancel_row_field(row, "OrderStatus", "order_status")
        if type(status) is int:
            status = str(status)
        if not (
            row_sys_id == expected_sys_id
            and row_instrument == instrument
            and row_exchange == exchange
            and row_broker == receipt.broker_id
            and row_investor == receipt.investor_id
            and row_day == receipt.trading_day
            and row_front == receipt.front_id
            and row_session == receipt.session_id
            and row_front == expected_session.get("front_id")
            and row_session == expected_session.get("session_id")
            and row_sys_id == cancel_identity.get("order_sys_id")
            and type(status) is str
            and status.strip().lower()
                in {"1", "3", "b", "c", "parttradedqueueing", "notradequeueing", "nottouched", "touched"}
        ):
            raise BtApiStoreError("registered-sim current query row differs from KNOWN owner")
        sys_rows = tuple(
            candidate
            for candidate in rows
            if isinstance(candidate, Mapping)
            and self._exact_cancel_row_text(candidate, "OrderSysID", "order_sys_id") == row_sys_id
            and self._exact_cancel_row_text(candidate, "ExchangeID", "exchange_id") == row_exchange
        )
        if len(sys_rows) != 1:
            raise BtApiStoreError("registered-sim current query OrderSysID is ambiguous")
        try:
            from .execution_decision_journal import _canonical_json

            matched_row_sha256 = hashlib.sha256(
                _canonical_json(dict(row)).encode("utf-8")
            ).hexdigest()
        except Exception:
            raise BtApiStoreError("registered-sim current query row digest is invalid") from None
        if binding is not None and any(
            binding.get(name) != value
            for name, value in (
                ("order_sys_id", row_sys_id),
                ("broker_id", row_broker),
                ("investor_id", row_investor),
                ("instrument", row_instrument),
                ("exchange", row_exchange),
                ("order_ref", order_ref),
                ("front_id", row_front),
                ("session_id", row_session),
                ("trading_day", row_day),
            )
        ):
            raise BtApiStoreError("registered-sim current query conflicts with immutable binding")
        if binding is None and (
            not isinstance(callback_identity, Mapping)
            or callback_identity.get("broker_id") != row_broker
            or callback_identity.get("investor_id") != row_investor
        ):
            raise BtApiStoreError(
                "registered-sim KNOWN callback account identity differs from current query"
            )
        return {
            "order_ref": order_ref,
            "order_sys_id": row_sys_id,
            "instrument_id": row_instrument,
            "exchange_id": row_exchange,
            "broker_id": row_broker,
            "investor_id": row_investor,
            "front_id": row_front,
            "session_id": row_session,
            "account_fingerprint": receipt.account_fingerprint,
            "connection_generation": receipt.connection_generation,
            "trading_day": receipt.trading_day,
            "query_request_id": receipt.request_id,
            "query_rows_sha256": receipt.rows_sha256,
            "matched_row_sha256": matched_row_sha256,
            "source_expires_monotonic": receipt.source_expires_monotonic,
        }

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

    def registered_sim_order_capacity_facts(self) -> Dict[str, Any]:
        """Read an already-created wrapper's count-only order projection.

        This method never calls ``_ensure_api_ready`` and never constructs a
        client.  The API reference is checked again after projection because
        Store shutdown may clear it concurrently.
        """
        api = self._api
        if not isinstance(api, RegisteredSimWrapper):
            return {
                "schema": "backtrader.registered_sim_order_capacity.v1",
                "status": "UNAVAILABLE",
                "reason_code": "api_not_initialized",
            }
        project = getattr(api, "registered_sim_order_capacity_facts", None)
        if not callable(project):
            return {
                "schema": "backtrader.registered_sim_order_capacity.v1",
                "status": "UNAVAILABLE",
                "reason_code": "projection_missing",
            }
        try:
            facts = project()
        except Exception:
            return {
                "schema": "backtrader.registered_sim_order_capacity.v1",
                "status": "UNAVAILABLE",
                "reason_code": "projection_failed",
            }
        if self._api is not api:
            return {
                "schema": "backtrader.registered_sim_order_capacity.v1",
                "status": "UNAVAILABLE",
                "reason_code": "api_changed_during_projection",
            }
        if not isinstance(facts, Mapping):
            return {
                "schema": "backtrader.registered_sim_order_capacity.v1",
                "status": "UNAVAILABLE",
                "reason_code": "invalid_projection",
            }
        schema = facts.get("schema")
        status = facts.get("status")
        if schema != "backtrader.registered_sim_order_capacity.v1":
            return {
                "schema": "backtrader.registered_sim_order_capacity.v1",
                "status": "UNAVAILABLE",
                "reason_code": "invalid_projection_schema",
            }
        if status == "UNAVAILABLE":
            reason_code = facts.get("reason_code")
            return {
                "schema": "backtrader.registered_sim_order_capacity.v1",
                "status": "UNAVAILABLE",
                "reason_code": reason_code
                if isinstance(reason_code, str) and reason_code
                else "projection_unavailable",
                "dispatching_order_count": facts.get("dispatching_order_count")
                if type(facts.get("dispatching_order_count")) is int
                and facts.get("dispatching_order_count") >= 0
                else None,
            }
        required_counts = (
            "active_order_count",
            "unknown_order_count",
            "terminal_order_count",
            "dispatching_order_count",
        )
        if any(type(facts.get(name)) is not int or facts[name] < 0 for name in required_counts):
            return {
                "schema": "backtrader.registered_sim_order_capacity.v1",
                "status": "UNAVAILABLE",
                "reason_code": "invalid_projection_counts",
            }
        terminal_limit = facts.get("terminal_order_limit")
        terminal_respected = facts.get("terminal_limit_respected")
        store_terminal_limit = getattr(self, "_registered_sim_terminal_order_limit", None)
        if (
            type(terminal_limit) is not int
            or terminal_limit <= 0
            or type(store_terminal_limit) is not int
            or terminal_limit != store_terminal_limit
            or type(terminal_respected) is not bool
            or terminal_respected != (facts["terminal_order_count"] <= terminal_limit)
            or facts.get("active_unknown_limit", object()) is not None
            or facts.get("active_unknown_bounded") is not False
            or facts["dispatching_order_count"] != 0
            or status not in ("OBSERVED", "UNSTABLE_OR_OVER_CAPACITY")
            or (status == "OBSERVED") != terminal_respected
        ):
            return {
                "schema": "backtrader.registered_sim_order_capacity.v1",
                "status": "UNAVAILABLE",
                "reason_code": "invalid_projection_limits",
            }
        return {
            key: facts[key]
            for key in (
                "schema",
                "status",
                *required_counts,
                "active_unknown_limit",
                "active_unknown_bounded",
                "terminal_order_limit",
                "terminal_limit_respected",
            )
        }

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
            grant_returned = False
            try:
                raw_result = arm(
                    instrument,
                    exchange,
                    md_front=md_front,
                    strategy_identity_sha256=strategy_identity_sha256,
                    execution_cycle_id=execution_cycle_id,
                    preflight_sha256=preflight_sha256,
                )
                grant_returned = True
                result = dict(raw_result)
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
                return result
            except BaseException as exc:
                if grant_returned or not isinstance(exc, Exception):
                    try:
                        self._freeze_store_after_arm_failure_locked(
                            api, "native_admission_publication_failed"
                        )
                    except BaseException:
                        pass
                else:
                    try:
                        self._sync_gate_after_arm_failure_locked(api, "native_admission_failed")
                    except BaseException:
                        pass
                raise

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

    def registered_sim_ensure_arm(
        self,
        instrument: str,
        exchange: str,
        *,
        expected_session: Optional[Mapping] = None,
    ) -> Dict[str, Any]:
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
            grant_returned = False
            try:
                if expected_session is None:
                    raw_result = ensure(instrument, exchange)
                    grant_returned = True
                    result = dict(raw_result)
                else:
                    session_scope = getattr(api, "registered_sim_expected_session_scope", None)
                    if not callable(session_scope):
                        raise BtApiStoreError(
                            "registered-sim expected-session binding is unavailable"
                        )
                    with session_scope(expected_session):
                        raw_result = ensure(instrument, exchange)
                        grant_returned = True
                        result = dict(raw_result)
                self._registered_sim_gate.update(
                    {
                        "armed": result.get("armed") is True,
                        "reason": "",
                        "instrument": instrument,
                        "exchange": exchange,
                    }
                )
                return result
            except BaseException as exc:
                if grant_returned or not isinstance(exc, Exception):
                    try:
                        self._freeze_store_after_arm_failure_locked(
                            api, "native_arm_switch_publication_failed"
                        )
                    except BaseException:
                        pass
                else:
                    try:
                        self._sync_gate_after_arm_failure_locked(api, "native_arm_switch_failed")
                    except BaseException:
                        pass
                raise

    def _freeze_store_after_arm_failure_locked(self, api: Any, reason: str) -> None:
        """Close Store and SDK admission if a returned grant cannot be published."""
        try:
            self._registered_sim_gate.update(
                {
                    "armed": False,
                    "frozen": True,
                    "reason": reason,
                    "instrument": None,
                    "exchange": None,
                }
            )
        finally:
            # Even if a second control exception interrupts local publication,
            # make the wrapper close its native gate before returning to the
            # caller. The caller preserves the original publication exception.
            try:
                freeze = getattr(api, "freeze_registered_sim_execution", None)
                if callable(freeze):
                    freeze(reason)
            except BaseException:
                pass

    def _sync_gate_after_arm_failure_locked(self, api: Any, reason: str) -> None:
        try:
            facts_method = getattr(api, "registered_sim_execution_facts", None)
            facts = facts_method() if callable(facts_method) else None
        except BaseException:
            self._registered_sim_gate.update(
                {"frozen": True, "armed": False, "reason": reason}
            )
            return
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
            except BaseException as exc:
                self._registered_sim_gate.update({"frozen": True, "reason": "native_disarm_failed"})
                if not isinstance(exc, Exception):
                    raise
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

    def _order_expected_session_scope(self, order: Any):
        expected = _order_expected_session(order)
        if expected is None:
            return None
        api = self._api
        method = getattr(api, "registered_sim_expected_session_scope", None)
        if not callable(method):
            raise BtApiStoreError("registered-sim expected-session binding is unavailable")
        return method(expected)

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
            sdk_client = None
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
                    sdk_gate = (
                        wrapper_facts.get("sdk_gate_projection")
                        if isinstance(wrapper_facts, Mapping)
                        else None
                    )
                    if sdk_gate is None and callable(sdk_state_method):
                        sdk_gate = sdk_state_method()

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
        canonical_route_instrument = _canonical_sdk_route_instrument(
            sdk_client,
            (instrument, exchange),
            bundle=authorized_instruments is not None,
        )
        expected_route_instrument = (
            canonical_route_instrument
            if canonical_route_instrument is not None
            else instrument
        )
        sdk_instrument_matches_route = (
            sdk_instrument in (instrument, expected_route_instrument)
            if sdk_instrument is not None
            else False
        )
        adapter_key = wrapper_facts.get("armed_key") if wrapper_observed else None
        cached_grant_matches = (
            wrapper_facts.get("current_grant_matches_sdk")
            if wrapper_observed and type(wrapper_facts.get("current_grant_matches_sdk")) is bool
            else None
        )
        sdk_capability_matches_route = None
        if wrapper_observed and sdk_gate_observed:
            if (
                sdk_managed is not True
                or sdk_armed is not True
                or adapter_key != (instrument, exchange)
                or (sdk_instrument is not None and not sdk_instrument_matches_route)
                or cached_grant_matches is False
            ):
                sdk_capability_matches_route = False
            elif cached_grant_matches is True and authorized_instruments is not None:
                sdk_capability_matches_route = (
                    expected_route_instrument in authorized_instruments
                )
            elif cached_grant_matches is True or cached_grant_matches is None:
                sdk_capability_matches_route = None

        instrument_query_complete = self.supports_complete_ctp_queries(include_reference_data=True)
        with self._ctp_query_result_lock:
            instrument_facts = self._ctp_query_results.get("instruments_result")
        instrument_rows = self.registered_sim_instrument_rows()
        instrument_eligible = None
        if instrument_query_complete and instrument_rows:
            instrument_eligible = _instrument_eligibility_from_rows(
                list(instrument_rows),
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
        session = _session_identity(sdk_client) if sdk_client is not None else {}
        current_session_account = session.get("account_fingerprint")
        current_session_generation = session.get("connection_generation")
        current_session_day = session.get("trading_day")
        current_session_ready = session.get("trading_ready")
        current_session_front_id = session.get("front_id")
        current_session_id = session.get("session_id")
        current_session_read_only_ready = session.get("read_only_ready")
        arm_api_available = (
            callable(getattr(sdk_client, "arm_execution_for_registered_sim", None))
            if sdk_client is not None
            else None
        )
        templates_configured_value = (
            wrapper_facts.get("arm_templates_configured") if wrapper_observed else None
        )
        arm_templates_configured = (
            templates_configured_value if type(templates_configured_value) is bool else None
        )
        arm_template_membership = None
        if arm_templates_configured is True:
            keys = wrapper_facts.get("arm_template_keys")
            if type(keys) is tuple:
                exact_keys = tuple(keys)
                if all(
                    type(key) is tuple
                    and len(key) == 2
                    and all(
                        type(value) is str and value and value == value.strip() for value in key
                    )
                    for key in exact_keys
                ) and len(set(exact_keys)) == len(exact_keys):
                    arm_template_membership = (instrument, exchange) in exact_keys
        if arm_templates_configured is False:
            arm_template_configured = False
        elif arm_templates_configured is True:
            # The public wrapper projection reports only membership and never
            # exposes template contents.
            keys = wrapper_facts.get("arm_template_keys")
            if isinstance(keys, (tuple, list)):
                if not keys:
                    arm_template_configured = False
                elif (instrument, exchange) in keys:
                    arm_template_configured = True
                else:
                    arm_template_configured = None
            else:
                arm_template_configured = None
        else:
            arm_template_configured = None
        if (
            wrapper_observed
            and sdk_gate_observed
            and sdk_managed is True
            and sdk_armed is True
            and sdk_instrument is not None
            and sdk_instrument_matches_route
            and adapter_key == (instrument, exchange)
            and sdk_gate.get("connection_generation") == current_session_generation
            and sdk_gate.get("trading_day") == current_session_day
            and current_session_ready is True
            and cached_grant_matches is True
        ):
            # The SDK exposes only the instrument grant here; exact exchange
            # identity remains bound by this canonical contract and per-write SDK call.
            sdk_capability_matches_route = (
                expected_route_instrument in authorized_instruments
                if authorized_instruments is not None
                else True
            )
        elif arm_templates_configured is True and sdk_capability_matches_route is None:
            # The grant can legitimately be absent before the first per-route
            # arm. This remains an observed false capability match, never a
            # write permission.
            if sdk_gate_observed and sdk_armed is False:
                sdk_capability_matches_route = False
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
        if current_session_ready is False:
            reason_codes.append("session_not_trading_ready")
        if arm_templates_configured is True and arm_template_configured is not True:
            reason_codes.append("arm_template_missing")
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
            arm_template_configured=arm_template_configured,
            arm_templates_configured=arm_templates_configured,
            arm_template_membership=arm_template_membership,
            arm_api_available=arm_api_available,
            current_session_account_fingerprint=current_session_account,
            current_session_connection_generation=current_session_generation,
            current_session_trading_day=current_session_day,
            current_session_trading_ready=current_session_ready,
            current_session_front_id=current_session_front_id,
            current_session_id=current_session_id,
            current_session_read_only_ready=current_session_read_only_ready,
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

    def registered_sim_retire_unknown(
        self,
        intent_id: str,
        reconciliation_id: str,
        *,
        original_identity: Mapping[str, Any],
        expected_session: Mapping[str, Any],
        terminal_event: Optional[Mapping[str, Any]],
    ) -> RegisteredSimUnknownRetirement:
        """Retire a proven UNKNOWN through the API queue polled by Broker."""
        expected = _expected_session(expected_session)
        with self._registered_sim_gate_lock:
            api = self._api
            method = (
                getattr(api, "retire_registered_sim_unknown", None) if api is not None else None
            )
            if not callable(method):
                raise BtApiStoreError("registered-sim recovery wrapper is unavailable")
            operation = (
                original_identity.get("operation")
                if isinstance(original_identity, Mapping)
                else None
            )
            expected_reason = (
                "registered_sim_{}_unknown".format(operation)
                if operation in ("insert", "cancel")
                else None
            )
            store_frozen = self._registered_sim_gate.get("frozen") is True
            if store_frozen and self._registered_sim_gate.get("reason") != expected_reason:
                raise BtApiStoreError("registered-sim recovery cannot clear another Store freeze")
            result = method(
                intent_id,
                reconciliation_id,
                original_identity=original_identity,
                expected_session=expected,
                terminal_event=terminal_event,
            )
            if not isinstance(result, RegisteredSimUnknownRetirement):
                raise BtApiStoreError("registered-sim recovery result is invalid")
            if result.status not in ("QUEUED", "ALREADY_ABSENT") or result.disarmed is not True:
                raise BtApiStoreError("registered-sim recovery result is not terminal")
            if store_frozen:
                facts = getattr(api, "registered_sim_execution_facts", None)
                current = facts() if callable(facts) else None
                if (
                    not isinstance(current, Mapping)
                    or current.get("frozen") is not False
                    or current.get("unknown_ids") != []
                ):
                    raise BtApiStoreError("registered-sim recovery left another UNKNOWN freeze")

            if store_frozen:
                self._registered_sim_gate.update(
                    {"armed": False, "frozen": False, "reason": "unknown_reconciled_disarmed"}
                )
            return result

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

    def registered_sim_write_route_invest_unit_id(
        self, instrument_id: str, exchange_id: str
    ) -> Optional[str]:
        """Read the exact unit used by this target's source-owned CTP writer."""

        api = self._api
        getter = (
            getattr(api, "registered_sim_write_route_invest_unit_id", None)
            if isinstance(api, RegisteredSimWrapper)
            else None
        )
        if not callable(getter):
            return None
        try:
            return getter(instrument_id, exchange_id)
        except Exception:
            return None

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

    def registered_sim_md_identity_facts(self) -> Dict[str, Any]:
        """Return redacted identity qualification facts for the current MD client.

        This is a read-only projection of the already-connected wrapper.  It
        deliberately does not call ``_ensure_api_ready``: observing login
        identity must never create or reconnect a provider session.
        """

        facts: Dict[str, Any] = {
            "status": "API_UNAVAILABLE",
            "observation_present": False,
            "identity_matches_bound": False,
            "source_generation_matches": None,
            "trading_day_matches": None,
            "identity_qualified": False,
        }
        api = self._api
        if not isinstance(api, RegisteredSimWrapper):
            return facts

        try:
            md_client = getattr(api, "md_client", None)
            if md_client is None:
                facts["status"] = "MD_CLIENT_UNAVAILABLE"
                return facts

            diagnostic = getattr(md_client, "login_callback_diagnostic", None)
            disposition = getattr(diagnostic, "disposition", None)
            disposition_name = getattr(disposition, "name", None)
            login_statuses = {
                "NONE": "MD_IDENTITY_UNAVAILABLE",
                "STALE_SPI": "MD_LOGIN_STALE_SPI",
                "GENERATION_MISMATCH": "MD_LOGIN_GENERATION_MISMATCH",
                "REQUEST_ID_TYPE_INVALID": "MD_LOGIN_REQUEST_ID_TYPE_INVALID",
                "REQUEST_ID_MISMATCH": "MD_LOGIN_REQUEST_ID_MISMATCH",
                "NONTERMINAL": "MD_LOGIN_NONTERMINAL",
                "IDENTITY_REJECTED": "MD_LOGIN_IDENTITY_REJECTED",
                "READ_ONLY_ACCEPTED": "READ_ONLY_ACCEPTED",
                "ACCEPTED": "MD_IDENTITY_UNAVAILABLE",
                "PROVIDER_REJECTED": "MD_LOGIN_PROVIDER_REJECTED",
                "DISCONNECTED": "DISCONNECTED",
            }
            login_status = (
                login_statuses.get(disposition_name, "MD_LOGIN_OTHER")
                if type(disposition_name) is str
                else "MD_IDENTITY_UNAVAILABLE"
            )
            if getattr(md_client, "_connected", None) is False:
                login_status = "DISCONNECTED"

            identity = getattr(md_client, "active_md_identity", None)
            if identity is None:
                facts["status"] = login_status
                return facts
            # The last callback diagnostic may not describe the identity that
            # remains active.  Qualify that identity from its current bindings.
            facts["observation_present"] = True

            from bt_api_ctp.md_identity import md_identity_matches

            current_generation = getattr(md_client, "connection_generation", None)
            request_id = getattr(md_client, "_login_request_id", None)
            try:
                identity_matches = md_identity_matches(
                    identity,
                    expected_front=getattr(md_client, "_bound_front", None),
                    expected_broker_id=getattr(md_client, "_bound_broker_id", None),
                    expected_user_id=getattr(md_client, "_bound_user_id", None),
                    expected_connection_generation=current_generation,
                    expected_request_id=request_id,
                )
            except Exception:
                identity_matches = False
            facts["identity_matches_bound"] = identity_matches is True

            source_generation = getattr(self, "_ctp_factor_expected_md_generation", None)
            expected_api_generation = getattr(
                api, "_ctp_factor_expected_md_generation", None
            )
            source_md_client = getattr(api, "_ctp_factor_md_client", None)
            source_enabled = getattr(self, "_ctp_factor_tick_source_enabled", None) is True
            if source_enabled:
                facts["source_generation_matches"] = bool(
                    type(source_generation) is int
                    and source_generation > 0
                    and type(expected_api_generation) is int
                    and expected_api_generation > 0
                    and source_md_client is md_client
                    and expected_api_generation == source_generation
                    and getattr(identity, "connection_generation", None) == source_generation
                    and current_generation == source_generation
                )

            trader = getattr(api, "trader_client", None)
            trader_day = getattr(trader, "_trading_day", None) if trader is not None else None
            identity_day = getattr(identity, "trading_day", None)
            if type(trader_day) is str and type(identity_day) is str:
                facts["trading_day_matches"] = identity_day == trader_day

            trader_stable = bool(
                getattr(api, "trader_client", None) is trader
                and (
                    (getattr(trader, "_trading_day", None) if trader is not None else None)
                    == trader_day
                )
            )
            stable_api_generation = getattr(
                api, "_ctp_factor_expected_md_generation", None
            )
            stable_source_md_client = getattr(api, "_ctp_factor_md_client", None)
            stable_source_generation = getattr(
                self, "_ctp_factor_expected_md_generation", None
            )
            identity_stable = bool(
                getattr(md_client, "active_md_identity", None) is identity
                and getattr(md_client, "connection_generation", None) == current_generation
                and self._api is api
                and getattr(api, "md_client", None) is md_client
                and trader_stable
                and (
                    not source_enabled
                    or (
                        getattr(self, "_ctp_factor_tick_source_enabled", None) is True
                        and stable_source_md_client is source_md_client
                        and type(stable_api_generation) is type(expected_api_generation)
                        and stable_api_generation == expected_api_generation
                        and type(stable_source_generation) is type(source_generation)
                        and stable_source_generation == source_generation
                    )
                )
            )
            facts["identity_qualified"] = bool(
                facts["identity_matches_bound"] is True
                and identity_stable is True
                and facts["source_generation_matches"] is True
                and facts["trading_day_matches"] is True
            )

            if identity_stable is not True:
                facts["status"] = "SESSION_CHANGED"
            elif facts["identity_matches_bound"] is not True:
                facts["status"] = "IDENTITY_UNQUALIFIED"
            elif facts["source_generation_matches"] is None:
                facts["status"] = "MD_SOURCE_UNBOUND"
            elif facts["source_generation_matches"] is not True:
                facts["status"] = "MD_SOURCE_GENERATION_MISMATCH"
            elif facts["trading_day_matches"] is None:
                facts["status"] = "TRADING_DAY_UNOBSERVED"
            elif facts["trading_day_matches"] is not True:
                facts["status"] = "TRADING_DAY_MISMATCH"
            else:
                facts["status"] = "QUALIFIED"
            return facts
        except ImportError:
            facts["status"] = "SDK_IDENTITY_API_UNAVAILABLE"
            return facts
        except Exception:
            facts["status"] = "OBSERVATION_READ_FAILED"
            return facts

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
            cache = (
                self._ctp_commission_query_snapshots
                if family == "instrument_commission_rate_result"
                else self._ctp_query_snapshots
            )
            facts = cache.get(cache_key)
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
        if facts.get("source_session_identity_valid") is True and not (
            _read_fact(current_scope, "broker_id") == facts.get("_source_broker_id")
            and _read_fact(current_scope, "investor_id") == facts.get("_source_investor_id")
        ):
            return None

        detached = _public_query_snapshot(facts)
        detached["query_filters"] = copy.deepcopy(dict(filters))
        return detached

    def registered_sim_order_identity_query_receipt(
        self,
    ) -> Optional[RegisteredSimOrderIdentityQueryReceipt]:
        """Seal the current complete, unfiltered orders query for Journal use.

        This does not issue I/O. It reuses the same current Store snapshot used
        by the facts projection, then verifies its source-owned request and
        session against the Store cache and the live SDK scope. A result from a
        callback, Broker ``info``, or caller-created mapping cannot produce
        this receipt.
        """
        snapshot = self.get_registered_sim_query_snapshot("orders_result")
        if not isinstance(snapshot, Mapping):
            return None
        rows = snapshot.get("rows")

        def public_order_row(row: Any) -> bool:
            return bool(
                isinstance(row, Mapping)
                and row
                and all(
                    type(name) is str
                    and bool(name)
                    and name == name.strip()
                    and (
                        value is None
                        or type(value) in (str, int, float, bool)
                        and (type(value) is not float or math.isfinite(value))
                    )
                    for name, value in row.items()
                )
            )

        if not (
            snapshot.get("family") == "orders_result"
            and snapshot.get("request_type") == "orders"
            and snapshot.get("expected_request_type") == "orders"
            and snapshot.get("query_complete") is True
            and snapshot.get("scope_complete") is True
            and snapshot.get("source_owned") is True
            and snapshot.get("source_session_identity_valid") is True
            and snapshot.get("query_filters") == {}
            and snapshot.get("source_explicit_request_filters") == ()
            and isinstance(rows, list)
            and all(public_order_row(row) for row in rows)
        ):
            return None
        request_id = snapshot.get("request_id")
        generation = snapshot.get("connection_generation")
        account = snapshot.get("account_fingerprint")
        day = snapshot.get("trading_day")
        started = snapshot.get("started_at_utc")
        completed = snapshot.get("completed_at_utc")
        if not (
            _positive_int(request_id)
            and _positive_int(generation)
            and type(account) is str
            and account
            and account == account.strip()
            and type(day) is str
            and re.fullmatch(r"[0-9]{8}", day) is not None
            and _is_aware_datetime(started)
            and _is_aware_datetime(completed)
            and started <= completed
        ):
            return None
        cache_key = _query_snapshot_key("orders_result", {})
        with self._ctp_query_result_lock:
            cached = self._ctp_query_snapshots.get(cache_key)
            current = self._ctp_query_results.get("orders_result")
            if not isinstance(cached, Mapping) or not isinstance(current, Mapping):
                return None
            issuer = cached.get("_source_issuer")
            expiry = cached.get("source_expires_monotonic")
            # The query result and bounded snapshot cache must still denote the
            # same request. A concurrent refresh cannot mix their rows.
            if not (
                current.get("request_id") == request_id
                and current.get("connection_generation") == generation
                and current.get("account_fingerprint") == account
                and current.get("trading_day") == day
                and current.get("completed_at_utc") == completed
                and current.get("rows") == rows
                and cached.get("request_id") == request_id
                and cached.get("connection_generation") == generation
                and cached.get("account_fingerprint") == account
                and cached.get("trading_day") == day
                and cached.get("query_complete") is True
                and cached.get("scope_complete") is True
                and cached.get("source_owned") is True
                and cached.get("source_session_identity_valid") is True
                and cached.get("source_explicit_request_filters") == ()
                and cached.get("started_at_utc") == started
                and cached.get("completed_at_utc") == completed
                and cached.get("rows") == rows
                and issuer is not None
                and type(expiry) in (int, float)
                and math.isfinite(expiry)
                and time.monotonic() < expiry
            ):
                return None
        api = self._api
        client = getattr(api, "trader_client", None) if api is not None else None
        session_snapshot = _session_scope_state_snapshot(client, require_canonical=True)
        if session_snapshot is None:
            return None
        scope, session_state = session_snapshot
        front_id = _read_fact(session_state, "front_id")
        session_id = _read_fact(session_state, "session_id")
        broker_id = _read_fact(scope, "broker_id")
        investor_id = _read_fact(scope, "investor_id")
        if not (
            _read_fact(scope, "read_only_ready") is True
            and _read_fact(scope, "issuer") is issuer
            and _read_fact(scope, "connection_generation") == generation
            and _read_fact(scope, "account_fingerprint") == account
            and _read_fact(scope, "trading_day") == day
            and _read_fact(session_state, "read_only_ready") is True
            and _read_fact(session_state, "connection_generation") == generation
            and _read_fact(session_state, "account_fingerprint") == account
            and _read_fact(session_state, "trading_day") == day
            and _positive_int(front_id)
            and _positive_int(session_id)
            and type(broker_id) is str
            and broker_id
            and broker_id == broker_id.strip()
            and type(investor_id) is str
            and investor_id
            and investor_id == investor_id.strip()
            and time.monotonic() < expiry
        ):
            return None
        try:
            canonical_rows = json.dumps(
                rows,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
            rows_digest = hashlib.sha256(canonical_rows).hexdigest()
            frozen_rows = tuple(MappingProxyType(copy.deepcopy(dict(row))) for row in rows)
        except (TypeError, ValueError, OverflowError):
            return None
        return RegisteredSimOrderIdentityQueryReceipt(
            request_id=request_id,
            connection_generation=generation,
            account_fingerprint=account,
            trading_day=day,
            started_at_utc=started,
            completed_at_utc=completed,
            front_id=front_id,
            session_id=session_id,
            broker_id=broker_id,
            investor_id=investor_id,
            rows_sha256=rows_digest,
            rows=frozen_rows,
            source_expires_monotonic=float(expiry),
            _store=self,
            _issuer=issuer,
        )

    def registered_sim_validate_order_identity_query_receipt(self, receipt: Any) -> bool:
        """Recheck a Store-minted receipt against the still-current query/session."""
        if (
            type(receipt) is not RegisteredSimOrderIdentityQueryReceipt
            or receipt._store is not self
        ):
            return False
        current = self.registered_sim_order_identity_query_receipt()
        return bool(
            current is not None
            and current._issuer is receipt._issuer
            and current.request_id == receipt.request_id
            and current.connection_generation == receipt.connection_generation
            and current.account_fingerprint == receipt.account_fingerprint
            and current.trading_day == receipt.trading_day
            and current.started_at_utc == receipt.started_at_utc
            and current.completed_at_utc == receipt.completed_at_utc
            and current.front_id == receipt.front_id
            and current.session_id == receipt.session_id
            and current.broker_id == receipt.broker_id
            and current.investor_id == receipt.investor_id
            and current.rows_sha256 == receipt.rows_sha256
            and current.rows == receipt.rows
            and current.source_expires_monotonic == receipt.source_expires_monotonic
        )

    @staticmethod
    def _instrument_scope(filters: Mapping) -> Tuple[str, str]:
        exchange = filters.get("exchange_id")
        product = filters.get("product_id")
        return (
            exchange if type(exchange) is str else "",
            product if type(product) is str else "",
        )

    def _replace_instrument_scope_rows(
        self, scope: Tuple[str, str], facts: Mapping, filters: Mapping
    ) -> None:
        """Replace exactly one product scope's merged instrument rows."""

        requested_instrument = filters.get("instrument_id")
        requested_exchange = filters.get("exchange_id")
        with self._ctp_query_result_lock:
            previous = self._ctp_query_instrument_scope_rows.pop(scope, ())
            for key in previous:
                self._ctp_query_instrument_rows.pop(key, None)
            keys = []
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
                key = (exchange, instrument)
                self._ctp_query_instrument_rows[key] = {
                    "instrument_id": instrument,
                    "exchange_id": exchange,
                    "is_trading": is_trading,
                }
                keys.append(key)
            self._ctp_query_instrument_scope_rows[scope] = tuple(keys)
            self._ctp_query_instrument_scopes[scope] = facts

    def _drop_instrument_scope(self, scope: Tuple[str, str]) -> None:
        """Forget one product scope after an incomplete or failed query."""

        with self._ctp_query_result_lock:
            previous = self._ctp_query_instrument_scope_rows.pop(scope, ())
            for key in previous:
                self._ctp_query_instrument_rows.pop(key, None)
            self._ctp_query_instrument_scopes.pop(scope, None)

    def _record_instrument_rows(self, facts: Mapping, filters: Mapping) -> None:
        self._replace_instrument_scope_rows(self._instrument_scope(filters), facts, filters)

    def registered_sim_query_interval_seconds(self) -> Optional[float]:
        """Return the SDK's enforced native query spacing, if it is visible.

        The real CTP client serializes native query submissions and sleeps for
        its own ``_query_interval`` (1.05 s by default).  The runner uses this
        value to avoid adding a second redundant wall-clock delay while still
        enforcing the >=1 s bound itself when a test double exposes no native
        pacing.
        """

        api = self._api
        client = getattr(api, "trader_client", None) if api is not None else None
        value = getattr(client, "_query_interval", None)
        if type(value) not in (int, float):
            return None
        number = float(value)
        if not math.isfinite(number) or number < 0:
            return None
        return number

    def registered_sim_query_in_flight(self) -> bool:
        """Return whether the SDK still tracks a native query callback.

        Provider callbacks can outlive a caller-visible timeout.  Retry logic
        must wait until both native submission and callback references drain.
        A missing probe attribute is treated as idle so test doubles and older
        SDKs remain usable; the retry is still bounded.
        """

        api = self._api
        client = getattr(api, "trader_client", None) if api is not None else None
        if client is None:
            return False
        for name in ("_native_request_inflight_refs", "_callback_inflight_refs"):
            value = getattr(client, name, 0)
            if type(value) is int and value > 0:
                return True
        return False

    def registered_sim_instrument_rows(self) -> Tuple[Mapping[str, Any], ...]:
        """Return current rows across all complete product-scoped queries.

        Each scope is revalidated against the live query-session identity and
        its source expiry without issuing provider I/O.  Rows from a failed or
        stale product query are absent, so route eligibility fails closed.
        """

        api = self._api
        client = getattr(api, "trader_client", None) if api is not None else None
        scope_getter = getattr(client, "get_query_session_scope", None)
        if not callable(scope_getter):
            return ()
        try:
            current_scope = scope_getter()
        except Exception:
            return ()
        now = time.monotonic()
        rows = []
        with self._ctp_query_result_lock:
            scopes = tuple(self._ctp_query_instrument_scopes)
            cache = self._ctp_query_snapshots
            for scope in scopes:
                facts = cache.get(
                    _query_snapshot_key(
                        "instruments_result",
                        {
                            "instrument_id": "",
                            "exchange_id": scope[0],
                            "product_id": scope[1],
                        },
                    )
                )
                if not isinstance(facts, Mapping):
                    continue
                expiry = facts.get("source_expires_monotonic")
                if not (
                    facts.get("query_complete") is True
                    and facts.get("source_owned") is True
                    and _read_fact(current_scope, "read_only_ready") is True
                    and _read_fact(current_scope, "issuer") is facts.get("_source_issuer")
                    and _read_fact(current_scope, "connection_generation")
                    == facts.get("connection_generation")
                    and _read_fact(current_scope, "account_fingerprint")
                    == facts.get("account_fingerprint")
                    and _read_fact(current_scope, "trading_day") == facts.get("trading_day")
                    and type(expiry) in (int, float)
                    and math.isfinite(expiry)
                    and now < expiry
                ):
                    continue
                rows.extend(facts.get("rows") or ())
        return tuple(rows)

    def registered_sim_query(
        self,
        family: str,
        timeout: float = 8.0,
        attempts: int = 2,
        *,
        deadline_monotonic: Optional[float] = None,
        **filters: Any,
    ) -> Dict[str, Any]:
        """Run a bounded typed query; absent completion facts remain unknown."""
        method_name = _QUERY_METHODS.get(family) if isinstance(family, str) else None
        if method_name is None:
            raise ValueError("unsupported registered-sim query family")
        if family == "instrument_commission_rate_result" and (
            set(filters) != {"instrument_id", "exchange_id"}
            or any(
                type(filters.get(name)) is not str
                or not filters[name]
                or filters[name] != filters[name].strip()
                for name in ("instrument_id", "exchange_id")
            )
        ):
            raise ValueError("commission query requires an exact instrument and exchange")
        commission_deadline = None
        if family == "instrument_commission_rate_result":
            if (
                type(deadline_monotonic) not in (int, float)
                or not math.isfinite(deadline_monotonic)
                or deadline_monotonic <= time.monotonic()
            ):
                raise ValueError("commission query requires a live monotonic deadline")
            commission_deadline = float(deadline_monotonic)
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
        if commission_deadline is not None:
            try:
                method_parameters = inspect.signature(method).parameters
            except (TypeError, ValueError):
                method_parameters = {}
            deadline_parameter = method_parameters.get("deadline_monotonic")
            if deadline_parameter is None or deadline_parameter.kind not in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            ):
                # An older SDK can wait indefinitely while holding its query
                # issue lock.  Do not start a fee request unless the selected
                # source exposes the end-to-end bound explicitly.
                raise BtApiStoreError("CTP commission query deadline is unavailable")
        effective_timeout = timeout_value
        facts: Dict[str, Any] = {"family": family, "query_complete": False, "rows": None}
        for attempt in range(1, attempts + 1):
            if commission_deadline is not None:
                remaining = commission_deadline - time.monotonic()
                if remaining <= 0:
                    break
                effective_timeout = min(effective_timeout, remaining)
            try:
                call_kwargs = dict(timeout=effective_timeout, **filters)
                if commission_deadline is not None:
                    call_kwargs["deadline_monotonic"] = commission_deadline
                result = method(**call_kwargs)
                api_client = getattr(api, "trader_client", None)
                scope_getter = getattr(api_client, "get_query_session_scope", None)
                scope = scope_getter() if callable(scope_getter) else None
                facts = _query_result_facts(result, family, attempt, scope, filters)
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
                    snapshot_cache = (
                        self._ctp_commission_query_snapshots
                        if family == "instrument_commission_rate_result"
                        else self._ctp_query_snapshots
                    )
                    snapshot_limit = (
                        _COMMISSION_QUERY_SNAPSHOT_LIMIT
                        if family == "instrument_commission_rate_result"
                        else _QUERY_SNAPSHOT_LIMIT
                    )
                    previous = snapshot_cache.get(snapshot_key)
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
                        snapshot_cache[snapshot_key] = facts
                        snapshot_cache.move_to_end(snapshot_key)
                        while len(snapshot_cache) > snapshot_limit:
                            snapshot_cache.popitem(last=False)
            if facts.get("query_complete") is True:
                if family == "instruments_result":
                    with self._ctp_query_result_lock:
                        self._record_instrument_rows(facts, filters)
                return _public_query_snapshot(facts)
            if family == "instruments_result":
                # A failed/partial product query invalidates that product's
                # previously observed rows; other product scopes are untouched.
                self._drop_instrument_scope(self._instrument_scope(filters))
            if attempt < attempts:
                retry_sleep = min(1.5 * attempt, 3.0)
                if commission_deadline is not None:
                    remaining = commission_deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    retry_sleep = min(retry_sleep, remaining)
                time.sleep(retry_sleep)
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
                and (
                    self._ctp_query_results[family].get("scope_complete") is True
                    # Live instrument families are product-scoped, so their
                    # declared coverage (not an unfiltered scope) is complete.
                    or family == "instruments_result"
                )
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
        required_scope = all(
            item.get("scope_complete") is True
            or (
                item.get("family") == "instruments_result"
                and item.get("query_complete") is True
            )
            for item in facts
        )
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
        current_instrument_rows = self.registered_sim_instrument_rows()
        instrument_facts = (
            list(current_instrument_rows) if complete and current_instrument_rows else None
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
            session_scope = self._order_expected_session_scope(order)
            if session_scope is None:
                return super().submit_order(order)
            # Store gate -> wrapper lock is the global lock order used by arm,
            # freeze, and dispatch. The wrapper lock remains held through the
            # SDK's final session/grant check and native method boundary.
            with self._registered_sim_gate_lock:
                if self._registered_sim_gate.get("frozen") is True:
                    raise BtApiStoreError("registered-sim Store gate is frozen")
                with session_scope:
                    return super().submit_order(order)
        except BaseException as exc:
            if (
                getattr(exc, "execution_unknown", False) is True
                or getattr(self._api, "_registered_sim_frozen", False) is True
            ):
                try:
                    self.registered_sim_freeze(getattr(exc, "code", "submit_unknown"))
                except BaseException:
                    pass
            raise

    def cancel_order(self, order):
        self._require_registered_sim_not_frozen()
        try:
            session_scope = self._order_expected_session_scope(order)
            route = self._order_route_from_info(order)
            journal_records = self._factor_cancel_journal_records(order)
            expected_session = _order_expected_session(order) if journal_records is not None else None
            if journal_records is not None and (route is None or expected_session is None):
                raise BtApiStoreError("registered-sim factor cancel has no exact route/session")
            if journal_records is not None and session_scope is None:
                raise BtApiStoreError("registered-sim factor cancel has no held session scope")
            dispatch_claim = None
            if journal_records is not None:
                cancel = journal_records["cancel"]
                # Prove the source before the durable one-shot admission.  The
                # query lock is released before entering Journal, preserving
                # the established Journal->Store lock order.  The exact same
                # source receipt is revalidated under the final Store locks
                # below; any change after this claim fails closed.
                try:
                    with self._ctp_query_result_lock:
                        initial_identity = self._registered_sim_cancel_target_identity(
                            order,
                            order_ref=cancel.original_identity["order_ref"],
                            instrument=route[0],
                            exchange=route[1],
                            expected_session=expected_session,
                            records=journal_records,
                        )
                    dispatch_claim = (
                        journal_records["journal"].claim_registered_sim_cancel_dispatch(
                            cancel.intent_id, initial_identity
                        )
                    )
                except Exception as error:
                    raise BtApiStoreError(
                        "registered-sim durable cancel dispatch admission failed"
                    ) from error
            if session_scope is None:
                if route is not None:
                    info = getattr(order, "info", {})
                    order_ref = (
                        info.get("external_order_id")
                        or info.get("ctp_order_ref")
                        or getattr(order, "ref", None)
                    )
                    instrument, exchange = route
                    dataname = "{}.{}".format(exchange, instrument)
                    if journal_records is None:
                        self._reject_legacy_cancel_for_durable_owner(
                            order_ref, broker_order_ref=getattr(order, "ref", None)
                        )
                    return self.cancel_order_ref(order_ref, dataname=dataname)
                if journal_records is None:
                    self._reject_legacy_cancel_for_durable_owner(
                        None, broker_order_ref=getattr(order, "ref", None)
                    )
                return super().cancel_order(order)
            with self._registered_sim_gate_lock:
                if self._registered_sim_gate.get("frozen") is True:
                    raise BtApiStoreError("registered-sim Store gate is frozen")
                with session_scope:
                    if route is not None:
                        info = getattr(order, "info", {})
                        order_ref = (
                            info.get("external_order_id")
                            or info.get("ctp_order_ref")
                            or getattr(order, "ref", None)
                        )
                        instrument, exchange = route
                        dataname = "{}.{}".format(exchange, instrument)
                        if journal_records is not None:
                            if type(order_ref) is not str or not order_ref:
                                raise BtApiStoreError(
                                    "registered-sim factor cancel requires its exact OrderRef"
                                )
                            # Lock order is Store gate -> wrapper session ->
                            # query result.  Journal reads above have completed
                            # before any of these locks are acquired, matching
                            # the Journal -> query-result order used on append.
                            with self._ctp_query_result_lock:
                                identity = self._registered_sim_cancel_target_identity(
                                    order,
                                    order_ref=order_ref,
                                    instrument=instrument,
                                    exchange=exchange,
                                    expected_session=expected_session,
                                    records=journal_records,
                                )
                                if not self._registered_sim_cancel_claim_matches_identity(
                                    dispatch_claim, identity
                                ):
                                    raise BtApiStoreError(
                                        "registered-sim cancel source changed after durable admission"
                                    )
                                api = self._api
                                discard = getattr(
                                    api, "_discard_registered_sim_cancel_target", None
                                )
                                if (
                                    api is not self._api
                                    or not isinstance(api, RegisteredSimWrapper)
                                    or not callable(discard)
                                    or len(api._registered_sim_cancel_targets) >= 8
                                ):
                                    raise BtApiStoreError(
                                        "registered-sim typed native cancel is unavailable"
                                    )
                                try:
                                    target = RegisteredSimCancelTarget(
                                        _issuer=self,
                                        _seal=self._registered_sim_cancel_target_seal,
                                        **identity,
                                    )
                                except (TypeError, ValueError):
                                    raise BtApiStoreError(
                                        "registered-sim cancel target identity is invalid"
                                    ) from None
                                api._registered_sim_cancel_targets[id(target)] = target
                                try:
                                    return self._cancel_order_ref_legacy(
                                        order_ref,
                                        dataname=dataname,
                                        registered_sim_cancel_target=target,
                                    )
                                finally:
                                    discard(target)
                        self._reject_legacy_cancel_for_durable_owner(
                            order_ref, broker_order_ref=getattr(order, "ref", None)
                        )
                        return self.cancel_order_ref(order_ref, dataname=dataname)
                    if journal_records is None:
                        self._reject_legacy_cancel_for_durable_owner(
                            None, broker_order_ref=getattr(order, "ref", None)
                        )
                    return super().cancel_order(order)
        except BaseException as exc:
            if (
                getattr(exc, "execution_unknown", False) is True
                or getattr(self._api, "_registered_sim_frozen", False) is True
            ):
                try:
                    self.registered_sim_freeze(getattr(exc, "code", "cancel_unknown"))
                except BaseException:
                    pass
            raise

    @staticmethod
    def _registered_sim_cancel_claim_matches_identity(
        claim: Any, identity: Mapping[str, Any]
    ) -> bool:
        if not isinstance(claim, Mapping) or not isinstance(identity, Mapping):
            return False
        pairs = (
            ("order_ref", "order_ref"),
            ("order_sys_id", "order_sys_id"),
            ("instrument", "instrument_id"),
            ("exchange", "exchange_id"),
            ("broker_id", "broker_id"),
            ("investor_id", "investor_id"),
            ("front_id", "front_id"),
            ("session_id", "session_id"),
            ("account_fingerprint", "account_fingerprint"),
            ("connection_generation", "connection_generation"),
            ("trading_day", "trading_day"),
            ("query_request_id", "query_request_id"),
            ("query_rows_sha256", "query_rows_sha256"),
            ("matched_row_sha256", "matched_row_sha256"),
            ("source_expires_monotonic", "source_expires_monotonic"),
        )
        return all(claim.get(claim_name) == identity.get(identity_name) for claim_name, identity_name in pairs)

    def cancel_order_ref(self, order_ref, dataname: Optional[str] = None):
        self._require_registered_sim_not_frozen()
        try:
            self._reject_legacy_cancel_for_durable_owner(order_ref)
            return super().cancel_order_ref(order_ref, dataname=dataname)
        except BaseException as exc:
            if (
                getattr(exc, "execution_unknown", False) is True
                or getattr(self._api, "_registered_sim_frozen", False) is True
            ):
                try:
                    self.registered_sim_freeze(getattr(exc, "code", "cancel_unknown"))
                except BaseException:
                    pass
            raise

    def _reject_legacy_cancel_for_durable_owner(
        self, order_ref: Any, *, broker_order_ref: Optional[int] = None
    ) -> None:
        broker = getattr(self, "_broker", None)
        coordinator = getattr(broker, "factor_execution_coordinator", None)
        if coordinator is None:
            if getattr(self, "_registered_sim_durable_owner_configured", False) is True:
                raise BtApiStoreError(
                    "registered-sim durable cancel coordinator is unavailable"
                )
            return
        from .execution_decision_journal import ExecutionDecisionJournal
        from .factor_execution import FactorExecutionCoordinator

        if (
            not isinstance(coordinator, FactorExecutionCoordinator)
            or coordinator.broker is not broker
            or coordinator.store is not self
            or type(coordinator.journal) is not ExecutionDecisionJournal
        ):
            raise BtApiStoreError("registered-sim legacy cancel owner scope is unavailable")
        api = self._api
        if not isinstance(api, RegisteredSimWrapper):
            # Without a held current session we cannot prove this OrderRef is
            # outside every Strategy/run in the account.
            raise BtApiStoreError("registered-sim raw cancel requires a held current session")
        with api._registered_sim_lock:
            expected = api._registered_sim_expected_session
            if not isinstance(expected, Mapping):
                raise BtApiStoreError("registered-sim raw cancel session is unavailable")
            account_fingerprint = expected.get("account_fingerprint")
            trading_day = expected.get("trading_day")
        if (
            (order_ref is not None and (
                type(order_ref) is not str
                or not order_ref
                or order_ref != order_ref.strip()
            ))
            or type(account_fingerprint) is not str
            or not account_fingerprint
            or type(trading_day) is not str
        ):
            raise BtApiStoreError("registered-sim raw cancel identity is incomplete")
        try:
            exists = coordinator.journal.native_order_ref_exists_in_account_day(
                account_scope=coordinator.account_scope,
                trading_day=trading_day,
                order_ref=order_ref,
                broker_order_ref=broker_order_ref,
            )
        except Exception as error:
            raise BtApiStoreError("registered-sim raw cancel owner lookup failed") from error
        if exists:
            raise BtApiStoreError(
                "registered-sim durable factor owner requires its exact CANCEL intent"
            )


__all__ = [
    "RegisteredSimExecutionUnknown",
    "RegisteredSimDispatchEvidence",
    "RegisteredSimUnknownRetirement",
    "RegisteredSimRouteEligibility",
    "RegisteredSimStore",
    "RegisteredSimWrapper",
]
