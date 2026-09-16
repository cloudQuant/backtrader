"""Fail-closed SimNow adapter for the Iteration 23 low-frequency example.

The adapter is deliberately small and owns no CTP client.  A caller must
inject either an already-created ``bt_api_py`` API object (or a pure mock), or
explicitly transfer one preflight-owned ``BtApiStore``.  This keeps credential
loading and native authorization in their owning SDK while making one runtime
lifecycle and the example's startup/reconciliation contract testable.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Mapping

import backtrader as bt

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds import BarEvidence, ClockMapping
from backtrader.stores.btapistore import BtApiStore

try:
    from .ctp_options_lowfreq_strategy import CtpOptionsLowfreqStrategy
except ImportError:  # Direct execution through this directory's run.py.
    from ctp_options_lowfreq_strategy import CtpOptionsLowfreqStrategy


class SimNowAdapterError(RuntimeError):
    """A missing or contradictory native precondition."""


class SimNowBlocked(SimNowAdapterError):
    """The adapter cannot safely enter the requested engineering path."""


# This adapter does not discover credentials or profiles.  It accepts only the
# named second-set operator context passed by a separately governed owner.
SECOND_SET_ENGINEERING_PROFILE = "simnow_second_7x24"
ENGINEERING_OBSERVATION_MAX_SECONDS = 3600.0
ENGINEERING_OBSERVATION_CANDIDATE_ID = "ctp_options_lowfreq-second-set-engineering-observation-v1"
ENGINEERING_OBSERVATION_G3_STATUS = "NOT_RUN_ENGINEERING_STRATEGY_OBSERVATION"
# The SDK route can expose a concrete reachable variant while the caller uses
# the stable operator label above.  Only this public-session family proves the
# intended second SimNow environment; the caller label is merely an admission
# request and is never reported as verified identity.
SECOND_SET_SESSION_PROFILE_PREFIX = "set2_7x24"
_ADAPTER_SCOPED_WRITE_EVIDENCE_BOUNDARY = (
    "NOT_PROVEN: the adapter membrane and market_data_only Broker only observe "
    "adapter-routed attempts; they cannot attest raw external provider writes."
)
_INJECTED_STORE_WRITE_EVIDENCE_BOUNDARY = (
    "NOT_PROVEN: the transferred Store and market_data_only Broker only observe "
    "Store-routed attempts; they cannot attest raw external provider writes."
)
# Keep this stable if a focused test replaces the construction symbol.  The
# Store-injected path accepts only a real, caller-created BtApiStore and must
# never construct a second Store from ``store.sdk_api``.
_BTAPI_STORE_TYPE = BtApiStore


class _ObservationReadOnlyApi:
    """Allow only public reads and lifecycle calls on an injected SDK.

    The only allowed configuration is the irreversible narrowing to
    ``market_data_only=True`` required by some managed SDK sessions at Store
    startup.  The wrapper never creates a client and never gives the example a
    way to construct, arm, settle, cancel, or submit an execution session.
    """

    _FORBIDDEN_METHODS = frozenset(
        {
            "submit_order",
            "make_order",
            "async_make_order",
            "place_order",
            "create_order",
            "send_order",
            "order_insert",
            "req_order_insert",
            "ReqOrderInsert",
            "cancel_order",
            "async_cancel_order",
            "order_action",
            "req_order_action",
            "ReqOrderAction",
            "settlement_confirm",
            "confirm_settlement",
            "confirm_ctp_settlement",
            "prepare_settlement",
            "prepare_ctp_settlement",
            "prepare_execution_authorization",
            "configure_ctp_execution_authorization",
            "configure_execution_authorization",
            "arm_execution",
            "arm_sdk_execution",
            "arm_execution_recovery",
            "complete_execution_recovery",
            "prepare_execution_recovery",
            "abort_execution_recovery",
            "enable_execution",
            "enable_trading",
            "disarm_execution",
            "arm_execution_from_preflight",
            "arm_execution_from_approval",
            "confirm_ctp_settlement_from_approval",
        }
    )
    _SAFE_READ_PREFIXES = (
        "get_",
        "query_",
        "list_",
        "fetch_",
        "poll_",
        "read_",
        "is_",
        "has_",
        "iter_",
        "supports_",
        "async_get_",
        "async_query_",
        "async_list_",
        "async_fetch_",
        "async_poll_",
    )
    _SAFE_READ_METHODS = frozenset({"get_ctp_session_state"})
    _SAFE_LIFECYCLE_METHODS = frozenset(
        {"connect", "disconnect", "close", "start", "stop", "subscribe", "unsubscribe"}
    )
    _FORBIDDEN_METHODS_NORMALIZED = frozenset(method.lower() for method in _FORBIDDEN_METHODS)

    def __init__(self, api: Any) -> None:
        """Wrap a caller-injected SDK API inside the read-only membrane."""

        if api is None:
            raise SimNowBlocked("SDK_NOT_INJECTED")
        self._api = api
        self._forbidden_write_attempts: dict[str, int] = {}
        self._safe_market_data_only_configuration_calls = 0

    def _blocked(self, method_name: str) -> None:
        self._forbidden_write_attempts[method_name] = (
            self._forbidden_write_attempts.get(method_name, 0) + 1
        )
        raise SimNowBlocked(f"FORBIDDEN_WRITE_ATTEMPT:{method_name}")

    def configure_execution(self, execution_config: Any) -> Any:
        """Permit only an exact, non-arming managed-SDK configuration."""

        if not isinstance(execution_config, Mapping) or dict(execution_config) != {
            "market_data_only": True
        }:
            self._blocked("configure_execution")
        configure = getattr(self._api, "configure_execution", None)
        if not callable(configure):
            raise SimNowBlocked("SDK_MARKET_DATA_ONLY_UNAVAILABLE")
        self._safe_market_data_only_configuration_calls += 1
        return configure({"market_data_only": True})

    def __getattr__(self, name: str) -> Any:
        if self._is_forbidden_method(name):
            return lambda *_args, **_kwargs: self._blocked(name)
        value = getattr(self._api, name)
        if callable(value) and not self._is_safe_callable(name):
            return lambda *_args, **_kwargs: self._blocked(name)
        return value

    @classmethod
    def _is_forbidden_method(cls, name: str) -> bool:
        return str(name).lower() in cls._FORBIDDEN_METHODS_NORMALIZED

    @classmethod
    def _is_safe_callable(cls, name: str) -> bool:
        normalized = str(name).lower()
        return (
            normalized in cls._SAFE_LIFECYCLE_METHODS
            or normalized in cls._SAFE_READ_METHODS
            or normalized.startswith(cls._SAFE_READ_PREFIXES)
        )

    def audit(self) -> dict[str, Any]:
        """Return aggregate membrane facts without exposing API configuration."""

        return {
            "forbidden_write_attempts": dict(sorted(self._forbidden_write_attempts.items())),
            "safe_market_data_only_configuration_calls": self._safe_market_data_only_configuration_calls,
        }


class _ObservationClockProvider:
    """Translate the caller's calibrated monotonic source into strategy time."""

    def __init__(self, *, feed_clock: Any, clock_mapping: ClockMapping) -> None:
        """Hold the calibrated feed clock and its mapping for later calls."""

        self._feed_clock = feed_clock
        self._clock_mapping = clock_mapping

    def __call__(self) -> dict[str, Any]:
        """Project the live monotonic reading onto trusted wall-clock time.

        Fail closed with ``SimNowBlocked`` unless a callable integer
        ``monotonic_ns`` source is present and its reading falls inside the
        calibrated mapping window; the returned observation is therefore
        always trusted and never synthesized.
        """
        monotonic_ns = getattr(self._feed_clock, "monotonic_ns", None)
        if not callable(monotonic_ns):
            raise SimNowBlocked("LIVE_FEED_CLOCK_REQUIRED")
        try:
            now_ns = monotonic_ns()
        except Exception as exc:
            raise SimNowBlocked("LIVE_FEED_CLOCK_REQUIRED") from exc
        if isinstance(now_ns, bool) or not isinstance(now_ns, int):
            raise SimNowBlocked("LIVE_FEED_CLOCK_REQUIRED")
        mapping = self._clock_mapping
        if now_ns < mapping.mono_ns_at_anchor or now_ns > mapping.valid_until_mono_ns:
            raise SimNowBlocked("LIVE_CLOCK_MAPPING_EXPIRED")
        wall_utc = mapping.wall_utc_at_anchor + timedelta(
            microseconds=(now_ns - mapping.mono_ns_at_anchor) / 1_000.0
        )
        return {
            "now_monotonic_ns": now_ns,
            "now_utc": wall_utc,
            "clock_domain_id": mapping.clock_domain_id,
            "generation": mapping.connection_generation,
            "trusted": True,
            "source": mapping.source,
            "boot_id": mapping.mapping_id,
            # The strategy owns its concrete bar-scope tuple.  This clock
            # establishes only transport/mapping identity and must not invent
            # a different decision scope.
            "scope": None,
            "mapping_id": mapping.mapping_id,
            "mapping_anchor_mono_ns": mapping.mono_ns_at_anchor,
            "mapping_anchor_wall_utc": mapping.wall_utc_at_anchor,
            "mapping_error_ns": mapping.error_bound_ns,
            "mapping_valid_until_mono_ns": mapping.valid_until_mono_ns,
            "session_open": True,
            "price_limits_known": False,
        }


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    for name in ("to_dict", "as_dict", "model_dump"):
        method = getattr(value, name, None)
        if callable(method):
            result = method()
            if isinstance(result, Mapping):
                return dict(result)
    try:
        return dict(vars(value))
    except TypeError as exc:
        raise SimNowBlocked("query record is not a mapping") from exc


def _records(value: Any, query_name: str) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        found = False
        for key in ("records", "data", "items", query_name):
            if key in value:
                value = value[key]
                found = True
                break
        if not found:
            return [_mapping(value)]
    if value is None or isinstance(value, (str, bytes)):
        raise SimNowBlocked(f"{query_name} query is incomplete")
    try:
        return [_mapping(item) for item in value]
    except TypeError as exc:
        raise SimNowBlocked(f"{query_name} query is not iterable") from exc


def _identity(record: Mapping[str, Any], name: str) -> Any:
    aliases = {
        "account": ("account_fingerprint", "account_id", "InvestorID", "account"),
        "trading_day": ("trading_day", "TradingDay"),
        "generation": ("generation", "connection_generation", "ConnectionGeneration"),
    }
    for key in aliases[name]:
        if key in record and record[key] not in (None, ""):
            return record[key]
    raise SimNowBlocked(f"{name} identity is missing")


def _canonical(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _engineering_duration_seconds(value: Any) -> float:
    """Accept a single bounded observation duration, never an open-ended run."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SimNowBlocked("ENGINEERING_DURATION")
    seconds = float(value)
    if (
        not math.isfinite(seconds)
        or seconds <= 0.0
        or seconds > ENGINEERING_OBSERVATION_MAX_SECONDS
    ):
        raise SimNowBlocked("ENGINEERING_DURATION")
    return seconds


_TRANSFER_IDLE_COUNTERS = (
    "queue_depth",
    "inflight",
    "publications_pending",
    "funding_queue_depth",
    "funding_pending",
    "broker_update_queue_depth",
    "broker_update_dropped",
)
_TRANSFER_IDLE_FLAGS = (
    "close_thread_alive",
    "funding_inflight",
    "funding_worker_alive",
    "read_only_metadata_probe_active",
    "restart_blocked_by_worker",
    "restart_blocked_by_close",
    "funding_restart_blocked_by_worker",
    "risk_state_latched",
)
_TRANSFER_REQUIRED_TRUE_FLAGS = ("broker_update_conservation",)


def _read_market_data_only_rejection_count(health: Mapping[str, Any]) -> int:
    rejected = health.get("rejected_market_data_only")
    if type(rejected) is not int or rejected < 0:
        raise SimNowBlocked("INJECTED_STORE_HEALTH_UNAVAILABLE")
    return rejected


def _uses_canonical_store_rejection_recorder(store: Any) -> bool:
    """Require the Store-owned aggregate audit implementation, not an override."""

    canonical = getattr(_BTAPI_STORE_TYPE, "record_market_data_only_broker_rejection", None)
    recorder = getattr(store, "record_market_data_only_broker_rejection", None)
    return (
        callable(canonical)
        and callable(recorder)
        and getattr(recorder, "__self__", None) is store
        and getattr(recorder, "__func__", None) is canonical
    )


def _require_idle_transfer_health(health: Mapping[str, Any]) -> int:
    """Return a zero write-attempt baseline for an exclusively idle Store."""

    if health.get("shutdown_state") in {"PASS", "FAIL", "INCOMPLETE"}:
        raise SimNowBlocked("ENGINEERING_STORE_OWNERSHIP_REQUIRED")
    for field in _TRANSFER_IDLE_COUNTERS:
        value = health.get(field)
        if type(value) is not int or value != 0:
            raise SimNowBlocked("ENGINEERING_STORE_OWNERSHIP_REQUIRED")
    if any(health.get(field) is not False for field in _TRANSFER_IDLE_FLAGS):
        raise SimNowBlocked("ENGINEERING_STORE_OWNERSHIP_REQUIRED")
    if any(health.get(field) is not True for field in _TRANSFER_REQUIRED_TRUE_FLAGS):
        raise SimNowBlocked("ENGINEERING_STORE_OWNERSHIP_REQUIRED")
    if health.get("last_error_code") != "":
        raise SimNowBlocked("ENGINEERING_STORE_OWNERSHIP_REQUIRED")
    if health.get("funding_last_refresh_error") is not None:
        raise SimNowBlocked("ENGINEERING_STORE_OWNERSHIP_REQUIRED")
    rejected = _read_market_data_only_rejection_count(health)
    if rejected != 0:
        raise SimNowBlocked("ENGINEERING_STORE_WRITE_BASELINE_REQUIRED")
    return rejected


def _require_transferable_observation_store(value: Any) -> tuple[BtApiStore, int]:
    """Accept one Store whose full lifecycle transfers to this run.

    The check intentionally uses only public Store contracts.  An already
    stopped Store cannot safely be reused, and recreating a Store around a
    managed SDK would create a second lifecycle.  A connected Store is valid:
    an operator may use it for one read-only CTP preflight, then explicitly
    transfer its only remaining lifecycle to this observation.  The normal
    Broker/Store start path is idempotent in that case and must not reconnect.
    """

    if not isinstance(value, _BTAPI_STORE_TYPE):
        raise SimNowBlocked("ENGINEERING_STORE_REQUIRED")
    if str(getattr(value, "provider", "")).strip().lower() != "btapi":
        raise SimNowBlocked("ENGINEERING_STORE_PROVIDER_REQUIRED")
    connected = getattr(value, "is_connected", False) is True
    health_reader = getattr(value, "get_command_health", None)
    if not callable(health_reader):
        raise SimNowBlocked("ENGINEERING_STORE_OWNERSHIP_REQUIRED")
    try:
        health = health_reader()
    except Exception as exc:
        raise SimNowBlocked("ENGINEERING_STORE_OWNERSHIP_REQUIRED") from exc
    if not isinstance(health, Mapping):
        raise SimNowBlocked("ENGINEERING_STORE_OWNERSHIP_REQUIRED")
    if not connected:
        raise SimNowBlocked("ENGINEERING_STORE_OWNERSHIP_REQUIRED")
    if not _uses_canonical_store_rejection_recorder(value):
        raise SimNowBlocked("ENGINEERING_STORE_AUDIT_CONTRACT_REQUIRED")
    return value, _require_idle_transfer_health(health)


def _store_write_guard(store: Any, *, baseline: int, ownership: str) -> dict[str, Any]:
    """Project the transferred Store's public local write fence.

    The adapter must not unwrap ``store.sdk_api`` to install a second
    membrane.  Instead, it checks public Store health after the
    market-data-only Broker completes its lifecycle.  This proves only the
    local routing fence; raw provider-side writes remain NOT_PROVEN.
    """

    health_reader = getattr(store, "get_command_health", None)
    if not callable(health_reader):
        raise SimNowBlocked("INJECTED_STORE_HEALTH_UNAVAILABLE")
    try:
        health = health_reader()
    except Exception as exc:
        raise SimNowBlocked("INJECTED_STORE_HEALTH_UNAVAILABLE") from exc
    if (
        not isinstance(health, Mapping)
        or health.get("shutdown_state") != "PASS"
        or health.get("accepting_openings") is not False
    ):
        raise SimNowBlocked("INJECTED_STORE_READ_ONLY_STATE_REQUIRED")
    rejected = _read_market_data_only_rejection_count(health)
    if rejected < baseline:
        raise SimNowBlocked("INJECTED_STORE_HEALTH_UNAVAILABLE")
    rejected_delta = rejected - baseline
    return {
        "source": "BtApiStore.get_command_health",
        "ownership": ownership,
        "forbidden_write_attempts": (
            {"store_market_data_only_rejected": rejected_delta} if rejected_delta else {}
        ),
        "accepting_openings": False,
        "rejected_market_data_only": {
            "baseline": baseline,
            "final": rejected,
            "delta": rejected_delta,
        },
    }


def _broker_write_guard(broker: Any) -> dict[str, Any]:
    """Read the Broker's public local rejected-write audit after shutdown."""

    getter = getattr(broker, "get_market_data_only_audit", None)
    if not callable(getter):
        raise SimNowBlocked("BROKER_WRITE_AUDIT_UNAVAILABLE")
    try:
        audit = getter()
    except Exception as exc:
        raise SimNowBlocked("BROKER_WRITE_AUDIT_UNAVAILABLE") from exc
    if not isinstance(audit, Mapping):
        raise SimNowBlocked("BROKER_WRITE_AUDIT_UNAVAILABLE")
    fields = ("submit_rejected", "cancel_rejected", "batch_cancel_rejected", "total_rejected")
    if any(type(audit.get(field)) is not int or audit[field] < 0 for field in fields):
        raise SimNowBlocked("BROKER_WRITE_AUDIT_UNAVAILABLE")
    total = audit["total_rejected"]
    if total != sum(audit[field] for field in fields[:-1]):
        raise SimNowBlocked("BROKER_WRITE_AUDIT_UNAVAILABLE")
    return {
        "source": "BtApiBroker.get_market_data_only_audit",
        **{field: audit[field] for field in fields},
        "forbidden_write_attempts": ({"broker_market_data_only_rejected": total} if total else {}),
    }


def _combine_write_guards(*guards: Mapping[str, Any]) -> dict[str, int]:
    combined: dict[str, int] = {}
    for guard in guards:
        attempts = guard.get("forbidden_write_attempts")
        if not isinstance(attempts, Mapping):
            raise SimNowBlocked("INJECTED_STORE_HEALTH_UNAVAILABLE")
        for name, value in attempts.items():
            if type(value) is not int or value <= 0:
                raise SimNowBlocked("INJECTED_STORE_HEALTH_UNAVAILABLE")
            combined[str(name)] = combined.get(str(name), 0) + value
    return combined


class _ObservationSessionBindingProbe(bt.Analyzer):
    """Bind the already-connected Store to one real public CTP session state."""

    params = (("on_session_bound", None),)

    def start(self) -> None:
        """Invoke the single mandatory session-binding callback at start."""

        on_session_bound = self.p.on_session_bound
        if not callable(on_session_bound):
            raise RuntimeError("engineering observation session-binding callback is unavailable")
        on_session_bound()


def _positive_generation(value: Any) -> int | None:
    """Return one exact positive public connection generation."""

    # Do not normalize a transport-supplied identity.  In particular, ``7.9``
    # and ``"7"`` must not become generation 7 merely because a caller's
    # calibrated mapping happens to use that value.
    if type(value) is not int or value <= 0:
        return None
    return value


def _require_second_set_session_binding(
    store: Any, *, clock_mapping: ClockMapping
) -> dict[str, Any]:
    """Verify the second-set identity from public Store session state only."""

    if getattr(store, "is_connected", False) is not True:
        raise SimNowBlocked("CTP_SESSION_STATE_UNAVAILABLE")
    getter = getattr(store, "get_ctp_session_state", None)
    if not callable(getter):
        raise SimNowBlocked("CTP_SESSION_STATE_UNAVAILABLE")
    try:
        state = getter()
    except Exception as exc:
        raise SimNowBlocked("CTP_SESSION_STATE_UNAVAILABLE") from exc
    if not isinstance(state, Mapping) or state.get("connected") is not True:
        raise SimNowBlocked("CTP_SESSION_STATE_UNAVAILABLE")

    profile = state.get("environment_profile")
    if not isinstance(profile, str) or not profile.startswith(SECOND_SET_SESSION_PROFILE_PREFIX):
        raise SimNowBlocked("SECOND_SET_SESSION_PROFILE_REQUIRED")

    account_fingerprint = state.get("account_fingerprint")
    if not isinstance(account_fingerprint, str) or not account_fingerprint.strip():
        raise SimNowBlocked("SESSION_ACCOUNT_FINGERPRINT_REQUIRED")
    if state.get("read_only_ready") is not True:
        raise SimNowBlocked("SESSION_READ_ONLY_NOT_READY")
    if state.get("execution_gate_armed") is not False:
        raise SimNowBlocked("SESSION_EXECUTION_GATE_NOT_UNARMED")

    session_generation = _positive_generation(state.get("connection_generation"))
    if session_generation is None:
        raise SimNowBlocked("SESSION_GENERATION_REQUIRED")
    if session_generation != clock_mapping.connection_generation:
        raise SimNowBlocked("SESSION_GENERATION_MISMATCH")

    # Keep the report useful for evidence joins while never echoing the
    # account fingerprint or any caller-provided profile label.
    return {
        "source": "BtApiStore.get_ctp_session_state",
        "session_environment_profile": profile,
        "profile_family_prefix": SECOND_SET_SESSION_PROFILE_PREFIX,
        "account_fingerprint_sha256": hashlib.sha256(account_fingerprint.encode()).hexdigest(),
        "read_only_ready": True,
        "execution_armed": False,
        "connection_generation": session_generation,
        "clock_mapping_id": clock_mapping.mapping_id,
        "clock_mapping_generation": clock_mapping.connection_generation,
    }


def _require_live_clock_mapping(
    *, clock_mapping: Any, feed_clock: Any, duration_seconds: float
) -> ClockMapping:
    """Require one caller-owned non-synthetic mapping covering the whole run."""

    if not isinstance(clock_mapping, ClockMapping) or clock_mapping.synthetic:
        raise SimNowBlocked("LIVE_CLOCK_MAPPING_REQUIRED")
    monotonic_ns = getattr(feed_clock, "monotonic_ns", None)
    if not callable(monotonic_ns):
        raise SimNowBlocked("LIVE_FEED_CLOCK_REQUIRED")
    try:
        now_ns = monotonic_ns()
    except Exception as exc:
        raise SimNowBlocked("LIVE_FEED_CLOCK_REQUIRED") from exc
    if isinstance(now_ns, bool) or not isinstance(now_ns, int):
        raise SimNowBlocked("LIVE_FEED_CLOCK_REQUIRED")
    required_until_ns = now_ns + int(math.ceil(duration_seconds * 1_000_000_000.0))
    if (
        now_ns < clock_mapping.mono_ns_at_anchor
        or required_until_ns > clock_mapping.valid_until_mono_ns
    ):
        raise SimNowBlocked("LIVE_CLOCK_MAPPING_EXPIRED")
    return clock_mapping


def _guarded_live_evidence_provider(
    provider: Callable[[Any], Any], *, clock_mapping: ClockMapping
) -> tuple[Callable[[Any], BarEvidence], list[BarEvidence]]:
    """Narrow one caller callback to immutable live bar evidence only."""

    emitted: list[BarEvidence] = []

    def guarded(bar: Any) -> BarEvidence:
        try:
            evidence = provider(bar)
        except SimNowBlocked:
            raise
        except Exception as exc:
            raise SimNowBlocked("LIVE_EVIDENCE_PROVIDER_FAILED") from exc
        if not isinstance(evidence, BarEvidence):
            raise SimNowBlocked("LIVE_EVIDENCE_REQUIRED")
        if evidence.clock_mode != "live" or evidence.clock_mapping.synthetic:
            raise SimNowBlocked("LIVE_EVIDENCE_CLOCK_MODE")
        if evidence.clock_mapping != clock_mapping:
            raise SimNowBlocked("LIVE_EVIDENCE_MAPPING_REQUIRED")
        if evidence.clock_domain != clock_mapping.clock_domain_id:
            raise SimNowBlocked("LIVE_EVIDENCE_CLOCK_DOMAIN")
        if evidence.candidate_id != ENGINEERING_OBSERVATION_CANDIDATE_ID:
            raise SimNowBlocked("LIVE_EVIDENCE_CANDIDATE_SCOPE")
        if evidence.rules_hash != clock_mapping.rules_hash:
            raise SimNowBlocked("LIVE_EVIDENCE_RULES_SCOPE")
        emitted.append(evidence)
        return evidence

    return guarded, emitted


def _observation_shutdown_complete(summary: Any, store: Any) -> bool:
    """Accept a clean read-only stop without claiming remote account flatness."""

    if not isinstance(summary, Mapping):
        return False
    try:
        if bool(getattr(store, "is_connected", False)):
            return False
    except BaseException:
        return False
    health_reader = getattr(store, "get_command_health", None)
    if not callable(health_reader):
        return False
    try:
        store_health = health_reader()
    except Exception:
        return False
    if not isinstance(store_health, Mapping) or store_health.get("shutdown_state") != "PASS":
        return False
    zero_counts = (
        "cancel_requested",
        "close_requested",
        "unknown_orders",
        "active_order_count",
        "local_position_count",
        "observed_remote_open_order_count",
    )
    return bool(
        summary.get("status") == "OBSERVATION_ONLY"
        and summary.get("market_data_only") is True
        and summary.get("store_shutdown_state") == "PASS"
        and summary.get("remote_flat_proven") is False
        and summary.get("remote_position_count") is None
        and summary.get("unknown_intent_count") is None
        and summary.get("unmatched_trade_count") is None
        and summary.get("startup_account_state_requires_nonflat") is False
        and all(type(summary.get(name)) is int and summary[name] == 0 for name in zero_counts)
    )


def _observation_unstarted_store_shutdown_complete(store: Any) -> bool:
    """Accept only a proven never-started Store after construction aborts."""

    health_reader = getattr(store, "get_command_health", None)
    health = health_reader() if callable(health_reader) else None
    return bool(
        not bool(getattr(store, "is_connected", False))
        and isinstance(health, Mapping)
        and health.get("shutdown_state") == "NOT_STARTED"
        and int(health.get("queue_depth", 0) or 0) == 0
        and not health.get("inflight")
        and not health.get("worker_alive")
        and not health.get("close_thread_alive")
        and int(health.get("funding_queue_depth", 0) or 0) == 0
        and not health.get("funding_inflight")
        and not health.get("funding_worker_alive")
        and not health.get("read_only_metadata_probe_active")
    )


def _observation_unstarted_graph_shutdown_complete(broker: Any, store: Any) -> bool:
    """Accept only a proven never-started Broker/Store graph."""

    if not _observation_unstarted_store_shutdown_complete(store):
        return False
    if broker is None:
        return True
    summary_reader = getattr(broker, "get_shutdown_summary", None)
    summary = summary_reader() if callable(summary_reader) else None
    return bool(isinstance(summary, Mapping) and summary.get("status") == "NOT_STARTED")


def _stop_observation_graph(*, broker: Any, feeds: list[Any], store: Any) -> bool:
    """Explicitly finish an interrupted Broker/Feed/Store lifecycle.

    ``Cerebro`` only runs its normal teardown after the strategy run loop has
    begun.  A session-binding rejection happens earlier, after the Store,
    Broker, and feeds have started, so each component must be stopped here.
    Continue after every error: an incomplete stop is still useful evidence,
    but it must not mask another unattempted component shutdown.
    """

    clean = True
    if broker is not None:
        try:
            broker.stop()
        except BaseException:
            clean = False
    for feed in feeds:
        try:
            feed.stop()
        except BaseException:
            clean = False
    if store is not None:
        try:
            store.stop(timeout=2.0)
        except BaseException:
            clean = False

    if not clean:
        return False
    if store is None:
        return broker is None

    shutdown_reader = getattr(broker, "get_shutdown_summary", None)
    try:
        summary = shutdown_reader() if callable(shutdown_reader) else None
    except BaseException:
        return False
    return _observation_shutdown_complete(
        summary, store
    ) or _observation_unstarted_graph_shutdown_complete(broker, store)


def _observation_shutdown_projection(summary: Any) -> dict[str, Any]:
    """Keep the public report compact while preserving strict lifecycle facts."""

    if not isinstance(summary, Mapping):
        return {"status": "UNPROVEN"}
    return {
        "status": summary.get("status", "UNPROVEN"),
        "market_data_only": summary.get("market_data_only"),
        "cancel_requested": summary.get("cancel_requested"),
        "close_requested": summary.get("close_requested"),
        "store_shutdown_state": summary.get("store_shutdown_state", "UNPROVEN"),
    }


def _observation_strategy_kwargs(
    config: Mapping[str, Any], *, clock_mapping: ClockMapping, clock_provider: Callable[[], Any]
) -> dict[str, Any]:
    """Bind the existing C/P/F strategy to live, Feed-sealed bar evidence."""

    candidate = config["candidate"]
    params = dict(config["strategy_params"])
    symbols = (candidate["future"], candidate["call"], candidate["put"])
    params.update(
        candidate_id=ENGINEERING_OBSERVATION_CANDIDATE_ID,
        future_symbol=candidate["future"],
        call_symbol=candidate["call"],
        put_symbol=candidate["put"],
        strike=candidate["strike"],
        multiplier=candidate["multiplier"],
        discount=candidate["discount"],
        capital_limit=config["budget"]["capital_limit"],
        ordinary_limit=config["budget"]["ordinary_limit"],
        recovery_reserve=config["budget"]["recovery_reserve"],
        first_send_seconds=config["timing"]["first_send_seconds"],
        completion_seconds=config["timing"]["completion_seconds"],
        minimum_hold_seconds=config["timing"]["minimum_hold_seconds"],
        maximum_hold_seconds=config["timing"]["maximum_hold_seconds"],
        risk_bar_max_age_seconds=config["timing"]["risk_bar_max_age_seconds"],
        session_stop_entry_seconds=config["timing"]["session_stop_entry_seconds"],
        session_exit_seconds=config["timing"]["session_exit_seconds"],
        session_handover_seconds=config["timing"]["session_handover_seconds"],
        rules_hash=clock_mapping.rules_hash,
        price_ticks=dict.fromkeys(symbols, params["price_tick"]),
        # An observation owner may record current reference metadata, but it
        # cannot synthesize an executable price-limit assertion for this
        # strategy.  No price limits means no ordinary order authorization.
        exchange_limits=None,
        exit_reserve=0.0,
        financing_reserve=0.0,
        model_reserve=0.0,
        clock_provider=clock_provider,
        require_feed_bar_evidence=True,
        bar_evidence_clock_domain=clock_mapping.clock_domain_id,
        bar_evidence_clock_mode="live",
    )
    return params


def _engineering_observation_evidence_complete(
    strategy: Any, *, expected_symbols: tuple[str, str, str], clock_mapping: ClockMapping
) -> tuple[bool, str, int]:
    """Verify that the actual strategy received one complete Feed-sealed cohort."""

    if not isinstance(strategy, CtpOptionsLowfreqStrategy):
        return False, "STRATEGY_RUNTIME_MISSING", 0
    if (
        strategy.p.require_feed_bar_evidence is not True
        or strategy.p.bar_evidence_clock_mode != "live"
        or strategy.p.bar_evidence_clock_domain != clock_mapping.clock_domain_id
    ):
        return False, "BAR_ONLY_STRICT_CONFIG_MISSING", 0
    decision = getattr(strategy, "_last_decision_input", None)
    if decision is None:
        return False, "FEED_SEALED_THREE_LEG_INPUT_MISSING", 0
    bars = getattr(decision, "bars", None)
    if not isinstance(bars, Mapping) or set(bars) != set(expected_symbols):
        return False, "FEED_SEALED_THREE_LEG_SCOPE_INCOMPLETE", 0
    for evidence in bars.values():
        if (
            not isinstance(evidence, BarEvidence)
            or evidence.clock_mode != "live"
            or evidence.clock_mapping != clock_mapping
            or evidence.clock_domain != clock_mapping.clock_domain_id
            or evidence.candidate_id != ENGINEERING_OBSERVATION_CANDIDATE_ID
            or evidence.rules_hash != clock_mapping.rules_hash
        ):
            return False, "FEED_SEALED_LIVE_EVIDENCE_MISMATCH", 0
    ready_count = sum(
        1 for result in getattr(strategy, "_barrier_results", ()) if result.get("ready") is True
    )
    return True, "PASS", ready_count


def run_engineering_observation(
    *,
    config: Mapping[str, Any],
    environment_profile: str,
    run_seconds: Any,
    feed_clock: Any,
    clock_mapping: Any,
    closed_bar_evidence_provider: Callable[[Any], Any],
    api: Any = None,
    store: BtApiStore | None = None,
    store_ownership: str | None = None,
) -> dict[str, Any]:
    """Run one explicit, bounded Set-2 zero-write low-frequency observation.

    The caller supplies exactly one lifecycle root: either an API (which this
    adapter narrows through its read-only membrane) or one Store with an
    explicit ownership transfer.  The latter path never reads ``store.sdk_api``
    or creates another Store.  Neither path reads an environment file,
    instantiates an SDK, calls a preflight that could be misreported as G3, or
    exposes a CLI connection path.  A 60-minute run starts from no history and
    cannot establish the strategy's 40-bar signal logic; it proves only
    lifecycle and BAR_ONLY feed hand-off facts.
    """

    api_supplied = api is not None
    store_supplied = store is not None
    if api_supplied and store_supplied:
        raise SimNowBlocked("ENGINEERING_STORE_API_EXCLUSIVE")
    if not api_supplied and not store_supplied:
        # Preserve the original API-only entrypoint's fail-closed result for
        # callers that have not adopted the Store transfer contract.
        raise SimNowBlocked("SDK_NOT_INJECTED")
    injected_store: BtApiStore | None = None
    if store_supplied:
        if store_ownership != "transfer":
            raise SimNowBlocked("ENGINEERING_STORE_OWNERSHIP_TRANSFER_REQUIRED")
    elif store_ownership is not None:
        raise SimNowBlocked("ENGINEERING_STORE_OWNERSHIP_UNEXPECTED")
    if environment_profile != SECOND_SET_ENGINEERING_PROFILE:
        raise SimNowBlocked("ENGINEERING_PROFILE_REQUIRED")
    if not isinstance(config, Mapping):
        raise SimNowBlocked("ENGINEERING_CONFIG")
    candidate = config.get("candidate")
    strategy_params = config.get("strategy_params")
    budget = config.get("budget")
    timing = config.get("timing")
    if not all(
        isinstance(value, Mapping) for value in (candidate, strategy_params, budget, timing)
    ):
        raise SimNowBlocked("ENGINEERING_CONFIG")
    if not callable(closed_bar_evidence_provider):
        raise SimNowBlocked("LIVE_EVIDENCE_REQUIRED")

    duration_seconds = _engineering_duration_seconds(run_seconds)
    # The engineering budget covers the entire runtime graph, including Store,
    # Broker, and Feed startup.  A later post-bind watchdog must not grant a
    # fresh full observation window after a slow pre-bind lifecycle.
    started_at = time.monotonic()
    lifecycle_deadline = started_at + ENGINEERING_OBSERVATION_MAX_SECONDS
    trusted_mapping = _require_live_clock_mapping(
        clock_mapping=clock_mapping,
        feed_clock=feed_clock,
        duration_seconds=duration_seconds,
    )
    symbols = (candidate.get("future"), candidate.get("call"), candidate.get("put"))
    if (
        any(not isinstance(symbol, str) or not symbol.strip() for symbol in symbols)
        or len(set(symbols)) != 3
    ):
        raise SimNowBlocked("ENGINEERING_CONFIG")
    typed_symbols = tuple(symbols)
    guarded_provider, emitted_evidence = _guarded_live_evidence_provider(
        closed_bar_evidence_provider,
        clock_mapping=trusted_mapping,
    )
    guarded_api = _ObservationReadOnlyApi(api) if api_supplied else None
    metadata = {
        symbol: {
            "tick_size": strategy_params["price_tick"],
            "contract_multiplier": candidate["multiplier"],
            "min_size": 1,
            "lot_size": 1,
            "quantity_step": 1,
            "currency": "CNY",
        }
        for symbol in typed_symbols
    }
    deadline_stop_requested = threading.Event()
    lifecycle_deadline_stop_requested = threading.Event()
    session_binding: list[dict[str, Any]] = []
    deadline_timers: list[threading.Timer] = []
    lifecycle_deadline_timers: list[threading.Timer] = []
    lifecycle_lock = threading.Lock()
    cerebro: Any = None
    store_write_baseline: int | None = None

    def request_deadline_stop() -> None:
        deadline_stop_requested.set()
        active_cerebro = cerebro
        if active_cerebro is not None:
            active_cerebro.runstop()

    def request_lifecycle_deadline_stop() -> None:
        lifecycle_deadline_stop_requested.set()
        active_cerebro = cerebro
        if active_cerebro is not None:
            active_cerebro.runstop()

    def require_lifecycle_budget() -> None:
        if time.monotonic() >= lifecycle_deadline:
            request_lifecycle_deadline_stop()
        if lifecycle_deadline_stop_requested.is_set():
            raise SimNowBlocked("OBSERVATION_LIFECYCLE_DURATION_EXCEEDED")

    # Start this before *any* native graph construction, including Cerebro.
    # A blocking constructor cannot receive a fresh runtime window once it
    # returns; it must fail at the next construction checkpoint instead.
    remaining_lifecycle_seconds = lifecycle_deadline - time.monotonic()
    if remaining_lifecycle_seconds <= 0.0:
        request_lifecycle_deadline_stop()
        raise SimNowBlocked("OBSERVATION_LIFECYCLE_DURATION_EXCEEDED")
    lifecycle_timer = threading.Timer(
        remaining_lifecycle_seconds,
        request_lifecycle_deadline_stop,
    )
    lifecycle_timer.name = "iter23-engineering-observation-lifecycle-deadline"
    lifecycle_timer.daemon = True
    lifecycle_deadline_timers.append(lifecycle_timer)
    lifecycle_timer.start()

    observation_store: Any = None
    broker: Any = None
    feeds: list[Any] = []
    try:
        require_lifecycle_budget()
        if store_supplied:
            # Transfer only after all pure caller/configuration validation has
            # completed and while the graph teardown guard is active.  A
            # later construction error then closes the transferred Store;
            # earlier validation failures leave it with its original owner.
            injected_store, store_write_baseline = _require_transferable_observation_store(store)
            observation_store = injected_store
        require_lifecycle_budget()
        cerebro = bt.Cerebro(stdstats=False, quicknotify=True, runonce=False)
        require_lifecycle_budget()
        if injected_store is None:
            observation_store = BtApiStore(
                provider="btapi",
                api=guarded_api,
                config={"market_data_only": True, "execution_config": {"market_data_only": True}},
                cash=float(budget["capital_limit"]),
                value=float(budget["capital_limit"]),
                contract_metadata=metadata,
                autostart=False,
            )
            health = observation_store.get_command_health()
            if not isinstance(health, Mapping):
                raise SimNowBlocked("INJECTED_STORE_HEALTH_UNAVAILABLE")
            store_write_baseline = _read_market_data_only_rejection_count(health)
            if store_write_baseline != 0:
                raise SimNowBlocked("ENGINEERING_STORE_WRITE_BASELINE_REQUIRED")
        require_lifecycle_budget()
        broker = BtApiBroker(
            store=observation_store,
            provider="btapi",
            cash=float(budget["capital_limit"]),
            value=float(budget["capital_limit"]),
            contract_metadata=metadata,
            market_data_only=True,
            flatten_on_stop=False,
            force_refresh_queries=False,
            sdk_preflight=False,
        )
        require_lifecycle_budget()
        cerebro.setbroker(broker)
        require_lifecycle_budget()
        for symbol in typed_symbols:
            feed = observation_store.getdata(
                dataname=symbol,
                timeframe=bt.TimeFrame.Minutes,
                compression=15,
                backfill_start=False,
                dispatch_ticks=False,
                dispatch_orderbooks=False,
                dispatch_bars=True,
                qcheck=0.01,
                price_tick=float(strategy_params["price_tick"]),
                clock=feed_clock,
                closed_bar_evidence_provider=guarded_provider,
            )
            feeds.append(feed)
            cerebro.adddata(feed, name=symbol)
            require_lifecycle_budget()
        strategy_clock = _ObservationClockProvider(
            feed_clock=feed_clock,
            clock_mapping=trusted_mapping,
        )
        cerebro.addstrategy(
            CtpOptionsLowfreqStrategy,
            **_observation_strategy_kwargs(
                config,
                clock_mapping=trusted_mapping,
                clock_provider=strategy_clock,
            ),
        )
        require_lifecycle_budget()
    except BaseException as exc:
        lifecycle_timer.cancel()
        lifecycle_timer.join(timeout=1.0)
        graph_shutdown_complete = observation_store is None or _stop_observation_graph(
            broker=broker,
            feeds=feeds,
            store=observation_store,
        )
        if lifecycle_timer.is_alive() or not graph_shutdown_complete:
            raise SimNowBlocked("ENGINEERING_OBSERVATION_SHUTDOWN_INCOMPLETE") from exc
        if isinstance(exc, SimNowBlocked):
            raise exc
        raise SimNowBlocked("ENGINEERING_OBSERVATION_RUNTIME") from exc

    def bind_session_then_start_deadline() -> None:
        """Run only after Cerebro has started the Store and real strategy."""

        binding = _require_second_set_session_binding(
            observation_store,
            clock_mapping=trusted_mapping,
        )
        with lifecycle_lock:
            if session_binding:
                return
            session_binding.append(binding)
            remaining_lifecycle_seconds = lifecycle_deadline - time.monotonic()
            if lifecycle_deadline_stop_requested.is_set() or remaining_lifecycle_seconds <= 0.0:
                request_lifecycle_deadline_stop()
                return
            timer = threading.Timer(
                min(duration_seconds, remaining_lifecycle_seconds),
                request_deadline_stop,
            )
            timer.name = "iter23-engineering-observation-watchdog"
            timer.daemon = True
            deadline_timers.append(timer)
            timer.start()

    try:
        require_lifecycle_budget()
        cerebro.addanalyzer(
            _ObservationSessionBindingProbe,
            on_session_bound=bind_session_then_start_deadline,
        )
        require_lifecycle_budget()
    except BaseException as exc:
        lifecycle_timer.cancel()
        lifecycle_timer.join(timeout=1.0)
        graph_shutdown_complete = _stop_observation_graph(
            broker=broker,
            feeds=feeds,
            store=observation_store,
        )
        if lifecycle_timer.is_alive() or not graph_shutdown_complete:
            raise SimNowBlocked("ENGINEERING_OBSERVATION_SHUTDOWN_INCOMPLETE") from exc
        if isinstance(exc, SimNowBlocked):
            raise exc
        raise SimNowBlocked("ENGINEERING_OBSERVATION_RUNTIME") from exc

    strategies: list[Any] = []
    run_error: BaseException | None = None
    shutdown_incomplete = False
    try:
        require_lifecycle_budget()
        strategies = cerebro.run(preload=False, runonce=False)
    except BaseException as exc:
        run_error = exc
    finally:
        with lifecycle_lock:
            deadline_timer = deadline_timers[0] if deadline_timers else None
            lifecycle_timer = lifecycle_deadline_timers[0] if lifecycle_deadline_timers else None
        for timer in (deadline_timer, lifecycle_timer):
            if timer is None:
                continue
            timer.cancel()
            timer.join(timeout=1.0)
            if timer.is_alive():
                shutdown_incomplete = True
        if run_error is not None:
            shutdown_reader = getattr(broker, "get_shutdown_summary", None)
            try:
                shutdown_before = shutdown_reader() if callable(shutdown_reader) else None
            except BaseException:
                shutdown_before = None
            # Cerebro normally stops its graph before re-raising a runtime
            # failure, but a disconnected Store alone is not shutdown proof.
            # Preserve the original runtime/binding reason only when the
            # public Broker/Store summary already proves the zero-write stop;
            # otherwise make one explicit full-graph attempt and fail closed.
            if not _observation_shutdown_complete(shutdown_before, observation_store):
                if not _stop_observation_graph(
                    broker=broker,
                    feeds=feeds,
                    store=observation_store,
                ):
                    shutdown_incomplete = True
    elapsed_seconds = max(time.monotonic() - started_at, 0.0)
    elapsed_within_maximum = elapsed_seconds <= ENGINEERING_OBSERVATION_MAX_SECONDS
    lifecycle_duration_complete = (
        elapsed_within_maximum and not lifecycle_deadline_stop_requested.is_set()
    )
    if shutdown_incomplete:
        raise SimNowBlocked("ENGINEERING_OBSERVATION_SHUTDOWN_INCOMPLETE")
    if run_error is not None:
        if isinstance(run_error, SimNowBlocked):
            raise run_error
        raise SimNowBlocked("ENGINEERING_OBSERVATION_RUNTIME") from run_error
    if len(session_binding) != 1:
        raise SimNowBlocked("CTP_SESSION_BINDING_MISSING")

    shutdown_reader = getattr(broker, "get_shutdown_summary", None)
    shutdown = shutdown_reader() if callable(shutdown_reader) else {"status": "UNPROVEN"}
    strategy = strategies[0] if len(strategies) == 1 else None
    evidence_complete, evidence_status, observed_cohorts = (
        _engineering_observation_evidence_complete(
            strategy,
            expected_symbols=typed_symbols,
            clock_mapping=trusted_mapping,
        )
    )
    required_bars = int(strategy_params["window"])
    strategy_logic_status = (
        "NOT_EVALUATED_INSUFFICIENT_CLOSED_BARS"
        if observed_cohorts < required_bars
        else "OBSERVED_ZERO_WRITE_NO_SIGNAL_OR_EXECUTION_CLAIM"
    )
    if store_write_baseline is None:
        raise SimNowBlocked("INJECTED_STORE_HEALTH_UNAVAILABLE")
    membrane_guard = (
        guarded_api.audit() if guarded_api is not None else {"forbidden_write_attempts": {}}
    )
    store_guard = _store_write_guard(
        observation_store,
        baseline=store_write_baseline,
        ownership=("INJECTED_STORE" if injected_store is not None else "ADAPTER_OWNED_STORE"),
    )
    broker_guard = _broker_write_guard(broker)
    # The Store-scoped delta already includes every Broker bound to this
    # Store, including this graph's Broker.  Keep the Broker result as an
    # attribution breakdown without counting one rejected callback twice.
    forbidden_write_attempts = _combine_write_guards(
        membrane_guard,
        store_guard,
    )
    write_guard = {
        **dict(membrane_guard),
        "forbidden_write_attempts": forbidden_write_attempts,
        "store_market_data_only": store_guard,
        "broker_market_data_only": broker_guard,
    }
    adapter_scoped_write_attempts = sum(forbidden_write_attempts.values())
    write_complete = bool(
        not forbidden_write_attempts
        and session_binding
        and session_binding[0].get("read_only_ready") is True
        and session_binding[0].get("execution_armed") is False
        and isinstance(shutdown, Mapping)
        and shutdown.get("market_data_only") is True
    )
    write_evidence_boundary = (
        _INJECTED_STORE_WRITE_EVIDENCE_BOUNDARY
        if injected_store is not None
        else _ADAPTER_SCOPED_WRITE_EVIDENCE_BOUNDARY
    )
    shutdown_complete = _observation_shutdown_complete(shutdown, observation_store)
    duration_complete = deadline_stop_requested.is_set()
    complete = (
        duration_complete
        and lifecycle_duration_complete
        and evidence_complete
        and shutdown_complete
        and write_complete
    )
    failure_codes = []
    if not duration_complete:
        failure_codes.append("OBSERVATION_DURATION_INCOMPLETE")
    if not lifecycle_duration_complete:
        failure_codes.append("OBSERVATION_TOTAL_LIFECYCLE_DURATION_EXCEEDED")
    if not evidence_complete:
        failure_codes.append(evidence_status)
    if not shutdown_complete:
        failure_codes.append("OBSERVATION_SHUTDOWN_INCOMPLETE")
    if not write_complete:
        failure_codes.append("FORBIDDEN_WRITE_ATTEMPT")
    strategy_report = strategy.report() if strategy is not None else None

    return {
        "status": (
            "PASS_ENGINEERING_STRATEGY_OBSERVATION"
            if complete
            else "INCOMPLETE_ENGINEERING_STRATEGY_OBSERVATION"
        ),
        "mode": "shadow",
        "purpose": "observation",
        "candidate_id": ENGINEERING_OBSERVATION_CANDIDATE_ID,
        "store_ownership": (
            "INJECTED_STORE_LIFECYCLE_TRANSFERRED"
            if injected_store is not None
            else "ADAPTER_OWNED_STORE_FROM_API"
        ),
        "chain": {
            "store": "BtApiStore",
            "feeds": ["BtApiFeed"] * len(feeds),
            "broker": "BtApiBroker",
            "cerebro": "Cerebro",
            "strategy": "CtpOptionsLowfreqStrategy",
        },
        "duration": {
            "requested_seconds": duration_seconds,
            "elapsed_seconds": elapsed_seconds,
            "deadline_stop_requested": duration_complete,
            "lifecycle_deadline_stop_requested": lifecycle_deadline_stop_requested.is_set(),
            "maximum_seconds": ENGINEERING_OBSERVATION_MAX_SECONDS,
            "total_lifecycle_within_maximum": lifecycle_duration_complete,
        },
        "feed_evidence": {
            "provider_emitted_count": len(emitted_evidence),
            "accepted_complete_three_leg_input": evidence_complete,
            "status": evidence_status,
            "clock_mode": "live",
            "clock_domain": trusted_mapping.clock_domain_id,
            "clock_mapping_id": trusted_mapping.mapping_id,
            "clock_mapping_generation": trusted_mapping.connection_generation,
            "bar_only_strict": True,
        },
        "session_binding": session_binding[0],
        "strategy_logic": {
            "status": strategy_logic_status,
            "required_closed_bars": required_bars,
            "observed_complete_three_leg_bars": observed_cohorts,
            "signal_or_order_claim": "NOT_APPLICABLE_LIFECYCLE_ONLY",
        },
        "account_scope": "NOT_RUN_NOT_G3_ACCOUNT_RECONCILIATION",
        "write_guard": write_guard,
        "adapter_scoped_write_attempts": adapter_scoped_write_attempts,
        "external_trade_writes": "NOT_PROVEN",
        "external_trade_writes_basis": write_evidence_boundary,
        "shutdown": _observation_shutdown_projection(shutdown),
        "strategy": strategy_report,
        "strategy_report_boundary": (
            "The strategy report is a local projection; its replay-labelled account and transport "
            "fields, including any local write count, are not external provider-write, SimNow, "
            "fill, PnL, or G3/G4 evidence."
        ),
        "failure_codes": failure_codes,
        "gates": {
            "G3_first_set_read_only": ENGINEERING_OBSERVATION_G3_STATUS,
            "G3_evaluation": "NOT_APPLICABLE_ENGINEERING_ONLY",
            "G4_simnow_mechanical": "NOT_RUN",
            "lowfreq_signal_logic": strategy_logic_status,
        },
    }


@dataclass(frozen=True)
class SimNowIdentity:
    """Immutable public account/session identity triple."""

    account_fingerprint: str
    trading_day: str
    generation: int


@dataclass(frozen=True)
class ReconciliationResult:
    """Immutable outcome of the two-round read-only account reconciliation."""

    status: str
    identity: SimNowIdentity
    rounds: int
    snapshot_hashes: tuple[str, ...]
    positions: tuple[dict[str, Any], ...]
    active_orders: tuple[dict[str, Any], ...]
    unknown_intents: tuple[dict[str, Any], ...]

    @property
    def flat_verified(self) -> bool:
        """True only when a stable snapshot proves a fully flat account."""

        return (
            self.status == "FLAT_VERIFIED"
            and not self.positions
            and not self.active_orders
            and not self.unknown_intents
        )


class SimNowOptionsAdapter:
    """One account/session adapter and one BT Store/Feed/Broker/Cerebro chain.

    ``api`` is intentionally mandatory.  This class never instantiates an API
    class, reads environment files, or calls a native write in smoke mode.
    """

    _terminal_order_states = frozenset(
        {"completed", "canceled", "cancelled", "rejected", "expired"}
    )

    def __init__(self, config: Mapping[str, Any], api: Any = None):
        """Fail closed unless a caller-injected API object is provided."""

        if api is None:
            raise SimNowBlocked("SIMNOW_API_INJECTION_REQUIRED")
        self.config = config
        self.api = api
        # Pure mocks may opt into the small query protocol below.  A native
        # API never gets this escape hatch: it must go through BtApiStore's
        # public CTP snapshot methods.
        self._mock_query_mode = bool(getattr(api, "iter23_pure_mock", False))
        self.store: BtApiStore | None = None
        self.feed: Any = None
        self.feeds: list[Any] = []
        self.broker: BtApiBroker | None = None
        self.cerebro: bt.Cerebro | None = None
        self.identity: SimNowIdentity | None = None
        self._request_count_deltas: list[dict[str, Any]] = []

    def _ensure_store(self) -> BtApiStore:
        if self.store is None:
            candidate = self.config["candidate"]
            symbols = (candidate["future"], candidate["call"], candidate["put"])
            metadata = {
                symbol: {
                    "tick_size": 1.0,
                    "contract_multiplier": candidate["multiplier"],
                    "min_size": 1,
                    "lot_size": 1,
                    "quantity_step": 1,
                    "currency": "CNY",
                }
                for symbol in symbols
            }
            self.store = BtApiStore(
                provider="btapi",
                api=self.api,
                cash=float(self.config["budget"]["capital_limit"]),
                value=float(self.config["budget"]["capital_limit"]),
                contract_metadata=metadata,
                market_data_only=True,
            )
        return self.store

    @staticmethod
    def _strict_store_schema(snapshot: Mapping[str, Any], *, label: str) -> None:
        required = {
            "evidence_complete",
            "read_only_safe",
            "write_request_free",
            "account_fingerprint",
            "trading_day",
            "connection_generation",
            "flat",
            "active_order_count",
            "unknown_intent_count",
            "unmatched_trade_count",
        }
        missing = sorted(required.difference(snapshot))
        if missing:
            raise SimNowBlocked(f"{label}_SCHEMA_INCOMPLETE:{','.join(missing)}")
        if any(
            snapshot[field] != 0
            for field in ("active_order_count", "unknown_intent_count", "unmatched_trade_count")
        ):
            raise SimNowBlocked(f"{label}_NONFLAT_OR_UNKNOWN")
        if any(
            snapshot[field] is not True
            for field in ("evidence_complete", "read_only_safe", "write_request_free", "flat")
        ):
            raise SimNowBlocked(f"{label}_NOT_READ_ONLY_COMPLETE_OR_FLAT")
        if (
            not isinstance(snapshot["account_fingerprint"], str)
            or not snapshot["account_fingerprint"].strip()
        ):
            raise SimNowBlocked(f"{label}_IDENTITY_INCOMPLETE")
        if not isinstance(snapshot["trading_day"], str) or not snapshot["trading_day"].strip():
            raise SimNowBlocked(f"{label}_IDENTITY_INCOMPLETE")
        if (
            type(snapshot["connection_generation"]) is not int
            or snapshot["connection_generation"] <= 0
        ):
            raise SimNowBlocked(f"{label}_IDENTITY_INCOMPLETE")

    @staticmethod
    def _semantic_payload(snapshot: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "account_fingerprint": snapshot["account_fingerprint"],
            "trading_day": snapshot["trading_day"],
            "connection_generation": snapshot["connection_generation"],
            "flat": snapshot["flat"],
            "active_order_count": snapshot["active_order_count"],
            "unknown_intent_count": snapshot["unknown_intent_count"],
            "unmatched_trade_count": snapshot["unmatched_trade_count"],
            "positions": snapshot.get("nonzero_positions", snapshot.get("positions", [])),
            "active_orders": snapshot.get("active_orders", []),
        }

    def _record_request_counts(self, snapshot: Mapping[str, Any]) -> None:
        delta = snapshot.get("request_count_delta")
        if isinstance(delta, Mapping):
            self._request_count_deltas.append(dict(delta))

    def external_request_counts(self) -> dict[str, Any]:
        """Aggregate observed request deltas without assuming absent ones are zero.

        Pure mocks report zero; a native path with no recorded deltas reports
        ``NOT_OBSERVED`` instead of an unproven zero count.
        """
        if self._mock_query_mode:
            return {"network": 0, "order_write": 0}
        if not self._request_count_deltas:
            return {"network": "NOT_OBSERVED", "order_write": "NOT_OBSERVED"}
        order_write = 0
        network = 0
        network_seen = False
        for delta in self._request_count_deltas:
            order_write += sum(
                int(delta.get(key, 0) or 0) for key in ("order_insert", "order_action")
            )
            if "network" in delta:
                network += int(delta["network"] or 0)
                network_seen = True
        return {"network": network if network_seen else "NOT_OBSERVED", "order_write": order_write}

    def _query(self, *names: str) -> Any:
        for name in names:
            method = getattr(self.api, name, None)
            if callable(method):
                return method()
        raise SimNowBlocked(f"native query capability unavailable: {names[0]}")

    def _snapshot(self) -> tuple[SimNowIdentity, dict[str, Any]]:
        if not self._mock_query_mode:
            store = self._ensure_store()
            candidate = self.config["candidate"]
            legs = [
                ("CZCE", candidate[name].split(".", 1)[-1]) for name in ("future", "call", "put")
            ]
            snapshot = _mapping(
                store.get_ctp_bundle_preflight_snapshot(
                    legs,
                    primary_leg=legs[0],
                    read_only=True,
                )
            )
            self._strict_store_schema(snapshot, label="CTP_BUNDLE_PREFLIGHT")
            self._record_request_counts(snapshot)
            identity = SimNowIdentity(
                snapshot["account_fingerprint"],
                snapshot["trading_day"],
                snapshot["connection_generation"],
            )
            positions = list(snapshot.get("nonzero_positions") or snapshot.get("positions") or [])
            active_orders = list(snapshot.get("active_orders") or [])
            unknown_count = int(snapshot.get("unknown_intent_count") or 0)
            unknown = [{"count": unknown_count}] if unknown_count else []
            payload = self._semantic_payload(snapshot)
            payload.update(
                {
                    "identity": identity.__dict__,
                    "positions": positions,
                    "active_orders": active_orders,
                    "unknown_intents": unknown,
                }
            )
            return identity, payload
        account_rows = _records(self._query("query_account", "query_account_result"), "account")
        if len(account_rows) != 1:
            raise SimNowBlocked("account-wide query must contain exactly one record")
        account = account_rows[0]
        identity = SimNowIdentity(
            str(_identity(account, "account")),
            str(_identity(account, "trading_day")),
            int(_identity(account, "generation")),
        )
        positions = _records(self._query("query_positions", "query_positions_result"), "positions")
        orders = _records(self._query("query_orders", "query_orders_result"), "orders")
        unknown = _records(
            self._query("query_unknown_intents", "query_unknown_intents_result"),
            "unknown_intents",
        )
        for name, rows in (
            ("positions", positions),
            ("orders", orders),
            ("unknown_intents", unknown),
        ):
            for row in rows:
                row_account = row.get(
                    "account_fingerprint", row.get("account_id", identity.account_fingerprint)
                )
                row_generation = int(
                    row.get("generation", row.get("connection_generation", identity.generation))
                )
                if (
                    str(row_account) != identity.account_fingerprint
                    or row_generation != identity.generation
                ):
                    raise SimNowBlocked(f"{name} identity differs from account query")
        active_orders = [
            row
            for row in orders
            if str(row.get("status", "")).lower() not in self._terminal_order_states
        ]
        payload = {
            "identity": identity.__dict__,
            "account_fingerprint": identity.account_fingerprint,
            "trading_day": identity.trading_day,
            "connection_generation": identity.generation,
            "positions": positions,
            "active_orders": active_orders,
            "unknown_intents": unknown,
            "evidence_complete": True,
            "read_only_safe": True,
            "write_request_free": True,
            "flat": not positions and not active_orders and not unknown,
            "active_order_count": len(active_orders),
            "unknown_intent_count": len(unknown),
            "unmatched_trade_count": 0,
        }
        return identity, payload

    def startup_preflight(self) -> dict[str, Any]:
        """Query account-wide state before constructing/starting Cerebro."""

        identity, payload = self._snapshot()
        if (
            not payload.get("flat", False)
            or payload.get("active_order_count") != 0
            or payload.get("unknown_intent_count") != 0
            or payload.get("unmatched_trade_count") != 0
        ):
            raise SimNowBlocked("STARTUP_ACCOUNT_NOT_FLAT_OR_UNKNOWN")
        self.identity = identity
        return {
            "status": "PASS",
            "scope": "account_wide",
            "identity": identity.__dict__,
            "positions": [],
            "active_orders": [],
            "unknown_intents": [],
        }

    def reconcile(self, *, rounds: int = 2) -> ReconciliationResult:
        """Run exactly two stable read-only snapshots and judge flatness.

        Fail closed with ``SimNowBlocked`` when identity changes between
        rounds or the canonical snapshot hashes differ; any remaining
        position, active order, or unknown intent yields
        ``EXPOSURE_REMAINS`` rather than a flat claim.
        """
        if rounds != 2:
            raise ValueError("Iter23 requires exactly two reconciliation rounds")
        if not self._mock_query_mode and self.store is not None:
            snapshots = []
            for _ in range(rounds):
                raw = _mapping(self.store.get_ctp_reconciliation_snapshot())
                self._strict_store_schema(raw, label="CTP_RECONCILIATION")
                self._record_request_counts(raw)
                identity = SimNowIdentity(
                    raw["account_fingerprint"], raw["trading_day"], raw["connection_generation"]
                )
                payload = self._semantic_payload(raw)
                payload.update(
                    {
                        "identity": identity.__dict__,
                        "positions": list(
                            raw.get("nonzero_positions") or raw.get("positions") or []
                        ),
                        "active_orders": list(raw.get("active_orders") or []),
                        "unknown_intents": (
                            [{"count": raw["unknown_intent_count"]}]
                            if raw["unknown_intent_count"]
                            else []
                        ),
                    }
                )
                snapshots.append((identity, payload))
        else:
            snapshots = [self._snapshot() for _ in range(rounds)]
        identities = {item[0] for item in snapshots}
        if len(identities) != 1:
            raise SimNowBlocked("RECONCILIATION_GENERATION_CHANGED")
        hashes = tuple(_canonical(self._semantic_payload(item[1])) for item in snapshots)
        if hashes[0] != hashes[1]:
            raise SimNowBlocked("RECONCILIATION_NOT_STABLE")
        final = snapshots[-1][1]
        status = (
            "FLAT_VERIFIED"
            if final.get("flat") is True
            and final.get("active_order_count") == 0
            and final.get("unknown_intent_count") == 0
            and final.get("unmatched_trade_count") == 0
            else "EXPOSURE_REMAINS"
        )
        return ReconciliationResult(
            status,
            snapshots[-1][0],
            rounds,
            hashes,
            tuple(final["positions"]),
            tuple(final["active_orders"]),
            tuple(final["unknown_intents"]),
        )

    def build_chain(self) -> tuple[bt.Cerebro, BtApiStore, Any, BtApiBroker]:
        """Construct the single market-data-only Store/Feed/Broker/Cerebro chain.

        Requires a completed startup preflight and returns the runtime chain
        without starting any data consumption or strategy run.
        """
        if self.identity is None:
            raise SimNowBlocked("STARTUP_PREFLIGHT_REQUIRED")
        candidate = self.config["candidate"]
        symbols = (candidate["future"], candidate["call"], candidate["put"])
        metadata = {
            symbol: {
                "tick_size": candidate.get("price_tick", 1.0),
                "contract_multiplier": candidate["multiplier"],
                "min_size": 1,
                "lot_size": 1,
                "quantity_step": 1,
                "currency": "CNY",
            }
            for symbol in symbols
        }
        self.store = self._ensure_store()
        self.broker = BtApiBroker(
            store=self.store,
            provider="btapi",
            cash=float(self.config["budget"]["capital_limit"]),
            value=float(self.config["budget"]["capital_limit"]),
            contract_metadata=metadata,
            sdk_preflight=False,
            market_data_only=True,
            flatten_on_stop=False,
            force_refresh_queries=False,
        )
        self.cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
        self.cerebro.setbroker(self.broker)
        for symbol in symbols:
            self.feed = self.store.getdata(
                dataname=symbol,
                historical_bars=[],
                live_bars=[],
                backfill_start=False,
                dispatch_ticks=False,
                dispatch_bars=False,
                qcheck=0.0,
            )
            self.feeds.append(self.feed)
            self.cerebro.adddata(self.feed, name=symbol)
        self.cerebro.addstrategy(
            CtpOptionsLowfreqStrategy,
            future_symbol=candidate["future"],
            call_symbol=candidate["call"],
            put_symbol=candidate["put"],
            strike=candidate["strike"],
            multiplier=candidate["multiplier"],
            discount=candidate["discount"],
            capital_limit=self.config["budget"]["capital_limit"],
            ordinary_limit=self.config["budget"]["ordinary_limit"],
            recovery_reserve=self.config["budget"]["recovery_reserve"],
            clock_provider=None,
        )
        return self.cerebro, self.store, self.feed, self.broker

    def run_engineering_smoke(self) -> dict[str, Any]:
        """Execute the bounded engineering smoke path end to end.

        Runs startup preflight, builds but never runs the chain, and
        reconciles twice; the report claims no native execution, fill, or
        authorization evidence.
        """
        preflight = self.startup_preflight()
        cerebro, store, feed, broker = self.build_chain()
        # No bars are consumed here: a live feed with no injected finite source
        # must not be allowed to turn an engineering smoke into an unbounded
        # wait.  Construction still exercises the single runtime ownership
        # chain; a real run belongs to the SDK-owned launcher.
        reconciliation = self.reconcile()
        return {
            "status": (
                "ENGINEERING_SMOKE_PASS" if reconciliation.status == "FLAT_VERIFIED" else "BLOCKED"
            ),
            "mode": "simnow",
            "purpose": "engineering_smoke",
            "preflight": preflight,
            "reconciliation": {
                "status": reconciliation.status,
                "rounds": reconciliation.rounds,
                "snapshot_hashes": reconciliation.snapshot_hashes,
                "identity": reconciliation.identity.__dict__,
            },
            "native_execution_status": "NOT_CLAIMED_NO_NATIVE_CONFIRMATION",
            "fill_claim_status": "NO_NATIVE_CONFIRMATION",
            "execution_authorization_status": "BLOCKED_TRUST_ROOT_MISSING",
            "market_data_only": True,
            "order_write_allowed": False,
            "flat_status": reconciliation.status,
            "external_request_counts": self.external_request_counts(),
            "runtime_chain": {
                "store": type(store).__name__,
                "store_provider": store.provider,
                "feeds": [type(item).__name__ for item in self.feeds],
                "broker": type(broker).__name__,
                "broker_provider": broker.provider,
                "cerebro": type(cerebro).__name__,
                "strategy": CtpOptionsLowfreqStrategy.__name__,
            },
        }
