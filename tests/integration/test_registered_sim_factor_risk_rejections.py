"""Risk-rejection composition through ordinary Strategy and Broker paths.

The registered-sim Store, execution coordinator, journal, Cerebro and Broker
are production objects. Synthetic provider/query data is limited to the public
leaves used by the existing fill-race composition fixture.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import MethodType

import pytest
from backtrader.order import Order
from backtrader.stores.execution_decision_journal import ExecutionIntentKey

from tests.integration import test_factor_execution_fill_races as fill_race
from tests.unit.stores import test_factor_execution as execution_path
from tests.unit.stores import test_factor_execution_facts as facts_path
from tests.unit import test_alpha003_simnow_strategy as alpha003_path


_UTC = timezone.utc
_ALPHA003 = alpha003_path._STRATEGY
_ALPHA003_STRATEGY = _ALPHA003.Alpha003TargetStrategy


def _query_rows(*, available, upper_limit=1000, lower_limit=1, positions=()):
    rows = fill_race._single_route_query_rows(
        facts_path._INSTRUMENT,
        facts_path._EXCHANGE,
        positions=positions,
    )
    rows["account_result"] = [{"Available": str(available), "CurrMargin": "0"}]
    rows["instruments_result"][0]["UpperLimitPrice"] = upper_limit
    rows["instruments_result"][0]["LowerLimitPrice"] = lower_limit
    return rows


def _system(monkeypatch, *, now, available, upper_limit=1000, lower_limit=1, positions=()):
    fill_race._bind_fixture_trading_day(monkeypatch, now)
    rows = _query_rows(
        available=available,
        upper_limit=upper_limit,
        lower_limit=lower_limit,
        positions=positions,
    )
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        data,
        _strategy,
        cerebro,
    ) = execution_path._system(now=now, query_rows=rows)
    store.registered_sim_configure_arm_templates(
        {
            (facts_path._INSTRUMENT, facts_path._EXCHANGE): fill_race._route_template(
                "risk-rejections"
            )
        }
    )

    # The tick, multiplier and margin match the public query rows. The minimum
    # and step use Broker-supported contract metadata fields. Only the SDK
    # balance leaf is supplied here; validation and routing remain real.
    broker._contract_metadata[facts_path._INSTRUMENT].update(
        {
            "min_price_tick": 1,
            "min_order_size": 1,
            "order_size_step": 1,
            "multiplier": 10,
            "margin_rate": 0.1,
        }
    )
    broker.p.validation_enabled = True
    broker.p.cash_check_enabled = True
    api.balance_reads = []

    def get_balance():
        api.balance_reads.append(True)
        source_available = float(api.query_rows["account_result"][0]["Available"])
        return {"cash": source_available, "value": source_available}

    api.get_balance = get_balance
    return api, store, broker, journal, coordinator, target, data, cerebro


def _source_facts(store, broker, target, now):
    query = facts_path._refresh_all(store, target)
    assert facts_path._consume_quote(store) is not None
    facts = facts_path._project(store, broker, target, now, query_set=query.query_set)
    return facts


def _submit_from_strategy(
    *,
    owner,
    coordinator,
    facts,
    data,
    now,
    quantity,
    price,
    leg=0,
):
    key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=facts_path._INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=leg,
    )
    batch_id = "fill-race-batch-0"
    economics = fill_race._open_economics(
        facts_path._INSTRUMENT,
        facts_path._EXCHANGE,
        quantity,
        batch_id=batch_id,
    )
    economics.update(quantity=str(quantity), limit_price=str(price), price=str(price))
    with fill_race._live_decision_scope(
        coordinator,
        owner,
        facts,
        now=now,
        grid_index=0,
        intent_keys=(key,),
        economics=(economics,),
    ):
        return owner.buy(
            data=data,
            size=quantity,
            price=price,
            exectype=Order.Limit,
            instrument_id=facts_path._INSTRUMENT,
            exchange_id=facts_path._EXCHANGE,
            factor_position_effect="OPEN",
            factor_strategy_scope=execution_path._SCOPE,
            offset="open",
        )


@pytest.mark.parametrize(
    ("case", "quantity", "price", "available", "minimum", "step", "error_code"),
    [
        ("tick", 1, 100.5, 100_000, 1, 1, "invalid_price_tick"),
        ("minimum", 1, 100, 100_000, 2, 1, "min_order_size_not_met"),
        ("step", 1, 100, 100_000, 1, 2, "invalid_order_size_step"),
        ("funds", 1, 100, 1, 1, 1, "insufficient_cash"),
    ],
)
def test_actual_strategy_broker_rejects_invalid_risk_before_native_dispatch(
    monkeypatch, case, quantity, price, available, minimum, step, error_code
):
    """Tick, lot and margin checks run inside the real Strategy/Broker route."""
    now = datetime.now(_UTC)
    api, store, broker, _journal, coordinator, target, data, cerebro = _system(
        monkeypatch,
        now=now,
        available=available,
    )
    broker._contract_metadata[facts_path._INSTRUMENT].update(
        min_order_size=minimum,
        order_size_step=step,
    )
    facts = _source_facts(store, broker, target, now)
    assert facts.open_risk_ready is True, (case, facts.blockers)
    state = {"order": None, "calls": 0}

    def command(owner):
        state["calls"] += 1
        state["order"] = _submit_from_strategy(
            owner=owner,
            coordinator=coordinator,
            facts=facts,
            data=owner.data0,
            now=now,
            quantity=quantity,
            price=price,
        )

    cerebro.addstrategy(execution_path._EngineBuyStrategy, command=command)
    result = cerebro.run(runonce=False, preload=False)

    assert len(result) == 1
    assert state["calls"] == 1
    assert state["order"] is not None
    assert state["order"].getstatusname() == "Rejected"
    assert state["order"].info["error_code"] == error_code
    assert api.native_calls == []
    if case == "funds":
        assert api.balance_reads


def test_actual_strategy_broker_valid_control_reaches_one_native_insert(monkeypatch):
    """The same production path admits a valid, source-aligned opening order."""
    now = datetime.now(_UTC)
    api, store, broker, _journal, coordinator, target, data, cerebro = _system(
        monkeypatch,
        now=now,
        available=100_000,
    )
    facts = _source_facts(store, broker, target, now)
    assert facts.open_risk_ready is True, facts.blockers
    state = {"order": None}

    def command(owner):
        state["order"] = _submit_from_strategy(
            owner=owner,
            coordinator=coordinator,
            facts=facts,
            data=owner.data0,
            now=now,
            quantity=1,
            price=100,
        )

    cerebro.addstrategy(execution_path._EngineBuyStrategy, command=command)
    result = cerebro.run(runonce=False, preload=False)

    assert len(result) == 1
    assert state["order"] is not None and state["order"].alive()
    assert state["order"].info["factor_dispatch_state"] == "KNOWN"
    assert api.native_calls == [
        ("insert", facts_path._INSTRUMENT, facts_path._EXCHANGE, "501", 101)
    ]


def _risk_batch(now):
    close_time = now - timedelta(seconds=6)
    return fill_race.LiveCohortBatch(
        batch_id="fill-race-batch-0",
        cohort_id=execution_path._COHORT,
        calendar_id=execution_path._CALENDAR,
        calendar_version="v1",
        epoch_id=1,
        slot_index=0,
        close_time=close_time,
        available_at=close_time + timedelta(milliseconds=1),
    )


def _alpha003_target(batch):
    return _ALPHA003.Alpha003TargetDecision(
        status="TARGETS_READY",
        reason=None,
        factor_name="alpha003",
        mode="native",
        execution_mode="LIVE",
        direction=1,
        source_sha256="a" * 64,
        cohort_id=execution_path._COHORT,
        batch_id=batch.batch_id,
        close_time=batch.close_time,
        available_at=batch.available_at,
        eligible_grid_index=5,
        rebalance_every=5,
        authorized_targets=("rb",),
        eligible_targets=("rb",),
        targets=(
            _ALPHA003.Alpha003SignalTarget(
                target_id="rb",
                product_key=(facts_path._EXCHANGE, facts_path._INSTRUMENT),
                target_position=1,
                raw_score=2.0,
                oriented_score=2.0,
            ),
        ),
    )


def _run_alpha003_plan(monkeypatch, *, now, upper_limit, lower_limit=1, positions=()):
    api, store, broker, _journal, coordinator, target, _data, cerebro = _system(
        monkeypatch,
        now=now,
        available=100_000,
        upper_limit=upper_limit,
        lower_limit=lower_limit,
        positions=positions,
    )
    # Hydrate the actual Broker before comparing its local book with the
    # source query projection. Cerebro's later start is idempotent.
    broker.start()
    facts = _source_facts(store, broker, target, now)
    batch = _risk_batch(now)
    target_decision = _alpha003_target(batch)
    planning = _ALPHA003._live_planning_input(
        facts,
        strategy_scope=execution_path._SCOPE,
        evaluated_at=now,
        risk_evidence_available_at=batch.available_at,
        session_close_at=now + timedelta(hours=1),
        run_end=False,
        risk_policy=alpha003_path._risk_policy(
            max_loss_per_position=Decimal("50"),
            max_total_loss=Decimal("100"),
        ),
        target_decision=target_decision,
        eligible_grid_ordinal=1,
        run_order_intents_used=coordinator.run_order_count(),
    )
    state = {"plan": None}

    def command(owner):
        owner._data_by_target = {"rb": owner.data0}
        owner._strategy_scope = execution_path._SCOPE
        owner._risk_policy = planning.risk_policy
        owner._risk_policy_payload = MethodType(_ALPHA003_STRATEGY._risk_policy_payload, owner)
        owner._order_intents = MethodType(_ALPHA003_STRATEGY._order_intents, owner)
        owner._orders_by_broker_ref = {}
        plan = _ALPHA003.plan_alpha003_orders(planning)
        state["plan"] = plan
        if not plan.actions:
            _ALPHA003_STRATEGY._dispatch_live_actions(owner, plan.actions, batch)
            return
        keys, economics = owner._order_intents(plan, batch)
        with fill_race._live_decision_scope(
            coordinator,
            owner,
            facts,
            now=now,
            grid_index=0,
            intent_keys=keys,
            economics=economics,
        ):
            _ALPHA003_STRATEGY._dispatch_live_actions(owner, plan.actions, batch)

    cerebro.addstrategy(execution_path._EngineBuyStrategy, command=command)
    result = cerebro.run(runonce=False, preload=False)
    assert len(result) == 1
    return api, broker, state["plan"], facts


def test_alpha003_price_band_and_foreign_position_block_actual_strategy_dispatch(monkeypatch):
    """Production Alpha003 planning emits no Broker action for invalid risk facts."""
    now = datetime.now(_UTC)
    api, _broker, plan, _facts = _run_alpha003_plan(
        monkeypatch,
        now=now,
        upper_limit=100,
    )
    assert plan.status == "BLOCKED"
    assert plan.reason == "CURRENT_QUOTE_INVALID_OR_STALE"
    assert plan.actions == ()
    assert api.native_calls == []

    trading_day = now.astimezone(fill_race._SHANGHAI).strftime("%Y%m%d")
    foreign_position = facts_path._dated_position_row(
        "1",
        trading_day=trading_day,
    )
    api, _broker, plan, facts = _run_alpha003_plan(
        monkeypatch,
        now=now,
        upper_limit=1000,
        positions=(foreign_position,),
    )
    assert facts.positions[0].quantity == Decimal("1")
    assert facts.positions[0].owner_intent_id is None
    assert plan.status == "BLOCKED"
    assert plan.reason == "UNOWNED_POSITION"
    assert plan.actions == ()
    assert api.native_calls == []


def test_alpha003_quote_below_lower_limit_blocks_actual_strategy_dispatch(monkeypatch):
    """The actual bid/ask below the queried lower band cannot reach Broker dispatch."""
    now = datetime.now(_UTC)
    api, _broker, plan, facts = _run_alpha003_plan(
        monkeypatch,
        now=now,
        upper_limit=1000,
        lower_limit=102,
    )

    assert len(facts.quotes) == 1
    quote = facts.quotes[0]
    assert quote.bid is not None and quote.ask is not None
    assert facts.instruments[0].lower_limit == Decimal("102")
    assert quote.bid < facts.instruments[0].lower_limit
    assert quote.ask < facts.instruments[0].lower_limit
    assert plan.status == "BLOCKED"
    assert plan.reason == "CURRENT_QUOTE_INVALID_OR_STALE"
    assert plan.actions == ()
    assert api.native_calls == []


def test_alpha003_valid_plan_dispatches_through_the_same_broker_composition(monkeypatch):
    """A valid Alpha003 planner action traverses its real dispatcher and Broker."""
    now = datetime.now(_UTC)
    api, _broker, plan, facts = _run_alpha003_plan(
        monkeypatch,
        now=now,
        upper_limit=1000,
    )
    assert plan.status == "READY", plan.reason
    assert len(plan.actions) == 1
    assert plan.actions[0].limit_price == Decimal("101")
    assert api.native_calls == [
        ("insert", facts_path._INSTRUMENT, facts_path._EXCHANGE, "501", 101)
    ]
