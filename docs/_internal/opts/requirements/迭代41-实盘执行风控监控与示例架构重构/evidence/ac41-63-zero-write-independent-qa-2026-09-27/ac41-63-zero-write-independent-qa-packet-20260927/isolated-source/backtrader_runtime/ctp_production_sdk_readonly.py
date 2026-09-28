"""Lazy SDK adapter for a sealed, production-only CTP read-only session.

The factory rechecks the parser-sealed config and caller-supplied exact
production account/front pin, then a separate code-owned SDK artifact pin,
before resolving credentials. It imports the native SDK only after those
local gates and exposes a session wrapper with seven query operations, zero-
write counters, identity evidence, and a bounded close operation. This module
does not add a default registration, operator route, or write capability.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import threading
import time
from typing import Any, Callable, Mapping, NoReturn, Optional, Tuple

from .ctp_production_credentials import (
    CtpProductionCredentials,
    CtpProductionCredentialResolutionError,
    require_ctp_production_credentials_seal,
    resolve_ctp_production_credentials,
)
from .ctp_production_artifact_provenance import (
    verify_ctp_production_sdk_artifact_provenance,
)
from .ctp_front_pair_probe import select_ctp_front_pair
from .ctp_production_readonly_admission import (
    CtpProductionReadOnlyAdmissionError,
    CtpProductionReadOnlyRegistration,
    production_account_binding_sha256,
    require_ctp_production_readonly_config_binding,
)
from .ctp_production_readonly_runtime import (
    CtpProductionReadOnlyQuerySnapshot,
    CtpProductionReadOnlyMarketDataObservation,
    CtpProductionReadOnlyRuntimeError,
    CtpProductionReadOnlySessionIdentity,
    CtpProductionReadOnlySessionRequest,
    _LOCAL_TD_FRONT_EVIDENCE,
)
from .ctp_sdk_readonly import _QUERY_ORDER, _SNAPSHOT_NAMES
from .ctp_preflight import REQUIRED_CTP_READ_ONLY_QUERIES
from .config import RuntimeConfig
from .registry import RuntimeRegistry
from .ctp_sdk_market_readonly import (
    _AccountLease,
    _MAX_NATIVE_JOIN_WAIT_SECONDS,
    _account_lock_key,
    _client_state_error,
    _error_id,
    _hold_lease_unknown,
    _instrument_text,
    _md_client_snapshot,
    _valid_tick,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ACCOUNT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WRITE_COUNTERS = ("settlement_confirm", "order_insert", "order_action")
_KNOWN_REQUEST_COUNTERS = frozenset(
    (
        "authenticate",
        "login",
        "settlement_confirm",
        "order_insert",
        "order_action",
        "query_account",
        "query_positions",
        "query_orders",
        "query_trades",
        "query_instruments",
        "query_margin_rate",
        "query_commission_rate",
        "query_depth_market_data",
        "query_option_trade_cost",
        "query_option_commission_rate",
        "query_settlement_confirmation",
    )
)
_MAX_SESSION_SECONDS = 60.0
_MAX_CLOSE_JOIN_WAIT_SECONDS = 1.0
_MD_TICK_OBSERVATION_SECONDS = 5.0


class CtpProductionSdkReadOnlyError(ValueError):
    """Redacted rejection from the production SDK read adapter."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("CTP production read-only SDK session rejected: {0}".format(reason))


def _reject(reason: str) -> NoReturn:
    raise CtpProductionSdkReadOnlyError(reason) from None


def _default_sdk_components() -> Tuple[Any, Any]:
    """Import SDK types lazily after config, pin, and credential gates pass."""

    from bt_api_ctp import CtpNativeQueryCertificateBuilder
    from bt_api_ctp.ctp.client import TraderClient

    return TraderClient, CtpNativeQueryCertificateBuilder


def _default_md_client_type() -> Any:
    """Import the MD client only after the seven TD queries have completed."""

    from bt_api_ctp.ctp.client import MdClient

    return MdClient


def _deadline_remaining(valid_until: float, monotonic_deadline: float) -> float:
    wall_remaining = valid_until - time.time()
    monotonic_remaining = monotonic_deadline - time.monotonic()
    if not math.isfinite(wall_remaining) or not math.isfinite(monotonic_remaining):
        _reject("session_clock_invalid")
    remaining = min(wall_remaining, monotonic_remaining)
    if remaining <= 0:
        _reject("session_deadline_expired")
    return remaining


def _front_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_request(
    request: CtpProductionReadOnlySessionRequest,
    binding: Any,
) -> None:
    if type(request) is not CtpProductionReadOnlySessionRequest:
        _reject("invalid_request")
    if (
        request.environment != binding.environment
        or not hmac.compare_digest(request.account_binding_sha256, binding.account_binding_sha256)
        or not hmac.compare_digest(request.front_pair_set_sha256, binding.front_pair_set_sha256)
        or not hmac.compare_digest(request.md_front_sha256, _front_digest(binding.md_front))
        or not hmac.compare_digest(request.td_front_sha256, _front_digest(binding.td_front))
        or request.instrument_id != binding.instrument_id
        or request.exchange_id != binding.exchange_id
        or request.hedge_flag != binding.hedge_flag
    ):
        _reject("request_scope_mismatch")
    remaining = request.valid_until - time.time()
    if not math.isfinite(remaining):
        _reject("session_clock_invalid")
    if remaining <= 0 or remaining > _MAX_SESSION_SECONDS:
        _reject("session_deadline_invalid")


def _require_zero_writes(client: Any) -> dict[str, int]:
    try:
        counts = client.get_request_counts()
    except Exception:
        _reject("native_write_counts_unavailable")
    if (
        type(counts) is not dict
        or not set(_WRITE_COUNTERS).issubset(counts)
        or not set(counts).issubset(_KNOWN_REQUEST_COUNTERS)
        or any(type(value) is not int or value < 0 for value in counts.values())
        or any(counts[name] != 0 for name in _WRITE_COUNTERS)
    ):
        _reject("native_write_detected")
    return dict.fromkeys(_WRITE_COUNTERS, 0)


def _close_client_read_only(client: Any) -> None:
    """Stop one native client and verify its bounded thread shutdown."""

    try:
        has_thread_slot = hasattr(client, "_thread")
        join_thread = getattr(client, "_thread", None)
        join_active = getattr(client, "_join_active", None)
        native_init_started = getattr(client, "_native_init_started", None)
        join_state_known = (
            has_thread_slot and type(join_active) is bool and type(native_init_started) is bool
        )
        join_state_uncertain = (
            join_state_known and join_thread is None and (join_active or native_init_started)
        )
    except Exception:
        join_thread = None
        join_state_known = False
        join_state_uncertain = True

    try:
        client.stop()
    except Exception:
        _reject("session_close_failed")

    if not join_state_known:
        _reject("session_join_state_unknown")
    if join_thread is not None:
        try:
            join_thread.join(_MAX_CLOSE_JOIN_WAIT_SECONDS)
            if join_thread.is_alive():
                _reject("session_close_incomplete")
        except CtpProductionSdkReadOnlyError:
            raise
        except Exception:
            _reject("session_join_state_unknown")
    if join_state_uncertain:
        _reject("session_close_incomplete")
    try:
        if (
            getattr(client, "_join_active", None) is not False
            or getattr(client, "_native_init_started", None) is not False
        ):
            _reject("session_close_incomplete")
    except CtpProductionSdkReadOnlyError:
        raise
    except Exception:
        _reject("session_join_state_unknown")


def _require_connected_td_front(
    client: Any,
    binding: Any,
    connection_generation: int,
) -> None:
    """Require the SDK's generation-fenced local CTP front callback state."""

    try:
        reader = getattr(client, "get_front_binding_state", None)
        evidence = reader() if callable(reader) else None
    except Exception:
        evidence = None
    required_keys = {
        "configured_front",
        "registered_front",
        "connection_confirmed_front",
        "connected",
        "connection_generation",
        "native_api_current",
        "bound_identity_current",
    }
    if type(evidence) is not dict or set(evidence) != required_keys:
        _reject("front_binding_evidence_unavailable")
    front_fields = (
        evidence.get("configured_front"),
        evidence.get("registered_front"),
        evidence.get("connection_confirmed_front"),
    )
    if any(type(value) is not str for value in front_fields) or any(
        value != binding.td_front for value in front_fields
    ):
        _reject("session_front_mismatch")
    if (
        evidence.get("connected") is not True
        or evidence.get("native_api_current") is not True
        or evidence.get("bound_identity_current") is not True
        or type(evidence.get("connection_generation")) is not int
        or evidence.get("connection_generation") != connection_generation
    ):
        _reject("front_binding_generation_mismatch")


def _identity_from_client(
    client: Any,
    binding: Any,
) -> CtpProductionReadOnlySessionIdentity:
    try:
        scope = client.get_query_session_scope()
        if scope.read_only_ready is not True:
            _reject("session_not_read_only_ready")
        broker_id = scope.broker_id
        investor_id = scope.investor_id
        if (
            type(broker_id) is not str
            or not _ACCOUNT_ID_RE.fullmatch(broker_id)
            or type(investor_id) is not str
            or not _ACCOUNT_ID_RE.fullmatch(investor_id)
        ):
            _reject("session_account_identity_invalid")
        account_digest = production_account_binding_sha256(broker_id, investor_id)
        if not hmac.compare_digest(account_digest, binding.account_binding_sha256):
            _reject("session_account_mismatch")
        _require_connected_td_front(client, binding, scope.connection_generation)
        return CtpProductionReadOnlySessionIdentity(
            account_binding_sha256=account_digest,
            trading_day=scope.trading_day,
            connection_generation=scope.connection_generation,
            md_front_sha256=_front_digest(binding.md_front),
            td_front_sha256=_front_digest(binding.td_front),
            td_front_binding_evidence=_LOCAL_TD_FRONT_EVIDENCE,
        )
    except CtpProductionSdkReadOnlyError:
        raise
    except Exception:
        _reject("session_identity_unavailable")


def _probe_production_market_readonly(
    *,
    binding: Any,
    broker_id: str,
    user_id: str,
    password: str,
    client_type: Any,
    timeout_seconds: float,
    tick_observation_seconds: float = _MD_TICK_OBSERVATION_SECONDS,
) -> CtpProductionReadOnlyMarketDataObservation:
    """Run one exact production MD login, subscription, and post-ack tick.

    The production config admission happens in the caller. This helper takes
    only that sealed binding's literal front and contract values; it has no
    profile selector or endpoint fallback. Its callback evidence remains
    local to the injected SDK and does not prove the remote endpoint identity.
    """

    if not callable(client_type):
        _reject("market_client_type_required")
    if (
        type(timeout_seconds) not in (int, float)
        or not math.isfinite(float(timeout_seconds))
        or timeout_seconds <= 0
        or timeout_seconds > _MAX_SESSION_SECONDS
        or type(tick_observation_seconds) not in (int, float)
        or not math.isfinite(float(tick_observation_seconds))
        or tick_observation_seconds <= 0
        or tick_observation_seconds > timeout_seconds
    ):
        _reject("market_timeout_invalid")
    front = binding.md_front
    instrument = binding.instrument_id
    exchange = binding.exchange_id
    account_digest = production_account_binding_sha256(broker_id, user_id)
    if not hmac.compare_digest(account_digest, binding.account_binding_sha256):
        _reject("market_account_mismatch")

    deadline = time.monotonic() + float(timeout_seconds)
    try:
        lease = _AccountLease(_account_lock_key(binding.account_binding_sha256))
        lease.acquire()
    except Exception as exc:
        _reject(getattr(exc, "reason", "market_account_probe_busy"))

    client = None
    client_started = False
    stop_failed = False
    close_state = "not_started"
    primary_error: str | None = None
    observation = None
    join_thread = None
    condition: threading.Condition | None = None
    state: dict[str, Any] | None = None
    try:
        if time.monotonic() >= deadline:
            _reject("market_probe_deadline_expired")
        # Preserve the configured address byte-for-byte. In particular, do
        # not map a production front through the SimNow profile table.
        client = client_type(front, broker_id, user_id, password)
        initial_snapshot = _md_client_snapshot(client)
        if initial_snapshot is None:
            _reject("market_client_state_unavailable")
        assert initial_snapshot is not None
        if initial_snapshot[0] != front:
            _reject("market_front_binding_mismatch")
        if initial_snapshot[1] != broker_id or initial_snapshot[2] != user_id:
            _reject("market_client_identity_mismatch")

        condition = threading.Condition()
        state = {
            "closed": False,
            "error": None,
            "login": False,
            "login_generation": None,
            "subscription_ack": False,
            "subscription_generation": None,
            "tick_count": 0,
            "tick_deadline": None,
        }

        def record_error(reason: str) -> None:
            with condition:
                if not state["closed"] and state["error"] is None:
                    state["error"] = reason
                    condition.notify_all()

        def validate_current_state() -> tuple[Any, ...] | None:
            snapshot = _md_client_snapshot(client)
            reason = _client_state_error(
                snapshot,
                front=front,
                broker_id=broker_id,
                user_id=user_id,
            )
            if reason is not None:
                record_error(reason)
                return None
            return snapshot

        def on_login(login_field: Any) -> None:
            snapshot = validate_current_state()
            if snapshot is None:
                return
            try:
                login_broker = getattr(login_field, "BrokerID")
                login_user = getattr(login_field, "UserID")
            except Exception:
                record_error("market_login_identity_unavailable")
                return
            if type(login_broker) is not str or type(login_user) is not str:
                record_error("market_login_identity_unavailable")
                return
            if login_broker != broker_id or login_user != user_id:
                record_error("market_login_identity_mismatch")
                return
            assert snapshot is not None
            with condition:
                if not state["closed"] and state["error"] is None:
                    state["login"] = True
                    state["login_generation"] = snapshot[3]
                    condition.notify_all()

        def on_error(response: Any) -> None:
            if _error_id(response) != 0:
                record_error("market_front_rejected")
                return
            with condition:
                if state["closed"] or state["error"] is not None:
                    return
                if state["login"] and state["subscription_ack"]:
                    return
                state["error"] = (
                    "market_login_identity_mismatch"
                    if not state["login"]
                    else "market_subscription_rejected"
                )
                condition.notify_all()

        def on_disconnect(_reason: Any) -> None:
            with condition:
                if not state["closed"]:
                    state["error"] = state["error"] or "market_front_disconnected"
                    condition.notify_all()

        def on_subscribe(specific_instrument: Any, response: Any) -> None:
            if _instrument_text(specific_instrument) != instrument:
                record_error("market_subscription_instrument_mismatch")
                return
            if _error_id(response) != 0:
                record_error("market_subscription_rejected")
                return
            snapshot = validate_current_state()
            if snapshot is None:
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
                state["subscription_ack"] = True
                state["subscription_generation"] = snapshot[3]
                state["tick_deadline"] = min(
                    deadline, time.monotonic() + float(tick_observation_seconds)
                )
                condition.notify_all()

        def on_tick(tick: Any) -> None:
            if not _valid_tick(tick, instrument, exchange):
                return
            snapshot = validate_current_state()
            if snapshot is None:
                return
            assert snapshot is not None
            with condition:
                if state["closed"] or state["error"] is not None:
                    return
                login_generation = state["login_generation"]
                subscription_generation = state["subscription_generation"]
                tick_deadline = state["tick_deadline"]
                if not state["subscription_ack"] or tick_deadline is None:
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
                state["tick_count"] += 1
                condition.notify_all()

        client.on_login = on_login
        client.on_error = on_error
        client.on_disconnect = on_disconnect
        client.on_subscribe = on_subscribe
        client.on_tick = on_tick
        client.subscribe([instrument])
        client_started = True
        client.start(block=False)

        with condition:
            if time.monotonic() >= deadline:
                _reject("market_probe_deadline_expired")
            while not (state["login"] and state["subscription_ack"]):
                if state["error"]:
                    _reject(state["error"])
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _reject(
                        "market_login_timeout"
                        if not state["login"]
                        else "market_subscription_ack_timeout"
                    )
                condition.wait(remaining)
            tick_deadline = state["tick_deadline"]
            while state["tick_count"] < 1:
                if state["error"]:
                    _reject(state["error"])
                remaining = tick_deadline - time.monotonic()
                if remaining <= 0:
                    _reject("market_tick_not_observed")
                condition.wait(remaining)
            if state["error"]:
                _reject(state["error"])
            snapshot = _md_client_snapshot(client)
            reason = _client_state_error(
                snapshot,
                front=front,
                broker_id=broker_id,
                user_id=user_id,
            )
            if reason is not None:
                _reject(reason)
            assert snapshot is not None
            login_generation = state["login_generation"]
            if (
                login_generation is None
                or state["subscription_generation"] != login_generation
                or snapshot[3] != login_generation
            ):
                _reject("market_connection_generation_changed")
            observation = CtpProductionReadOnlyMarketDataObservation(
                md_front_sha256=_front_digest(front),
                account_binding_sha256=binding.account_binding_sha256,
                instrument_id=instrument,
                exchange_id=exchange,
                tick_observation_count=state["tick_count"],
                connection_generation=snapshot[3],
                client_stop_returned=True,
                native_join_pending=False,
            )
            state["closed"] = True
    except CtpProductionSdkReadOnlyError as exc:
        primary_error = exc.reason
    except Exception:
        primary_error = "market_probe_failed"
    finally:
        if client is not None:
            try:
                join_thread = getattr(client, "_thread", None)
            except Exception:
                join_thread = None
            try:
                if condition is not None and state is not None:
                    with condition:
                        state["closed"] = True
                client.stop()
                close_state = "stop_returned"
            except Exception:
                close_state = "stop_failed"
                stop_failed = True

            pending = False
            if join_thread is not None:
                try:
                    join_thread.join(
                        min(
                            _MAX_NATIVE_JOIN_WAIT_SECONDS,
                            max(0.0, deadline - time.monotonic()),
                        )
                    )
                    pending = bool(join_thread.is_alive())
                except Exception:
                    pending = True
            join_tracking_unknown = client_started and not hasattr(client, "_thread")
            if pending:
                close_state = "native_join_pending"
                _hold_lease_unknown(lease, client, join_thread)
            elif join_tracking_unknown:
                close_state = "native_join_state_unknown"
                _hold_lease_unknown(lease, client, join_thread)
            elif stop_failed:
                _hold_lease_unknown(lease, client, join_thread)
            else:
                lease.release()
        else:
            lease.release()

    if stop_failed:
        _reject("market_client_stop_failed")
    if close_state == "native_join_pending":
        _reject("market_client_join_pending")
    if close_state == "native_join_state_unknown":
        _reject("market_client_join_state_unknown")
    if primary_error is not None:
        _reject(primary_error)
    if observation is None:
        _reject("market_probe_failed")
    assert observation is not None
    return observation


class _CtpProductionSdkReadOnlySession:
    """Narrow public API; trusted in-process callers can inspect private state."""

    __slots__ = (
        "_binding",
        "_builder_type",
        "_client",
        "_closed",
        "_close_complete",
        "_connect_timeout",
        "_broker_id",
        "_user_id",
        "_password",
        "_md_client_type_loader",
        "_td_close_complete",
        "_identity_cache",
        "_snapshot_cache",
        "_monotonic_deadline",
        "_query_timeout",
        "_valid_until",
    )

    def __init__(
        self,
        client: Any,
        builder_type: Any,
        binding: Any,
        valid_until: float,
        monotonic_deadline: float,
        query_timeout: float,
        connect_timeout: float,
        broker_id: str,
        user_id: str,
        password: str,
        md_client_type_loader: Callable[[], Any],
    ) -> None:
        self._client = client
        self._builder_type = builder_type
        self._binding = binding
        self._valid_until = valid_until
        self._monotonic_deadline = monotonic_deadline
        self._query_timeout = query_timeout
        self._connect_timeout = connect_timeout
        self._broker_id = broker_id
        self._user_id = user_id
        self._password = password
        self._md_client_type_loader = md_client_type_loader
        self._td_close_complete = False
        self._identity_cache: Optional[CtpProductionReadOnlySessionIdentity] = None
        self._snapshot_cache: Optional[CtpProductionReadOnlyQuerySnapshot] = None
        self._closed = False
        self._close_complete = False

    def __repr__(self) -> str:
        return "CtpProductionSdkReadOnlySession(environment='production', client=<redacted>)"

    def _require_open(self) -> float:
        if self._closed:
            _reject("session_closed")
        return _deadline_remaining(self._valid_until, self._monotonic_deadline)

    def read_identity(self) -> CtpProductionReadOnlySessionIdentity:
        if self._td_close_complete and self._identity_cache is not None:
            if self._closed:
                _reject("session_closed")
            _deadline_remaining(self._valid_until, self._monotonic_deadline)
            return self._identity_cache
        self._require_open()
        identity = _identity_from_client(self._client, self._binding)
        _require_zero_writes(self._client)
        self._require_open()
        return identity

    def read_query_snapshot(self) -> CtpProductionReadOnlyQuerySnapshot:
        if self._snapshot_cache is not None:
            self._require_open()
            return self._snapshot_cache
        first_identity = self.read_identity()
        try:
            builder = self._builder_type(
                self._client,
                instrument_id=self._binding.instrument_id,
                exchange_id=self._binding.exchange_id,
                hedge_flag=self._binding.hedge_flag,
            )
            for query_name, method_name in _QUERY_ORDER:
                remaining = self._require_open()
                method = getattr(self._client, method_name)
                timeout = min(remaining, self._query_timeout)
                if query_name == "instruments":
                    result = method(
                        instrument_id=self._binding.instrument_id,
                        exchange_id=self._binding.exchange_id,
                        timeout=timeout,
                    )
                elif query_name == "margin_rate":
                    result = method(
                        self._binding.instrument_id,
                        exchange_id=self._binding.exchange_id,
                        hedge_flag=self._binding.hedge_flag,
                        timeout=timeout,
                    )
                elif query_name == "commission_rate":
                    result = method(
                        self._binding.instrument_id,
                        exchange_id=self._binding.exchange_id,
                        timeout=timeout,
                    )
                else:
                    result = method(timeout=timeout)
                builder.add(result)
                _require_zero_writes(self._client)
                if self.read_identity() != first_identity:
                    _reject("session_identity_changed")
            certificate = builder.finish()
            final_identity = self.read_identity()
            if final_identity != first_identity:
                _reject("session_identity_changed")
            normalized_query_digests = tuple(
                (_SNAPSHOT_NAMES.get(name, name), digest)
                for name, digest in certificate.query_digests
            )
            if tuple(sorted(name for name, _ in normalized_query_digests)) != tuple(
                sorted(REQUIRED_CTP_READ_ONLY_QUERIES)
            ):
                _reject("incomplete_query_set")
            # Close TD before loading or constructing MdClient. The production
            # MD pass is a distinct read-only client and starts only after the
            # complete seven-query certificate has been built.
            self._identity_cache = final_identity
            self._close_td_client()
            self._require_open()
            md_password = self._password
            self._password = ""
            try:
                md_client_type = self._md_client_type_loader()
            except Exception:
                _reject("market_sdk_import_failed")
            remaining = self._require_open()
            market_observation = _probe_production_market_readonly(
                binding=self._binding,
                broker_id=self._broker_id,
                user_id=self._user_id,
                password=md_password,
                client_type=md_client_type,
                timeout_seconds=min(remaining, self._connect_timeout),
                tick_observation_seconds=min(
                    _MD_TICK_OBSERVATION_SECONDS,
                    remaining,
                    self._connect_timeout,
                ),
            )
            _require_zero_writes(self._client)
            if self.read_identity() != first_identity:
                _reject("session_identity_changed")
            query_digests = tuple(
                (_SNAPSHOT_NAMES.get(name, name), digest)
                for name, digest in certificate.query_digests
            )
            snapshot = CtpProductionReadOnlyQuerySnapshot.from_query_digests(
                first_identity,
                query_digests,
                instrument_id=self._binding.instrument_id,
                exchange_id=self._binding.exchange_id,
                hedge_flag=self._binding.hedge_flag,
                native_certificate_sha256=certificate.certificate_sha256,
                market_data_observation=market_observation,
            )
            self._snapshot_cache = snapshot
            return snapshot
        except CtpProductionSdkReadOnlyError:
            raise
        except CtpProductionReadOnlyRuntimeError:
            _reject("native_query_certificate_failed")
        except Exception:
            _reject("native_query_certificate_failed")

    def read_write_counters(self) -> Mapping[str, int]:
        return _require_zero_writes(self._client)

    def _close_td_client(self) -> None:
        if self._td_close_complete:
            return
        _close_client_read_only(self._client)
        _require_zero_writes(self._client)
        self._td_close_complete = True

    def close_read_only(self) -> None:
        if self._closed:
            if not self._close_complete:
                _reject("session_close_incomplete")
            return
        self._closed = True
        self._close_td_client()
        _require_zero_writes(self._client)
        self._close_complete = True


class CtpProductionSdkReadOnlySessionFactory:
    """Production-only seven-query SDK adapter with no write interface."""

    def __init__(
        self,
        *,
        config: RuntimeConfig,
        registry: RuntimeRegistry,
        admission_registration: CtpProductionReadOnlyRegistration,
        connect_timeout: float = 15.0,
        query_timeout: float = 5.0,
        sdk_components_loader: Optional[Callable[[], Tuple[Any, Any]]] = None,
        md_client_type_loader: Optional[Callable[[], Any]] = None,
    ) -> None:
        if type(config) is not RuntimeConfig:
            raise TypeError("config must be a sealed RuntimeConfig")
        if type(registry) is not RuntimeRegistry:
            raise TypeError("registry must be a RuntimeRegistry")
        if type(admission_registration) is not CtpProductionReadOnlyRegistration:
            raise TypeError("admission_registration must be an exact production pin")
        if type(connect_timeout) not in (int, float) or not 0 < connect_timeout <= 60:
            raise ValueError("invalid production read-only connect timeout")
        if type(query_timeout) not in (int, float) or not 0 < query_timeout <= 30:
            raise ValueError("invalid production read-only query timeout")
        self._config = config
        self._registry = registry
        self._admission_registration = admission_registration
        self._connect_timeout = float(connect_timeout)
        self._query_timeout = float(query_timeout)
        self._sdk_components_loader = sdk_components_loader or _default_sdk_components
        self._md_client_type_loader = md_client_type_loader or _default_md_client_type

    def __repr__(self) -> str:
        return "CtpProductionSdkReadOnlySessionFactory(environment='production', credentials=<deferred>)"

    def open_read_only(
        self,
        request: CtpProductionReadOnlySessionRequest,
    ) -> _CtpProductionSdkReadOnlySession:
        try:
            candidate_binding = require_ctp_production_readonly_config_binding(
                self._config,
                self._registry,
                self._admission_registration,
            )
        except CtpProductionReadOnlyAdmissionError as error:
            if error.reason == "legacy_front_pin_incompatible_with_multi_pair_config":
                _reject("legacy_front_pin_incompatible_with_multi_pair_config")
            _reject("config_binding_rejected")
        except Exception:
            _reject("config_binding_rejected")
        selected_pairs = tuple(
            (md_front, td_front)
            for md_front, td_front in candidate_binding.front_pairs
            if hmac.compare_digest(_front_digest(md_front), request.md_front_sha256)
            and hmac.compare_digest(_front_digest(td_front), request.td_front_sha256)
        )
        if len(selected_pairs) != 1:
            _reject("request_scope_mismatch")
        try:
            binding = require_ctp_production_readonly_config_binding(
                self._config,
                self._registry,
                self._admission_registration,
                selected_front_pair=selected_pairs[0],
            )
        except Exception:
            _reject("config_binding_rejected")
        _validate_request(request, binding)

        # The public wrapper ranks configured candidates before creating its
        # request. This lower-level factory also enforces reachability when
        # called directly: probe exactly the request-selected sealed pair, as
        # a one-item set, so this gate can neither rerank nor fall back.
        try:
            selected_probe = select_ctp_front_pair(
                ({"md_front": binding.md_front, "td_front": binding.td_front},),
                timeout_seconds=2.0,
                max_pairs=1,
                repeated_samples=3,
            )
        except Exception:
            _reject("front_probe_rejected")
        if (
            getattr(getattr(selected_probe, "pair", None), "md_front", None)
            != binding.md_front
            or getattr(getattr(selected_probe, "pair", None), "td_front", None)
            != binding.td_front
        ):
            _reject("front_probe_selection_mismatch")
        remaining = request.valid_until - time.time()
        monotonic_deadline = time.monotonic() + remaining
        _deadline_remaining(request.valid_until, monotonic_deadline)

        # A production wheel pair needs its own code-reviewed pin. Keep this
        # gate ahead of any private credential read or native SDK import.
        try:
            verify_ctp_production_sdk_artifact_provenance()
        except Exception:
            _reject("artifact_provenance_rejected")

        # Resolve only after both the exact sealed config and every request
        # selector match the production pin. Credential access rechecks the
        # private config ACL and provenance on every individual read.
        try:
            credentials = resolve_ctp_production_credentials(
                self._config,
                self._registry,
                self._admission_registration,
            )
            if type(credentials) is not CtpProductionCredentials:
                _reject("credential_resolution_invalid")
            require_ctp_production_credentials_seal(
                credentials,
                config=self._config,
                registry=self._registry,
                admission_registration=self._admission_registration,
            )
            if (
                credentials.scope.provider != "ctp"
                or credentials.scope.provider_environment != "production"
                or credentials.scope.policy_environment != "production"
                or credentials.scope.account_fingerprint_sha256 != binding.account_binding_sha256
            ):
                _reject("credential_scope_mismatch")
            broker_id = credentials.require_credential("broker_id")
            user_id = credentials.require_credential("user_id")
            password = credentials.require_credential("password")
            app_id = credentials.require_credential("app_id")
            auth_code = credentials.require_credential("auth_code")
        except CtpProductionSdkReadOnlyError:
            raise
        except CtpProductionCredentialResolutionError:
            _reject("credential_unavailable")
        except Exception:
            _reject("credential_unavailable")
        if (
            not _ACCOUNT_ID_RE.fullmatch(broker_id)
            or not _ACCOUNT_ID_RE.fullmatch(user_id)
            or not hmac.compare_digest(
                production_account_binding_sha256(broker_id, user_id),
                binding.account_binding_sha256,
            )
        ):
            _reject("credential_account_mismatch")
        _deadline_remaining(request.valid_until, monotonic_deadline)

        client = None
        session = None
        try:
            client_type, builder_type = self._sdk_components_loader()
            _deadline_remaining(request.valid_until, monotonic_deadline)
            client = client_type(
                binding.td_front,
                broker_id,
                user_id,
                password,
                app_id=app_id,
                auth_code=auth_code,
                auto_settlement_confirm=False,
            )
            # Own the client before start so every post-construction failure
            # gets the same bounded stop/join and zero-write verification.
            session = _CtpProductionSdkReadOnlySession(
                client,
                builder_type,
                binding,
                request.valid_until,
                monotonic_deadline,
                self._query_timeout,
                self._connect_timeout,
                broker_id,
                user_id,
                password,
                self._md_client_type_loader,
            )
            client.start(block=False)
            remaining = _deadline_remaining(request.valid_until, monotonic_deadline)
            if client.wait_ready(timeout=min(remaining, self._connect_timeout)) is not True:
                _reject("session_not_read_only_ready")
            state = client.get_session_state()
            if type(state) is not dict or state.get("auto_settlement_confirm") is not False:
                _reject("settlement_write_not_disabled")
            _identity_from_client(client, binding)
            _require_zero_writes(client)
            session.read_identity()
            return session
        except CtpProductionSdkReadOnlyError:
            if session is not None:
                session.close_read_only()
            elif client is not None:
                _close_client_read_only(client)
            raise
        except Exception:
            if session is not None:
                session.close_read_only()
            elif client is not None:
                _close_client_read_only(client)
            _reject("session_open_failed")


__all__ = [
    "CtpProductionSdkReadOnlyError",
    "CtpProductionSdkReadOnlySessionFactory",
]
