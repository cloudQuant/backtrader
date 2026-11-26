"""Bounded, read-only MarketHub wire probe for the 007 CTP Gateway.

The probe uses the existing strict resource loader, cross-process identity
lease, Gateway market runtime, and SDK market client. Its public result is a
small aggregate only: no quote values, keys, endpoints, references, raw frames,
or exception text are returned or printed. Timestamp proximity is always
reported as unverified and never establishes execution eligibility.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


MAX_DURATION_SECONDS = 7 * 24 * 60 * 60
_MAX_POLL_TIMEOUT_MS = 1_000
_RECENT_AGE_SECONDS = 30.0
_AGE_CLASSES = (
    "STALE_OR_DELAYED_CANDIDATE",
    "RECENT_UNVERIFIED",
    "NOT_ASSESSED",
)
_FAILURE_CODES = frozenset(
    {
        "PROBE_LOCK_BUSY",
        "PROBE_SOURCE_UNAVAILABLE",
        "PROBE_CLOCK_INVALID",
        "PROBE_DURATION_INVALID",
        "MARKET_IDENTITY_INVALID",
        "MARKET_PROBE_OWNER_THREAD_MISMATCH",
        "MARKET_PROBE_ALREADY_STARTED",
        "MARKET_PROBE_NOT_STARTED",
        "MARKET_PROBE_DEPENDENCIES_UNAVAILABLE",
        "MARKET_PROBE_UNCERTAIN_SESSION_RETAINED",
        "MARKET_PROBE_CLEANUP_UNCERTAIN",
        "MARKET_PROBE_FAILED",
        "MARKET_RESOURCE_LOAD_FAILED",
        "MARKET_IDENTITY_LEASE_FAILED",
        "MARKET_RESOURCE_INVALID",
        "MARKET_RUNTIME_CREATE_FAILED",
        "MARKET_RUNTIME_START_FAILED",
        "MARKET_CLIENT_CREATE_FAILED",
        "MARKET_CLIENT_START_FAILED",
        "MARKET_BOOTSTRAP_INVALID",
        "MARKET_POLL_FAILED",
        "MARKET_STREAM_UNHEALTHY",
        "MARKET_UNSUBSCRIPTION_UNCERTAIN",
    }
)
_SIBLINGS: dict[str, ModuleType] = {}
_PROBE_LOCK = threading.Lock()
_UNCERTAIN_PROBES: list["_ProbeSession"] = []


class MarketProbeError(RuntimeError):
    """Value-free finite failure at the market-probe boundary."""

    def __init__(self, code: str):
        if type(code) is not str or not code.isascii() or not code.replace("_", "").isalnum():
            code = "MARKET_PROBE_FAILED"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MarketProbeSummary:
    probe_status: str
    cleanup_status: str
    failure_code: str | None
    valid_count: int
    rejected_count: int
    pub_count: int
    replay_count: int
    unknown_receipt_count: int
    sequence_gaps: int
    first_provider_event_time_utc: str | None
    last_provider_event_time_utc: str | None
    first_local_receive_time_utc: str | None
    last_local_receive_time_utc: str | None
    age_classification_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if self.failure_code is not None and (
            type(self.failure_code) is not str
            or not self.failure_code.isascii()
            or self.failure_code not in _FAILURE_CODES
        ):
            object.__setattr__(self, "failure_code", "MARKET_PROBE_FAILED")

    def to_dict(self) -> dict[str, Any]:
        """Return the exact allowlisted, value-free summary shape."""
        return {
            "probe_status": self.probe_status,
            "cleanup_status": self.cleanup_status,
            "failure_code": self.failure_code,
            "valid_count": self.valid_count,
            "rejected_count": self.rejected_count,
            "pub_count": self.pub_count,
            "replay_count": self.replay_count,
            "unknown_receipt_count": self.unknown_receipt_count,
            "sequence_gaps": self.sequence_gaps,
            "first_provider_event_time_utc": self.first_provider_event_time_utc,
            "last_provider_event_time_utc": self.last_provider_event_time_utc,
            "first_local_receive_time_utc": self.first_local_receive_time_utc,
            "last_local_receive_time_utc": self.last_local_receive_time_utc,
            "age_classification_counts": dict(self.age_classification_counts),
        }


class _SummaryBuilder:
    def __init__(self) -> None:
        self.probe_status = "failed"
        self.cleanup_status = "not_started"
        self.failure_code: str | None = None
        self.valid_count = 0
        self.rejected_count = 0
        self.pub_count = 0
        self.replay_count = 0
        self.unknown_receipt_count = 0
        self.sequence_gaps = 0
        self.first_provider_event_time_utc: str | None = None
        self.last_provider_event_time_utc: str | None = None
        self.first_local_receive_time_utc: str | None = None
        self.last_local_receive_time_utc: str | None = None
        self.age_classification_counts = {name: 0 for name in _AGE_CLASSES}

    def freeze(self) -> MarketProbeSummary:
        return MarketProbeSummary(
            probe_status=self.probe_status,
            cleanup_status=self.cleanup_status,
            failure_code=self.failure_code,
            valid_count=self.valid_count,
            rejected_count=self.rejected_count,
            pub_count=self.pub_count,
            replay_count=self.replay_count,
            unknown_receipt_count=self.unknown_receipt_count,
            sequence_gaps=self.sequence_gaps,
            first_provider_event_time_utc=self.first_provider_event_time_utc,
            last_provider_event_time_utc=self.last_provider_event_time_utc,
            first_local_receive_time_utc=self.first_local_receive_time_utc,
            last_local_receive_time_utc=self.last_local_receive_time_utc,
            age_classification_counts=tuple(
                (name, self.age_classification_counts[name]) for name in _AGE_CLASSES
            ),
        )


def _load_sibling(name: str) -> ModuleType:
    module = _SIBLINGS.get(name)
    if module is not None:
        return module
    if name not in {"market_only_resources"}:
        raise MarketProbeError("PROBE_SOURCE_UNAVAILABLE")
    path = Path(__file__).resolve().with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_market_only_probe_{name}", path)
    if spec is None or spec.loader is None:
        raise MarketProbeError("PROBE_SOURCE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _SIBLINGS[name] = module
    return module


@dataclass(frozen=True, repr=False)
class _ProbeDependencies:
    resources: ModuleType
    runtime_factory: Callable[..., Any]
    client_factory: Callable[..., Any]


def preflight_market_probe_dependencies() -> _ProbeDependencies:
    """Load and bind the default import path without opening resources or sockets.

    This deliberately runs before ``load_market_connection`` reads any key
    bytes. It imports the strategy-side SDK/Base/transport composition used by
    the default runtime and MarketHub client, but creates no runtime, client,
    transport, provider, or network operation. The native CTP provider remains
    in the separate Gateway process and is not imported into the probe.
    """
    try:
        import zmq
        from zmq.utils import z85

        from bt_api_base import account_protocol, market_history_protocol
        from bt_api_base.market_protocol import (
            MARKET_EVENT_OPERATION,
            MARKET_EVENT_SCHEMA,
            MARKET_EVENT_SCHEMA_VERSION,
            MarketInstrumentKey,
            MarketSourceDescriptor,
            MarketSubscriptionKey,
        )
        from bt_api_base.market_tick_protocol import (
            MarketEventCursor,
            bind_market_tick_event,
            market_tick_payload_from_wire,
        )
        from bt_api_base.service_protocol import (
            WIRE_PROTOCOL_VERSION,
            WireEnvelope,
            WireHeader,
            WireIdentity,
            WireMessageKind,
            WireRole,
            WireScope,
        )
        from bt_api_gateway import account_process
        from bt_api_py.ctp_account_process import CTP_MARKET_TICK_CHANNEL
        from bt_api_py.ctp_gateway_composition import (
            GatewayClientConnection,
            create_gateway_market_runtime,
            ctp_gateway_instrument_key,
            gateway_market_check_client,
        )
        from bt_api_py.gateway_market_runtime import GatewayMarketTickRuntimeFactory
        from bt_api_py.service_config import parse_client_config
        from bt_api_py.service_market import (
            MarketBootstrap,
            MarketReceiveReceipt,
            ServiceMarketClient,
            ZmqMarketTransportFactory,
        )
        from bt_api_py.service_runtime import (
            ClientCurveKeys,
            ServiceClientRuntime,
            ZmqTransportFactory,
        )
        from bt_api_transport_zmq.market_v2 import (
            MarketFrameReceipt,
            ZmqMarketContextPool,
            ZmqMarketSubscriber,
        )
        from bt_api_transport_zmq.server import CurveClientCredentials
        from bt_api_transport_zmq.service_v2 import ServiceReplyReceipt, ZmqServiceClient

        from bt_api_py.ctp_account_process import (
            CTP_SIMNOW_MARKET_ENVIRONMENT,
            ctp_simnow_gateway_refs,
        )

        # The strict resource loader checks these modules before reading key
        # bytes. Load them here too, so the default loader does no first import
        # after it begins resource validation.
        if os.name == "nt":
            from bt_api_py import _win32_security

            del _win32_security

        # Bind the otherwise lazy imports used in the later default calls.
        del (
            zmq,
            z85,
            account_protocol,
            market_history_protocol,
            MARKET_EVENT_OPERATION,
            MARKET_EVENT_SCHEMA,
            MARKET_EVENT_SCHEMA_VERSION,
            MarketInstrumentKey,
            MarketSourceDescriptor,
            MarketSubscriptionKey,
            MarketEventCursor,
            bind_market_tick_event,
            market_tick_payload_from_wire,
            WIRE_PROTOCOL_VERSION,
            WireEnvelope,
            WireHeader,
            WireIdentity,
            WireMessageKind,
            WireRole,
            WireScope,
            account_process,
            CTP_MARKET_TICK_CHANNEL,
            CTP_SIMNOW_MARKET_ENVIRONMENT,
            ctp_simnow_gateway_refs,
            GatewayClientConnection,
            GatewayMarketTickRuntimeFactory,
            ctp_gateway_instrument_key,
            parse_client_config,
            MarketBootstrap,
            MarketReceiveReceipt,
            ServiceMarketClient,
            ZmqMarketTransportFactory,
            ClientCurveKeys,
            ServiceClientRuntime,
            ZmqTransportFactory,
            MarketFrameReceipt,
            ZmqMarketContextPool,
            ZmqMarketSubscriber,
            CurveClientCredentials,
            ServiceReplyReceipt,
            ZmqServiceClient,
        )
        resources = _load_sibling("market_only_resources")
        # The strict loader imports this public helper before reading private
        # key material. Warm it during preflight so all default-loader source
        # dependencies are resolved at this boundary.
        resources._local_resource_module()
        return _ProbeDependencies(
            resources=resources,
            runtime_factory=create_gateway_market_runtime,
            client_factory=gateway_market_check_client,
        )
    except Exception:
        raise MarketProbeError("MARKET_PROBE_DEPENDENCIES_UNAVAILABLE") from None


def _is_valid_text(value: Any, *, limit: int = 128) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= limit
        and value == value.strip()
        and value.isprintable()
    )


def _utc_datetime(value: Any) -> datetime | None:
    if type(value) is not datetime or value.tzinfo is None:
        return None
    try:
        if value.utcoffset() != timedelta(0):
            return None
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None


def _utc_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _event_time(value: Any) -> datetime | None:
    if type(value) is not str:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _utc_datetime(parsed)


def _age_classification(
    provider_time: datetime | None,
    local_receive_time: datetime | None,
) -> str:
    if provider_time is None or local_receive_time is None:
        return "NOT_ASSESSED"
    age_seconds = (local_receive_time - provider_time).total_seconds()
    if not math.isfinite(age_seconds) or age_seconds < 0:
        return "NOT_ASSESSED"
    if age_seconds > _RECENT_AGE_SECONDS:
        return "STALE_OR_DELAYED_CANDIDATE"
    # Proximity between two clocks is only a candidate; UNKNOWN/UNAVAILABLE
    # clock and execution fields never become a FRESH qualification here.
    return "RECENT_UNVERIFIED"


class MarketHubProbe:
    """Validate one SDK MarketHub subscription without exposing quote facts."""

    def __init__(
        self,
        client: Any,
        *,
        symbol: str,
        venue: str,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not _is_valid_text(symbol) or not _is_valid_text(venue):
            raise MarketProbeError("MARKET_IDENTITY_INVALID")
        if not callable(monotonic_clock):
            raise MarketProbeError("PROBE_CLOCK_INVALID")
        self._client = client
        self._symbol = symbol
        self._venue = venue
        self._monotonic = monotonic_clock
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._owner_thread = threading.get_ident()
        self._summary = _SummaryBuilder()
        self._source = None
        self._last_sequence: int | None = None
        self._started = False
        self.client_start_failed = False

    def _assert_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise MarketProbeError("MARKET_PROBE_OWNER_THREAD_MISMATCH")

    def start(self) -> None:
        self._assert_owner()
        if self._started:
            raise MarketProbeError("MARKET_PROBE_ALREADY_STARTED")
        from bt_api_base.market_protocol import MarketSourceDescriptor, MarketSubscriptionKey
        from bt_api_py.ctp_account_process import CTP_MARKET_TICK_CHANNEL
        from bt_api_py.service_market import MarketBootstrap

        try:
            key = self._client.key
            try:
                bootstrap = self._client.start()
            except Exception:
                self.client_start_failed = True
                raise
            source = bootstrap.source_descriptor
            if (
                type(key) is not MarketSubscriptionKey
                or key.instrument.native_symbol != self._symbol
                or key.instrument.venue != self._venue
                or key.channel != CTP_MARKET_TICK_CHANNEL
                or type(bootstrap) is not MarketBootstrap
                or type(source) is not MarketSourceDescriptor
                or source.key != key
                or source.stream_id != key.stream_id
                or bootstrap.stream_id != source.stream_id
                or bootstrap.snapshot_epoch != source.epoch
                or bootstrap.cursor_epoch != source.epoch
                or type(bootstrap.snapshot_sequence) is not int
                or bootstrap.snapshot_sequence < 0
                or type(bootstrap.cursor_sequence) is not int
                or bootstrap.cursor_sequence != bootstrap.snapshot_sequence
                or bootstrap.resync_required
                or bootstrap.snapshot_complete
                or bootstrap.full_baseline_available
                or bootstrap.snapshot_kind != "latest_event"
            ):
                raise ValueError
        except MarketProbeError:
            raise
        except Exception:
            raise MarketProbeError("MARKET_BOOTSTRAP_INVALID") from None
        self._source = source
        self._last_sequence = bootstrap.snapshot_sequence
        self._started = True
        if bootstrap.snapshot is not None:
            # The bootstrap snapshot has no local pub/replay receipt. Count it
            # as unknown receipt evidence and validate its exact cursor.
            self._consume(bootstrap.snapshot, None, snapshot=True)

    def poll_for(self, duration_seconds: int) -> MarketProbeSummary:
        self._assert_owner()
        if not self._started or self._source is None or self._last_sequence is None:
            raise MarketProbeError("MARKET_PROBE_NOT_STARTED")
        if type(duration_seconds) is not int or not 1 <= duration_seconds <= MAX_DURATION_SECONDS:
            raise MarketProbeError("PROBE_DURATION_INVALID")
        deadline = self._monotonic() + duration_seconds
        while True:
            self._assert_owner()
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                break
            timeout_ms = max(1, min(_MAX_POLL_TIMEOUT_MS, math.ceil(remaining * 1000)))
            try:
                delivery = self._client.poll_with_receipt(timeout_ms=timeout_ms)
            except Exception:
                raise MarketProbeError("MARKET_POLL_FAILED") from None
            if delivery is None:
                if (
                    getattr(self._client, "healthy", True) is not True
                    or getattr(self._client, "recovery_required", False) is True
                ):
                    raise MarketProbeError("MARKET_STREAM_UNHEALTHY")
                continue
            if type(delivery) is not tuple or len(delivery) != 2:
                self._summary.unknown_receipt_count += 1
                self._summary.rejected_count += 1
                continue
            frame, receipt = delivery
            self._consume(frame, receipt, snapshot=False)
        self._summary.probe_status = "complete"
        return self._summary.freeze()

    def _receipt_class(self, frame: Any, receipt: Any) -> tuple[str, bool]:
        from bt_api_base.service_protocol import WireEnvelope
        from bt_api_py.service_market import MarketReceiveReceipt

        try:
            if type(frame) is not WireEnvelope or type(receipt) is not MarketReceiveReceipt:
                return "unknown", False
            header = frame.header
            if (
                self._source is None
                or header.stream_id != self._source.stream_id
                or header.stream_epoch != self._source.epoch
                or type(header.sequence) is not int
                or receipt.stream_id != header.stream_id
                or receipt.stream_epoch != header.stream_epoch
                or type(receipt.sequence) is not int
                or receipt.sequence != header.sequence
                or receipt.message_id != header.message_id
                or type(receipt.received_wall_ns) is not int
                or receipt.received_wall_ns <= 0
                or type(receipt.received_monotonic_ns) is not int
                or receipt.received_monotonic_ns <= 0
                or type(receipt.pid) is not int
                or receipt.pid != os.getpid()
                or type(receipt.thread_id) is not int
                or receipt.thread_id != self._owner_thread
            ):
                return "unknown", False
            if receipt.source == "pub" and receipt.request_message_id is None and receipt.reply_message_id is None:
                return "pub", True
            if (
                receipt.source == "replay"
                and _is_valid_text(receipt.request_message_id, limit=256)
                and _is_valid_text(receipt.reply_message_id, limit=256)
            ):
                return "replay", True
            return "unknown", False
        except Exception:
            return "unknown", False

    def _wall_time_for(self, receipt_valid: bool, receipt: Any) -> datetime | None:
        if receipt_valid:
            try:
                seconds, nanos = divmod(receipt.received_wall_ns, 1_000_000_000)
                return datetime.fromtimestamp(seconds, timezone.utc).replace(
                    microsecond=nanos // 1_000
                )
            except (OverflowError, OSError, ValueError):
                pass
        try:
            return _utc_datetime(self._wall_clock())
        except Exception:
            return None

    def _consume(self, frame: Any, receipt: Any, *, snapshot: bool) -> None:
        self._assert_owner()
        from bt_api_base.market_protocol import (
            MARKET_EVENT_OPERATION,
            MARKET_EVENT_SCHEMA,
            MARKET_EVENT_SCHEMA_VERSION,
            MarketSubscriptionKey,
        )
        from bt_api_base.market_tick_protocol import (
            MarketEventCursor,
            bind_market_tick_event,
            market_tick_payload_from_wire,
        )
        from bt_api_base.service_protocol import (
            WIRE_PROTOCOL_VERSION,
            WireEnvelope,
            WireMessageKind,
            WireRole,
        )

        receipt_kind, receipt_valid = self._receipt_class(frame, receipt)
        if receipt_kind == "pub":
            self._summary.pub_count += 1
        elif receipt_kind == "replay":
            self._summary.replay_count += 1
        else:
            self._summary.unknown_receipt_count += 1

        try:
            if type(frame) is not WireEnvelope or self._source is None or self._last_sequence is None:
                raise ValueError
            header = frame.header
            if (
                header.protocol_version != WIRE_PROTOCOL_VERSION
                or header.kind is not WireMessageKind.EVENT
                or header.identity.role is not WireRole.SERVICE
                or header.correlation_id is not None
                or header.owner_epoch is not None
                or header.stream_id != self._source.stream_id
                or header.stream_epoch != self._source.epoch
                or type(header.sequence) is not int
                or header.sequence < 1
            ):
                raise ValueError
            if snapshot:
                if header.sequence != self._last_sequence:
                    raise ValueError
            else:
                expected_sequence = self._last_sequence + 1
                if header.sequence > expected_sequence:
                    self._summary.sequence_gaps += header.sequence - expected_sequence
                    # The SDK client has consumed this cursor. Advance the
                    # probe cursor while rejecting the discontinuous frame.
                    self._last_sequence = header.sequence
                    raise ValueError
                if header.sequence != expected_sequence:
                    raise ValueError
                # Keep the next probe expectation aligned even if this frame's
                # operation, key or DTO is malformed.
                self._last_sequence = header.sequence

            if (
                header.operation != MARKET_EVENT_OPERATION
                or header.schema_id != MARKET_EVENT_SCHEMA
                or header.schema_version != MARKET_EVENT_SCHEMA_VERSION
            ):
                raise ValueError
            envelope_payload = frame.payload
            if not isinstance(envelope_payload, Mapping) or set(envelope_payload) != {"key", "data"}:
                raise ValueError
            raw_key = envelope_payload["key"]
            if not isinstance(raw_key, Mapping):
                raise ValueError
            key = MarketSubscriptionKey.from_dict(raw_key)
            if key != self._client.key:
                raise ValueError
            payload = market_tick_payload_from_wire(envelope_payload["data"])
            cursor = MarketEventCursor(header.stream_id, header.stream_epoch, header.sequence)
            bind_market_tick_event(payload, self._source, cursor)
            provider_time = _event_time(payload.provider_event_time_utc)
            local_time = self._wall_time_for(receipt_valid, receipt)
        except Exception:
            self._summary.rejected_count += 1
            return

        self._summary.valid_count += 1
        provider_text = _utc_text(provider_time)
        local_text = _utc_text(local_time)
        if provider_text is not None:
            if self._summary.first_provider_event_time_utc is None:
                self._summary.first_provider_event_time_utc = provider_text
            self._summary.last_provider_event_time_utc = provider_text
        if local_text is not None:
            if self._summary.first_local_receive_time_utc is None:
                self._summary.first_local_receive_time_utc = local_text
            self._summary.last_local_receive_time_utc = local_text
        age = _age_classification(provider_time, local_time)
        self._summary.age_classification_counts[age] += 1


class _ProbeSession:
    """Owner-thread client/runtime/lease cleanup with sticky uncertainty."""

    def __init__(self) -> None:
        self.owner_thread = threading.get_ident()
        self.client: Any = None
        self.runtime: Any = None
        self.runtime_factory_object: Any = None
        self.lease: Any = None
        self.retained_objects: list[Any] = []
        self.uncertainty_hint = False
        self.cleanup_failure_code: str | None = None
        self.closed = False

    def _assert_owner(self) -> None:
        if threading.get_ident() != self.owner_thread:
            raise MarketProbeError("MARKET_PROBE_OWNER_THREAD_MISMATCH")

    def retain_uncertain(self) -> None:
        self.uncertainty_hint = True
        if self.lease is not None:
            try:
                if getattr(self.lease, "active", False) or getattr(self.lease, "held", False):
                    self.lease.mark_uncertain()
            except Exception:
                pass
        if self not in _UNCERTAIN_PROBES:
            _UNCERTAIN_PROBES.append(self)

    def close_once(self) -> bool:
        if self.closed:
            return True
        try:
            self._assert_owner()
            if self.uncertainty_hint:
                raise MarketProbeError("MARKET_PROBE_CLEANUP_UNCERTAIN")
            if self.client is not None:
                self.client.close()
            if self.runtime is not None:
                self.runtime.close()
            if self.lease is not None:
                if getattr(self.lease, "retained", False):
                    raise MarketProbeError("MARKET_PROBE_CLEANUP_UNCERTAIN")
                if getattr(self.lease, "active", False):
                    self.lease.clear_active_marker()
                    self.lease.release_clean()
                else:
                    self.lease.release_unstarted()
            self.closed = True
            return True
        except Exception as error:
            if getattr(error, "code", None) == "UNSUBSCRIPTION_UNCERTAIN":
                self.cleanup_failure_code = "MARKET_UNSUBSCRIPTION_UNCERTAIN"
            else:
                self.cleanup_failure_code = "MARKET_PROBE_CLEANUP_UNCERTAIN"
            self.retain_uncertain()
            return False


def _validate_probe_inputs(symbol: str, venue: str, duration_seconds: int) -> None:
    if not _is_valid_text(symbol) or not _is_valid_text(venue):
        raise MarketProbeError("MARKET_IDENTITY_INVALID")
    if type(duration_seconds) is not int or not 1 <= duration_seconds <= MAX_DURATION_SECONDS:
        raise MarketProbeError("PROBE_DURATION_INVALID")


def run_market_probe(
    resource_root: str | os.PathLike[str],
    *,
    symbol: str,
    venue: str,
    duration_seconds: int,
    resource_loader: Callable[..., Any] | None = None,
    lease_factory: Callable[[], Any] | None = None,
    runtime_factory: Callable[..., Any] | None = None,
    client_factory: Callable[..., Any] | None = None,
    monotonic_clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], datetime] | None = None,
) -> MarketProbeSummary:
    """Load one protected connection and observe one finite MarketHub stream.

    The injectable callables exist for source-fake tests. Production defaults
    reuse ``market_only_resources`` and the SDK CTP Gateway MarketHub APIs.
    """
    _validate_probe_inputs(symbol, venue, duration_seconds)
    summary = _SummaryBuilder()
    if not _PROBE_LOCK.acquire(blocking=False):
        if _UNCERTAIN_PROBES:
            summary.cleanup_status = "uncertain"
            summary.failure_code = "MARKET_PROBE_UNCERTAIN_SESSION_RETAINED"
        else:
            summary.failure_code = "PROBE_LOCK_BUSY"
        return summary.freeze()
    # Recheck under the latch. A prior cleanup uncertainty must never be
    # hidden by a race between the initial observation and lock acquisition.
    if _UNCERTAIN_PROBES:
        summary.cleanup_status = "uncertain"
        summary.failure_code = "MARKET_PROBE_UNCERTAIN_SESSION_RETAINED"
        # Keep the just-acquired latch held while retained objects exist.
        return summary.freeze()
    release_latch = True
    session = _ProbeSession()
    probe: MarketHubProbe | None = None
    stage = "dependency_preflight"
    try:
        dependencies = None
        if (
            resource_loader is None
            or lease_factory is None
            or runtime_factory is None
            or client_factory is None
        ):
            # This is deliberately before the strict resource loader. It
            # resolves the default SDK/Base/transport imports before any
            # protected key file can be opened.
            dependencies = preflight_market_probe_dependencies()
        resources = dependencies.resources if dependencies is not None else None
        if resource_loader is None:
            resource_loader = resources.load_market_connection
        if lease_factory is None:
            lease_factory = resources.GlobalMarketIdentityLease
        if runtime_factory is None:
            runtime_factory = dependencies.runtime_factory
        if client_factory is None:
            client_factory = dependencies.client_factory

        stage = "identity_lease"
        try:
            session.lease = lease_factory()
            session.lease.acquire()
        except Exception:
            raise MarketProbeError("MARKET_IDENTITY_LEASE_FAILED") from None

        stage = "resource_load"
        try:
            loaded = resource_loader(resource_root)
            generation_id = loaded.generation_id
            connection = loaded.connection
        except Exception:
            raise MarketProbeError("MARKET_RESOURCE_LOAD_FAILED") from None
        if not _is_valid_text(generation_id):
            raise MarketProbeError("MARKET_RESOURCE_INVALID")

        stage = "identity_lease"
        try:
            session.lease.mark_active(generation_id=generation_id, run_id=uuid.uuid4().hex)
        except Exception:
            session.uncertainty_hint = True
            raise MarketProbeError("MARKET_IDENTITY_LEASE_FAILED") from None

        stage = "runtime_create"
        try:
            session.runtime, session.runtime_factory_object = runtime_factory(
                connection, start=False
            )
        except Exception:
            raise MarketProbeError("MARKET_RUNTIME_CREATE_FAILED") from None

        stage = "runtime_start"
        try:
            session.runtime.start()
        except Exception:
            # SDK runtime startup already rolls back acquired transports. Do
            # not issue another close/unregister after an uncertain startup.
            session.uncertainty_hint = True
            raise MarketProbeError("MARKET_RUNTIME_START_FAILED") from None

        stage = "client_create"
        try:
            session.client = client_factory(session.runtime, connection, symbol, venue)
        except Exception:
            raise MarketProbeError("MARKET_CLIENT_CREATE_FAILED") from None
        probe = MarketHubProbe(
            session.client,
            symbol=symbol,
            venue=venue,
            monotonic_clock=monotonic_clock,
            wall_clock=wall_clock,
        )
        probe._summary = summary
        stage = "client_start"
        probe.start()
        stage = "poll"
        probe.poll_for(duration_seconds)
    except Exception as error:
        if probe is not None and probe.client_start_failed:
            # ServiceMarketClient.start performs its own failure cleanup.
            # Preserve its exact client/runtime rather than repeating it.
            session.uncertainty_hint = True
            summary.failure_code = "MARKET_CLIENT_START_FAILED"
        elif type(error) is MarketProbeError and error.code in _FAILURE_CODES:
            summary.failure_code = error.code
        else:
            summary.failure_code = {
                "dependency_preflight": "MARKET_PROBE_DEPENDENCIES_UNAVAILABLE",
                "identity_lease": "MARKET_IDENTITY_LEASE_FAILED",
                "resource_load": "MARKET_RESOURCE_LOAD_FAILED",
                "runtime_create": "MARKET_RUNTIME_CREATE_FAILED",
                "runtime_start": "MARKET_RUNTIME_START_FAILED",
                "client_create": "MARKET_CLIENT_CREATE_FAILED",
                "client_start": "MARKET_BOOTSTRAP_INVALID",
                "poll": "MARKET_PROBE_FAILED",
            }.get(stage, "MARKET_PROBE_FAILED")
        # Startup adapters may return a retained transport when cleanup is
        # uncertain. Preserve that exact object; do not retry or close it here.
        try:
            retained_transport = vars(error).get("transport")
        except Exception:
            retained_transport = None
        if retained_transport is not None:
            session.retained_objects.append(retained_transport)
            session.uncertainty_hint = True
    finally:
        if session.close_once():
            summary.cleanup_status = "clean"
        else:
            summary.probe_status = "failed"
            summary.cleanup_status = "uncertain"
            if summary.failure_code is None:
                summary.failure_code = (
                    session.cleanup_failure_code or "MARKET_PROBE_CLEANUP_UNCERTAIN"
                )
            release_latch = False
        if release_latch:
            _PROBE_LOCK.release()
    return summary.freeze()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded read-only 007 CTP MarketHub wire probe.")
    parser.add_argument("--resource-root", required=True, help="absolute owner-only generation directory")
    parser.add_argument("--symbol", required=True, help="one CTP native instrument symbol")
    parser.add_argument("--venue", required=True, help="one CTP venue")
    parser.add_argument("--duration-seconds", required=True, type=int, help="finite duration (1..604800)")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    probe: Callable[..., MarketProbeSummary] = run_market_probe,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        _validate_probe_inputs(args.symbol, args.venue, args.duration_seconds)
    except MarketProbeError:
        parser.error("invalid bounded probe arguments")
    result = probe(
        args.resource_root,
        symbol=args.symbol,
        venue=args.venue,
        duration_seconds=args.duration_seconds,
    )
    print(json.dumps(result.to_dict(), sort_keys=True, separators=(",", ":")))
    return 0 if result.probe_status == "complete" and result.cleanup_status == "clean" else 2


if __name__ == "__main__":  # pragma: no cover - command-line boundary
    raise SystemExit(main())
