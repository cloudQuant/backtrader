"""Unregistered, read-only Feed handoff for the managed CTP MD bridge.

This candidate consumes only an exact ``CtpSimNowManagedMdTickBridge``. The
bridge owns the lease/scope checks and validates each typed tick; this Feed
adds bounded receive/event-time expiry checks and maps one tick to one
Backtrader ``TimeFrame.Ticks`` line advance. It never creates a Store, Broker,
native client, subscription, strategy, or fallback bar. It does not establish
provider authenticity: the repository still has no accepted real MD source
adapter/provenance, so this module must remain outside the default 33-case
runner.

Strategies can read ``close``/``volume`` plus ``bid``, ``ask``, sizes,
``tick_sequence`` and ``connection_generation`` in their normal ``next``
callback. ``openinterest`` is NaN because the bridge carries no OI field.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import NoReturn

from backtrader.dataseries import TimeFrame
from backtrader.feed import DataBase
from backtrader_runtime.ctp_simnow_managed_md_bridge import (
    CtpSimNowManagedMdBridgeError,
    CtpSimNowManagedMdTickBridge,
    ManagedCtpMdSourceIdentity,
    ManagedCtpMdTick,
)

_MAX_RECEIVE_AGE_NS = 2_000_000_000
_MAX_EVENT_AGE_SECONDS = 5.0
_MAX_FUTURE_SKEW_SECONDS = 0.5
_MAX_QCHECK_SECONDS = 1.0


def _monotonic_ns() -> int:
    """Clock seam kept module-local so tests can replace it safely."""

    return time.monotonic_ns()


def _wall_time_seconds() -> float:
    """UTC epoch clock seam for normalized bridge event timestamps."""

    return time.time()


class CtpSimNowManagedMdFeedError(RuntimeError):
    """Redacted fail-closed error from the unregistered managed Feed candidate."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class CtpSimNowManagedMdTickFeedCandidate(DataBase):
    """One validated bridge tick per Backtrader strategy clock step.

    The caller must pass the already constructed bridge. Feed lifecycle methods
    do not start, stop, or retire it because the managed runtime owns the MD
    client and account lease. A source/lease/expiry fault is sticky and raises;
    no prior tick, seed bar, replay bar, or other provider is substituted.
    """

    lines = (
        "bid",
        "ask",
        "bidvolume",
        "askvolume",
        "tick_sequence",
        "connection_generation",
    )

    params = (
        ("bridge", None),
        ("max_receive_age_ns", _MAX_RECEIVE_AGE_NS),
        ("max_event_age_seconds", _MAX_EVENT_AGE_SECONDS),
        ("max_future_skew_seconds", _MAX_FUTURE_SKEW_SECONDS),
        ("timeframe", TimeFrame.Ticks),
        ("compression", 1),
        ("qcheck", 0.1),
    )

    def __init__(self) -> None:
        # ParamsMixin has already populated ``self.p`` before invoking this
        # constructor. Feed constructors must read declared parameters there:
        # the patched initializer intentionally consumes matching keywords.
        bridge = self.p.bridge
        if type(bridge) is not CtpSimNowManagedMdTickBridge:
            raise CtpSimNowManagedMdFeedError("validated_managed_md_bridge_required")
        try:
            identity = bridge.identity
        except CtpSimNowManagedMdBridgeError as exc:
            raise CtpSimNowManagedMdFeedError("managed_md_bridge_unavailable") from exc
        if type(identity) is not ManagedCtpMdSourceIdentity:
            raise CtpSimNowManagedMdFeedError("managed_md_identity_invalid")

        requested_name = self.p.dataname
        if requested_name is not None:
            if type(requested_name) is not str or requested_name != identity.instrument_id:
                raise CtpSimNowManagedMdFeedError("feed_instrument_scope_mismatch")
        if requested_name is None:
            self.p.dataname = identity.instrument_id
        super().__init__()

        if self._timeframe != TimeFrame.Ticks or self._compression != 1:
            raise CtpSimNowManagedMdFeedError("tick_timeframe_required")
        receive_age = self.p.max_receive_age_ns
        if type(receive_age) is not int or receive_age <= 0 or receive_age > _MAX_RECEIVE_AGE_NS:
            raise CtpSimNowManagedMdFeedError("receive_expiry_out_of_bounds")
        event_age = self.p.max_event_age_seconds
        if (
            type(event_age) not in (int, float)
            or not math.isfinite(float(event_age))
            or not 0 < float(event_age) <= _MAX_EVENT_AGE_SECONDS
        ):
            raise CtpSimNowManagedMdFeedError("event_expiry_out_of_bounds")
        future_skew = self.p.max_future_skew_seconds
        if (
            type(future_skew) not in (int, float)
            or not math.isfinite(float(future_skew))
            or not 0 <= float(future_skew) <= _MAX_FUTURE_SKEW_SECONDS
        ):
            raise CtpSimNowManagedMdFeedError("future_clock_tolerance_out_of_bounds")
        qcheck = self.p.qcheck
        if (
            type(qcheck) not in (int, float)
            or not math.isfinite(float(qcheck))
            or not 0 <= float(qcheck) <= _MAX_QCHECK_SECONDS
        ):
            raise CtpSimNowManagedMdFeedError("qcheck_out_of_bounds")

        self._bridge = bridge
        self._identity = identity
        self._max_receive_age_ns = receive_age
        self._max_event_age_seconds = float(event_age)
        self._max_future_skew_seconds = float(future_skew)
        self._last_sequence = identity.ready_tick_sequence
        self._last_event_timestamp = float(identity.ready_event_timestamp)
        self._last_received_monotonic_ns = identity.ready_received_monotonic_ns
        self._fault: str | None = None
        self._stopped = False
        self._live_announced = False

    def start(self) -> None:
        """Initialize local Feed buffers; do not touch bridge ownership."""

        if self._stopped:
            self._fail("managed_md_feed_cannot_restart")
        super().start()

    def stop(self) -> None:
        """Stop this Feed locally; the managed runtime retains bridge ownership."""

        self._stopped = True
        super().stop()

    def islive(self) -> bool:
        """Disable preload/runonce because each strategy step is one live tick."""

        return True

    def haslivedata(self) -> bool:
        """The bridge has no look-ahead queue; let the normal qcheck pace polling."""

        return False

    def _load(self) -> bool | None:
        if self._stopped:
            return False
        if self._fault is not None:
            self._raise_fault()

        try:
            tick = self._bridge.poll_tick()
        except CtpSimNowManagedMdBridgeError as exc:
            self.put_notification(self.DISCONNECTED)
            self._fail("managed_md_bridge_rejected")
            raise AssertionError("unreachable") from exc
        except Exception as exc:
            self._fail("managed_md_bridge_poll_failed")
            raise AssertionError("unreachable") from exc

        if tick is None:
            if self._qcheck > 0:
                time.sleep(self._qcheck)
            return None
        self._validate_fresh_tick(tick)
        self._write_tick_lines(tick)
        if not self._live_announced:
            self._live_announced = True
            self.put_notification(self.LIVE)
        return True

    def _validate_fresh_tick(self, tick: object) -> None:
        if type(tick) is not ManagedCtpMdTick:
            self._fail("managed_md_tick_type_invalid")
        assert isinstance(tick, ManagedCtpMdTick)
        if tick.identity != self._identity:
            self._fail("managed_md_tick_identity_changed")
        if (
            type(tick.sequence) is not int
            or tick.sequence <= self._last_sequence
            or type(tick.received_monotonic_ns) is not int
            or tick.received_monotonic_ns <= self._last_received_monotonic_ns
            or type(tick.event_timestamp) not in (int, float)
            or not math.isfinite(float(tick.event_timestamp))
            or float(tick.event_timestamp) < self._last_event_timestamp
        ):
            self._fail("managed_md_tick_clock_or_sequence_invalid")

        monotonic_now = _monotonic_ns()
        if (
            type(monotonic_now) is not int
            or monotonic_now < tick.received_monotonic_ns
            or monotonic_now - tick.received_monotonic_ns > self._max_receive_age_ns
        ):
            self._fail("managed_md_tick_receive_expired")

        wall_now = _wall_time_seconds()
        if type(wall_now) not in (int, float) or not math.isfinite(float(wall_now)):
            self._fail("managed_md_wall_clock_invalid")
        event_age = float(wall_now) - float(tick.event_timestamp)
        if event_age > self._max_event_age_seconds or event_age < -self._max_future_skew_seconds:
            self._fail("managed_md_tick_event_expired_or_future")

        self._last_sequence = tick.sequence
        self._last_event_timestamp = float(tick.event_timestamp)
        self._last_received_monotonic_ns = tick.received_monotonic_ns

    def _write_tick_lines(self, tick: ManagedCtpMdTick) -> None:
        try:
            tick_datetime = datetime.fromtimestamp(float(tick.event_timestamp), tz=timezone.utc)
            datetime_line = self.date2num(tick_datetime)
        except (OverflowError, OSError, ValueError) as exc:
            self._fail("managed_md_tick_timestamp_invalid")
            raise AssertionError("unreachable") from exc

        price = float(tick.last_price)
        self.lines.datetime[0] = datetime_line
        self.lines.open[0] = price
        self.lines.high[0] = price
        self.lines.low[0] = price
        self.lines.close[0] = price
        self.lines.volume[0] = float(tick.volume_delta)
        self.lines.openinterest[0] = float("nan")
        self.lines.bid[0] = float(tick.bid_price)
        self.lines.ask[0] = float(tick.ask_price)
        self.lines.bidvolume[0] = float(tick.bid_volume)
        self.lines.askvolume[0] = float(tick.ask_volume)
        self.lines.tick_sequence[0] = tick.sequence
        self.lines.connection_generation[0] = tick.identity.connection_generation

    def _fail(self, reason: str) -> NoReturn:
        if self._fault is None:
            self._fault = reason
        self._raise_fault()

    def _raise_fault(self) -> NoReturn:
        assert self._fault is not None
        raise CtpSimNowManagedMdFeedError(self._fault) from None


__all__ = [
    "CtpSimNowManagedMdFeedError",
    "CtpSimNowManagedMdTickFeedCandidate",
]
