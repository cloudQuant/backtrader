"""Actual Broker composition tests for execution fill races.

These tests reuse the accepted Cerebro/RegisteredSimStore/BtApiBroker/journal
composition in ``tests.unit.stores.test_factor_execution``. Only the provider
callback and query leaves are synthetic; orders and fills pass through the
ordinary engine and Broker polling path.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import backtrader as bt
import pandas as pd
import pytest
from backtrader.order import Order
from backtrader.research.live import LiveFactorReadiness, LiveFactorSnapshot
from backtrader.research.live_cohort import LiveCohortBatch
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionKey,
    ExecutionDecisionJournalError,
    ExecutionIntentKey,
)
from backtrader.stores.factor_execution_facts import (
    FactorExecutionTarget,
    project_factor_execution_facts,
    refresh_factor_execution_queries,
)

from tests.unit.stores import test_factor_execution as execution_path
from tests.unit.stores import test_factor_execution_facts as facts_path


_UTC = timezone.utc
_SHANGHAI = timezone(timedelta(hours=8))


def _bind_fixture_trading_day(monkeypatch, now):
    """Keep the fake CTP session day aligned with its observed wall clock."""
    trading_day = now.astimezone(_SHANGHAI).strftime("%Y%m%d")
    monkeypatch.setattr(facts_path, "_TRADING_DAY", trading_day)
    quote = facts_path._quote

    def quote_for_trading_day(*, event_time, **kwargs):
        kwargs.setdefault("trading_day", trading_day)
        return quote(event_time=event_time, **kwargs)

    # _quote captured its original module default at import time. Bind every
    # synthetic tick to this run's provider session, including the initial one.
    monkeypatch.setattr(facts_path, "_quote", quote_for_trading_day)
    return trading_day


def _ctp_second(value):
    """Return the CTP TradeTime precision point without inventing subseconds."""
    return value.astimezone(_UTC).replace(microsecond=0)


def _wait_for_wall_time(value):
    """Wait only until a source timestamp is observable on the wall clock."""
    while True:
        remaining = (value - datetime.now(_UTC)).total_seconds()
        if remaining <= 0:
            return
        threading.Event().wait(remaining)


def _live_decision_scope(
    coordinator,
    owner,
    facts,
    *,
    now,
    grid_index,
    intent_keys,
    economics,
):
    close_time = now - timedelta(seconds=6 - grid_index)
    batch_id = "fill-race-batch-{}".format(grid_index)
    batch = LiveCohortBatch(
        batch_id=batch_id,
        cohort_id=execution_path._COHORT,
        calendar_id=execution_path._CALENDAR,
        calendar_version="v1",
        epoch_id=1,
        slot_index=grid_index,
        close_time=close_time,
        available_at=close_time + timedelta(milliseconds=1),
    )
    snapshot = LiveFactorSnapshot(
        plan_id="alpha003-fill-race-test-plan",
        cohort_id=execution_path._COHORT,
        calendar_id=execution_path._CALENDAR,
        calendar_version="v1",
        frequency="1min",
        epoch_id=1,
        batch_id=batch_id,
        close_time=close_time,
        available_at=batch.available_at,
        batch_complete=True,
        readiness=LiveFactorReadiness.LIVE_READY,
        readiness_reasons=(),
        factors={},
    )
    key = ExecutionDecisionKey(
        account_scope=execution_path._ACCOUNT_SCOPE,
        strategy_scope=execution_path._SCOPE,
        logical_run_id="run-1",
        cohort_id=execution_path._COHORT,
        close_time=close_time.isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_GRID",
    )
    return coordinator.decision_scope(
        owner=owner,
        key=key,
        economic_payload={"intent_economics": tuple(economics)},
        intent_keys=tuple(intent_keys),
        batch=batch,
        snapshot=snapshot,
        execution_facts=facts,
        inputs_complete=True,
        expected_run_order_intents_used=coordinator.run_order_count(),
        remaining_exit_intent_reserve=0,
    )


def _open_economics(instrument, exchange, quantity, *, batch_id):
    return {
        "instrument": instrument,
        "exchange": exchange,
        "side": "BUY",
        "position_effect": "OPEN",
        "quantity": str(quantity),
        "limit_price": "100",
        "offset": "open",
        "factor_stop_price": "95",
        "risk_policy_id": "a003-risk-v1",
        "risk_policy": {"stop_loss_ticks": 5, "max_loss_per_position": "200"},
        "entry_grid_ordinal": 1,
        "batch_id": batch_id,
        "price": "100",
    }


_SDK_MD_FRONT = "tcp://182.254.243.31:30012"


def _route_template(cycle, *, md_front="tcp://127.0.0.1:1"):
    return {
        "md_front": md_front,
        "strategy_identity_sha256": "a" * 64,
        "execution_cycle_id": cycle,
        "preflight_sha256": "b" * 64,
    }


def _enable_fake_single_route_switch(api):
    """Model the SDK's exact-capability disarm required before a route switch."""
    client = api.trader_client
    arm = client.arm_execution_for_registered_sim
    active_capability = None

    def arm_with_capability_tracking(**kwargs):
        nonlocal active_capability
        capability, state = arm(**kwargs)
        active_capability = capability
        return capability, state

    def disarm_exact_capability(capability, reason):
        nonlocal active_capability
        if active_capability is None or capability is not active_capability:
            raise AssertionError("registered-sim disarm must match the active SDK capability")
        state = dict(client._gate_state)
        if state.get("armed") is not True:
            raise AssertionError("registered-sim disarm requires one active route")
        state.update(
            {
                "armed": False,
                "instrument": None,
                "authorized_instruments": [],
                "revocation_reason": str(reason),
            }
        )
        client._gate_state = state
        active_capability = None
        return dict(state)

    client.arm_execution_for_registered_sim = arm_with_capability_tracking
    client.disarm_execution_gate = disarm_exact_capability


def _make_trade_row(
    *, trade_id, order_ref, instrument, exchange, when, quantity, price, trading_day, offset="0"
):
    local = when.astimezone(_SHANGHAI)
    return {
        "TradeID": trade_id,
        "OrderRef": str(order_ref),
        "InstrumentID": instrument,
        "ExchangeID": exchange,
        "Direction": "0",
        "OffsetFlag": offset,
        "HedgeFlag": "1",
        "Volume": str(quantity),
        "Price": str(price),
        "TradeDate": local.strftime("%Y%m%d"),
        "TradeTime": local.strftime("%H:%M:%S"),
        "TradingDay": trading_day,
    }


def _emit_trade(api, *, order_ref, trade_id, when, quantity, price, offset="open"):
    source_time = when.astimezone(_SHANGHAI)
    assert source_time.microsecond == 0, "the CTP TradeTime fixture is second-precision"
    api.emit_provider_trade_callback(
        order_ref,
        trade_id=trade_id,
        quantity=quantity,
        offset=offset,
        when=source_time,
    )
    # The emitter is a provider leaf, so set the exact raw and normalized price
    # fields that its callback would have supplied. Leave execution_source
    # absent here; RegisteredSimStore binds the production trade-driven mode.
    update = api._order_updates[-1]
    details = update["details"]
    assert "execution_source" not in update
    assert details["TradeDate"] == source_time.strftime("%Y%m%d")
    assert details["TradeTime"] == source_time.strftime("%H:%M:%S")
    assert details["TradingDay"] == api.trader_client._trading_day
    update["price"] = float(price)
    details["Price"] = str(price)


def _emit_order_status(api, order_ref, *, status, filled, remaining):
    """Queue a normalized order event with native CTP status fields preserved."""
    native_status = {
        "partial": ("1", None),
        "completed": ("0", None),
        "canceled": ("5", None),
        "rejected": ("a", "4"),
    }
    try:
        order_status, submit_status = native_status[status]
    except KeyError:
        raise AssertionError("unmodeled normalized CTP order status") from None

    api.emit_provider_order_callback(
        order_ref,
        status=status,
        filled=filled,
        remaining=remaining,
    )
    update = api._order_updates[-1]
    details = update["details"]
    assert "execution_source" not in update
    details["OrderStatus"] = order_status
    details["TradingDay"] = api.trader_client._trading_day
    if submit_status is not None:
        details["OrderSubmitStatus"] = submit_status


def _single_route_query_rows(
    instrument,
    exchange,
    *,
    positions=(),
    orders=(),
    trades=(),
):
    rows = facts_path._query_rows(positions=positions, orders=orders, trades=trades)
    rows["instruments_result"] = [
        {
            "InstrumentID": instrument,
            "ExchangeID": exchange,
            "IsTrading": 1,
            "VolumeMultiple": 10,
            "PriceTick": 1,
            "LowerLimitPrice": 1,
            "UpperLimitPrice": 1000,
        }
    ]
    rows["instrument_margin_rate_result"] = [
        {
            "InstrumentID": instrument,
            "ExchangeID": exchange,
            "HedgeFlag": "1",
            "LongMarginRatioByMoney": "0.1",
            "LongMarginRatioByVolume": "0",
            "ShortMarginRatioByMoney": "0.1",
            "ShortMarginRatioByVolume": "0",
        }
    ]
    return rows


def _multi_route_query_rows(targets, *, positions=(), orders=(), trades=()):
    rows = facts_path._query_rows(positions=positions, orders=orders, trades=trades)
    rows["instruments_result"] = [
        {
            "InstrumentID": target.instrument,
            "ExchangeID": target.exchange,
            "IsTrading": 1,
            "VolumeMultiple": 10,
            "PriceTick": 1,
            "LowerLimitPrice": 1,
            "UpperLimitPrice": 1000,
        }
        for target in targets
    ]
    rows["instrument_margin_rate_result"] = [
        {
            "InstrumentID": target.instrument,
            "ExchangeID": target.exchange,
            "HedgeFlag": "1",
            "LongMarginRatioByMoney": "0.1",
            "LongMarginRatioByVolume": "0",
            "ShortMarginRatioByMoney": "0.1",
            "ShortMarginRatioByVolume": "0",
        }
        for target in targets
    ]
    return rows


def _refresh_multi_route_facts(api, store, broker, targets, *, query_rows, sequence):
    api.query_rows = query_rows
    api.use_live_query_clock = True
    receipt = refresh_factor_execution_queries(
        store,
        targets=tuple(targets),
        overall_timeout=4.0,
    )
    assert receipt.blockers == ()
    assert receipt.pending_families == ()
    assert receipt.query_set is not None
    for offset, target in enumerate(targets):
        # The query completion is already source evidence. Sample each quote
        # from the current clock after that query, and then project against a
        # later current-clock sample instead of inventing future receive times.
        event_time = max(receipt.query_set.completed_at_utc, datetime.now(_UTC))
        received_at = datetime.now(_UTC)
        api.ticks[target.instrument] = facts_path._quote(
            event_time=event_time,
            received_at=received_at,
            symbol=target.instrument,
            exchange=target.exchange,
            sequence=sequence + offset,
            trading_day=api.trader_client._trading_day,
        )
        assert store.poll_tick(target.instrument) is not None
    now = datetime.now(_UTC)
    facts = project_factor_execution_facts(
        store,
        broker,
        targets=tuple(targets),
        account_scope=execution_path._ACCOUNT_SCOPE,
        strategy_scope=execution_path._SCOPE,
        now=now,
        quote_max_age=timedelta(seconds=2),
        max_query_age=timedelta(seconds=10),
        query_set=receipt.query_set,
    )
    return receipt, facts


def _fresh_facts_with_quote(api, store, broker, target, *, query_rows, sequence):
    api.query_rows = query_rows
    api.use_live_query_clock = True
    receipt = facts_path._refresh_all(store, target)
    event_time = max(receipt.query_set.completed_at_utc, datetime.now(_UTC))
    received_at = datetime.now(_UTC)
    api.tick = facts_path._quote(
        event_time=event_time,
        received_at=received_at,
        symbol=target.instrument,
        exchange=target.exchange,
        sequence=sequence,
        trading_day=api.trader_client._trading_day,
    )
    api.tick.exchange = target.exchange
    api.tick.exchange_id = target.exchange
    assert store.poll_tick(target.instrument) is not None
    now = datetime.now(_UTC)
    facts = facts_path._project(
        store,
        broker,
        target,
        now,
        query_set=receipt.query_set,
    )
    return receipt, facts, now


def _position_book_snapshot(coordinator, target, facts):
    position = next(item for item in facts.positions if item.instrument == target.instrument)
    return coordinator.position_book.snapshot(
        account_scope=execution_path._ACCOUNT_SCOPE,
        strategy_scope=execution_path._SCOPE,
        instrument=target.instrument,
        exchange=target.exchange,
        broker_quantity=position.broker_quantity,
        long_quantity=position.long_quantity,
        short_quantity=position.short_quantity,
        snapshot_id=facts.snapshot_id,
        available_at=facts.available_at,
    )


def _run_engine(cerebro, gate, state):
    try:
        state["result"] = cerebro.run(runonce=False, preload=False)
    except BaseException as error:
        state["error"] = error
        gate.allow_through(1000)


def _new_notification_state():
    return {
        "order_notifications": [],
        "trade_notifications": [],
        "partial_order_seen": threading.Event(),
        "cancel_ack_seen": threading.Event(),
        "cancel_terminal_seen": threading.Event(),
        "close_order_completed": threading.Event(),
        "open_trade_seen": threading.Event(),
        "close_trade_seen": threading.Event(),
    }


def test_actual_cerebro_out_of_order_fills_dedupe_and_same_route_owner_gate(monkeypatch):
    now = datetime.now(_UTC).replace(microsecond=0)
    trading_day = _bind_fixture_trading_day(monkeypatch, now)
    exchange = "DCE"
    gate = execution_path._BarAdvanceGate()
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
    ) = execution_path._system(now=now, bars=3, bar_advance_gate=gate, exchange=exchange)
    api.tick.trading_day = trading_day
    receipt = facts_path._refresh_all(store, target)
    store.registered_sim_configure_arm_templates(
        {(target.instrument, exchange): _route_template("fill-race-open")}
    )
    store.registered_sim_arm(
        instrument=target.instrument,
        exchange=exchange,
        **_route_template("fill-race-open"),
    )
    assert store.poll_tick(target.instrument) is not None
    open_facts = facts_path._project(store, broker, target, now, query_set=receipt.query_set)
    assert open_facts.open_risk_ready is True, open_facts.blockers

    commission = bt.CommInfoBase(
        commission=0.25,
        commtype=bt.CommInfoBase.COMM_FIXED,
        stocklike=False,
    )
    broker.addcommissioninfo(commission, name=target.instrument)
    first_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=target.instrument,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    second_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=target.instrument,
        side="SELL",
        position_effect="OPEN",
        leg=0,
    )
    state = _new_notification_state()
    state.update(
        open_sent=threading.Event(),
        bar1=threading.Event(),
        second_order=None,
        second_error=None,
        order=None,
        submitted_at=None,
    )

    def command(owner, bar_index):
        if bar_index == 0:
            first_economics = _open_economics(
                target.instrument, exchange, 2, batch_id="fill-race-batch-0"
            )
            with _live_decision_scope(
                coordinator,
                owner,
                open_facts,
                now=now,
                grid_index=0,
                intent_keys=(first_key,),
                economics=(first_economics,),
            ):
                state["order"] = owner.buy(
                    data=data,
                    size=2,
                    price=100,
                    exectype=Order.Limit,
                    instrument_id=target.instrument,
                    exchange_id=exchange,
                    factor_position_effect="OPEN",
                    factor_strategy_scope=execution_path._SCOPE,
                    offset="open",
                )
            state["submitted_at"] = datetime.now(_UTC)

            # A fresh eligible grid must still fail closed on the exact route
            # owner while that first Broker order remains active.
            second_economics = _open_economics(
                target.instrument, exchange, 1, batch_id="fill-race-batch-1"
            )
            second_economics["side"] = "SELL"
            try:
                with _live_decision_scope(
                    coordinator,
                    owner,
                    open_facts,
                    now=now,
                    grid_index=1,
                    intent_keys=(second_key,),
                    economics=(second_economics,),
                ):
                    state["second_order"] = owner.sell(
                        data=data,
                        size=1,
                        price=100,
                        exectype=Order.Limit,
                        instrument_id=target.instrument,
                        exchange_id=exchange,
                        factor_position_effect="OPEN",
                        factor_strategy_scope=execution_path._SCOPE,
                        offset="open",
                    )
            except ExecutionDecisionJournalError as error:
                state["second_error"] = error.code

            state["open_sent"].set()
        elif bar_index == 1:
            assert broker.execution_position_snapshot(data).quantity == Decimal("2")
            state["bar1"].set()

    cerebro.addstrategy(
        execution_path._OrchestratedExecutionStrategy,
        command=command,
        notifications=state,
    )
    engine = threading.Thread(
        target=_run_engine, args=(cerebro, gate, state), name="fill-race-engine"
    )
    engine.start()
    try:
        assert state["open_sent"].wait(10), state["error"]
        order = state["order"]
        assert order is not None and order.alive()
        assert len(api.native_calls) == 1
        assert api.native_calls[0] == ("insert", target.instrument, exchange, "501", 101)
        assert state["second_error"] == "INSTRUMENT_OWNER_ACTIVE"

        # Deliver the later execution first, the earlier execution second,
        # followed by a replay of the first provider TradeID.
        first_execution_second = max(
            _ctp_second(state["submitted_at"]), _ctp_second(datetime.now(_UTC))
        )
        early_time = first_execution_second
        late_time = first_execution_second + timedelta(seconds=1)
        _wait_for_wall_time(late_time)
        assert _ctp_second(state["submitted_at"]) <= early_time < late_time
        _emit_trade(
            api,
            order_ref="501",
            trade_id="out-of-order-late",
            when=late_time,
            quantity=1,
            price="102",
        )
        _emit_trade(
            api,
            order_ref="501",
            trade_id="out-of-order-early",
            when=early_time,
            quantity=1,
            price="98",
        )
        _emit_trade(
            api,
            order_ref="501",
            trade_id="out-of-order-late",
            when=late_time,
            quantity=1,
            price="102",
        )
        _emit_order_status(api, "501", status="completed", filled=2, remaining=0)
        gate.allow_through(1)
        assert state["bar1"].wait(10), state["error"]

        trade_late = _make_trade_row(
            trade_id="out-of-order-late",
            order_ref="501",
            instrument=target.instrument,
            exchange=exchange,
            when=late_time,
            quantity=1,
            price="102",
            trading_day=trading_day,
        )
        trade_early = _make_trade_row(
            trade_id="out-of-order-early",
            order_ref="501",
            instrument=target.instrument,
            exchange=exchange,
            when=early_time,
            quantity=1,
            price="98",
            trading_day=trading_day,
        )
        terminal_order = {
            "OrderRef": "501",
            "InstrumentID": target.instrument,
            "ExchangeID": exchange,
            "OrderStatus": "0",
            "Direction": "0",
            "CombOffsetFlag": "0",
            "VolumeTotalOriginal": "2",
            "VolumeTraded": "2",
            "VolumeTotal": "0",
            "FrontID": 4,
            "SessionID": 7,
            "TradingDay": facts_path._TRADING_DAY,
        }
        position = {
            "InstrumentID": target.instrument,
            "ExchangeID": exchange,
            "PosiDirection": "2",
            "Position": "2",
        }
        query_rows = _single_route_query_rows(
            target.instrument,
            exchange,
            positions=(position,),
            orders=(terminal_order,),
            # Query source order is deliberately the opposite chronology.
            trades=(trade_late, trade_early),
        )
        refreshed, facts, _refresh_now = _fresh_facts_with_quote(
            api, store, broker, target, query_rows=query_rows, sequence=2
        )
        first_replay = coordinator.reconcile_trade_observations(facts)
        assert len(first_replay.items) == 2
        assert all(item.status in {"APPLIED", "DUPLICATE"} for item in first_replay.items)
        second_replay = coordinator.reconcile_trade_observations(facts)
        assert len(second_replay.items) == 2
        assert all(item.status == "DUPLICATE" for item in second_replay.items)

        # The durable trade receipts were written after the positions query in
        # ``facts``. Refresh the complete source snapshot before comparing the
        # position book with CTP and the actual Broker projection.
        verified_receipt, facts, _verified_now = _fresh_facts_with_quote(
            api, store, broker, target, query_rows=query_rows, sequence=3
        )
        assert verified_receipt.query_set is not None

        assert order.status == Order.Completed
        assert len(order.executed.exbits) == 2
        assert tuple(float(bit.size) for bit in order.executed.exbits) == (1.0, 1.0)
        assert float(order.executed.size) == pytest.approx(2.0)
        assert float(order.executed.comm) > 0
        assert float(order.executed.comm) == pytest.approx(
            sum(float(bit.comm) for bit in order.executed.exbits)
        )
        assert order.executed.comm == pytest.approx(0.5)
        assert broker.execution_position_snapshot(data).quantity == Decimal("2")

        book = _position_book_snapshot(coordinator, target, facts)
        assert book.status == "MATCHED", book
        assert book.signed_quantity == Decimal("2")
        current = journal._connection.execute(
            """SELECT open_quantity,close_quantity,open_notional
               FROM factor_position_current WHERE account_scope=? AND instrument=?
               AND exchange=?""",
            (execution_path._ACCOUNT_SCOPE, target.instrument, exchange),
        ).fetchone()
        assert current is not None
        assert tuple(current) == ("2", "0", "200")
        fill_count = journal._connection.execute(
            """SELECT COUNT(*) FROM factor_position_fills
               WHERE account_scope=? AND instrument=? AND exchange=?""",
            (execution_path._ACCOUNT_SCOPE, target.instrument, exchange),
        ).fetchone()[0]
        assert fill_count == 2
        assert len(api.native_calls) == 1, "same-route second order must not dispatch"
    finally:
        gate.allow_through(1000)
        engine.join(timeout=10)
    assert not engine.is_alive()
    assert state.get("error") is None
    assert state["result"]


def test_actual_cerebro_cancel_terminal_waits_for_late_trade_id_once(monkeypatch):
    now = datetime.now(_UTC).replace(microsecond=0)
    trading_day = _bind_fixture_trading_day(monkeypatch, now)
    exchange = "DCE"
    gate = execution_path._BarAdvanceGate()
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
        _trader,
        _native,
    ) = execution_path._source_sdk_system(
        monkeypatch, now=now, bars=7, bar_advance_gate=gate, exchange=exchange
    )
    api.tick.trading_day = trading_day
    initial = facts_path._refresh_all(store, target)
    store.registered_sim_configure_arm_templates(
        {
            (target.instrument, exchange): _route_template(
                "late-fill-cancel", md_front=_SDK_MD_FRONT
            )
        }
    )
    store.registered_sim_arm(
        instrument=target.instrument,
        exchange=exchange,
        **_route_template("late-fill-cancel", md_front=_SDK_MD_FRONT),
    )
    assert store.poll_tick(target.instrument) is not None
    open_facts = facts_path._project(store, broker, target, now, query_set=initial.query_set)
    assert open_facts.open_risk_ready is True, open_facts.blockers

    commission = bt.CommInfoBase(
        commission=0.25,
        commtype=bt.CommInfoBase.COMM_FIXED,
        stocklike=False,
    )
    broker.addcommissioninfo(commission, name=target.instrument)
    open_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=target.instrument,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    cancel_key = ExecutionIntentKey(
        action="CANCEL",
        instrument=target.instrument,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    state = _new_notification_state()
    state.update(
        open_sent=threading.Event(),
        partial_bar=threading.Event(),
        cancel_facts=None,
        cancel_sent=threading.Event(),
        cancel_requested_at=None,
        bar3=threading.Event(),
        terminal_report_seen=threading.Event(),
        late_fill_seen=threading.Event(),
        bar6=threading.Event(),
        order=None,
        error=None,
        submitted_at=None,
        late_fill_time=None,
    )
    cancel_economics = {
        "instrument": target.instrument,
        "exchange": exchange,
        "side": "BUY",
        "position_effect": "OPEN",
        "owner_intent_id": None,
        "reason": "cancel remaining quantity after partial fill",
    }

    def command(owner, bar_index):
        if bar_index == 0:
            economics = _open_economics(
                target.instrument, exchange, 3, batch_id="fill-race-batch-0"
            )
            with _live_decision_scope(
                coordinator,
                owner,
                open_facts,
                now=now,
                grid_index=0,
                intent_keys=(open_key,),
                economics=(economics,),
            ):
                state["order"] = owner.buy(
                    data=data,
                    size=3,
                    price=100,
                    exectype=Order.Limit,
                    instrument_id=target.instrument,
                    exchange_id=exchange,
                    factor_position_effect="OPEN",
                    factor_strategy_scope=execution_path._SCOPE,
                    offset="open",
                )
            state["submitted_at"] = datetime.now(_UTC)
            cancel_economics["owner_intent_id"] = state["order"].info["factor_intent_id"]
            state["open_sent"].set()
        elif bar_index == 1:
            assert broker.execution_position_snapshot(data).quantity == Decimal("1")
            state["partial_bar"].set()
        elif bar_index == 2:
            facts = state["cancel_facts"]
            key = ExecutionDecisionKey(
                account_scope=execution_path._ACCOUNT_SCOPE,
                strategy_scope=execution_path._SCOPE,
                logical_run_id="run-1",
                cohort_id=execution_path._COHORT,
                close_time=facts.available_at.isoformat().replace("+00:00", "Z"),
                decision_kind="ALPHA003_RISK_REDUCTION",
            )
            with coordinator.risk_decision_scope(
                owner=owner,
                key=key,
                economic_payload={"intent_economics": (cancel_economics,)},
                intent_keys=(cancel_key,),
                execution_facts=facts,
                inputs_complete=True,
                expected_run_order_intents_used=coordinator.run_order_count(),
                remaining_exit_intent_reserve=1,
            ):
                state["late_fill_time"] = _ctp_second(datetime.now(_UTC))
                owner.cancel(state["order"])
                state["cancel_requested_at"] = datetime.now(_UTC)
            state["cancel_sent"].set()
        elif bar_index == 3:
            assert state["order"].alive()
            assert state["order"].info.get("cancel_acknowledged") is True
            state["bar3"].set()
        elif bar_index == 4:
            order = state["order"]
            assert order.info.get("remote_terminal_status") == "canceled"
            assert order.info.get("remote_terminal_filled") == 2
            assert order.info.get("execution_pending_trades") is True
            state["terminal_report_seen"].set()
        elif bar_index == 5:
            order = state["order"]
            assert order.status == Order.Canceled
            assert float(order.executed.size) == pytest.approx(2.0)
            assert order.info.get("execution_pending_trades") is False
            assert broker.execution_position_snapshot(data).quantity == Decimal("2")
            state["late_fill_seen"].set()
        elif bar_index == 6:
            assert state["order"].status == Order.Canceled
            state["bar6"].set()

    cerebro.addstrategy(
        execution_path._OrchestratedExecutionStrategy,
        command=command,
        notifications=state,
    )
    engine = threading.Thread(
        target=_run_engine, args=(cerebro, gate, state), name="late-fill-engine"
    )
    engine.start()
    try:
        assert state["open_sent"].wait(10), state["error"]
        order = state["order"]
        assert api.native_calls == [("insert", target.instrument, exchange, "501", 101)]

        first_time = _ctp_second(datetime.now(_UTC))
        assert _ctp_second(state["submitted_at"]) <= first_time
        _emit_trade(
            api,
            order_ref="501",
            trade_id="fill-before-cancel-callback-first",
            when=first_time,
            quantity=1,
            price="102",
        )
        _emit_order_status(api, "501", status="partial", filled=1, remaining=2)
        gate.allow_through(1)
        assert state["partial_bar"].wait(10), state["error"]

        partial_trade = _make_trade_row(
            trade_id="fill-before-cancel-callback-first",
            order_ref="501",
            instrument=target.instrument,
            exchange=exchange,
            when=first_time,
            quantity=1,
            price="102",
            trading_day=trading_day,
        )
        active_order = {
            "OrderRef": "501",
            "OrderSysID": "sys-501",
            "InstrumentID": target.instrument,
            "ExchangeID": exchange,
            "OrderStatus": "1",
            "Direction": "0",
            "CombOffsetFlag": "0",
            "VolumeTotalOriginal": "3",
            "VolumeTraded": "1",
            "VolumeTotal": "2",
            "FrontID": 4,
            "SessionID": 7,
            "TradingDay": facts_path._TRADING_DAY,
        }
        one_position = {
            "InstrumentID": target.instrument,
            "ExchangeID": exchange,
            "PosiDirection": "2",
            "Position": "1",
        }
        api.query_rows = _single_route_query_rows(
            target.instrument,
            exchange,
            positions=(one_position,),
            orders=(active_order,),
            trades=(partial_trade,),
        )
        api.use_live_query_clock = True
        callback_created_at_ns = journal._connection.execute(
            "SELECT MAX(created_at_ns) FROM execution_decision_callbacks"
        ).fetchone()[0]
        api.query_completion_floor = datetime.fromtimestamp(
            callback_created_at_ns / 1_000_000_000, _UTC
        ) + timedelta(milliseconds=20)
        _receipt, cancel_facts, _cancel_now = _fresh_facts_with_quote(
            api, store, broker, target, query_rows=api.query_rows, sequence=2
        )
        first_trade_projection = coordinator.reconcile_trade_observations(cancel_facts)
        assert len(first_trade_projection.items) == 1
        assert first_trade_projection.items[0].status in {"APPLIED", "DUPLICATE"}
        # A fill receipt is newer than that positions snapshot. Take a second
        # complete query set before using those facts to authorize cancellation.
        _wait_for_wall_time(first_time + timedelta(seconds=1))
        _receipt, cancel_facts, _cancel_now = _fresh_facts_with_quote(
            api, store, broker, target, query_rows=api.query_rows, sequence=3
        )
        assert cancel_facts.order_cancel_ready is True, cancel_facts.order_cancel_blockers
        assert cancel_facts.positions[0].broker_quantity == Decimal("1")
        state["cancel_facts"] = cancel_facts

        gate.allow_through(2)
        assert state["cancel_sent"].wait(10), state["error"]
        assert api.native_calls[1][:4] == ("cancel", target.instrument, exchange, "501")
        assert api.native_calls[1][4] > api.native_calls[0][4]
        late_time = state["late_fill_time"]
        cancel_requested_at = state["cancel_requested_at"]
        assert (
            late_time is not None
            and cancel_requested_at is not None
            and first_time < late_time < cancel_requested_at
        )
        gate.allow_through(3)
        assert state["bar3"].wait(10), state["error"]

        # The exchange terminal says two units filled and one canceled. The
        # second fill happened before cancellation but its distinct TradeID
        # callback is delayed until after this canceled terminal was consumed.
        _emit_order_status(api, "501", status="canceled", filled=2, remaining=1)
        gate.allow_through(4)
        assert state["terminal_report_seen"].wait(10), state["error"]
        _emit_trade(
            api,
            order_ref="501",
            trade_id="fill-before-cancel-callback-late",
            when=late_time,
            quantity=1,
            price="98",
        )
        gate.allow_through(5)
        assert state["late_fill_seen"].wait(10), state["error"]

        late_trade = _make_trade_row(
            trade_id="fill-before-cancel-callback-late",
            order_ref="501",
            instrument=target.instrument,
            exchange=exchange,
            when=late_time,
            quantity=1,
            price="98",
            trading_day=trading_day,
        )
        canceled_order = {
            **active_order,
            "OrderStatus": "5",
            "VolumeTraded": "2",
            "VolumeTotal": "1",
        }
        two_positions = {**one_position, "Position": "2"}
        final_rows = _single_route_query_rows(
            target.instrument,
            exchange,
            positions=(two_positions,),
            orders=(canceled_order,),
            trades=(late_trade, partial_trade),
        )
        final_receipt, final_facts, _final_now = _fresh_facts_with_quote(
            api, store, broker, target, query_rows=final_rows, sequence=3
        )
        replay = coordinator.reconcile_trade_observations(final_facts)
        assert len(replay.items) == 2
        assert all(item.status in {"APPLIED", "DUPLICATE"} for item in replay.items)
        replay_again = coordinator.reconcile_trade_observations(final_facts)
        assert len(replay_again.items) == 2
        assert all(item.status == "DUPLICATE" for item in replay_again.items)

        # Reconciliation creates durable fill receipts after the source query;
        # only a later complete query set can prove the book/Broker match.
        verified_receipt, final_facts, _verified_now = _fresh_facts_with_quote(
            api, store, broker, target, query_rows=final_rows, sequence=4
        )
        assert verified_receipt.query_set is not None

        assert order.status == Order.Canceled
        assert len(order.executed.exbits) == 2
        assert tuple(float(bit.size) for bit in order.executed.exbits) == (1.0, 1.0)
        assert float(order.executed.size) == pytest.approx(2.0)
        assert order.executed.comm == pytest.approx(0.5)
        assert order.executed.comm == pytest.approx(
            sum(float(bit.comm) for bit in order.executed.exbits)
        )
        assert broker.execution_position_snapshot(data).quantity == Decimal("2")
        book = _position_book_snapshot(coordinator, target, final_facts)
        assert book.status == "MATCHED", book
        assert book.signed_quantity == Decimal("2")
        current = journal._connection.execute(
            """SELECT open_quantity,close_quantity,open_notional
               FROM factor_position_current WHERE account_scope=? AND instrument=?
               AND exchange=?""",
            (execution_path._ACCOUNT_SCOPE, target.instrument, exchange),
        ).fetchone()
        assert current is not None
        assert tuple(current) == ("2", "0", "200")
        assert (
            journal._connection.execute(
                """SELECT COUNT(*) FROM factor_position_fills
               WHERE account_scope=? AND instrument=? AND exchange=?""",
                (execution_path._ACCOUNT_SCOPE, target.instrument, exchange),
            ).fetchone()[0]
            == 2
        )
        assert verified_receipt.query_set is not None
        assert [call[:4] for call in api.native_calls] == [
            ("insert", target.instrument, exchange, "501"),
            ("cancel", target.instrument, exchange, "501"),
        ]
        assert api.native_calls[1][4] > api.native_calls[0][4]

        gate.allow_through(6)
        assert state["bar6"].wait(10), state["error"]
    finally:
        gate.allow_through(1000)
        engine.join(timeout=10)
    assert not engine.is_alive()
    assert state["error"] is None
    assert state["result"]


def test_actual_cerebro_multi_route_success_and_reject_is_non_atomic(monkeypatch):
    now = datetime.now(_UTC).replace(microsecond=0)
    trading_day = _bind_fixture_trading_day(monkeypatch, now)
    exchange = "DCE"
    second_instrument = "cu2612"
    gate = execution_path._BarAdvanceGate()
    initial_rows = _multi_route_query_rows(
        (
            FactorExecutionTarget("rb", execution_path._INSTRUMENT, exchange, object()),
            FactorExecutionTarget("cu", second_instrument, exchange, object()),
        )
    )
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        first,
        first_data,
        _strategy,
        cerebro,
    ) = execution_path._system(
        now=now,
        query_rows=initial_rows,
        bars=3,
        bar_advance_gate=gate,
        exchange=exchange,
    )
    api.tick.trading_day = trading_day
    _enable_fake_single_route_switch(api)

    index = pd.date_range(start=now.replace(tzinfo=None), periods=3, freq="min")
    second_frame = pd.DataFrame(
        {
            "open": [100.0] * 3,
            "high": [101.0] * 3,
            "low": [99.0] * 3,
            "close": [100.0] * 3,
            "volume": [10] * 3,
        },
        index=index,
    )
    second_data = execution_path._GatedPandasData(
        dataname=second_frame,
        name=second_instrument,
        bar_advance_gate=gate,
    )
    cerebro.adddata(second_data)
    second_data.reset()
    second_data._start()
    assert second_data.load() is True
    # Match the exact route identity used by a live feed while retaining the
    # real PandasData line and Cerebro lifecycle for this local composition.
    second_data._dataname = second_instrument
    broker._contract_metadata[second_instrument] = {
        "instrument_id": second_instrument,
        "exchange_id": exchange,
    }
    second = FactorExecutionTarget("cu", second_instrument, exchange, second_data)
    targets = (first, second)

    templates = {
        (target.instrument, target.exchange): _route_template(
            "multi-route-{}".format(target.target_id)
        )
        for target in targets
    }
    store.registered_sim_configure_arm_templates(templates)
    store.registered_sim_arm(
        instrument=first.instrument,
        exchange=first.exchange,
        **templates[(first.instrument, first.exchange)],
    )
    receipt, open_facts = _refresh_multi_route_facts(
        api,
        store,
        broker,
        targets,
        query_rows=initial_rows,
        sequence=1,
    )
    assert open_facts.open_risk_ready is True, open_facts.blockers
    assert len(open_facts.positions) == len(open_facts.route_eligibilities) == 2
    assert receipt.query_set is not None

    broker.addcommissioninfo(
        bt.CommInfoBase(
            commission=0.25,
            commtype=bt.CommInfoBase.COMM_FIXED,
            stocklike=False,
        ),
        name=first.instrument,
    )
    broker.addcommissioninfo(
        bt.CommInfoBase(
            commission=0.25,
            commtype=bt.CommInfoBase.COMM_FIXED,
            stocklike=False,
        ),
        name=second.instrument,
    )
    keys = tuple(
        ExecutionIntentKey(
            action="SUBMIT",
            instrument=target.instrument,
            side="BUY",
            position_effect="OPEN",
            leg=leg,
        )
        for leg, target in enumerate(targets)
    )
    economics = tuple(
        _open_economics(
            target.instrument,
            target.exchange,
            1,
            batch_id="fill-race-batch-0",
        )
        for target in targets
    )
    state = _new_notification_state()
    state.update(
        orders_sent=threading.Event(),
        outcomes_seen=threading.Event(),
        first_order=None,
        second_order=None,
        error=None,
        submitted_at=None,
    )

    def command(owner, bar_index):
        if bar_index == 0:
            with _live_decision_scope(
                coordinator,
                owner,
                open_facts,
                now=now,
                grid_index=0,
                intent_keys=keys,
                economics=economics,
            ):
                state["first_order"] = owner.buy(
                    data=first_data,
                    size=1,
                    price=100,
                    exectype=Order.Limit,
                    instrument_id=first.instrument,
                    exchange_id=exchange,
                    factor_position_effect="OPEN",
                    factor_strategy_scope=execution_path._SCOPE,
                    offset="open",
                )
                # The production actor synchronously switches the one-route
                # SDK grant while preparing this exact second leg, then submits
                # it through the same Broker/Store path as the first.
                state["second_order"] = owner.buy(
                    data=second_data,
                    size=1,
                    price=100,
                    exectype=Order.Limit,
                    instrument_id=second.instrument,
                    exchange_id=exchange,
                    factor_position_effect="OPEN",
                    factor_strategy_scope=execution_path._SCOPE,
                    offset="open",
                )
            state["submitted_at"] = datetime.now(_UTC)
            state["orders_sent"].set()
        elif bar_index == 1:
            assert state["first_order"].status == Order.Completed
            assert state["second_order"].status == Order.Rejected
            assert broker.execution_position_snapshot(first_data).quantity == Decimal("1")
            assert broker.execution_position_snapshot(second_data).quantity == Decimal("0")
            state["outcomes_seen"].set()

    cerebro.addstrategy(
        execution_path._OrchestratedExecutionStrategy,
        command=command,
        notifications=state,
    )
    engine = threading.Thread(
        target=_run_engine, args=(cerebro, gate, state), name="multi-route-fill-engine"
    )
    engine.start()
    try:
        assert state["orders_sent"].wait(10), state["error"]
        first_order = state["first_order"]
        second_order = state["second_order"]
        assert first_order is not None and first_order.alive()
        assert second_order is not None and second_order.alive()
        assert api.native_calls == [
            ("insert", first.instrument, exchange, "501", 101),
            ("insert", second.instrument, exchange, "502", 102),
        ]
        assert [
            (entry["instrument"], entry["exchange"]) for entry in api.registered_sim_arm_history()
        ] == [(first.instrument, exchange), (second.instrument, exchange)]

        # One independent route completes while the provider rejects the
        # other. The already filled exposure is intentionally not rolled back:
        # these ordinary Broker legs are not an atomic multi-asset transaction.
        fill_time = _ctp_second(datetime.now(_UTC))
        assert _ctp_second(state["submitted_at"]) <= fill_time
        _emit_trade(
            api,
            order_ref="501",
            trade_id="multi-route-first-fill",
            when=fill_time,
            quantity=1,
            price="100",
        )
        _emit_order_status(api, "501", status="completed", filled=1, remaining=0)
        _emit_order_status(api, "502", status="rejected", filled=0, remaining=1)
        gate.allow_through(1)
        assert state["outcomes_seen"].wait(10), state["error"]

        first_trade = _make_trade_row(
            trade_id="multi-route-first-fill",
            order_ref="501",
            instrument=first.instrument,
            exchange=exchange,
            when=fill_time,
            quantity=1,
            price="100",
            trading_day=trading_day,
        )
        first_terminal = {
            "OrderRef": "501",
            "InstrumentID": first.instrument,
            "ExchangeID": exchange,
            "OrderStatus": "0",
            "Direction": "0",
            "CombOffsetFlag": "0",
            "VolumeTotalOriginal": "1",
            "VolumeTraded": "1",
            "VolumeTotal": "0",
            "FrontID": 4,
            "SessionID": 7,
            "TradingDay": facts_path._TRADING_DAY,
        }
        rejected_terminal = {
            "OrderRef": "502",
            "InstrumentID": second.instrument,
            "ExchangeID": exchange,
            "OrderStatus": "4",
            "Direction": "0",
            "CombOffsetFlag": "0",
            "VolumeTotalOriginal": "1",
            "VolumeTraded": "0",
            "VolumeTotal": "1",
            "FrontID": 4,
            "SessionID": 7,
            "TradingDay": facts_path._TRADING_DAY,
        }
        first_position = {
            "InstrumentID": first.instrument,
            "ExchangeID": exchange,
            "PosiDirection": "2",
            "Position": "1",
        }
        query_rows = _multi_route_query_rows(
            targets,
            positions=(first_position,),
            orders=(first_terminal, rejected_terminal),
            trades=(first_trade,),
        )
        final_receipt, final_facts = _refresh_multi_route_facts(
            api,
            store,
            broker,
            targets,
            query_rows=query_rows,
            sequence=3,
        )
        first_page = coordinator.reconcile_trade_observations(final_facts)
        assert len(first_page.items) == 1
        assert first_page.items[0].status in {"APPLIED", "DUPLICATE"}
        replay = coordinator.reconcile_trade_observations(final_facts)
        assert len(replay.items) == 1
        assert replay.items[0].status == "DUPLICATE"

        # The fill receipt is newer than this query set. Refresh all target
        # routes atomically before asserting durable attribution matches CTP
        # and the local Broker.
        verified_receipt, verified_facts = _refresh_multi_route_facts(
            api,
            store,
            broker,
            targets,
            query_rows=query_rows,
            sequence=4,
        )
        assert verified_receipt.query_set is not None

        assert first_order.status == Order.Completed
        assert first_order.executed.comm == pytest.approx(0.25)
        assert len(first_order.executed.exbits) == 1
        assert second_order.status == Order.Rejected
        assert second_order.executed.size == 0
        assert broker.execution_position_snapshot(first_data).quantity == Decimal("1")
        assert broker.execution_position_snapshot(second_data).quantity == Decimal("0")
        first_position_book = _position_book_snapshot(coordinator, first, verified_facts)
        assert first_position_book.status == "MATCHED", first_position_book
        assert first_position_book.signed_quantity == Decimal("1")
        fills = journal._connection.execute(
            """SELECT COUNT(*) FROM factor_position_fills
               WHERE account_scope=? AND instrument=? AND exchange=?""",
            (execution_path._ACCOUNT_SCOPE, first.instrument, exchange),
        ).fetchone()[0]
        assert fills == 1
        assert len(api.native_calls) == 2
    finally:
        gate.allow_through(1000)
        engine.join(timeout=10)
    assert not engine.is_alive()
    assert state["error"] is None
    assert state["result"]
