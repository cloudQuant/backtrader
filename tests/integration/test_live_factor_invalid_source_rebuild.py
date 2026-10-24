"""An invalid raw tick freezes its epoch; a fresh whole group can recover."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
import math
from types import MappingProxyType

import pytest

from backtrader.research.live import LiveFactorReadiness
from backtrader.research.live_cohort import (
    LiveCohortFrozenError,
    LiveCohortValidationError,
)
from tests.integration import test_iteration50_handoff_contract_gaps as fixtures


def _candidate_bar(calendar, *, generation: str):
    slot = calendar.slots[0]
    return MappingProxyType(
        {
            "instrument": "A",
            "symbol": "A",
            "timestamp": slot.close_time.timestamp(),
            "datetime": slot.close_time,
            "bucket_start": slot.bucket_start,
            "bucket_end": slot.close_time,
            "available_at": slot.close_time,
            "trading_day": slot.trading_day,
            "session_segment": slot.session_segment,
            "timezone_id": calendar.timezone_id,
            "clock_domain_id": calendar.clock_domain_id,
            "connection_generation": generation,
            "bar_sequence": 1,
            "bar_id": "A-slot-0-{}".format(generation),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 2.0,
            "openinterest": 0.0,
            "present": True,
            "complete": True,
            "quality": "GOOD",
            "quality_flags": (),
            "source": "deterministic-fake-provider",
        }
    )


@pytest.mark.integration
def test_invalid_raw_tick_freezes_old_grid_then_fresh_whole_group_recovers(monkeypatch):
    fixtures._FACTOR_CALLS.clear()
    calendar_template = fixtures._single_member_calendar(slot_count=2)
    valid_before_error = fixtures._tick(
        calendar_template.slots[0].bucket_start + timedelta(seconds=10),
        sequence=1,
        price=100.0,
    )
    invalid_tick = fixtures._tick(
        calendar_template.slots[0].bucket_start + timedelta(seconds=20),
        sequence=2,
        price=math.nan,
    )
    old_cerebro, old_cohort, old_feed, old_client, old_calendar = fixtures._tick_composition(
        ticks=(valid_before_error, invalid_tick), slot_count=2
    )
    old_slots = tuple(old_calendar.slots)

    with pytest.raises(LiveCohortValidationError) as error:
        old_cerebro.run()

    assert error.value.code == "LAST_PRICE_INVALID"
    assert error.value.report["category"] == "nan"
    assert old_client.observed_ticks == [valid_before_error, invalid_tick]
    assert old_cohort.epoch_id == old_calendar.epoch_id == 1
    assert old_cohort.frozen is True
    assert old_cohort.frozen_reason == "invalid_source_tick_price"
    assert old_cohort.current_batch() is None
    assert old_cohort._next_slot_index == 0
    assert old_cohort._calendar is old_calendar
    assert tuple(old_cohort._calendar.slots) == old_slots
    assert len(old_feed) == 0
    assert fixtures._FACTOR_CALLS == []

    # The old planned grid cannot accept a later valid row after source
    # rejection. Recovery requires a new exact cohort/feed/engine group.
    with pytest.raises(LiveCohortFrozenError, match="cohort is frozen"):
        old_cohort.capture_bar(
            old_feed,
            _candidate_bar(old_calendar, generation="generation-1"),
            source_role="live",
        )
    assert old_cohort._next_slot_index == 0
    assert old_cohort.current_batch() is None
    assert len(old_feed) == 0

    new_calendar = replace(old_calendar, version="v2", epoch_id=2)
    valid_ticks = (
        fixtures._tick(
            new_calendar.slots[0].bucket_start + timedelta(seconds=30),
            sequence=1,
            price=100.0,
        ),
        fixtures._tick(
            new_calendar.slots[1].bucket_start + timedelta(seconds=1),
            sequence=2,
            price=101.0,
        ),
        fixtures._tick(
            new_calendar.slots[1].bucket_start + timedelta(seconds=30),
            sequence=3,
            price=102.0,
        ),
    )
    for tick in valid_ticks:
        tick.connection_generation = "generation-2"

    cohort_type = fixtures.LiveBarCohort

    def build_new_cohort(_cohort_id, calendar, **kwargs):
        return cohort_type("cohort-50-rebuilt-epoch", calendar, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(fixtures, "_single_member_calendar", lambda _slot_count: new_calendar)
        patch.setattr(fixtures, "LiveBarCohort", build_new_cohort)
        (
            new_cerebro,
            new_cohort,
            _new_feed,
            _new_client,
            rebuilt_calendar,
        ) = fixtures._tick_composition(ticks=valid_ticks, slot_count=2)
        [strategy] = new_cerebro.run()

    assert new_cohort is not old_cohort
    assert new_cohort.cohort_id != old_cohort.cohort_id
    assert new_calendar.epoch_id == new_cohort.epoch_id == 2
    assert tuple(rebuilt_calendar.slots) == old_slots
    assert old_cohort.frozen is True and old_cohort._next_slot_index == 0
    assert old_cohort.current_batch() is None and len(old_feed) == 0

    assert [row["batch"].slot_index for row in strategy.rows] == [0, 1]
    assert [row["batch"].close_time for row in strategy.rows] == [
        slot.close_time for slot in old_slots
    ]
    assert all(
        row["receipt"].envelope.connection_generation == "generation-2" for row in strategy.rows
    )
    assert all(row["snapshot"].readiness is LiveFactorReadiness.LIVE_READY for row in strategy.rows)
    assert [row["snapshot"].factors["close_value"].values["A"].value for row in strategy.rows] == [
        100.0,
        102.0,
    ]
    assert fixtures._FACTOR_CALLS == [100.0, 102.0]
