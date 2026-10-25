"""Cross-route cancellation on the ordinary registered-sim execution path.

The accepted fill-race integration module supplies the real Cerebro/Store/
Broker setup and its provider-leaf helpers. This case keeps both orders live
through a route switch, then cancels the original order after the second route
has been submitted.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from decimal import Decimal

import backtrader as bt
import pandas as pd
import pytest
from backtrader.order import Order
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionKey,
    ExecutionIntentKey,
)
from backtrader.stores.factor_execution_facts import FactorExecutionTarget
from tests.integration import test_factor_execution_fill_races as fill_races
from tests.unit.stores import test_factor_execution as execution_path
from tests.unit.stores import test_factor_execution_facts as facts_path


_UTC = fill_races._UTC


class _RouteRecordingExecutionStrategy(execution_path._OrchestratedExecutionStrategy):
    """Capture ordinary notifications with the order/trade route identity."""

    def notify_order(self, order):
        self.p.notifications["routed_order_notifications"].append(
            {
                "status": order.getstatusname(),
                "ref": order.ref,
                "instrument": order.data._name,
                "instrument_id": order.info.get("instrument_id"),
                "exchange_id": order.info.get("exchange_id"),
                "external_order_ref": order.info.get("external_order_ref"),
                "intent_id": order.info.get("factor_intent_id"),
            }
        )
        super().notify_order(order)

    def notify_trade(self, trade):
        self.p.notifications["routed_trade_notifications"].append(
            {
                "instrument": trade.data._name,
                "size": float(trade.size or 0.0),
                "justopened": bool(trade.justopened),
                "isclosed": bool(trade.isclosed),
            }
        )
        super().notify_trade(trade)


def _ctp_order(instrument, exchange, order_ref, *, status, original, filled, remaining):
    return {
        "OrderRef": str(order_ref),
        "InstrumentID": instrument,
        "ExchangeID": exchange,
        "OrderStatus": status,
        "Direction": "0",
        "CombOffsetFlag": "0",
        "VolumeTotalOriginal": str(original),
        "VolumeTraded": str(filled),
        "VolumeTotal": str(remaining),
        "FrontID": 4,
        "SessionID": 7,
        "TradingDay": facts_path._TRADING_DAY,
    }


def test_actual_strategy_cancels_old_order_after_registered_sim_route_switch(monkeypatch):
    now = datetime.now(_UTC).replace(microsecond=0)
    trading_day = fill_races._bind_fixture_trading_day(monkeypatch, now)
    exchange = "DCE"
    second_instrument = "cu2612"
    gate = execution_path._BarAdvanceGate()
    initial_rows = fill_races._multi_route_query_rows(
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
        bars=5,
        bar_advance_gate=gate,
        exchange=exchange,
    )
    api.tick.trading_day = trading_day
    fill_races._enable_fake_single_route_switch(api)

    index = pd.date_range(start=now.replace(tzinfo=None), periods=5, freq="min")
    second_frame = pd.DataFrame(
        {
            "open": [100.0] * 5,
            "high": [101.0] * 5,
            "low": [99.0] * 5,
            "close": [100.0] * 5,
            "volume": [10] * 5,
        },
        index=index,
    )
    second_data = fill_races.execution_path._GatedPandasData(
        dataname=second_frame,
        name=second_instrument,
        bar_advance_gate=gate,
    )
    cerebro.adddata(second_data)
    second_data.reset()
    second_data._start()
    assert second_data.load() is True
    second_data._dataname = second_instrument
    broker._contract_metadata[second_instrument] = {
        "instrument_id": second_instrument,
        "exchange_id": exchange,
    }
    second = FactorExecutionTarget("cu", second_instrument, exchange, second_data)
    targets = (first, second)

    templates = {
        (target.instrument, target.exchange): fill_races._route_template(
            "cross-route-cancel-{}".format(target.target_id)
        )
        for target in targets
    }
    store.registered_sim_configure_arm_templates(templates)
    store.registered_sim_arm(
        instrument=first.instrument,
        exchange=first.exchange,
        **templates[(first.instrument, first.exchange)],
    )
    receipt, open_facts = fill_races._refresh_multi_route_facts(
        api,
        store,
        broker,
        targets,
        query_rows=initial_rows,
        sequence=1,
    )
    assert receipt.query_set is not None
    assert open_facts.open_risk_ready is True, open_facts.blockers
    assert len(open_facts.positions) == len(open_facts.route_eligibilities) == 2

    for target in targets:
        broker.addcommissioninfo(
            bt.CommInfoBase(
                commission=0.25,
                commtype=bt.CommInfoBase.COMM_FIXED,
                stocklike=False,
            ),
            name=target.instrument,
        )

    open_keys = tuple(
        ExecutionIntentKey(
            action="SUBMIT",
            instrument=target.instrument,
            side="BUY",
            position_effect="OPEN",
            leg=leg,
        )
        for leg, target in enumerate(targets)
    )
    open_economics = (
        fill_races._open_economics(first.instrument, exchange, 2, batch_id="fill-race-batch-0"),
        fill_races._open_economics(second.instrument, exchange, 1, batch_id="fill-race-batch-0"),
    )
    state = fill_races._new_notification_state()
    state.update(
        routed_order_notifications=[],
        routed_trade_notifications=[],
        orders_sent=threading.Event(),
        cancel_facts=None,
        cancel_query_completed_at=None,
        cancel_sent=threading.Event(),
        cancel_ack_bar=threading.Event(),
        terminal_bar=threading.Event(),
        late_fill_bar=threading.Event(),
        first_order=None,
        second_order=None,
        submitted_at=None,
        late_fill_time=None,
        cancel_requested_at=None,
        error=None,
    )
    cancel_economics = {
        "instrument": first.instrument,
        "exchange": exchange,
        "side": "BUY",
        "position_effect": "OPEN",
        "owner_intent_id": None,
        "reason": "cancel the original route order after submitting the next route",
    }
    cancel_key = ExecutionIntentKey(
        action="CANCEL",
        instrument=first.instrument,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )

    def command(owner, bar_index):
        if bar_index == 0:
            with fill_races._live_decision_scope(
                coordinator,
                owner,
                open_facts,
                now=now,
                grid_index=0,
                intent_keys=open_keys,
                economics=open_economics,
            ):
                state["first_order"] = owner.buy(
                    data=first_data,
                    size=2,
                    price=100,
                    exectype=Order.Limit,
                    instrument_id=first.instrument,
                    exchange_id=exchange,
                    factor_position_effect="OPEN",
                    factor_strategy_scope=execution_path._SCOPE,
                    offset="open",
                )
                # The second submit switches the single-route SDK grant to B.
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
            # No terminal-order gate is introduced between submitting B and
            # cancelling the still-live A order.
            assert state["first_order"].alive()
            assert state["second_order"].alive()
            facts = state["cancel_facts"]
            assert facts is not None and facts.order_cancel_ready is True
            cancel_economics["owner_intent_id"] = state["first_order"].info["factor_intent_id"]
            key = ExecutionDecisionKey(
                account_scope=execution_path._ACCOUNT_SCOPE,
                strategy_scope=execution_path._SCOPE,
                logical_run_id="run-1",
                cohort_id=execution_path._COHORT,
                close_time=facts.available_at.isoformat().replace("+00:00", "Z"),
                decision_kind="ALPHA003_RISK_REDUCTION",
            )
            query_completed_at = state["cancel_query_completed_at"]
            assert isinstance(query_completed_at, datetime)
            late_fill_time = fill_races._ctp_second(query_completed_at)
            if late_fill_time < query_completed_at:
                late_fill_time += timedelta(seconds=1)
            fill_races._wait_for_wall_time(late_fill_time)
            state["late_fill_time"] = fill_races._ctp_second(datetime.now(_UTC))
            assert state["late_fill_time"] >= query_completed_at
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
                cancel_started_at = datetime.now(_UTC)
                assert (
                    timedelta(0) <= cancel_started_at - query_completed_at <= timedelta(seconds=10)
                )
                assert facts.quotes
                assert all(
                    quote.available_at is not None
                    and timedelta(0)
                    <= cancel_started_at - quote.available_at
                    <= timedelta(seconds=2)
                    for quote in facts.quotes
                )
                owner.cancel(state["first_order"])
            state["cancel_requested_at"] = datetime.now(_UTC)
            state["cancel_sent"].set()
        elif bar_index == 2:
            assert state["first_order"].alive()
            assert state["first_order"].info.get("cancel_acknowledged") is True
            assert state["second_order"].alive()
            state["cancel_ack_bar"].set()
        elif bar_index == 3:
            order = state["first_order"]
            assert order.alive()
            assert order.info.get("remote_terminal_status") == "canceled"
            assert order.info.get("remote_terminal_filled") == 1
            assert order.info.get("execution_pending_trades") is True
            assert state["second_order"].alive()
            state["terminal_bar"].set()
        elif bar_index == 4:
            assert state["first_order"].status == Order.Canceled
            assert float(state["first_order"].executed.size) == pytest.approx(1.0)
            assert len(state["first_order"].executed.exbits) == 1
            assert state["second_order"].alive()
            assert broker.execution_position_snapshot(first_data).quantity == Decimal("1")
            assert broker.execution_position_snapshot(second_data).quantity == Decimal("0")
            state["late_fill_bar"].set()

    cerebro.addstrategy(
        _RouteRecordingExecutionStrategy,
        command=command,
        notifications=state,
    )
    engine = threading.Thread(
        target=fill_races._run_engine,
        args=(cerebro, gate, state),
        name="cross-route-cancel-engine",
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
        active_gate = api.trader_client._gate_state
        assert active_gate["armed"] is True
        assert active_gate["instrument"] == second.instrument

        active_first = _ctp_order(
            first.instrument,
            exchange,
            "501",
            status="3",
            original=2,
            filled=0,
            remaining=2,
        )
        active_second = _ctp_order(
            second.instrument,
            exchange,
            "502",
            status="3",
            original=1,
            filled=0,
            remaining=1,
        )
        active_rows = fill_races._multi_route_query_rows(
            targets,
            orders=(active_first, active_second),
        )
        receipt, cancel_facts = fill_races._refresh_multi_route_facts(
            api,
            store,
            broker,
            targets,
            query_rows=active_rows,
            sequence=2,
        )
        assert receipt.query_set is not None
        state["cancel_query_completed_at"] = receipt.query_set.completed_at_utc
        assert cancel_facts.order_cancel_ready is True, cancel_facts.order_cancel_blockers
        assert {(row.instrument, row.order_ref) for row in cancel_facts.working_orders} == {
            (first.instrument, "501"),
            (second.instrument, "502"),
        }
        state["cancel_facts"] = cancel_facts

        gate.allow_through(1)
        assert state["cancel_sent"].wait(10), state["error"]
        assert api.native_calls == [
            ("insert", first.instrument, exchange, "501", 101),
            ("insert", second.instrument, exchange, "502", 102),
            ("cancel", first.instrument, exchange, "501", 103),
        ]
        assert [
            (entry["instrument"], entry["exchange"]) for entry in api.registered_sim_arm_history()
        ] == [
            (first.instrument, exchange),
            (second.instrument, exchange),
            (first.instrument, exchange),
        ]
        first_owner = journal.active_instrument_owner(
            execution_path._ACCOUNT_SCOPE, first.instrument
        )
        assert first_owner is not None
        assert first_owner.intent_id == first_order.info["factor_intent_id"]
        assert first_owner.cancel_intent_id is not None
        cancel_intent = journal.intent(first_owner.cancel_intent_id)
        assert cancel_intent is not None
        assert cancel_intent.key.action == "CANCEL"
        assert cancel_intent.key.instrument == first.instrument
        assert cancel_intent.owner_intent_id == first_order.info["factor_intent_id"]
        assert cancel_intent.original_identity["backtrader_order_ref"] == first_order.ref

        gate.allow_through(2)
        assert state["cancel_ack_bar"].wait(10), state["error"]
        late_fill_time = state["late_fill_time"]
        cancel_requested_at = state["cancel_requested_at"]
        cancel_query_completed_at = state["cancel_query_completed_at"]
        submitted_at = state["submitted_at"]
        assert late_fill_time is not None and cancel_requested_at is not None
        assert isinstance(cancel_query_completed_at, datetime)
        assert submitted_at is not None
        assert fill_races._ctp_second(submitted_at) <= late_fill_time < cancel_requested_at
        assert cancel_query_completed_at <= late_fill_time

        # The A fill happened before cancel, but its callback arrives after
        # A's cancel terminal and after B was already submitted.
        fill_races._emit_order_status(api, "501", status="canceled", filled=1, remaining=1)
        gate.allow_through(3)
        assert state["terminal_bar"].wait(10), state["error"]
        assert state["second_order"].alive()
        fill_races._emit_trade(
            api,
            order_ref="501",
            trade_id="cross-route-late-fill",
            when=late_fill_time,
            quantity=1,
            price="100",
        )
        gate.allow_through(4)
        assert state["late_fill_bar"].wait(10), state["error"]

        late_trade = fill_races._make_trade_row(
            trade_id="cross-route-late-fill",
            order_ref="501",
            instrument=first.instrument,
            exchange=exchange,
            when=late_fill_time,
            quantity=1,
            price="100",
            trading_day=trading_day,
        )
        terminal_first = _ctp_order(
            first.instrument,
            exchange,
            "501",
            status="5",
            original=2,
            filled=1,
            remaining=1,
        )
        final_rows = fill_races._multi_route_query_rows(
            targets,
            positions=(
                {
                    "InstrumentID": first.instrument,
                    "ExchangeID": exchange,
                    "PosiDirection": "2",
                    "Position": "1",
                },
            ),
            orders=(terminal_first, active_second),
            trades=(late_trade,),
        )
        final_receipt, final_facts = fill_races._refresh_multi_route_facts(
            api,
            store,
            broker,
            targets,
            query_rows=final_rows,
            sequence=3,
        )
        assert final_receipt.query_set is not None
        assert len(final_facts.terminal_orders) == 1
        assert final_facts.terminal_orders[0].instrument == first.instrument
        assert final_facts.terminal_orders[0].exchange == exchange
        assert final_facts.terminal_orders[0].order_ref == "501"
        assert final_facts.terminal_orders[0].terminal_state == "CANCELED"
        assert {(row.instrument, row.order_ref) for row in final_facts.working_orders} == {
            (second.instrument, "502")
        }

        projection = coordinator.reconcile_trade_observations(final_facts)
        assert len(projection.items) == 1
        assert projection.items[0].status in {"APPLIED", "DUPLICATE"}
        verified_receipt, verified_facts = fill_races._refresh_multi_route_facts(
            api,
            store,
            broker,
            targets,
            query_rows=final_rows,
            sequence=4,
        )
        assert verified_receipt.query_set is not None
        assert verified_facts.terminal_orders[0].instrument == first.instrument
        assert {row.order_ref: row.instrument for row in verified_facts.working_orders} == {
            "502": second.instrument
        }
        position_book = fill_races._position_book_snapshot(coordinator, first, verified_facts)
        assert position_book.status == "MATCHED", position_book
        assert position_book.signed_quantity == Decimal("1")

        assert first_order.status == Order.Canceled
        assert len(first_order.executed.exbits) == 1
        assert float(first_order.executed.size) == pytest.approx(1.0)
        assert second_order.alive()
        assert broker.execution_position_snapshot(first_data).quantity == Decimal("1")
        assert broker.execution_position_snapshot(second_data).quantity == Decimal("0")

        order_notices = state["routed_order_notifications"]
        assert any(
            item["instrument"] == first.instrument
            and item["instrument_id"] == first.instrument
            and item["exchange_id"] == exchange
            and item["external_order_ref"] == "501"
            and item["intent_id"] == first_order.info["factor_intent_id"]
            and item["status"] == "Canceled"
            for item in order_notices
        )
        assert not any(
            item["instrument"] == second.instrument and item["status"] == "Canceled"
            for item in order_notices
        )
        trade_notices = state["routed_trade_notifications"]
        assert trade_notices
        assert all(item["instrument"] == first.instrument for item in trade_notices)
        assert any(item["size"] == pytest.approx(1.0) for item in trade_notices)
        assert api.native_calls == [
            ("insert", first.instrument, exchange, "501", 101),
            ("insert", second.instrument, exchange, "502", 102),
            ("cancel", first.instrument, exchange, "501", 103),
        ]
    finally:
        gate.allow_through(1000)
        engine.join(timeout=10)
    assert not engine.is_alive()
    assert state["error"] is None
    assert state["result"]
