"""Counterexamples for the public closed-bar evidence barrier contract."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backtrader.feeds import (
    BarBarrierPolicy,
    BarEvidence,
    BarLeg,
    ClockMapping,
    MultiLegBarBarrier,
    CtpQuoteEvidence,
    validate_quote_against_bar,
)

UTC = timezone.utc
BASE = datetime(2026, 9, 10, 1, 0, tzinfo=UTC)
_SYNTHETIC_MAPPINGS = {}


def _bar(symbol, *, end=BASE, seal=1.0, **overrides):
    values = {
        "symbol": symbol,
        "exchange": "CZCE",
        "bucket_start": end - timedelta(minutes=1),
        "bucket_end": end,
        "available_at": end + timedelta(seconds=seal),
        "seal_received_mono": seal,
        "trading_day": "20260910",
        "generation": 7,
        "session_segment": "day-1",
        "rules_hash": "rules-v1",
        "quality": "GOOD",
        "volume_complete": True,
        "first_ingest_seq": int(seal * 100),
        "last_ingest_seq": int(seal * 100),
        "quote_cutoff_seq": int(seal * 100) + 5,
        "bar_id": f"{symbol}-{seal}",
        "bar_sequence": int(seal * 100),
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.0,
        "volume": 1.0,
        "clock_domain": "replay-clock",
        "clock_mode": "replay",
        "complete": True,
        "candidate_id": "candidate-v1",
        "watermark": end + timedelta(seconds=seal),
        "seal_received_at": end + timedelta(seconds=seal),
        "trade_count": 1,
    }
    values.update(overrides)
    if "clock_mapping" not in values:
        seal_at = values["seal_received_at"]
        expected_mono = (values["bucket_end"] - BASE).total_seconds() + float(seal)
        if "seal_received_mono" not in overrides:
            values["seal_received_mono"] = expected_mono
        explicit_continuous_pair = (
            seal_at == values["bucket_end"] + timedelta(seconds=seal)
            and abs(float(values["seal_received_mono"]) - expected_mono) <= 1.0e-12
        )
        if explicit_continuous_pair:
            cache_key = (
                values["generation"],
                values["rules_hash"],
                values["clock_domain"],
                values["clock_mode"],
            )
            mapping = _SYNTHETIC_MAPPINGS.get(cache_key)
            if mapping is None:
                mapping = ClockMapping(
                    mapping_id=f"synthetic-test:continuous:{cache_key[0]}",
                    wall_utc_at_anchor=BASE,
                    mono_ns_at_anchor=0,
                    clock_domain_id=values["clock_domain"],
                    connection_generation=values["generation"],
                    source="synthetic-test-recorded-anchor",
                    error_bound_ns=0,
                    valid_until_mono_ns=10**18,
                    rules_hash=values["rules_hash"],
                    synthetic=True,
                )
                _SYNTHETIC_MAPPINGS[cache_key] = mapping
            values["clock_mapping"] = mapping
            return BarEvidence(**values)
        seal_ns = int(round(float(values["seal_received_mono"]) * 1_000_000_000.0))
        wall_offset_ns = (
            (seal_at - end).days * 24 * 60 * 60 + (seal_at - end).seconds
        ) * 1_000_000_000 + (seal_at - end).microseconds * 1_000
        anchor_ns = seal_ns - wall_offset_ns
        anchor_wall = end
        if anchor_ns < 0:
            anchor_wall = seal_at
            anchor_ns = seal_ns
        values["clock_mapping"] = ClockMapping(
            mapping_id=f"synthetic-test:{end.isoformat()}:{anchor_ns}",
            wall_utc_at_anchor=anchor_wall,
            mono_ns_at_anchor=anchor_ns,
            clock_domain_id=values["clock_domain"],
            connection_generation=values["generation"],
            source="synthetic-test-recorded-anchor",
            error_bound_ns=0,
            valid_until_mono_ns=anchor_ns + 86_400 * 1_000_000_000,
            rules_hash=values["rules_hash"],
            synthetic=True,
        )
    return BarEvidence(**values)


def _barrier(timeout=2.0):
    return MultiLegBarBarrier(
        expected_legs=(
            BarLeg("F", "CZCE"),
            BarLeg("C", "CZCE"),
            BarLeg("P", "CZCE"),
        ),
        candidate_id="candidate-v1",
        policy=BarBarrierPolicy(timeframe_seconds=60, timeout_seconds=timeout),
    )


def _quote(symbol="C", *, event_time=None, received_at=None, **overrides):
    received_was_supplied = received_at is not None
    values = {
        "symbol": symbol,
        "exchange": "CZCE",
        "event_time": BASE - timedelta(seconds=1) if event_time is None else event_time,
        "received_at": BASE + timedelta(milliseconds=500) if received_at is None else received_at,
        "received_monotonic": 0.5,
        "ingest_seq": 101,
        "generation": 7,
        "trading_day": "20260910",
        "session_segment": "day-1",
        "rules_hash": "rules-v1",
        "clock_domain": "replay-clock",
        "clock_mode": "replay",
        "quality": "GOOD",
        "volume_complete": True,
        "candidate_id": "candidate-v1",
    }
    values.update(overrides)
    explicit_mono = "received_monotonic" in overrides or "received_monotonic_ns" in overrides
    if not received_was_supplied and explicit_mono and "received_monotonic" in values:
        values["received_at"] = BASE + timedelta(seconds=float(values["received_monotonic"]))
    elif not explicit_mono:
        received = values["received_at"]
        if isinstance(received, datetime):
            offset = (received - BASE).total_seconds()
            if offset < 0:
                offset = -offset
                values["received_at"] = BASE + timedelta(seconds=offset)
            values["received_monotonic"] = offset
    return values


def test_missing_third_leg_expires_and_a_late_bar_cannot_backfill_history():
    barrier = _barrier()
    assert barrier.ingest(_bar("F", end=BASE, seal=0.5)).reason == "WAITING_FOR_LEGS"
    assert barrier.ingest(_bar("C", end=BASE, seal=0.6)).reason == "WAITING_FOR_LEGS"

    expired = barrier.advance(2.500001)
    assert expired and expired[0].reason == "SKIP_BARRIER_TIMEOUT"
    late = barrier.ingest(_bar("P", end=BASE, seal=2.0))
    assert late.reason == "LATE_BAR_REJECTED"
    assert late.decision_input is None


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"quality": "PARTIAL"}, "SKIP_INCOMPLETE_MINUTE"),
        ({"volume_complete": False}, "SKIP_INCOMPLETE_MINUTE"),
        ({"max_event_time": BASE + timedelta(microseconds=1)}, "FUTURE_DATA_REJECTED"),
    ],
)
def test_invalid_bar_is_rejected_and_cannot_be_revised(overrides, reason):
    barrier = _barrier()
    result = barrier.ingest(_bar("F", **overrides))
    assert result.reason == reason
    revised = barrier.ingest(_bar("F", bar_id="revision", **overrides))
    assert revised.reason in {"LATE_BAR_REJECTED", reason}


def test_session_and_identity_are_exact_barrier_dimensions():
    barrier = _barrier()
    assert barrier.ingest(_bar("F", session_segment="day-1")).reason == "WAITING_FOR_LEGS"
    mismatch = barrier.ingest(_bar("C", session_segment="night-1"))
    assert mismatch.reason == "SESSION_MISMATCH"
    exchange = barrier.ingest(_bar("P", exchange="DCE"))
    assert exchange.reason == "EXCHANGE_MISMATCH"


def test_cutoff_is_frozen_and_late_or_future_quotes_are_excluded():
    barrier = _barrier()
    event = {
        "symbol": "C",
        "event_time": BASE - timedelta(seconds=1),
        "received_at": BASE + timedelta(milliseconds=800),
        "ingest_seq": 106,
        "connection_generation": 7,
        "clock_domain": "replay-clock",
    }
    bars = (
        _bar("F", quote_cutoff_seq=105, seal=0.5),
        _bar("C", quote_cutoff_seq=110, seal=0.6, quote_events=(event,)),
        _bar("P", quote_cutoff_seq=105, seal=0.7),
    )
    result = None
    for bar in bars:
        result = barrier.ingest(bar)
    assert result is not None and result.ready
    decision = result.decision_input
    assert decision is not None
    assert decision.quote_cutoffs["C"] == 110
    assert decision.accepted_quotes["C"] == ()

    # A post-seal quote must not mutate the already-frozen decision.
    accepted = barrier.accept_quote({**event, "received_at": BASE + timedelta(seconds=3)})
    assert accepted.accepted is False
    assert decision.accepted_quotes["C"] == ()


def test_nested_quote_payload_is_detached_from_the_source_mapping():
    payload = {
        "symbol": "C",
        "event_time": BASE - timedelta(seconds=1),
        "received_at": BASE - timedelta(milliseconds=1),
        "ingest_seq": 106,
        "details": {"levels": [{"bid": 10.0}]},
    }
    bar = _bar("C", quote_cutoff_seq=110, quote_events=(payload,))
    payload["details"]["levels"][0]["bid"] = 999.0
    assert bar.quote_events[0]["details"]["levels"][0]["bid"] == 10.0
    with pytest.raises(TypeError):
        bar.quote_events[0]["details"] = {}


def test_live_bar_requires_explicit_timezone_and_seal_provenance():
    values = dict(
        _bar("F").__dict__,
        clock_mode="live",
        clock_domain="ctp-front-clock",
        bucket_start=BASE - timedelta(minutes=1),
        bucket_end=BASE,
        available_at=BASE + timedelta(seconds=1),
        seal_received_at=BASE + timedelta(seconds=1),
    )
    values["bucket_end"] = BASE.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone"):
        BarEvidence(**values)


def test_identity_alias_conflicts_fail_closed():
    barrier = _barrier()
    values = _bar("F").to_dict()
    assert barrier.ingest(dict(values, generation=7, connection_generation=8)).reason == (
        "INVALID_BAR"
    )
    assert (
        barrier.ingest(
            dict(
                values,
                watermark=BASE + timedelta(seconds=1),
                event_watermark=BASE + timedelta(seconds=2),
            )
        ).reason
        == "INVALID_BAR"
    )


def test_two_leg_barrier_uses_the_same_frozen_contract():
    barrier = MultiLegBarBarrier(
        expected_legs=(BarLeg("F", "CZCE"), BarLeg("C", "CZCE")),
        candidate_id="candidate-v1",
        policy=BarBarrierPolicy(timeframe_seconds=60, timeout_seconds=10),
    )
    assert barrier.ingest(_bar("F", seal=0.5)).reason == "WAITING_FOR_LEGS"
    result = barrier.ingest(_bar("C", seal=0.6))
    assert result.reason == "READY"
    assert result.decision_input is not None
    assert result.decision_input.bar_ids == ("F-0.5", "C-0.6")


def test_quote_missing_scope_or_quality_cannot_enter_a_decision_input():
    bar = _bar("C", quote_cutoff_seq=110)
    for field in ("trading_day", "generation", "clock_domain", "quality"):
        event = _quote()
        event.pop(field)
        result = validate_quote_against_bar(event, bar=bar)
        assert result.accepted is False


def test_already_validated_ctp_quote_evidence_can_be_cutoff_checked():
    quote = CtpQuoteEvidence(
        symbol="C",
        exchange="CZCE",
        asset_type="option",
        bid=10.0,
        ask=10.5,
        bid_size=1.0,
        ask_size=1.0,
        last=10.0,
        lower_limit=1.0,
        upper_limit=20.0,
        source_epoch=BASE.timestamp() - 1.0,
        receive_epoch=BASE.timestamp() + 0.5,
        receive_monotonic_ns=500_000_000,
        ingest_seq=101,
        connection_generation=7,
        subscription_epoch=1,
        trading_day="20260910",
        action_day="20260910",
        clock_domain_id="replay-clock",
        rules_hash="rules-v1",
        source="fixture",
        event_time_source="exchange",
        source_clock_error_ms=0.0,
        receive_clock_error_ms=0.0,
    )
    result = validate_quote_against_bar(quote, bar=_bar("C", quote_cutoff_seq=110))
    assert result.accepted is True
    assert result.event is not None
    assert result.event["validated_quote_type"] == "CtpQuoteEvidence"


def test_quote_monotonic_units_are_field_defined_and_aliases_must_agree():
    bar = _bar("C", seal=100.0, quote_cutoff_seq=10005)
    assert (
        validate_quote_against_bar(_quote(received_monotonic=101.0), bar=bar).reason
        == "QUOTE_AFTER_SEAL"
    )
    nanosecond_quote = _quote()
    nanosecond_quote.pop("received_monotonic")
    nanosecond_quote["received_monotonic_ns"] = 101_000_000_000
    assert validate_quote_against_bar(nanosecond_quote, bar=bar).reason == "QUOTE_AFTER_SEAL"
    float_nanosecond_quote = _quote()
    float_nanosecond_quote.pop("received_monotonic")
    float_nanosecond_quote["received_monotonic_ns"] = 1.1
    assert validate_quote_against_bar(float_nanosecond_quote, bar=bar).accepted is False
    assert (
        validate_quote_against_bar(
            _quote(received_monotonic=0.5, received_monotonic_ns=900_000_000), bar=bar
        ).reason
        == "QUOTE_IDENTITY_CONFLICT"
    )


def test_complete_quote_cohort_skew_is_a_permanent_barrier_skip():
    barrier = _barrier()
    bars = (
        _bar(
            "F",
            seal=0.5,
            quote_cutoff_seq=200,
            quote_events=(
                _quote(
                    "F",
                    event_time=BASE - timedelta(milliseconds=900),
                    received_at=BASE - timedelta(milliseconds=50),
                ),
            ),
        ),
        _bar(
            "C",
            seal=0.6,
            quote_cutoff_seq=200,
            quote_events=(
                _quote(
                    "C",
                    event_time=BASE - timedelta(milliseconds=100),
                    received_at=BASE - timedelta(milliseconds=50),
                ),
            ),
        ),
        _bar(
            "P",
            seal=0.7,
            quote_cutoff_seq=200,
            quote_events=(
                _quote(
                    "P",
                    event_time=BASE - timedelta(milliseconds=100),
                    received_at=BASE - timedelta(milliseconds=50),
                ),
            ),
        ),
    )
    result = None
    for bar in bars:
        result = barrier.ingest(bar)
    assert result is not None
    assert result.reason == "BLOCKED_CROSS_LEG_SKEW"
    assert result.reset_warmup is True
    assert barrier.ingest(_bar("F", seal=0.5, quote_cutoff_seq=200)).reason == ("LATE_BAR_REJECTED")


def test_retirement_watermark_survives_bounded_history_eviction():
    barrier = _barrier()
    for offset in range(70):
        end = BASE + timedelta(minutes=offset)
        for index, symbol in enumerate(("F", "C", "P")):
            result = barrier.ingest(_bar(symbol, end=end, seal=0.5 + offset / 1000 + index / 100))
        assert result.reason == "READY"
    assert len(barrier.finalized_inputs) <= barrier._MAX_RETAINED_INPUTS
    assert len(barrier._last_results) <= barrier._MAX_RESULT_HISTORY
    assert barrier.ingest(_bar("F", end=BASE, seal=1.0)).reason == "LATE_BAR_REJECTED"


@pytest.mark.parametrize("timeout,late_seconds", ((10.0, 11.0), (2.0, 2.1)))
def test_bar_available_and_seal_deadlines_bound_each_strategy_policy(timeout, late_seconds):
    barrier = _barrier(timeout=timeout)
    late = BASE + timedelta(seconds=late_seconds)
    result = barrier.ingest(
        _bar(
            "F",
            available_at=late,
            seal_received_at=late,
            watermark=late,
        )
    )
    assert result.reason == "SKIP_BARRIER_TIMEOUT"
    assert result.reset_warmup is True
    assert barrier.ingest(_bar("C")).reason == "LATE_BAR_REJECTED"


def test_watermark_before_bucket_end_is_not_a_closed_bar():
    barrier = _barrier()
    result = barrier.ingest(_bar("F", watermark=BASE - timedelta(microseconds=1)))
    assert result.reason == "SKIP_INCOMPLETE_MINUTE"


def test_mapping_bar_cannot_infer_required_provenance_or_completion_fields():
    barrier = _barrier()
    values = _bar("F").to_dict()
    for field in ("quality", "volume_complete", "complete", "clock_domain", "clock_mode"):
        missing = dict(values)
        missing.pop(field)
        assert barrier.ingest(missing).reason == "INVALID_BAR"


def test_first_seal_deadline_cannot_be_extended_by_a_late_leg():
    barrier = _barrier(timeout=2.0)
    assert barrier.ingest(_bar("F", seal=0.5)).reason == "WAITING_FOR_LEGS"
    late_leg = _bar(
        "C",
        seal=2.6,
        available_at=BASE + timedelta(seconds=2),
        seal_received_at=BASE + timedelta(seconds=2),
        watermark=BASE + timedelta(seconds=2),
    )
    assert barrier.ingest(late_leg).reason == "SKIP_BARRIER_TIMEOUT"


def test_monotonic_clock_regression_is_rejected_without_reopening_buckets():
    barrier = _barrier()
    assert barrier.advance(10.0) == ()
    result = barrier.advance(9.0)
    assert result and result[0].reason == "CLOCK_REGRESSION"
    assert barrier.ingest(_bar("F", seal=0.5)).reason == "CLOCK_REGRESSION"


def test_ingest_seals_advance_the_global_observation_fence():
    barrier = _barrier()
    assert barrier.ingest(_bar("F", seal=0.5)).reason == "WAITING_FOR_LEGS"
    result = barrier.advance(0.4)
    assert result and result[0].reason == "CLOCK_REGRESSION"
    assert barrier.ingest(_bar("C", seal=0.6)).reason == "CLOCK_REGRESSION"

    barrier = _barrier()
    result = None
    for symbol, seal in zip(("F", "C", "P"), (0.5, 0.6, 0.7)):
        result = barrier.ingest(_bar(symbol, seal=seal))
    assert result is not None and result.ready
    assert barrier._last_now_mono == pytest.approx(0.7)
    regressed = barrier.advance(0.6)
    assert regressed and regressed[0].reason == "CLOCK_REGRESSION"


def test_clock_fault_revokes_active_input_but_retains_audit_history():
    barrier = _barrier()
    result = None
    for symbol, seal in zip(("F", "C", "P"), (0.5, 0.6, 0.7)):
        result = barrier.ingest(
            _bar(
                symbol,
                seal=seal,
                quote_cutoff_seq=110,
                quote_events=(_quote("C"),) if symbol == "C" else (),
            )
        )
    assert result is not None and result.ready
    decision = result.decision_input
    assert decision is not None

    fault = barrier.advance(None)
    assert fault and fault[0].reason == "CLOCK_INVALID"
    assert barrier.last_input is None
    assert len(barrier.finalized_inputs) == 1
    assert barrier.accept_quote(_quote("C")).reason == "CLOCK_INVALID"
    assert barrier.accept_quote(_quote("C"), decision_input=decision).reason == "CLOCK_INVALID"


def test_reset_cannot_reopen_retired_scope_but_new_generation_can():
    barrier = _barrier()
    result = None
    for symbol, seal in zip(("F", "C", "P"), (0.5, 0.6, 0.7)):
        result = barrier.ingest(_bar(symbol, seal=seal))
    assert result is not None and result.ready
    barrier.advance(None)
    mapping = _bar("F").clock_mapping
    with pytest.raises(ValueError, match="active or retired scope"):
        barrier.reset_scope(
            trading_day="20260910",
            generation=7,
            session_segment="day-1",
            rules_hash="rules-v1",
            clock_domain="replay-clock",
            clock_mode="replay",
            clock_mapping=mapping,
            candidate_id="candidate-v1",
        )

    new_mapping = _bar("F", generation=8).clock_mapping
    barrier.reset_scope(
        trading_day="20260910",
        generation=8,
        session_segment="day-1",
        rules_hash="rules-v1",
        clock_domain="replay-clock",
        clock_mode="replay",
        clock_mapping=new_mapping,
        candidate_id="candidate-v1",
    )
    for symbol, seal in zip(("F", "C", "P"), (0.5, 0.6, 0.7)):
        result = barrier.ingest(_bar(symbol, seal=seal, generation=8))
    assert result is not None and result.ready


def test_new_scope_does_not_reauthorize_explicit_old_decision_input():
    barrier = _barrier()
    result = None
    for symbol, seal in zip(("F", "C", "P"), (0.5, 0.6, 0.7)):
        result = barrier.ingest(
            _bar(
                symbol,
                seal=seal,
                quote_cutoff_seq=110,
                quote_events=(_quote("C"),) if symbol == "C" else (),
            )
        )
    assert result is not None and result.ready
    old_input = result.decision_input
    assert old_input is not None
    barrier.advance(None)

    new_mapping = _bar("F", generation=8).clock_mapping
    barrier.reset_scope(
        trading_day="20260910",
        generation=8,
        session_segment="day-1",
        rules_hash="rules-v1",
        clock_domain="replay-clock",
        clock_mode="replay",
        clock_mapping=new_mapping,
        candidate_id="candidate-v1",
    )
    stale_before = barrier.accept_quote(_quote("C"), decision_input=old_input)
    assert stale_before.accepted is False
    assert stale_before.reason == "SCOPE_RESET_REQUIRED"

    for symbol, seal in zip(("F", "C", "P"), (0.5, 0.6, 0.7)):
        result = barrier.ingest(
            _bar(
                symbol,
                seal=seal,
                generation=8,
                quote_cutoff_seq=110,
                quote_events=(_quote("C", generation=8),) if symbol == "C" else (),
            )
        )
    assert result is not None and result.ready
    fresh = barrier.accept_quote(_quote("C", generation=8), decision_input=result.decision_input)
    stale_after = barrier.accept_quote(_quote("C"), decision_input=old_input)
    assert fresh.accepted is True
    assert stale_after.accepted is False
    assert stale_after.reason == "SCOPE_RESET_REQUIRED"


def test_retired_scope_lifecycle_fence_survives_cache_eviction():
    barrier = _barrier()
    result = None
    for symbol, seal in zip(("F", "C", "P"), (0.5, 0.6, 0.7)):
        result = barrier.ingest(_bar(symbol, seal=seal))
    assert result is not None and result.ready
    original_mapping = _bar("F").clock_mapping
    barrier.advance(None)

    for generation in range(8, 8 + barrier._MAX_RETAINED_INPUTS + 1):
        mapping = _bar("F", generation=generation).clock_mapping
        barrier.reset_scope(
            trading_day="20260910",
            generation=generation,
            session_segment="day-1",
            rules_hash="rules-v1",
            clock_domain="replay-clock",
            clock_mode="replay",
            clock_mapping=mapping,
            candidate_id="candidate-v1",
        )
        for symbol, seal in zip(("F", "C", "P"), (0.5, 0.6, 0.7)):
            result = barrier.ingest(_bar(symbol, seal=seal, generation=generation))
        assert result is not None and result.ready

    assert len(barrier._retired_scopes) == barrier._MAX_RETAINED_INPUTS
    with pytest.raises(ValueError, match="lifecycle fence"):
        barrier.reset_scope(
            trading_day="20260910",
            generation=7,
            session_segment="day-1",
            rules_hash="rules-v1",
            clock_domain="replay-clock",
            clock_mode="replay",
            clock_mapping=original_mapping,
            candidate_id="candidate-v1",
        )

    latest_generation = 8 + barrier._MAX_RETAINED_INPUTS + 1
    latest_mapping = _bar("F", generation=latest_generation).clock_mapping
    barrier.reset_scope(
        trading_day="20260910",
        generation=latest_generation,
        session_segment="day-1",
        rules_hash="rules-v1",
        clock_domain="replay-clock",
        clock_mode="replay",
        clock_mapping=latest_mapping,
        candidate_id="candidate-v1",
    )
    for symbol, seal in zip(("F", "C", "P"), (0.5, 0.6, 0.7)):
        result = barrier.ingest(_bar(symbol, seal=seal, generation=latest_generation))
    assert result is not None and result.ready


def _feed_continuous_scope(barrier, mapping, *, end, trading_day, session_segment):
    """Feed bars whose seal pairs use one recorded wall/monotonic mapping."""

    base_mono = mapping.mono_ns_at_anchor / 1_000_000_000.0
    elapsed = (end - mapping.wall_utc_at_anchor).total_seconds()
    result = None
    for symbol, seal in zip(("F", "C", "P"), (0.5, 0.6, 0.7)):
        result = barrier.ingest(
            _bar(
                symbol,
                end=end,
                seal=seal,
                seal_received_mono=base_mono + elapsed + seal,
                trading_day=trading_day,
                session_segment=session_segment,
                generation=mapping.connection_generation,
                rules_hash=mapping.rules_hash,
                clock_domain=mapping.clock_domain_id,
                clock_mapping=mapping,
            )
        )
    assert result is not None
    return result


def test_same_mapping_can_progress_business_sessions_without_reauthorizing_old_input():
    barrier = _barrier()
    mapping = _bar("F").clock_mapping
    first = _feed_continuous_scope(
        barrier,
        mapping,
        end=BASE,
        trading_day="20260910",
        session_segment="day-1",
    )
    assert first.ready
    old_input = first.decision_input

    barrier.reset_scope(
        trading_day="20260910",
        generation=7,
        session_segment="day-2",
        rules_hash="rules-v1",
        clock_domain="replay-clock",
        clock_mode="replay",
        clock_mapping=mapping,
        candidate_id="candidate-v1",
    )
    second = _feed_continuous_scope(
        barrier,
        mapping,
        end=BASE + timedelta(minutes=1),
        trading_day="20260910",
        session_segment="day-2",
    )
    assert second.ready
    assert second.decision_input is not None
    assert second.decision_input.barrier_ready_mono > first.decision_input.barrier_ready_mono
    assert old_input is not None
    stale = barrier.accept_quote(_quote("C"), decision_input=old_input)
    assert stale.accepted is False
    assert stale.reason == "SCOPE_RESET_REQUIRED"

    barrier.reset_scope(
        trading_day="20260911",
        generation=7,
        session_segment="day-1",
        rules_hash="rules-v1",
        clock_domain="replay-clock",
        clock_mode="replay",
        clock_mapping=mapping,
        candidate_id="candidate-v1",
    )
    third = _feed_continuous_scope(
        barrier,
        mapping,
        end=BASE + timedelta(days=1),
        trading_day="20260911",
        session_segment="day-1",
    )
    assert third.ready


def test_same_generation_old_bucket_stays_retired_after_session_cache_eviction():
    barrier = _barrier()
    mapping = _bar("F").clock_mapping
    first = _feed_continuous_scope(
        barrier,
        mapping,
        end=BASE,
        trading_day="20260910",
        session_segment="session-0",
    )
    assert first.ready
    original_scope = barrier._scope
    original_input = first.decision_input
    assert original_input is not None

    for index in range(1, barrier._MAX_RETAINED_INPUTS + 2):
        barrier.reset_scope(
            trading_day="20260910",
            generation=7,
            session_segment=f"session-{index}",
            rules_hash="rules-v1",
            clock_domain="replay-clock",
            clock_mode="replay",
            clock_mapping=mapping,
            candidate_id="candidate-v1",
        )
        result = _feed_continuous_scope(
            barrier,
            mapping,
            end=BASE + timedelta(minutes=index),
            trading_day="20260910",
            session_segment=f"session-{index}",
        )
        assert result.ready

    assert original_scope not in barrier._retired_scopes
    barrier.reset_scope(
        trading_day="20260910",
        generation=7,
        session_segment="session-0",
        rules_hash="rules-v1",
        clock_domain="replay-clock",
        clock_mode="replay",
        clock_mapping=mapping,
        candidate_id="candidate-v1",
    )
    stale_quote = barrier.accept_quote(_quote("C"), decision_input=original_input)
    assert stale_quote.accepted is False
    assert stale_quote.reason == "SCOPE_RESET_REQUIRED"
    replay = barrier.ingest(
        _bar(
            "F",
            end=BASE,
            seal=0.5,
            seal_received_mono=0.5,
            trading_day="20260910",
            session_segment="session-0",
            clock_mapping=mapping,
        )
    )
    assert replay.reason == "LATE_BAR_REJECTED"


def test_new_clock_domain_does_not_compare_unrelated_monotonic_values():
    barrier = _barrier()
    first_mapping = _bar("F").clock_mapping
    first = _feed_continuous_scope(
        barrier,
        first_mapping,
        end=BASE,
        trading_day="20260910",
        session_segment="day-1",
    )
    assert first.ready
    second_mapping = ClockMapping(
        mapping_id="synthetic-test:second-clock-domain",
        wall_utc_at_anchor=BASE,
        mono_ns_at_anchor=0,
        clock_domain_id="replay-clock-2",
        connection_generation=7,
        source="synthetic-test-recorded-anchor",
        error_bound_ns=0,
        valid_until_mono_ns=10**18,
        rules_hash="rules-v1",
        synthetic=True,
    )
    barrier.reset_scope(
        trading_day="20260910",
        generation=7,
        session_segment="day-2",
        rules_hash="rules-v1",
        clock_domain="replay-clock-2",
        clock_mode="replay",
        clock_mapping=second_mapping,
        candidate_id="candidate-v1",
    )
    result = _feed_continuous_scope(
        barrier,
        second_mapping,
        end=BASE,
        trading_day="20260910",
        session_segment="day-2",
    )
    assert result.ready


def test_same_connection_recalibration_preserves_bucket_watermark():
    barrier = _barrier()
    original_mapping = _bar("F").clock_mapping
    first = _feed_continuous_scope(
        barrier,
        original_mapping,
        end=BASE + timedelta(minutes=1),
        trading_day="20260910",
        session_segment="day-1",
    )
    assert first.ready

    recalibrated = replace(
        original_mapping,
        mapping_id="synthetic-test:recalibrated-anchor",
        wall_utc_at_anchor=BASE + timedelta(seconds=30),
        mono_ns_at_anchor=30_000_000_000,
    )
    barrier.reset_scope(
        trading_day="20260910",
        generation=7,
        session_segment="day-2",
        rules_hash="rules-v1",
        clock_domain="replay-clock",
        clock_mode="replay",
        clock_mapping=recalibrated,
        candidate_id="candidate-v1",
    )

    old_bucket = _feed_continuous_scope(
        barrier,
        recalibrated,
        end=BASE + timedelta(minutes=1),
        trading_day="20260910",
        session_segment="day-2",
    )
    assert old_bucket.reason == "LATE_BAR_REJECTED"
    future_bucket = _feed_continuous_scope(
        barrier,
        recalibrated,
        end=BASE + timedelta(minutes=2),
        trading_day="20260910",
        session_segment="day-2",
    )
    assert future_bucket.ready


def test_same_connection_recalibration_preserves_monotonic_observation():
    barrier = _barrier()
    original_mapping = _bar("F").clock_mapping
    first = _feed_continuous_scope(
        barrier,
        original_mapping,
        end=BASE + timedelta(minutes=1),
        trading_day="20260910",
        session_segment="day-1",
    )
    assert first.ready
    recalibrated = replace(
        original_mapping,
        mapping_id="synthetic-test:recalibrated-anchor-mono",
        wall_utc_at_anchor=BASE + timedelta(seconds=30),
        mono_ns_at_anchor=30_000_000_000,
    )
    barrier.reset_scope(
        trading_day="20260910",
        generation=7,
        session_segment="day-2",
        rules_hash="rules-v1",
        clock_domain="replay-clock",
        clock_mode="replay",
        clock_mapping=recalibrated,
        candidate_id="candidate-v1",
    )

    regressed = barrier.advance(60.6)
    assert regressed and regressed[0].reason == "CLOCK_REGRESSION"


def test_incompatible_recalibration_latches_mapping_fault():
    barrier = _barrier()
    original_mapping = _bar("F").clock_mapping
    first = _feed_continuous_scope(
        barrier,
        original_mapping,
        end=BASE + timedelta(minutes=1),
        trading_day="20260910",
        session_segment="day-1",
    )
    assert first.ready
    incompatible = replace(
        original_mapping,
        mapping_id="synthetic-test:incompatible-anchor",
        wall_utc_at_anchor=BASE + timedelta(seconds=30),
        mono_ns_at_anchor=31_000_000_000,
    )

    with pytest.raises(ValueError, match="incompatible clock mapping"):
        barrier.reset_scope(
            trading_day="20260910",
            generation=7,
            session_segment="day-2",
            rules_hash="rules-v1",
            clock_domain="replay-clock",
            clock_mode="replay",
            clock_mapping=incompatible,
            candidate_id="candidate-v1",
        )
    assert barrier._clock_fault == "CLOCK_MAPPING_MISMATCH"
    assert (
        barrier.ingest(_bar("F", end=BASE + timedelta(minutes=2))).reason
        == "CLOCK_MAPPING_MISMATCH"
    )


def test_backward_incompatible_recalibration_latches_mapping_fault():
    barrier = _barrier()
    original_mapping = _bar("F").clock_mapping
    first = _feed_continuous_scope(
        barrier,
        original_mapping,
        end=BASE + timedelta(minutes=1),
        trading_day="20260910",
        session_segment="day-1",
    )
    assert first.ready
    old_input = first.decision_input
    assert old_input is not None
    old_quote = _quote("C", ingest_seq=1)
    incompatible = replace(
        original_mapping,
        mapping_id="synthetic-test:incompatible-backward-anchor",
        wall_utc_at_anchor=BASE - timedelta(seconds=30),
        mono_ns_at_anchor=0,
    )

    with pytest.raises(ValueError, match="incompatible clock mapping"):
        barrier.reset_scope(
            trading_day="20260910",
            generation=7,
            session_segment="day-2",
            rules_hash="rules-v1",
            clock_domain="replay-clock",
            clock_mode="replay",
            clock_mapping=incompatible,
            candidate_id="candidate-v1",
        )
    assert barrier._clock_fault == "CLOCK_MAPPING_MISMATCH"
    assert barrier.last_input is None
    assert barrier.accept_quote(old_quote).reason == "CLOCK_MAPPING_MISMATCH"
    assert (
        barrier.accept_quote(old_quote, decision_input=old_input).reason == "CLOCK_MAPPING_MISMATCH"
    )
    assert (
        barrier.ingest(_bar("F", end=BASE + timedelta(minutes=2))).reason
        == "CLOCK_MAPPING_MISMATCH"
    )


def test_clock_mapping_requires_recorded_anchor_and_uses_conservative_deadline():
    with pytest.raises(ValueError, match="explicit timezone"):
        ClockMapping(
            mapping_id="mapping-naive",
            wall_utc_at_anchor=BASE.replace(tzinfo=None),
            mono_ns_at_anchor=1_000_000_000,
            clock_domain_id="replay-clock",
            connection_generation=7,
            source="recorded-fixture-anchor",
            error_bound_ns=100_000,
            valid_until_mono_ns=10_000_000_000,
            rules_hash="rules-v1",
            synthetic=True,
        )

    mapping = ClockMapping(
        mapping_id="mapping-recorded",
        wall_utc_at_anchor=BASE,
        mono_ns_at_anchor=1_000_000_000,
        clock_domain_id="replay-clock",
        connection_generation=7,
        source="recorded-fixture-anchor",
        error_bound_ns=100_000,
        valid_until_mono_ns=10_000_000_000,
        rules_hash="rules-v1",
        synthetic=True,
    )
    assert mapping.map_wall_to_mono_ns(BASE + timedelta(seconds=1)) == 2_000_000_000
    assert mapping.conservative_deadline_seconds(BASE + timedelta(seconds=1)) == pytest.approx(
        1.9999
    )
    with pytest.raises(ValueError, match="error bound"):
        mapping.validate_pair(BASE + timedelta(seconds=1), 2.001)


def test_now_alias_conflict_is_a_clock_fault_and_missing_mapping_is_invalid():
    barrier = _barrier()
    assert barrier.ingest(_bar("F"), now_mono=0.5, now=0.6).reason == "CLOCK_INVALID"
    raw = _bar("F").to_dict()
    raw.pop("clock_mapping")
    assert _barrier().ingest(raw).reason == "INVALID_BAR"


def test_scope_fault_requires_explicit_reset_before_a_new_generation_can_ready():
    barrier = _barrier()
    assert barrier.ingest(_bar("F", seal=0.5)).reason == "WAITING_FOR_LEGS"
    assert barrier.ingest(_bar("C", seal=0.6, generation=8)).reason == "GENERATION_MISMATCH"
    assert barrier.ingest(_bar("C", seal=0.6, generation=7)).reason == "GENERATION_MISMATCH"

    mapping = _bar("F", generation=8).clock_mapping
    barrier.reset_scope(
        trading_day="20260910",
        generation=8,
        session_segment="day-1",
        rules_hash="rules-v1",
        clock_domain="replay-clock",
        clock_mode="replay",
        clock_mapping=mapping,
        candidate_id="candidate-v1",
    )
    result = None
    for symbol, seal in zip(("F", "C", "P"), (0.5, 0.6, 0.7)):
        result = barrier.ingest(_bar(symbol, seal=seal, generation=8))
    assert result is not None and result.reason == "READY"


def test_minute_input_recursively_freezes_quote_payload():
    payload = _quote(
        "C",
        ingest_seq=106,
        details={"levels": [{"bid": 10.0, "ask": 10.5}]},
    )
    barrier = _barrier()
    result = None
    for symbol, seal in zip(("F", "C", "P"), (0.5, 0.6, 0.7)):
        result = barrier.ingest(
            _bar(
                symbol,
                seal=seal,
                quote_cutoff_seq=110,
                quote_events=(payload,) if symbol == "C" else (),
            )
        )
    assert result is not None and result.ready
    decision = result.decision_input
    assert decision is not None
    payload["details"]["levels"][0]["bid"] = 999.0
    assert decision.accepted_quotes["C"][0]["details"]["levels"][0]["bid"] == 10.0
    with pytest.raises(TypeError):
        decision.accepted_quotes["C"][0]["details"] = {}
