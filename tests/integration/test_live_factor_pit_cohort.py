"""Real Cerebro composition for bounded field-PIT qualification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from types import MappingProxyType

import backtrader as bt
import pytest

from backtrader.research import (
    FactorHistoryContract,
    FactorIndicator,
    FactorSpec,
    FieldPITPolicy,
    LiveFactorPlan,
    LiveFactorSet,
)
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveFieldContract,
    LiveFieldObservation,
)

UTC = timezone.utc
START = datetime(2026, 10, 24, 9, 30, tzinfo=UTC)
NAMES = ("A", "B", "C")


class ReplayClock:
    def __init__(self, available_times):
        self.now = min(available_times)
        self.monotonic = 1_000
        self.available_times = tuple(sorted(available_times))

    def utc_now(self):
        return self.now

    def monotonic_ns(self):
        return self.monotonic

    def wait(self, timeout_seconds):
        future = [value for value in self.available_times if value > self.now]
        elapsed = float(timeout_seconds)
        if future:
            elapsed = min(elapsed, (future[0] - self.now).total_seconds())
        self.now += timedelta(seconds=elapsed)
        self.monotonic += max(1, int(elapsed * 1_000_000_000))


class DollarVolumeValue(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("dollar_volume",)
    lookback_h = 0
    history_contract = FactorHistoryContract.finite_window(span_bars=2)

    def __init__(self):
        super().__init__()
        self._result_lines = self.field_lines("dollar_volume")

    def next(self):
        for data, value in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = value[0]


class ADV3Value(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("vwap", "volume", "dollar_volume", "adv3")
    lookback_h = 0
    history_contract = FactorHistoryContract.finite_window(span_bars=3)

    def __init__(self):
        super().__init__()
        self._result_lines = self.field_lines("adv3")

    def next(self):
        for data, value in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = value[0]


class PITStrategy(bt.Strategy):
    params = (("plan", None), ("cohort", None))

    def __init__(self):
        self.live_factors = LiveFactorSet.bind(
            self.p.plan,
            {data._name: data for data in self.datas},
            cohort=self.p.cohort,
        )
        self.captured = []

    def prenext(self):
        self.next()

    def nextstart(self):
        self.next()

    def next(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        snapshot = self.live_factors.snapshot()
        self.captured.append(
            (
                batch.slot_index,
                snapshot,
                {data._name: float(data.dollar_volume[0]) for data in self.datas},
                batch,
            )
        )


class DerivedPITStrategy(bt.Strategy):
    params = (("plan", None), ("cohort", None))

    def __init__(self):
        self.live_factors = LiveFactorSet.bind(
            self.p.plan,
            {data._name: data for data in self.datas},
            cohort=self.p.cohort,
        )
        self.captured = []

    def prenext(self):
        self.next()

    def nextstart(self):
        self.next()

    def next(self):
        batch = self.p.cohort.current_batch()
        assert batch is not None and batch.status == "COMPLETE"
        snapshot = self.live_factors.snapshot()
        self.captured.append(
            (
                batch.slot_index,
                snapshot,
                {data._name: (float(data.vwap[0]), float(data.volume[0])) for data in self.datas},
                batch,
            )
        )


def _event(name, slot, index, *, stale=False, missing_field=False):
    close_time = slot.close_time
    sequence = index + 1
    bar_id = f"{name}-{sequence}"
    generation = "generation-1"
    field_source = f"aux-source-{name}"
    effective_at = close_time - timedelta(seconds=3600 if stale else 1)
    available_at = close_time
    observations = MappingProxyType(
        {}
        if missing_field
        else {
            "dollar_volume": LiveFieldObservation(
                source_ref=field_source,
                unit="USD",
                effective_at=effective_at,
                available_at=available_at,
                revision=f"revision-{sequence}",
                valid_until=close_time + timedelta(minutes=2),
            )
        }
    )
    value = 1000.0 + NAMES.index(name) * 100.0 + index
    return MappingProxyType(
        {
            "instrument": name,
            "symbol": name,
            "timestamp": close_time.timestamp(),
            "datetime": close_time,
            "bucket_start": slot.bucket_start,
            "bucket_end": close_time,
            "available_at": available_at,
            "trading_day": slot.trading_day,
            "session_segment": slot.session_segment,
            "timezone_id": "UTC",
            "clock_domain_id": "pit-clock",
            "connection_generation": generation,
            "bar_sequence": sequence,
            "bar_id": bar_id,
            "open": 10.0 + index,
            "high": 12.0 + index,
            "low": 9.0 + index,
            "close": 11.0 + index,
            "volume": float(sequence),
            "openinterest": 0.0,
            "dollar_volume": float("nan") if missing_field else value,
            "missing_fields": ("dollar_volume",) if missing_field else (),
            "present": not missing_field,
            "complete": True,
            "quality": "MISSING" if missing_field else "GOOD",
            "quality_flags": ("MISSING_FIELDS",) if missing_field else (),
            "source": "pit-integration-fixture",
            "field_observations": observations,
        }
    )


def _scenario(*, pit_policy=True, missing_auxiliary=False):
    slots = tuple(
        LiveCalendarSlot(
            slot_id=f"slot-{index}",
            bucket_start=START + timedelta(minutes=index),
            close_time=START + timedelta(minutes=index + 1),
            trading_day=START.date().isoformat(),
            session_segment="regular",
        )
        for index in range(7)
    )
    calendar = LiveCohortCalendar(
        calendar_id="pit-integration-calendar",
        version="v1",
        epoch_id=11,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="pit-clock",
        session_semantics="regular-v1",
        slots=slots,
    )
    cohort = LiveBarCohort(
        "pit-integration-cohort",
        calendar,
        max_pending_slots=2,
        max_window_bars=7,
        wait_timeout_ns=10_000_000_000,
    )
    feeds = {}
    available_times = [slot.close_time for slot in slots]
    for name in NAMES:
        events = tuple(
            _event(
                name,
                slot,
                index,
                stale=(name == "B" and index == 3 and not missing_auxiliary),
                missing_field=(name == "B" and index == 3 and missing_auxiliary),
            )
            for index, slot in enumerate(slots)
        )
        feed = bt.feeds.BtApiFeed(
            dataname=name,
            historical_bars=events[:2],
            live_bars=events[2:],
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
        )
        feeds[name] = feed
        cohort.register_member(
            f"member-{name}",
            feed,
            instrument=name,
            source_ref=f"bar-source-{name}",
            line_fields=("open", "high", "low", "close", "volume", "openinterest", "dollar_volume"),
            raw_fields=("open", "high", "low", "close", "volume", "openinterest", "dollar_volume"),
            numeric_fields=(
                "open",
                "high",
                "low",
                "close",
                "volume",
                "openinterest",
                "dollar_volume",
            ),
            field_contracts={
                "dollar_volume": LiveFieldContract(
                    source_ref=f"aux-source-{name}", unit="USD", delivery_mode="independent"
                )
            },
        )
    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    for name in NAMES:
        cerebro.adddata(feeds[name], name=name)
    factor_specs = {
        "pit_value": FactorSpec(
            name="pit_value",
            indicator=DollarVolumeValue,
            panel_line="factor",
            field_bindings={"dollar_volume": "feed:target:dollar_volume"},
            field_policies=(
                {"dollar_volume": FieldPITPolicy(unit="USD", max_age_seconds=60.0)}
                if pit_policy
                else {}
            ),
        )
    }
    if pit_policy:
        factor_specs["legacy_value"] = FactorSpec(
            name="legacy_value",
            indicator=DollarVolumeValue,
            panel_line="factor",
            field_bindings={"dollar_volume": "feed:target:dollar_volume"},
        )
    plan = LiveFactorPlan(
        targets=NAMES,
        groups=dict.fromkeys(NAMES, "market"),
        factors=factor_specs,
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=2,
        max_pending_slots=2,
        max_window_bars=7,
        wait_timeout_ns=10_000_000_000,
        max_live_bar_age_seconds=120.0,
        max_future_skew_seconds=0.0,
    )
    clock = ReplayClock(available_times)
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(PITStrategy, plan=plan, cohort=cohort)
    return cerebro, cohort, feeds


def _derived_scenario():
    slots = tuple(
        LiveCalendarSlot(
            slot_id=f"derived-slot-{index}",
            bucket_start=START + timedelta(minutes=index),
            close_time=START + timedelta(minutes=index + 1),
            trading_day=START.date().isoformat(),
            session_segment="regular",
        )
        for index in range(7)
    )
    calendar = LiveCohortCalendar(
        calendar_id="derived-pit-calendar",
        version="v1",
        epoch_id=21,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="pit-clock",
        session_semantics="regular-v1",
        slots=slots,
    )
    cohort = LiveBarCohort(
        "derived-pit-cohort",
        calendar,
        max_pending_slots=2,
        max_window_bars=7,
        wait_timeout_ns=10_000_000_000,
    )
    feeds = {}
    for name in NAMES:
        events = []
        for index, slot in enumerate(slots):
            close_time = slot.close_time
            vwap = 10.0 + NAMES.index(name) + index
            volume = float(index + 1)
            stale = name == "B" and index == 3
            field_observations = MappingProxyType(
                {
                    "vwap": LiveFieldObservation(
                        source_ref=f"vwap-source-{name}",
                        unit="USD/share",
                        effective_at=(
                            close_time - timedelta(hours=1)
                            if stale
                            else close_time - timedelta(seconds=1)
                        ),
                        available_at=close_time,
                        revision=f"vwap-{name}-{index}",
                        valid_until=close_time + timedelta(minutes=3),
                    )
                }
            )
            events.append(
                MappingProxyType(
                    {
                        "instrument": name,
                        "symbol": name,
                        "timestamp": close_time.timestamp(),
                        "datetime": close_time,
                        "bucket_start": slot.bucket_start,
                        "bucket_end": close_time,
                        "available_at": close_time,
                        "trading_day": slot.trading_day,
                        "session_segment": slot.session_segment,
                        "timezone_id": "UTC",
                        "clock_domain_id": "pit-clock",
                        "connection_generation": "generation-1",
                        "bar_sequence": index + 1,
                        "bar_id": f"{name}-{index + 1}",
                        "open": 10.0 + index,
                        "high": 12.0 + index,
                        "low": 9.0 + index,
                        "close": 11.0 + index,
                        "volume": volume,
                        "openinterest": 0.0,
                        "vwap": vwap,
                        "present": True,
                        "complete": True,
                        "quality": "GOOD",
                        "quality_flags": (),
                        "source": "derived-pit-fixture",
                        "source_ref": f"bar-source-{name}",
                        "field_observations": field_observations,
                    }
                )
            )
        feed = bt.feeds.BtApiFeed(
            dataname=name,
            historical_bars=tuple(events[:2]),
            live_bars=tuple(events[2:]),
            cohort_source_mode=True,
            backfill_start=False,
            timeframe=bt.TimeFrame.Minutes,
            compression=1,
        )
        feeds[name] = feed
        cohort.register_member(
            f"derived-member-{name}",
            feed,
            instrument=name,
            source_ref=f"bar-source-{name}",
            line_fields=("open", "high", "low", "close", "volume", "openinterest", "vwap"),
            raw_fields=("open", "high", "low", "close", "volume", "openinterest", "vwap"),
            numeric_fields=("open", "high", "low", "close", "volume", "openinterest", "vwap"),
            field_contracts={
                "vwap": LiveFieldContract(
                    source_ref=f"vwap-source-{name}",
                    unit="USD/share",
                    delivery_mode="independent",
                ),
                "volume": LiveFieldContract(
                    source_ref=f"bar-source-{name}",
                    unit="share",
                    delivery_mode="co_delivered",
                    validity_seconds=180,
                ),
            },
        )
    cerebro = bt.Cerebro(stdstats=False, exactbars=3, preload=False, runonce=False)
    for name in NAMES:
        cerebro.adddata(feeds[name], name=name)
    bindings = {
        "vwap": "feed:target:vwap",
        "volume": "feed:target:volume",
        "dollar_volume": {
            "derive": "vwap_volume",
            "vwap": "vwap",
            "volume": "volume",
        },
        "adv3": {"derive": "adv", "source": "dollar_volume", "window": 3},
    }
    policies = {
        "vwap": FieldPITPolicy("USD/share", 120.0),
        "volume": FieldPITPolicy("share", 120.0),
        "dollar_volume": FieldPITPolicy("USD", 90.0),
        "adv3": FieldPITPolicy("USD", 90.0),
    }
    plan = LiveFactorPlan(
        targets=NAMES,
        groups=dict.fromkeys(NAMES, "market"),
        factors={
            "derived_adv": FactorSpec(
                name="derived_adv",
                indicator=ADV3Value,
                panel_line="factor",
                field_bindings=bindings,
                field_policies=policies,
            )
        },
        calendar_id=calendar.calendar_id,
        frequency=calendar.frequency,
        warmup_min_bars=2,
        max_pending_slots=2,
        max_window_bars=7,
        wait_timeout_ns=10_000_000_000,
        max_live_bar_age_seconds=120.0,
        max_future_skew_seconds=0.0,
    )
    clock = ReplayClock(tuple(slot.close_time for slot in slots))
    cerebro.add_live_bar_cohort(cohort, clock=clock)
    cerebro.addstrategy(DerivedPITStrategy, plan=plan, cohort=cohort)
    return cerebro, cohort, feeds


@pytest.mark.integration
def test_live_pit_stale_sample_keeps_group_members_and_recovers_after_clean_window():
    cerebro, cohort, _feeds = _scenario()
    strategy = cerebro.run()[0]
    by_slot = {
        slot_index: (snapshot, lines, batch)
        for slot_index, snapshot, lines, batch in strategy.captured
    }
    assert set(by_slot) == set(range(7))

    stale_snapshot, stale_lines, stale_batch = by_slot[3]
    assert math.isnan(stale_lines["B"])
    stale_envelope = stale_batch.receipt_for_feed(_feeds["B"]).envelope
    assert stale_envelope.raw_values["dollar_volume"] > 0.0
    assert math.isnan(stale_envelope.line_values["dollar_volume"])
    pit_result = stale_snapshot.factors["pit_value"]
    assert pit_result.pit_policy_complete is True
    assert pit_result.pit_qualified is False
    assert set(pit_result.values) == set(NAMES)
    assert all(output.status.value == "OUTPUT_UNAVAILABLE" for output in pit_result.values.values())
    assert stale_snapshot.readiness.value == "WARMUP"
    assert "field_pit_input_unqualified" in stale_snapshot.readiness_reasons
    provenance = pit_result.values["A"].field_provenance["dollar_volume"]
    assert len(provenance) == len(NAMES)
    assert {row.feed_name for row in provenance} == set(NAMES)
    stale_field = next(row for row in provenance if row.feed_name == "B")
    assert stale_field.status == "FIELD_STALE"
    assert stale_field.evaluated_at == stale_snapshot.available_at
    with pytest.raises(TypeError):
        pit_result.values["A"].field_provenance["other"] = ()

    still_blocked = by_slot[4][0].factors["pit_value"]
    assert still_blocked.pit_qualified is False
    assert all(
        output.status.value == "OUTPUT_UNAVAILABLE" for output in still_blocked.values.values()
    )

    recovered = by_slot[5][0].factors["pit_value"]
    assert recovered.pit_qualified is True
    assert all(output.status.value == "OUTPUT_AVAILABLE" for output in recovered.values.values())
    assert by_slot[5][0].readiness.value == "LIVE_READY"

    legacy = by_slot[5][0].factors["legacy_value"]
    assert legacy.pit_policy_complete is False
    assert legacy.pit_qualified is False
    assert legacy.unqualified_fields == ("dollar_volume",)
    assert all(output.status.value == "OUTPUT_AVAILABLE" for output in legacy.values.values())
    assert len(legacy.values) == len(NAMES)
    legacy_statuses = {
        row.status
        for output in legacy.values.values()
        for row in output.field_provenance["dollar_volume"]
    }
    assert legacy_statuses == {"UNQUALIFIED"}


def test_no_policy_legacy_factor_remains_explicitly_unqualified():
    cerebro, _cohort, _feeds = _scenario(pit_policy=False)
    strategy = cerebro.run()[0]
    final_snapshot = strategy.captured[-1][1]
    legacy = final_snapshot.factors["pit_value"]
    assert legacy.pit_policy_complete is False
    assert legacy.pit_qualified is False
    assert legacy.unqualified_fields == ("dollar_volume",)


@pytest.mark.integration
def test_missing_auxiliary_keeps_group_members_and_recovers_after_clean_window():
    cerebro, _cohort, feeds = _scenario(missing_auxiliary=True)
    strategy = cerebro.run()[0]
    by_slot = {
        slot_index: (snapshot, lines, batch)
        for slot_index, snapshot, lines, batch in strategy.captured
    }

    missing_snapshot, missing_lines, missing_batch = by_slot[3]
    result = missing_snapshot.factors["pit_value"]
    assert set(result.values) == set(NAMES)
    assert all(output.status.value == "OUTPUT_UNAVAILABLE" for output in result.values.values())
    assert missing_snapshot.readiness.value == "WARMUP"
    assert math.isnan(missing_lines["B"])
    missing_receipt = missing_batch.receipt_for_feed(feeds["B"])
    assert missing_receipt.present is False
    assert missing_receipt.missing_fields == ("dollar_volume",)
    assert math.isnan(missing_receipt.raw_values["dollar_volume"])
    missing_field = result.values["A"].field_provenance["dollar_volume"]
    assert next(row for row in missing_field if row.feed_name == "B").status == "FIELD_MISSING"

    recovered = by_slot[5][0].factors["pit_value"]
    assert recovered.pit_qualified is True
    assert all(output.status.value == "OUTPUT_AVAILABLE" for output in recovered.values.values())


@pytest.mark.integration
def test_vwap_volume_product_and_adv_window_require_exact_units_and_clean_window():
    cerebro, _cohort, feeds = _derived_scenario()
    strategy = cerebro.run()[0]
    by_slot = {
        slot_index: (snapshot, lines, batch)
        for slot_index, snapshot, lines, batch in strategy.captured
    }

    initial = by_slot[2][0].factors["derived_adv"]
    expected = sum((10.0 + index) * (index + 1) for index in range(3)) / 3.0
    assert initial.values["A"].value == pytest.approx(expected)
    assert initial.pit_policy_complete is True
    assert initial.pit_qualified is True

    stale_snapshot, stale_lines, stale_batch = by_slot[3]
    assert math.isnan(stale_lines["B"][0])
    stale_receipt = stale_batch.receipt_for_feed(feeds["B"])
    assert stale_receipt.raw_values["vwap"] == pytest.approx(14.0)
    assert math.isnan(stale_receipt.line_values["vwap"])
    product_provenance = (
        stale_snapshot.factors["derived_adv"].values["A"].field_provenance["dollar_volume"]
    )
    assert {row.line_name for row in product_provenance} == {"vwap", "volume"}
    assert (
        next(
            row for row in product_provenance if row.feed_name == "B" and row.line_name == "vwap"
        ).status
        == "FIELD_STALE"
    )

    for slot_index in (3, 4, 5):
        result = by_slot[slot_index][0].factors["derived_adv"]
        assert result.pit_qualified is False
        assert set(result.values) == set(NAMES)
        assert all(output.status.value == "OUTPUT_UNAVAILABLE" for output in result.values.values())
    recovered = by_slot[6][0]
    result = recovered.factors["derived_adv"]
    assert result.pit_qualified is True
    assert all(output.status.value == "OUTPUT_AVAILABLE" for output in result.values.values())
    assert recovered.readiness.value == "LIVE_READY"
