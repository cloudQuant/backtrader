"""Focused contracts for factor-authored field point-in-time inputs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from types import MappingProxyType

import pytest

from backtrader.errors import ResearchConfigError
from backtrader.research import FieldPITPolicy, FactorIndicator, FactorSpec
from backtrader.research.live_cohort import (
    LiveBarCohort,
    LiveCalendarSlot,
    LiveCohortCalendar,
    LiveCohortValidationError,
    LiveFieldContract,
    LiveFieldObservation,
)

UTC = timezone.utc
START = datetime(2026, 10, 24, 9, 30, tzinfo=UTC)


class DollarVolumeIdentity(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("dollar_volume",)
    lookback_h = 0

    def __init__(self):
        super().__init__()
        self._result_lines = self.field_lines("dollar_volume")

    def next(self):
        for data, value in zip(self.datas, self._result_lines):
            self.outputs[data].factor[0] = value[0]


class DerivedADVIdentity(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("vwap", "volume", "dollar_volume", "adv3")
    lookback_h = 0

    def __init__(self):
        super().__init__()

    def next(self):
        return None


def _calendar_and_cohort(*, delivery_mode="independent", max_age_seconds=30.0):
    slot = LiveCalendarSlot(
        slot_id="slot-0",
        bucket_start=START,
        close_time=START + timedelta(minutes=1),
        trading_day=START.date().isoformat(),
        session_segment="regular",
    )
    calendar = LiveCohortCalendar(
        calendar_id="pit-calendar",
        version="v1",
        epoch_id=4,
        frequency="1min",
        frequency_seconds=60,
        timezone_id="UTC",
        clock_domain_id="pit-clock",
        session_semantics="regular-v1",
        slots=(slot,),
    )
    cohort = LiveBarCohort(
        "pit-cohort",
        calendar,
        max_pending_slots=1,
        max_window_bars=2,
        wait_timeout_ns=1_000_000_000,
    )
    feed = object()
    cohort.register_member(
        "member-A",
        feed,
        instrument="A",
        source_ref="bar-source-A",
        line_fields=("open", "high", "low", "close", "volume", "openinterest", "dollar_volume"),
        raw_fields=("open", "high", "low", "close", "volume", "openinterest", "dollar_volume"),
        numeric_fields=("open", "high", "low", "close", "volume", "openinterest", "dollar_volume"),
        field_contracts={
            "dollar_volume": LiveFieldContract(
                source_ref=("bar-source-A" if delivery_mode == "co_delivered" else "aux-A"),
                unit="USD",
                delivery_mode=delivery_mode,
                validity_seconds=(120 if delivery_mode == "co_delivered" else None),
            )
        },
    )
    cohort.bind_factor_field_policy(
        feed, "dollar_volume", unit="USD", max_age_seconds=max_age_seconds
    )
    return cohort, feed, slot


def _event(
    slot,
    *,
    effective_at=None,
    field_available_at=None,
    bar_available_at=None,
    revision="r1",
    source_ref=None,
    field_source_ref="aux-A",
    field_valid_until=None,
    include_observation=True,
):
    close_time = slot.close_time
    generation = "generation-1"
    sequence = 1
    bar_id = "bar-1"
    effective_at = effective_at or close_time - timedelta(seconds=1)
    field_available_at = field_available_at or close_time
    bar_available_at = bar_available_at or close_time
    event = {
        "instrument": "A",
        "symbol": "A",
        "timestamp": close_time.timestamp(),
        "datetime": close_time,
        "bucket_start": slot.bucket_start,
        "bucket_end": close_time,
        "available_at": bar_available_at,
        "trading_day": slot.trading_day,
        "session_segment": slot.session_segment,
        "timezone_id": "UTC",
        "clock_domain_id": "pit-clock",
        "connection_generation": generation,
        "bar_sequence": sequence,
        "bar_id": bar_id,
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.0,
        "volume": 5.0,
        "openinterest": 0.0,
        "dollar_volume": 500.0,
        "present": True,
        "complete": True,
        "quality": "GOOD",
        "quality_flags": (),
        "source": "pit-unit-test",
        "source_ref": source_ref,
    }
    if include_observation:
        event["field_observations"] = MappingProxyType(
            {
                "dollar_volume": LiveFieldObservation(
                    source_ref=field_source_ref,
                    unit="USD",
                    effective_at=effective_at,
                    available_at=field_available_at,
                    revision=revision,
                    valid_until=(
                        field_valid_until
                        if field_valid_until is not None
                        else close_time + timedelta(minutes=1)
                    ),
                )
            }
        )
    return MappingProxyType(event)


def test_factor_field_policy_is_immutable_validated_and_fingerprinted():
    policy = FieldPITPolicy(unit="USD", max_age_seconds=30)
    spec = FactorSpec(
        name="dv",
        indicator=DollarVolumeIdentity,
        panel_line="factor",
        field_bindings={"dollar_volume": "feed:target:dollar_volume"},
        field_policies={"dollar_volume": policy},
    )
    assert spec.field_policies["dollar_volume"] is policy
    assert (
        spec.field_policy_sha256
        != FactorSpec(
            name="dv",
            indicator=DollarVolumeIdentity,
            panel_line="factor",
            field_bindings={"dollar_volume": "feed:target:dollar_volume"},
        ).field_policy_sha256
    )
    assert spec.to_metadata()["field_policies"]["dollar_volume"] == {
        "unit": "USD",
        "max_age_seconds": 30.0,
    }
    with pytest.raises(TypeError):
        spec.field_policies["other"] = policy
    for invalid in (True, 0, -1, float("inf"), float("nan")):
        with pytest.raises(ResearchConfigError):
            FieldPITPolicy(unit="USD", max_age_seconds=invalid)


def test_field_observation_requires_aware_ordered_times_and_explicit_revision():
    close_time = START + timedelta(minutes=1)
    with pytest.raises(LiveCohortValidationError):
        LiveFieldObservation(
            source_ref="aux-A",
            unit="USD",
            effective_at=close_time,
            available_at=close_time - timedelta(seconds=1),
            revision="r1",
            valid_until=close_time + timedelta(seconds=1),
        )
    for revision in (None, False, True, 0, "", b"", ()):
        with pytest.raises(LiveCohortValidationError):
            LiveFieldObservation(
                source_ref="aux-A",
                unit="USD",
                effective_at=close_time,
                available_at=close_time,
                revision=revision,
                valid_until=close_time + timedelta(seconds=1),
            )


def test_capture_rejects_future_field_availability_and_wrong_codelivery_identity():
    cohort, feed, slot = _calendar_and_cohort()
    event = _event(slot, field_available_at=slot.close_time + timedelta(seconds=1))
    with pytest.raises(LiveCohortValidationError, match="not available"):
        cohort.capture_bar(feed, event, source_role="history")
    assert cohort.current_batch() is None
    assert cohort.frozen_reason == "invalid_source_bar"

    cohort, feed, slot = _calendar_and_cohort(delivery_mode="co_delivered")
    event = _event(
        slot,
        effective_at=slot.close_time,
        revision=("generation-1", 2, "different-bar"),
        source_ref="bar-source-A",
        field_source_ref="bar-source-A",
    )
    with pytest.raises(LiveCohortValidationError, match="exact bar event"):
        cohort.capture_bar(feed, event, source_role="history")
    assert cohort.current_batch() is None
    assert cohort.frozen_reason == "invalid_source_bar"


def test_exact_codelivered_field_provenance_is_accepted():
    cohort, feed, slot = _calendar_and_cohort(delivery_mode="co_delivered")
    event = _event(
        slot,
        effective_at=slot.close_time,
        revision=("generation-1", 1, "bar-1"),
        source_ref="bar-source-A",
        field_source_ref="bar-source-A",
        include_observation=False,
    )
    captured = cohort.capture_bar(feed, event, source_role="history")
    assert captured.envelope.raw_values["dollar_volume"] == 500.0
    observation = captured.envelope.field_observations["dollar_volume"]
    assert observation.source_ref == "bar-source-A"
    assert observation.unit == "USD"
    assert observation.effective_at == slot.close_time
    assert observation.available_at == slot.close_time
    assert observation.revision == (
        "generation-1",
        1,
        "bar-1",
    )
    assert observation.valid_until == slot.close_time + timedelta(seconds=120)
    assert cohort.frozen_reason is None


def test_codelivered_observation_cannot_extend_adapter_validity():
    cohort, feed, slot = _calendar_and_cohort(delivery_mode="co_delivered")
    event = _event(
        slot,
        effective_at=slot.close_time,
        revision=("generation-1", 1, "bar-1"),
        source_ref="bar-source-A",
        field_source_ref="bar-source-A",
        field_valid_until=slot.close_time + timedelta(seconds=121),
    )
    with pytest.raises(LiveCohortValidationError, match="exceeds adapter validity"):
        cohort.capture_bar(feed, event, source_role="history")
    assert cohort.current_batch() is None
    assert cohort.frozen_reason == "invalid_source_bar"


def test_codelivered_observation_derivation_requires_exact_event_source_identity():
    for source_ref in (None, "other-source"):
        cohort, feed, slot = _calendar_and_cohort(delivery_mode="co_delivered")
        event = _event(
            slot,
            effective_at=slot.close_time,
            revision=("generation-1", 1, "bar-1"),
            source_ref=source_ref,
            include_observation=False,
        )
        with pytest.raises(LiveCohortValidationError, match="source differs"):
            cohort.capture_bar(feed, event, source_role="history")
        assert cohort.current_batch() is None
        assert cohort.frozen_reason == "invalid_source_bar"


def test_derived_product_and_adv_policies_require_supported_units_and_source_windows():
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
        "vwap": FieldPITPolicy(unit="USD/share", max_age_seconds=60),
        "volume": FieldPITPolicy(unit="share", max_age_seconds=60),
        "dollar_volume": FieldPITPolicy(unit="USD", max_age_seconds=45),
        "adv3": FieldPITPolicy(unit="USD", max_age_seconds=30),
    }
    spec = FactorSpec(
        name="adv",
        indicator=DerivedADVIdentity,
        panel_line="factor",
        field_bindings=bindings,
        field_policies=policies,
    )
    assert spec.field_policies["dollar_volume"].unit == "USD"
    assert spec.field_policies["adv3"].unit == "USD"

    wrong_product = dict(policies)
    wrong_product["dollar_volume"] = FieldPITPolicy("USD/share", 45)
    with pytest.raises(ResearchConfigError, match="price-times-quantity"):
        FactorSpec(
            name="adv",
            indicator=DerivedADVIdentity,
            panel_line="factor",
            field_bindings=bindings,
            field_policies=wrong_product,
        )

    wrong_adv = dict(policies)
    wrong_adv["adv3"] = FieldPITPolicy("CNY", 30)
    with pytest.raises(ResearchConfigError, match="source policy's output unit"):
        FactorSpec(
            name="adv",
            indicator=DerivedADVIdentity,
            panel_line="factor",
            field_bindings=bindings,
            field_policies=wrong_adv,
        )


def test_capture_rejects_unbound_or_malformed_field_provenance_before_queueing():
    cohort, feed, slot = _calendar_and_cohort()
    event = _event(slot)
    without_observation = MappingProxyType(
        {name: value for name, value in event.items() if name != "field_observations"}
    )
    with pytest.raises(LiveCohortValidationError, match="lacks an immutable"):
        cohort.capture_bar(feed, without_observation, source_role="history")
    assert cohort.current_batch() is None
    assert cohort.frozen_reason == "invalid_source_bar"

    cohort, feed, slot = _calendar_and_cohort()
    event = _event(
        slot,
        effective_at=slot.close_time + timedelta(seconds=1),
        field_available_at=slot.close_time + timedelta(seconds=2),
        bar_available_at=slot.close_time + timedelta(seconds=2),
    )
    with pytest.raises(LiveCohortValidationError, match="after bar close"):
        cohort.capture_bar(feed, event, source_role="history")
    assert cohort.current_batch() is None
    assert cohort.frozen_reason == "invalid_source_bar"


def test_prepare_waits_until_the_field_is_available_at_the_scheduler_boundary():
    cohort, feed, slot = _calendar_and_cohort(max_age_seconds=0.5)
    event = _event(
        slot,
        effective_at=slot.close_time,
        field_available_at=slot.close_time + timedelta(seconds=1),
        bar_available_at=slot.close_time + timedelta(seconds=2),
    )
    cohort.capture_bar(feed, event, source_role="history")

    early = cohort.prepare_round(
        1_000,
        source_time_utc=slot.close_time + timedelta(milliseconds=500),
    )
    assert early.status == "WAITING_AVAILABILITY"
    middle = cohort.prepare_round(
        1_001,
        source_time_utc=slot.close_time + timedelta(milliseconds=1500),
    )
    assert middle.status == "WAITING_AVAILABILITY"
    ready = cohort.prepare_round(
        1_002,
        source_time_utc=slot.close_time + timedelta(seconds=2),
    )
    assert ready.status == "READY"
    envelope = cohort.prepared_envelope(feed)
    assert envelope.field_evaluated_at == slot.close_time + timedelta(seconds=2)
    assert envelope.field_gaps["dollar_volume"] == "field_stale"
    assert math.isnan(cohort.preflight_delivery(feed, envelope)["dollar_volume"])


def test_stale_field_is_nan_projected_while_source_value_and_batch_remain_auditable():
    cohort, feed, slot = _calendar_and_cohort()
    event = _event(slot, effective_at=slot.close_time - timedelta(minutes=1))
    capture = cohort.capture_bar(feed, event, source_role="history")
    prepared = cohort.prepare_round(
        1_000,
        source_time_utc=slot.close_time,
    )
    assert prepared.status == "READY"
    envelope = cohort.prepared_envelope(feed)
    assert envelope is capture.envelope
    assert envelope.field_gaps["dollar_volume"] == "field_stale"
    assert envelope.raw_values["dollar_volume"] == 500.0
    projected = cohort.preflight_delivery(feed, envelope)
    assert math.isnan(projected["dollar_volume"])
    receipt = cohort.record_delivery(
        feed,
        envelope,
        delivered_close_time=slot.close_time,
    )
    assert receipt.raw_values["dollar_volume"] == 500.0
    assert math.isnan(receipt.line_values["dollar_volume"])
    assert cohort.complete_window_bars(feed, ("dollar_volume",), 1) == ()
    assert cohort.current_batch() is not None
    assert cohort.current_batch().status == "COMPLETE"
