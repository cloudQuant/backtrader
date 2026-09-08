from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from importlib import import_module
import os
from types import SimpleNamespace

import pytest

from bt_api_py import CrossVenueLeg as InstrumentRule
from bt_api_py import Freshness, FundingSnapshot

hft = import_module("examples.012_2_event_driven_cross_exchange.strategy")
D = Decimal


def rules(fee="0"):
    return {
        "okx": InstrumentRule(D(".01"), D("1"), D("1"), D("0"), D(".1"), D(fee)),
        "binance": InstrumentRule(D("1"), D(".001"), D(".001"), D("0"), D(".1"), D(fee)),
    }


def explicit_funding():
    return {venue: (D("0"), D("99999999999")) for venue in hft.VENUE_SYMBOLS}


def typed_funding_pair(
    *,
    next_time="2000",
    stale=False,
    available=True,
    rate=".0001",
    exchange_names=None,
    cache_age="1",
):
    exchange_names = exchange_names or {venue: venue for venue in hft.VENUE_SYMBOLS}
    return {
        venue: {
            "available": available,
            "unavailable_reason": None if available else "funding_unavailable",
            "exchange_name": exchange_names[venue],
            "symbol": hft.VENUE_SYMBOLS[venue],
            "rate": D(rate),
            "next_funding_time": datetime.fromtimestamp(float(next_time), tz=UTC),
            "settlement_interval_seconds": 28800,
            "source": "exchange",
            "freshness": {
                "observed_at": datetime.fromtimestamp(1, tz=UTC),
                "source": "exchange",
                "stale": stale,
            },
            "cache_age_seconds": D(cache_age),
        }
        for venue in hft.VENUE_SYMBOLS
    }


def risk(**changes):
    base = hft.EventDrivenRisk(
        depth_fraction=D("1"),
        exit_reserve_bps=D("0"),
        latency_reserve_bps=D("0"),
        failure_reserve_bps=D("0"),
        model_buffer_bps=D("0"),
        maximum_adverse_markout_bps=D("100"),
        minimum_markout_samples=D("0"),
    )
    return replace(base, **changes)


def qualified_models(rule_set=None, *, path_p99=".1"):
    rule_set = rule_set or rules()
    models = []
    for direction in (("okx", "binance"), ("binance", "okx")):
        fee_bucket = hft.event_fee_bucket(rule_set, *direction)
        for first_venue in direction:
            for depth_bucket in ("1x_to_2x", "2x_to_5x", "5x_to_10x", "10x_plus"):
                payload = {
                    "direction": direction,
                    "first_venue": first_venue,
                    "fee_bucket": fee_bucket,
                    "depth_bucket": depth_bucket,
                    "end_to_end_path_p99_seconds": D(path_p99),
                    "sample_count": 100,
                    "qualified": True,
                    "source_data_sha256": "a" * 64,
                    "evidence_role": hft.EVENT_PATH_EVIDENCE_ROLE,
                    "latency_scope": hft.EVENT_PATH_LATENCY_SCOPE,
                }
                payload["model_sha256"] = hft.event_path_model_sha256(payload)
                models.append(hft.EventPathQualification(**payload))
    return tuple(models)


def event_engine(rule_set=None, risk_config=None, venue_stats=None, *, models=None):
    rule_set = rule_set or rules()
    risk_config = risk_config or risk()
    return hft.EventArbitrageEngine(
        rule_set,
        risk_config,
        venue_stats,
        qualified_models(rule_set) if models is None else models,
    )


def book(
    venue,
    bid,
    ask,
    now,
    sequence,
    previous=None,
    recovery=False,
    size=".1",
    snapshot_or_delta="snapshot",
    continuity_status=None,
):
    if continuity_status is None:
        continuity_status = "snapshot" if snapshot_or_delta == "snapshot" else "continuous"
    return hft.EventBook(
        venue=venue,
        bids=((D(bid), D(size)),),
        asks=((D(ask), D(size)),),
        exchange_time=D(now),
        receive_time=D(now),
        sequence=sequence,
        previous_sequence=previous,
        snapshot_or_delta=snapshot_or_delta,
        continuity_status=continuity_status,
        recovery_snapshot=recovery,
    )


def update_pair(engine, now, sequence, *, binance=("101", "101.1"), previous=None):
    engine.update_book(book("okx", "99.9", "100", now, sequence, previous))
    engine.update_book(book("binance", *binance, now, sequence, previous))


def orderbook_event(venue, bid, ask, now, sequence):
    native_size = D("10") if venue == "okx" else D(".1")
    return SimpleNamespace(
        symbol=hft.VENUE_SYMBOLS[venue],
        bids=((D(bid), native_size),),
        asks=((D(ask), native_size),),
        exchange_time=D(now),
        timestamp=D(now),
        received_monotonic_ns=int(D(now) * D("1000000000")) + 1,
        sequence=sequence,
        previous_sequence=None,
        snapshot_or_delta="snapshot",
        continuity_status="snapshot",
        recovery_snapshot=True,
        stale=False,
        clock_domain_id="process-monotonic",
    )


def reconcile_snapshot(positions=None, summary_changes=None, **changes):
    summary = {
        "unknown_ids": [],
        "fee_unresolved_orders": [],
        "trading_blocked": False,
        "active_orders": 0,
        "generation": 1,
        "fencing_epoch": 1,
        "evidence_complete": True,
    }
    summary.update(summary_changes or {})
    snapshot = {
        "positions": (
            positions
            if positions is not None
            else {
                "okx": {"long": 0, "short": 0},
                "binance": {"long": 0, "short": 0},
            }
        ),
        "open_orders": [],
        "configured_venues": ["okx", "binance"],
        "reconciled_venues": ["okx", "binance"],
        "generation": 1,
        "fencing_epoch": 1,
        "as_of_monotonic_ns": 10_000_000_000,
        "unknown_ids": [],
        "trading_blocked": False,
        "evidence_complete": True,
        "evidence_errors": [],
        "execution_summary": summary,
    }
    snapshot.update(changes)
    return snapshot


def strategy_stub(risk_config=None):
    strategy = object.__new__(hft.CrossExchangeArbitrageStrategy)
    strategy.rules = rules()
    strategy.risk = risk_config or risk()
    strategy.engine = event_engine(strategy.rules, strategy.risk)
    strategy.pending_order = None
    strategy.pair_state = None
    strategy.known_order_refs = set()
    strategy.processed_order_refs = set()
    strategy.order_records = {}
    strategy.cancel_requested = False
    strategy.awaiting_reconciliation = False
    strategy.remote_flat_proven = False
    strategy.leg_deadline = None
    strategy.cancel_deadline = None
    strategy.pair_deadline = None
    strategy.unhedged_started = None
    strategy.unhedged_durations = []
    strategy._now = lambda: D("10")
    strategy.p = SimpleNamespace(
        funding=explicit_funding(),
        funding_snapshot_provider=None,
        funding_exchange_routes=None,
        funding_max_age_seconds=D("30"),
        account_risk_ledger=None,
    )
    strategy.broker = SimpleNamespace(
        request_reconcile=lambda: {"queued": True},
        getvalue=lambda: 100,
    )
    strategy._ensure_runtime_state()
    return strategy


def test_event_runtime_funding_pair_fails_closed_and_recovers():
    strategy = strategy_stub()
    current = {"value": typed_funding_pair()}
    strategy._wall_now = lambda: D("1000")
    strategy.p = SimpleNamespace(
        funding=None,
        funding_snapshot_provider=lambda: current["value"],
        account_risk_ledger=None,
    )

    assert strategy._refresh_funding_gate(opening=True) is True
    current["value"] = typed_funding_pair(available=False)
    assert strategy._refresh_funding_gate(opening=True) is False
    assert strategy.funding_evidence_status == "stale_or_unavailable"
    current["value"] = typed_funding_pair(next_time="1005")
    assert strategy._refresh_funding_gate(opening=True) is False
    assert strategy.engine.reject_reasons["funding_entry_window"] == 1
    current["value"] = typed_funding_pair(next_time="2001", rate="-.0003")
    assert strategy._refresh_funding_gate(opening=True) is True
    assert strategy._funding_states["binance"].rate == D("-.0003")


def test_event_runtime_funding_pair_requires_both_venues():
    strategy = strategy_stub()
    strategy._wall_now = lambda: D("1000")
    incomplete = typed_funding_pair()
    incomplete.pop("okx")
    strategy.p = SimpleNamespace(
        funding=None,
        funding_snapshot_provider=lambda: incomplete,
        account_risk_ledger=None,
    )

    assert strategy._refresh_funding_gate(opening=True) is False
    assert strategy.engine.reject_reasons["funding_stale"] == 1


def test_event_funding_expiry_before_hedge_flattens_confirmed_first_leg():
    strategy = strategy_stub()
    intent = SimpleNamespace(long_venue="okx", short_venue="binance")
    exposures = {"okx": ("long", D(".01"))}
    strategy.pair_state = {
        "intent": intent,
        "phase": "hedge",
        "fills": {},
        "exposures": exposures,
    }
    strategy._refresh_funding_gate = lambda **_kwargs: False
    calls = []
    strategy._begin_flatten = lambda current, reason: calls.append((current, reason))

    strategy._submit(
        "binance",
        "sell",
        D(".01"),
        D("101"),
        "hedge",
        position_side="short",
    )

    assert calls == [(exposures, "funding_stale")]


def test_event_funding_expiry_before_first_submit_releases_empty_cycle():
    strategy = strategy_stub()
    strategy.pair_state = {
        "intent": SimpleNamespace(long_venue="okx", short_venue="binance"),
        "phase": "first",
        "fills": {},
        "exposures": {},
    }
    strategy.pair_deadline = D("20")
    strategy.leg_deadline = D("15")
    strategy.cancel_deadline = D("16")
    strategy._refresh_funding_gate = lambda **_kwargs: False

    strategy._submit(
        "okx",
        "buy",
        D(".01"),
        D("100"),
        "first",
        position_side="long",
    )

    assert strategy.pair_state is None
    assert strategy.pair_deadline is None
    assert strategy.leg_deadline is None
    assert strategy.cancel_deadline is None


def test_event_flatten_and_reconcile_progress_without_a_funding_snapshot():
    strategy = strategy_stub()
    strategy.pending_order = SimpleNamespace(ref=1)
    strategy.pair_state = {"phase": "flatten"}
    strategy.awaiting_reconciliation = False
    deadlines = []
    strategy._check_deadlines = lambda: deadlines.append("checked")
    strategy._refresh_funding_gate = lambda **_kwargs: pytest.fail(
        "flatten must not depend on funding refresh"
    )

    strategy.notify_orderbook(SimpleNamespace(symbol=hft.VENUE_SYMBOLS["okx"]))

    assert deadlines == ["checked"]

    strategy.pending_order = None
    strategy.pair_state = {"phase": "reconcile"}
    strategy.awaiting_reconciliation = True
    polls = []
    strategy._poll_remote_reconcile = lambda: polls.append("polled")
    strategy.notify_orderbook(SimpleNamespace(symbol=hft.VENUE_SYMBOLS["binance"]))
    assert polls == ["polled"]


def test_event_funding_provider_binds_sdk_route_identity_and_source_age():
    strategy = strategy_stub()
    routes = {"okx": "OKX___SWAP", "binance": "BINANCE___SWAP"}
    current = {"value": typed_funding_pair(exchange_names=routes)}
    strategy._wall_now = lambda: D("1000")
    strategy.p = SimpleNamespace(
        funding=None,
        funding_snapshot_provider=lambda: current["value"],
        funding_exchange_routes=routes,
        funding_max_age_seconds=D("30"),
        account_risk_ledger=None,
    )

    assert strategy._refresh_funding_gate(opening=True) is True
    current["value"] = typed_funding_pair(exchange_names=routes, cache_age="30.0001")
    assert strategy._refresh_funding_gate(opening=True) is False
    current["value"] = typed_funding_pair(exchange_names={**routes, "okx": "BINANCE___SWAP"})
    assert strategy._refresh_funding_gate(opening=True) is False


def test_event_entry_funding_window_includes_pair_hedge_budget():
    strategy = strategy_stub()
    strategy._wall_now = lambda: D("1000")
    boundary = (
        D("1000")
        + strategy.risk.maximum_holding_seconds
        + strategy.risk.flatten_deadline_seconds
        + strategy.risk.pair_deadline_seconds
        - D(".001")
    )
    strategy.p = SimpleNamespace(
        funding=None,
        funding_snapshot_provider=lambda: typed_funding_pair(next_time=str(boundary)),
        funding_exchange_routes=None,
        funding_max_age_seconds=D("30"),
        account_risk_ledger=None,
    )

    assert strategy._refresh_funding_gate(opening=True) is False
    assert strategy.engine.reject_reasons["funding_entry_window"] == 1


def test_event_notify_idle_exits_active_pair_when_funding_schedule_moves_earlier():
    engine = event_engine(rules(), risk())
    intent = mature(engine)
    engine.mark_open(intent, D(".5"))
    strategy = strategy_stub(engine.risk)
    strategy.engine = engine
    strategy.pending_order = None
    strategy.pair_state = None
    strategy.awaiting_reconciliation = False
    strategy._now = lambda: D(".5")
    strategy._wall_now = lambda: D("1000")
    strategy.p = SimpleNamespace(
        funding=None,
        funding_snapshot_provider=lambda: typed_funding_pair(next_time="1001"),
        funding_exchange_routes=None,
        funding_max_age_seconds=D("30"),
        account_risk_ledger=None,
    )
    calls = []
    strategy._begin_flatten = lambda exposures, reason: calls.append((exposures, reason))

    strategy.notify_idle()

    assert calls == [
        (
            {
                intent.long_venue: ("long", engine.active_pair.quantity_base),
                intent.short_venue: ("short", engine.active_pair.quantity_base),
            },
            "close_funding_window_data_silence",
        )
    ]


def test_event_notify_idle_funding_refresh_failure_exits_active_pair_fail_closed():
    engine = event_engine(rules(), risk())
    intent = mature(engine)
    engine.mark_open(intent, D(".5"))
    strategy = strategy_stub(engine.risk)
    strategy.engine = engine
    strategy.pending_order = None
    strategy.pair_state = None
    strategy.awaiting_reconciliation = False
    strategy._now = lambda: D(".5")
    strategy._wall_now = lambda: D("1000")
    strategy.p = SimpleNamespace(
        funding=None,
        funding_snapshot_provider=lambda: typed_funding_pair(available=False),
        funding_exchange_routes=None,
        funding_max_age_seconds=D("30"),
        account_risk_ledger=None,
    )
    calls = []
    strategy._begin_flatten = lambda exposures, reason: calls.append((exposures, reason))

    strategy.notify_idle()

    assert calls == [
        (
            {
                intent.long_venue: ("long", engine.active_pair.quantity_base),
                intent.short_venue: ("short", engine.active_pair.quantity_base),
            },
            "funding_stale",
        )
    ]
    assert strategy.funding_evidence_status == "stale_or_unavailable"
    assert strategy.engine.reject_reasons["funding_stale"] == 1


def test_event_funding_stale_cancel_latches_exit_before_fill_beats_cancel():
    strategy = strategy_stub()
    strategy.pending_order = SimpleNamespace(ref=91)
    strategy.pair_state = {
        "phase": "hedge",
        "exposures": {"okx": ("long", D(".01"))},
    }
    strategy.pair_deadline = D("20")
    strategy.leg_deadline = D("15")
    strategy.cancel_deadline = D("16")
    strategy.cancel_requested = False
    strategy.awaiting_reconciliation = False
    strategy._refresh_funding_gate = lambda **_kwargs: False
    cancelled = []
    strategy.cancel = lambda order: cancelled.append(order.ref)

    strategy.notify_orderbook(SimpleNamespace(symbol=hft.VENUE_SYMBOLS["okx"]))

    assert strategy.pair_state["risk_exit_reason"] == "funding_stale"
    assert cancelled == [91]


def test_event_known_hedge_local_failure_compensates_and_flatten_uses_latest_book():
    strategy = strategy_stub()
    update_pair(strategy.engine, D("10"), 1)
    exposures = {"okx": ("long", D(".01"))}
    strategy.pair_state = {"phase": "hedge", "exposures": exposures}
    strategy.pair_deadline = D("10")
    strategy.pending_order = None
    strategy._refresh_funding_gate = lambda **_kwargs: True
    calls = []
    strategy._begin_flatten = lambda current, reason: calls.append((current, reason))

    strategy._submit("binance", "sell", D(".01"), D("101"), "hedge", position_side="short")

    assert calls == [(exposures, "pair_deadline")]

    strategy = strategy_stub()
    update_pair(strategy.engine, D("10"), 1)
    strategy._funding_states = strategy._static_funding_states(D("0"))
    strategy.pending_order = None
    strategy.pair_state = {"phase": "flatten"}
    strategy.pair_deadline = D("20")
    strategy.awaiting_reconciliation = False
    strategy._now = lambda: D("10.5")
    strategy.notify_orderbook(orderbook_event("okx", "100", "100.1", "10.5", 2))
    assert strategy.engine.books["okx"].sequence == 2


def test_event_unknown_transition_advances_fence_and_requests_new_snapshot():
    strategy = strategy_stub()
    requests = []
    strategy.broker.request_reconcile = lambda: requests.append(True) or {"queued": True}
    strategy._reconcile_min_as_of_ns = 10_000_000_000

    strategy._mark_unknown("cancel_deadline")

    assert strategy._reconcile_min_as_of_ns > 10_000_000_000
    assert requests == [True]


def test_event_repeated_stale_reconcile_snapshot_keeps_fence_and_fresh_snapshot_recovers():
    strategy = strategy_stub()
    now = {"value": D("10")}
    strategy._now = lambda: now["value"]
    requests = []
    strategy.broker.request_reconcile = lambda: requests.append(True) or {"queued": True}
    strategy._reconcile_min_as_of_ns = 10_000_000_000
    strategy._mark_unknown("cancel_deadline")
    fence = strategy._reconcile_min_as_of_ns
    stale = reconcile_snapshot(as_of_monotonic_ns=fence - 1)

    assert strategy.confirm_remote_flat(stale) is False
    assert strategy.confirm_remote_flat(stale) is False
    assert strategy._reconcile_min_as_of_ns == fence
    assert requests == [True]

    now["value"] = D("11")
    assert strategy.confirm_remote_flat(reconcile_snapshot(as_of_monotonic_ns=fence)) is True
    assert strategy.engine.halted_unknown is False
    assert strategy.awaiting_reconciliation is False
    assert requests == [True]


def test_event_unknown_external_fence_advance_requests_exactly_once():
    strategy = strategy_stub()
    now = {"value": D("10")}
    strategy._now = lambda: now["value"]
    requests = []
    strategy.broker.request_reconcile = lambda: requests.append(True) or {"queued": True}
    strategy._reconcile_min_as_of_ns = 10_000_000_000
    strategy._mark_unknown("cancel_deadline")
    first_fence = strategy._reconcile_min_as_of_ns

    now["value"] = D("11")
    strategy._advance_reconcile_fence()
    externally_advanced_fence = strategy._reconcile_min_as_of_ns
    strategy._mark_unknown("late_known_order_update")
    strategy._mark_unknown("late_known_order_update")

    assert externally_advanced_fence > first_fence
    assert strategy._reconcile_min_as_of_ns == externally_advanced_fence
    assert strategy._last_reconcile_request_fence_ns == externally_advanced_fence
    assert requests == [True, True]


def test_event_failed_cycle_keeps_entry_funding_evidence_and_requires_crossing_ledger():
    strategy = strategy_stub()
    strategy._cycle_id = 1
    strategy._wall_now = lambda: D("12")
    snapshot = {
        "captured_at_epoch": D("10"),
        "venues": {
            venue: FundingSnapshot(
                exchange_name=venue,
                symbol=hft.VENUE_SYMBOLS[venue],
                rate=D(".0001"),
                next_funding_time=datetime.fromtimestamp(11, tz=UTC),
                settlement_interval_seconds=28800,
                source="exchange",
                freshness=Freshness(
                    source="exchange",
                    observed_at=datetime.fromtimestamp(10, tz=UTC),
                ),
            )
            for venue in hft.VENUE_SYMBOLS
        },
    }
    strategy.pair_state = {
        "intent": SimpleNamespace(buy_price=D("100"), sell_price=D("101")),
        "phase": "hedge",
        "funding_snapshot": snapshot,
    }
    strategy._submit_flatten_head = lambda: None

    strategy._begin_flatten({"okx": ("long", D(".01"))}, "hedge_unfilled")

    assert strategy.pair_state["funding_snapshot"] is snapshot
    strategy.confirmed_fill_ledger.extend(
        (
            {
                "cycle_id": 1,
                "venue": "okx",
                "side": "buy",
                "quantity": D(".01"),
                "price": D("100"),
                "commission": D(".001"),
            },
            {
                "cycle_id": 1,
                "venue": "okx",
                "side": "sell",
                "quantity": D(".01"),
                "price": D("99"),
                "commission": D(".001"),
            },
        )
    )
    assert strategy._finalize_realized_close() is False
    assert strategy.engine.reject_reasons["funding_ledger_missing_failed_cycle"] == 1


def mature(engine):
    update_pair(engine, "0", 1)
    assert engine.evaluate(D("0")) is None
    update_pair(engine, ".25", 2, previous=1)
    assert engine.evaluate(D(".25")) is None
    update_pair(engine, ".5", 3, previous=2)
    return engine.evaluate(D(".5"))


def test_ac_event_003_single_frame_dies_before_lifetime_gate():
    engine = event_engine(rules(), risk())
    update_pair(engine, "0", 1)

    assert engine.evaluate(D("0")) is None
    assert engine.reject_reasons["opportunity_too_short"] == 1


def test_ac_event_004_mature_depth_qualified_opportunity_creates_event_intent():
    engine = event_engine(rules(), risk())

    intent = mature(engine)

    assert intent is not None
    assert (intent.long_venue, intent.short_venue) == ("okx", "binance")
    assert intent.opportunity_lifetime == D(".5")
    assert intent.cost.expected_net > D("0")


def test_public_shadow_observes_mature_intent_with_zero_execution_accounting():
    strategy = object.__new__(hft.CrossExchangeArbitrageStrategy)
    strategy.p = SimpleNamespace(
        rules=rules(),
        risk=risk(),
        venue_stats=None,
        admission_models=qualified_models(),
        funding=explicit_funding(),
        account_risk_ledger=None,
        execution_enabled=False,
        shadow=True,
    )
    strategy.datas = [
        SimpleNamespace(_name=hft.VENUE_SYMBOLS["okx"]),
        SimpleNamespace(_name=hft.VENUE_SYMBOLS["binance"]),
    ]
    strategy.broker = SimpleNamespace(getvalue=lambda: 100)
    hft.CrossExchangeArbitrageStrategy.__init__(strategy)

    for now, sequence in (("0", 1), (".25", 2), (".5", 3)):
        strategy.notify_orderbook(orderbook_event("okx", "99.9", "100", now, sequence))
        strategy.notify_orderbook(orderbook_event("binance", "101", "101.1", now, sequence))

    report = strategy.report()
    assert len(strategy.engine.intents) >= 1
    assert report["submitted_order_count"] == 0
    assert report["confirmed_fill_events"] == 0
    assert report["execution_economics"] == []
    assert report["account_risk_status"] == "NOT_APPLICABLE_OBSERVATION_ONLY"


def test_execution_adapter_without_path_model_submits_zero_orders():
    strategy = object.__new__(hft.CrossExchangeArbitrageStrategy)
    strategy.p = SimpleNamespace(
        rules=rules(),
        risk=risk(),
        venue_stats=None,
        admission_models=(),
        funding=explicit_funding(),
        account_risk_ledger=None,
        execution_enabled=True,
        shadow=False,
    )
    strategy.datas = [
        SimpleNamespace(_name=hft.VENUE_SYMBOLS["okx"]),
        SimpleNamespace(_name=hft.VENUE_SYMBOLS["binance"]),
    ]
    strategy.broker = SimpleNamespace(getvalue=lambda: 100)
    hft.CrossExchangeArbitrageStrategy.__init__(strategy)
    submissions = []
    strategy.buy = lambda **kwargs: submissions.append(kwargs)
    strategy.sell = lambda **kwargs: submissions.append(kwargs)

    for now, sequence in (("0", 1), (".25", 2), (".5", 3)):
        strategy.notify_orderbook(orderbook_event("okx", "99.9", "100", now, sequence))
        strategy.notify_orderbook(orderbook_event("binance", "101", "101.1", now, sequence))

    assert submissions == []
    assert strategy.submitted_order_count == 0
    assert not strategy.engine.intents
    assert strategy.engine.reject_reasons["event_model_missing"] >= 1


def test_event_intent_uses_multilevel_vwap_and_marginal_prices():
    engine = event_engine(rules(), risk())

    def update(now, sequence):
        engine.update_book(
            hft.EventBook(
                "okx",
                ((D("99.9"), D(".005")), (D("99.8"), D(".005"))),
                ((D("100"), D(".005")), (D("100.2"), D(".005"))),
                D(now),
                D(now),
                sequence,
                continuity_status="snapshot",
            )
        )
        engine.update_book(
            hft.EventBook(
                "binance",
                ((D("101"), D(".005")), (D("100.8"), D(".005"))),
                ((D("101.1"), D(".005")), (D("101.3"), D(".005"))),
                D(now),
                D(now),
                sequence,
                continuity_status="snapshot",
            )
        )

    update("0", 1)
    assert engine.evaluate(D("0")) is None
    update(".25", 2)
    assert engine.evaluate(D(".25")) is None
    update(".5", 3)
    intent = engine.evaluate(D(".5"))

    assert intent.entry_buy.price == D("100.1")
    assert intent.entry_buy.marginal_price == D("100.2")
    assert intent.entry_sell.price == D("100.9")
    assert intent.entry_sell.marginal_price == D("100.8")
    assert intent.exit_sell_preview.levels_consumed == 2
    assert intent.exit_buy_preview.levels_consumed == 2


def test_ac_event_005_gap_freezes_until_explicit_recovery_snapshot():
    engine = event_engine(rules(), risk())
    update_pair(engine, "0", 1)
    engine.evaluate(D("0"))
    engine.update_book(book("okx", "99.9", "100", ".25", 2, 1))
    engine.update_book(
        book(
            "binance",
            "101",
            "101.1",
            ".25",
            300,
            0,
            snapshot_or_delta="delta",
        )
    )

    assert engine.evaluate(D(".25")) is None
    assert "binance" in engine.gapped_venues

    engine.update_book(
        book(
            "binance",
            "101",
            "101.1",
            ".5",
            400,
            300,
            recovery=True,
            continuity_status="recovered",
        )
    )
    engine.update_book(book("okx", "99.9", "100", ".5", 3, 2))
    assert "binance" not in engine.gapped_venues
    assert engine.evaluate(D(".5")) is None


def test_complete_snapshots_accept_large_native_sequence_jumps():
    engine = event_engine(rules(), risk())
    update_pair(engine, "0", 100)
    assert engine.update_book(book("okx", "99.9", "100", ".1", 9000))
    assert engine.update_book(book("binance", "101", "101.1", ".1", 800000))
    assert not engine.gapped_venues

    assert not engine.update_book(book("okx", "99.9", "100", ".2", 9000))
    assert "okx" in engine.gapped_venues
    assert engine.update_book(
        book(
            "okx",
            "99.9",
            "100",
            ".3",
            9001,
            recovery=True,
            continuity_status="recovered",
        )
    )
    assert "okx" not in engine.gapped_venues


def test_initial_delta_without_recovery_snapshot_is_fail_closed():
    engine = event_engine(rules(), risk())

    assert not engine.update_book(
        book(
            "okx",
            "99.9",
            "100",
            "0",
            1,
            0,
            snapshot_or_delta="delta",
        )
    )
    assert engine.reject_reasons["initial_delta_without_snapshot"] == 1


@pytest.mark.parametrize(
    ("sequence", "continuity", "reason"),
    [
        (0, "snapshot", "orderbook_sequence_missing_or_invalid"),
        (1, "unknown", "orderbook_continuity_missing_or_invalid"),
        (1, "unverified", "orderbook_continuity_missing_or_invalid"),
    ],
)
def test_unverified_orderbook_evidence_never_becomes_tradable(sequence, continuity, reason):
    engine = event_engine(rules(), risk())

    accepted = engine.update_book(
        book("okx", "99.9", "100", "0", sequence, continuity_status=continuity)
    )

    assert accepted is False
    assert "okx" in engine.gapped_venues
    assert engine.books == {}
    assert engine.reject_reasons[reason] == 1


def test_ac_event_005_stale_and_skew_are_fail_closed():
    stale = event_engine(rules(), risk())
    update_pair(stale, "0", 1)
    assert stale.evaluate(D(".51")) is None
    assert stale.reject_reasons["stale"] == 1

    skewed = event_engine(rules(), risk())
    skewed.update_book(book("okx", "99.9", "100", "0", 1))
    skewed.update_book(book("binance", "101", "101.1", ".251", 1))
    assert skewed.evaluate(D(".251")) is None
    assert skewed.reject_reasons["venue_skew"] == 1


def test_ac_event_006_latency_reserve_can_remove_otherwise_positive_edge():
    engine = event_engine(rules(), risk(latency_reserve_bps=D("200")))
    update_pair(engine, "0", 1)

    assert engine.evaluate(D("0")) is None
    assert engine.reject_reasons["net_edge"] == 1


def test_dynamic_first_leg_uses_ack_reject_and_depth_score():
    stats = {
        "okx": hft.VenueExecutionStats(ack_p99_seconds=D(".2")),
        "binance": hft.VenueExecutionStats(ack_p99_seconds=D(".01")),
    }
    engine = event_engine(rules(), risk(), stats)

    assert mature(engine).first_venue == "binance"


def test_ac_event_009_unknown_execution_freezes_new_opportunities():
    engine = event_engine(rules(), risk())
    update_pair(engine, "0", 1)
    engine.mark_unknown()

    assert engine.evaluate(D("0")) is None
    assert engine.halted_unknown is True
    assert engine.reject_reasons["unknown_execution"] >= 1


def test_ac_event_010_all_markout_horizons_keep_adverse_samples():
    engine = event_engine(rules(), risk())
    assert mature(engine) is not None
    for sequence, now in enumerate((".510", ".550", ".600", "1.000"), 4):
        update_pair(
            engine,
            now,
            sequence,
            binance=("100.1", "100.2"),
            previous=sequence - 1,
        )

    route = engine._route_key(("okx", "binance"), "okx")
    for horizon in ("10", "50", "100", "500"):
        assert len(engine.markouts[horizon][route]) == 1
        assert D(engine.markouts[horizon][route][0]) > 0
        assert engine.markout_observations[horizon][route][0]["status"] == "observed"
        assert D(engine.markout_observations[horizon][route][0]["actual_elapsed_ms"]) == D(horizon)


def test_sparse_late_frame_does_not_backfill_all_markout_horizons():
    engine = event_engine(rules(), risk())
    assert mature(engine) is not None

    update_pair(engine, "1.1", 4, binance=("100.1", "100.2"), previous=3)

    assert all(not samples for routes in engine.markouts.values() for samples in routes.values())
    assert engine.reject_reasons["markout_missed_tolerance"] == 4


def test_adverse_500ms_markout_blocks_a_new_entry():
    engine = event_engine(rules(), risk(maximum_adverse_markout_bps=D("1")))
    direction = ("okx", "binance")
    route = engine._route_key(direction, "okx")
    engine._markout_series("500", route).append("1")
    assert engine._markout_allows_entry(D("1"), direction, "okx") is False
    assert engine.reject_reasons["adverse_markout"] >= 1


def test_default_markout_gate_is_fail_closed_until_calibrated():
    engine = event_engine(
        rules(),
        risk(minimum_markout_samples=D("21")),
    )

    assert mature(engine) is None
    assert engine.reject_reasons["markout_insufficient_samples"] == 1
    assert len(engine.pending_markouts) == len(hft.MARKOUT_HORIZONS_MS)


def test_markout_missing_ratio_is_fail_closed():
    engine = event_engine(
        rules(),
        risk(
            minimum_markout_samples=D("5"),
            maximum_markout_miss_ratio=D(".25"),
        ),
    )
    direction = ("okx", "binance")
    route = engine._route_key(direction, "okx")
    engine._markout_series("500", route).extend(["0"] * 5)
    engine._markout_observation_series("500", route).extend(
        [{"status": "observed"}] * 5 + [{"status": "missed"}] * 2
    )

    assert engine._markout_allows_entry(D("1"), direction, "okx") is False
    assert engine.reject_reasons["markout_missing_ratio"] == 1


def test_adverse_markout_reserve_is_charged_once_in_expected_cost():
    engine = event_engine(
        rules(),
        risk(
            minimum_markout_samples=D("5"),
            maximum_adverse_markout_bps=D("100"),
        ),
    )
    route = engine._route_key(("okx", "binance"), "okx")
    engine._markout_series("500", route).extend([".00005"] * 5)
    engine._markout_observation_series("500", route).extend([{"status": "observed"}] * 5)

    intent = mature(engine)

    assert intent is not None
    assert intent.cost.model_error_buffer == D(".00005")


def test_missing_path_model_is_fail_closed_even_with_configured_path_p99():
    engine = hft.EventArbitrageEngine(
        rules(),
        risk(path_p99_seconds=D("0")),
    )

    assert mature(engine) is None
    assert not engine.intents
    assert engine.reject_reasons["event_model_missing"] == 1
    assert engine.report()["admission"]["configured_path_p99_is_evidence"] is False


def test_path_model_must_match_current_fee_and_depth_buckets():
    only_shallow_models = tuple(
        model for model in qualified_models() if model.depth_bucket == "1x_to_2x"
    )
    engine = event_engine(rules(), risk(), models=only_shallow_models)

    assert mature(engine) is None
    assert engine.reject_reasons["event_model_missing"] == 1


def test_mutated_path_model_fingerprint_is_rejected():
    models = list(qualified_models())
    selected = next(
        index
        for index, model in enumerate(models)
        if model.direction == ("okx", "binance")
        and model.first_venue == "okx"
        and model.depth_bucket == "10x_plus"
    )
    models[selected] = replace(models[selected], end_to_end_path_p99_seconds=D(".2"))
    engine = event_engine(rules(), risk(), models=models)

    assert mature(engine) is None
    assert engine.reject_reasons["event_model_fingerprint"] == 1


def test_measured_end_to_end_model_p99_controls_opportunity_lifetime():
    engine = event_engine(
        rules(),
        risk(),
        models=qualified_models(path_p99=".75"),
    )

    assert mature(engine) is None
    assert engine.reject_reasons["opportunity_shorter_than_measured_path_p99"] == 1
    update_pair(engine, ".75", 4, previous=3)
    assert engine.evaluate(D(".75")) is not None


def test_markout_upper_tail_blocks_catastrophic_minority_hidden_by_median():
    engine = event_engine(
        rules(),
        risk(
            minimum_markout_samples=D("21"),
            maximum_adverse_markout_bps=D("1"),
        ),
    )
    direction = ("okx", "binance")
    route = engine._route_key(direction, "okx")
    engine._markout_series("500", route).extend(["0"] * 11 + ["1"] * 10)
    engine._markout_observation_series("500", route).extend([{"status": "observed"}] * 21)

    allowed, reserve = engine._markout_gate(D("100"), direction, "okx")

    assert allowed is False
    assert reserve == D("1")
    assert engine.reject_reasons["adverse_markout"] == 1


def test_markout_samples_are_isolated_by_direction_and_first_venue():
    engine = event_engine(
        rules(),
        risk(minimum_markout_samples=D("5"), maximum_adverse_markout_bps=D("1")),
    )
    adverse_direction = ("okx", "binance")
    adverse_route = engine._route_key(adverse_direction, "okx")
    safe_direction = ("binance", "okx")
    safe_route = engine._route_key(safe_direction, "binance")
    engine._markout_series("500", adverse_route).extend(["1"] * 5)
    engine._markout_observation_series("500", adverse_route).extend([{"status": "observed"}] * 5)
    engine._markout_series("500", safe_route).extend(["0"] * 5)
    engine._markout_observation_series("500", safe_route).extend([{"status": "observed"}] * 5)

    assert engine._markout_allows_entry(D("100"), adverse_direction, "okx") is False
    assert engine._markout_allows_entry(D("100"), safe_direction, "binance") is True


def test_partial_matched_pair_scales_frozen_cost_before_convergence_exit():
    engine = event_engine(rules(fee=".001"), risk(quantity_base=D(".02")))
    intent = mature(engine)
    assert intent.quantity_base == D(".02")
    engine.mark_open(intent, D(".5"), quantity_base=D(".01"))
    engine.update_book(book("okx", "100", "100.1", ".6", 4, 3))
    engine.update_book(book("binance", "100.4", "100.5", ".6", 4, 3))

    assert engine.exit_reason(D(".6")) == "convergence"


def test_ac_event_007_sub_lattice_first_partial_is_flattened_on_its_venue():
    strategy = object.__new__(hft.CrossExchangeArbitrageStrategy)
    strategy.rules = rules()
    strategy.engine = event_engine(strategy.rules, risk())
    intent = SimpleNamespace(
        long_venue="okx",
        short_venue="binance",
        buy_price=D("100"),
        sell_price=D("101"),
    )
    strategy.pair_state = {
        "intent": intent,
        "phase": "first",
        "fills": {},
        "exposures": {},
    }
    order = SimpleNamespace(
        ref=7,
        info={},
        data=SimpleNamespace(_name="BTCUSDT"),
        executed=SimpleNamespace(size=D(".006"), price=D("101"), comm=D("0")),
        alive=lambda: False,
        isbuy=lambda: False,
        getstatusname=lambda: "Partial",
    )
    strategy.pending_order = order
    strategy.order_records = {}
    strategy.known_order_refs = {7}
    strategy.processed_order_refs = set()
    strategy.pair_deadline = D("999999999")
    strategy.leg_deadline = D("999999999")
    strategy.cancel_deadline = D("999999999")
    strategy.cancel_requested = False
    strategy.awaiting_reconciliation = False
    strategy.remote_flat_proven = False
    strategy.unhedged_started = None
    strategy.unhedged_durations = []
    strategy._now = lambda: D("10")
    submissions = []
    strategy._submit = lambda *args, **kwargs: submissions.append((args, kwargs))

    strategy.notify_order(order)

    args, kwargs = submissions[-1]
    assert args[:4] == ("binance", "buy", D(".006"), D("101"))
    assert kwargs == {"position_side": "short", "reduce_only": True}
    assert strategy.pair_state["phase"] == "flatten"
    assert strategy.engine.reject_reasons["partial_below_common_lattice"] == 1
    assert D(strategy.order_records[7]["fill_price"]) == D("101")
    assert D(strategy.order_records[7]["commission"]) == 0


@pytest.mark.parametrize(
    ("pair_deadline", "execution_deadline_ns", "cancel_deadline_ns"),
    (
        (D("15"), 11_000_000_000, 11_500_000_000),
        (D("10.75"), 10_750_000_000, 10_750_000_000),
    ),
)
def test_event_submit_uses_marginal_depth_price_and_capped_broker_deadlines(
    pair_deadline,
    execution_deadline_ns,
    cancel_deadline_ns,
):
    strategy = object.__new__(hft.CrossExchangeArbitrageStrategy)
    strategy.rules = rules()
    strategy.risk = risk()
    strategy.engine = event_engine(strategy.rules, strategy.risk)
    strategy.p = SimpleNamespace(funding=explicit_funding(), funding_snapshot_provider=None)
    strategy.pending_order = None
    strategy.engine.update_book(
        hft.EventBook(
            "okx",
            ((D("99.9"), D(".01")),),
            ((D("100.05"), D(".005")), (D("100.17"), D(".005"))),
            D("10"),
            D("10"),
            1,
            continuity_status="snapshot",
        )
    )
    strategy.engine.update_book(book("binance", "100.7", "100.9", "10", 1))
    strategy.feeds = {"okx": object()}
    strategy.pair_deadline = pair_deadline
    strategy.known_order_refs = set()
    strategy.cancel_requested = False
    strategy.awaiting_reconciliation = False
    strategy._now = lambda: D("10")
    submitted = []

    def submit(**kwargs):
        submitted.append(kwargs)
        return SimpleNamespace(ref=41)

    strategy.buy = submit
    strategy._submit("okx", "buy", D(".01"), D("100"), "first", position_side="long")

    kwargs = submitted[0]
    assert kwargs["price"] == D("100.2")
    assert kwargs["size"] == D("1")
    assert kwargs["execution_deadline_monotonic_ns"] == execution_deadline_ns
    assert kwargs["cancel_deadline_monotonic_ns"] == cancel_deadline_ns
    assert kwargs["cancel_deadline_monotonic_ns"] <= int(pair_deadline * D("1000000000"))


def test_cancel_request_waits_until_cancel_deadline_before_unknown():
    strategy = object.__new__(hft.CrossExchangeArbitrageStrategy)
    strategy.engine = event_engine(rules(), risk())
    strategy.pending_order = SimpleNamespace(ref=3)
    strategy.leg_deadline = D("9")
    strategy.pair_deadline = D("12")
    strategy.cancel_deadline = D("9.5")
    strategy.cancel_requested = False
    strategy.awaiting_reconciliation = False
    now = [D("9")]
    strategy._now = lambda: now[0]
    cancelled = []
    strategy.cancel = lambda order: cancelled.append(order.ref)

    strategy._check_deadlines()

    assert cancelled == [3]
    assert strategy.engine.halted_unknown is False
    now[0] = D("9.5")
    strategy._check_deadlines()
    assert strategy.engine.halted_unknown is True


def test_naked_leg_timer_starts_on_first_confirmed_live_partial():
    strategy = object.__new__(hft.CrossExchangeArbitrageStrategy)
    strategy.rules = rules()
    strategy.engine = event_engine(strategy.rules, risk())
    order = SimpleNamespace(
        ref=8,
        info={},
        data=SimpleNamespace(_name="BTCUSDT"),
        executed=SimpleNamespace(size=D(".004"), price=D("101"), comm=D(".001")),
        alive=lambda: True,
        isbuy=lambda: False,
    )
    strategy.pending_order = order
    strategy.known_order_refs = {8}
    strategy.pair_state = {"phase": "first", "fills": {}, "exposures": {}}
    strategy.unhedged_started = None
    strategy._now = lambda: D("10")

    strategy.notify_order(order)

    assert strategy.unhedged_started == D("10")
    assert strategy.pair_state["exposures"] == {"binance": ("short", D(".004"))}
    assert D(strategy.pair_state["confirmed_partials"]["first"]["commission"]) == D(".001")


def test_invalid_data_after_first_fill_flattens_known_same_venue_exposure():
    strategy = object.__new__(hft.CrossExchangeArbitrageStrategy)
    strategy.engine = event_engine(rules(), risk())
    strategy.pending_order = None
    strategy.pair_state = {
        "intent": SimpleNamespace(long_venue="okx", short_venue="binance"),
        "phase": "hedge",
        "fills": {},
        "exposures": {"binance": ("short", D(".01"))},
    }
    calls = []
    strategy._begin_flatten = lambda exposures, reason: calls.append((exposures, reason))

    strategy._handle_invalid_book("okx")

    assert calls == [({"binance": ("short", D(".01"))}, "invalid_market_data")]


def test_late_known_terminal_update_is_fail_closed():
    strategy = object.__new__(hft.CrossExchangeArbitrageStrategy)
    strategy.engine = event_engine(rules(), risk())
    strategy.pending_order = SimpleNamespace(ref=2)
    strategy.known_order_refs = {1, 2}
    strategy.processed_order_refs = set()
    strategy.awaiting_reconciliation = False
    late = SimpleNamespace(ref=1, info={}, alive=lambda: False)

    strategy.notify_order(late)

    assert strategy.engine.halted_unknown is True
    assert strategy.engine.reject_reasons["late_known_order_update"] == 1


def test_empty_local_flatten_queue_requires_remote_flat_snapshot():
    engine = event_engine(rules(), risk())
    intent = mature(engine)
    engine.mark_open(intent, D(".5"))
    strategy = object.__new__(hft.CrossExchangeArbitrageStrategy)
    strategy.engine = engine
    strategy.pair_state = {
        "intent": intent,
        "phase": "flatten",
        "flatten_queue": [],
        "flatten_fills": [
            {
                "venue": intent.long_venue,
                "side": "sell",
                "quantity": D(".01"),
                "price": D("100"),
                "commission": D(".001"),
            },
            {
                "venue": intent.short_venue,
                "side": "buy",
                "quantity": D(".01"),
                "price": D("100.2"),
                "commission": D(".001"),
            },
        ],
    }
    strategy.pending_order = None
    strategy.awaiting_reconciliation = False
    strategy.remote_flat_proven = False
    strategy.leg_deadline = D("1")
    strategy.cancel_deadline = D("1")
    strategy.pair_deadline = D("2")
    strategy.unhedged_started = None
    strategy.unhedged_durations = []
    strategy._now = lambda: D("10")
    strategy.broker = SimpleNamespace(request_reconcile=lambda: {"queued": True})

    strategy._submit_flatten_head()

    assert strategy.awaiting_reconciliation is True
    assert engine.active_pair is not None
    assert (
        strategy.confirm_remote_flat(
            reconcile_snapshot(),
            signed_funding=D("0"),
        )
        is True
    )
    assert engine.active_pair is None
    assert strategy.remote_flat_proven is True
    assert engine.last_exit_economics["status"] == "realized_confirmed_fills_and_funding"
    assert D(engine.last_exit_economics["exit_fees"]) == D(".002")


def test_net_position_values_cannot_prove_dual_side_accounts_flat():
    strategy = object.__new__(hft.CrossExchangeArbitrageStrategy)
    strategy.engine = event_engine(rules(), risk())
    strategy.awaiting_reconciliation = True

    assert (
        strategy.confirm_remote_flat(reconcile_snapshot(positions={"okx": 0, "binance": 0}))
        is False
    )
    assert strategy.engine.halted_unknown is True
    assert strategy.engine.reject_reasons["remote_position_not_flat"] == 1


@pytest.mark.parametrize(
    ("snapshot_changes", "summary_changes", "reason"),
    (
        ({"open_orders": [{"order_id": "live"}]}, {}, "remote_open_orders_not_empty"),
        ({"as_of_monotonic_ns": 9_000_000_000}, {}, "reconcile_fence_mismatch"),
        ({"generation": 2}, {}, "reconcile_fence_mismatch"),
        (
            {"reconciled_venues": ["okx", "binance", "unexpected"]},
            {},
            "reconcile_venue_coverage",
        ),
        ({"evidence_complete": False}, {}, "reconcile_snapshot_incomplete"),
        ({"unknown_ids": ["root-unknown"]}, {}, "reconcile_snapshot_incomplete"),
        ({}, {"unknown_ids": ["unknown"]}, "sdk_execution_summary_unsafe"),
        ({}, {"fee_unresolved_orders": ["fee"]}, "sdk_execution_summary_unsafe"),
        ({}, {"trading_blocked": True}, "sdk_execution_summary_unsafe"),
        ({}, {"active_orders": None}, "sdk_execution_summary_unsafe"),
        ({}, {"evidence_complete": False}, "sdk_execution_summary_unsafe"),
    ),
)
def test_remote_flat_contract_rejects_unfenced_or_unsafe_snapshots(
    snapshot_changes, summary_changes, reason
):
    strategy = strategy_stub()
    strategy.awaiting_reconciliation = True
    strategy._reconcile_min_as_of_ns = 10_000_000_000
    snapshot = reconcile_snapshot(summary_changes=summary_changes, **snapshot_changes)

    assert strategy.confirm_remote_flat(snapshot) is False
    assert strategy.engine.reject_reasons[reason] == 1


def test_explicit_empty_execution_summary_cannot_fall_back_to_embedded_evidence():
    strategy = strategy_stub()
    strategy.awaiting_reconciliation = True

    assert strategy.confirm_remote_flat(reconcile_snapshot(), execution_summary={}) is False
    assert strategy.engine.reject_reasons["sdk_execution_summary_unsafe"] == 1


def test_account_level_loss_budget_requires_fresh_durable_fenced_ledger():
    strategy = strategy_stub()
    valid = {
        "baseline_equity": "100",
        "current_equity": "99.6",
        "realized_net": "-.4",
        "configured_venues": ["okx", "binance"],
        "generation": 1,
        "fencing_epoch": 1,
        "as_of_monotonic_ns": 10_000_000_000,
        "owner_pid": os.getpid(),
        "clock_domain_id": f"process:{os.getpid()}:monotonic",
        "identity_binding_sha256": "a" * 64,
        "durable": True,
        "trading_blocked": False,
        "evidence_complete": True,
        "evidence_errors": [],
        "loss_limit_bps": "50",
        "loss_limit_breached": False,
    }
    strategy.p.account_risk_ledger = valid
    assert strategy._account_loss_allows_entry() is True

    strategy.p.account_risk_ledger = {
        **valid,
        "current_equity": "99.5",
        "realized_net": "-.5",
        "generation": 2,
        "fencing_epoch": 2,
        "trading_blocked": True,
        "loss_limit_breached": True,
    }
    assert strategy._account_loss_allows_entry() is False
    assert strategy.account_loss_kill_switch is True

    strategy = strategy_stub()
    strategy.p.account_risk_ledger = {**valid, "evidence_complete": False}
    assert strategy._account_loss_allows_entry() is False
    assert strategy.account_risk_status == "stale_or_unbound"

    strategy = strategy_stub()
    strategy.p.account_risk_ledger = {
        **valid,
        "owner_pid": os.getpid() + 1,
        "clock_domain_id": f"process:{os.getpid() + 1}:monotonic",
    }
    assert strategy._account_loss_allows_entry() is False
    assert strategy.account_risk_status == "invalid_contract"

    strategy = strategy_stub()
    assert strategy._account_loss_allows_entry() is False
    assert strategy.account_risk_status == "missing_or_incomplete"


def test_sdk_loss_latch_cannot_be_cleared_by_equity_rebound_in_process():
    strategy = strategy_stub()
    breached = {
        "baseline_equity": "100",
        "current_equity": "100",
        "configured_venues": ["okx", "binance"],
        "generation": 1,
        "fencing_epoch": 1,
        "as_of_monotonic_ns": 10_000_000_000,
        "owner_pid": os.getpid(),
        "clock_domain_id": f"process:{os.getpid()}:monotonic",
        "identity_binding_sha256": "a" * 64,
        "durable": True,
        "trading_blocked": True,
        "evidence_complete": True,
        "evidence_errors": [],
        "loss_limit_bps": "50.0",
        "loss_limit_breached": True,
    }
    strategy.p.account_risk_ledger = breached

    assert strategy._account_loss_allows_entry() is False
    assert strategy.account_loss_kill_switch is True

    strategy.p.account_risk_ledger = {
        **breached,
        "generation": 2,
        "fencing_epoch": 2,
        "trading_blocked": False,
        "loss_limit_breached": False,
    }
    assert strategy._account_loss_allows_entry() is False
    assert strategy.account_loss_kill_switch is True
    assert strategy.account_risk_status == "loss_limit"


def test_sdk_loss_limit_must_exactly_match_strategy_configuration():
    strategy = strategy_stub()
    strategy.p.account_risk_ledger = {
        "baseline_equity": "100",
        "current_equity": "100",
        "configured_venues": ["okx", "binance"],
        "generation": 1,
        "fencing_epoch": 1,
        "as_of_monotonic_ns": 10_000_000_000,
        "owner_pid": os.getpid(),
        "clock_domain_id": f"process:{os.getpid()}:monotonic",
        "identity_binding_sha256": "a" * 64,
        "durable": True,
        "trading_blocked": False,
        "evidence_complete": True,
        "evidence_errors": [],
        "loss_limit_bps": "50.0001",
        "loss_limit_breached": False,
    }

    assert strategy._account_loss_allows_entry() is False
    assert strategy.account_loss_kill_switch is True
    assert strategy.account_risk_status == "invalid_contract"
    assert strategy.engine.reject_reasons["account_risk_loss_limit_mismatch"] == 1


def test_cumulative_order_updates_produce_unique_fill_deltas_and_fee_adjustment():
    strategy = strategy_stub()
    strategy._cycle_id = 1
    order = SimpleNamespace(
        ref=11,
        data=SimpleNamespace(_name="BTCUSDT"),
        executed=SimpleNamespace(size=D(".004"), price=D("101"), comm=D(".001")),
        isbuy=lambda: False,
    )

    first = strategy._capture_fill_delta(order, "first", "binance")
    order.executed.size = D(".01")
    order.executed.price = D("100.88")
    order.executed.comm = D(".002")
    second = strategy._capture_fill_delta(order, "first", "binance")
    duplicate = strategy._capture_fill_delta(order, "first", "binance")
    order.executed.comm = D(".0025")
    fee_only = strategy._capture_fill_delta(order, "first", "binance")

    assert first["quantity"] == D(".004") and first["price"] == D("101")
    assert second["quantity"] == D(".006") and second["price"] == D("100.8")
    assert duplicate is None
    assert fee_only["commission_adjustment"] == D(".0005")
    assert strategy._confirmed_fill_event_count == 2
    assert sum(event["commission"] for event in strategy.confirmed_fill_ledger) == D(".0025")


def test_failed_leg_compensation_uses_complete_fill_ledger_economics():
    strategy = strategy_stub()
    strategy._cycle_id = 1
    opening = SimpleNamespace(
        ref=21,
        data=SimpleNamespace(_name="BTCUSDT"),
        executed=SimpleNamespace(size=D(".01"), price=D("101"), comm=D(".001")),
        isbuy=lambda: False,
    )
    closing = SimpleNamespace(
        ref=22,
        data=SimpleNamespace(_name="BTCUSDT"),
        executed=SimpleNamespace(size=D(".01"), price=D("102"), comm=D(".001")),
        isbuy=lambda: True,
    )
    strategy._capture_fill_delta(opening, "first", "binance")
    strategy._capture_fill_delta(closing, "flatten", "binance")

    assert strategy._finalize_realized_close(signed_funding=D("0")) is True
    economics = strategy.execution_economics_history[-1]
    assert D(economics["gross_pnl"]) == D("-.01")
    assert D(economics["failure_leg_loss"]) == D(".01")
    assert D(economics["realized_net"]) == D("-.012")
    assert economics["signed_funding_cashflow"] == "0"
    assert "signed_funding" not in economics


def test_close_requires_actual_funding_ledger_after_a_settlement_boundary():
    engine = event_engine(rules(), risk())
    intent = mature(engine)
    engine.mark_open(intent, D(".5"))
    active = engine.active_pair
    active.funding_snapshot = {
        venue: (
            D(".5"),
            D(".6"),
            D(".0001"),
            snapshot[3],
            snapshot[4],
            snapshot[5],
        )
        for venue, snapshot in active.funding_snapshot.items()
    }
    engine.books = {
        venue: replace(venue_book, exchange_time=D(".55"))
        for venue, venue_book in engine.books.items()
    }
    strategy = strategy_stub()
    strategy.engine = engine
    strategy._wall_now = lambda: D(".7")
    strategy.pair_state = {
        "flatten_fills": [
            {
                "venue": intent.long_venue,
                "side": "sell",
                "quantity": D(".01"),
                "price": D("100"),
                "commission": D(".001"),
            },
            {
                "venue": intent.short_venue,
                "side": "buy",
                "quantity": D(".01"),
                "price": D("100.2"),
                "commission": D(".001"),
            },
        ]
    }

    assert all(book.exchange_time < D(".6") for book in engine.books.values())
    assert strategy._finalize_realized_close() is False
    assert strategy.funding_evidence_status == "missing"
    assert engine.reject_reasons["funding_ledger_missing"] == 1

    assert strategy._finalize_realized_close(signed_funding=D("0")) is True
    assert strategy.funding_evidence_status == "actual_ledger"
    economics = strategy.execution_economics_history[-1]
    assert D(economics["signed_funding_cashflow"]) == D("0")
    assert "signed_funding" not in economics


def test_remote_flat_does_not_hide_missing_failed_leg_fill_events():
    strategy = strategy_stub()
    strategy._cycle_id = 1
    opening = SimpleNamespace(
        ref=23,
        data=SimpleNamespace(_name="BTCUSDT"),
        executed=SimpleNamespace(size=D(".01"), price=D("101"), comm=D(".001")),
        isbuy=lambda: False,
    )
    strategy._capture_fill_delta(opening, "first", "binance")
    strategy.awaiting_reconciliation = True

    assert strategy.confirm_remote_flat(reconcile_snapshot(), signed_funding=D("0")) is False
    assert strategy.engine.reject_reasons["failed_leg_fill_ledger_incomplete"] == 1
    assert strategy.remote_flat_proven is False


def test_cancel_unknown_halts_before_hedge_and_requests_full_reconcile():
    strategy = strategy_stub()
    requests = []
    strategy.broker.request_reconcile = lambda: requests.append(True) or {"queued": True}
    strategy.pair_state = {
        "intent": SimpleNamespace(long_venue="okx", short_venue="binance"),
        "phase": "first",
        "fills": {},
        "exposures": {},
    }
    order = SimpleNamespace(
        ref=31,
        info={"cancel_execution_unknown": True},
        data=SimpleNamespace(_name="BTCUSDT"),
        executed=SimpleNamespace(size=D(".004"), price=D("101"), comm=D(".001")),
        alive=lambda: True,
        isbuy=lambda: False,
        getstatusname=lambda: "Partial",
    )
    strategy.pending_order = order
    strategy.known_order_refs.add(order.ref)
    submissions = []
    strategy._submit = lambda *args, **kwargs: submissions.append((args, kwargs))

    strategy.notify_order(order)

    assert strategy.engine.halted_unknown is True
    assert strategy.awaiting_reconciliation is True
    assert strategy._confirmed_fill_event_count == 1
    assert submissions == []
    assert requests == [True]


def test_broker_owned_cancel_retry_is_not_duplicated_by_strategy():
    strategy = strategy_stub()
    strategy.pair_state = {
        "intent": SimpleNamespace(long_venue="okx", short_venue="binance"),
        "phase": "first",
        "fills": {},
        "exposures": {},
    }
    order = SimpleNamespace(
        ref=32,
        info={
            "cancel_reconcile_confirmed_live": True,
            "cancel_intent_active": True,
        },
        data=SimpleNamespace(_name="BTCUSDT"),
        executed=SimpleNamespace(size=D("0"), price=D("0"), comm=D("0")),
        alive=lambda: True,
        isbuy=lambda: False,
    )
    strategy.pending_order = order
    strategy.known_order_refs.add(order.ref)
    cancellations = []
    strategy.cancel = lambda current: cancellations.append(current.ref)

    strategy.notify_order(order)

    assert cancellations == []
    assert strategy.cancel_requested is True
    assert strategy.cancel_deadline is None
    assert strategy.engine.halted_unknown is False


def test_strategy_cancel_retry_deadline_is_capped_to_pair_deadline():
    strategy = strategy_stub()
    strategy.pair_state = {
        "intent": SimpleNamespace(long_venue="okx", short_venue="binance"),
        "phase": "first",
        "fills": {},
        "exposures": {},
    }
    strategy.pair_deadline = D("10.25")
    order = SimpleNamespace(
        ref=35,
        info={
            "cancel_reconcile_confirmed_live": True,
            "cancel_intent_active": False,
        },
        data=SimpleNamespace(_name="BTCUSDT"),
        executed=SimpleNamespace(size=D("0"), price=D("0"), comm=D("0")),
        alive=lambda: True,
        isbuy=lambda: False,
    )
    strategy.pending_order = order
    strategy.known_order_refs.add(order.ref)
    cancellations = []
    strategy.cancel = lambda current: cancellations.append(current.ref)

    strategy.notify_order(order)

    assert cancellations == [35]
    assert strategy.cancel_deadline == strategy.pair_deadline == D("10.25")


def test_late_fill_after_flat_proof_invalidates_proof_and_halts():
    strategy = strategy_stub()
    strategy.remote_flat_proven = True
    strategy.processed_order_refs.add(33)
    strategy.known_order_refs.add(33)
    late_fill = SimpleNamespace(
        ref=33,
        info={},
        data=SimpleNamespace(_name="BTCUSDT"),
        executed=SimpleNamespace(size=D(".001"), price=D("101"), comm=D(".0001")),
        alive=lambda: False,
        isbuy=lambda: False,
    )

    strategy.notify_order(late_fill)

    assert strategy.engine.halted_unknown is True
    assert strategy.remote_flat_proven is False
    assert strategy._confirmed_fill_event_count == 1
    assert strategy.engine.reject_reasons["late_known_order_update"] == 1


def test_late_commission_adjustment_invalidates_flat_proof_without_adding_a_fill():
    strategy = strategy_stub()
    order = SimpleNamespace(
        ref=34,
        info={},
        data=SimpleNamespace(_name="BTCUSDT"),
        executed=SimpleNamespace(size=D(".001"), price=D("101"), comm=D(".0001")),
        alive=lambda: False,
        isbuy=lambda: False,
    )
    strategy.known_order_refs.add(order.ref)
    strategy._capture_fill_delta(order, "first", "binance")
    strategy.processed_order_refs.add(order.ref)
    strategy.remote_flat_proven = True
    order.executed.comm = D(".00015")

    strategy.notify_order(order)

    assert strategy.engine.halted_unknown is True
    assert strategy.remote_flat_proven is False
    assert strategy._confirmed_fill_event_count == 1
    assert strategy.confirmed_fill_ledger[0]["commission"] == D(".00015")
    assert strategy.engine.reject_reasons["late_known_order_update"] == 1


def test_strategy_report_separates_submissions_from_unique_confirmed_fills():
    strategy = strategy_stub()
    strategy.submitted_order_count = 3
    strategy._confirmed_fill_event_count = 1

    report = strategy.report()

    assert report["submitted_order_count"] == 3
    assert report["confirmed_fill_events"] == 1
    assert report["funding_evidence_status"] == "not_observed"


def test_event_flatten_retry_only_consumes_head_venue_new_sequence():
    strategy = strategy_stub()
    strategy.pending_order = None
    strategy.pair_deadline = D("20")
    strategy.awaiting_reconciliation = False
    strategy.engine.halted_unknown = False
    strategy._funding_states = strategy._static_funding_states(D("0"))
    strategy.pair_state = {
        "phase": "flatten",
        "flatten_queue": [
            {
                "venue": "okx",
                "position_side": "long",
                "side": "sell",
                "remaining": D(".01"),
                "fallback": D("100"),
                "attempts": 1,
            }
        ],
        "flatten_waiting_for_book": "order_depth",
    }
    submissions = []
    strategy._submit = lambda *args, **kwargs: submissions.append((args, kwargs))

    strategy.notify_orderbook(orderbook_event("binance", "101", "101.1", "10.1", 1))

    head = strategy.pair_state["flatten_queue"][0]
    assert head["attempts"] == 1
    assert strategy.pair_state["flatten_waiting_for_book"] == "order_depth"
    assert submissions == []

    head_event = orderbook_event("okx", "100", "100.1", "10.1", 1)
    strategy.notify_orderbook(head_event)

    assert head["attempts"] == 2
    assert "flatten_waiting_for_book" not in strategy.pair_state
    assert len(submissions) == 1

    strategy.pair_state["flatten_waiting_for_book"] = "terminal_remaining"
    strategy.notify_orderbook(head_event)

    assert head["attempts"] == 2
    assert strategy.pair_state["flatten_waiting_for_book"] == "terminal_remaining"
    assert len(submissions) == 1


@pytest.mark.parametrize(
    ("filled_native", "fill_price", "expected_remaining"),
    ((D("0"), D("0"), D(".01")), (D(".004"), D("101"), D(".006"))),
)
def test_event_terminal_incomplete_flatten_waits_for_new_book_before_resubmit(
    filled_native,
    fill_price,
    expected_remaining,
):
    strategy = strategy_stub()
    order = SimpleNamespace(
        ref=71,
        info={},
        data=SimpleNamespace(_name=hft.VENUE_SYMBOLS["binance"]),
        executed=SimpleNamespace(size=filled_native, price=fill_price, comm=D(".001")),
        alive=lambda: False,
        isbuy=lambda: True,
        getstatusname=lambda: "Completed",
    )
    strategy.pending_order = order
    strategy.known_order_refs = {order.ref}
    strategy.processed_order_refs = set()
    strategy.pair_deadline = D("20")
    strategy.leg_deadline = D("15")
    strategy.cancel_deadline = D("16")
    strategy.awaiting_reconciliation = False
    strategy.engine.halted_unknown = False
    strategy.pair_state = {
        "phase": "flatten",
        "flatten_queue": [
            {
                "venue": "binance",
                "position_side": "short",
                "side": "buy",
                "remaining": D(".01"),
                "fallback": D("101"),
                "attempts": 1,
            }
        ],
        "flatten_fills": [],
    }
    submissions = []
    strategy._submit_flatten_head = lambda: submissions.append(True)

    strategy.notify_order(order)

    assert submissions == []
    assert strategy.pending_order is None
    assert strategy.pair_state["flatten_queue"][0]["remaining"] == expected_remaining
    assert strategy.pair_state["flatten_waiting_for_book"] == "terminal_remaining"


def test_event_empty_flatten_queue_submit_failure_is_unknown():
    strategy = strategy_stub()
    strategy.pending_order = None
    strategy.awaiting_reconciliation = False
    strategy.engine.halted_unknown = False
    strategy.pair_state = {"phase": "flatten", "flatten_queue": []}

    strategy._handle_local_submit_failure("order_depth", "flatten", True)

    assert strategy.engine.halted_unknown is True
    assert strategy.awaiting_reconciliation is True
    assert "flatten_waiting_for_book" not in strategy.pair_state
    assert strategy.engine.reject_reasons["flatten_queue_missing"] == 1


def test_event_flatten_book_wait_past_deadline_becomes_unknown():
    strategy = strategy_stub()
    strategy.pending_order = None
    strategy.pair_deadline = D("9")
    strategy.awaiting_reconciliation = False
    strategy.engine.halted_unknown = False
    strategy.pair_state = {
        "phase": "flatten",
        "flatten_queue": [{"venue": "okx"}],
        "flatten_waiting_for_book": "terminal_remaining",
    }

    strategy.notify_idle()

    assert strategy.engine.halted_unknown is True
    assert strategy.awaiting_reconciliation is True
    assert strategy.engine.reject_reasons["flatten_deadline"] == 1
