"""Bounded synthetic facts and an actual no-bar Cerebro feed for MF-T1.

Every object in this module is local evidence.  The provider is intentionally
read-only and marks its scope, mapping, clock, and execution facts synthetic.
It is suitable for deterministic projection tests only.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

import backtrader as bt

try:
    from .execution_timing import (
        ClockMapping,
        ClockObservation,
        ExecutionFacts,
        MinuteInput,
        ScopeIdentity,
    )
except ImportError:  # Direct execution through this directory's run.py.
    from execution_timing import (
        ClockMapping,
        ClockObservation,
        ExecutionFacts,
        MinuteInput,
        ScopeIdentity,
    )

UTC = timezone.utc
FIXTURE_BASE = datetime(2026, 9, 11, 9, 30, tzinfo=UTC)


class FixtureExhausted(RuntimeError):
    """Raised instead of silently inventing a clock or execution fact."""


def _clock_for(scope: ScopeIdentity, mapping: ClockMapping, monotonic_ns: int) -> ClockObservation:
    wall = mapping.anchor_wall_utc + timedelta(microseconds=monotonic_ns / 1000)
    return ClockObservation(
        monotonic_ns=monotonic_ns,
        wall_utc=wall,
        clock_domain=scope.clock_domain,
        mapping=mapping,
        scope=scope,
        source="mf-t1-explicit-synthetic-clock",
        trusted=True,
        synthetic=True,
    )


class TimingFixtureProvider:
    """A finite, explicit provider consumed by the strategy callbacks."""

    def __init__(
        self,
        *,
        scope: ScopeIdentity,
        mapping: ClockMapping,
        minute: MinuteInput | Sequence[MinuteInput],
        facts: ExecutionFacts,
        next_clock_ns: int | Sequence[int],
        idle_clock_ns: Sequence[int],
    ) -> None:
        if not scope.synthetic or not mapping.synthetic or facts.source_kind != "synthetic":
            raise ValueError("TimingFixtureProvider only accepts explicitly synthetic evidence")
        self.scope = scope
        self.mapping = mapping
        self._minutes = (minute,) if isinstance(minute, MinuteInput) else tuple(minute)
        if not self._minutes or any(item.scope != scope for item in self._minutes):
            raise ValueError("fixture must expose at least one minute in the same scope")
        self.minute = self._minutes[0]
        self._facts = facts
        self._next_clock_ns = (
            (next_clock_ns,) if isinstance(next_clock_ns, int) else tuple(next_clock_ns)
        )
        if len(self._next_clock_ns) != len(self._minutes):
            raise ValueError("each fixture minute needs one explicit next clock")
        self._idle_clock_ns = tuple(idle_clock_ns)
        self._next_index = 0
        self._idle_index = 0
        self.next_calls = 0
        self.idle_calls = 0

    @property
    def idle_count(self) -> int:
        return len(self._idle_clock_ns)

    def next_minute(self) -> MinuteInput:
        self.next_calls += 1
        if self._next_index >= len(self._minutes):
            raise FixtureExhausted("the fixture exposes one closed minute")
        minute = self._minutes[self._next_index]
        self._next_index += 1
        return minute

    def execution_facts(self) -> ExecutionFacts:
        return self._facts

    def clock_for_next(self) -> ClockObservation:
        if self._next_index == 0:
            raise FixtureExhausted("clock requested before a minute")
        return _clock_for(self.scope, self.mapping, self._next_clock_ns[self._next_index - 1])

    def clock_for_idle(self) -> ClockObservation:
        if self._idle_index >= len(self._idle_clock_ns):
            raise FixtureExhausted("no implicit idle clock values are permitted")
        monotonic_ns = self._idle_clock_ns[self._idle_index]
        self._idle_index += 1
        self.idle_calls += 1
        return _clock_for(self.scope, self.mapping, monotonic_ns)


class TimingFixtureFeed(bt.feed.DataBase):
    """One live-like bar, then explicit no-bar polls, then end of source."""

    params = (("qcheck", 0.0),)

    def __init__(
        self,
        *,
        timestamp: datetime = FIXTURE_BASE,
        idle_polls: int = 2,
        bar_count: int = 1,
    ) -> None:
        super().__init__()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if type(idle_polls) is not int or idle_polls < 1:
            raise ValueError("idle_polls must be a positive integer")
        if type(bar_count) is not int or bar_count < 1:
            raise ValueError("bar_count must be a positive integer")
        self._timestamp = timestamp.astimezone(UTC)
        self._bar_count = bar_count
        self._bar_index = 0
        self._idle_remaining = idle_polls
        self._sent_bar = False
        self.idle_returns = 0

    def islive(self) -> bool:
        return True

    def haslivedata(self) -> bool:
        return True

    def _load(self) -> Optional[bool]:
        if self._bar_index < self._bar_count:
            value = bt.date2num(self._timestamp + timedelta(minutes=self._bar_index))
            for line in (self.lines.datetime,):
                line[0] = value
            for line in (self.lines.open, self.lines.high, self.lines.low, self.lines.close):
                line[0] = 100.0
            self.lines.volume[0] = 1.0
            self.lines.openinterest[0] = 0.0
            self._bar_index += 1
            return True
        if self._idle_remaining:
            self._idle_remaining -= 1
            self.idle_returns += 1
            return None
        return False


def build_timing_fixture() -> TimingFixtureProvider:
    """Build the explicit local positive timeline used by ``run.py``."""

    scope = ScopeIdentity(
        candidate_id="ctp-options-midfreq-local-fixture-v1",
        basket_id="synthetic-basket-1",
        account_fingerprint="synthetic-account",
        trading_day="20260911",
        session_segment="day-1",
        generation=7,
        rules_hash="local-fixture-rules-v1",
        clock_domain="mf-t1-synthetic-clock",
        mapping_id="mf-t1-synthetic-mapping-v1",
        source="mf-t1-explicit-synthetic-scope",
        synthetic=True,
    )
    mapping = ClockMapping(
        mapping_id=scope.mapping_id,
        anchor_wall_utc=FIXTURE_BASE,
        anchor_monotonic_ns=0,
        clock_domain=scope.clock_domain,
        generation=scope.generation,
        source="mf-t1-explicit-synthetic-anchor",
        error_bound_ns=1_000,
        valid_until_ns=2_000_000_000_000,
        rules_hash=scope.rules_hash,
        synthetic=True,
    )
    minute = MinuteInput(
        minute_id="MFT1-0931",
        bucket_start_ns=0,
        bucket_end_ns=60_000_000_000,
        scope=scope,
        bar_ids=("MFT1-F-0931", "MFT1-C-0931", "MFT1-P-0931"),
        quote_cutoffs=(("F_LOCAL_1000", 101), ("C_LOCAL_1000", 102), ("P_LOCAL_1000", 103)),
        direction="conversion",
        max_quantity=1,
        invocation_id="next-1",
        next_boundary_ns=60_000_000_000,
        decision_deadline_ns=30_000_000_000,
        entry_candidate=False,
        z_score=0.0,
        legal_barrier=True,
    )
    facts = ExecutionFacts(
        scope=scope,
        source="mf-t1-explicit-synthetic-execution",
        source_kind="synthetic",
        trusted=True,
        reported_phase="EXPOSED",
        first_leg_intent_ns=None,
        first_basket_intent_ns=None,
        cancel_intent_ns=None,
        earliest_exposure_lower_ns=1_000_000_000,
        latest_complete_fill_upper_ns=4_000_000_000,
        complete_basket=True,
        authoritative_flat_verified=False,
        possible_exposure_qty=3,
        confirmed_qty=3,
        event_ids=(),
        collection_version="mf-t1-fixture-v1",
    )
    return TimingFixtureProvider(
        scope=scope,
        mapping=mapping,
        minute=minute,
        facts=facts,
        next_clock_ns=60_000_000_000,
        idle_clock_ns=(75_000_000_000, 901_000_000_000),
    )


def build_normal_exit_fixture() -> TimingFixtureProvider:
    """Build a two-minute actual-Cerebro fixture with a legal normal exit."""

    base = build_timing_fixture()
    later = replace(
        base.minute,
        minute_id="MFT1-0932",
        bucket_start_ns=60_000_000_000,
        bucket_end_ns=120_000_000_000,
        bar_ids=("MFT1-F-0932", "MFT1-C-0932", "MFT1-P-0932"),
        invocation_id="next-2",
        next_boundary_ns=120_000_000_000,
        decision_deadline_ns=90_000_000_000,
    )
    return TimingFixtureProvider(
        scope=base.scope,
        mapping=base.mapping,
        minute=(base.minute, later),
        facts=base.execution_facts(),
        next_clock_ns=(60_000_000_000, 120_000_000_000),
        # The second minute is observed at 120s; idle must remain in the
        # same monotonic domain and advance within the 250ms cadence budget.
        idle_clock_ns=(120_200_000_000,),
    )


__all__ = [
    "FIXTURE_BASE",
    "FixtureExhausted",
    "TimingFixtureFeed",
    "TimingFixtureProvider",
    "build_normal_exit_fixture",
    "build_timing_fixture",
]
