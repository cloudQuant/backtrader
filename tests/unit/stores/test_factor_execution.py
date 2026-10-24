"""Ordinary Strategy-to-registered-sim execution route integration tests.

The production Broker, Store and RegisteredSimWrapper remain in the path.  The
fake class below supplies only SDK/provider leaves, including the synchronous
native-call hooks consumed by the real wrapper.
"""

from __future__ import annotations

import threading
import time
from queue import Empty, Queue
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

import backtrader as bt
from backtrader.metabase import OwnerContext
from backtrader.order import Order
from backtrader.research.live import LiveFactorReadiness, LiveFactorSnapshot
from backtrader.research.live_cohort import LiveCohortBatch
from backtrader.stores.execution_decision_journal import (
    ExecutionDecisionJournal,
    ExecutionDecisionKey,
    ExecutionIntentKey,
)
from backtrader.stores.factor_execution import FactorExecutionCoordinator
from backtrader.stores.factor_execution_facts import FactorExecutionTarget
from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper
from tests.unit.stores import test_factor_execution_facts as facts_helpers


_INSTRUMENT = facts_helpers._INSTRUMENT
_EXCHANGE = facts_helpers._EXCHANGE
_SCOPE = "alpha003"
_ACCOUNT_SCOPE = "acct-scope"
_COHORT = "rb-cohort"
_CALENDAR = "simnow-common-minutes-v1"


class _FakeProviderClient(facts_helpers._ProviderLeaves):
    """Provider client base composed under the real RegisteredSimWrapper."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.native_calls = []
        self._native_request_id = 100
        self._next_order_reference = 500
        self.trader_client._front_id = 4
        self.trader_client._session_id = 7
        self.trader_client.next_order_ref = self._reserve_order_ref
        self.trader_client.submit_order_insert = self._native_insert
        self.trader_client.submit_order_action = self._native_cancel
        self._provider_orders = {}
        self._broker_updates = Queue()
        self.use_live_query_clock = False
        self.query_completion_floor = None

    def _query_family(self, family, request_type, **filters):
        if self.use_live_query_clock:
            # Model a provider completion observed during each request. This
            # keeps reconciliation evidence after callback receipt time while
            # remaining no later than the real refresh completion.
            while (
                self.query_completion_floor is not None
                and datetime.now(timezone.utc) < self.query_completion_floor
            ):
                time.sleep(0.002)
            self.query_time = datetime.now(timezone.utc) + timedelta(milliseconds=1)
        return super()._query_family(family, request_type, **filters)

    def get_positions(self):
        """Expose the CTP wrapper's normalized Broker position view."""
        normalized = []
        for row in self.query_rows.get("positions_result", ()):
            quantity = float(row.get("Position", 0) or 0)
            if quantity <= 0:
                continue
            direction = {"2": "long", "3": "short"}.get(str(row.get("PosiDirection", "")), "")
            instrument = row.get("InstrumentID")
            exchange = row.get("ExchangeID")
            normalized.append(
                {
                    "instrument": instrument,
                    "symbol": instrument,
                    "direction": direction,
                    "exchange_id": exchange,
                    "volume": quantity,
                    "size": -quantity if direction == "short" else quantity,
                    "price": 100.0,
                    "avg_price": 100.0,
                }
            )
        return normalized

    def _reserve_order_ref(self):
        self._next_order_reference += 1
        return str(self._next_order_reference)

    def _next_request(self):
        self._native_request_id += 1
        return self._native_request_id

    def _native_insert(self, field, request_id, *, execution_capability):
        assert execution_capability is not None
        self.native_calls.append(
            ("insert", field.InstrumentID, field.ExchangeID, field.OrderRef, request_id)
        )
        return 0

    def _native_cancel(self, field, request_id, *, execution_capability):
        assert execution_capability is not None
        self.native_calls.append(
            ("cancel", field.InstrumentID, field.ExchangeID, field.OrderRef, request_id)
        )
        return 0

    def emit_provider_order_callback(self, order_ref, *, status, filled, remaining):
        """Queue one normalized callback emitted by the fake CTP provider leaf."""
        identity = self._provider_orders[str(order_ref)]
        update = {
            "kind": "order",
            "order_ref": str(order_ref),
            "data_name": identity["instrument_id"],
            "instrument": identity["instrument_id"],
            "exchange_id": identity["exchange_id"],
            "front_id": identity["front_id"],
            "session_id": identity["session_id"],
            "status": status,
            "side": identity["side"],
            "offset": identity["offset"],
            "price": 100.0,
            "size": identity["size"],
            "filled": filled,
            "remaining": remaining,
            "details": {
                "OrderRef": str(order_ref),
                "OrderSysID": identity["order_sys_id"] or "",
                "InstrumentID": identity["instrument_id"],
                "ExchangeID": identity["exchange_id"],
                "FrontID": identity["front_id"],
                "SessionID": identity["session_id"],
                "OrderStatus": status,
                "Direction": "0" if identity["side"] == "buy" else "1",
                "CombOffsetFlag": "0" if identity["offset"] == "open" else "1",
                "LimitPrice": "100",
                "VolumeTotalOriginal": str(identity["size"]),
                "VolumeTraded": str(filled),
                "VolumeTotal": str(remaining),
            },
        }
        self._broker_updates.put(update)

    def emit_provider_trade_callback(
        self,
        order_ref,
        *,
        trade_id,
        quantity,
        offset,
        when,
        omit_trade_date=False,
        trade_date_override=None,
    ):
        """Queue one normalized incremental trade callback from the provider leaf."""
        identity = self._provider_orders[str(order_ref)]
        details = {
            "OrderRef": str(order_ref),
            "OrderSysID": identity["order_sys_id"] or "",
            "TradeID": trade_id,
            "InstrumentID": identity["instrument_id"],
            "ExchangeID": identity["exchange_id"],
            "Direction": "0" if identity["side"] == "buy" else "1",
            "OffsetFlag": "0" if offset == "open" else "1",
            "Volume": str(quantity),
            "Price": "100",
            "TradingDay": facts_helpers._TRADING_DAY,
            "TradeTime": when.strftime("%H:%M:%S"),
        }
        if not omit_trade_date:
            details["TradeDate"] = trade_date_override or when.strftime("%Y%m%d")
        self._broker_updates.put(
            {
                "kind": "trade",
                "trade_id": trade_id,
                "order_ref": str(order_ref),
                "data_name": identity["instrument_id"],
                "instrument": identity["instrument_id"],
                "exchange_id": identity["exchange_id"],
                "side": identity["side"],
                "offset": offset,
                "price": 100.0,
                "size": quantity,
                "timestamp": when.isoformat(),
                "details": details,
            }
        )

    def poll_broker_update(self):
        """Expose queued fake provider callbacks through the normal Store poll."""
        try:
            return self._broker_updates.get_nowait()
        except Empty:
            return None

    def submit_order(self, payload):
        request_id = self._next_request()
        field = SimpleNamespace(
            InstrumentID=payload["instrument_id"],
            ExchangeID=payload["exchange_id"],
            OrderRef=payload["order_ref"],
            RequestID=request_id,
            FrontID=self.trader_client._front_id,
            SessionID=self.trader_client._session_id,
            OrderSysID="",
        )
        self._send_native_order_insert(field, request_id)
        self._provider_orders[field.OrderRef] = {
            "instrument_id": field.InstrumentID,
            "exchange_id": field.ExchangeID,
            "front_id": field.FrontID,
            "session_id": field.SessionID,
            "order_sys_id": None,
            "side": str(payload.get("side") or "buy").lower(),
            "offset": str(payload.get("offset") or "open").lower(),
            "size": int(payload.get("size") or 0),
        }
        return {
            "status": "accepted",
            "id": field.OrderRef,
            "order_ref": field.OrderRef,
            "front_id": field.FrontID,
            "session_id": field.SessionID,
            "exchange_id": field.ExchangeID,
        }

    def cancel_order(self, order_ref, dataname=None):
        del dataname
        identity = self._provider_orders[str(order_ref)]
        request_id = self._next_request()
        field = SimpleNamespace(
            InstrumentID=identity["instrument_id"],
            ExchangeID=identity["exchange_id"],
            OrderRef=str(order_ref),
            OrderSysID=identity["order_sys_id"] or "",
            FrontID=identity["front_id"],
            SessionID=identity["session_id"],
            RequestID=request_id,
        )
        self._send_native_order_action(field, request_id)
        return {
            "status": "accepted",
            "id": field.OrderRef,
            "order_ref": field.OrderRef,
            "front_id": field.FrontID,
            "session_id": field.SessionID,
            "exchange_id": field.ExchangeID,
        }


class _PlainStrategy(bt.Strategy):
    """Minimal direct Strategy subclass with no execution-specific base API."""


class _BarAdvanceGate:
    """Test-only feed gate: pause between bars while provider/query leaves advance."""

    def __init__(self):
        self._condition = threading.Condition()
        self._allowed_through = 0

    def allow_through(self, bar_index):
        with self._condition:
            self._allowed_through = max(self._allowed_through, int(bar_index))
            self._condition.notify_all()

    def wait_for(self, bar_index, timeout=10):
        with self._condition:
            if not self._condition.wait_for(
                lambda: self._allowed_through >= bar_index, timeout=timeout
            ):
                raise AssertionError("test feed did not receive the next bar permit")


class _GatedPandasData(bt.feeds.PandasData):
    params = (("bar_advance_gate", None),)

    def _load(self):
        gate = self.p.bar_advance_gate
        next_index = self._idx + 1
        if gate is not None and next_index < self._df_len and next_index > 0:
            gate.wait_for(next_index)
        return super()._load()


def _system(*, now, query_rows=None, bars=1, bar_advance_gate=None, exchange=_EXCHANGE):
    query_rows = query_rows or facts_helpers._query_rows()
    for family_rows in query_rows.values():
        if not isinstance(family_rows, list):
            continue
        for row in family_rows:
            if row.get("ExchangeID") == _EXCHANGE:
                row["ExchangeID"] = exchange
    tick = facts_helpers._quote(event_time=now - timedelta(milliseconds=200))
    tick.exchange = exchange
    tick.exchange_id = exchange
    store = RegisteredSimStore(
        allow_writes=True,
        api_cls=_FakeProviderClient,
        live_tick_provenance={"source": "fake-ctp-event"},
    )
    # Exercise the Store's production factory: RegisteredSimWrapper is the
    # leading MRO class, while only the external client base is fake.
    api = store._api_cls(
        query_rows=query_rows,
        query_time=now - timedelta(seconds=1),
        tick=tick,
    )
    assert isinstance(api, RegisteredSimWrapper)
    assert _FakeProviderClient in type(api).__mro__
    store._api = api
    store._connected = True
    store.live_tick_provenance = {"source": "fake-ctp-event"}

    data_index = pd.date_range(start=now.replace(tzinfo=None), periods=bars, freq="min")
    data_frame = pd.DataFrame(
        {
            "open": [100.0] * bars,
            "high": [101.0] * bars,
            "low": [99.0] * bars,
            "close": [100.0] * bars,
            "volume": [10] * bars,
        },
        index=data_index,
    )
    data_class = _GatedPandasData if bar_advance_gate is not None else bt.feeds.PandasData
    data_kwargs = {"bar_advance_gate": bar_advance_gate} if bar_advance_gate is not None else {}
    data = data_class(dataname=data_frame, name=_INSTRUMENT, **data_kwargs)
    broker = bt.brokers.BtApiBroker(
        store=store,
        cash=1_000_000,
        validation_enabled=False,
        cash_check_enabled=False,
        contract_metadata={_INSTRUMENT: {"instrument_id": _INSTRUMENT, "exchange_id": exchange}},
    )
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.setbroker(broker)
    cerebro._init_stcount()
    data.reset()
    data._start()
    assert data.load() is True
    with OwnerContext.set_owner(cerebro):
        strategy = _PlainStrategy(data)

    journal = ExecutionDecisionJournal(":memory:")
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        logical_run_id="run-1",
        max_order_intents_per_grid=4,
        max_order_intents_per_run=100,
    )
    target = FactorExecutionTarget("rb", _INSTRUMENT, exchange, data)
    return api, store, broker, journal, coordinator, target, data, strategy, cerebro


def _live_scope(coordinator, strategy, facts, *, now, intent_key, economics):
    close_time = (now - timedelta(seconds=2)).replace(microsecond=0)
    batch_id = "batch-1"
    batch = LiveCohortBatch(
        batch_id=batch_id,
        cohort_id=_COHORT,
        calendar_id=_CALENDAR,
        calendar_version="v1",
        epoch_id=1,
        slot_index=0,
        close_time=close_time,
        available_at=close_time + timedelta(milliseconds=1),
    )
    snapshot = LiveFactorSnapshot(
        plan_id="alpha003-test-plan",
        cohort_id=_COHORT,
        calendar_id=_CALENDAR,
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
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        logical_run_id="run-1",
        cohort_id=_COHORT,
        close_time=close_time.isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_GRID",
    )
    return coordinator.decision_scope(
        owner=strategy,
        key=key,
        economic_payload={"intent_economics": (economics,)},
        intent_keys=(intent_key,),
        batch=batch,
        snapshot=snapshot,
        execution_facts=facts,
        inputs_complete=True,
        expected_run_order_intents_used=coordinator.run_order_count(),
        # This local helper only creates a single-decision fixture. Production
        # Strategy plans pass the actual remaining-exit reserve explicitly.
        remaining_exit_intent_reserve=0,
    )


def test_sourcefake_plain_strategy_buy_manual_fill_component_only():
    """Prove component dispatch/dedupe; the actual engine lifecycle is below."""
    now = datetime.now(timezone.utc)
    # This component-level callback fixture deliberately uses DCE so it does
    # not imply SHFE close-today/yesterday inventory from a net position row.
    exchange = "DCE"
    api, store, broker, journal, coordinator, target, data, strategy, _cerebro = _system(
        now=now, exchange=exchange
    )
    query = facts_helpers._refresh_all(store, target)
    store.registered_sim_configure_arm_templates(
        {
            (_INSTRUMENT, exchange): {
                "md_front": "tcp://127.0.0.1:1",
                "strategy_identity_sha256": "a" * 64,
                "execution_cycle_id": "cycle-1",
                "preflight_sha256": "b" * 64,
            }
        }
    )
    store.registered_sim_arm(
        instrument=_INSTRUMENT,
        exchange=exchange,
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256="a" * 64,
        execution_cycle_id="cycle-1",
        preflight_sha256="b" * 64,
    )
    consumed = facts_helpers._consume_quote(store)
    facts = facts_helpers._project(store, broker, target, now, query_set=query.query_set)
    assert consumed is not None
    assert facts.open_risk_ready is True, facts.blockers

    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=_INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    economics = {
        "instrument": _INSTRUMENT,
        "exchange": exchange,
        "side": "BUY",
        "position_effect": "OPEN",
        "quantity": "2",
        "limit_price": "100",
        "factor_stop_price": "95",
        "risk_policy_id": "a003-risk-v1",
        "risk_policy": {"stop_loss_ticks": 5, "max_loss_per_position": "25"},
        "entry_grid_ordinal": 1,
        "batch_id": "batch-1",
        "price": "100",
    }
    with _live_scope(
        coordinator,
        strategy,
        facts,
        now=now,
        intent_key=intent_key,
        economics=economics,
    ) as decision:
        order = strategy.buy(
            data=data,
            size=2,
            price=100,
            exectype=Order.Limit,
            instrument_id=_INSTRUMENT,
            exchange_id=exchange,
            factor_position_effect="OPEN",
            factor_strategy_scope=_SCOPE,
            offset="open",
        )

    assert decision.decision_id is not None
    assert decision.is_new_grid is True
    assert order is not None and order.alive()
    assert order.getstatusname() == "Accepted"
    assert order.info["factor_dispatch_state"] == "KNOWN"
    assert order.info["factor_intent_id"]
    assert order.info["external_order_ref"] == "501"
    assert order.info["order_ref"] == "501"
    assert order.info["front_id"] == 4
    assert order.info["session_id"] == 7
    assert api.native_calls == [("insert", _INSTRUMENT, exchange, "501", 101)]
    assert len(store.registered_sim_dispatch_history()) == 1
    assert journal.intent(order.info["factor_intent_id"]).state == "KNOWN"
    assert broker.execution_order_snapshot()[0].external_order_ref == "501"

    trade_time = now.astimezone(timezone(timedelta(hours=8))) - timedelta(seconds=2)
    callback = {
        "bt_order_ref": order.ref,
        "order_ref": "501",
        "instrument": _INSTRUMENT,
        "exchange_id": exchange,
        "trade_id": "trade-501-1",
        "size": 1,
        "price": 100.0,
        "details": {
            "bt_order_ref": order.ref,
            "OrderRef": "501",
            "TradeID": "trade-501-1",
            "InstrumentID": _INSTRUMENT,
            "ExchangeID": exchange,
            "Direction": "0",
            "OffsetFlag": "0",
            "Volume": "1",
            "Price": "100",
            "TradeDate": trade_time.strftime("%Y%m%d"),
            "TradeTime": trade_time.strftime("%H:%M:%S"),
        },
    }
    assert broker._apply_trade_update(callback) == "applied"
    assert broker.getposition(data).size == pytest.approx(1)
    receipt_count = len(journal.pending_callbacks(limit=10))
    assert receipt_count == 0
    assert broker._apply_trade_update(callback) == "ignored"
    assert broker.getposition(data).size == pytest.approx(1)
    assert journal.pending_callbacks(limit=10) == ()

    # The runner refreshes complete source rows outside Strategy, projects the
    # exact local/remote partial order join, and consumes the query trade as an
    # idempotent recovery observation before authorizing a normal cancel call.
    # Keep the refreshed source snapshot strictly after the already durable
    # callback receipt's journal timestamp, using the injected facts clock.
    trade_row = {
        "TradeID": "trade-501-1",
        "OrderRef": "501",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": exchange,
        "Direction": "0",
        "OffsetFlag": "0",
        "Volume": "1",
        "Price": "100",
        "TradeDate": trade_time.strftime("%Y%m%d"),
        "TradeTime": trade_time.strftime("%H:%M:%S"),
    }
    active_order_row = {
        "OrderRef": "501",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": exchange,
        "OrderStatus": "1",
        "Direction": "0",
        "CombOffsetFlag": "0",
        "VolumeTotalOriginal": "2",
        "VolumeTraded": "1",
        "VolumeTotal": "1",
        "FrontID": 4,
        "SessionID": 7,
    }
    position_row = {
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": exchange,
        "PosiDirection": "2",
        "Position": "1",
    }
    query_rows = facts_helpers._query_rows(
        positions=(position_row,),
        orders=(active_order_row,),
        trades=(trade_row,),
    )
    for family_rows in query_rows.values():
        if isinstance(family_rows, list):
            for row in family_rows:
                if row.get("ExchangeID") == _EXCHANGE:
                    row["ExchangeID"] = exchange
    api.query_rows = query_rows
    callback_created_at_ns = journal._connection.execute(
        "SELECT MAX(created_at_ns) FROM execution_decision_callbacks"
    ).fetchone()[0]
    api.query_completion_floor = datetime.fromtimestamp(
        callback_created_at_ns / 1_000_000_000, timezone.utc
    ) + timedelta(milliseconds=20)
    api.use_live_query_clock = True
    refreshed = facts_helpers._refresh_all(store, target)
    refresh_now = datetime.now(timezone.utc) + timedelta(milliseconds=2)
    reconciled = coordinator.reconcile_trade_observations(
        facts_helpers._project(store, broker, target, refresh_now, query_set=refreshed.query_set)
    )
    assert len(reconciled.items) == 1
    assert reconciled.items[0].status in {"APPLIED", "DUPLICATE"}
    stale_facts = facts_helpers._project(
        store, broker, target, refresh_now, query_set=refreshed.query_set
    )
    assert stale_facts.order_cancel_ready is False
    assert "POSITION_CALLBACK_AFTER_SNAPSHOT" in stale_facts.order_cancel_blockers

    # The query observation itself becomes a durable fill receipt after its
    # snapshot was taken. A second complete query set is needed to establish
    # that the position snapshot includes that receipt.
    refreshed = facts_helpers._refresh_all(store, target)
    refresh_now = datetime.now(timezone.utc) + timedelta(milliseconds=2)
    replayed = coordinator.reconcile_trade_observations(
        facts_helpers._project(store, broker, target, refresh_now, query_set=refreshed.query_set)
    )
    assert replayed.items[0].status == "DUPLICATE"
    cancel_facts = facts_helpers._project(
        store, broker, target, refresh_now, query_set=refreshed.query_set
    )
    assert cancel_facts.order_cancel_ready is True, cancel_facts.order_cancel_blockers
    assert len(cancel_facts.working_orders) == 1
    working = cancel_facts.working_orders[0]
    assert working.order_ref == "501"
    assert working.remaining_quantity == Decimal("1")
    assert working.owner_strategy_scope == _SCOPE
    assert working.owner_intent_id == order.info["factor_intent_id"]

    cancel_key = ExecutionDecisionKey(
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        logical_run_id="run-1",
        cohort_id=_COHORT,
        close_time=cancel_facts.available_at.isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_RISK_REDUCTION",
    )
    cancel_intent_key = ExecutionIntentKey(
        action="CANCEL",
        instrument=_INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    cancel_economics = {
        "instrument": _INSTRUMENT,
        "exchange": exchange,
        "side": "BUY",
        "position_effect": "OPEN",
        "owner_intent_id": order.info["factor_intent_id"],
        "reason": "source-fake partial-order cancel",
    }
    with coordinator.risk_decision_scope(
        owner=strategy,
        key=cancel_key,
        economic_payload={"intent_economics": (cancel_economics,)},
        intent_keys=(cancel_intent_key,),
        batch=None,
        execution_facts=cancel_facts,
        inputs_complete=True,
        expected_run_order_intents_used=coordinator.run_order_count(),
        remaining_exit_intent_reserve=0,
    ) as cancel_decision:
        strategy.cancel(order)

    assert cancel_decision.decision_id is not None
    assert len(api.native_calls) == 2
    assert api.native_calls[1] == ("cancel", _INSTRUMENT, exchange, "501", 102)
    assert order.alive()
    assert order.info["cancel_requested_remote"] is True


class _EngineBuyStrategy(bt.Strategy):
    params = (("command", None),)

    def next(self):
        self.p.command(self)


class _OrchestratedExecutionStrategy(bt.Strategy):
    params = (("command", None), ("notifications", None))

    def __init__(self):
        self._bar_index = 0

    def next(self):
        # The engine thread never waits for the test driver.  Provider/query
        # work is coordinated between bars by _BarAdvanceGate instead.
        self.p.command(self, self._bar_index)
        self._bar_index += 1

    def notify_order(self, order):
        if self.p.notifications is not None:
            self.p.notifications["order_notifications"].append(
                (
                    order.getstatusname(),
                    float(order.executed.size or 0.0),
                    bool(order.info.get("cancel_acknowledged", False)),
                )
            )
            if order.getstatusname() == "Partial" and float(order.executed.size or 0.0) == 1.0:
                self.p.notifications["partial_order_seen"].set()
            if order.info.get("cancel_acknowledged", False):
                self.p.notifications["cancel_ack_seen"].set()
            if order.getstatusname() == "Canceled":
                self.p.notifications["cancel_terminal_seen"].set()
            if order.getstatusname() == "Completed":
                self.p.notifications["close_order_completed"].set()

    def notify_trade(self, trade):
        if self.p.notifications is not None:
            self.p.notifications["trade_notifications"].append(
                (bool(trade.justopened), bool(trade.isclosed), float(trade.size or 0.0))
            )
            if trade.justopened and not trade.isclosed:
                self.p.notifications["open_trade_seen"].set()
            if trade.isclosed:
                self.p.notifications["close_trade_seen"].set()


def test_ordinary_buy_is_dispatched_from_actual_cerebro_next():
    now = datetime.now(timezone.utc)
    api, store, broker, journal, coordinator, target, data, _strategy, cerebro = _system(now=now)
    query = facts_helpers._refresh_all(store, target)
    facts_helpers._arm(store)
    assert facts_helpers._consume_quote(store) is not None
    facts = facts_helpers._project(store, broker, target, now, query_set=query.query_set)
    assert facts.open_risk_ready is True, facts.blockers

    intent_key = ExecutionIntentKey(
        action="SUBMIT",
        instrument=_INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    economics = {
        "instrument": _INSTRUMENT,
        "exchange": _EXCHANGE,
        "side": "BUY",
        "position_effect": "OPEN",
        "quantity": "1",
        "limit_price": "100",
        "factor_stop_price": "95",
        "risk_policy_id": "a003-risk-v1",
        "risk_policy": {"stop_loss_ticks": 5, "max_loss_per_position": "25"},
        "entry_grid_ordinal": 1,
        "batch_id": "batch-1",
        "price": "100",
    }
    state = {"order": None, "decision_id": None, "calls": 0}

    def command(owner):
        state["calls"] += 1
        with _live_scope(
            coordinator,
            owner,
            facts,
            now=now,
            intent_key=intent_key,
            economics=economics,
        ) as decision:
            state["order"] = owner.buy(
                data=owner.data0,
                size=1,
                price=100,
                exectype=Order.Limit,
                instrument_id=_INSTRUMENT,
                exchange_id=_EXCHANGE,
                factor_position_effect="OPEN",
                factor_strategy_scope=_SCOPE,
                offset="open",
            )
        state["decision_id"] = decision.decision_id

    cerebro.addstrategy(_EngineBuyStrategy, command=command)
    result = cerebro.run(runonce=False, preload=False)

    assert len(result) == 1
    assert state["calls"] == 1
    order = state["order"]
    assert order is not None and order.alive()
    assert order.info["factor_dispatch_state"] == "KNOWN"
    assert order.info["external_order_ref"] == "501"
    assert api.native_calls == [("insert", _INSTRUMENT, _EXCHANGE, "501", 101)]
    assert journal.intent(order.info["factor_intent_id"]).state == "KNOWN"
    assert state["decision_id"] is not None


def test_actual_cerebro_open_cancel_terminal_and_risk_close_chain():
    now = datetime.now(timezone.utc)
    exchange = "DCE"

    def route_query_rows(**kwargs):
        rows = facts_helpers._query_rows(**kwargs)
        for family_rows in rows.values():
            if not isinstance(family_rows, list):
                continue
            for row in family_rows:
                if row.get("InstrumentID") == _INSTRUMENT:
                    row["InstrumentID"] = _INSTRUMENT
                if row.get("ExchangeID") == _EXCHANGE:
                    row["ExchangeID"] = exchange
        return rows

    gate = _BarAdvanceGate()
    api, store, broker, journal, coordinator, target, data, _strategy, cerebro = _system(
        now=now, bars=7, bar_advance_gate=gate, exchange=exchange
    )
    initial = facts_helpers._refresh_all(store, target)
    store.registered_sim_configure_arm_templates(
        {
            (_INSTRUMENT, exchange): {
                "md_front": "tcp://127.0.0.1:1",
                "strategy_identity_sha256": "a" * 64,
                "execution_cycle_id": "cycle-1",
                "preflight_sha256": "b" * 64,
            }
        }
    )
    store.registered_sim_arm(
        instrument=_INSTRUMENT,
        exchange=exchange,
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256="a" * 64,
        execution_cycle_id="cycle-1",
        preflight_sha256="b" * 64,
    )
    assert facts_helpers._consume_quote(store) is not None
    open_facts = facts_helpers._project(store, broker, target, now, query_set=initial.query_set)
    assert open_facts.open_risk_ready is True, open_facts.blockers

    open_intent = ExecutionIntentKey(
        action="SUBMIT",
        instrument=_INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    open_economics = {
        "instrument": _INSTRUMENT,
        "exchange": exchange,
        "side": "BUY",
        "position_effect": "OPEN",
        "quantity": "2",
        "limit_price": "100",
        "offset": "open",
        "factor_stop_price": "95",
        "risk_policy_id": "a003-risk-v1",
        "risk_policy": {"stop_loss_ticks": 5, "max_loss_per_position": "200"},
        "entry_grid_ordinal": 1,
        "batch_id": "batch-1",
        "price": "100",
    }
    state = {
        "open_sent": threading.Event(),
        "partial_order_seen": threading.Event(),
        "open_trade_seen": threading.Event(),
        "cancel_sent": threading.Event(),
        "cancel_ack_seen": threading.Event(),
        "cancel_terminal_seen": threading.Event(),
        "close_order_completed": threading.Event(),
        "close_trade_seen": threading.Event(),
        "bar1": threading.Event(),
        "bar3": threading.Event(),
        "bar4": threading.Event(),
        "bar6": threading.Event(),
        "close_sent": threading.Event(),
        "order": None,
        "close_order": None,
        "close_facts": None,
        "order_notifications": [],
        "trade_notifications": [],
        "error": None,
    }

    cancel_intent = ExecutionIntentKey(
        action="CANCEL",
        instrument=_INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    close_intent = ExecutionIntentKey(
        action="SUBMIT",
        instrument=_INSTRUMENT,
        side="SELL",
        position_effect="CLOSE",
        leg=0,
    )
    cancel_economics = {
        "instrument": _INSTRUMENT,
        "exchange": exchange,
        "side": "BUY",
        "position_effect": "OPEN",
        "owner_intent_id": "pending-opening-owner",
        "reason": "integration cancel before close",
    }
    close_economics = {
        "instrument": _INSTRUMENT,
        "exchange": exchange,
        "side": "SELL",
        "position_effect": "CLOSE",
        "quantity": "1",
        "limit_price": "100",
        "offset": "close",
        "owner_intent_id": "pending-opening-owner",
        "owner_position_effect": "OPEN",
        "owner_side": "BUY",
        "entry_grid_ordinal": 1,
    }

    def command(owner, bar_index):
        if bar_index == 0:
            with _live_scope(
                coordinator,
                owner,
                open_facts,
                now=now,
                intent_key=open_intent,
                economics=open_economics,
            ):
                state["order"] = owner.buy(
                    data=owner.data0,
                    size=2,
                    price=100,
                    exectype=Order.Limit,
                    instrument_id=_INSTRUMENT,
                    exchange_id=exchange,
                    factor_position_effect="OPEN",
                    factor_strategy_scope=_SCOPE,
                    offset="open",
                )
            cancel_economics["owner_intent_id"] = state["order"].info["factor_intent_id"]
            close_economics["owner_intent_id"] = state["order"].info["factor_intent_id"]
            state["open_sent"].set()
        elif bar_index == 1:
            order = state["order"]
            assert order is not None and order.alive()
            assert broker.execution_position_snapshot(data).quantity == Decimal("1")
            state["bar1"].set()
        elif bar_index == 2:
            order = state["order"]
            facts = state["cancel_facts"]
            key = ExecutionDecisionKey(
                account_scope=_ACCOUNT_SCOPE,
                strategy_scope=_SCOPE,
                logical_run_id="run-1",
                cohort_id=_COHORT,
                close_time=facts.available_at.isoformat().replace("+00:00", "Z"),
                decision_kind="ALPHA003_RISK_REDUCTION",
            )
            with coordinator.risk_decision_scope(
                owner=owner,
                key=key,
                economic_payload={"intent_economics": (cancel_economics,)},
                intent_keys=(cancel_intent,),
                execution_facts=facts,
                inputs_complete=True,
                expected_run_order_intents_used=coordinator.run_order_count(),
                remaining_exit_intent_reserve=1,
            ):
                owner.cancel(order)
                state["cancel_sent"].set()
        elif bar_index == 3:
            order = state["order"]
            assert order.alive(), "cancel ACK is not a terminal order update"
            assert order.info["cancel_acknowledged"] is True
            state["bar3"].set()
        elif bar_index == 4:
            order = state["order"]
            assert order.status == Order.Canceled
            assert order.alive() is False
            state["bar4"].set()
        elif bar_index == 5:
            facts = state["close_facts"]
            key = ExecutionDecisionKey(
                account_scope=_ACCOUNT_SCOPE,
                strategy_scope=_SCOPE,
                logical_run_id="run-1",
                cohort_id=_COHORT,
                close_time=facts.available_at.isoformat().replace("+00:00", "Z"),
                decision_kind="ALPHA003_RISK_REDUCTION",
            )
            with coordinator.risk_decision_scope(
                owner=owner,
                key=key,
                economic_payload={"intent_economics": (close_economics,)},
                intent_keys=(close_intent,),
                execution_facts=facts,
                inputs_complete=True,
                expected_run_order_intents_used=coordinator.run_order_count(),
                remaining_exit_intent_reserve=0,
            ):
                state["close_order"] = owner.sell(
                    data=owner.data0,
                    size=1,
                    price=100,
                    exectype=Order.Limit,
                    instrument_id=_INSTRUMENT,
                    exchange_id=exchange,
                    factor_position_effect="CLOSE",
                    factor_strategy_scope=_SCOPE,
                    factor_owner_side="BUY",
                    factor_owner_position_effect="OPEN",
                    offset="close",
                )
            state["close_sent"].set()
        elif bar_index == 6:
            assert state["close_order"].status == Order.Completed
            assert broker.execution_position_snapshot(data).quantity == Decimal("0")
            state["bar6"].set()

    def run_engine():
        try:
            state["result"] = cerebro.run(runonce=False, preload=False)
        except BaseException as error:
            state["error"] = error
            for key in state:
                if key.startswith("bar") or key.endswith(("_sent", "_seen")):
                    value = state[key]
                    if isinstance(value, threading.Event):
                        value.set()

    cerebro.addstrategy(_OrchestratedExecutionStrategy, command=command, notifications=state)
    engine_thread = threading.Thread(target=run_engine, name="factor-engine-test")
    engine_thread.start()

    assert state["open_sent"].wait(10), state["error"]
    order = state["order"]
    assert order is not None and order.alive()
    assert api.native_calls == [("insert", _INSTRUMENT, exchange, "501", 101)]

    # Normal fake provider callbacks are enqueued on the composed API and are
    # drained by the ordinary Store.poll_broker_update -> Broker.next path.
    # The trade is delivered before its cumulative partial order snapshot so
    # the trade remains the Broker's actual fill authority.
    trade_time = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
    api.emit_provider_trade_callback(
        "501",
        trade_id="trade-chain-open-1",
        quantity=1,
        offset="open",
        when=trade_time,
        omit_trade_date=True,
    )
    api.emit_provider_trade_callback(
        "501",
        trade_id="trade-chain-open-1",
        quantity=1,
        offset="open",
        when=trade_time,
        omit_trade_date=True,
    )
    api.emit_provider_order_callback("501", status="partial", filled=1, remaining=1)

    trade_row = {
        "TradeID": "trade-chain-open-1",
        "OrderRef": "501",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": exchange,
        "Direction": "0",
        "OffsetFlag": "0",
        "Volume": "1",
        "Price": "100",
        "TradeDate": trade_time.strftime("%Y%m%d"),
        "TradeTime": trade_time.strftime("%H:%M:%S"),
    }
    active_order = {
        "OrderRef": "501",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": exchange,
        "OrderStatus": "1",
        "Direction": "0",
        "CombOffsetFlag": "0",
        "VolumeTotalOriginal": "2",
        "VolumeTraded": "1",
        "VolumeTotal": "1",
        "FrontID": 4,
        "SessionID": 7,
    }
    position_row = {
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": exchange,
        "PosiDirection": "2",
        "Position": "1",
    }
    api.query_rows = route_query_rows(
        positions=(position_row,), orders=(active_order,), trades=(trade_row,)
    )
    gate.allow_through(1)
    assert state["bar1"].wait(10), state["error"]
    assert state["partial_order_seen"].wait(10), state["error"]
    assert state["open_trade_seen"].wait(10), state["error"]
    assert broker.execution_position_snapshot(data).quantity == Decimal("1")
    assert float(order.executed.size) == pytest.approx(1.0)

    # The native callbacks intentionally omit TradeDate. They update the
    # ordinary Broker once, while the raw receipts remain unprojected until a
    # complete source query binds them to a dated trade identity.
    api.use_live_query_clock = True
    callback_created_at_ns = journal._connection.execute(
        "SELECT MAX(created_at_ns) FROM execution_decision_callbacks"
    ).fetchone()[0]
    api.query_completion_floor = datetime.fromtimestamp(
        callback_created_at_ns / 1_000_000_000, timezone.utc
    ) + timedelta(milliseconds=20)
    refreshed = facts_helpers._refresh_all(store, target)
    query_projection = facts_helpers._project(
        store,
        broker,
        target,
        datetime.now(timezone.utc) + timedelta(milliseconds=2),
        query_set=refreshed.query_set,
    )
    replay = coordinator.reconcile_trade_observations(query_projection)
    assert len(replay.items) == 1
    assert replay.items[0].status == "APPLIED"
    raw_callback = journal._connection.execute(
        """SELECT evidence_payload_json, acknowledged
           FROM execution_decision_callbacks
           WHERE intent_id=? AND evidence_payload_json LIKE '%unresolved_trade_callback%'""",
        (order.info["factor_intent_id"],),
    ).fetchone()
    assert raw_callback is not None and raw_callback[1] == 1
    assert '"trade_date":null' in raw_callback[0]
    assert '"execution_id"' not in raw_callback[0]
    # Reconciliation persists the complete-query observation after that query
    # set's position snapshot. A subsequent complete query set proves the
    # durable fill receipt is no newer than the authoritative position row.
    refreshed = facts_helpers._refresh_all(store, target)
    query_projection = facts_helpers._project(
        store,
        broker,
        target,
        datetime.now(timezone.utc) + timedelta(milliseconds=2),
        query_set=refreshed.query_set,
    )
    replay = coordinator.reconcile_trade_observations(query_projection)
    assert len(replay.items) == 1
    assert replay.items[0].status == "DUPLICATE"
    cancel_facts = facts_helpers._project(
        store,
        broker,
        target,
        datetime.now(timezone.utc) + timedelta(milliseconds=2),
        query_set=refreshed.query_set,
    )
    last_callback_at_ns = journal._connection.execute(
        "SELECT last_callback_at_ns FROM factor_position_current WHERE instrument=?",
        (_INSTRUMENT,),
    ).fetchone()[0]
    assert cancel_facts.order_cancel_ready is True, (
        cancel_facts.order_cancel_blockers,
        cancel_facts.positions,
        callback_created_at_ns,
        datetime.fromtimestamp(callback_created_at_ns / 1_000_000_000, timezone.utc),
        last_callback_at_ns,
        datetime.fromtimestamp(last_callback_at_ns / 1_000_000_000, timezone.utc),
        refreshed.query_set.completed_at_utc,
    )
    assert cancel_facts.positions[0].broker_quantity == Decimal("1")
    assert cancel_facts.positions[0].quantity == Decimal("1")
    state["cancel_facts"] = cancel_facts
    gate.allow_through(2)
    assert state["cancel_sent"].wait(10), state["error"]
    assert order.alive(), "native cancel ACK must not be treated as terminal"
    assert order.info["factor_cancel_dispatch_state"] == "KNOWN"
    assert api.native_calls[1] == ("cancel", _INSTRUMENT, exchange, "501", 102)

    # Let a broker cycle run with no terminal provider callback.  The ordinary
    # order remains alive after the native cancel acknowledgement.
    gate.allow_through(3)
    assert state["bar3"].wait(10), state["error"]
    assert state["cancel_ack_seen"].is_set()
    assert order.alive()
    assert order.info["cancel_acknowledged"] is True

    # A separate provider terminal event, not the cancel ACK, completes the
    # cancellation on the next Broker.next polling cycle.
    api.emit_provider_order_callback("501", status="canceled", filled=1, remaining=1)
    terminal_order = dict(active_order, OrderStatus="5")
    api.query_rows = route_query_rows(
        positions=(position_row,), orders=(terminal_order,), trades=(trade_row,)
    )
    gate.allow_through(4)
    assert state["bar4"].wait(10), state["error"]
    assert state["cancel_terminal_seen"].is_set()
    assert order.status == Order.Canceled

    refreshed = facts_helpers._refresh_all(store, target)
    quote_event_time = refreshed.query_set.completed_at_utc + timedelta(milliseconds=5)
    quote_received = quote_event_time + timedelta(milliseconds=1)
    api.tick = facts_helpers._quote(
        event_time=quote_event_time, received_at=quote_received, sequence=2
    )
    api.tick.exchange = exchange
    api.tick.exchange_id = exchange
    assert facts_helpers._consume_quote(store) is not None
    refresh_now = quote_received + timedelta(milliseconds=1)
    terminal_facts = facts_helpers._project(
        store, broker, target, refresh_now, query_set=refreshed.query_set
    )
    terminal = coordinator.reconcile_terminal_order_observations(terminal_facts)
    assert len(terminal.items) == 1
    assert terminal.items[0].status == "RESOLVED", terminal.items[0]
    opening_resolution = journal.instrument_resolution(order.info["factor_intent_id"])
    assert opening_resolution is not None
    assert opening_resolution.position_flat is False
    opening_reconciliation_id = terminal.items[0].reconciliation_id
    assert opening_reconciliation_id == opening_resolution.reconciliation_id
    terminal_proof = coordinator.terminal_order_reconciliation_snapshot(terminal_facts)
    assert terminal_proof.truncated is False
    assert terminal_proof.items[0].status == "RESOLVED"
    trade_proof = coordinator.trade_reconciliation_snapshot(terminal_facts)
    assert trade_proof.truncated is False
    assert trade_proof.items[0].status in {"APPLIED", "DUPLICATE"}
    close_facts = facts_helpers._project(
        store, broker, target, refresh_now, query_set=refreshed.query_set
    )
    assert close_facts.risk_reduction_ready is True, close_facts.blockers
    assert close_facts.open_risk_ready is False
    state["close_facts"] = close_facts
    gate.allow_through(5)
    assert state["close_sent"].wait(10), state["error"]
    close_order = state["close_order"]
    assert close_order is not None and close_order.alive(), (
        None if close_order is None else close_order.getstatusname(),
        None if close_order is None else dict(close_order.info),
        api.native_calls,
    )
    assert close_order.info["factor_position_effect"] == "CLOSE"
    assert close_order.info["factor_intent_id"]
    assert len(api.native_calls) == 3
    assert api.native_calls[2] == ("insert", _INSTRUMENT, exchange, "502", 103)

    # Reconcile a complete query first, then deliver the same close through
    # the normal queued Store/Broker callback path with no TradeDate. The
    # query-derived fill updates the position book once; the late callback
    # updates Backtrader's Broker once and leaves a separate raw receipt.
    close_time = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
    closed_trade_row = {
        "TradeID": "trade-chain-close-1",
        "OrderRef": "502",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": exchange,
        "Direction": "1",
        "OffsetFlag": "1",
        "Volume": "1",
        "Price": "100",
        "TradeDate": close_time.strftime("%Y%m%d"),
        "TradeTime": close_time.strftime("%H:%M:%S"),
    }
    closed_order = {
        "OrderRef": "502",
        "InstrumentID": _INSTRUMENT,
        "ExchangeID": exchange,
        "OrderStatus": "0",
        "Direction": "1",
        "CombOffsetFlag": "1",
        "VolumeTotalOriginal": "1",
        "VolumeTraded": "1",
        "VolumeTotal": "0",
        "FrontID": 4,
        "SessionID": 7,
    }
    api.query_rows = route_query_rows(
        positions=(),
        orders=(terminal_order, closed_order),
        trades=(trade_row, closed_trade_row),
    )
    close_query = facts_helpers._refresh_all(store, target)
    close_query_facts = facts_helpers._project(
        store,
        broker,
        target,
        datetime.now(timezone.utc) + timedelta(milliseconds=2),
        query_set=close_query.query_set,
    )
    close_query_replay = coordinator.reconcile_trade_observations(close_query_facts)
    close_query_item = next(
        item
        for item in close_query_replay.items
        if item.execution_id == "ctp:{}:trade-chain-close-1".format(close_time.strftime("%Y%m%d"))
    )
    assert close_query_item.status == "APPLIED", close_query_replay.items
    assert broker.execution_position_snapshot(data).quantity == Decimal("1")
    api.emit_provider_trade_callback(
        "502",
        trade_id="trade-chain-close-1",
        quantity=1,
        offset="close",
        when=close_time,
        trade_date_override="not-a-trade-date",
    )
    api.emit_provider_order_callback("502", status="completed", filled=1, remaining=0)
    gate.allow_through(6)
    assert state["bar6"].wait(10), state["error"]
    assert state["close_order_completed"].is_set()
    assert state["close_trade_seen"].is_set()
    assert broker.execution_position_snapshot(data).quantity == Decimal("0")
    close_raw_callback = journal._connection.execute(
        """SELECT evidence_payload_json, acknowledged
           FROM execution_decision_callbacks
           WHERE intent_id=? AND evidence_payload_json LIKE '%unresolved_trade_callback%'""",
        (close_order.info["factor_intent_id"],),
    ).fetchone()
    assert close_raw_callback is not None and close_raw_callback[1] == 1
    assert '"trade_date":"not-a-trade-date"' in close_raw_callback[0]
    assert '"execution_id"' not in close_raw_callback[0]

    engine_thread.join(timeout=10)
    assert not engine_thread.is_alive()
    assert state["error"] is None
    assert len(state["result"]) == 1
    statuses = [status for status, _size, _ack in state["order_notifications"]]
    assert "Partial" in statuses
    assert "Canceled" in statuses
    assert "Completed" in statuses
    assert (
        sum(
            1
            for just_opened, closed, size in state["trade_notifications"]
            if just_opened and not closed and size == 1.0
        )
        == 1
    )
    assert any(
        not just_opened and closed and size == 0.0
        for just_opened, closed, size in state["trade_notifications"]
    )
    assert float(order.executed.size) == pytest.approx(1.0)
    assert float(close_order.executed.size) == pytest.approx(-1.0)
    assert journal.intent(order.info["factor_intent_id"]).state == "KNOWN"
    assert journal.intent(close_order.info["factor_intent_id"]).state == "KNOWN"
    assert coordinator.run_order_count() == 3

    # Repeated terminal history is reusable only while the complete current
    # trade query still agrees with durable callback fills.  A changed volume
    # for the same source TradeID blocks terminal reconciliation for the whole
    # route and cannot checkpoint the CLOSE as flat.
    changed_open_trade = dict(trade_row, Volume="2")
    api.query_rows = route_query_rows(
        positions=(),
        orders=(terminal_order, closed_order),
        trades=(changed_open_trade, closed_trade_row),
    )
    changed_refresh = facts_helpers._refresh_all(store, target)
    changed_facts = facts_helpers._project(
        store,
        broker,
        target,
        datetime.now(timezone.utc) + timedelta(milliseconds=2),
        query_set=changed_refresh.query_set,
    )
    changed_terminal = coordinator.reconcile_terminal_order_observations(changed_facts)
    assert all(
        item.status == "BLOCKED" and item.blocker_code == "TERMINAL_TRADE_PROJECTION_NOT_RECONCILED"
        for item in changed_terminal.items
    ), changed_terminal.items
    assert journal.instrument_resolution(close_order.info["factor_intent_id"]) is None

    # A final complete source refresh resolves the completed CLOSE and verifies
    # the persistent book is flat after the real Broker notifications.
    api.query_rows = route_query_rows(
        positions=(),
        orders=(terminal_order, closed_order),
        trades=(trade_row, closed_trade_row),
    )
    final_refresh = facts_helpers._refresh_all(store, target)
    final_facts = facts_helpers._project(
        store,
        broker,
        target,
        datetime.now(timezone.utc) + timedelta(milliseconds=2),
        query_set=final_refresh.query_set,
    )
    final_trades = coordinator.reconcile_trade_observations(final_facts)
    assert len(final_trades.items) == 2
    assert all(item.status in {"APPLIED", "DUPLICATE"} for item in final_trades.items)
    close_trade_replay = next(
        item
        for item in final_trades.items
        if item.execution_id == "ctp:{}:trade-chain-close-1".format(close_time.strftime("%Y%m%d"))
    )
    assert close_trade_replay.status == "DUPLICATE"
    final_terminals = coordinator.reconcile_terminal_order_observations(final_facts)
    assert len(final_terminals.items) == 2
    assert all(item.status == "RESOLVED" for item in final_terminals.items), tuple(
        (item.status, item.blocker_code, item.intent_id) for item in final_terminals.items
    )
    # The later flat snapshot must resolve the CLOSE without rewriting the
    # original canceled OPEN's immutable non-flat terminal checkpoint.
    assert final_terminals.items[0].intent_id == order.info["factor_intent_id"]
    assert final_terminals.items[0].reconciliation_id == opening_reconciliation_id
    close_resolution = journal.instrument_resolution(close_order.info["factor_intent_id"])
    assert close_resolution is not None and close_resolution.position_flat is True
    assert final_terminals.items[1].reconciliation_id == close_resolution.reconciliation_id
    final_terminal_proof = coordinator.terminal_order_reconciliation_snapshot(final_facts)
    assert final_terminal_proof.truncated is False
    assert all(item.status == "RESOLVED" for item in final_terminal_proof.items)
    position = coordinator.position_book.snapshot(
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        instrument=_INSTRUMENT,
        exchange=exchange,
        broker_quantity=Decimal("0"),
        long_quantity=Decimal("0"),
        short_quantity=Decimal("0"),
        snapshot_id=final_facts.snapshot_id,
        available_at=final_facts.available_at,
    )
    assert position.status == "FLAT", position
