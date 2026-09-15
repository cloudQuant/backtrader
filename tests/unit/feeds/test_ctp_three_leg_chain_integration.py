"""Zero-write CTP Quote V2 three-leg Store/Feed/Cerebro integration tests.

The parent SDK attestation itself belongs to ``bt_api_py``.  These tests use
already-attested in-memory V2 events to prove the root-repository boundary:
the Store retains their typed evidence, the Feed owns the decision-time field,
and a strategy can pass the resulting evidence into the public cohort
validator without creating an order or touching a network transport.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections import deque
from copy import deepcopy

import backtrader as bt
import pytest

from backtrader.stores.btapistore import BtApiStore

VENUE = "CTP___FUTURE"
EXCHANGE = "CZCE"
CLOCK_DOMAIN = "fixture-ctp-parent-monotonic-v1"
RULES_HASH = "fixture-ctp-three-leg-rules-v1"
FUTURE = "FG701"
CALL = "FG701C970"
PUT = "FG701P970"
BASE_TIME = dt.datetime(2026, 9, 10, 1, 0, tzinfo=dt.timezone.utc)


class FixedClock:
    """A deterministic Feed clock in the fake parent clock domain."""

    def __init__(self, monotonic_ns):
        self._monotonic_ns = monotonic_ns

    def monotonic_ns(self):
        return self._monotonic_ns


class InMemoryCtpQuoteSdk:
    """Small read-only public-SDK double; all outbound order paths fail loudly."""

    exchange_kwargs = {VENUE: {}}

    def __init__(self, events):
        self._events = deque(deepcopy(list(events)))
        self.subscriptions = []
        self.write_attempts = []
        self.closed = False

    def subscribe(self, name, topics):
        self.subscriptions.append((name, deepcopy(topics)))

    def get_ctp_session_state(self, *, exchange_name):
        assert exchange_name == VENUE
        return {
            "connected": True,
            "ready": True,
            "read_only_ready": True,
            "auth_state": "authenticated",
            "login_state": "logged_in",
        }

    def get_all_balances(self, *, normalized):
        assert normalized is True
        return {VENUE: {"cash": 0.0, "value": 0.0, "currency": "CNY"}}

    def get_portfolio_balance(self, *, venue_balances):
        assert VENUE in venue_balances
        return {"cash": 0.0, "value": 0.0}

    def poll_events(self, venue, *, max_raw_items, coalesce_market_snapshots):
        assert venue == VENUE
        del max_raw_items, coalesce_market_snapshots
        events = list(self._events)
        self._events.clear()
        return events

    def poll_event(self, _venue):
        raise AssertionError("batch-capable SDK must use poll_events")

    def submit_order(self, *args, **kwargs):
        self.write_attempts.append(("submit_order", args, kwargs))
        raise AssertionError("three-leg quote validation must never submit an order")

    def cancel_order(self, *args, **kwargs):
        self.write_attempts.append(("cancel_order", args, kwargs))
        raise AssertionError("three-leg quote validation must never cancel an order")

    def close(self):
        self.closed = True


def _quote(
    symbol,
    *,
    asset_type,
    last,
    ingest_seq,
    execution_eligible=True,
):
    """Return a parent-attested, strict V2 quote with forged raw decision fields."""

    event_time = BASE_TIME + dt.timedelta(milliseconds=ingest_seq)
    receive_time = event_time + dt.timedelta(microseconds=100)
    receive_monotonic_ns = 10_000_000_000 + ingest_seq * 1_000
    parent_now_monotonic_ns = receive_monotonic_ns + 100
    return {
        "kind": "tick",
        "symbol": symbol,
        "instrument_id": symbol,
        "exchange": EXCHANGE,
        "exchange_id": EXCHANGE,
        "asset_type": asset_type,
        "timestamp": event_time.timestamp(),
        "local_time": receive_time.timestamp(),
        "received_wall_time": receive_time.timestamp(),
        "received_monotonic_ns": receive_monotonic_ns,
        "clock_domain_id": CLOCK_DOMAIN,
        "sequence": ingest_seq,
        "snapshot_or_delta": "snapshot",
        "continuity_status": "continuous",
        "stale": False,
        "stale_reason": "",
        "source": "fixture.ctp.parent-attested",
        "event_id": f"fixture-v2-{symbol}-{ingest_seq}",
        "price": last,
        "volume": 1.0,
        "delta_volume": 1.0,
        "cum_volume": 100.0 + ingest_seq,
        "cumulative_volume": 100.0 + ingest_seq,
        "direction": "buy",
        "bid_price": last - 1.0,
        "ask_price": last,
        "bid_volume": 2.0,
        "ask_volume": 3.0,
        "schema_version": "ctp.quote.v2",
        "volume_semantics": "delta",
        "volume_complete": True,
        "volume_quality": "CONTINUOUS",
        "trading_day": "20260910",
        "action_day": "20260910",
        "event_time_utc": event_time,
        "recv_time_utc": receive_time,
        "recv_monotonic_ns": receive_monotonic_ns,
        "connection_generation": 9,
        "ingest_seq": ingest_seq,
        "subscription_epoch": 5,
        "rules_hash": RULES_HASH,
        "quality_flags": (),
        "event_time_source": "action_day_update_time",
        "source_clock_quality": "verified",
        "receive_clock_quality": "verified",
        "source_clock_error_ms": 0.1,
        "receive_clock_error_ms": 0.1,
        "freshness_verified": True,
        "execution_eligible": execution_eligible,
        # Parent receipt evidence is allowed to cross the Store boundary.
        "cohort_now_monotonic_ns": parent_now_monotonic_ns,
        "cohort_now_epoch": receive_time.timestamp() + 0.000001,
        "cohort_now_clock_domain_id": CLOCK_DOMAIN,
        "cohort_now_receive_clock_error_ms": 0.1,
        "cohort_now_receive_clock_quality": "verified",
        "cohort_now_freshness_verified": True,
        # These fields are intentionally hostile input.  The Store never
        # transports them and the Feed must own them at strategy dispatch.
        "cohort_decision_now_monotonic_ns": 1,
        "cohort_decision_now_epoch": 1.0,
        "cohort_decision_now_clock_domain_id": "forged-transport-domain",
        "cohort_decision_now_receive_clock_error_ms": 0.0,
        "cohort_decision_now_receive_clock_quality": "verified",
        "cohort_decision_now_freshness_verified": True,
        "lower_limit_price": 1.0,
        "upper_limit_price": 9_999.0,
    }


def _expected_validator():
    return bt.feeds.CtpQuoteCohortValidator(
        expected_legs=(
            bt.feeds.CtpCohortLeg(FUTURE, EXCHANGE, 1.0, asset_type="future"),
            bt.feeds.CtpCohortLeg(CALL, EXCHANGE, 1.0, asset_type="option"),
            bt.feeds.CtpCohortLeg(PUT, EXCHANGE, 1.0, asset_type="option"),
        ),
        expected_rules_hash=RULES_HASH,
        policy=bt.feeds.CtpCohortPolicy(
            max_receive_age_ms=10.0,
            max_receive_skew_ms=10.0,
            max_source_age_ms=10.0,
            max_source_skew_ms=10.0,
            max_source_clock_error_ms=1.0,
            max_receive_clock_error_ms=1.0,
        ),
    )


def _decision_now_from_tick(tick):
    """Build validator input only from Feed-owned decision-boundary fields."""

    fields = (
        "cohort_decision_now_monotonic_ns",
        "cohort_decision_now_epoch",
        "cohort_decision_now_clock_domain_id",
        "cohort_decision_now_receive_clock_error_ms",
        "cohort_decision_now_receive_clock_quality",
        "cohort_decision_now_freshness_verified",
    )
    if any(getattr(tick, field, None) is None for field in fields):
        return None
    return bt.feeds.CtpCohortNow(
        now_monotonic_ns=tick.cohort_decision_now_monotonic_ns,
        now_epoch=tick.cohort_decision_now_epoch,
        clock_domain_id=tick.cohort_decision_now_clock_domain_id,
        receive_clock_error_ms=tick.cohort_decision_now_receive_clock_error_ms,
        receive_clock_quality=tick.cohort_decision_now_receive_clock_quality,
        freshness_verified=tick.cohort_decision_now_freshness_verified,
    )


def _run_three_leg_chain(*, events, decision_provider):
    """Run three fake CTP symbols through Store, Feed and a real strategy callback."""

    sdk = InMemoryCtpQuoteSdk(events)
    store = BtApiStore(
        provider="btapi",
        api=sdk,
        config={
            "exchange_kwargs": {VENUE: {}},
            "symbol_routes": dict.fromkeys((FUTURE, CALL, PUT), VENUE),
        },
    )
    clock = FixedClock(10_000_100_000)
    feeds = [
        store.getdata(
            dataname=symbol,
            timeframe=bt.TimeFrame.Ticks,
            compression=1,
            backfill_start=False,
            qcheck=0,
            price_tick=1.0,
            clock=clock,
            ctp_decision_now_provider=decision_provider,
        )
        for symbol in (FUTURE, CALL, PUT)
    ]

    class CohortStrategy(bt.Strategy):
        params = (("validator", None),)

        def __init__(self):
            self.ticks = []
            self.results = []
            self.cohorts = []

        def notify_tick(self, tick):
            self.ticks.append(tick)
            result = self.p.validator.ingest(tick, now=_decision_now_from_tick(tick))
            self.results.append(result)
            if result.cohort is not None:
                self.cohorts.append(result.cohort)
            # This is a finite in-memory test source.  Stopping after all
            # three callbacks makes no rejected case depend on a live EOF.
            if len(self.ticks) == 3:
                self.cerebro.runstop()

    cerebro = bt.Cerebro(stdstats=False, quicknotify=True)
    for feed in feeds:
        cerebro.adddata(feed)
    cerebro.addstrategy(CohortStrategy, validator=_expected_validator())

    timed_out = []

    def stop_if_regressed():
        timed_out.append(True)
        cerebro.runstop()

    watchdog = threading.Timer(2.0, stop_if_regressed)
    watchdog.daemon = True
    watchdog.start()
    try:
        [strategy] = cerebro.run(preload=False, runonce=False)
    finally:
        watchdog.cancel()

    assert not timed_out
    return sdk, store, strategy


def _provider(tick):
    """Supply an explicit same-domain clock at Feed strategy-dispatch time."""

    return bt.feeds.CtpCohortNow(
        now_monotonic_ns=tick.recv_monotonic_ns + 100_000,
        now_epoch=tick.recv_time_utc.timestamp() + 0.0001,
        clock_domain_id=tick.clock_domain_id,
        receive_clock_error_ms=0.1,
    )


def _events(*, execution_eligible=True):
    return (
        _quote(
            FUTURE,
            asset_type="future",
            last=1_800.0,
            ingest_seq=1,
            execution_eligible=execution_eligible,
        ),
        _quote(
            CALL,
            asset_type="option",
            last=100.0,
            ingest_seq=2,
            execution_eligible=execution_eligible,
        ),
        _quote(
            PUT, asset_type="option", last=80.0, ingest_seq=3, execution_eligible=execution_eligible
        ),
    )


def test_parent_attested_v2_three_leg_chain_reaches_one_cohort_without_writes():
    sdk, store, strategy = _run_three_leg_chain(events=_events(), decision_provider=_provider)

    assert [tick.symbol for tick in strategy.ticks] == [FUTURE, CALL, PUT]
    assert len(strategy.cohorts) == 1
    assert strategy.results[-1].accepted is True
    assert all(
        result.reason == bt.feeds.CtpCohortReason.WAITING_FOR_LEGS
        for result in strategy.results[:2]
    )
    assert len(sdk.subscriptions) == 3
    assert sdk.write_attempts == []
    assert sdk.closed is True
    assert store._sdk_execution_config["market_data_only"] is True

    for tick in strategy.ticks:
        raw = next(event for event in _events() if event["symbol"] == tick.symbol)
        assert tick.schema_version == "ctp.quote.v2"
        assert tick.execution_eligible is True
        assert tick.rules_hash == RULES_HASH
        assert tick.source == "fixture.ctp.parent-attested"
        assert tick.cohort_now_monotonic_ns == raw["cohort_now_monotonic_ns"]
        assert tick.cohort_now_epoch == pytest.approx(raw["cohort_now_epoch"])
        assert tick.cohort_now_clock_domain_id == CLOCK_DOMAIN
        assert tick.cohort_now_receive_clock_error_ms == pytest.approx(0.1)
        assert tick.cohort_now_receive_clock_quality == "verified"
        assert tick.cohort_now_freshness_verified is True
        assert tick.cohort_decision_now_monotonic_ns == tick.recv_monotonic_ns + 100_000
        assert tick.cohort_decision_now_epoch == pytest.approx(
            tick.recv_time_utc.timestamp() + 0.0001
        )
        assert tick.cohort_decision_now_clock_domain_id == CLOCK_DOMAIN
        assert tick.cohort_decision_now_clock_domain_id != "forged-transport-domain"
        assert tick.cohort_decision_now_receive_clock_error_ms == pytest.approx(0.1)
        assert tick.cohort_decision_now_receive_clock_quality == "verified"
        assert tick.cohort_decision_now_freshness_verified is True


def test_three_leg_chain_rejects_parent_execution_ineligible_quotes_without_writes():
    sdk, _, strategy = _run_three_leg_chain(
        events=_events(execution_eligible=False),
        decision_provider=_provider,
    )

    assert len(strategy.ticks) == 3
    assert strategy.cohorts == []
    assert [result.reason for result in strategy.results] == [
        bt.feeds.CtpCohortReason.QUOTE_QUALITY_FLAGS_PRESENT,
        bt.feeds.CtpCohortReason.QUOTE_QUALITY_FLAGS_PRESENT,
        bt.feeds.CtpCohortReason.QUOTE_QUALITY_FLAGS_PRESENT,
    ]
    assert all(tick.execution_eligible is False for tick in strategy.ticks)
    assert all("UPSTREAM_EXECUTION_INELIGIBLE" in tick.quality_flags for tick in strategy.ticks)
    assert sdk.write_attempts == []
    assert sdk.closed is True


def test_three_leg_chain_preserves_contract_identity_aliases_and_rejects_a_conflict():
    """Store must not erase a parent identity conflict before cohort validation."""

    events = list(_events())
    events[0].update(
        product_class="2",
        contract_type="option",
        option_type="call",
        underlying_instrument="FG701",
        strike_price=970.0,
    )
    sdk, _, strategy = _run_three_leg_chain(events=events, decision_provider=_provider)

    future = strategy.ticks[0]
    assert future.product_class == "2"
    assert future.contract_type == "option"
    assert future.option_type == "call"
    assert future.underlying_instrument == "FG701"
    assert future.strike_price == pytest.approx(970.0)
    assert strategy.results[0].reason == bt.feeds.CtpCohortReason.QUOTE_IDENTITY_CONFLICT
    assert strategy.cohorts == []
    assert sdk.write_attempts == []
    assert sdk.closed is True


def test_three_leg_chain_rejects_missing_decision_provider_and_clears_forged_transport_time():
    sdk, _, strategy = _run_three_leg_chain(events=_events(), decision_provider=None)

    assert len(strategy.ticks) == 3
    assert strategy.cohorts == []
    assert [result.reason for result in strategy.results] == [
        bt.feeds.CtpCohortReason.TRUSTED_NOW_REQUIRED,
        bt.feeds.CtpCohortReason.TRUSTED_NOW_REQUIRED,
        bt.feeds.CtpCohortReason.TRUSTED_NOW_REQUIRED,
    ]
    for tick in strategy.ticks:
        assert tick.cohort_decision_now_monotonic_ns is None
        assert tick.cohort_decision_now_epoch is None
        assert tick.cohort_decision_now_clock_domain_id is None
        assert tick.cohort_decision_now_receive_clock_error_ms is None
        assert tick.cohort_decision_now_receive_clock_quality is None
        assert tick.cohort_decision_now_freshness_verified is None
    assert sdk.write_attempts == []
    assert sdk.closed is True
