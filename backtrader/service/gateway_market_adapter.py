"""Bind one BT feed to one explicitly configured SDK Gateway subscription."""
from __future__ import annotations

import math
import threading
import time
from types import MappingProxyType

from bt_api_base.service_protocol import WireScope
from bt_api_py.gateway_market_projection import (
    GatewayMarketProjectionError,
    GatewayMarketTickProjector,
)



# Owner-side conditions that clear by themselves: a call still queued/running,
# or another call holding the subscription client's single pending slot (it is
# retired once finished). Never terminal for this adapter.
_TRANSIENT_OWNER_CODES = ("OWNER_TIMEOUT_QUEUED", "OWNER_TIMEOUT_RUNNING", "OWNER_OPERATION_PENDING")

class GatewayMarketAdapter:
    """Own a single feed cursor; never create a provider or a market source."""

    def __init__(self, store, symbol, feed, *, timeout_seconds=1.0, clock_verification=None):
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
        claims = store.__dict__.setdefault("_gateway_market_feed_claims", {})
        self._claim_lock = store.__dict__.setdefault("_gateway_market_feed_claim_lock", threading.Lock())
        self._claims, self._name, self._feed = claims, name, feed
        self._store, self._api, self._key = store, store.gateway_api, setting.key
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
        self._projector = GatewayMarketTickProjector(
            self._api.market_subscription(config.exchange_name, name),
            key=setting.key, scope=WireScope(config.route.scope.execution_domain_ref),
            peer=config.peer, timeout_seconds=timeout_seconds,
        )
        if clock_verification is not None and clock_verification is not False:
            from bt_api_py.clock_verification import ClockVerifier, GatewayClockVerifier, GatewayTradeClockQualifier

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
                jump = options.get("max_wall_jump_ns", 10_000_000)
                self._clock_verifier = GatewayClockVerifier(ClockVerifier(
                    servers=tuple(servers), validity_seconds=validity,
                    max_error_bound_ms=error, timeout_seconds=timeout), max_wall_jump_ns=jump)
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
            self._qualifier = GatewayTradeClockQualifier(
                self._projector._client, self._clock_verifier, **self._qualifier_options)
        with self._claim_lock:
            if name in claims and claims[name] is not feed:
                raise ValueError("GATEWAY_MARKET_SUBSCRIPTION_ALREADY_CLAIMED")
            claims[name] = feed

    def start(self):
        if self._clock_owned and not self._clock_started:
            self._clock_verifier.start_background_refresh(self._clock_interval)
            self._clock_started = True
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
        if self._pending_operation == "start":
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
        store = self._store
        if not store.is_connected:
            return False
        api = store.gateway_api
        config = store.gateway_strategy_config
        try:
            client = api.market_subscription(config.exchange_name, self._name)
            projector = GatewayMarketTickProjector(
                client, key=self._key, scope=WireScope(config.route.scope.execution_domain_ref),
                peer=config.peer, timeout_seconds=self._timeout_seconds)
            qualifier = None
            if self._qualifier_options is not None:
                from bt_api_py.clock_verification import GatewayTradeClockQualifier

                qualifier = GatewayTradeClockQualifier(client, self._clock_verifier,
                                                       **self._qualifier_options)
        except Exception:
            return False
        self._api, self._projector, self._qualifier = api, projector, qualifier
        self._reason, self._pending_operation = "STARTING", "start"
        self._attempt, self._next_retry = 0, 0.0
        return True

    def poll(self):
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
        if event is not self._last_event:
            return None
        return self._last_receipt

    def latest_realtime(self):
        """The latest real-time delivery pair; not itself trading authority."""
        if self._reason is not None:
            return None
        if self._latest_event is None or self._latest_receipt is None:
            return None
        return self._latest_event, self._latest_receipt

    def matches(self, store, feed, instrument):
        """Check the exact Store, Feed, subscription and complete instrument."""
        from bt_api_base.market_protocol import MarketInstrumentKey

        if type(instrument) is not MarketInstrumentKey:
            return False
        if store is not self._store or feed is not self._feed or instrument != self._key.instrument:
            return False
        try:
            with self._claim_lock:
                claimed = self._claims.get(self._name) is feed
            config = store.gateway_strategy_config
            selected = config.market_settings.subscriptions[self._name]
            return bool(claimed and store.gateway_api is self._api
                        and selected.key == self._key
                        and self._api.market_subscription(config.exchange_name, self._name)
                        is self._projector._client)
        except (AttributeError, KeyError, TypeError, RuntimeError, ValueError):
            return False

    def qualify_latest(self):
        """Run authenticated clock checks only at the order boundary."""
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
                return None
            key = self._key.to_dict()
            key["instrument"] = MappingProxyType(key["instrument"])
            reference = MappingProxyType({"key": MappingProxyType(key), "epoch": receipt.stream_epoch,
                                          "sequence": receipt.sequence, "message_id": receipt.message_id})
            return result, reference
        except Exception:
            return None
    def close(self):
        self._last_event = self._last_receipt = None
        self._latest_event = self._latest_receipt = None
        if self._clock_owned and self._clock_started:
            if not self._clock_verifier.stop_background_refresh(timeout_seconds=5):
                raise RuntimeError("GATEWAY_CLOCK_SHUTDOWN_PENDING")
            self._clock_started = False
        with self._claim_lock:
            if self._claims.get(self._name) is self._feed:
                # The SDK proxy has no per-subscription close/unsubscribe yet.
                # Prevent reuse of a stale bootstrap cursor; session shutdown
                # remains the owner of unsubscription.
                self._claims[self._name] = None
