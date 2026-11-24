"""Bind one BT feed to one explicitly configured SDK Gateway subscription."""
from __future__ import annotations

import logging
import math
import threading
import time
from types import MappingProxyType

from bt_api_base.service_protocol import WireScope
from bt_api_py.gateway_market_projection import (
    GatewayMarketProjectionError,
    GatewayMarketTickProjector,
)
from bt_api_py.service_runtime_thread import OwnerOperationError, ThreadedRuntimeError



# Owner-side conditions that clear by themselves: a call still queued/running,
# or another call holding the subscription client's single pending slot (it is
# retired once finished). Never terminal for this adapter.
_TRANSIENT_OWNER_CODES = ("OWNER_TIMEOUT_QUEUED", "OWNER_TIMEOUT_RUNNING", "OWNER_OPERATION_PENDING")
_OWNER_CALL_NOT_SUBMITTED_CODES = frozenset({
    "INVALID_OWNER_ARGUMENTS",
    "NOT_READY",
    "OWNER_THREAD_REENTRY",
    "OWNER_UNAVAILABLE",
    "QUEUE_FULL",
    "WRONG_PROCESS",
})
_GATEWAY_ACQUIRE_PREFLIGHT_CODES = frozenset({
    "GATEWAY_BINDING_CHANGED",
    "GATEWAY_FACADE_CLOSED",
    "GATEWAY_FACADE_CLOSING",
    "GATEWAY_ROUTE_MISMATCH",
    "MARKET_SUBSCRIPTION_UNAVAILABLE",
    "WRONG_PROCESS",
})


def _session_generation(store):
    """Read the local Store session generation, or return no release proof."""
    try:
        generation = store.gateway_session_generation
    except Exception:
        return None
    return generation if type(generation) is int and generation >= 0 else None


def _new_session_proves_cursor_isolation(store, tombstone, api):
    """A successful Store reconnect gives a new local client and cursor owner.

    This proves local session separation only. It does not assert that the
    Gateway or provider stopped an upstream subscription.
    """
    if type(tombstone) is not tuple or len(tombstone) not in (3, 5) or tombstone[2] is not True:
        return False
    old_api_id, old_generation, terminal = tombstone[:3]
    try:
        current_api = store.gateway_api
        generation = store.gateway_session_generation
        connected = store.is_connected is True
        final_api = store.gateway_api
        final_generation = store.gateway_session_generation
    except Exception:
        return False
    return (
        terminal is True
        and type(old_api_id) is int
        and type(old_generation) is int
        and old_generation >= 0
        and type(generation) is int
        and generation is not None
        and generation > old_generation
        and api is not None
        and current_api is api
        and id(api) != old_api_id
        and connected
        and final_api is api
        and type(final_generation) is int
        and final_generation == generation
    )


def _same_session_lease_release_proves_cursor_isolation(store, tombstone, api):
    """A confirmed SDK registration release permits a fresh local cursor."""
    if (type(tombstone) is not tuple or len(tombstone) != 5
            or tombstone[2] is not True or tombstone[3] is not True
            or tombstone[4] is not api):
        return False
    old_api_id, old_generation = tombstone[:2]
    try:
        current_api = store.gateway_api
        generation = store.gateway_session_generation
        connected = store.is_connected is True
        final_api = store.gateway_api
        final_generation = store.gateway_session_generation
    except Exception:
        return False
    return (
        type(old_api_id) is int
        and old_api_id == id(api)
        and type(old_generation) is int
        and old_generation >= 0
        and type(generation) is int
        and generation == old_generation
        and connected
        and current_api is api
        and final_api is api
        and type(final_generation) is int
        and final_generation == generation
    )


def _market_lease_acquirer(api):
    try:
        acquire = api.acquire_market_subscription
    except AttributeError:
        return None
    return acquire if callable(acquire) else None


def _acquire_failed_without_lease(exc):
    """Recognize only SDK outcomes that prove no market lease was created."""
    if isinstance(exc, OwnerOperationError):
        # The SDK manager rolls back its local candidate for an owner refusal;
        # the owner-side claim contract raises before changing lease state.
        return True
    if (
        type(exc) is ThreadedRuntimeError
        and getattr(exc, "_owner_call_not_submitted", False) is True
        and getattr(exc, "code", None) in _OWNER_CALL_NOT_SUBMITTED_CODES
    ):
        return True
    # GatewayBtApi performs these exact checks before it calls the lease
    # manager. Bind only the finite SDK preflight errors; arbitrary RuntimeError
    # values can follow a submitted owner operation and remain unknown.
    return (
        type(exc) in (RuntimeError, ValueError)
        and len(exc.args) == 1
        and type(exc.args[0]) is str
        and exc.args[0] in _GATEWAY_ACQUIRE_PREFLIGHT_CODES
    )


def begin_gateway_market_session_drain(
        store, api, *, pending_only=False, deadline=None):
    """Close exact active feed leases before Store closes their SDK runtime.

    The Store claim lock is held only while setting the admission gate and
    snapshotting current claims. SDK calls happen after releasing it.
    """
    claims = store.__dict__.setdefault("_gateway_market_feed_claims", {})
    lock = store.__dict__.setdefault(
        "_gateway_market_feed_claim_lock", threading.Lock()
    )
    store.__dict__.setdefault("_gateway_market_feed_claim_tombstones", {})
    token = object()
    remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
    acquired = (
        lock.acquire()
        if remaining is None
        else lock.acquire(timeout=min(remaining, threading.TIMEOUT_MAX))
    )
    if not acquired:
        return None
    try:
        if store.__dict__.get("_gateway_market_session_draining") is not None:
            return None
        claim_values = tuple(claims.values())
        adapters = tuple(
            adapter for adapter in claim_values
            if type(adapter) is GatewayMarketAdapter
        )
        unsupported_claim = any(
            adapter is not None and type(adapter) is not GatewayMarketAdapter
            for adapter in claim_values
        )
        if pending_only:
            adapters = tuple(
                adapter for adapter in adapters
                if adapter._lease_drain_pending and adapter._api is api
            )
            if not adapters and not unsupported_claim:
                return (store, lock, None, api, (), True)
        store.__dict__["_gateway_market_session_draining"] = token
    finally:
        lock.release()
    complete = not unsupported_claim
    try:
        for adapter in adapters:
            try:
                if adapter.prepare_session_reconnect(
                    api, force=not pending_only, deadline=deadline
                ) is not True:
                    complete = False
            except Exception:
                complete = False
    except BaseException as exc:
        end_gateway_market_session_drain((store, lock, token))
        if isinstance(exc, Exception):
            complete = False
        else:
            raise
    return (store, lock, token, api, adapters, complete)


def end_gateway_market_session_drain(drain):
    """Release the short-lived Store admission gate created above."""
    if drain is None:
        return
    store, lock, token = drain[:3]
    with lock:
        if token is not None and store.__dict__.get(
                "_gateway_market_session_draining") is token:
            del store.__dict__["_gateway_market_session_draining"]


def resume_gateway_market_session_drain(drain, *, deadline=None):
    """Resume same-session adapters if a lost API recovered during draining."""
    if drain is None or len(drain) != 6:
        return False
    _store, _lock, _token, api, adapters, _complete = drain
    resumed = True
    for adapter in adapters:
        if adapter.resume_session_reconnect(api, deadline=deadline) is not True:
            resumed = False
    return resumed

class GatewayMarketAdapter:
    """Own a single feed cursor; never create a provider or a market source."""

    def __init__(self, store, symbol, feed, *, timeout_seconds=3.0, clock_verification=None):
        config = store.gateway_strategy_config
        settings = config.market_settings
        if settings is None or type(symbol) is not str or not symbol:
            raise ValueError("GATEWAY_MARKET_SUBSCRIPTION_REQUIRED")
        matches = [(name, item) for name, item in settings.subscriptions.items()
                   if item.key.channel == "tick"
                   and symbol in (item.key.instrument.instrument_id, item.key.instrument.native_symbol)]
        if len(matches) != 1:
            raise ValueError("GATEWAY_MARKET_SUBSCRIPTION_AMBIGUOUS")
        name, setting = matches[0]
        if not setting.require_source_descriptor:
            raise ValueError("GATEWAY_MARKET_SOURCE_DESCRIPTOR_REQUIRED")
        expected = [key for key in config.instruments_by_ref.values() if key == setting.key.instrument]
        if len(expected) != 1:
            raise ValueError("GATEWAY_MARKET_INSTRUMENT_MISMATCH")
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds):
            raise ValueError("GATEWAY_MARKET_TIMEOUT_INVALID")
        if feed is None:
            raise ValueError("GATEWAY_MARKET_FEED_REQUIRED")
        claims = store.__dict__.setdefault("_gateway_market_feed_claims", {})
        self._claim_lock = store.__dict__.setdefault("_gateway_market_feed_claim_lock", threading.Lock())
        tombstones = store.__dict__.setdefault("_gateway_market_feed_claim_tombstones", {})
        self._claims, self._claim_tombstones, self._name, self._feed = claims, tombstones, name, feed
        self._store, self._api, self._key = store, store.gateway_api, setting.key
        self._config = config
        self._session_generation = _session_generation(store)
        self._lease_mode = _market_lease_acquirer(self._api) is not None
        if self._lease_mode and not 0 < timeout_seconds <= 30:
            raise GatewayMarketProjectionError("INVALID_GATEWAY_MARKET_BINDING")
        self._lease_client = None
        self._lease_api = None
        self._retired_leases = []
        self._lease_attempted = False
        self._lease_candidate_api = None
        self._lease_acquire_state = "idle"
        self._lease_release_confirmed = False
        self._lease_drain_pending = False
        self._lifecycle_lock = threading.RLock()
        self._closing = False
        self._closed = False
        self._reason = "STARTING"
        self._backoff = (0, 1, 2, 5, 10, 30)
        self._attempt = 0
        self._next_retry = 0.0
        self._pending_operation = None
        self._last_event = None
        self._last_receipt = None
        self._latest_event = None
        self._latest_receipt = None
        self._clock_verifier = None
        self._clock_owned = False
        self._clock_started = False
        self._qualifier = None
        self._clock_interval = 300.0
        self._timeout_seconds = timeout_seconds
        self._qualifier_options = None
        self._allow_stale_event_time = False
        self._projector = None
        self._projector_client = None
        if not self._lease_mode:
            # Preserve the legacy API's accessor and projector construction
            # order. A lease-capable API is deliberately not touched until
            # start() can retain a failed or pending claim on this adapter.
            self._projector_client = self._api.market_subscription(
                config.exchange_name, name
            )
            self._projector = self._make_projector(self._projector_client, config)
        if clock_verification is not None and clock_verification is not False:
            from bt_api_py.clock_verification import ClockVerifier, GatewayClockVerifier

            if type(clock_verification) is GatewayClockVerifier:
                self._clock_verifier = clock_verification
            elif type(clock_verification) is dict:
                options = clock_verification
                allowed = {"servers", "validity_seconds", "max_error_bound_ms", "timeout_seconds",
                           "refresh_interval_seconds", "max_wall_jump_ns", "max_latency_seconds",
                           "max_clock_error_ms", "rpc_timeout_seconds"}
                servers = options.get("servers")
                if (set(options) - allowed or type(servers) not in (list, tuple) or not servers
                        or any(type(s) is not str or not s.strip() or s != s.strip() for s in servers)):
                    raise ValueError("GATEWAY_CLOCK_CONFIGURATION_INVALID")
                def number(name, default, minimum, maximum):
                    value = options.get(name, default)
                    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
                        raise ValueError("GATEWAY_CLOCK_CONFIGURATION_INVALID")
                    return value
                validity = number("validity_seconds", 900, 1, 86400)
                error = number("max_error_bound_ms", 500, 0.001, 60000)
                timeout = number("timeout_seconds", 2, 0.001, 30)
                self._clock_interval = number("refresh_interval_seconds", 300, 1, 3600)
                verifier = ClockVerifier(
                    servers=tuple(servers), validity_seconds=validity,
                    max_error_bound_ms=error, timeout_seconds=timeout)
                if "max_wall_jump_ns" in options:
                    self._clock_verifier = GatewayClockVerifier(
                        verifier, max_wall_jump_ns=options["max_wall_jump_ns"])
                else:
                    self._clock_verifier = GatewayClockVerifier(verifier)
                self._clock_owned = True
            else:
                raise ValueError("GATEWAY_CLOCK_CONFIGURATION_INVALID")
            options = clock_verification if type(clock_verification) is dict else {}
            feed_limit = feed.p.event_time_max_age
            requested_limit = options.get("max_latency_seconds", feed_limit)
            if (type(feed_limit) not in (int, float) or not math.isfinite(feed_limit) or feed_limit <= 0
                    or type(requested_limit) not in (int, float)
                    or not math.isfinite(requested_limit) or requested_limit <= 0):
                raise ValueError("GATEWAY_CLOCK_CONFIGURATION_INVALID")
            self._qualifier_options = {
                "max_latency_seconds": min(requested_limit, feed_limit),
                "max_clock_error_ms": options.get("max_clock_error_ms", 500),
                "timeout_seconds": options.get("rpc_timeout_seconds", 1)}
            allow_stale = getattr(feed.p, "allow_stale_market_feed", False)
            if type(allow_stale) is not bool:
                raise ValueError("GATEWAY_CLOCK_CONFIGURATION_INVALID")
            self._allow_stale_event_time = allow_stale
        if not self._lease_mode:
            self._qualifier = self._make_qualifier(self._projector_client)
        with self._claim_lock:
            if store.__dict__.get("_gateway_market_session_draining") is not None:
                raise ValueError("GATEWAY_MARKET_SESSION_RECONNECTING")
            existing = claims.get(name)
            if existing is not None:
                # The SDK facade shares one consumer and cursor per
                # subscription. Even the same Feed object must never be
                # backed by two adapters with independent local sequence
                # state.
                raise ValueError("GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED")
            if name in claims or name in tombstones:
                tombstone = tombstones.get(name)
                new_session = _new_session_proves_cursor_isolation(
                    store, tombstone, self._api
                )
                released_lease = (
                    self._lease_mode
                    and _same_session_lease_release_proves_cursor_isolation(
                        store, tombstone, self._api
                    )
                )
                if not (new_session or released_lease):
                    raise ValueError("GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED")
                claims.pop(name, None)
                tombstones.pop(name, None)
            claims[name] = self

    def _install_market_client(self, client, config):
        self._projector, self._qualifier = self._build_market_client(client, config)
        self._projector_client = client

    def _build_market_client(self, client, config, *, timeout_seconds=None):
        return (
            self._make_projector(client, config, timeout_seconds=timeout_seconds),
            self._make_qualifier(client),
        )

    def _make_projector(self, client, config, *, timeout_seconds=None):
        projector = GatewayMarketTickProjector(
            client,
            key=self._key,
            scope=WireScope(config.route.scope.execution_domain_ref),
            peer=config.peer,
            timeout_seconds=(
                self._timeout_seconds if timeout_seconds is None else timeout_seconds
            ),
        )
        return projector

    def _make_qualifier(self, client):
        if self._qualifier_options is not None:
            from bt_api_py.clock_verification import GatewayTradeClockQualifier

            return GatewayTradeClockQualifier(
                client,
                self._clock_verifier,
                allow_stale_event_time=self._allow_stale_event_time,
                **self._qualifier_options,
            )
        return None

    def _ensure_market_client(self, api=None, config=None, *, timeout_seconds=None):
        api = self._api if api is None else api
        config = self._config if config is None else config
        if self._projector is not None:
            return
        acquire = _market_lease_acquirer(api)
        if acquire is None:
            if self._lease_mode:
                raise RuntimeError("GATEWAY_MARKET_LEASE_API_REQUIRED")
            client = api.market_subscription(config.exchange_name, self._name)
            self._lease_mode = False
        else:
            self._lease_mode = True
            if self._lease_client is not None and self._lease_api is api:
                client = self._lease_client
            else:
                client = self._acquire_sdk_lease(
                    api, config, timeout_seconds=timeout_seconds
                )
            if not callable(getattr(client, "close", None)):
                raise RuntimeError("GATEWAY_MARKET_LEASE_INVALID")
        self._projector, self._qualifier = self._build_market_client(
            client, config, timeout_seconds=timeout_seconds
        )
        self._projector_client = client

    def _acquire_sdk_lease(self, api, config, *, timeout_seconds=None):
        acquire = _market_lease_acquirer(api)
        if acquire is None:
            raise RuntimeError("GATEWAY_MARKET_LEASE_API_REQUIRED")
        self._lease_attempted = True
        self._lease_candidate_api = api
        self._lease_acquire_state = "unknown"
        lease_timeout = (
            self._timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        if type(lease_timeout) not in (int, float) or lease_timeout <= 0:
            self._lease_acquire_state = "unknown"
            raise RuntimeError("GATEWAY_MARKET_LEASE_UNCONFIRMED")
        try:
            client = acquire(
                config.exchange_name,
                self._name,
                timeout_seconds=lease_timeout,
            )
        except Exception as exc:
            if _acquire_failed_without_lease(exc):
                self._lease_acquire_state = "none"
            raise
        self._lease_client = client
        self._lease_api = api
        self._lease_acquire_state = "acquired"
        self._lease_release_confirmed = False
        if not callable(getattr(client, "close", None)):
            raise RuntimeError("GATEWAY_MARKET_LEASE_INVALID")
        return client

    def _retain_retired_lease(self, api, client):
        if client is not None and not any(
            old_api is api and old_client is client
            for old_api, old_client in self._retired_leases
        ):
            self._retired_leases.append((api, client))

    def _has_lease_for_api(self, api):
        return self._lease_mode and (
            self._api is api
            or self._lease_api is api
            or (self._lease_acquire_state == "unknown"
                and self._lease_candidate_api is api)
            or any(old_api is api for old_api, _client in self._retired_leases)
        )

    def _has_any_owned_lease(self):
        return (
            self._lease_client is not None
            or bool(self._retired_leases)
            or self._lease_acquire_state == "unknown"
        )

    def _lease_for_api(self, api, config):
        for old_api, client in self._retired_leases:
            if old_api is api:
                return client
        acquire = _market_lease_acquirer(api)
        if acquire is None:
            return None
        return self._acquire_sdk_lease(api, config)

    def _resolve_unreturned_lease(self, api, *, timeout_seconds=None):
        """Re-observe a timed-out SDK manager candidate before local close."""
        if self._lease_client is not None or self._lease_acquire_state != "unknown":
            return
        if api is None or self._lease_candidate_api is not api:
            raise RuntimeError("GATEWAY_MARKET_LEASE_UNCONFIRMED")
        try:
            self._acquire_sdk_lease(
                api, self._config, timeout_seconds=timeout_seconds
            )
        except Exception as exc:
            if self._lease_acquire_state == "none":
                return
            raise RuntimeError("GATEWAY_MARKET_LEASE_UNCONFIRMED") from exc

    def _release_sdk_leases(self, *, timeout_seconds=None, deadline=None):
        lease_timeout = self._timeout_seconds if timeout_seconds is None else timeout_seconds

        def remaining_timeout():
            if deadline is None:
                return lease_timeout
            return max(0.0, min(lease_timeout, deadline - time.monotonic()))

        if self._lease_client is None and self._lease_acquire_state == "unknown":
            self._resolve_unreturned_lease(
                self._lease_candidate_api, timeout_seconds=remaining_timeout()
            )
        entries = list(self._retired_leases)
        if self._lease_client is not None:
            entries.insert(0, (self._lease_api, self._lease_client))
        if not entries:
            if self._lease_acquire_state == "unknown":
                raise RuntimeError("GATEWAY_MARKET_LEASE_UNCONFIRMED")
            self._lease_acquire_state = "none"
            self._lease_release_confirmed = True
            return
        for api, client in entries:
            close = getattr(client, "close", None)
            if not callable(close):
                raise RuntimeError("GATEWAY_MARKET_LEASE_UNCONFIRMED")
            close_timeout = remaining_timeout()
            if close_timeout <= 0 or close(timeout_seconds=close_timeout) is not True:
                raise RuntimeError("GATEWAY_MARKET_LEASE_UNCONFIRMED")
            if self._lease_client is client and self._lease_api is api:
                self._lease_client = None
                self._lease_api = None
                self._lease_acquire_state = "none"
            self._retired_leases = [
                (old_api, old_client)
                for old_api, old_client in self._retired_leases
                if not (old_api is api and old_client is client)
            ]
        self._lease_release_confirmed = True

    def _owns_claim(self):
        with self._claim_lock:
            current = self._store.__dict__.get("_gateway_market_feed_claims")
            return current is self._claims and current.get(self._name) is self

    def _session_is_draining(self):
        with self._claim_lock:
            return self._store.__dict__.get(
                "_gateway_market_session_draining"
            ) is not None

    def _store_stopped(self):
        return getattr(self._store, "_started", True) is False

    def _start_owned_clock(self):
        if self._clock_owned and not self._clock_started:
            refresh = getattr(self._clock_verifier, "refresh", None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass
            self._clock_verifier.start_background_refresh(self._clock_interval)
            self._clock_started = True

    def _mark_claim_lost(self):
        self._last_event = self._last_receipt = None
        self._latest_event = self._latest_receipt = None
        self._pending_operation = None
        self._reason = "GATEWAY_MARKET_SUBSCRIPTION_CLAIM_LOST"

    def start(self):
        with self._lifecycle_lock:
            if self._session_is_draining():
                raise RuntimeError("GATEWAY_MARKET_SESSION_RECONNECTING")
            if self._store_stopped():
                raise RuntimeError("GATEWAY_STORE_STOPPED")
            if self._closing or self._closed:
                raise RuntimeError("GATEWAY_MARKET_ADAPTER_CLOSED")
            if not self._owns_claim():
                self._mark_claim_lost()
                raise RuntimeError("GATEWAY_MARKET_SUBSCRIPTION_CLAIM_LOST")
            if self._lease_drain_pending:
                current_api = self._store.gateway_api
                if current_api is self._api:
                    if not self.resume_session_reconnect(current_api):
                        raise RuntimeError("GATEWAY_MARKET_LEASE_RESUME_UNCONFIRMED")
                    return None
                if not self._adopt_session():
                    raise RuntimeError("GATEWAY_SESSION_REPLACED")
            return self._start_open()

    def _start_open(self):
        if self._lease_drain_pending:
            self._reason = "GATEWAY_MARKET_SESSION_RECONNECTING"
            return
        if self._projector is None:
            try:
                self._ensure_market_client()
            except Exception as exc:
                self._pending_operation = "lease"
                code = getattr(exc, "code", None)
                self._reason = (
                    code if type(code) is str else "GATEWAY_MARKET_LEASE_UNAVAILABLE"
                )
                return
        self._start_owned_clock()
        self._pending_operation = "start"
        try:
            self._projector.start()
            self._pending_operation = "status"
            status = self._projector.status()
            self._reason = self._status_reason(status)
            self._pending_operation = None
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code in _TRANSIENT_OWNER_CODES:
                self._reason = code
            elif code in ("RECOVERY_REQUIRED", "PROVIDER_RESYNC_REQUIRED"):
                self._pending_operation = None
                self._reason = code
            else:
                raise

    @staticmethod
    def _status_reason(status):
        if status["local_result_gap"]:
            return "LOCAL_RESULT_GAP"
        if status["authorization_interrupted"]:
            return "MARKET_AUTHORIZATION_INTERRUPTED"
        if status["resync_required"]:
            return "PROVIDER_RESYNC_REQUIRED"
        if status["recovery_required"] or not status["healthy"]:
            return "RECOVERY_REQUIRED"
        return None

    def recovery_reason(self, _symbol=None):
        return self._reason

    def _retry(self):
        now = time.monotonic()
        if now < self._next_retry:
            return False
        self._next_retry = now + self._backoff[min(self._attempt, len(self._backoff) - 1)]
        self._attempt += 1
        if self._pending_operation == "poll":
            return True
        if self._pending_operation == "clock":
            try:
                self._start_owned_clock()
            except Exception:
                self._reason = "GATEWAY_CLOCK_REFRESH_UNAVAILABLE"
                return False
            self._pending_operation = "start"
        if self._pending_operation == "lease":
            try:
                self._ensure_market_client()
                self._start_owned_clock()
            except Exception as exc:
                code = getattr(exc, "code", None)
                self._reason = (
                    code if type(code) is str else "GATEWAY_MARKET_LEASE_UNAVAILABLE"
                )
                return False
            self._pending_operation = "start"
        if self._pending_operation == "start":
            self._start_owned_clock()
            self._projector.start()
            self._pending_operation = "status"
        if self._pending_operation == "status":
            self._reason = self._status_reason(self._projector.status())
            self._pending_operation = None
            if self._reason is None:
                self._attempt = 0
                return True
            return False
        if self._pending_operation == "resync" or self._reason == "PROVIDER_RESYNC_REQUIRED":
            self._pending_operation = "resync"
            self._projector.accept_resync()
        elif self._pending_operation == "recover" or self._reason == "RECOVERY_REQUIRED":
            self._pending_operation = "recover"
            self._projector.recover()
        else:
            return False
        self._pending_operation = "status"
        self._reason = self._status_reason(self._projector.status())
        self._pending_operation = None
        if self._reason is None:
            self._attempt = 0
            return True
        return False

    def _adopt_session(self):
        """Follow the Store to its new SDK session after a reconnect (D63-03).

        The old subscription client died with its runtime. A new projector
        starts from the subscription's bootstrap, so nothing of the old cursor
        is carried over and the feed is not tradable until fresh real-time
        ticks arrive (the feed reports DELAYED, then LIVE again).
        """
        if self._closing or self._closed or not self._owns_claim():
            return False
        if self._session_is_draining() or (
                self._lease_drain_pending
                and (self._lease_client is not None
                     or not self._lease_release_confirmed)):
            return False
        store = self._store
        if not store.is_connected:
            return False
        api = store.gateway_api
        generation = _session_generation(store)
        if (self._session_generation is not None
                and (generation is None or generation <= self._session_generation)):
            return False
        config = store.gateway_strategy_config
        acquire = _market_lease_acquirer(api)
        client = None
        leased_client = None
        try:
            if acquire is None:
                if self._lease_mode:
                    return False
                client = api.market_subscription(config.exchange_name, self._name)
            else:
                # A per-consumer lease cannot be silently abandoned when the
                # Store replaced its runtime without the pre-close drain hook.
                if (self._lease_client is not None
                        and self._lease_api is not api):
                    return False
                if (self._lease_acquire_state == "unknown"
                        and self._lease_candidate_api is not api):
                    return False
                leased_client = self._lease_for_api(api, config)
                client = leased_client
            projector, qualifier = self._build_market_client(client, config)
        except Exception:
            if leased_client is not None:
                self._retain_retired_lease(api, leased_client)
            return False
        if (store.gateway_api is not api
                or _session_generation(store) != generation
                or not store.is_connected):
            if leased_client is not None:
                self._retain_retired_lease(api, leased_client)
            return False
        if self._lease_client is not None and self._lease_api is not api:
            self._retain_retired_lease(self._lease_api, self._lease_client)
        if leased_client is not None:
            self._retired_leases = [
                (old_api, old_client)
                for old_api, old_client in self._retired_leases
                if not (old_api is api and old_client is leased_client)
            ]
            self._lease_client, self._lease_api = leased_client, api
            self._lease_release_confirmed = False
        else:
            self._lease_client = self._lease_api = None
        self._lease_mode = acquire is not None
        self._api, self._projector, self._qualifier = api, projector, qualifier
        self._projector_client = client
        self._config = config
        self._session_generation = generation
        self._lease_drain_pending = False
        self._reason, self._pending_operation = "STARTING", "start"
        self._attempt, self._next_retry = 0, 0.0
        if self._clock_owned and not self._clock_started:
            self._reason, self._pending_operation = "GATEWAY_CLOCK_REFRESH_UNAVAILABLE", "clock"
        return True

    def prepare_session_reconnect(self, api, *, force=True, deadline=None):
        """Owner-confirm lease release before Store closes this SDK runtime.

        A timeout is resolved by reacquiring the same API/name through the SDK
        manager, which retains and returns its original candidate. Unknown
        results remain claimed and block runtime replacement.
        """
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        acquired = (
            self._lifecycle_lock.acquire()
            if remaining is None
            else self._lifecycle_lock.acquire(
                timeout=min(remaining, threading.TIMEOUT_MAX)
            )
        )
        if not acquired:
            return False
        try:
            if not self._owns_claim():
                return True
            has_owned_clock = self._clock_owned and self._clock_started
            if not self._has_lease_for_api(api) and not self._has_any_owned_lease():
                if not (force and has_owned_clock):
                    return True
            if not force and not self._lease_drain_pending:
                return True
            if self._closed:
                return (
                    self._lease_client is None
                    and not self._retired_leases
                    and self._lease_acquire_state != "unknown"
                )
            self._lease_drain_pending = True
            if self._clock_owned and self._clock_started:
                clock_timeout = (
                    5.0 if deadline is None
                    else max(0.0, min(5.0, deadline - time.monotonic()))
                )
                if clock_timeout <= 0 or not self._clock_verifier.stop_background_refresh(
                    timeout_seconds=clock_timeout
                ):
                    self._lease_drain_pending = False
                    return False
                self._clock_started = False
            try:
                self._release_sdk_leases(deadline=deadline)
            except Exception:
                self._reason = "GATEWAY_MARKET_LEASE_DRAIN_UNCONFIRMED"
                return False
            if self._closing:
                return (
                    self._lease_client is None
                    and not self._retired_leases
                    and self._lease_acquire_state != "unknown"
                )
            self._projector = None
            self._projector_client = None
            self._qualifier = None
            self._last_event = self._last_receipt = None
            self._latest_event = self._latest_receipt = None
            self._pending_operation = "lease"
            self._reason = "GATEWAY_SESSION_RECONNECTING"
            self._attempt, self._next_retry = 0, 0.0
            return True
        finally:
            self._lifecycle_lock.release()

    def resume_session_reconnect(self, api, *, deadline=None):
        """Restore a still-current API after a cancelled/failed drain."""
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        acquired = (
            self._lifecycle_lock.acquire()
            if remaining is None
            else self._lifecycle_lock.acquire(
                timeout=min(remaining, threading.TIMEOUT_MAX)
            )
        )
        if not acquired:
            return False
        try:
            if not self._lease_drain_pending:
                return True
            if self._store_stopped():
                return False
            if self._closed or self._closing:
                return (
                    self._lease_client is None
                    and not self._retired_leases
                    and self._lease_acquire_state != "unknown"
                )
            if not self._owns_claim():
                return False
            if self._session_is_draining():
                return False
            state_getter = getattr(self._store, "gateway_session_state", None)
            if callable(state_getter):
                if state_getter() != "CONNECTED":
                    return False
            elif getattr(self._store, "is_connected", False) is not True:
                return False
            current_api = self._store.gateway_api
            if current_api is not api or self._api is not api:
                return (
                    current_api is not self._api
                    and self._lease_client is None
                    and self._lease_release_confirmed
                )
            try:
                self._release_sdk_leases(deadline=deadline)
                if deadline is None:
                    acquire_timeout = self._timeout_seconds
                else:
                    remaining = max(0.0, deadline - time.monotonic())
                    acquire_timeout = min(self._timeout_seconds, remaining / 3.0)
                    if acquire_timeout <= 0:
                        return False
                self._ensure_market_client(
                    api, self._config, timeout_seconds=acquire_timeout
                )
            except Exception as exc:
                code = getattr(exc, "code", None)
                self._reason = (
                    code if type(code) is str
                    else "GATEWAY_MARKET_LEASE_RESUME_UNCONFIRMED"
                )
                return False
            self._lease_drain_pending = False
            try:
                self._start_open()
            except Exception as exc:
                code = getattr(exc, "code", None)
                self._reason = (
                    code if type(code) is str
                    else "GATEWAY_MARKET_START_UNAVAILABLE"
                )
                self._pending_operation = "start"
            return True
        finally:
            self._lifecycle_lock.release()

    def poll(self):
        with self._lifecycle_lock:
            if self._store_stopped():
                self._last_event = self._last_receipt = None
                self._latest_event = self._latest_receipt = None
                self._reason = "GATEWAY_MARKET_ADAPTER_CLOSED"
                return None
            if self._session_is_draining():
                self._last_event = self._last_receipt = None
                self._latest_event = self._latest_receipt = None
                self._reason = "GATEWAY_MARKET_SESSION_RECONNECTING"
                return None
            if self._lease_drain_pending:
                current_api = self._store.gateway_api
                if current_api is self._api:
                    if not self.resume_session_reconnect(current_api):
                        self._last_event = self._last_receipt = None
                        self._latest_event = self._latest_receipt = None
                        return None
                elif (self._lease_client is not None
                      or not self._lease_release_confirmed):
                    self._last_event = self._last_receipt = None
                    self._latest_event = self._latest_receipt = None
                    self._reason = "GATEWAY_MARKET_SESSION_RECONNECTING"
                    return None
            if self._closing or self._closed:
                self._last_event = self._last_receipt = None
                self._latest_event = self._latest_receipt = None
                self._reason = "GATEWAY_MARKET_ADAPTER_CLOSED"
                return None
            if not self._owns_claim():
                self._mark_claim_lost()
                return None
            return self._poll_open()

    def _poll_open(self):
        self._last_event = self._last_receipt = None
        if self._store.gateway_api is not self._api:
            self._latest_event = self._latest_receipt = None
            if not self._adopt_session():
                self._pending_operation = None
                self._reason = "GATEWAY_SESSION_REPLACED"
                return None
        try:
            if self._reason is not None:
                self._latest_event = self._latest_receipt = None
                if not self._retry():
                    return None
            self._pending_operation = "poll"
            result = self._projector.poll()
            self._pending_operation = None
            if result is None:
                self._pending_operation = "status"
                self._reason = self._status_reason(self._projector.status())
                self._pending_operation = None
                if self._reason is not None:
                    self._latest_event = self._latest_receipt = None
            else:
                self._reason = None
                self._last_event = result
                self._last_receipt = self._projector.last_receipt
                if self._last_receipt is not None and self._last_receipt.source == "pub":
                    self._latest_event, self._latest_receipt = result, self._last_receipt
                else:
                    # Replay or snapshot is valid observation, not proof of a
                    # current real-time receipt for new order admission.
                    self._latest_event = self._latest_receipt = None
            return result
        except Exception as exc:
            self._latest_event = self._latest_receipt = None
            code = getattr(exc, "code", None)
            if code in _TRANSIENT_OWNER_CODES:
                # The pending operation is retried unchanged after backoff.
                self._reason = code
            elif (type(code) is str and code not in ("RECOVERY_REQUIRED", "PROVIDER_RESYNC_REQUIRED")
                  and not isinstance(exc, GatewayMarketProjectionError)):
                # Any other SDK failure (for example while the Gateway is
                # paused or restarting) used to stop this feed for good: after
                # backoff, re-read the SDK status to learn whether to recover,
                # resync or simply resume (I63-E112). Projection checks of this
                # adapter stay terminal.
                self._pending_operation = "status"
                self._reason = code
            else:
                self._pending_operation = None
                self._reason = code if type(code) is str else "GATEWAY_MARKET_UNAVAILABLE"
            return None

    def receipt_for(self, event):
        """Return the SDK's exact receipt only for the just-delivered event."""
        with self._lifecycle_lock:
            if self._store_stopped() or self._session_is_draining() or self._lease_drain_pending:
                return None
            if self._closing or self._closed:
                return None
            owns_claim = self._owns_claim()
            if not owns_claim:
                self._mark_claim_lost()
                return None
            if event is not self._last_event:
                return None
            return self._last_receipt

    def latest_realtime(self):
        """The latest real-time delivery pair; not itself trading authority."""
        with self._lifecycle_lock:
            if self._store_stopped() or self._session_is_draining() or self._lease_drain_pending:
                return None
            if self._closing or self._closed:
                return None
            owns_claim = self._owns_claim()
            if not owns_claim:
                self._mark_claim_lost()
                return None
            if self._reason is not None:
                return None
            if self._latest_event is None or self._latest_receipt is None:
                return None
            return self._latest_event, self._latest_receipt

    def matches(self, store, feed, instrument):
        """Check the exact Store, Feed, subscription and complete instrument."""
        from bt_api_base.market_protocol import MarketInstrumentKey

        with self._lifecycle_lock:
            if self._store_stopped() or self._session_is_draining() or self._lease_drain_pending:
                return False
            if self._closed:
                return False
            if type(instrument) is not MarketInstrumentKey:
                return False
            if store is not self._store or feed is not self._feed or instrument != self._key.instrument:
                return False
            try:
                claimed = self._owns_claim()
                if self._closed:
                    return False
                if not claimed:
                    self._mark_claim_lost()
                    return False
                config = store.gateway_strategy_config
                selected = config.market_settings.subscriptions[self._name]
                api = store.gateway_api
                generation = _session_generation(store)
                if (api is not self._api
                        or generation != self._session_generation
                        or selected.key != self._key):
                    return False
                projector_client = self._projector._client
                if self._lease_mode:
                    client_matches = (
                        self._lease_api is api
                        and self._lease_client is projector_client
                    )
                else:
                    client_matches = (
                        api.market_subscription(config.exchange_name, self._name)
                        is projector_client
                    )
                return bool(
                    claimed
                    and client_matches
                    and store.gateway_api is api
                    and _session_generation(store) == generation
                )
            except (AttributeError, KeyError, TypeError, RuntimeError, ValueError):
                return False

    def qualify_latest(self):
        """Run authenticated clock checks only at the order boundary."""
        with self._lifecycle_lock:
            if self._store_stopped() or self._session_is_draining() or self._lease_drain_pending:
                return None
            if self._closing or self._closed:
                return None
            if not self._owns_claim():
                self._mark_claim_lost()
                return None
            return self._qualify_latest_open()

    def _qualify_latest_open(self):
        from bt_api_py.clock_verification import GatewayTradeClockQualification
        from bt_api_py.service_market import MarketReceiveReceipt

        pair = self.latest_realtime()
        if self._qualifier is None or pair is None:
            return None
        event, receipt = pair
        try:
            if (type(receipt) is not MarketReceiveReceipt or receipt.source != "pub"
                    or receipt.stream_id != event.cursor.stream_id
                    or receipt.stream_epoch != event.cursor.epoch
                    or type(receipt.sequence) is not int or receipt.sequence != event.cursor.sequence
                    or type(receipt.message_id) is not str or not receipt.message_id
                    or event.data.instrument != self._key.instrument):
                return None
            result = self._qualifier.qualify(event, receipt)
            current = self.latest_realtime()
            status = self._projector.status()
            after_status = self.latest_realtime()
            if (type(result) is not GatewayTradeClockQualification or result.ok is not True
                    or current is None or current[0] is not event or current[1] is not receipt
                    or after_status is None or after_status[0] is not event or after_status[1] is not receipt
                    or self._status_reason(status) is not None
                    or type(result.expires_monotonic_ns) is not int
                    or time.monotonic_ns() >= result.expires_monotonic_ns):
                logging.getLogger("bt_api_ctp").warning(
                    "gateway market qualify_latest rejected: ok=%s reason=%s status_reason=%s",
                    getattr(result, "ok", None),
                    getattr(result, "reason", None),
                    self._status_reason(status),
                )
                return None
            key = self._key.to_dict()
            key["instrument"] = MappingProxyType(key["instrument"])
            reference = MappingProxyType({"key": MappingProxyType(key), "epoch": receipt.stream_epoch,
                                          "sequence": receipt.sequence, "message_id": receipt.message_id})
            return result, reference
        except Exception:
            return None
    def close(self):
        with self._lifecycle_lock:
            if self._closed:
                return None
            self._closing = True
            return self._close_open()

    def _close_open(self):
        self._last_event = self._last_receipt = None
        self._latest_event = self._latest_receipt = None
        self._pending_operation = None
        if self._clock_owned and self._clock_started:
            if not self._clock_verifier.stop_background_refresh(timeout_seconds=5):
                raise RuntimeError("GATEWAY_CLOCK_SHUTDOWN_PENDING")
            self._clock_started = False
        if (self._lease_mode or self._lease_client is not None
                or self._retired_leases or self._lease_attempted):
            self._release_sdk_leases()
        with self._claim_lock:
            self._closed = True
            self._reason = "GATEWAY_MARKET_ADAPTER_CLOSED"
            current = self._store.__dict__.get("_gateway_market_feed_claims")
            if current is self._claims and current.get(self._name) is self:
                self._claims[self._name] = None
                if self._lease_mode:
                    self._claim_tombstones[self._name] = (
                        id(self._api), self._session_generation, self._closed,
                        self._lease_release_confirmed, self._api,
                    )
                else:
                    # Legacy SDK APIs do not prove per-consumer release. Keep
                    # their prior generation-gated tombstone behavior.
                    self._claim_tombstones[self._name] = (
                        id(self._api), self._session_generation, self._closed
                    )
