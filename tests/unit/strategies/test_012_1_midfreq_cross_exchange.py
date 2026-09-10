from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
from importlib import import_module
import os
import random
from types import SimpleNamespace

import pytest

from bt_api_py import CrossVenueLeg as InstrumentRule
from bt_api_py import Freshness, FundingSnapshot

mid = import_module("examples.012_1_midfreq_cross_exchange.strategy")
D = Decimal


def source_data_sha256(samples):
    canonical = "\n".join(f"{index},{value:f}" for index, value in enumerate(samples))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def rules(fee="0"):
    return {
        "okx": InstrumentRule(D(".01"), D("1"), D("1"), D("0"), D(".1"), D(fee)),
        "binance": InstrumentRule(D("1"), D(".001"), D(".001"), D("0"), D(".1"), D(fee)),
    }


def explicit_funding():
    return {venue: (D("0"), D("99999999999")) for venue in mid.VENUE_SYMBOLS}


def typed_funding_pair(
    *,
    next_time="2000",
    stale=False,
    available=True,
    rate=".0001",
    exchange_names=None,
    cache_age="1",
):
    exchange_names = exchange_names or {venue: venue for venue in mid.VENUE_SYMBOLS}
    return {
        venue: {
            "available": available,
            "unavailable_reason": None if available else "funding_unavailable",
            "exchange_name": exchange_names[venue],
            "symbol": mid.VENUE_SYMBOLS[venue],
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
        for venue in mid.VENUE_SYMBOLS
    }


def risk(**changes):
    base = mid.MidFrequencyRisk(
        zscore_window=10,
        minimum_samples=5,
        confirmations=1,
        persistence_seconds=D("0"),
        minimum_interval_seconds=D("0"),
        maximum_quote_age_seconds=D("2"),
        maximum_venue_skew_seconds=D(".25"),
        depth_fraction=D("1"),
        exit_reserve_bps=D("0"),
        latency_reserve_bps=D("0"),
        failure_reserve_bps=D("0"),
        model_buffer_bps=D("0"),
    )
    return replace(base, **changes)


def qualification(
    venue_rules=None,
    risk_config=None,
    direction=("okx", "binance"),
    **changes,
):
    venue_rules = venue_rules or rules()
    risk_config = risk_config or risk()
    samples = ar_samples(".45")
    artifact = mid.qualify_basis_model(
        samples,
        sample_interval_seconds=D("1"),
        maximum_half_life_seconds=risk_config.maximum_half_life_seconds,
        valid_from_epoch=D("0"),
        valid_until_epoch=D("1000"),
        buy_venue=direction[0],
        sell_venue=direction[1],
        minimum_samples=risk_config.minimum_qualification_samples,
        source_data_sha256=source_data_sha256(samples),
        provenance="unit-test-source",
        qualification_contract_sha256=mid.qualification_contract_sha256(
            venue_rules, risk_config, *direction
        ),
    )
    return replace(artifact, **changes)


def qualifications(venue_rules, risk_config):
    return {
        direction: qualification(venue_rules, risk_config, direction)
        for direction in (("okx", "binance"), ("binance", "okx"))
    }


def new_engine(venue_rules, risk_config, model_qualification=None, wall_clock=lambda: D("10")):
    return mid.MidFrequencyEngine(
        venue_rules,
        risk_config,
        (
            qualifications(venue_rules, risk_config)
            if model_qualification is None
            else model_qualification
        ),
        wall_clock=wall_clock,
    )


def book(
    venue,
    bid,
    ask,
    now,
    sequence,
    size=".1",
    previous_sequence=None,
    snapshot_or_delta="snapshot",
    **kwargs,
):
    kwargs.setdefault(
        "continuity_status", "snapshot" if snapshot_or_delta == "snapshot" else "continuous"
    )
    return mid.BookState(
        venue=venue,
        bids=((D(bid), D(size)),),
        asks=((D(ask), D(size)),),
        exchange_time=D(now),
        receive_time=D(now),
        sequence=sequence,
        previous_sequence=previous_sequence,
        snapshot_or_delta=snapshot_or_delta,
        **kwargs,
    )


def seed(engine):
    samples = (D("-.1"), D("0"), D(".1"), D("-.05"), D(".05"))
    for model in engine.models.values():
        model.values.extend(samples)


def update_pair(engine, now, okx=("99.9", "100"), binance=("101", "101.1"), seq=1, size=".1"):
    engine.update_book(book("okx", *okx, now, seq, size=size))
    engine.update_book(book("binance", *binance, now, seq, size=size))


def orderbook_event(venue, bid, ask, now, sequence):
    native_size = D("10") if venue == "okx" else D(".1")
    return SimpleNamespace(
        symbol=mid.VENUE_SYMBOLS[venue],
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
    strategy = object.__new__(mid.CrossExchangeArbitrageStrategy)
    strategy.rules = rules()
    strategy.risk = risk_config or risk()
    strategy.engine = new_engine(strategy.rules, strategy.risk)
    strategy._now = lambda: D("10")
    strategy.p = SimpleNamespace(
        funding=explicit_funding(),
        funding_snapshot_provider=None,
        funding_exchange_routes=None,
        funding_max_age_seconds=D("30"),
        account_risk_ledger=None,
    )
    strategy.broker = SimpleNamespace(getvalue=lambda: 100)
    strategy.unhedged_started = None
    strategy.unhedged_durations = []
    strategy._ensure_runtime_state()
    return strategy


def test_mid_trade_logger_context_is_published_live_from_cached_broker_state():
    strategy = strategy_stub()
    strategy.pair_state = None
    strategy.pending_order = None
    strategy.cancel_requested = False
    strategy.unknown = False
    strategy.awaiting_reconciliation = False
    strategy.remote_flat_proven = False
    strategy.order_records = {}
    getter_calls = []
    cached_state_calls = []

    def forbidden_getvalue():
        getter_calls.append("getvalue")
        raise AssertionError("live broker getter must not be used for TradeLogger context")

    def cached_report_state():
        cached_state_calls.append("cached")
        return {"value": D("1234.5")}

    strategy.broker = SimpleNamespace(
        getvalue=forbidden_getvalue,
        get_cached_report_state=cached_report_state,
    )

    class RecordingTradeLogger:
        def __init__(self):
            self.contexts = []

        def update_report_context(self, context, *, namespace):
            self.contexts.append((namespace, context))
            return True

    trade_logger = RecordingTradeLogger()
    strategy.stats = SimpleNamespace(trade_logger=trade_logger)

    strategy.start()
    assert len(trade_logger.contexts) == 1
    assert trade_logger.contexts[-1][0] == "cross_venue"
    assert trade_logger.contexts[-1][1]["broker_value"] == "1234.5"
    assert getter_calls == []
    assert cached_state_calls == ["cached"]

    # High-rate same-state callbacks only compare the local signature: they do
    # not rebuild the extension or call even the local cached-state getter.
    assert [strategy._publish_trade_logger_context() for _ in range(100)] == [False] * 100
    assert len(trade_logger.contexts) == 1
    assert cached_state_calls == ["cached"]

    strategy.remote_flat_proven = True
    assert strategy._publish_trade_logger_context() is True
    assert len(trade_logger.contexts) == 2
    assert trade_logger.contexts[-1][1]["remote_flat_proven"] is True
    assert cached_state_calls == ["cached", "cached"]


def test_dynamic_funding_pair_fails_closed_at_runtime_and_recovers():
    strategy = strategy_stub()
    current = {"value": typed_funding_pair()}
    strategy._wall_now = lambda: D("1000")
    strategy.p = SimpleNamespace(
        funding=None,
        funding_snapshot_provider=lambda: current["value"],
        funding_exit_window_seconds=D("10"),
        account_risk_ledger=None,
    )

    assert strategy._refresh_funding_gate(opening=True) is True
    current["value"] = typed_funding_pair(stale=True)
    assert strategy._refresh_funding_gate(opening=True) is False
    assert strategy.funding_evidence_status == "stale_or_unavailable"
    current["value"] = typed_funding_pair(next_time="1305")
    assert strategy._refresh_funding_gate(opening=True) is False
    assert strategy.engine.reject_reasons["funding_entry_window"] == 1
    current["value"] = typed_funding_pair(next_time="2001", rate=".0002")
    assert strategy._refresh_funding_gate(opening=True) is True
    assert strategy._funding_states["okx"].rate == D(".0002")


def test_dynamic_funding_pair_requires_both_venues():
    strategy = strategy_stub()
    strategy._wall_now = lambda: D("1000")
    incomplete = typed_funding_pair()
    incomplete.pop("binance")
    strategy.p = SimpleNamespace(
        funding=None,
        funding_snapshot_provider=lambda: incomplete,
        account_risk_ledger=None,
    )

    assert strategy._refresh_funding_gate(opening=True) is False
    assert strategy.engine.reject_reasons["funding_stale"] == 1


def test_mid_funding_expiry_before_hedge_flattens_confirmed_first_leg():
    strategy = strategy_stub()
    strategy.pending_order = None
    intent = SimpleNamespace(long_venue="okx", short_venue="binance")
    exposures = {"binance": ("short", D(".01"))}
    strategy.pair_state = {
        "intent": intent,
        "phase": "open_long",
        "fills": {},
        "exposures": exposures,
    }
    strategy._refresh_funding_gate = lambda **_kwargs: False
    calls = []
    strategy._begin_flatten = lambda current, reason: calls.append((current, reason))

    strategy._submit(
        "okx",
        "buy",
        D(".01"),
        D("100"),
        "open_long",
        position_side="long",
    )

    assert calls == [(exposures, "funding_stale")]


def test_mid_funding_expiry_before_first_submit_releases_empty_cycle():
    strategy = strategy_stub()
    strategy.pending_order = None
    strategy.pair_state = {
        "intent": SimpleNamespace(long_venue="okx", short_venue="binance"),
        "phase": "open_short",
        "fills": {},
        "exposures": {},
    }
    strategy.pair_deadline = D("20")
    strategy.leg_deadline = D("15")
    strategy.cancel_deadline = D("16")
    strategy._refresh_funding_gate = lambda **_kwargs: False

    strategy._submit(
        "binance",
        "sell",
        D(".01"),
        D("101"),
        "open_short",
        position_side="short",
    )

    assert strategy.pair_state is None
    assert strategy.pair_deadline is None
    assert strategy.leg_deadline is None
    assert strategy.cancel_deadline is None


def test_mid_flatten_and_reconcile_progress_without_a_funding_snapshot():
    strategy = strategy_stub()
    strategy.unknown = False
    strategy.pending_order = SimpleNamespace(ref=1)
    strategy.pair_state = {"phase": "flatten"}
    strategy.awaiting_reconciliation = False
    deadlines = []
    strategy._check_deadlines = lambda: deadlines.append("checked")
    strategy._refresh_funding_gate = lambda **_kwargs: pytest.fail(
        "flatten must not depend on funding refresh"
    )

    strategy.notify_orderbook(SimpleNamespace(symbol=mid.VENUE_SYMBOLS["okx"]))

    assert deadlines == ["checked"]

    strategy.pending_order = None
    strategy.pair_state = {"phase": "reconcile"}
    strategy.awaiting_reconciliation = True
    polls = []
    strategy._poll_remote_reconcile = lambda: polls.append("polled")
    strategy.notify_orderbook(SimpleNamespace(symbol=mid.VENUE_SYMBOLS["binance"]))
    assert polls == ["polled"]


def test_mid_funding_provider_binds_sdk_route_identity_and_source_age():
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


def test_mid_entry_funding_window_includes_pair_hedge_budget():
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


def test_mid_notify_idle_exits_active_pair_when_funding_schedule_moves_earlier():
    engine = new_engine(rules(), risk(entry_zscore=D("1")))
    seed(engine)
    update_pair(engine, D(".5"), seq=1)
    intent = engine.evaluate(D(".5"))
    assert intent is not None
    engine.mark_open(intent, D(".5"))
    strategy = strategy_stub(engine.risk)
    strategy.engine = engine
    strategy.pending_order = None
    strategy.pair_state = None
    strategy.awaiting_reconciliation = False
    strategy.unknown = False
    strategy._now = lambda: D(".5")
    strategy._wall_now = lambda: D("1000")
    strategy.p = SimpleNamespace(
        funding=None,
        funding_snapshot_provider=lambda: typed_funding_pair(next_time="1001"),
        funding_exchange_routes=None,
        funding_max_age_seconds=D("30"),
        funding_exit_window_seconds=D("5"),
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


def test_mid_notify_idle_funding_refresh_failure_exits_active_pair_fail_closed():
    engine = new_engine(rules(), risk(entry_zscore=D("1")))
    seed(engine)
    update_pair(engine, D(".5"), seq=1)
    intent = engine.evaluate(D(".5"))
    assert intent is not None
    engine.mark_open(intent, D(".5"))
    strategy = strategy_stub(engine.risk)
    strategy.engine = engine
    strategy.pending_order = None
    strategy.pair_state = None
    strategy.awaiting_reconciliation = False
    strategy.unknown = False
    strategy._now = lambda: D(".5")
    strategy._wall_now = lambda: D("1000")
    strategy.p = SimpleNamespace(
        funding=None,
        funding_snapshot_provider=lambda: typed_funding_pair(available=False),
        funding_exchange_routes=None,
        funding_max_age_seconds=D("30"),
        funding_exit_window_seconds=D("5"),
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


def test_mid_funding_stale_cancel_latches_exit_before_fill_beats_cancel():
    strategy = strategy_stub()
    strategy.pending_order = SimpleNamespace(ref=91)
    strategy.pair_state = {
        "phase": "open_long",
        "exposures": {"binance": ("short", D(".01"))},
    }
    strategy.pair_deadline = D("20")
    strategy.leg_deadline = D("15")
    strategy.cancel_deadline = D("16")
    strategy.cancel_requested = False
    strategy.awaiting_reconciliation = False
    strategy.unknown = False
    strategy._refresh_funding_gate = lambda **_kwargs: False
    cancelled = []
    strategy.cancel = lambda order: cancelled.append(order.ref)

    strategy.notify_orderbook(SimpleNamespace(symbol=mid.VENUE_SYMBOLS["okx"]))

    assert strategy.pair_state["risk_exit_reason"] == "funding_stale"
    assert cancelled == [91]


def test_mid_known_hedge_local_failure_compensates_and_flatten_uses_latest_book():
    strategy = strategy_stub()
    update_pair(strategy.engine, D("10"), seq=1)
    exposures = {"binance": ("short", D(".01"))}
    strategy.pair_state = {"phase": "open_long", "exposures": exposures}
    strategy.pair_deadline = D("10")
    strategy.pending_order = None
    strategy._refresh_funding_gate = lambda **_kwargs: True
    calls = []
    strategy._begin_flatten = lambda current, reason: calls.append((current, reason))

    strategy._submit("okx", "buy", D(".01"), D("100"), "open_long", position_side="long")

    assert calls == [(exposures, "pair_deadline")]

    strategy = strategy_stub()
    update_pair(strategy.engine, D("10"), seq=1)
    strategy._funding_states = strategy._static_funding_states(D("0"))
    strategy.pending_order = None
    strategy.pair_state = {"phase": "flatten"}
    strategy.pair_deadline = D("20")
    strategy.awaiting_reconciliation = False
    strategy.unknown = False
    strategy._now = lambda: D("10.5")
    strategy.notify_orderbook(orderbook_event("okx", "100", "100.1", "10.5", 2))
    assert strategy.engine.books["okx"].sequence == 2


def test_mid_unknown_transition_advances_fence_and_requests_new_snapshot():
    strategy = strategy_stub()
    requests = []
    strategy.broker.request_reconcile = lambda: requests.append(True) or {"queued": True}
    strategy.unknown = False
    strategy._reconcile_min_as_of_ns = 10_000_000_000

    strategy._mark_unknown("cancel_deadline")

    assert strategy._reconcile_min_as_of_ns > 10_000_000_000
    assert requests == [True]


def test_mid_repeated_stale_reconcile_snapshot_keeps_fence_and_fresh_snapshot_recovers():
    strategy = strategy_stub()
    now = {"value": D("10")}
    strategy._now = lambda: now["value"]
    requests = []
    strategy.broker.request_reconcile = lambda: requests.append(True) or {"queued": True}
    strategy.unknown = False
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
    assert strategy.unknown is False
    assert strategy.awaiting_reconciliation is False
    assert requests == [True]


def test_mid_unknown_external_fence_advance_requests_exactly_once():
    strategy = strategy_stub()
    now = {"value": D("10")}
    strategy._now = lambda: now["value"]
    requests = []
    strategy.broker.request_reconcile = lambda: requests.append(True) or {"queued": True}
    strategy.unknown = False
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


def test_mid_failed_cycle_keeps_entry_funding_evidence_and_requires_crossing_ledger():
    strategy = strategy_stub()
    strategy._cycle_id = 1
    strategy._wall_now = lambda: D("12")
    snapshot = {
        "captured_at_epoch": D("10"),
        "venues": {
            venue: FundingSnapshot(
                exchange_name=venue,
                symbol=mid.VENUE_SYMBOLS[venue],
                rate=D(".0001"),
                next_funding_time=datetime.fromtimestamp(11, tz=UTC),
                settlement_interval_seconds=28800,
                source="exchange",
                freshness=Freshness(
                    source="exchange",
                    observed_at=datetime.fromtimestamp(10, tz=UTC),
                ),
            )
            for venue in mid.VENUE_SYMBOLS
        },
    }
    strategy.pair_state = {
        "intent": SimpleNamespace(buy_price=D("100"), sell_price=D("101")),
        "phase": "open_long",
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

    assert strategy._finalize_realized_close(signed_funding=D("0")) is True
    economics = strategy.execution_economics_history[-1]
    assert economics["signed_funding_cashflow"] == "0"
    assert "signed_funding" not in economics


def account_risk_snapshot(**changes):
    snapshot = {
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
    snapshot.update(changes)
    return snapshot


def ar_samples(beta, count=180):
    value = D("0")
    innovations = (D("1"), D("-.7"), D(".2"), D("-.4"), D(".8"), D("-.2"))
    result = []
    for index in range(count):
        value = D(beta) * value + innovations[index % len(innovations)]
        result.append(value)
    return result


def qualify(samples, maximum_half_life="20", **changes):
    venue_rules = changes.pop("venue_rules", rules())
    risk_config = changes.pop("risk_config", risk())
    direction = changes.pop("direction", ("okx", "binance"))
    args = {
        "sample_interval_seconds": D("1"),
        "maximum_half_life_seconds": D(maximum_half_life),
        "valid_from_epoch": D("0"),
        "valid_until_epoch": D("1000"),
        "buy_venue": direction[0],
        "sell_venue": direction[1],
        "minimum_samples": len(samples),
        "source_data_sha256": source_data_sha256(samples),
        "provenance": "unit-test-source",
        "qualification_contract_sha256": mid.qualification_contract_sha256(
            venue_rules, risk_config, *direction
        ),
    }
    args.update(changes)
    return mid.qualify_basis_model(samples, **args)


def test_model_qualification_accepts_stationary_series_with_explicit_provenance():
    artifact = qualify(ar_samples(".45"))

    assert artifact.qualified is True
    assert artifact.half_life_seconds <= artifact.maximum_half_life_seconds
    assert artifact.basis_series_sha256 != artifact.source_data_sha256
    assert artifact.provenance == "unit-test-source"


def test_model_qualification_rejects_trend_random_walk_break_and_long_half_life():
    trend = qualify([D(index) for index in range(180)])
    random_walk = []
    level = D("0")
    for innovation in ar_samples("0", 180):
        level += innovation
        random_walk.append(level)
    stationary = ar_samples(".45")
    broken = qualify(stationary[:90] + [value + D("50") for value in stationary[90:]])
    long_half_life = qualify(ar_samples(".98"), maximum_half_life="2")

    assert trend.qualified is False
    assert qualify(random_walk).qualified is False
    assert broken.qualified is False
    assert broken.rejection_reason == "model_structural_break"
    assert long_half_life.qualified is False


def test_model_qualification_rejects_seeded_random_walks_conservatively():
    for seed in (*range(8), 8, 18):
        rng = random.Random(seed)
        level = D("0")
        samples = []
        for _ in range(180):
            level += D(str(rng.gauss(0, 1)))
            samples.append(level)
        artifact = qualify(samples)
        assert artifact.qualified is False, (seed, artifact.as_dict())


def test_nonzero_equilibrium_basis_is_not_counted_as_capturable_profit():
    venue_rules = rules()
    risk_config = risk(entry_zscore=D("1"))
    samples = [value + D("10") for value in ar_samples(".45")]
    artifact = qualify(
        samples,
        venue_rules=venue_rules,
        risk_config=risk_config,
        direction=("okx", "binance"),
    )
    engine = mid.MidFrequencyEngine(
        venue_rules,
        risk_config,
        artifact,
        wall_clock=lambda: D("10"),
    )
    engine.models[("okx", "binance")].values.extend(
        D("10") + value for value in (D("-.1"), D("0"), D(".1"), D("-.05"), D(".05"))
    )
    update_pair(
        engine,
        1,
        okx=("99.9", "100"),
        binance=("110.2", "110.3"),
    )

    assert engine.evaluate(D("1")) is None
    assert engine.reject_reasons["net_edge"] == 1
    assert engine.cost_history[-1].expected_exit_basis > D("10")
    assert engine.cost_history[-1].expected_gross_convergence < D("0")


def test_legacy_qualification_without_equilibrium_fields_is_rejected():
    artifact = dict(qualification().as_dict())
    artifact.pop("equilibrium_basis")
    artifact.pop("equilibrium_upper_confidence")

    with pytest.raises(TypeError):
        mid.BasisModelQualification(**artifact)


def test_model_qualification_is_bound_to_exact_strategy_contract():
    venue_rules = rules()
    risk_config = risk()
    artifact = qualification(venue_rules, risk_config)
    tampered = replace(artifact, qualification_contract_sha256="c" * 64)
    engine = mid.MidFrequencyEngine(
        venue_rules,
        risk_config,
        tampered,
        wall_clock=lambda: D("10"),
    )
    update_pair(engine, 1)

    assert engine.evaluate(D("1")) is None
    assert engine.reject_reasons["model_contract_binding"] == 1
    changed_risk = replace(risk_config, cancel_deadline_seconds=D(".5"))
    assert mid.qualification_contract_sha256(
        venue_rules, risk_config, "okx", "binance"
    ) != mid.qualification_contract_sha256(venue_rules, changed_risk, "okx", "binance")


def test_serialized_qualification_rejects_non_boolean_flags():
    artifact = dict(qualification().as_dict())
    artifact["qualified"] = "false"

    with pytest.raises(ValueError, match="flags must be booleans"):
        mid.BasisModelQualification(**artifact)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"unit_root_pvalue": "-0.1"}, "unit_root_pvalue"),
        ({"lag1_upper_confidence": "0"}, "fitted magnitude"),
        ({"rejection_reason": "contradiction"}, "qualified artifact"),
    ),
)
def test_serialized_qualification_rejects_internally_inconsistent_statistics(changes, message):
    artifact = {**qualification().as_dict(), **changes}

    with pytest.raises(ValueError, match=message):
        mid.BasisModelQualification(**artifact)


def test_one_direction_qualification_cannot_authorize_reverse_basis():
    venue_rules = rules()
    risk_config = risk(entry_zscore=D("1"))
    only_forward = qualification(
        venue_rules,
        risk_config,
        direction=("okx", "binance"),
    )
    engine = mid.MidFrequencyEngine(
        venue_rules,
        risk_config,
        only_forward,
        wall_clock=lambda: D("10"),
    )
    seed(engine)
    update_pair(
        engine,
        1,
        okx=("101", "101.1"),
        binance=("99.9", "100"),
    )

    assert engine.evaluate(D("1")) is None
    assert engine.reject_reasons["model_qualification_missing_binance_to_okx"] == 1


def test_direction_qualification_mapping_round_trips_through_serialized_dicts():
    venue_rules = rules()
    risk_config = risk()
    serialized = {
        "->".join(direction): artifact.as_dict()
        for direction, artifact in qualifications(venue_rules, risk_config).items()
    }

    engine = mid.MidFrequencyEngine(venue_rules, risk_config, serialized)

    assert set(engine.model_qualifications) == {
        ("okx", "binance"),
        ("binance", "okx"),
    }


def test_public_shadow_observes_qualified_intent_with_zero_execution_accounting():
    assert not hasattr(mid.CrossExchangeArbitrageStrategy, "report")
    assert hasattr(mid.MidFrequencyEngine, "report")
    venue_rules = rules()
    risk_config = risk()
    strategy = object.__new__(mid.CrossExchangeArbitrageStrategy)
    strategy.p = SimpleNamespace(
        rules=venue_rules,
        risk=risk_config,
        model_qualification=qualifications(venue_rules, risk_config),
        funding=explicit_funding(),
        account_risk_ledger=None,
        execution_enabled=False,
        shadow=True,
    )
    strategy.datas = [
        SimpleNamespace(_name=mid.VENUE_SYMBOLS["okx"]),
        SimpleNamespace(_name=mid.VENUE_SYMBOLS["binance"]),
    ]
    strategy.broker = SimpleNamespace(getvalue=lambda: 100)
    mid.CrossExchangeArbitrageStrategy.__init__(strategy)
    strategy.engine._wall_clock = lambda: D("10")
    assert strategy.engine.report() == strategy.engine.snapshot()
    seed(strategy.engine)

    strategy.notify_orderbook(orderbook_event("okx", "99.9", "100", "1", 1))
    strategy.notify_orderbook(orderbook_event("binance", "101", "101.1", "1", 1))

    report = strategy.trade_logger_context()
    assert len(strategy.engine.intent_history) == 1
    assert report["submitted_order_count"] == 0
    assert report["confirmed_fill_events"] == 0
    assert report["execution_economics"] == []
    assert report["account_risk_status"] == "NOT_APPLICABLE_OBSERVATION_ONLY"


def test_model_qualification_missing_or_expired_fails_closed():
    missing = mid.MidFrequencyEngine(rules(), risk(), wall_clock=lambda: D("10"))
    expired = new_engine(
        rules(),
        risk(),
        qualification(valid_until_epoch=D("10")),
        wall_clock=lambda: D("10"),
    )
    update_pair(missing, 1)
    update_pair(expired, 1)

    assert missing.evaluate(D("1")) is None
    assert expired.evaluate(D("1")) is None
    assert missing.reject_reasons["model_qualification_missing"] == 1
    assert expired.reject_reasons["model_qualification_expired"] == 1


def test_ac_mid_001_positive_edge_without_zscore_is_rejected():
    engine = new_engine(rules(), risk(entry_zscore=D("3")))
    seed(engine)
    update_pair(engine, 1, binance=("100.2", "100.3"))

    assert engine.evaluate(D("1")) is None
    assert engine.reject_reasons["deviation_gate"] >= 1


def test_ac_mid_002_zscore_passes_but_full_round_trip_net_edge_does_not():
    engine = new_engine(rules(".01"), risk(entry_zscore=D("1")))
    seed(engine)
    update_pair(engine, 1, binance=("101", "101.1"))

    assert engine.evaluate(D("1")) is None
    assert engine.reject_reasons["net_edge"] >= 1


def test_ac_mid_003_confirmed_robust_deviation_creates_correct_pair_intent():
    engine = new_engine(
        rules(),
        risk(confirmations=3, persistence_seconds=D("2"), entry_zscore=D("3")),
    )
    seed(engine)
    decision = None
    for sequence, now in enumerate((5, 6, 7), 1):
        update_pair(engine, now, seq=sequence)
        decision = engine.evaluate(D(now))

    assert decision is not None
    assert (decision.long_venue, decision.short_venue) == ("okx", "binance")
    assert decision.quantity_base == D(".01")
    assert decision.cost.expected_net > D("0")


def test_ac_mid_004_depth_is_floored_to_common_lattice():
    engine = new_engine(rules(), risk(quantity_base=D(".037"), entry_zscore=D("1")))
    seed(engine)
    update_pair(engine, 1, seq=1, size=".025")

    decision = engine.evaluate(D("1"))

    assert decision is not None
    assert decision.quantity_base == D(".02")


def test_entry_and_exit_preview_use_multilevel_vwap_and_marginal_ioc_limits():
    engine = new_engine(rules(), risk(entry_zscore=D("1")))
    seed(engine)
    engine.update_book(
        mid.BookState(
            "okx",
            ((D("99.9"), D(".005")), (D("99.8"), D(".005"))),
            ((D("100"), D(".005")), (D("100.2"), D(".005"))),
            D("1"),
            D("1"),
            1,
            continuity_status="snapshot",
        )
    )
    engine.update_book(
        mid.BookState(
            "binance",
            ((D("101"), D(".005")), (D("100.8"), D(".005"))),
            ((D("101.1"), D(".005")), (D("101.3"), D(".005"))),
            D("1"),
            D("1"),
            1,
            continuity_status="snapshot",
        )
    )

    intent = engine.evaluate(D("1"))

    assert intent.entry_buy.price == D("100.1")
    assert intent.entry_buy.marginal_price == D("100.2")
    assert intent.entry_sell.price == D("100.9")
    assert intent.entry_sell.marginal_price == D("100.8")
    assert intent.exit_sell_preview.levels_consumed == 2
    assert intent.exit_buy_preview.levels_consumed == 2
    assert intent.cost.expected_exit_execution_cost > 0


def test_ac_mid_007_signed_funding_is_included_for_each_leg():
    engine = new_engine(
        rules(),
        risk(entry_zscore=D("1"), maximum_holding_seconds=D("31")),
    )
    seed(engine)
    engine.update_book(
        book(
            "okx",
            "99.9",
            "100",
            "100",
            1,
            funding_rate=D(".001"),
            next_funding_time=D("110"),
        )
    )
    engine.update_book(
        book(
            "binance",
            "101",
            "101.1",
            "100",
            1,
            funding_rate=D(".002"),
            next_funding_time=D("110"),
        )
    )

    decision = engine.evaluate(D("100"))

    assert decision is not None
    # One settlement: long pays 0.001 and short receives 0.002.
    assert decision.cost.signed_funding_cashflow > D("0")


def test_complete_snapshots_allow_large_sequence_jumps_but_broken_delta_freezes():
    engine = new_engine(rules(), risk())
    update_pair(engine, 1, seq=100)
    assert engine.update_book(book("okx", "99.9", "100", 2, 9000))
    assert not engine.gapped_venues
    assert not engine.update_book(
        book(
            "binance",
            "101",
            "101.1",
            2,
            800000,
            previous_sequence=7,
            snapshot_or_delta="delta",
        )
    )
    assert "binance" in engine.gapped_venues

    assert not engine.update_book(book("okx", "99.9", "100", 3, 9000))
    assert "okx" in engine.gapped_venues
    assert engine.update_book(
        book(
            "okx",
            "99.9",
            "100",
            4,
            9001,
            continuity_status="recovered",
            recovery_snapshot=True,
        )
    )
    assert "okx" not in engine.gapped_venues


def test_initial_delta_without_recovery_snapshot_is_fail_closed():
    engine = new_engine(rules(), risk())

    assert not engine.update_book(
        book(
            "okx",
            "99.9",
            "100",
            1,
            1,
            previous_sequence=0,
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
    engine = new_engine(rules(), risk())

    accepted = engine.update_book(
        book("okx", "99.9", "100", 1, sequence, continuity_status=continuity)
    )

    assert accepted is False
    assert "okx" in engine.gapped_venues
    assert engine.books == {}
    assert engine.reject_reasons[reason] == 1


def test_ac_mid_005_convergence_requires_positive_executable_realized_net():
    engine = new_engine(rules(), risk(entry_zscore=D("1"), exit_reserve_bps=D("1")))
    seed(engine)
    update_pair(engine, 1)
    intent = engine.evaluate(D("1"))
    engine.mark_open(intent, D("1"))
    update_pair(
        engine,
        2,
        okx=("100", "100.1"),
        binance=("100.1", "100.2"),
        seq=2,
    )

    assert engine.exit_reason(D("2")) == "convergence"
    assert D(engine.last_exit_economics["realized_net"]) > 0
    assert D(engine.last_exit_economics["total_preview_reserve"]) == 0
    assert "expected_exit_execution_cost" not in engine.last_exit_economics


def test_converged_zscore_with_negative_executable_close_stays_open():
    engine = new_engine(rules(), risk(entry_zscore=D("1"), maximum_loss_bps=D("1000000")))
    seed(engine)
    update_pair(engine, 1)
    intent = engine.evaluate(D("1"))
    engine.mark_open(intent, D("1"))
    update_pair(
        engine,
        2,
        okx=("90", "100"),
        binance=("100", "110"),
        seq=2,
    )

    assert engine.exit_reason(D("2")) is None
    assert engine.reject_reasons["convergence_not_profitable"] == 1
    assert D(engine.last_exit_economics["risk_adjusted_net"]) < 0


def test_ac_mid_008_exit_risk_reasons_are_deterministic():
    engine = new_engine(rules(), risk(entry_zscore=D("1")))
    seed(engine)
    update_pair(engine, 1)
    intent = engine.evaluate(D("1"))
    engine.mark_open(intent, D("1"))

    assert engine.exit_reason(D("1"), margin_ok=False) == "margin"
    assert engine.exit_reason(D("400")) == "stale"

    update_pair(engine, 302, seq=2)
    assert engine.exit_reason(D("302")) == "maximum_holding"


def test_pair_notional_bps_stop_uses_executable_four_fill_preview():
    engine = new_engine(rules(), risk(entry_zscore=D("1"), maximum_loss_bps=D("100")))
    seed(engine)
    update_pair(engine, 1)
    intent = engine.evaluate(D("1"))
    engine.mark_open(intent, D("1"))
    update_pair(engine, 2, okx=("99", "99.1"), binance=("101.9", "102"), seq=2)

    assert engine.exit_reason(D("2")) == "loss"
    assert D(engine.last_exit_economics["realized_net"]) < -(
        engine.active_pair.entry_mean_notional * D("100") / D("10000")
    )


@pytest.mark.parametrize(
    ("pair_deadline", "execution_deadline_ns", "cancel_deadline_ns"),
    (
        (D("15"), 12_000_000_000, 13_000_000_000),
        (D("11"), 11_000_000_000, 11_000_000_000),
    ),
)
def test_mid_submit_uses_marginal_depth_price_and_capped_broker_deadlines(
    pair_deadline,
    execution_deadline_ns,
    cancel_deadline_ns,
):
    strategy = object.__new__(mid.CrossExchangeArbitrageStrategy)
    strategy.rules = rules()
    strategy.risk = risk()
    strategy.engine = new_engine(strategy.rules, strategy.risk)
    strategy.p = SimpleNamespace(funding=explicit_funding(), funding_snapshot_provider=None)
    strategy.pending_order = None
    strategy.engine.update_book(
        mid.BookState(
            "okx",
            ((D("101.05"), D(".005")), (D("100.83"), D(".005"))),
            ((D("101.2"), D(".01")),),
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
    strategy.unknown = False
    strategy._now = lambda: D("10")
    submitted = []

    def submit(**kwargs):
        submitted.append(kwargs)
        return SimpleNamespace(ref=42)

    strategy.sell = submit
    strategy._submit(
        "okx",
        "sell",
        D(".01"),
        D("101"),
        "open_short",
        position_side="short",
    )

    kwargs = submitted[0]
    assert kwargs["price"] == D("100.8")
    assert kwargs["size"] == D("1")
    assert kwargs["execution_deadline_monotonic_ns"] == execution_deadline_ns
    assert kwargs["cancel_deadline_monotonic_ns"] == cancel_deadline_ns
    assert kwargs["cancel_deadline_monotonic_ns"] <= int(pair_deadline * D("1000000000"))


def test_mid_strategy_consumes_sdk_loss_latch_and_never_unlocks_on_rebound():
    strategy = strategy_stub()
    strategy.p.account_risk_ledger = account_risk_snapshot(
        current_equity="100",
        realized_net="0",
        trading_blocked=True,
        loss_limit_bps="50.0",
        loss_limit_breached=True,
    )

    assert strategy._account_loss_allows_entry() is False
    assert strategy.account_loss_kill_switch is True

    strategy.p.account_risk_ledger = account_risk_snapshot(
        current_equity="100",
        realized_net="0",
        generation=2,
        fencing_epoch=2,
    )
    assert strategy._account_loss_allows_entry() is False
    assert strategy.account_loss_kill_switch is True
    assert strategy.account_risk_status == "loss_limit"


def test_mid_strategy_requires_exact_sdk_loss_limit_binding():
    strategy = strategy_stub()
    strategy.p.account_risk_ledger = account_risk_snapshot(loss_limit_bps="50.0001")

    assert strategy._account_loss_allows_entry() is False
    assert strategy.account_loss_kill_switch is True
    assert strategy.account_risk_status == "invalid_contract"
    assert strategy.engine.reject_reasons["account_risk_loss_limit_mismatch"] == 1


def test_mid_strategy_cancel_retry_deadline_is_capped_to_pair_deadline():
    strategy = strategy_stub()
    strategy.pair_state = {
        "intent": SimpleNamespace(long_venue="okx", short_venue="binance"),
        "phase": "open_short",
        "fills": {},
        "exposures": {},
    }
    strategy.pair_deadline = D("10.25")
    strategy.cancel_requested = True
    strategy.pending_order = SimpleNamespace(
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
    strategy.known_order_refs = {35}
    strategy.processed_order_refs = set()
    strategy.remote_flat_proven = False
    cancellations = []
    strategy.cancel = lambda current: cancellations.append(current.ref)

    strategy.notify_order(strategy.pending_order)

    assert cancellations == [35]
    assert strategy.cancel_deadline == strategy.pair_deadline == D("10.25")


def test_ac_mid_009_entry_threshold_changes_signal_and_current_sample_is_not_future_data():
    low = new_engine(rules(), risk(entry_zscore=D("3")))
    high = new_engine(rules(), risk(entry_zscore=D("30")))
    seed(low)
    seed(high)
    before = tuple(low.models[("okx", "binance")].values)
    update_pair(low, 1)
    update_pair(high, 1)

    assert low.evaluate(D("1")) is not None
    assert high.evaluate(D("1")) is None
    assert before[-1] != D("1")
    assert tuple(low.models[("okx", "binance")].values)[-1] == D("1.10")


def test_mid_flatten_retry_only_consumes_head_venue_new_sequence():
    strategy = strategy_stub()
    strategy.pending_order = None
    strategy.pair_deadline = D("20")
    strategy.awaiting_reconciliation = False
    strategy.unknown = False
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
def test_mid_terminal_incomplete_flatten_waits_for_new_book_before_resubmit(
    filled_native,
    fill_price,
    expected_remaining,
):
    strategy = strategy_stub()
    order = SimpleNamespace(
        ref=71,
        info={},
        data=SimpleNamespace(_name=mid.VENUE_SYMBOLS["binance"]),
        executed=SimpleNamespace(size=filled_native, price=fill_price, comm=D(".001")),
        alive=lambda: False,
        isbuy=lambda: True,
        getstatusname=lambda: "Completed",
    )
    strategy.pending_order = order
    strategy.known_order_refs = {order.ref}
    strategy.processed_order_refs = set()
    strategy.order_records = {}
    strategy.pair_deadline = D("20")
    strategy.leg_deadline = D("15")
    strategy.cancel_deadline = D("16")
    strategy.awaiting_reconciliation = False
    strategy.unknown = False
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


def test_mid_empty_flatten_queue_submit_failure_is_unknown():
    strategy = strategy_stub()
    strategy.broker.request_reconcile = lambda: {"queued": True}
    strategy.pending_order = None
    strategy.awaiting_reconciliation = False
    strategy.unknown = False
    strategy.pair_state = {"phase": "flatten", "flatten_queue": []}

    strategy._handle_local_submit_failure("order_depth", "flatten", True)

    assert strategy.unknown is True
    assert strategy.awaiting_reconciliation is True
    assert "flatten_waiting_for_book" not in strategy.pair_state
    assert strategy.engine.reject_reasons["flatten_queue_missing"] == 1


def test_mid_flatten_book_wait_past_deadline_becomes_unknown():
    strategy = strategy_stub()
    strategy.broker.request_reconcile = lambda: {"queued": True}
    strategy.pending_order = None
    strategy.pair_deadline = D("9")
    strategy.awaiting_reconciliation = False
    strategy.unknown = False
    strategy.pair_state = {
        "phase": "flatten",
        "flatten_queue": [{"venue": "okx"}],
        "flatten_waiting_for_book": "terminal_remaining",
    }

    strategy.notify_idle()

    assert strategy.unknown is True
    assert strategy.awaiting_reconciliation is True
    assert strategy.engine.reject_reasons["flatten_deadline"] == 1


def test_mid_stale_book_does_not_hide_wall_clock_funding_settlement():
    engine = new_engine(rules(), risk(entry_zscore=D("1")))
    seed(engine)
    update_pair(engine, D(".5"), seq=1)
    intent = engine.evaluate(D(".5"))
    assert intent is not None
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
    economics = strategy.execution_economics_history[-1]
    assert D(economics["signed_funding_cashflow"]) == D("0")
    assert "signed_funding" not in economics
