"""Session health guard: turn "no data is arriving" into an alarm.

On 2026-09-17 the collector spent hours delivering almost nothing for the
commodity exchanges and still looked healthy, because the only progress signal
was a cumulative counter that kept creeping upwards.  This guard watches the
*rate* of data instead and raises an error when the feed stalls, or when
instruments that had been ticking go quiet in bulk.

The guard is deliberately pure: it takes samples and returns a verdict, so the
observed numbers from a real session can be replayed in tests.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_logger = logging.getLogger(__name__)

#: The reference set for the silence alarm is everything seen within this many
#: ``silent_after_sec`` windows.  Instruments that went quiet long ago are
#: simply not expected to tick any more, so counting them would make the share
#: meaningless late in the day.
_ACTIVE_WINDOW_FACTOR = 3.0


@dataclass(frozen=True)
class HealthThresholds:
    """When to alarm.

    Thresholds are per evaluation interval, i.e. per ``heartbeat_interval_sec``.
    """

    #: Fewer ticks than this in one interval counts as a stalled interval.
    min_ticks_per_interval: int = 1
    #: Consecutive stalled intervals before raising an alarm.  Two intervals
    #: avoids firing on a single unusually quiet minute.
    stall_intervals: int = 2
    #: How long a recently active instrument must be silent to count as silent.
    silent_after_sec: float = 300.0
    #: Share of recently active instruments that may be silent before alarming.
    silent_share_alarm: float = 0.8


@dataclass(frozen=True)
class HealthVerdict:
    """One interval's worth of evidence plus whatever alarms it triggered."""

    in_session: bool
    ticks_in_window: int
    active_instruments: int
    subscribed: int
    silent_active: int
    tracked_instruments: int
    max_silence_sec: float
    alarm_reasons: tuple[str, ...]

    @property
    def healthy(self) -> bool:
        return not self.alarm_reasons

    @property
    def silent_share(self) -> float:
        if not self.tracked_instruments:
            return 0.0
        return self.silent_active / self.tracked_instruments

    def describe(self) -> str:
        return (
            f"session={self.in_session} ticks={self.ticks_in_window} "
            f"active={self.active_instruments} subscribed={self.subscribed} "
            f"silent_active={self.silent_active}/{self.tracked_instruments} "
            f"max_silence={self.max_silence_sec:.0f}s"
        )


class CollectionHealthGuard:
    """Sample data arrival and decide whether collection is still healthy."""

    def __init__(self, thresholds: HealthThresholds | None = None) -> None:
        self._thresholds = thresholds or HealthThresholds()
        self._last_seen: dict[str, float] = {}
        self._ticks_in_window = 0
        self._active_in_window: set[str] = set()
        self._stalled_intervals = 0
        self._session: int | None = None
        self._session_known = False

    @property
    def thresholds(self) -> HealthThresholds:
        return self._thresholds

    def observe(self, ticks: Mapping[str, Sequence[Any]], *, now: float) -> None:
        """Record that these instruments produced data at ``now``."""
        for instrument_id, batch in ticks.items():
            if not batch:
                continue
            self._ticks_in_window += len(batch)
            self._active_in_window.add(instrument_id)
            self._last_seen[instrument_id] = now

    def evaluate(self, *, now: float, subscribed: int, session: int | None) -> HealthVerdict:
        """Judge the interval that just ended and reset the window.

        ``session`` is the session index the moment falls in (``None`` outside
        every session).  A session change clears what used to be active:
        instruments legitimately stop during a scheduled break, so remembering
        them would raise a silence alarm at every break.
        """
        if self._session_known and session != self._session:
            self._last_seen.clear()
        self._session = session
        self._session_known = True

        in_session = session is not None
        tracked, silent, max_silence = self._silent_stats(now)
        share = silent / tracked if tracked else 0.0
        reasons: list[str] = []

        if in_session:
            if self._ticks_in_window < self._thresholds.min_ticks_per_interval:
                self._stalled_intervals += 1
            else:
                self._stalled_intervals = 0
            if self._stalled_intervals >= self._thresholds.stall_intervals:
                reasons.append(
                    f"feed stalled: {self._stalled_intervals} consecutive intervals below "
                    f"{self._thresholds.min_ticks_per_interval} tick(s)"
                )
            if tracked and share >= self._thresholds.silent_share_alarm:
                reasons.append(
                    f"{silent}/{tracked} recently active instruments silent for more than "
                    f"{self._thresholds.silent_after_sec:.0f}s"
                )
        else:
            # 非交易时段静默是正常的，且不能让停摆计数跨时段累计。
            self._stalled_intervals = 0

        verdict = HealthVerdict(
            in_session=in_session,
            ticks_in_window=self._ticks_in_window,
            active_instruments=len(self._active_in_window),
            subscribed=int(subscribed),
            silent_active=silent,
            tracked_instruments=tracked,
            max_silence_sec=max_silence,
            alarm_reasons=tuple(reasons),
        )
        self._ticks_in_window = 0
        self._active_in_window = set()
        return verdict

    def _silent_stats(self, now: float) -> tuple[int, int, float]:
        """Return (tracked, silent, max silence) over the recent-activity window."""
        window_start = now - self._thresholds.silent_after_sec * _ACTIVE_WINDOW_FACTOR
        tracked = 0
        silent = 0
        max_silence = 0.0
        for last_seen in self._last_seen.values():
            if last_seen < window_start:
                continue
            tracked += 1
            silence = now - last_seen
            if silence > self._thresholds.silent_after_sec:
                silent += 1
                max_silence = max(max_silence, silence)
        return tracked, silent, max_silence


__all__ = ["CollectionHealthGuard", "HealthThresholds", "HealthVerdict"]
