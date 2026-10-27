"""Ordinary Strategy-to-registered-sim execution route integration tests.

The production Broker, Store and RegisteredSimWrapper remain in the path.  The
fake class below supplies only SDK/provider leaves, including the synchronous
native-call hooks consumed by the real wrapper.
"""

from __future__ import annotations

import collections
import contextvars
from contextlib import ExitStack
from dataclasses import replace
import threading
import time
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
    ExecutionDecisionJournalError,
    ExecutionDecisionKey,
    ExecutionIntentKey,
    ExecutionRunLossGuardContext,
)
from backtrader.stores.factor_execution import FactorExecutionCoordinator, FactorExecutionError
from backtrader.stores.factor_execution_facts import (
    FactorExecutionAccountFacts,
    FactorExecutionTarget,
)
from backtrader.stores.registered_sim import RegisteredSimStore, RegisteredSimWrapper
from tests.unit.stores import test_factor_execution_facts as facts_helpers


_INSTRUMENT = facts_helpers._INSTRUMENT
_EXCHANGE = facts_helpers._EXCHANGE
_SCOPE = "alpha003"
_ACCOUNT_SCOPE = "acct-scope"
_COHORT = "rb-cohort"
_CALENDAR = "simnow-common-minutes-v1"


@pytest.mark.parametrize(("side", "signed_size"), [("BUY", 2), ("SELL", -2)])
def test_unknown_insert_terminal_event_matches_backtrader_signed_size(side, signed_size):
    intent_id = "unknown-open-intent"
    order_ref = 23
    order = SimpleNamespace(
        alive=lambda: True,
        isbuy=lambda: side == "BUY",
        size=signed_size,
        info={
            "execution_unknown": True,
            "factor_intent_id": intent_id,
            "factor_strategy_scope": _SCOPE,
            "instrument_id": _INSTRUMENT,
            "exchange_id": _EXCHANGE,
            "external_order_ref": "native-23",
            "factor_position_effect": "OPEN",
            "factor_session_account_fingerprint": "fake-account-1",
            "factor_session_trading_day": "20261024",
            "factor_session_front_id": 4,
            "factor_session_id": 7,
        },
        data=SimpleNamespace(_name="display-name"),
    )
    coordinator = SimpleNamespace(
        broker=SimpleNamespace(orders={order_ref: order}), strategy_scope=_SCOPE
    )
    intent = SimpleNamespace(
        intent_id=intent_id,
        key=SimpleNamespace(side=side),
        original_identity={
            "backtrader_order_ref": order_ref,
            "account_fingerprint": "fake-account-1",
            "trading_day": "20261024",
            "front_id": 4,
            "session_id": 7,
        },
        economic_payload={"offset": "open", "limit_price": "100"},
    )
    observation = SimpleNamespace(
        instrument=_INSTRUMENT,
        exchange=_EXCHANGE,
        order_ref="native-23",
        order_sys_id="sys-23",
        terminal_status="5",
        terminal_state="CANCELED",
    )

    event = FactorExecutionCoordinator._unknown_terminal_broker_event(
        coordinator, None, intent, observation, Decimal("2")
    )

    assert event["side"] == side.lower()
    assert event["size"] == 2
    assert event["filled"] == 0
    assert event["remaining"] == 2

    order.size = -signed_size
    with pytest.raises(FactorExecutionError, match="UNKNOWN_BROKER_ORDER_LINEAGE_MISMATCH"):
        FactorExecutionCoordinator._unknown_terminal_broker_event(
            coordinator, None, intent, observation, Decimal("2")
        )


def test_terminal_recovery_scope_is_durable_thread_local_and_not_reentrant(tmp_path):
    journal = ExecutionDecisionJournal(tmp_path / "terminal-recovery.sqlite3")
    store = SimpleNamespace(registered_sim_route_id="simnow-registered-v1", allow_writes=True)
    broker = SimpleNamespace(store=store)
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        logical_run_id="run-1",
        max_order_intents_per_grid=1,
        max_order_intents_per_run=8,
    )
    try:
        copied_context = None
        with coordinator.terminal_recovery_scope(timeout_seconds=0.25) as started_at:
            assert started_at.tzinfo is not None
            scope = coordinator._current_terminal_recovery_scope()
            assert scope is not None
            assert scope.coordinator is coordinator
            assert scope.journal is journal
            assert scope.lease.cross_process is True
            with ExitStack() as stack:
                nested = stack.enter_context(pytest.raises(FactorExecutionError))
                stack.enter_context(coordinator.terminal_recovery_scope(timeout_seconds=0.25))
            assert nested.value.code == "DISPATCHING_RECOVERY_SCOPE_NESTED"
            copied_context = contextvars.copy_context()
        assert coordinator._current_terminal_recovery_scope() is None
        assert copied_context is not None
        assert copied_context.run(coordinator._current_terminal_recovery_scope) is None
    finally:
        journal.close()

    memory_journal = ExecutionDecisionJournal(":memory:")
    memory_coordinator = FactorExecutionCoordinator(
        SimpleNamespace(store=store),
        memory_journal,
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        logical_run_id="run-1",
        max_order_intents_per_grid=1,
        max_order_intents_per_run=8,
    )
    try:
        with ExitStack() as stack:
            memory_scope = stack.enter_context(pytest.raises(FactorExecutionError))
            stack.enter_context(memory_coordinator.terminal_recovery_scope(timeout_seconds=0.25))
        assert memory_scope.value.code == "DISPATCH_RECOVERY_REQUIRES_DURABLE_JOURNAL"
    finally:
        memory_journal.close()


@pytest.mark.parametrize(
    ("owner_state", "cancel_intent_id", "owner_intent_state", "owner_dispatch_state", "matches"),
    [
        ("DISPATCHING", None, "DISPATCHING", None, True),
        ("UNKNOWN", None, "UNKNOWN", None, False),
        ("DISPATCHING", "cancel-child", "DISPATCHING", None, False),
        ("DISPATCHING", None, "DISPATCHING", "KNOWN", False),
    ],
)
def test_dispatching_flat_book_exception_requires_exact_pending_open_owner(
    owner_state, cancel_intent_id, owner_intent_state, owner_dispatch_state, matches
):
    intent_id = "dispatching-open-intent"
    original_identity = {
        "operation": "insert",
        "instrument_id": _INSTRUMENT,
        "exchange_id": _EXCHANGE,
        "order_ref": "native-23",
    }
    intent = SimpleNamespace(
        intent_id=intent_id,
        state="DISPATCHING",
        dispatch_state=None,
        provider_identity=None,
        outcome_code=None,
        key=SimpleNamespace(action="SUBMIT", position_effect="OPEN", instrument=_INSTRUMENT),
        original_identity=original_identity,
    )
    owner_intent = SimpleNamespace(
        intent_id=intent_id,
        state=owner_intent_state,
        dispatch_state=owner_dispatch_state,
        provider_identity=None,
        outcome_code=None,
        key=intent.key,
        original_identity=original_identity,
    )
    owner = SimpleNamespace(
        account_scope=_ACCOUNT_SCOPE,
        instrument=_INSTRUMENT,
        intent_id=intent_id,
        state=owner_state,
        cancel_intent_id=cancel_intent_id,
    )
    coordinator = FactorExecutionCoordinator.__new__(FactorExecutionCoordinator)
    coordinator.account_scope = _ACCOUNT_SCOPE
    coordinator.journal = SimpleNamespace(
        active_instrument_owner=lambda _account, _instrument: owner,
        intent=lambda _intent_id: owner_intent,
    )
    observation = SimpleNamespace(
        instrument=_INSTRUMENT,
        exchange=_EXCHANGE,
        order_ref="native-23",
    )
    assert coordinator._dispatching_pending_owner_is_exact(intent, observation) is matches


class _FakeProviderClient(facts_helpers._ProviderLeaves):
    """Provider client base composed under the real RegisteredSimWrapper."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.native_calls = []
        self._native_request_id = 100
        self._next_order_reference = 500
        self.trader_client._front_id = 4
        self.trader_client._session_id = 7
        get_session_state = self.trader_client.get_session_state

        def session_state_with_native_identity():
            state = get_session_state()
            state["front_id"] = self.trader_client._front_id
            state["session_id"] = self.trader_client._session_id
            return state

        self.trader_client.get_session_state = session_state_with_native_identity
        self.trader_client.next_order_ref = self._reserve_order_ref
        self.trader_client.submit_order_insert = self._native_insert
        self.trader_client.submit_order_action = self._native_cancel
        self._provider_orders = {}
        # Mirror the generated CTP wrapper: normalized provider callbacks and
        # durable recovery events share its deque, which Store.poll drains.
        self._order_updates = collections.deque()
        self._live_bar_event_notifier = None
        self.use_live_query_clock = False
        self.query_completion_floor = None

    def set_live_bar_event_notifier(self, callback):
        self._live_bar_event_notifier = callback

    def _notify_live_bar_event(self):
        notifier = self._live_bar_event_notifier
        if notifier is not None:
            notifier()

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
        self._order_updates.append(update)

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
        self._order_updates.append(
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
        """Drain the same normal API queue used by the generated CTP wrapper."""
        if not self._order_updates:
            return None
        return self._order_updates.popleft()

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
    # Manual component cases do not pass through Store.getbroker()/Cerebro's
    # Broker startup, so bind the same exact Broker metadata owner explicitly.
    store._broker = broker
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.setbroker(broker)
    cerebro._init_stcount()
    data.reset()
    data._start()
    assert data.load() is True
    # PandasData's _dataname is its DataFrame. Bind the synthetic routed
    # contract explicitly so the RegisteredSimStore order path sees the same
    # exact subscribed instrument a live CTP feed exposes.
    data._dataname = _INSTRUMENT
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


def _live_scope(
    coordinator,
    strategy,
    facts,
    *,
    now,
    intent_key,
    economics,
    loss_guard_context=None,
    cohort_id=_COHORT,
    batch_id="batch-1",
    close_time=None,
):
    close_time = (
        (now - timedelta(seconds=2)).replace(microsecond=0)
        if close_time is None
        else close_time
    )
    batch = LiveCohortBatch(
        batch_id=batch_id,
        cohort_id=cohort_id,
        calendar_id=_CALENDAR,
        calendar_version="v1",
        epoch_id=1,
        slot_index=0,
        close_time=close_time,
        available_at=close_time + timedelta(milliseconds=1),
    )
    snapshot = LiveFactorSnapshot(
        plan_id="alpha003-test-plan",
        cohort_id=cohort_id,
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
        cohort_id=cohort_id,
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
        loss_guard_context=loss_guard_context,
    )


def _qualified_loss_account_facts(
    *, account_scope, snapshot_id, available_at, trading_day, total_net_pnl
):
    return FactorExecutionAccountFacts(
        account_scope=account_scope,
        snapshot_id=snapshot_id,
        available_at=available_at,
        route_permitted=True,
        available_margin=Decimal("100000"),
        used_margin=Decimal("0"),
        current_notional=Decimal("0"),
        current_worst_case_loss=Decimal("0"),
        account_fingerprint="fake-account-1",
        connection_generation=1,
        trading_day=trading_day,
        total_net_pnl=total_net_pnl,
        currency="CNY",
        total_net_pnl_available=True,
        total_net_pnl_reason=None,
    )


def test_coordinator_run_loss_guard_is_explicit_typed_and_restart_sticky(tmp_path):
    now = datetime.now(timezone.utc)
    journal = ExecutionDecisionJournal(tmp_path / "coordinator-loss-guard.sqlite3")
    store = SimpleNamespace(registered_sim_route_id="simnow-registered-v1", allow_writes=True)
    broker = SimpleNamespace(store=store)
    coordinator = FactorExecutionCoordinator(
        broker,
        journal,
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        logical_run_id="run-loss-guard-component",
        max_order_intents_per_grid=2,
        max_order_intents_per_run=8,
    )
    context = ExecutionRunLossGuardContext(
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        logical_run_id="run-loss-guard-component",
        trading_day=facts_helpers._TRADING_DAY,
        currency="CNY",
        pnl_basis="validated_total_net_after_fees_v1",
    )
    baseline = _qualified_loss_account_facts(
        account_scope=_ACCOUNT_SCOPE,
        snapshot_id="qualified-pnl-baseline",
        available_at=now - timedelta(seconds=1),
        trading_day=facts_helpers._TRADING_DAY,
        total_net_pnl=Decimal("10000"),
    )
    try:
        assert coordinator.run_loss_guard(context) is None
        with pytest.raises(FactorExecutionError, match="RUN_LOSS_GUARD_NOT_CONFIGURED"):
            coordinator.record_run_loss_observation(context, baseline)
        assert coordinator.run_loss_guard(context) is None

        unqualified = replace(
            baseline,
            total_net_pnl=None,
            total_net_pnl_available=False,
            total_net_pnl_reason="position_profit_unavailable",
        )
        with pytest.raises(FactorExecutionError, match="RUN_LOSS_ACCOUNT_PNL_UNQUALIFIED"):
            coordinator.enable_run_loss_guard(
                context,
                unqualified,
                net_loss_threshold=Decimal("1000"),
                max_observation_age_seconds=600,
            )
        for invalid, code in (
            (
                replace(baseline, trading_day="20261025"),
                "RUN_LOSS_ACCOUNT_TRADING_DAY_MISMATCH",
            ),
            (replace(baseline, currency="USD"), "RUN_LOSS_ACCOUNT_CURRENCY_MISMATCH"),
            (
                replace(baseline, available_at=now.replace(tzinfo=None)),
                "RUN_LOSS_ACCOUNT_ASOF_INVALID",
            ),
            (
                replace(baseline, total_net_pnl=Decimal("NaN")),
                "RUN_LOSS_ACCOUNT_PNL_UNQUALIFIED",
            ),
        ):
            with pytest.raises(FactorExecutionError, match=code):
                coordinator.enable_run_loss_guard(
                    context,
                    invalid,
                    net_loss_threshold=Decimal("1000"),
                    max_observation_age_seconds=600,
                )
        assert coordinator.run_loss_guard(context) is None

        enabled = coordinator.enable_run_loss_guard(
            context,
            baseline,
            net_loss_threshold=Decimal("1000"),
            max_observation_age_seconds=600,
        )
        assert enabled.baseline_observation_id == baseline.snapshot_id
        assert enabled.baseline_total_net_pnl == Decimal("10000")
        assert not enabled.tripped

        tripped_facts = replace(
            baseline,
            snapshot_id="qualified-pnl-trip",
            available_at=datetime.now(timezone.utc),
            total_net_pnl=Decimal("9000"),
        )
        tripped = coordinator.record_run_loss_observation(context, tripped_facts)
        assert tripped.tripped
        assert tripped.trip_observation_id == tripped_facts.snapshot_id
        assert tripped.total_net_loss_from_baseline == Decimal("1000")

        restarted = FactorExecutionCoordinator(
            SimpleNamespace(store=store),
            journal,
            account_scope=_ACCOUNT_SCOPE,
            strategy_scope=_SCOPE,
            logical_run_id="run-loss-guard-component",
            max_order_intents_per_grid=2,
            max_order_intents_per_run=8,
        )
        assert restarted.run_loss_guard(context) == tripped
        with pytest.raises(FactorExecutionError, match="RUN_LOSS_GUARD_POLICY_CONFLICT"):
            restarted.enable_run_loss_guard(
                context,
                tripped_facts,
                net_loss_threshold=Decimal("1000"),
                max_observation_age_seconds=600,
            )
        assert restarted.run_loss_guard(context) == tripped
    finally:
        journal.close()


def test_coordinator_run_loss_guard_survives_sqlite_close_reopen(tmp_path):
    """A fresh coordinator observes the loss fence after SQLite close/reopen.

    The production coordinator and file-backed journal APIs run with synthetic
    facts only. No order is dispatched and no Store/provider is called; risk-
    only rows prove journal admission, not native execution.
    """
    path = tmp_path / "run-loss-guard-reopen.sqlite3"
    journal = ExecutionDecisionJournal(path)
    context = ExecutionRunLossGuardContext(
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        logical_run_id="run-loss-guard-reopen",
        trading_day=facts_helpers._TRADING_DAY,
        currency="CNY",
        pnl_basis="validated_total_net_after_fees_v1",
    )
    store = SimpleNamespace(registered_sim_route_id="simnow-registered-v1", allow_writes=True)
    now = datetime.now(timezone.utc)
    coordinator = FactorExecutionCoordinator(
        SimpleNamespace(store=store),
        journal,
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        logical_run_id=context.logical_run_id,
        max_order_intents_per_grid=2,
        max_order_intents_per_run=8,
    )

    def iso_utc(value):
        return value.isoformat().replace("+00:00", "Z")

    def open_decision(database, *, key, batch_id, expected_used):
        return database.record_grid_decision(
            key,
            open_payload,
            intent_keys=(open_intent,),
            epoch_id="epoch-1",
            batch_id=batch_id,
            eligible=True,
            complete=True,
            live_ready=True,
            inputs_complete=True,
            max_order_intents_per_run=8,
            expected_run_order_intents_used=expected_used,
            remaining_exit_intent_reserve=0,
            loss_guard_context=context,
        )

    def risk_decision(database, *, cohort_id, close_time, payload, intent, expected_used):
        return database.record_risk_decision(
            ExecutionDecisionKey(
                account_scope=_ACCOUNT_SCOPE,
                strategy_scope=_SCOPE,
                logical_run_id=context.logical_run_id,
                cohort_id=cohort_id,
                close_time=close_time,
                decision_kind="ALPHA003_RISK_REDUCTION",
            ),
            payload,
            intent_keys=(intent,),
            max_order_intents_per_run=8,
            expected_run_order_intents_used=expected_used,
            remaining_exit_intent_reserve=0,
        )

    open_intent = ExecutionIntentKey(
        action="SUBMIT",
        instrument=_INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    open_payload = {
        "intent_economics": (
            {
                "instrument": _INSTRUMENT,
                "exchange": _EXCHANGE,
                "side": "BUY",
                "position_effect": "OPEN",
                "quantity": "1",
                "limit_price": "100",
                "offset": "open",
            },
        )
    }
    initial_key = ExecutionDecisionKey(
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        logical_run_id=context.logical_run_id,
        cohort_id="loss-guard-reopen-grid",
        close_time=iso_utc(now - timedelta(seconds=3)),
        decision_kind="ALPHA003_GRID",
    )
    try:
        baseline_facts = _qualified_loss_account_facts(
            account_scope=_ACCOUNT_SCOPE,
            snapshot_id="reopen-baseline",
            available_at=now - timedelta(seconds=4),
            trading_day=facts_helpers._TRADING_DAY,
            total_net_pnl=Decimal("10000"),
        )
        baseline = coordinator.enable_run_loss_guard(
            context,
            baseline_facts,
            net_loss_threshold=Decimal("1000"),
            max_observation_age_seconds=600,
        )
        assert not baseline.tripped

        first = open_decision(
            journal, key=initial_key, batch_id="loss-guard-reopen-batch-1", expected_used=0
        )
        assert first.is_new_grid is True
        assert first.decision is not None
        assert journal.run_order_count(
            _ACCOUNT_SCOPE, _SCOPE, context.logical_run_id
        ) == 1

        tripped_facts = _qualified_loss_account_facts(
            account_scope=_ACCOUNT_SCOPE,
            snapshot_id="reopen-trip",
            available_at=now - timedelta(seconds=2),
            trading_day=facts_helpers._TRADING_DAY,
            total_net_pnl=Decimal("9000"),
        )
        tripped = coordinator.record_run_loss_observation(
            context, tripped_facts
        )
        assert tripped.tripped is True
        assert tripped.total_net_loss_from_baseline == Decimal("1000")

        journal.close()
        journal = None
        journal = ExecutionDecisionJournal(path)
        restarted = FactorExecutionCoordinator(
            SimpleNamespace(store=store),
            journal,
            account_scope=_ACCOUNT_SCOPE,
            strategy_scope=_SCOPE,
            logical_run_id=context.logical_run_id,
            max_order_intents_per_grid=2,
            max_order_intents_per_run=8,
        )

        persisted = restarted.run_loss_guard(context)
        assert persisted is not None
        assert persisted.baseline_observation_id == "reopen-baseline"
        assert persisted.baseline_total_net_pnl == Decimal("10000")
        assert persisted.net_loss_threshold == Decimal("1000")
        assert persisted.tripped is True
        assert persisted.trip_observation_id == "reopen-trip"
        assert persisted.latest_observation_id == "reopen-trip"
        assert persisted.latest_total_net_pnl == Decimal("9000")

        improved_facts = _qualified_loss_account_facts(
            account_scope=_ACCOUNT_SCOPE,
            snapshot_id="reopen-improved-pnl",
            available_at=now - timedelta(seconds=1),
            trading_day=facts_helpers._TRADING_DAY,
            total_net_pnl=Decimal("9500"),
        )
        improved = restarted.record_run_loss_observation(
            context,
            improved_facts,
        )
        assert improved.tripped is True
        assert improved.baseline_observation_id == "reopen-baseline"
        assert improved.baseline_total_net_pnl == Decimal("10000")
        assert improved.net_loss_threshold == Decimal("1000")
        assert improved.trip_observation_id == "reopen-trip"
        assert improved.latest_observation_id == "reopen-improved-pnl"
        assert improved.latest_total_net_pnl == Decimal("9500")

        replay = open_decision(
            journal,
            key=initial_key,
            batch_id="loss-guard-reopen-batch-1",
            expected_used=1,
        )
        assert replay.is_new_grid is False
        assert replay.decision is not None
        assert replay.decision.decision_id == first.decision.decision_id
        assert journal.run_order_count(
            _ACCOUNT_SCOPE, _SCOPE, context.logical_run_id
        ) == 1

        new_key = replace(
            initial_key,
            close_time=iso_utc(now - timedelta(seconds=2)),
        )
        with pytest.raises(
            ExecutionDecisionJournalError,
            match="RUN_TOTAL_NET_LOSS_LIMIT_REACHED",
        ):
            open_decision(
                journal,
                key=new_key,
                batch_id="loss-guard-reopen-batch-2",
                expected_used=1,
            )

        next_day = replace(
            context,
            trading_day=(
                datetime.strptime(context.trading_day, "%Y%m%d") + timedelta(days=1)
            ).strftime("%Y%m%d"),
        )
        next_day_facts = _qualified_loss_account_facts(
            account_scope=_ACCOUNT_SCOPE,
            snapshot_id="must-not-rebaseline-next-day",
            available_at=now - timedelta(seconds=1),
            trading_day=next_day.trading_day,
            total_net_pnl=Decimal("9500"),
        )
        with pytest.raises(
            FactorExecutionError,
            match="RUN_LOSS_GUARD_POLICY_CONFLICT",
        ):
            restarted.enable_run_loss_guard(
                next_day,
                next_day_facts,
                net_loss_threshold=Decimal("1000"),
                max_observation_age_seconds=600,
            )
        still_tripped = restarted.run_loss_guard(context)
        assert still_tripped == improved

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
        cancel_result = risk_decision(
            journal,
            cohort_id="loss-guard-risk-cancel",
            close_time=iso_utc(now - timedelta(seconds=1)),
            payload={
                "intent_economics": (
                    {
                        "instrument": _INSTRUMENT,
                        "exchange": _EXCHANGE,
                        "side": "BUY",
                        "position_effect": "OPEN",
                        "reason": "explicit risk-only cancellation",
                    },
                ),
            },
            intent=cancel_intent,
            expected_used=1,
        )
        assert cancel_result.is_new_grid is True
        assert journal.run_order_count(
            _ACCOUNT_SCOPE, _SCOPE, context.logical_run_id
        ) == 2

        close_result = risk_decision(
            journal,
            cohort_id="loss-guard-risk-close",
            close_time=iso_utc(now - timedelta(milliseconds=500)),
            payload={
                "intent_economics": (
                    {
                        "instrument": _INSTRUMENT,
                        "exchange": _EXCHANGE,
                        "side": "SELL",
                        "position_effect": "CLOSE",
                        "quantity": "1",
                        "reason": "explicit position risk reduction",
                    },
                ),
            },
            intent=close_intent,
            expected_used=2,
        )
        assert close_result.is_new_grid is True
        assert journal.run_order_count(
            _ACCOUNT_SCOPE, _SCOPE, context.logical_run_id
        ) == 3  # one earlier OPEN plus the CANCEL and risk-reducing CLOSE
    finally:
        if journal is not None:
            journal.close()


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
    store.registered_sim_configure_arm_templates(
        {
            (_INSTRUMENT, _EXCHANGE): {
                "md_front": "tcp://127.0.0.1:1",
                "strategy_identity_sha256": "a" * 64,
                "execution_cycle_id": "cycle-ordinary-buy",
                "preflight_sha256": "b" * 64,
            }
        }
    )
    before_arm = store.registered_sim_route_eligibility(_INSTRUMENT, _EXCHANGE)
    assert before_arm.arm_templates_configured is True
    assert before_arm.arm_template_configured is True
    assert before_arm.sdk_capability_armed is False
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
    assert order.info["factor_session_account_fingerprint"] == facts.account.account_fingerprint
    assert order.info["factor_session_connection_generation"] == 1
    assert order.info["factor_session_trading_day"] == "20261024"
    assert order.info["factor_session_front_id"] == 4
    assert order.info["factor_session_id"] == 7
    assert api.trader_client._gate_state["armed"] is True
    assert api.trader_client._gate_state["instrument"] == _INSTRUMENT
    assert api.native_calls == [("insert", _INSTRUMENT, _EXCHANGE, "501", 101)]
    intent = journal.intent(order.info["factor_intent_id"])
    assert intent.state == "KNOWN"
    assert intent.original_identity == {
        "account_fingerprint": facts.account.account_fingerprint,
        "backtrader_order_ref": order.ref,
        "connection_generation": 1,
        "exchange_id": _EXCHANGE,
        "front_id": 4,
        "instrument_id": _INSTRUMENT,
        "operation": "insert",
        "order_ref": "501",
        "session_id": 7,
        "trading_day": "20261024",
    }
    order.info["front_id"] = None
    order.info["session_id"] = None
    snapshot = broker.execution_order_snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].front_id == 4
    assert snapshot[0].session_id == 7
    assert state["decision_id"] is not None


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("_connection_generation", 2),
        ("_front_id", 5),
        ("_session_id", 8),
    ],
)
def test_actual_cerebro_session_change_after_preflight_blocks_native_dispatch(
    changed_field, changed_value
):
    now = datetime.now(timezone.utc)
    api, store, broker, journal, coordinator, target, _data, _strategy, cerebro = _system(now=now)
    query = facts_helpers._refresh_all(store, target)
    store.registered_sim_configure_arm_templates(
        {
            (_INSTRUMENT, _EXCHANGE): {
                "md_front": "tcp://127.0.0.1:1",
                "strategy_identity_sha256": "a" * 64,
                "execution_cycle_id": "cycle-session-race",
                "preflight_sha256": "b" * 64,
            }
        }
    )
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
    state = {"order": None, "decision_id": None}
    reserve_ref = store.registered_sim_reserve_order_ref

    def reserve_then_change_session():
        order_ref = reserve_ref()
        # This is the narrow reconnect race: the selected route and SDK grant
        # were validated immediately before the ordinary Broker reserved its
        # native ref, but the live session changes before Store dispatch.
        setattr(api.trader_client, changed_field, changed_value)
        return order_ref

    store.registered_sim_reserve_order_ref = reserve_then_change_session

    def command(owner):
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
    assert state["order"] is not None
    assert state["decision_id"] is not None
    assert state["order"].info["factor_session_connection_generation"] == 1
    assert getattr(api.trader_client, changed_field) == changed_value
    assert api.native_calls == []
    intent = journal.intent(state["order"].info["factor_intent_id"])
    assert intent.dispatch_state == "UNKNOWN"


def test_no_template_facts_reject_same_key_sdk_rearm_as_active_route():
    now = datetime.now(timezone.utc)
    api, store, broker, _journal, _coordinator, target, _data, _strategy, _cerebro = _system(
        now=now
    )
    query = facts_helpers._refresh_all(store, target)
    store.registered_sim_arm(
        instrument=_INSTRUMENT,
        exchange=_EXCHANGE,
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256="a" * 64,
        execution_cycle_id="cycle-legacy-grant",
        preflight_sha256="b" * 64,
    )
    assert facts_helpers._consume_quote(store) is not None

    # An out-of-band SDK re-arm changes the signed proof while keeping the
    # instrument, session and opaque core capability unchanged. The route DTO
    # and the resulting strategy facts must no longer call this grant active.
    api.trader_client._gate_state["proof_sha256"] = "f" * 64
    route = store.registered_sim_route_eligibility(_INSTRUMENT, _EXCHANGE)
    assert route.capability_matches_route is False

    facts = facts_helpers._project(store, broker, target, now, query_set=query.query_set)
    target_route = next(
        item for item in facts.route_eligibilities if item.instrument == _INSTRUMENT
    )
    assert target_route.eligible is False
    assert target_route.capability_matches_route is False


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
    assert open_facts.account is not None
    qualified_open_account = replace(
        open_facts.account,
        total_net_pnl=Decimal("10000"),
        currency="CNY",
        total_net_pnl_available=True,
        total_net_pnl_reason=None,
    )
    open_facts = replace(open_facts, account=qualified_open_account)
    loss_guard_context = ExecutionRunLossGuardContext(
        account_scope=_ACCOUNT_SCOPE,
        strategy_scope=_SCOPE,
        logical_run_id="run-1",
        trading_day=facts_helpers._TRADING_DAY,
        currency="CNY",
        pnl_basis="validated_total_net_after_fees_v1",
    )
    baseline_guard = coordinator.enable_run_loss_guard(
        loss_guard_context,
        qualified_open_account,
        net_loss_threshold=Decimal("1000"),
        max_observation_age_seconds=600,
    )
    assert not baseline_guard.tripped

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
        "owner": None,
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
                loss_guard_context=loss_guard_context,
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
            state["owner"] = owner
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

    trip_account_facts = replace(
        qualified_open_account,
        snapshot_id="pnl-trip-after-open",
        available_at=datetime.now(timezone.utc),
        total_net_pnl=Decimal("9000"),
    )
    tripped_guard = coordinator.record_run_loss_observation(
        loss_guard_context, trip_account_facts
    )
    assert tripped_guard.tripped
    assert tripped_guard.total_net_loss_from_baseline == Decimal("1000")
    tripped_open_facts = replace(open_facts, account=trip_account_facts)
    with _live_scope(
        coordinator,
        state["owner"],
        open_facts,
        now=now,
        intent_key=open_intent,
        economics=open_economics,
        loss_guard_context=loss_guard_context,
    ) as replayed_open:
        assert replayed_open.is_new_grid is False
        assert replayed_open.dispatch_allowed is False

    probe_close_time = (now - timedelta(seconds=2)).replace(microsecond=0) + timedelta(
        seconds=1
    )
    with pytest.raises(
        ExecutionDecisionJournalError, match="RUN_LOSS_GUARD_CONTEXT_REQUIRED"
    ):
        with _live_scope(
            coordinator,
            state["owner"],
            tripped_open_facts,
            now=now,
            intent_key=open_intent,
            economics=open_economics,
            cohort_id="loss-guard-context-required",
            batch_id="loss-guard-context-required-batch",
            close_time=probe_close_time,
        ):
            pass
    with pytest.raises(
        ExecutionDecisionJournalError, match="RUN_TOTAL_NET_LOSS_LIMIT_REACHED"
    ):
        with _live_scope(
            coordinator,
            state["owner"],
            tripped_open_facts,
            now=now,
            intent_key=open_intent,
            economics=open_economics,
            loss_guard_context=loss_guard_context,
            cohort_id="loss-guard-tripped-open",
            batch_id="loss-guard-tripped-open-batch",
            close_time=probe_close_time,
        ):
            pass

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
    if close_order is not None and close_order.status == Order.Rejected:
        # This is a synthetic-only fake-provider path.  The Broker maps
        # exceptions from several distinct pre-trade checks to the same
        # finite error code; retain a bounded fake exception message in the
        # focused failure so a failed run can identify the throwing check.
        error_code = close_order.info.get("error_code")
        error_msg = close_order.info.get("error_msg")
        diagnostic_code = error_code if type(error_code) is str else None
        diagnostic_msg = error_msg[:512] if type(error_msg) is str else None
        assert error_code != "pre_trade_state_refresh_failed", (
            "synthetic close pre-trade exception: code={!r}, message={!r}".format(
                diagnostic_code, diagnostic_msg
            )
        )
    assert close_order is not None and close_order.alive(), (
        None if close_order is None else close_order.getstatusname(),
        None if close_order is None else dict(close_order.info),
        api.native_calls,
    )
    assert close_order.info["factor_position_effect"] == "CLOSE"
    assert close_order.info["factor_intent_id"]
    assert len(api.native_calls) == 3
    assert api.native_calls[2] == ("insert", _INSTRUMENT, exchange, "502", 103)
    assert coordinator.run_loss_guard(loss_guard_context).tripped

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
