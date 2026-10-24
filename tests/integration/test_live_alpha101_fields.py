"""Real Feed/Cerebro coverage for the fixed Alpha101 extra-field contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from types import MappingProxyType

import backtrader as bt
import pytest

from backtrader.research import FactorIndicator, FactorSpec, LiveFactorPlan, LiveFactorSet
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortValidationError,
)


UTC = timezone.utc
START = datetime(2025, 1, 2, 9, 30, tzinfo=UTC)
BASE_FIELDS = ("open", "high", "low", "close", "volume")
EXTRA_FIELDS = ("vwap", "cap", "sector", "industry", "subindustry")
ALL_FIELDS = BASE_FIELDS + EXTRA_FIELDS


class ReplayClock:
    """Deterministic source-time clock used by ordinary Cerebro cohort runs."""

    def __init__(self, now):
        self.now = now
        self.monotonic = 1_000
        self.waits = []

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def wait(self, timeout_seconds):
        timeout_seconds = max(0.0, float(timeout_seconds))
        self.waits.append(timeout_seconds)
        self.monotonic += max(1, int(timeout_seconds * 1_000_000_000))
        self.now += timedelta(seconds=timeout_seconds)


class _NumericFieldProbe(FactorIndicator):
    lines = ("factor",)
    formula_fields = EXTRA_FIELDS
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self._inputs = tuple(self.field_lines(name) for name in EXTRA_FIELDS)

    def next(self):
        for index, data in enumerate(self.datas):
            value = 0.0
            for lines in self._inputs:
                value += lines[index][0]
            self.outputs[data].factor[0] = value

    @classmethod
    def build(cls, ctx, **_params):
        value = ctx.vwap
        for name in EXTRA_FIELDS[1:]:
            value = value + getattr(ctx, name)
        return value


class _CapProbe(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("cap",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self._cap = self.field_lines("cap")

    def next(self):
        for index, data in enumerate(self.datas):
            self.outputs[data].factor[0] = self._cap[index][0]


class FieldStrategy(bt.Strategy):
    params = (("cohort", None), ("plan", None), ("clock", None))

    def __init__(self):
        self.live_factors = LiveFactorSet.bind(
            self.p.plan,
            {data._name: data for data in self.datas},
            cohort=self.p.cohort,
        )
        self.readings = []

    def next(self):
        data = self.datas[0]
        batch = self.p.cohort.current_batch()
        snapshot = self.live_factors.snapshot()
        output = snapshot.factors["field_probe"].values[data._name]
        self.readings.append(
            {
                "batch": batch,
                "snapshot": snapshot,
                "output": output,
                "line_values": {name: float(getattr(data, name)[0]) for name in EXTRA_FIELDS},
                "callback_time": self.p.clock.utc_now(),
            }
        )


class _LineOnlyStrategy(bt.Strategy):
    def __init__(self):
        self.extra_values = []

    def next(self):
        self.extra_values.append(tuple(float(getattr(self.data, name)[0]) for name in EXTRA_FIELDS))


def _event(slot, sequence, *, overrides=None, include_extras=True, delay_seconds=2):
    close = 10.0 + sequence
    values = {
        "instrument": "SYN",
        "symbol": "SYN",
        "timestamp": slot.close_time.timestamp(),
        "datetime": slot.close_time,
        "bucket_start": slot.bucket_start,
        "bucket_end": slot.close_time,
        "available_at": slot.close_time + timedelta(seconds=delay_seconds),
        "trading_day": slot.trading_day,
        "session_segment": slot.session_segment,
        "timezone_id": "UTC",
        "clock_domain_id": "field-replay-clock",
        "connection_generation": "history-1",
        "bar_sequence": sequence,
        "bar_id": "SYN-{}".format(sequence),
        "open": close - 0.2,
        "high": close + 0.8,
        "low": close - 0.7,
        "close": close,
        "volume": 100.0 + sequence,
        "openinterest": 0.0,
        "present": True,
        "complete": True,
        "quality": "GOOD",
        "quality_flags": (),
        "source": "alpha101-extra-fields-test",
    }
    if include_extras:
        # VWAP is an independent synthetic input, deliberately unlike the
        # average of the OHLC values. Codes are fixture-local numeric IDs.
        values.update(
            {
                "vwap": close + 0.123 + sequence * 0.01,
                "cap": 1_000_000.0 + sequence * 1_250.0,
                "sector": float(sequence % 3),
                "industry": float(10 + sequence % 5),
                "subindustry": float(100 + sequence % 7),
            }
        )
    if overrides:
        values.update(overrides)
    return MappingProxyType(values)


def _setup(*, count=3, declared_fields=EXTRA_FIELDS, mode="native", factor=True, events=None):
    slots = tuple(
        LiveCalendarSlot(
            slot_id="slot-{}".format(index),
            bucket_start=START + timedelta(minutes=index),
            close_time=START + timedelta(minutes=index + 1),
            trading_day="2025-01-02",
            session_segment="regular",
        )
        for index in range(count)
    )
    calendar = LiveCohortCalendar(
        calendar_id="synthetic-field-calendar",
        version="v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="field-replay-clock",
        session_semantics="synthetic-minute-v1",
        slots=slots,
    )
    cohort = LiveBarCohort(
        "synthetic-field-cohort",
        calendar,
        max_pending_slots=2,
        max_window_bars=max(4, count),
        wait_timeout_ns=30_000_000_000,
    )
    clock = ReplayClock(slots[0].close_time)
    if events is None:
        events = tuple(_event(slot, index + 1) for index, slot in enumerate(slots))
    feed = bt.feeds.BtApiFeed(
        dataname="SYN",
        historical_bars=tuple(events),
        live_bars=(),
        cohort_source_mode=True,
        backfill_start=False,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        bar_watermark_ms=0,
        clock=clock,
    )
    cerebro = bt.Cerebro(stdstats=False, exactbars=0, preload=False, runonce=False)
    cerebro.adddata(feed, name="SYN")
    member_lines = BASE_FIELDS + tuple(declared_fields)
    raw_fields = member_lines + (("openinterest",) if "openinterest" not in member_lines else ())
    numeric_fields = raw_fields
    cohort.register_member(
        "member-SYN",
        feed,
        instrument="SYN",
        source_ref="synthetic-source-SYN",
        line_fields=member_lines,
        raw_fields=raw_fields,
        numeric_fields=numeric_fields,
    )
    plan = None
    if factor:
        selected_fields = (
            EXTRA_FIELDS if declared_fields == EXTRA_FIELDS else tuple(declared_fields)
        )
        factor_class = _NumericFieldProbe if selected_fields == EXTRA_FIELDS else _CapProbe
        bindings = {name: "feed:target:{}".format(name) for name in factor_class.formula_fields}
        plan = LiveFactorPlan(
            targets=("SYN",),
            factors={
                "field_probe": FactorSpec(
                    name="field_probe",
                    indicator=factor_class,
                    panel_line="factor",
                    field_bindings=bindings,
                    mode=mode,
                )
            },
            calendar_id=calendar.calendar_id,
            frequency=calendar.frequency,
            warmup_min_bars=1,
            max_pending_slots=2,
            max_window_bars=max(4, count),
            wait_timeout_ns=30_000_000_000,
        )
        cerebro.add_live_bar_cohort(cohort, clock=clock)
        cerebro.addstrategy(FieldStrategy, cohort=cohort, plan=plan, clock=clock)
    else:
        cerebro.add_live_bar_cohort(cohort, clock=clock)
        cerebro.addstrategy(_LineOnlyStrategy)
    return cerebro, cohort, feed, clock, slots, plan


@pytest.mark.integration
@pytest.mark.parametrize("mode", ("native", "build"))
def test_fixed_numeric_alpha101_fields_flow_before_ordinary_strategy_callback(mode):
    cerebro, cohort, feed, clock, slots, _plan = _setup(count=3, mode=mode)
    events = tuple(_event(slot, index + 1) for index, slot in enumerate(slots))
    strategy = cerebro.run()[0]

    assert len(strategy.readings) == len(events)
    for index, reading in enumerate(strategy.readings):
        event = events[index]
        batch = reading["batch"]
        receipt = batch.receipt_for_feed(feed)
        assert batch.status == "COMPLETE"
        assert batch.close_time == event["bucket_end"]
        assert batch.available_at == event["available_at"]
        assert reading["callback_time"] >= event["available_at"]
        assert receipt.close_time == event["bucket_end"]
        assert receipt.available_at == event["available_at"]
        for name in EXTRA_FIELDS:
            assert reading["line_values"][name] == event[name]
        expected = sum(float(event[name]) for name in EXTRA_FIELDS)
        assert reading["output"].status.value == "OUTPUT_AVAILABLE"
        assert reading["output"].value == pytest.approx(expected, rel=1e-12, abs=1e-12)
        assert reading["output"].source_ref == "synthetic-source-SYN"
    assert clock.waits
    assert cohort.current_batch() is strategy.readings[-1]["batch"]


def test_undeclared_fixed_extras_stay_nan_and_cannot_be_factor_inputs():
    slot = LiveCalendarSlot(
        slot_id="slot-0",
        bucket_start=START,
        close_time=START + timedelta(minutes=1),
        trading_day="2025-01-02",
        session_segment="regular",
    )
    event = _event(slot, 1)
    cerebro, cohort, feed, _clock, _slots, _plan = _setup(
        count=1,
        declared_fields=(),
        factor=False,
        events=(event,),
    )
    with pytest.raises(LiveCohortValidationError, match="not declared"):
        cohort.require_factor_field(feed, "cap")

    strategy = cerebro.run()[0]
    assert len(strategy.extra_values) == 1
    assert all(math.isnan(value) for value in strategy.extra_values[0])


@pytest.mark.parametrize(
    "override,missing_key",
    (
        ({"vwap": "10.5"}, None),
        ({"sector": "energy"}, None),
        ({"cap": math.inf}, None),
        ({"vwap": math.nan}, None),
        ({"available_at": START}, None),
        ({}, "industry"),
    ),
)
def test_invalid_or_noncausal_extra_raw_fields_fail_before_any_line_delivery(override, missing_key):
    slot = LiveCalendarSlot(
        slot_id="slot-0",
        bucket_start=START,
        close_time=START + timedelta(minutes=1),
        trading_day="2025-01-02",
        session_segment="regular",
    )
    values = dict(_event(slot, 1))
    if missing_key is not None:
        values.pop(missing_key)
    values.update(override)
    cerebro, cohort, feed, _clock, _slots, _plan = _setup(
        count=1,
        events=(MappingProxyType(values),),
    )

    with pytest.raises(LiveCohortValidationError):
        cerebro.run()
    assert cohort.frozen is True
    assert cohort.current_batch() is None
    assert len(feed) == 0


def test_cohort_registration_rejects_a_feed_line_without_numeric_raw_mapping():
    slot = LiveCalendarSlot(
        slot_id="slot-0",
        bucket_start=START,
        close_time=START + timedelta(minutes=1),
        trading_day="2025-01-02",
        session_segment="regular",
    )
    calendar = LiveCohortCalendar(
        calendar_id="invalid-line-calendar",
        version="v1",
        epoch_id=1,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="field-replay-clock",
        session_semantics="synthetic-minute-v1",
        slots=(slot,),
    )
    cohort = LiveBarCohort("invalid-line-cohort", calendar)
    feed = bt.feeds.BtApiFeed(dataname="SYN")
    with pytest.raises(LiveCohortValidationError, match="numeric raw field"):
        cohort.register_member(
            "member-SYN",
            feed,
            instrument="SYN",
            source_ref="synthetic-source-SYN",
            line_fields=BASE_FIELDS + ("cap",),
            raw_fields=BASE_FIELDS + ("cap",),
            numeric_fields=BASE_FIELDS,
        )


def test_legacy_feed_extra_lines_remain_nan_without_changing_bar_values():
    from tests.fixtures.fake_btapi import FakeBtApiClient, make_store

    bar_time = START + timedelta(minutes=1)

    class FiniteHistoryClient(FakeBtApiClient):
        def is_source_exhausted(self, _symbol):
            return True

        def get_source_event_time_watermark(self, _symbol):
            return bar_time + timedelta(seconds=1)

    client = FiniteHistoryClient()
    store = make_store(api=client)
    feed = store.getdata(
        dataname="LEGACY",
        historical_bars=(
            {
                "datetime": bar_time,
                "open": 10.0,
                "high": 12.0,
                "low": 9.0,
                "close": 11.0,
                "volume": 100.0,
            },
        ),
        backfill_start=False,
        qcheck=0,
    )
    cerebro = bt.Cerebro(stdstats=False, preload=False, runonce=False)
    cerebro.adddata(feed, name="LEGACY")
    cerebro.addstrategy(_LineOnlyStrategy)
    strategy = cerebro.run()[0]

    assert len(strategy.extra_values) == 1
    assert all(math.isnan(value) for value in strategy.extra_values[0])
    assert feed.open[0] == 10.0
    assert feed.high[0] == 12.0
    assert feed.low[0] == 9.0
    assert feed.close[0] == 11.0
    assert feed.volume[0] == 100.0
