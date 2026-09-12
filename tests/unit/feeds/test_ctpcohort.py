"""Unit tests for strict, side-effect-free CTP multi-leg quote cohorts."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import backtrader as bt
import pytest
from backtrader.feeds.ctpcohort import CtpCohortNow

SYMBOLS = ("SA701", "SA701C1080", "SA701P1080")
RULES_HASH = "bundle-rules-sha256"


def _policy(**overrides):
    values = {
        "max_receive_age_ms": 250.0,
        "max_receive_skew_ms": 100.0,
        "max_source_age_ms": 250.0,
        "max_source_skew_ms": 100.0,
        "max_source_clock_error_ms": 5.0,
        "max_receive_clock_error_ms": 5.0,
    }
    values.update(overrides)
    return bt.feeds.CtpCohortPolicy(**values)


def _validator(*, policy=None, symbols=SYMBOLS):
    return bt.feeds.CtpQuoteCohortValidator(
        expected_legs=tuple(
            bt.feeds.CtpCohortLeg(symbol=symbol, exchange="CZCE", price_tick=0.5)
            for symbol in symbols
        ),
        expected_rules_hash=RULES_HASH,
        policy=policy or _policy(),
    )


def _quote(
    symbol,
    *,
    sequence=1,
    receive_monotonic_ns=1_000_000_000,
    source_epoch=1_700_000_000.0,
    receive_epoch=1_700_000_000.01,
    **overrides,
):
    event = {
        "schema_version": "ctp.quote.v2",
        "volume_semantics": "delta",
        "symbol": symbol,
        "exchange": "CZCE",
        "source_clock_quality": "verified",
        "receive_clock_quality": "verified",
        "freshness_verified": True,
        "event_time_source": "action_day_update_time",
        "rules_hash": RULES_HASH,
        "source": "ctp-front",
        "stale": False,
        "stale_reason": "",
        "continuity_status": "continuous",
        "quality_flags": (),
        "execution_eligible": True,
        "volume_complete": True,
        "volume_quality": "CONTINUOUS",
        "bid_price": 99.0,
        "ask_price": 100.0,
        "bid_volume": 3.0,
        "ask_volume": 4.0,
        "price": 99.5,
        "lower_limit_price": 90.0,
        "upper_limit_price": 110.0,
        "source_clock_error_ms": 1.0,
        "receive_clock_error_ms": 1.0,
        "event_time_utc": source_epoch,
        "recv_time_utc": receive_epoch,
        "recv_monotonic_ns": receive_monotonic_ns,
        "ingest_seq": sequence,
        "connection_generation": 7,
        "subscription_epoch": 11,
        "trading_day": "20260910",
        "action_day": "20260910",
        "clock_domain_id": "ctp-sdk-process-monotonic",
    }
    event.update(overrides)
    return event


def _value(event, *names):
    if isinstance(event, dict):
        for name in names:
            if name in event:
                return event[name]
        return None
    for name in names:
        if hasattr(event, name):
            return getattr(event, name)
    return None


def _now_for(event, **overrides):
    monotonic = _value(event, "recv_monotonic_ns", "received_monotonic_ns")
    epoch = _value(event, "recv_time_utc", "received_wall_time", "local_time")
    clock_domain_id = _value(event, "clock_domain_id")
    receive_clock_error_ms = _value(event, "receive_clock_error_ms")
    values = {
        "now_monotonic_ns": (
            monotonic if type(monotonic) is int and monotonic > 0 else 1_000_000_000
        ),
        "now_epoch": (
            epoch
            if isinstance(epoch, (int, float)) and not isinstance(epoch, bool)
            else 1_700_000_000.01
        ),
        "clock_domain_id": (
            clock_domain_id
            if isinstance(clock_domain_id, str)
            and clock_domain_id.strip() == clock_domain_id
            and clock_domain_id
            else "ctp-sdk-process-monotonic"
        ),
        "receive_clock_error_ms": (
            receive_clock_error_ms
            if isinstance(receive_clock_error_ms, (int, float))
            and not isinstance(receive_clock_error_ms, bool)
            else 1.0
        ),
    }
    values.update(overrides)
    return CtpCohortNow(**values)


def _ingest(validator, event, *, now=None):
    return validator.ingest(event, now=_now_for(event) if now is None else now)


def _admit_initial(validator):
    assert _ingest(validator, _quote(SYMBOLS[0], receive_monotonic_ns=1_000_000_000)).reason == (
        bt.feeds.CtpCohortReason.WAITING_FOR_LEGS
    )
    assert _ingest(validator, _quote(SYMBOLS[1], receive_monotonic_ns=1_010_000_000)).reason == (
        bt.feeds.CtpCohortReason.WAITING_FOR_LEGS
    )
    return _ingest(validator, _quote(SYMBOLS[2], receive_monotonic_ns=1_020_000_000))


def test_public_feed_api_admits_a_immutable_three_leg_cohort_only_after_all_legs_arrive():
    validator = _validator()

    result = _admit_initial(validator)

    assert result.accepted is True
    assert result.reason is None
    assert result.cohort is not None
    assert tuple(result.cohort.quotes) == SYMBOLS
    assert result.cohort.quote_for(SYMBOLS[1]).ask == 100.0
    assert result.cohort.cohort_id == ("SA701:7:11:1|SA701C1080:7:11:1|SA701P1080:7:11:1")
    with pytest.raises(TypeError):
        result.cohort.quotes["other"] = result.cohort.quote_for(SYMBOLS[0])
    with pytest.raises(FrozenInstanceError):
        result.cohort.quote_for(SYMBOLS[0]).bid = 1.0
    assert validator.expected_legs == tuple(validator.expected_legs)


def test_admitted_cohorts_require_a_new_valid_quote_for_every_leg():
    validator = _validator()
    assert _admit_initial(validator).accepted

    result = _ingest(
        validator,
        _quote(
            SYMBOLS[0],
            sequence=2,
            receive_monotonic_ns=1_030_000_000,
            source_epoch=1_700_000_000.03,
            receive_epoch=1_700_000_000.04,
        ),
    )
    assert result.reason == bt.feeds.CtpCohortReason.WAITING_FOR_ALL_LEGS_NEW
    result = _ingest(
        validator,
        _quote(
            SYMBOLS[1],
            sequence=2,
            receive_monotonic_ns=1_040_000_000,
            source_epoch=1_700_000_000.04,
            receive_epoch=1_700_000_000.05,
        ),
    )
    assert result.reason == bt.feeds.CtpCohortReason.WAITING_FOR_ALL_LEGS_NEW
    result = _ingest(
        validator,
        _quote(
            SYMBOLS[2],
            sequence=2,
            receive_monotonic_ns=1_050_000_000,
            source_epoch=1_700_000_000.05,
            receive_epoch=1_700_000_000.06,
        ),
    )
    assert result.accepted
    assert result.cohort is not None
    assert {quote.ingest_seq for quote in result.cohort.quotes.values()} == {2}


def test_new_valid_leg_update_revokes_the_prior_confirmation_until_the_next_full_round():
    validator = _validator()
    assert _admit_initial(validator).accepted

    pending = _ingest(
        validator,
        _quote(
            SYMBOLS[0],
            sequence=2,
            receive_monotonic_ns=1_030_000_000,
            source_epoch=1_700_000_000.03,
            receive_epoch=1_700_000_000.04,
        ),
    )

    assert pending.reason == bt.feeds.CtpCohortReason.WAITING_FOR_ALL_LEGS_NEW
    assert validator.validate_at(now=_now_for(_quote(SYMBOLS[0]))).reason == (
        bt.feeds.CtpCohortReason.NO_CONFIRMED_COHORT
    )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"source_clock_quality": "unknown"}, "SOURCE_CLOCK_UNVERIFIED"),
        ({"receive_clock_quality": "unknown"}, "RECEIVE_CLOCK_UNVERIFIED"),
        ({"freshness_verified": False}, "FRESHNESS_UNVERIFIED"),
        ({"continuity_status": "gap"}, "QUOTE_CONTINUITY_NOT_CONTINUOUS"),
        ({"quality_flags": ("GAP",)}, "QUOTE_QUALITY_FLAGS_PRESENT"),
        ({"execution_eligible": False}, "EXECUTION_INELIGIBLE_QUOTE"),
        ({"volume_complete": False}, "VOLUME_INCOMPLETE"),
        ({"volume_quality": "GAP"}, "VOLUME_QUALITY_NOT_CONTINUOUS"),
        ({"bid_price": "99.0"}, "QUOTE_NUMERIC_TYPE_INVALID"),
        ({"bid_price": float("nan")}, "QUOTE_NUMERIC_TYPE_INVALID"),
        ({"bid_price": float("inf")}, "QUOTE_NUMERIC_TYPE_INVALID"),
        ({"bid_price": 1.0e30}, "QUOTE_NUMERIC_TYPE_INVALID"),
        ({"ask_price": 98.0}, "QUOTE_CROSSED"),
        ({"price": 111.0}, "QUOTE_OUTSIDE_DAILY_LIMIT"),
        ({"price": 99.7}, "QUOTE_OFF_TICK_GRID"),
        ({"source_clock_error_ms": 5.1}, "SOURCE_CLOCK_ERROR_INVALID"),
        ({"receive_clock_error_ms": 5.1}, "RECEIVE_CLOCK_ERROR_INVALID"),
        ({"recv_monotonic_ns": "1000000000"}, "QUOTE_IDENTITY_TYPE_INVALID"),
        ({"event_time_utc": "2026-09-10T09:00:00"}, "SOURCE_TIME_INVALID"),
    ],
)
def test_quote_level_quality_and_type_failures_are_explicit(overrides, reason):
    validator = _validator()

    result = _ingest(validator, _quote(SYMBOLS[0], **overrides))

    assert result.cohort is None
    assert result.reason == getattr(bt.feeds.CtpCohortReason, reason)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("source", " ", "QUOTE_SOURCE_MISSING"),
        ("event_time_source", "\t", "EVENT_TIME_SOURCE_MISSING"),
        ("clock_domain_id", "  ", "CLOCK_DOMAIN_UNKNOWN"),
        ("action_day", "", "ACTION_DAY_INVALID"),
        ("action_day", "20260230", "ACTION_DAY_INVALID"),
        ("action_day", "2026091A", "ACTION_DAY_INVALID"),
    ],
)
def test_blank_provenance_and_invalid_action_day_fail_closed(field, value, reason):
    validator = _validator()

    result = _ingest(validator, _quote(SYMBOLS[0], **{field: value}))

    assert result.cohort is None
    assert result.reason == getattr(bt.feeds.CtpCohortReason, reason)


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("action_day", "ACTION_DAY_INVALID"),
        ("receive_clock_quality", "RECEIVE_CLOCK_UNVERIFIED"),
        ("freshness_verified", "FRESHNESS_UNVERIFIED"),
        ("stale", "QUOTE_STREAM_UNREADY"),
        ("stale_reason", "QUOTE_STREAM_UNREADY"),
    ],
)
def test_required_v2_evidence_cannot_be_omitted(field, reason):
    validator = _validator()
    quote = _quote(SYMBOLS[0])
    quote.pop(field)

    result = _ingest(validator, quote)

    assert result.reason == getattr(bt.feeds.CtpCohortReason, reason)


def test_action_day_is_retained_and_may_legally_differ_from_trading_day_at_night():
    validator = _validator()
    night = {"trading_day": "20260910", "action_day": "20260909"}

    assert (
        _ingest(
            validator,
            _quote(SYMBOLS[0], receive_monotonic_ns=1_000_000_000, **night),
        ).reason
        == bt.feeds.CtpCohortReason.WAITING_FOR_LEGS
    )
    assert (
        _ingest(
            validator,
            _quote(SYMBOLS[1], receive_monotonic_ns=1_010_000_000, **night),
        ).reason
        == bt.feeds.CtpCohortReason.WAITING_FOR_LEGS
    )
    result = _ingest(
        validator,
        _quote(SYMBOLS[2], receive_monotonic_ns=1_020_000_000, **night),
    )

    assert result.accepted
    assert result.cohort is not None
    assert result.cohort.trading_day == "20260910"
    assert result.cohort.action_day == "20260909"
    assert {quote.action_day for quote in result.cohort.quotes.values()} == {"20260909"}


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"continuity_status": "gap"}, "QUOTE_CONTINUITY_NOT_CONTINUOUS"),
        ({"quality_flags": ("GAP",)}, "QUOTE_QUALITY_FLAGS_PRESENT"),
        ({"receive_clock_quality": "unknown"}, "RECEIVE_CLOCK_UNVERIFIED"),
        ({"recv_monotonic_ns": "bad"}, "QUOTE_IDENTITY_TYPE_INVALID"),
    ],
)
def test_expected_leg_failure_invalidates_confirmation_and_requires_all_fresh_legs(
    overrides,
    reason,
):
    validator = _validator()
    assert _admit_initial(validator).accepted

    failed = _ingest(
        validator,
        _quote(
            SYMBOLS[0],
            sequence=2,
            receive_monotonic_ns=1_030_000_000,
            source_epoch=1_700_000_000.03,
            receive_epoch=1_700_000_000.04,
            **overrides,
        ),
    )
    assert failed.reason == getattr(bt.feeds.CtpCohortReason, reason)
    assert validator.validate_at(now=_now_for(_quote(SYMBOLS[0]))).reason == (
        bt.feeds.CtpCohortReason.NO_CONFIRMED_COHORT
    )

    assert (
        _ingest(
            validator,
            _quote(
                SYMBOLS[1],
                sequence=2,
                receive_monotonic_ns=1_040_000_000,
                source_epoch=1_700_000_000.04,
                receive_epoch=1_700_000_000.05,
            ),
        ).reason
        == bt.feeds.CtpCohortReason.WAITING_FOR_LEGS
    )
    assert (
        _ingest(
            validator,
            _quote(
                SYMBOLS[2],
                sequence=2,
                receive_monotonic_ns=1_050_000_000,
                source_epoch=1_700_000_000.05,
                receive_epoch=1_700_000_000.06,
            ),
        ).reason
        == bt.feeds.CtpCohortReason.WAITING_FOR_LEGS
    )
    recovered = _ingest(
        validator,
        _quote(
            SYMBOLS[0],
            sequence=2,
            receive_monotonic_ns=1_060_000_000,
            source_epoch=1_700_000_000.06,
            receive_epoch=1_700_000_000.07,
        ),
    )

    assert recovered.accepted
    assert recovered.cohort is not None
    assert {quote.ingest_seq for quote in recovered.cohort.quotes.values()} == {2}


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("trading_day", "20260911", "COHORT_TRADING_DAY_MISMATCH"),
        ("action_day", "20260911", "COHORT_ACTION_DAY_MISMATCH"),
        ("clock_domain_id", "another-process-monotonic", "COHORT_CLOCK_DOMAIN_MISMATCH"),
    ],
)
def test_mixed_cohort_identity_boundaries_fail_closed(field, value, reason):
    validator = _validator()
    assert _ingest(validator, _quote(SYMBOLS[0], receive_monotonic_ns=1_000_000_000)).reason
    assert _ingest(validator, _quote(SYMBOLS[1], receive_monotonic_ns=1_010_000_000)).reason

    result = _ingest(
        validator, _quote(SYMBOLS[2], receive_monotonic_ns=1_020_000_000, **{field: value})
    )

    assert result.cohort is None
    assert result.reason == getattr(bt.feeds.CtpCohortReason, reason)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("connection_generation", 8),
        ("subscription_epoch", 12),
    ],
)
def test_new_connection_scope_restarts_sequence_without_mixing_old_evidence(field, value):
    validator = _validator()
    assert _ingest(
        validator, _quote(SYMBOLS[0], sequence=91, receive_monotonic_ns=1_000_000_000)
    ).reason
    assert _ingest(
        validator, _quote(SYMBOLS[1], sequence=92, receive_monotonic_ns=1_010_000_000)
    ).reason

    new_scope_quote = _quote(
        SYMBOLS[2],
        sequence=1,
        receive_monotonic_ns=1_020_000_000,
        source_epoch=1_700_000_000.02,
        receive_epoch=1_700_000_000.03,
        **{field: value},
    )
    switched = _ingest(validator, new_scope_quote)
    assert switched.reason == bt.feeds.CtpCohortReason.WAITING_FOR_LEGS

    shared = {field: value}
    assert (
        _ingest(
            validator,
            _quote(
                SYMBOLS[0],
                sequence=1,
                receive_monotonic_ns=1_030_000_000,
                source_epoch=1_700_000_000.03,
                receive_epoch=1_700_000_000.04,
                **shared,
            ),
        ).reason
        == bt.feeds.CtpCohortReason.WAITING_FOR_LEGS
    )
    result = _ingest(
        validator,
        _quote(
            SYMBOLS[1],
            sequence=1,
            receive_monotonic_ns=1_040_000_000,
            source_epoch=1_700_000_000.04,
            receive_epoch=1_700_000_000.05,
            **shared,
        ),
    )

    assert result.accepted
    assert result.cohort is not None
    assert {quote.ingest_seq for quote in result.cohort.quotes.values()} == {1}
    assert {getattr(quote, field) for quote in result.cohort.quotes.values()} == {value}


def test_receive_and_source_age_and_skew_boundaries_fail_closed():
    receive_stale = _validator()
    assert _ingest(receive_stale, _quote(SYMBOLS[0], receive_monotonic_ns=1_000_000_000)).reason
    assert _ingest(receive_stale, _quote(SYMBOLS[1], receive_monotonic_ns=1_010_000_000)).reason
    result = _ingest(
        receive_stale,
        _quote(
            SYMBOLS[2],
            receive_monotonic_ns=1_400_000_000,
            source_epoch=1_700_000_000.39,
            receive_epoch=1_700_000_000.4,
        ),
    )
    assert result.reason == bt.feeds.CtpCohortReason.STALE_COHORT_RECEIVE_TIME

    receive_skew = _validator(policy=_policy(max_receive_age_ms=1_000.0, max_receive_skew_ms=50.0))
    assert _ingest(receive_skew, _quote(SYMBOLS[0], receive_monotonic_ns=1_000_000_000)).reason
    assert _ingest(receive_skew, _quote(SYMBOLS[1], receive_monotonic_ns=1_010_000_000)).reason
    result = _ingest(
        receive_skew,
        _quote(
            SYMBOLS[2],
            receive_monotonic_ns=1_100_000_000,
            source_epoch=1_700_000_000.09,
            receive_epoch=1_700_000_000.1,
        ),
    )
    assert result.reason == bt.feeds.CtpCohortReason.BLOCKED_CROSS_LEG_SKEW

    source_stale = _validator(policy=_policy(max_receive_age_ms=1_000.0, max_source_age_ms=100.0))
    assert _ingest(source_stale, _quote(SYMBOLS[0], receive_monotonic_ns=1_000_000_000)).reason
    assert _ingest(
        source_stale,
        _quote(
            SYMBOLS[1],
            receive_monotonic_ns=1_010_000_000,
            source_epoch=1_700_000_000.2,
            receive_epoch=1_700_000_000.21,
        ),
    ).reason
    result = _ingest(
        source_stale,
        _quote(
            SYMBOLS[2],
            receive_monotonic_ns=1_020_000_000,
            source_epoch=1_700_000_000.21,
            receive_epoch=1_700_000_000.22,
        ),
    )
    assert result.reason == bt.feeds.CtpCohortReason.STALE_COHORT_SOURCE_TIME

    source_skew = _validator(
        policy=_policy(
            max_receive_age_ms=1_000.0,
            max_source_age_ms=1_000.0,
            max_source_skew_ms=50.0,
        )
    )
    assert _ingest(source_skew, _quote(SYMBOLS[0], receive_monotonic_ns=1_000_000_000)).reason
    assert _ingest(
        source_skew,
        _quote(
            SYMBOLS[1],
            receive_monotonic_ns=1_010_000_000,
            source_epoch=1_700_000_000.04,
            receive_epoch=1_700_000_000.05,
        ),
    ).reason
    result = _ingest(
        source_skew,
        _quote(
            SYMBOLS[2],
            receive_monotonic_ns=1_020_000_000,
            source_epoch=1_700_000_000.08,
            receive_epoch=1_700_000_000.09,
        ),
    )
    assert result.reason == bt.feeds.CtpCohortReason.BLOCKED_SOURCE_SKEW


def test_duplicate_and_out_of_order_evidence_invalidates_a_round_and_requires_fresh_legs():
    validator = _validator()
    assert _ingest(
        validator, _quote(SYMBOLS[0], sequence=1, receive_monotonic_ns=1_000_000_000)
    ).reason

    duplicate = _ingest(
        validator, _quote(SYMBOLS[0], sequence=1, receive_monotonic_ns=1_010_000_000)
    )
    assert duplicate.reason == bt.feeds.CtpCohortReason.DUPLICATE_OR_OUT_OF_ORDER
    receive_reversed = _ingest(
        validator,
        _quote(
            SYMBOLS[0],
            sequence=2,
            receive_monotonic_ns=999_000_000,
            source_epoch=1_700_000_000.01,
            receive_epoch=1_700_000_000.02,
        ),
    )
    assert receive_reversed.reason == bt.feeds.CtpCohortReason.OUT_OF_ORDER_RECEIVE_TIME
    source_reversed = _ingest(
        validator,
        _quote(
            SYMBOLS[0],
            sequence=2,
            receive_monotonic_ns=1_020_000_000,
            source_epoch=1_699_999_999.99,
            receive_epoch=1_700_000_000.02,
        ),
    )
    assert source_reversed.reason == bt.feeds.CtpCohortReason.OUT_OF_ORDER_SOURCE_TIME

    assert _ingest(validator, _quote(SYMBOLS[1], receive_monotonic_ns=1_010_000_000)).reason == (
        bt.feeds.CtpCohortReason.WAITING_FOR_LEGS
    )
    assert _ingest(validator, _quote(SYMBOLS[2], receive_monotonic_ns=1_020_000_000)).reason == (
        bt.feeds.CtpCohortReason.WAITING_FOR_LEGS
    )
    result = _ingest(
        validator,
        _quote(
            SYMBOLS[0],
            sequence=2,
            receive_monotonic_ns=1_030_000_000,
            source_epoch=1_700_000_000.03,
            receive_epoch=1_700_000_000.04,
        ),
    )
    assert result.accepted
    assert result.cohort is not None
    assert result.cohort.quote_for(SYMBOLS[0]).ingest_seq == 2


def test_two_legs_are_supported_and_event_objects_may_use_public_ctp_aliases():
    symbols = SYMBOLS[:2]
    validator = _validator(symbols=symbols)
    first = _quote(symbols[0], receive_monotonic_ns=1_000_000_000)
    assert _ingest(validator, first).reason == bt.feeds.CtpCohortReason.WAITING_FOR_LEGS
    second = _quote(symbols[1], receive_monotonic_ns=1_010_000_000)
    second["InstrumentID"] = second.pop("symbol")
    second["ExchangeID"] = second.pop("exchange")
    second["BidPrice1"] = second.pop("bid_price")
    second["AskPrice1"] = second.pop("ask_price")
    second["BidVolume1"] = second.pop("bid_volume")
    second["AskVolume1"] = second.pop("ask_volume")
    second["LastPrice"] = second.pop("price")
    second["LowerLimitPrice"] = second.pop("lower_limit_price")
    second["UpperLimitPrice"] = second.pop("upper_limit_price")
    second["TradingDay"] = second.pop("trading_day")

    result = _ingest(validator, SimpleNamespace(**second))

    assert result.accepted
    assert result.cohort is not None
    assert tuple(result.cohort.quotes) == symbols


def test_ingest_requires_trusted_same_domain_now_evidence_without_reference_fallback():
    validator = _validator()
    quote = _quote(SYMBOLS[0], receive_monotonic_ns=1_000_000_000)

    missing = validator.ingest(quote)
    assert missing.reason == bt.feeds.CtpCohortReason.TRUSTED_NOW_REQUIRED

    unverified = validator.ingest(
        quote,
        now={
            "now_monotonic_ns": 1_000_000_000,
            "now_epoch": 1_700_000_000.01,
            "clock_domain_id": "ctp-sdk-process-monotonic",
            "receive_clock_error_ms": 1.0,
            "receive_clock_quality": "unknown",
            "freshness_verified": True,
        },
    )
    assert unverified.reason == bt.feeds.CtpCohortReason.RECEIVE_CLOCK_UNVERIFIED

    excessive_error = validator.ingest(
        quote,
        now={
            "now_monotonic_ns": 1_000_000_000,
            "now_epoch": 1_700_000_000.01,
            "clock_domain_id": "ctp-sdk-process-monotonic",
            "receive_clock_error_ms": 5.1,
            "receive_clock_quality": "verified",
            "freshness_verified": True,
        },
    )
    assert excessive_error.reason == bt.feeds.CtpCohortReason.RECEIVE_CLOCK_ERROR_INVALID

    stale_clock_domain = _ingest(
        validator,
        quote,
        now=_now_for(quote, clock_domain_id="another-process-monotonic"),
    )
    assert stale_clock_domain.reason == bt.feeds.CtpCohortReason.NOW_CLOCK_DOMAIN_MISMATCH


def test_ingest_rejects_queue_delayed_quote_using_absolute_caller_now():
    validator = _validator()
    quote = _quote(SYMBOLS[0], receive_monotonic_ns=1_000_000_000)
    delayed_now = _now_for(
        quote,
        now_monotonic_ns=1_300_000_000,
        now_epoch=1_700_000_000.31,
    )

    result = _ingest(validator, quote, now=delayed_now)

    assert result.reason == bt.feeds.CtpCohortReason.STALE_COHORT_RECEIVE_TIME


def test_ingest_rejects_wall_clock_queue_delay_even_when_monotonic_age_is_fresh():
    validator = _validator()
    quote = _quote(SYMBOLS[0], receive_monotonic_ns=1_000_000_000)
    delayed_wall_now = _now_for(
        quote,
        now_monotonic_ns=1_000_000_000,
        now_epoch=1_700_000_000.31,
    )

    result = _ingest(validator, quote, now=delayed_wall_now)

    assert result.reason == bt.feeds.CtpCohortReason.STALE_COHORT_RECEIVE_TIME


def test_validate_at_rechecks_confirmed_cohort_before_submission_and_expires_it():
    validator = _validator()
    admitted = _admit_initial(validator)
    assert admitted.accepted

    fresh_now = CtpCohortNow(
        now_monotonic_ns=1_020_000_000,
        now_epoch=1_700_000_000.01,
        clock_domain_id="ctp-sdk-process-monotonic",
        receive_clock_error_ms=1.0,
    )
    assert validator.validate_at(now=fresh_now).accepted

    expired_now = CtpCohortNow(
        now_monotonic_ns=1_400_000_000,
        now_epoch=1_700_000_000.41,
        clock_domain_id="ctp-sdk-process-monotonic",
        receive_clock_error_ms=1.0,
    )
    expired = validator.recheck(now=expired_now)
    assert expired.reason == bt.feeds.CtpCohortReason.STALE_COHORT_RECEIVE_TIME
    assert (
        validator.validate_at(now=expired_now).reason
        == bt.feeds.CtpCohortReason.NO_CONFIRMED_COHORT
    )


def test_public_cohort_constructor_rejects_mismatched_mapping_keys_and_metadata():
    validator = _validator()
    result = _admit_initial(validator)
    assert result.cohort is not None
    cohort = result.cohort
    quote = cohort.quote_for(SYMBOLS[0])
    common = {
        "exchange": cohort.exchange,
        "trading_day": cohort.trading_day,
        "action_day": cohort.action_day,
        "connection_generation": cohort.connection_generation,
        "subscription_epoch": cohort.subscription_epoch,
        "clock_domain_id": cohort.clock_domain_id,
        "rules_hash": cohort.rules_hash,
        "cohort_id": cohort.cohort_id,
    }

    with pytest.raises(ValueError, match="mapping keys"):
        bt.feeds.CtpQuoteCohort(quotes={"wrong": quote}, **common)
    with pytest.raises(ValueError, match="metadata"):
        bt.feeds.CtpQuoteCohort(
            quotes=cohort.quotes,
            exchange="DCE",
            **{key: value for key, value in common.items() if key != "exchange"},
        )


def test_constructor_rejects_non_frozen_invalid_leg_sets_and_unknown_policy_types():
    leg = bt.feeds.CtpCohortLeg(symbol=SYMBOLS[0], exchange="CZCE", price_tick=0.5)
    with pytest.raises(ValueError, match="two or three"):
        bt.feeds.CtpQuoteCohortValidator(
            expected_legs=(leg,), expected_rules_hash=RULES_HASH, policy=_policy()
        )
    with pytest.raises(ValueError, match="one exchange"):
        bt.feeds.CtpQuoteCohortValidator(
            expected_legs=(
                leg,
                bt.feeds.CtpCohortLeg(symbol=SYMBOLS[1], exchange="DCE", price_tick=0.5),
            ),
            expected_rules_hash=RULES_HASH,
            policy=_policy(),
        )
    with pytest.raises(TypeError, match="policy"):
        bt.feeds.CtpQuoteCohortValidator(
            expected_legs=(leg, bt.feeds.CtpCohortLeg(SYMBOLS[1], "CZCE", 0.5)),
            expected_rules_hash=RULES_HASH,
            policy=object(),
        )


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("source", "unknown", "QUOTE_SOURCE_MISSING"),
        ("event_time_source", "unverified", "EVENT_TIME_SOURCE_MISSING"),
        ("rules_hash", "unknown", "RULES_HASH_MISMATCH"),
        ("clock_domain_id", "n/a", "CLOCK_DOMAIN_UNKNOWN"),
    ],
)
def test_placeholder_provenance_identity_never_becomes_a_matching_identity(field, value, reason):
    validator = _validator()
    quote = _quote(SYMBOLS[0], **{field: value})

    result = validator.ingest(
        quote,
        now=CtpCohortNow(
            now_monotonic_ns=1_000_000_000,
            now_epoch=1_700_000_000.01,
            clock_domain_id="ctp-sdk-process-monotonic",
            receive_clock_error_ms=1.0,
        ),
    )

    assert result.reason == getattr(bt.feeds.CtpCohortReason, reason)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"stale": True}, "QUOTE_STREAM_UNREADY"),
        ({"stale": False, "stale_reason": "recovery_pending_validation"}, "QUOTE_STREAM_UNREADY"),
    ],
)
def test_stale_or_recovery_pending_quote_never_enters_a_cohort(overrides, reason):
    validator = _validator()

    result = _ingest(validator, _quote(SYMBOLS[0], **overrides))

    assert result.reason == getattr(bt.feeds.CtpCohortReason, reason)


def test_expected_rules_hash_and_trusted_now_reject_placeholder_identity():
    with pytest.raises(ValueError, match="provenance identity"):
        bt.feeds.CtpQuoteCohortValidator(
            expected_legs=(
                bt.feeds.CtpCohortLeg(SYMBOLS[0], "CZCE", 0.5),
                bt.feeds.CtpCohortLeg(SYMBOLS[1], "CZCE", 0.5),
            ),
            expected_rules_hash="unknown",
            policy=_policy(),
        )
    with pytest.raises(ValueError, match="provenance identity"):
        CtpCohortNow(
            now_monotonic_ns=1_000_000_000,
            now_epoch=1_700_000_000.01,
            clock_domain_id="unknown",
            receive_clock_error_ms=1.0,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"instrument_id": "OTHER"},
        {"exchange_id": "DCE"},
        {"asset_type": "future", "contract_type": "option"},
    ],
)
def test_identity_alias_conflicts_are_rejected_before_cohort_admission(overrides):
    validator = _validator()

    result = _ingest(validator, _quote(SYMBOLS[0], **overrides))

    assert result.reason == bt.feeds.CtpCohortReason.QUOTE_IDENTITY_CONFLICT


def test_expected_leg_asset_type_rejects_mislabeled_future_and_option_quotes():
    validator = bt.feeds.CtpQuoteCohortValidator(
        expected_legs=(
            bt.feeds.CtpCohortLeg(SYMBOLS[0], "CZCE", 0.5, "future"),
            bt.feeds.CtpCohortLeg(SYMBOLS[1], "CZCE", 0.5, "option"),
            bt.feeds.CtpCohortLeg(SYMBOLS[2], "CZCE", 0.5, "option"),
        ),
        expected_rules_hash=RULES_HASH,
        policy=_policy(),
    )

    future_mismatch = _ingest(validator, _quote(SYMBOLS[0], asset_type="option"))
    option_mismatch = _ingest(validator, _quote(SYMBOLS[1], asset_type="future"))

    assert future_mismatch.reason == bt.feeds.CtpCohortReason.ASSET_TYPE_MISMATCH
    assert option_mismatch.reason == bt.feeds.CtpCohortReason.ASSET_TYPE_MISMATCH


def _admit_scope(validator, *, generation, epoch, receive_monotonic_ns, source_epoch):
    """Admit a fresh three-leg scope and return its last quote for rechecks."""

    last = None
    for index, symbol in enumerate(SYMBOLS):
        last = _quote(
            symbol,
            sequence=1,
            connection_generation=generation,
            subscription_epoch=epoch,
            receive_monotonic_ns=receive_monotonic_ns + index * 10_000_000,
            source_epoch=source_epoch + index * 0.01,
            receive_epoch=source_epoch + index * 0.01 + 0.001,
        )
        result = _ingest(validator, last)
    assert result.accepted
    return last


@pytest.mark.parametrize(
    ("newer_scope", "delayed_scope"),
    [((7, 13), (7, 12)), ((8, 1), (7, 99))],
)
def test_delayed_unseen_scope_cannot_roll_back_a_newer_scope(newer_scope, delayed_scope):
    validator = _validator(policy=_policy(max_receive_age_ms=10_000.0, max_source_age_ms=10_000.0))
    _admit_scope(
        validator,
        generation=7,
        epoch=11,
        receive_monotonic_ns=1_000_000_000,
        source_epoch=1_700_000_000.0,
    )
    current_last = _admit_scope(
        validator,
        generation=newer_scope[0],
        epoch=newer_scope[1],
        receive_monotonic_ns=1_100_000_000,
        source_epoch=1_700_000_001.0,
    )

    delayed = _ingest(
        validator,
        _quote(
            SYMBOLS[0],
            connection_generation=delayed_scope[0],
            subscription_epoch=delayed_scope[1],
            receive_monotonic_ns=1_200_000_000,
            source_epoch=1_700_000_002.0,
            receive_epoch=1_700_000_002.001,
        ),
    )

    assert delayed.reason == bt.feeds.CtpCohortReason.RETIRED_CONNECTION_SCOPE
    assert validator.validate_at(now=_now_for(current_last)).accepted
