"""Offline evidence for the Iteration 41 managed fill projection boundary.

The durable managed-execution facade owns provider idempotency.  The
Backtrader broker owns its in-process order, position, and observer facts.
These tests cover the ordinary first-dispatch projection and prove that legacy
or fixture replays without a private framework receipt remain rejected.  The
separate integration recovery test exercises the fully composed local receipt
path across a fresh process-shaped Broker state.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace
from typing import Any, Optional

import backtrader as bt
import pandas as pd
import pytest

from backtrader.stores.managed_execution import (
    CtpManagedExecutionProjection,
    CtpManagedProjectionState,
)
from backtrader.stores.btapistore import ManagedCtpHandoffError
from backtrader_runtime.managed_execution import (
    ManagedExecutionBindingError,
    ManagedExecutionBridge,
    project_cancel_record_to_store_response,
)
from backtrader_runtime.framework_projection import FrameworkProjectionRecoveryError
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


class _Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class _PositionEffect(Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CLOSE_TODAY = "CLOSE_TODAY"
    CLOSE_YESTERDAY = "CLOSE_YESTERDAY"


class _ExecutionState(Enum):
    ACKED = "ACKED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class _Intent:
    scope: object
    intent_id: str
    signal_id: str
    instrument: str
    side: _Side
    quantity: Decimal
    price: Decimal
    position_effect: _PositionEffect
    reduce_only: bool
    metadata_version: str
    tags: dict[str, str]


class _OrderIntent:
    @staticmethod
    def limit(**kwargs: Any) -> _Intent:
        return _Intent(**kwargs)


@dataclass
class _ProviderObservation:
    intent_id: str
    state: _ExecutionState
    provider_order_id: Optional[str] = None
    filled_quantity: Decimal = Decimal("0")
    average_price: Optional[Decimal] = None
    reason_code: Optional[str] = None

    @staticmethod
    def accepted(intent_id: str, provider_order_id: str) -> "_ProviderObservation":
        return _ProviderObservation(
            intent_id=intent_id,
            state=_ExecutionState.ACKED,
            provider_order_id=provider_order_id,
        )

    @staticmethod
    def rejected(intent_id: str, reason: str) -> "_ProviderObservation":
        return _ProviderObservation(
            intent_id=intent_id,
            state=_ExecutionState.REJECTED,
            reason_code=reason,
        )


class _Execution:
    Side = _Side
    PositionEffect = _PositionEffect
    OrderIntent = _OrderIntent
    ProviderObservation = _ProviderObservation
    ExecutionState = _ExecutionState


@dataclass
class _CumulativeProviderObservation:
    intent_id: str
    state: _ExecutionState
    provider_order_id: Optional[str] = None
    filled_quantity: Decimal = Decimal("0")
    average_price: Optional[Decimal] = None
    reason_code: Optional[str] = None
    cumulative_commission: Optional[Decimal] = None

    @classmethod
    def accepted(cls, intent_id: str, provider_order_id: str):
        return cls(intent_id, _ExecutionState.ACKED, provider_order_id=provider_order_id)

    @classmethod
    def rejected(cls, intent_id: str, reason: str):
        return cls(intent_id, _ExecutionState.REJECTED, reason_code=reason)


class _ExecutionWithCumulativeFees(_Execution):
    ProviderObservation = _CumulativeProviderObservation


class _DurableFakeManagedRuntime:
    """A zero-I/O durable facade double with explicit replay behavior.

    It only emulates the small public facade contract consumed by
    ``ManagedExecutionBridge``.  The second submission of one intent returns
    the prior durable record without entering the provider dispatch callback.
    """

    def __init__(self) -> None:
        self.execution = _Execution
        self.scope = SimpleNamespace(
            strategy_id="fixture.managed.projection", environment="offline"
        )
        self.records: dict[str, object] = {}

    def submit(self, intent: _Intent, dispatch: Any) -> object:
        existing = self.records.get(intent.intent_id)
        if existing is not None:
            return existing
        try:
            observation = dispatch(intent)
        except ManagedExecutionBindingError as error:
            # The real facade turns ambiguous provider evidence into a durable
            # UNKNOWN record and never asks the Store to submit again.
            record = SimpleNamespace(
                state=SimpleNamespace(value="UNKNOWN"),
                provider_order_id=None,
                filled_quantity=Decimal("0"),
                average_price=None,
                unknown_reason=str(error),
            )
        else:
            record = SimpleNamespace(
                state=observation.state,
                provider_order_id=observation.provider_order_id,
                filled_quantity=observation.filled_quantity,
                average_price=observation.average_price,
                unknown_reason=observation.reason_code,
            )
        self.records[intent.intent_id] = record
        return record


class _ProjectionEventRuntime(_DurableFakeManagedRuntime):
    """Small durable-shaped runtime for the Store-to-Broker event seam."""

    def __init__(self, state_directory: object) -> None:
        super().__init__()
        self.execution = _ExecutionWithCumulativeFees
        self.scope.key = "scope.fixture.managed.provider-events"
        self.state_directory = state_directory
        self.framework_projection_session_id = uuid.uuid4().hex
        self.journal_generation = "d" * 32
        self._source_sequence = 0
        self._outbox: list[object] = []
        self._source_observations: dict[str, _CumulativeProviderObservation] = {}
        runtime = self

        class _ExecutionStore:
            def assert_writer_lease(self, _scope: object, _lease: object) -> None:
                return None

            def journal_source_identity(self) -> dict[str, object]:
                return {
                    "generation_kind": "EXECUTION_JOURNAL",
                    "generation": runtime.journal_generation,
                    "epoch": 1,
                }

            def read_outbox(self, *, after_sequence=0, limit=100, scope=None):
                if scope is not runtime.scope:
                    raise AssertionError("the source reader must bind the exact execution scope")
                return tuple(event for event in runtime._outbox if event.sequence > after_sequence)[
                    :limit
                ]

        class _Facade:
            def acquire_writer_lease(self) -> object:
                return SimpleNamespace(fencing_token=1)

            def record_provider_observation_event(self, observation):
                return runtime._record_provider_event(observation)

        self.execution_store = _ExecutionStore()
        self.facade = _Facade()

    def _record_provider_event(self, observation: _CumulativeProviderObservation):
        previous = self._source_observations.get(observation.intent_id)
        if previous == observation:
            return None
        if previous is not None and previous.cumulative_commission is None:
            event_type = "provider_commission_evidence"
        else:
            event_type = "reconciled_observation"
        self._source_sequence += 1
        self._source_observations[observation.intent_id] = observation
        event = SimpleNamespace(
            sequence=self._source_sequence,
            event_id="source-event." + str(self._source_sequence),
            intent_id=observation.intent_id,
            scope_key=self.scope.key,
            event_type=event_type,
            state=observation.state,
            created_at_ns=1_900_000_000_000_000_000 + self._source_sequence,
            journal_incarnation_id=self.journal_generation,
            payload={
                "provider_order_id": observation.provider_order_id,
                "filled_quantity": format(observation.filled_quantity, "f"),
                "average_price": (
                    None
                    if observation.average_price is None
                    else format(observation.average_price, "f")
                ),
                "cumulative_commission": (
                    None
                    if observation.cumulative_commission is None
                    else format(observation.cumulative_commission, "f")
                ),
                **({} if event_type == "provider_commission_evidence" else {"reason_code": None}),
                "source": "reconcile",
            },
        )
        self._outbox.append(event)
        return event


class _ResponseProvider(FakeBtApiClient):
    """Fake provider that returns exactly one reviewed result per dispatch."""

    def __init__(self, responses: list[dict[str, object]]) -> None:
        super().__init__(
            balance={"cash": 1000.0, "value": 1000.0},
            history={
                DEFAULT_SYMBOL: [
                    make_bar(0, 100.0, 102.0, 99.0, 101.0),
                    make_bar(1, 101.0, 103.0, 100.0, 102.0),
                ]
            },
        )
        self._responses = list(responses)
        self.balance_reads = 0

    def get_balance(self) -> dict[str, float]:
        self.balance_reads += 1
        return super().get_balance()

    def submit_order(self, payload: dict[str, object]) -> dict[str, object]:
        self.submitted_orders.append(dict(payload))
        if not self._responses:
            raise AssertionError("fake provider received an unexpected second dispatch")
        return dict(self._responses.pop(0))


class _ManagedCancelProjectionAdapter:
    """Use the real submit bridge and a durable-shaped cancel projection fake."""

    def __init__(self, runtime: _DurableFakeManagedRuntime, state: str) -> None:
        self._submit_bridge = ManagedExecutionBridge(runtime)
        self._state = state
        self.cancel_calls: list[tuple[object, object]] = []

    def submit_order(self, order: object, legacy_dispatch: Any) -> object:
        return self._submit_bridge.submit_order(order, legacy_dispatch)

    def cancel_order(self, order: object, dataname: object, _legacy_dispatch: Any) -> object:
        self.cancel_calls.append((order, dataname))
        return project_cancel_record_to_store_response(
            SimpleNamespace(
                state=SimpleNamespace(value=self._state),
                provider_order_id=getattr(order, "info", {}).get("external_order_id"),
                unknown_reason="fixture_cancel_outcome_unknown",
            ),
            provider_response=None,
        )


@pytest.mark.parametrize(
    "state",
    (CtpManagedProjectionState.PENDING, CtpManagedProjectionState.UNKNOWN),
)
def test_ctp_durable_projection_stays_nonterminal_until_provider_facts(state) -> None:
    """A typed outbox claim cannot accept an order or project an immediate fill."""

    provider = _ResponseProvider([])
    adapter = _CtpDurableProjectionAdapter(state)
    _store, data, broker = _make_started_stack(
        _DurableFakeManagedRuntime(), provider, managed_execution_adapter=adapter
    )
    try:
        order = _submit(broker, data, "intent.store-projection." + state.value.lower())

        assert order.status == bt.Order.Submitted
        assert order.alive() is True
        assert order.executed.size == pytest.approx(0.0)
        assert order.info["managed_execution_projection_state"] == state.value
        assert order.info.get("execution_unknown", False) is (
            state is CtpManagedProjectionState.UNKNOWN
        )
        assert adapter.submit_calls == 1
        assert provider.submitted_orders == []

        assert broker.cancel(order) is order
        assert order.status == bt.Order.Submitted
        assert order.alive() is True
        assert order.executed.size == pytest.approx(0.0)
        assert order.info["managed_execution_cancel_state"] == state.value
        assert order.info["managed_execution_cancel_pending"] is True
        assert adapter.cancel_calls == 1
        assert provider.submitted_orders == []
        assert broker.cancel(order) is order
        assert adapter.cancel_calls == 1
    finally:
        broker.stop()


def test_local_rejected_cancel_projection_keeps_order_live_without_retry() -> None:
    provider = _ResponseProvider([])
    adapter = _CtpDurableProjectionAdapter(
        CtpManagedProjectionState.PENDING,
        cancel_state=CtpManagedProjectionState.LOCAL_REJECTED,
    )
    _store, data, broker = _make_started_stack(
        _DurableFakeManagedRuntime(), provider, managed_execution_adapter=adapter
    )
    try:
        order = _submit(broker, data, "intent.store-projection.cancel-rejected")
        assert order.status == bt.Order.Submitted

        assert broker.cancel(order) is order

        assert order.status == bt.Order.Submitted
        assert order.alive() is True
        assert order.info["managed_execution_cancel_state"] == "LOCAL_REJECTED"
        assert order.info["managed_execution_cancel_pending"] is False
        assert order.info["cancel_requested_remote"] is False
        assert adapter.cancel_calls == 1
        assert provider.submitted_orders == []
    finally:
        broker.stop()


@pytest.mark.parametrize(
    ("state", "expected_status", "expected_unknown"),
    (
        ("LOCAL_REJECTED", bt.Order.Rejected, False),
        ("UNKNOWN", bt.Order.Submitted, True),
    ),
)
def test_managed_submit_handoff_failure_never_projects_provider_acceptance(
    state: str, expected_status: int, expected_unknown: bool
) -> None:
    provider = _ResponseProvider([])
    _store, data, broker = _make_started_stack(
        _DurableFakeManagedRuntime(),
        provider,
        managed_execution_adapter=_CtpDurableProjectionAdapter(CtpManagedProjectionState.PENDING),
    )
    try:
        # Exercise the SDK-mode Broker branch with the same typed failure the
        # CTP Store raises when its adapter cannot return a durable projection.
        broker.store._sdk_mode = True

        def fail_submit(_order: object) -> None:
            raise ManagedCtpHandoffError(
                "offline fixture handoff failure",
                code="managed_ctp_submit_handoff_unknown",
                state=state,
            )

        broker.store.submit_order = fail_submit
        order = _submit(broker, data, "intent.handoff." + state.lower())

        assert order.status == expected_status
        assert order.executed.size == pytest.approx(0.0)
        assert order.info.get("execution_unknown", False) is expected_unknown
        assert provider.submitted_orders == []
    finally:
        broker.stop()


def test_managed_cancel_handoff_unknown_stays_live_without_duplicate_dispatch() -> None:
    provider = _ResponseProvider([])
    store, data, broker = _make_started_stack(
        _DurableFakeManagedRuntime(),
        provider,
        managed_execution_adapter=_CtpDurableProjectionAdapter(CtpManagedProjectionState.PENDING),
    )
    try:
        order = _submit(broker, data, "intent.cancel-handoff")
        assert order.status == bt.Order.Submitted
        store._sdk_mode = True
        cancel_calls = []

        def fail_cancel(_order: object) -> None:
            cancel_calls.append(_order)
            raise ManagedCtpHandoffError(
                "offline fixture cancellation handoff failure",
                code="managed_ctp_cancel_handoff_unknown",
                state="UNKNOWN",
            )

        store.cancel_order = fail_cancel
        assert broker.cancel(order) is order
        assert order.status == bt.Order.Submitted
        assert order.alive() is True
        assert order.info["managed_execution_cancel_pending"] is True
        assert order.info["execution_unknown"] is True
        assert broker.cancel(order) is order
        assert len(cancel_calls) == 1
        assert provider.submitted_orders == []
    finally:
        broker.stop()


class _CtpDurableProjectionAdapter:
    """Return only offline durable pending projections, with no provider call."""

    def __init__(
        self,
        state: CtpManagedProjectionState,
        *,
        cancel_state: Optional[CtpManagedProjectionState] = None,
    ) -> None:
        self.state = state
        self.cancel_state = cancel_state or state
        self.submit_calls = 0
        self.cancel_calls = 0

    def submit_order(self, order: object, _dispatch: Any) -> dict[str, Any]:
        self.submit_calls += 1
        intent_id = order.info["managed_intent_id"]
        error_code = (
            "local_submit_rejected"
            if self.state is CtpManagedProjectionState.LOCAL_REJECTED
            else None
        )
        return CtpManagedExecutionProjection(
            operation="submit",
            state=self.state,
            durable_projection_id="outbox:submit:" + intent_id,
            managed_intent_id=intent_id,
            runtime_order_id="bt-managed-v1:" + ("a" * 64),
            error_code=error_code,
        ).to_store_response()

    def cancel_order(self, order: object, _dataname: object, _dispatch: Any) -> dict[str, Any]:
        self.cancel_calls += 1
        intent_id = order.info["managed_intent_id"]
        state = self.cancel_state
        error_code = None
        if state is CtpManagedProjectionState.LOCAL_REJECTED:
            error_code = "local_cancel_rejected"
        return CtpManagedExecutionProjection(
            operation="cancel",
            state=state,
            durable_projection_id="outbox:cancel:" + intent_id,
            managed_intent_id=intent_id,
            runtime_order_id="bt-managed-v1:" + ("a" * 64),
            managed_cancel_intent_id="cancel." + intent_id,
            error_code=error_code,
        ).to_store_response()


def _managed_info(intent_id: str) -> dict[str, Any]:
    return {
        "managed_order_type": "LIMIT",
        "managed_intent_id": intent_id,
        "managed_signal_id": "signal." + intent_id,
        "managed_instrument": DEFAULT_SYMBOL,
        "managed_position_effect": "OPEN",
        "managed_metadata_version": "fixture.metadata.v1",
        "managed_instrument_metadata_digest": "a" * 64,
        "offset": "open",
        "reduce_only": False,
    }


def _make_started_stack(
    runtime: _DurableFakeManagedRuntime,
    provider: _ResponseProvider,
    *,
    account_cache_ttl: float = 3600.0,
    account_refresh_interval: float = 3600.0,
    managed_execution_adapter: Optional[object] = None,
):
    store = make_store(
        api=provider,
        account_cache_ttl=account_cache_ttl,
        managed_execution_adapter=(
            ManagedExecutionBridge(runtime)
            if managed_execution_adapter is None
            else managed_execution_adapter
        ),
    )
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    data._start()
    assert data.load() is True
    broker = store.getbroker(
        validation_enabled=False,
        cash_check_enabled=False,
        account_refresh_interval=account_refresh_interval,
        positions_refresh_interval=3600.0,
        open_orders_refresh_interval=3600.0,
    )
    broker.start()
    return store, data, broker


def _submit(broker: object, data: object, intent_id: str):
    return broker.buy(
        owner=None,
        data=data,
        size=2,
        price=101.0,
        exectype=bt.Order.Limit,
        **_managed_info(intent_id),
    )


def _cumulative_provider_observation(runtime, intent, update):
    state_by_status = {
        "accepted": _ExecutionState.ACKED,
        "partial": _ExecutionState.PARTIALLY_FILLED,
        "completed": _ExecutionState.FILLED,
        "rejected": _ExecutionState.REJECTED,
    }
    status = str(update.get("status") or "").lower()
    if status not in state_by_status:
        raise ManagedExecutionBindingError("fixture update status is unsupported")
    raw_quantity = update.get("filled", "0")
    raw_average = update.get("avg_price")
    raw_commission = update.get("cumulative_commission")
    return runtime.execution.ProviderObservation(
        intent_id=intent.intent_id,
        state=state_by_status[status],
        provider_order_id=update.get("id"),
        filled_quantity=Decimal(str(raw_quantity)),
        average_price=None if raw_average is None else Decimal(str(raw_average)),
        reason_code=update.get("reason_code"),
        cumulative_commission=(None if raw_commission is None else Decimal(str(raw_commission))),
    )


def _make_provider_event_stack(
    tmp_path,
    intent_id="intent.provider-events",
    responses=None,
):
    runtime = _ProjectionEventRuntime(tmp_path)
    provider = _ResponseProvider(
        responses or [{"status": "accepted", "id": "provider.event-fixture"}]
    )
    bridge = ManagedExecutionBridge(
        runtime,
        provider_observation_from_update=_cumulative_provider_observation,
    )
    store, data, broker = _make_started_stack(runtime, provider, managed_execution_adapter=bridge)
    order = _submit(broker, data, intent_id)
    return runtime, provider, store, data, broker, order


def _push_cumulative_update(
    provider,
    order,
    *,
    status="partial",
    quantity,
    average,
    commission,
    provider_order_id="provider.event-fixture",
):
    provider.push_broker_update(
        {
            "kind": "order",
            "bt_order_ref": order.ref,
            "data_name": DEFAULT_SYMBOL,
            "side": "buy",
            "status": status,
            "id": provider_order_id,
            "filled": str(quantity),
            "avg_price": None if average is None else str(average),
            "cumulative_commission": None if commission is None else str(commission),
        }
    )


@pytest.mark.parametrize(
    (
        "provider_response",
        "expected_status",
        "expected_executed",
        "expected_commission",
        "expected_unknown",
    ),
    (
        ({"status": "accepted", "id": "managed.acked"}, bt.Order.Accepted, 0.0, 0.0, False),
        (
            {
                "status": "partial",
                "id": "managed.partial",
                "filled_quantity": "1",
                "average_price": "101.5",
                "cumulative_commission": "0.25",
            },
            bt.Order.Partial,
            1.0,
            0.25,
            False,
        ),
        (
            {
                "status": "filled",
                "id": "managed.filled",
                "filled_quantity": "2",
                "average_price": "101.5",
                "cumulative_commission": "0.50",
            },
            bt.Order.Completed,
            2.0,
            0.50,
            False,
        ),
        (
            {"status": "rejected", "reason": "fixture_rejected"},
            bt.Order.Rejected,
            0.0,
            0.0,
            False,
        ),
        # No provider identity is unconfirmed evidence.  It must remain a live
        # framework order with the UNKNOWN latch, rather than becoming a fill.
        ({"status": "accepted"}, bt.Order.Accepted, 0.0, 0.0, True),
        # A managed fill cannot use a local commission-rate estimate in place
        # of an exact cumulative provider fee fact.
        (
            {
                "status": "filled",
                "id": "managed.missing-fee",
                "filled_quantity": "2",
                "average_price": "101.5",
            },
            bt.Order.Accepted,
            0.0,
            0.0,
            True,
        ),
    ),
)
def test_first_managed_provider_result_projects_only_confirmed_fill_facts(
    provider_response: dict[str, object],
    expected_status: int,
    expected_executed: float,
    expected_commission: float,
    expected_unknown: bool,
) -> None:
    runtime = _DurableFakeManagedRuntime()
    provider = _ResponseProvider([provider_response])
    store, data, broker = _make_started_stack(runtime, provider)
    try:
        order = _submit(broker, data, "intent.first")

        assert store.managed_execution_active is True
        assert len(provider.submitted_orders) == 1
        assert provider.submitted_orders[0] == {
            "symbol": DEFAULT_SYMBOL,
            "data_name": DEFAULT_SYMBOL,
            "bt_order_ref": order.ref,
            "side": "buy",
            "size": 2,
            "price": 101.0,
            "order_type": "limit",
            "valid": None,
            "tradeid": 0,
            "offset": "open",
            "reduce_only": False,
            "position_mode": "net",
        }
        assert order.status == expected_status
        assert order.executed.size == pytest.approx(expected_executed)
        assert order.executed.comm == pytest.approx(expected_commission)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(expected_executed)
        # A fill receipt is not an account snapshot.  The live broker keeps the
        # independently observed balance rather than inventing cash from a
        # provider-specific margin/settlement model.
        assert broker.getcash() == pytest.approx(1000.0)

        if expected_executed:
            assert order.executed.price == pytest.approx(101.5)
        else:
            assert order.executed.price == pytest.approx(0.0)
        if expected_unknown:
            assert order.info["execution_unknown"] is True
        else:
            assert not order.info.get("execution_unknown", False)
    finally:
        broker.stop()


def test_managed_fill_reads_cash_only_from_a_following_provider_account_snapshot() -> None:
    """Cash stays an account fact instead of a guessed fill-accounting result."""

    runtime = _DurableFakeManagedRuntime()
    provider = _ResponseProvider(
        [
            {
                "status": "filled",
                "id": "managed.cash",
                "filled_quantity": "2",
                "average_price": "101.5",
                "cumulative_commission": "0.50",
            }
        ]
    )
    _store, data, broker = _make_started_stack(
        runtime,
        provider,
        account_cache_ttl=0.0,
        account_refresh_interval=0.0,
    )
    try:
        order = _submit(broker, data, "intent.cash")
        assert order.status == bt.Order.Completed
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(2.0)

        # A fake, independently-read account snapshot is the sole authority
        # for cash/value after a managed fill.  No order-response field can
        # modify these values, which avoids inventing margin or settlement
        # semantics in the framework adapter.
        provider.balance = {"cash": 799.50, "value": 1002.50}
        assert broker.getcash() == pytest.approx(799.50)
        assert broker.getvalue() == pytest.approx(1002.50)
        assert provider.balance_reads >= 2
    finally:
        broker.stop()


def test_managed_cancel_ack_keeps_mapping_for_a_late_authoritative_fill() -> None:
    """An ACK is dispatch evidence, not local cancellation authority."""

    runtime = _DurableFakeManagedRuntime()
    provider = _ResponseProvider([{"status": "accepted", "id": "managed.cancel.ack"}])
    adapter = _ManagedCancelProjectionAdapter(runtime, "ACKED")
    _store, data, broker = _make_started_stack(runtime, provider, managed_execution_adapter=adapter)
    try:
        order = _submit(broker, data, "intent.cancel.ack")
        assert order.status == bt.Order.Accepted
        assert broker._orders_by_external_id["managed.cancel.ack"] is order

        assert broker.cancel(order) is order
        assert broker.cancel(order) is order

        assert len(adapter.cancel_calls) == 1
        assert order.status == bt.Order.Accepted
        assert order.alive() is True
        assert order.info["managed_execution_cancel_state"] == "ACKED"
        assert order.info["managed_execution_cancel_pending"] is True
        assert order.info["managed_execution_cancel_reconciliation_required"] is True
        assert order.info["cancel_requested_remote"] is True
        assert broker._orders_by_external_id["managed.cancel.ack"] is order

        # A fill that crossed the provider cancellation command remains bound
        # to the original framework order and is booked exactly once.
        broker._apply_order_update(
            {
                "kind": "order",
                "external_order_id": "managed.cancel.ack",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "status": "completed",
                "filled": "2",
                "price": "101.5",
                "cumulative_commission": "0.50",
            }
        )

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(2.0)
        assert order.executed.comm == pytest.approx(0.50)
        assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(2.0)
        assert order.info["managed_execution_cancel_pending"] is False
        assert "managed.cancel.ack" not in broker._orders_by_external_id
    finally:
        broker.stop()


def test_managed_unknown_cancel_keeps_original_order_and_freeze_markers() -> None:
    """An unknown managed cancel cannot use the legacy local-cancel shortcut."""

    runtime = _DurableFakeManagedRuntime()
    provider = _ResponseProvider([{"status": "accepted", "id": "managed.cancel.unknown"}])
    adapter = _ManagedCancelProjectionAdapter(runtime, "UNKNOWN")
    _store, data, broker = _make_started_stack(runtime, provider, managed_execution_adapter=adapter)
    try:
        order = _submit(broker, data, "intent.cancel.unknown")
        assert broker.cancel(order) is order

        assert len(adapter.cancel_calls) == 1
        assert order.status == bt.Order.Accepted
        assert order.alive() is True
        assert order.info["execution_unknown"] is True
        assert order.info["cancel_execution_unknown"] is True
        assert order.info["managed_execution_cancel_freeze_required"] is True
        assert order.info["managed_execution_cancel_pending"] is True
        assert broker._orders_by_external_id["managed.cancel.unknown"] is order
    finally:
        broker.stop()


def test_only_terminal_managed_cancel_clears_the_original_order_mapping() -> None:
    """The explicitly durable CANCELLED state is the sole local terminal path."""

    runtime = _DurableFakeManagedRuntime()
    provider = _ResponseProvider([{"status": "accepted", "id": "managed.cancel.terminal"}])
    adapter = _ManagedCancelProjectionAdapter(runtime, "CANCELLED")
    _store, data, broker = _make_started_stack(runtime, provider, managed_execution_adapter=adapter)
    try:
        order = _submit(broker, data, "intent.cancel.terminal")
        assert broker._orders_by_external_id["managed.cancel.terminal"] is order

        assert broker.cancel(order) is order

        assert len(adapter.cancel_calls) == 1
        assert order.status == bt.Order.Canceled
        assert order.alive() is False
        assert "managed.cancel.terminal" not in broker._orders_by_external_id
    finally:
        broker.stop()


def test_cancel_projection_marks_nonterminal_records_for_broker_preservation() -> None:
    """The bridge must not pass a permissive legacy ACK through unchanged."""

    ack = project_cancel_record_to_store_response(
        SimpleNamespace(state=SimpleNamespace(value="ACKED"), provider_order_id="provider.cancel"),
        {"status": "accepted", "id": "provider.cancel"},
    )
    unknown = project_cancel_record_to_store_response(
        SimpleNamespace(
            state=SimpleNamespace(value="UNKNOWN"),
            provider_order_id="provider.cancel",
            unknown_reason="fixture_unknown",
        ),
        None,
    )
    terminal = project_cancel_record_to_store_response(
        SimpleNamespace(
            state=SimpleNamespace(value="CANCELLED"), provider_order_id="provider.cancel"
        ),
        {"status": "accepted", "id": "provider.cancel"},
    )

    assert ack["status"] == "cancel_requested"
    assert ack["managed_execution_cancel_pending"] is True
    assert ack["managed_execution_cancel_reconciliation_required"] is True
    assert unknown["execution_unknown"] is True
    assert unknown["managed_execution_cancel_pending"] is True
    assert unknown["managed_execution_cancel_freeze_required"] is True
    assert terminal["status"] == "cancelled"


@pytest.mark.parametrize(
    ("response", "expected_status", "expected_size", "expected_commission"),
    (
        (
            {
                "status": "partial",
                "id": "managed.restart.partial",
                "filled_quantity": "1",
                "average_price": "101.5",
                "cumulative_commission": "0.25",
            },
            bt.Order.Partial,
            1.0,
            0.25,
        ),
        (
            {
                "status": "filled",
                "id": "managed.restart.filled",
                "filled_quantity": "2",
                "average_price": "101.5",
                "cumulative_commission": "0.50",
            },
            bt.Order.Completed,
            2.0,
            0.50,
        ),
    ),
)
def test_replayed_managed_fill_is_rejected_before_a_second_framework_projection(
    response: dict[str, object],
    expected_status: int,
    expected_size: float,
    expected_commission: float,
) -> None:
    """A restart cannot replay a durable partial/full fill without a recovery receipt.

    This fixture's execution journal has no private Backtrader-order receipt,
    commission currency conversion, or authoritative restored position/cash
    state.  Rejecting its new framework order is therefore the strongest safe
    behavior: it cannot double book a partial or full position, nor fabricate
    a fee from a local rate.
    """

    runtime = _DurableFakeManagedRuntime()
    provider = _ResponseProvider([response])
    _store, first_data, first_broker = _make_started_stack(runtime, provider)
    try:
        first = _submit(first_broker, first_data, "intent.restart")
        assert first.status == expected_status
        assert first.executed.size == pytest.approx(expected_size)
        assert first.executed.comm == pytest.approx(expected_commission)
        assert first_broker.positions[DEFAULT_SYMBOL].size == pytest.approx(expected_size)
    finally:
        first_broker.stop()

    _store, restarted_data, restarted_broker = _make_started_stack(runtime, provider)
    try:
        replayed = _submit(restarted_broker, restarted_data, "intent.restart")

        assert len(provider.submitted_orders) == 1
        assert replayed.status == bt.Order.Rejected
        assert replayed.executed.size == pytest.approx(0.0)
        assert replayed.executed.comm == pytest.approx(0.0)
        assert replayed.info["error_code"] == "managed_execution_projection_replay_blocked"
        assert restarted_broker.positions[DEFAULT_SYMBOL].size == pytest.approx(0.0)
        assert restarted_broker.getcash() == pytest.approx(1000.0)
    finally:
        restarted_broker.stop()


def test_replayed_managed_unknown_is_rejected_without_a_second_provider_attempt() -> None:
    """A restarted framework order cannot take ownership of an UNKNOWN attempt."""

    runtime = _DurableFakeManagedRuntime()
    provider = _ResponseProvider([{"status": "accepted"}])
    _store, first_data, first_broker = _make_started_stack(runtime, provider)
    try:
        first = _submit(first_broker, first_data, "intent.unknown-restart")
        assert first.status == bt.Order.Accepted
        assert first.info["execution_unknown"] is True
    finally:
        first_broker.stop()

    _store, restarted_data, restarted_broker = _make_started_stack(runtime, provider)
    try:
        replayed = _submit(restarted_broker, restarted_data, "intent.unknown-restart")

        assert len(provider.submitted_orders) == 1
        assert replayed.status == bt.Order.Rejected
        assert replayed.executed.size == pytest.approx(0.0)
        assert replayed.info["error_code"] == "managed_execution_projection_replay_blocked"
    finally:
        restarted_broker.stop()


def test_trade_logger_records_first_managed_fill_once_without_external_io(tmp_path) -> None:
    """The genuine observer sees the same completed order/commission facts."""

    runtime = _DurableFakeManagedRuntime()
    provider = _ResponseProvider(
        [
            {
                "status": "filled",
                "id": "managed.trade-logger",
                "filled_quantity": "2",
                "average_price": "101.5",
                "cumulative_commission": "0.50",
            }
        ]
    )
    store = make_store(api=provider, managed_execution_adapter=ManagedExecutionBridge(runtime))
    data = bt.feeds.PandasData(
        dataname=pd.DataFrame(
            {
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [1.0, 1.0],
                "openinterest": [0.0, 0.0],
            },
            index=[dt.datetime(2024, 1, 1), dt.datetime(2024, 1, 2)],
        )
    )
    broker = store.getbroker(
        validation_enabled=False,
        cash_check_enabled=False,
        account_refresh_interval=3600.0,
        positions_refresh_interval=3600.0,
        open_orders_refresh_interval=3600.0,
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False)

    class _Strategy(bt.Strategy):
        def next(self) -> None:
            if len(self) == 1:
                self.order = self.buy(
                    data=self.datas[0],
                    size=2,
                    price=101.0,
                    exectype=bt.Order.Limit,
                    **_managed_info("intent.trade-logger"),
                )
            elif len(self) == 2:
                self.cerebro.runstop()

    cerebro.setbroker(broker)
    cerebro.adddata(data, name=DEFAULT_SYMBOL)
    cerebro.addstrategy(_Strategy)
    cerebro.addobserver(
        bt.observers.TradeLogger,
        obsname="trade_logger",
        log_dir=str(tmp_path),
        log_format="json",
        log_orders=False,
        log_trades=False,
        log_positions=False,
        log_indicators=False,
        log_signals=False,
        log_ticks=False,
        log_bars=False,
        log_position_snapshot=False,
        report_max_records=20,
    )

    results = cerebro.run()
    strategy = results[0]
    report = strategy.stats.trade_logger.final_report()

    assert len(provider.submitted_orders) == 1
    assert strategy.order.status == bt.Order.Completed
    assert strategy.order.executed.size == pytest.approx(2.0)
    assert strategy.order.executed.comm == pytest.approx(0.50)
    assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(2.0)
    assert report is not None
    completed = [item for item in report["order_summaries"] if item["status"] == "Completed"]
    assert len(completed) == 1
    assert completed[0]["executed_size"] == pytest.approx(2.0)
    assert completed[0]["executed_price"] == pytest.approx(101.5)
    assert completed[0]["commission"] == pytest.approx(0.50)


def test_durable_outbox_projects_cumulative_deltas_once_and_preserves_cash(tmp_path) -> None:
    runtime, provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    try:
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(100.0)
        assert order.executed.comm == pytest.approx(0.05)

        _push_cumulative_update(
            provider,
            order,
            status="completed",
            quantity="2",
            average="110",
            commission="0.11",
        )
        broker._drain_store_updates()

        assert order.status == bt.Order.Completed
        assert order.executed.size == pytest.approx(2.0)
        assert order.executed.price == pytest.approx(110.0)
        assert order.executed.comm == pytest.approx(0.11)
        assert [bit.size for bit in order.executed.exbits] == pytest.approx([1.0, 1.0])
        assert [bit.price for bit in order.executed.exbits] == pytest.approx([100.0, 120.0])
        assert [bit.comm for bit in order.executed.exbits] == pytest.approx([0.05, 0.06])
        assert broker.getcash() == pytest.approx(1000.0)
        assert runtime._source_sequence == 2

        # An exact raw callback retry returns no newly appended event and the
        # already-applied durable cursor prevents a second Broker booking.
        _push_cumulative_update(
            provider,
            order,
            status="completed",
            quantity="2",
            average="110",
            commission="0.11",
        )
        broker._drain_store_updates()
        assert len(order.executed.exbits) == 2
        assert order.executed.comm == pytest.approx(0.11)
        assert runtime._source_sequence == 2
    finally:
        broker.stop()


@pytest.mark.parametrize(
    (
        "first_quantity",
        "first_average",
        "first_commission",
        "next_quantity",
        "next_average",
        "next_commission",
        "expected_incremental_price",
        "expected_incremental_commission",
    ),
    (
        ("1", "0.1", "0.01", "3", "0.2", "0.03", 0.25, 0.02),
        ("1", "100", "0.1", "2", "100", "-0.3", 100.0, -0.4),
        ("1", "100", "1", "2", "100", "1.01", 100.0, 0.01),
        ("1", "100", "100", "2", "100", "100.01", 100.0, 0.01),
    ),
)
def test_binary64_rounding_projects_cumulative_average_and_signed_fee(
    tmp_path,
    first_quantity,
    first_average,
    first_commission,
    next_quantity,
    next_average,
    next_commission,
    expected_incremental_price,
    expected_incremental_commission,
) -> None:
    runtime = _ProjectionEventRuntime(tmp_path)
    provider = _ResponseProvider(
        [
            {"status": "accepted", "id": "provider.float-rounding-1"},
            {"status": "accepted", "id": "provider.float-rounding-2"},
        ]
    )
    bridge = ManagedExecutionBridge(
        runtime,
        provider_observation_from_update=_cumulative_provider_observation,
    )
    _store, data, broker = _make_started_stack(runtime, provider, managed_execution_adapter=bridge)
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=4,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_info("intent.float-rounding"),
        )
        for quantity, average, commission, state in (
            (
                first_quantity,
                first_average,
                first_commission,
                _ExecutionState.PARTIALLY_FILLED,
            ),
            (
                next_quantity,
                next_average,
                next_commission,
                _ExecutionState.PARTIALLY_FILLED,
            ),
        ):
            runtime._record_provider_event(
                _CumulativeProviderObservation(
                    intent_id="intent.float-rounding",
                    state=state,
                    provider_order_id="provider.float-rounding-1",
                    filled_quantity=Decimal(quantity),
                    average_price=Decimal(average),
                    cumulative_commission=Decimal(commission),
                )
            )
            broker._drain_store_updates()

        assert order.executed.size == pytest.approx(float(next_quantity))
        assert order.executed.price == pytest.approx(float(next_average), abs=1e-15)
        assert order.executed.comm == pytest.approx(float(next_commission), abs=1e-15)
        assert order.executed.exbits[-1].price == expected_incremental_price
        assert order.executed.exbits[-1].comm == expected_incremental_commission
        assert order.info.get("execution_unknown", False) is False
        assert bridge._source_projection_blocked is False
        journal = bridge._framework_projection_journal
        assert (
            journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 2
        )

        next_order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
            **_managed_info("intent.after-float-rounding"),
        )
        runtime._record_provider_event(
            _CumulativeProviderObservation(
                intent_id="intent.after-float-rounding",
                state=_ExecutionState.ACKED,
                provider_order_id="provider.float-rounding-2",
                filled_quantity=Decimal("0"),
                average_price=None,
                cumulative_commission=Decimal("0"),
            )
        )
        broker._drain_store_updates()
        assert next_order.status == bt.Order.Accepted
        assert next_order.executed.size == pytest.approx(0.0)
        assert bridge._source_projection_blocked is False
        assert (
            journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 3
        )
    finally:
        broker.stop()
        bridge.close()


def _raw_source_high_water(journal, runtime) -> int:
    row = journal._connection.execute(
        """
        SELECT high_water_sequence
        FROM framework_projection_source_streams
        WHERE scope_key = ? AND journal_incarnation_id = ? AND session_id = ?
        """,
        (
            runtime.scope.key,
            runtime.journal_generation,
            runtime.framework_projection_session_id,
        ),
    ).fetchone()
    return 0 if row is None else int(row["high_water_sequence"])


def test_fractional_cumulative_quantity_and_nonterminating_average_allow_same_qty_cancel(
    tmp_path,
) -> None:
    runtime = _ProjectionEventRuntime(tmp_path)
    provider = _ResponseProvider([{"status": "accepted", "id": "provider.fractional"}])
    bridge = ManagedExecutionBridge(
        runtime,
        provider_observation_from_update=_cumulative_provider_observation,
    )
    _store, data, broker = _make_started_stack(runtime, provider, managed_execution_adapter=bridge)
    order = broker.buy(
        owner=None,
        data=data,
        size=1,
        price=101.0,
        exectype=bt.Order.Limit,
        **_managed_info("intent.fractional-checkpoint"),
    )
    quantity = Decimal("0.3333333333333333333333333333")
    average = Decimal("100.3333333333333333333333333")
    commission = Decimal("0.1")
    try:
        for state in (_ExecutionState.PARTIALLY_FILLED, _ExecutionState.CANCELLED):
            runtime._record_provider_event(
                _CumulativeProviderObservation(
                    intent_id="intent.fractional-checkpoint",
                    state=state,
                    provider_order_id="provider.event-fixture",
                    filled_quantity=quantity,
                    average_price=average,
                    cumulative_commission=commission,
                )
            )
            broker._drain_store_updates()

        assert order.status == bt.Order.Canceled
        assert order.executed.size == pytest.approx(float(quantity))
        assert order.executed.price == pytest.approx(float(average))
        assert order.executed.comm == pytest.approx(float(commission))
        assert len(order.executed.exbits) == 1
        assert bridge._source_projection_blocked is False
        journal = bridge._framework_projection_journal
        assert (
            journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 2
        )
    finally:
        broker.stop()


def test_large_cumulative_quantity_projects_exact_decimal_notional_delta(tmp_path) -> None:
    runtime = _ProjectionEventRuntime(tmp_path)
    provider = _ResponseProvider([{"status": "accepted", "id": "provider.large-qty"}])
    bridge = ManagedExecutionBridge(
        runtime,
        provider_observation_from_update=_cumulative_provider_observation,
    )
    _store, data, broker = _make_started_stack(runtime, provider, managed_execution_adapter=bridge)
    order = broker.buy(
        owner=None,
        data=data,
        size=2_000_000_000_000_000,
        price=1.0,
        exectype=bt.Order.Limit,
        **_managed_info("intent.large-quantity"),
    )
    try:
        for quantity, average, commission in (
            ("1000000000000000", "1", "0.1"),
            ("1000000000000001", "1.0000000000000001", "0.2"),
        ):
            runtime._record_provider_event(
                _CumulativeProviderObservation(
                    intent_id="intent.large-quantity",
                    state=_ExecutionState.PARTIALLY_FILLED,
                    provider_order_id="provider.large-qty",
                    filled_quantity=Decimal(quantity),
                    average_price=Decimal(average),
                    cumulative_commission=Decimal(commission),
                )
            )
            broker._drain_store_updates()

        assert order.executed.size == pytest.approx(1_000_000_000_000_001.0)
        assert len(order.executed.exbits) == 2
        assert order.executed.exbits[0].price == 1.0
        assert order.executed.exbits[1].size == 1.0
        assert order.executed.exbits[1].price == 1.1
        assert order.executed.exbits[1].comm == 0.1
        assert bridge._source_projection_blocked is False
        assert (
            bridge._framework_projection_journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 2
        )
    finally:
        broker.stop()


def test_large_cumulative_commission_projects_exact_small_fee_delta(tmp_path) -> None:
    runtime, provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    try:
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="1000000000000",
        )
        broker._drain_store_updates()
        _push_cumulative_update(
            provider,
            order,
            quantity="2",
            average="100",
            commission="1000000000000.0001",
        )
        broker._drain_store_updates()

        assert order.executed.size == pytest.approx(2.0)
        assert len(order.executed.exbits) == 2
        assert order.executed.exbits[1].comm == 0.0001
        assert bridge._source_projection_blocked is False
        assert _raw_source_high_water(bridge._framework_projection_journal, runtime) == 2
    finally:
        broker.stop()


def test_quantity_delta_below_broker_resolution_fences_before_booking(tmp_path) -> None:
    runtime, _provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    journal = bridge._framework_projection_journal
    try:
        _push_cumulative_update(
            _provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()
        assert order.executed.size == pytest.approx(1.0)
        assert len(order.executed.exbits) == 1

        _push_cumulative_update(
            _provider,
            order,
            quantity="1.0000000000005",
            average="100",
            commission="0.06",
        )
        broker._drain_store_updates()

        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.comm == pytest.approx(0.05)
        assert len(order.executed.exbits) == 1
        assert order.info["execution_unknown"] is True
        assert bridge._source_projection_blocked is True
        assert _raw_source_high_water(journal, runtime) == 1
    finally:
        broker.stop()


def test_tiny_fee_delta_stays_in_incremental_execution_bit(tmp_path) -> None:
    runtime, provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    try:
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()
        _push_cumulative_update(
            provider,
            order,
            quantity="1.5",
            average="100",
            commission="0.05000000000000000001",
        )
        broker._drain_store_updates()

        assert order.executed.size == pytest.approx(1.5)
        assert len(order.executed.exbits) == 2
        assert order.executed.exbits[1].comm == 1e-20
        assert bridge._source_projection_blocked is False
        assert _raw_source_high_water(bridge._framework_projection_journal, runtime) == 2
    finally:
        broker.stop()


def test_substantial_post_apply_fee_mismatch_fences_booked_fill(tmp_path) -> None:
    runtime, provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    journal = bridge._framework_projection_journal
    original_apply = broker._apply_order_update

    def apply_then_change_fee(update):
        result = original_apply(update)
        order.executed.comm += 0.01
        return result

    broker._apply_order_update = apply_then_change_fee
    try:
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()

        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.comm == pytest.approx(0.06)
        assert len(order.executed.exbits) == 1
        assert order.info["execution_unknown"] is True
        assert order.info["ledger_mismatch"] is True
        assert bridge._source_projection_blocked is True
        assert _raw_source_high_water(journal, runtime) == 0
    finally:
        broker.stop()


def test_substantial_post_apply_quantity_mismatch_fences_booked_fill(tmp_path) -> None:
    runtime, provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    journal = bridge._framework_projection_journal
    original_apply = broker._apply_order_update

    def apply_then_change_quantity(update):
        result = original_apply(update)
        order.executed.size += 0.25
        return result

    broker._apply_order_update = apply_then_change_quantity
    try:
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()

        assert order.executed.size == pytest.approx(1.25)
        assert len(order.executed.exbits) == 1
        assert order.info["execution_unknown"] is True
        assert order.info["ledger_mismatch"] is True
        assert bridge._source_projection_blocked is True
        assert _raw_source_high_water(journal, runtime) == 0
    finally:
        broker.stop()


def test_source_quantity_regression_fences_without_broker_mutation(tmp_path) -> None:
    runtime, _provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    journal = bridge._framework_projection_journal
    try:
        _push_cumulative_update(
            _provider,
            order,
            quantity="0.75",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()
        assert order.executed.size == pytest.approx(0.75)

        _push_cumulative_update(
            _provider,
            order,
            quantity="0.7",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()

        assert order.executed.size == pytest.approx(0.75)
        assert len(order.executed.exbits) == 1
        assert order.info["execution_unknown"] is True
        assert bridge._source_projection_blocked is True
        assert _raw_source_high_water(journal, runtime) == 1
    finally:
        broker.stop()


def test_same_quantity_commission_rebate_is_applied_as_signed_cumulative_delta(tmp_path) -> None:
    _runtime, provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    try:
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()
        _push_cumulative_update(
            provider,
            order,
            status="completed",
            quantity="2",
            average="110",
            commission="0.02",
        )
        broker._drain_store_updates()

        assert order.executed.comm == pytest.approx(0.02)
        assert [bit.comm for bit in order.executed.exbits] == pytest.approx([0.05, -0.03])
        assert [bit.price for bit in order.executed.exbits] == pytest.approx([100.0, 120.0])
    finally:
        broker.stop()


def test_missing_fee_stays_unknown_until_later_same_quantity_fee_event(tmp_path) -> None:
    runtime, provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    try:
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission=None,
        )
        broker._drain_store_updates()
        assert order.executed.size == pytest.approx(0.0)
        assert order.executed.comm == pytest.approx(0.0)
        assert order.info["execution_unknown"] is True

        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.comm == pytest.approx(0.05)
        assert len(order.executed.exbits) == 1
        assert runtime._source_sequence == 2
    finally:
        broker.stop()


def test_changed_fee_after_quantity_was_booked_fences_without_adjustment(tmp_path) -> None:
    _runtime, provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    try:
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.04",
        )
        broker._drain_store_updates()

        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.comm == pytest.approx(0.05)
        assert order.info["managed_provider_projection_blocked"] is True
        assert broker._managed_provider_projection_failed is True
    finally:
        broker.stop()


def test_source_event_committed_before_claim_replays_from_outbox_after_restart(tmp_path) -> None:
    runtime, provider, _store, _data, broker, first_order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    try:
        raw_update = {
            "kind": "order",
            "bt_order_ref": first_order.ref,
            "data_name": DEFAULT_SYMBOL,
            "side": "buy",
            "status": "partial",
            "id": "provider.event-fixture",
            "filled": "1",
            "avg_price": "100",
            "cumulative_commission": "0.05",
        }
        # The execution SQLite append succeeds, but the process stops before
        # the separate FrameworkProjectionJournal has any claim for it.
        assert bridge.prepare_managed_provider_projection(raw_update, first_order) is None
        assert runtime._source_sequence == 1
        assert first_order.executed.size == pytest.approx(0.0)
    finally:
        broker.stop()
        bridge.close()

    runtime.framework_projection_session_id = uuid.uuid4().hex
    restarted_bridge = ManagedExecutionBridge(
        runtime,
        provider_observation_from_update=_cumulative_provider_observation,
    )
    second_provider = _ResponseProvider([])
    _store, _data, restarted_broker = _make_started_stack(
        runtime, second_provider, managed_execution_adapter=restarted_bridge
    )
    try:
        recovered_order = _submit(restarted_broker, _data, "intent.provider-events")
        assert recovered_order.info["execution_unknown"] is True
        assert second_provider.submitted_orders == []

        restarted_broker._drain_store_updates()

        assert recovered_order.executed.size == pytest.approx(1.0)
        assert recovered_order.executed.price == pytest.approx(100.0)
        assert recovered_order.executed.comm == pytest.approx(0.05)
        assert len(recovered_order.executed.exbits) == 1
        assert getattr(restarted_broker, "_managed_provider_projection_failed", False) is False
    finally:
        restarted_broker.stop()
        restarted_bridge.close()


def test_outbox_recovery_rejects_unrecognized_journal_epoch(tmp_path) -> None:
    runtime, _provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    runtime.execution_store.journal_source_identity = lambda: {
        "generation_kind": "EXECUTION_JOURNAL",
        "generation": runtime.journal_generation,
        "epoch": 2,
    }
    try:
        with pytest.raises(ManagedExecutionBindingError, match="journal identity is invalid"):
            bridge.poll_managed_provider_outbox_update()

        assert bridge._source_projection_blocked is True
        assert order.executed.size == pytest.approx(0.0)
        with pytest.raises(FrameworkProjectionRecoveryError, match="fenced"):
            bridge._framework_projection_journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
    finally:
        broker.stop()
        bridge.close()


def test_outbox_read_failure_marks_pending_managed_order_unknown(tmp_path) -> None:
    runtime, _provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter

    def fail_read(**_kwargs):
        raise OSError("fixture sqlite outbox read failure")

    runtime.execution_store.read_outbox = fail_read
    try:
        broker._drain_store_updates()

        assert order.executed.size == pytest.approx(0.0)
        assert order.info["execution_unknown"] is True
        assert order.info["ledger_mismatch"] is True
        assert order.info["managed_provider_projection_blocked"] is True
        assert broker._managed_provider_projection_failed is True
        assert bridge._source_projection_blocked is True
    finally:
        broker.stop()


def test_post_apply_source_receipt_failure_fences_without_retrying_same_session(
    tmp_path,
) -> None:
    _runtime, provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    journal = bridge._framework_projection_journal

    def fail_complete(_claim):
        raise FrameworkProjectionRecoveryError("fixture post-apply sqlite commit failure")

    journal.complete_source_event = fail_complete
    try:
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()

        # Broker accounting happened before its separate local receipt could
        # commit. The session is marked UNKNOWN and cannot apply another event.
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.comm == pytest.approx(0.05)
        assert order.info["execution_unknown"] is True
        assert order.info["ledger_mismatch"] is True
        assert order.info["managed_provider_projection_blocked"] is True
        assert broker._managed_provider_projection_failed is True
        assert bridge._source_projection_blocked is True
    finally:
        broker.stop()


def test_active_outbox_event_id_payload_collision_fences_without_second_fill(tmp_path) -> None:
    runtime, _provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    try:
        first = runtime._record_provider_event(
            _CumulativeProviderObservation(
                intent_id="intent.provider-events",
                state=_ExecutionState.PARTIALLY_FILLED,
                provider_order_id="provider.event-fixture",
                filled_quantity=Decimal("1"),
                average_price=Decimal("100"),
                cumulative_commission=Decimal("0.05"),
            )
        )
        broker._drain_store_updates()
        assert order.executed.size == pytest.approx(1.0)

        conflicting = runtime._record_provider_event(
            _CumulativeProviderObservation(
                intent_id="intent.provider-events",
                state=_ExecutionState.FILLED,
                provider_order_id="provider.event-fixture",
                filled_quantity=Decimal("2"),
                average_price=Decimal("110"),
                cumulative_commission=Decimal("0.11"),
            )
        )
        conflicting.event_id = first.event_id
        broker._drain_store_updates()

        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.comm == pytest.approx(0.05)
        assert order.status == bt.Order.Partial
        assert order.info["execution_unknown"] is True
        assert order.info["managed_provider_projection_blocked"] is True
        assert broker._managed_provider_projection_failed is True
        assert bridge._source_projection_blocked is True
    finally:
        broker.stop()


def test_fresh_broker_rebuilds_ordered_events_instead_of_latest_record_values(tmp_path) -> None:
    runtime, _provider, _store, _data, broker, _order = _make_provider_event_stack(tmp_path)
    first_bridge = broker.store._managed_execution_adapter
    try:
        for observation in (
            _CumulativeProviderObservation(
                intent_id="intent.provider-events",
                state=_ExecutionState.ACKED,
                provider_order_id="provider.event-fixture",
                filled_quantity=Decimal("0"),
                average_price=None,
                cumulative_commission=Decimal("0"),
            ),
            _CumulativeProviderObservation(
                intent_id="intent.provider-events",
                state=_ExecutionState.PARTIALLY_FILLED,
                provider_order_id="provider.event-fixture",
                filled_quantity=Decimal("1"),
                average_price=Decimal("100"),
                cumulative_commission=Decimal("0.05"),
            ),
            _CumulativeProviderObservation(
                intent_id="intent.provider-events",
                state=_ExecutionState.FILLED,
                provider_order_id="provider.event-fixture",
                filled_quantity=Decimal("2"),
                average_price=Decimal("110"),
                cumulative_commission=Decimal("0.11"),
            ),
        ):
            runtime._record_provider_event(observation)

        # The current durable row is intentionally inconsistent with the
        # event-time snapshots. The recovery path must ignore it for fill math.
        runtime.records["intent.provider-events"] = SimpleNamespace(
            state=_ExecutionState.FILLED,
            provider_order_id="provider.event-fixture",
            filled_quantity=Decimal("2"),
            average_price=Decimal("999"),
            cumulative_commission=Decimal("9.99"),
            unknown_reason=None,
        )
    finally:
        broker.stop()
        first_bridge.close()

    runtime.framework_projection_session_id = uuid.uuid4().hex
    restarted_bridge = ManagedExecutionBridge(
        runtime,
        provider_observation_from_update=_cumulative_provider_observation,
    )
    second_provider = _ResponseProvider([])
    _store, data, restarted_broker = _make_started_stack(
        runtime, second_provider, managed_execution_adapter=restarted_bridge
    )
    try:
        recovered = _submit(restarted_broker, data, "intent.provider-events")
        assert recovered.executed.size == pytest.approx(0.0)
        restarted_broker._drain_store_updates()

        assert recovered.status == bt.Order.Completed
        assert recovered.executed.size == pytest.approx(2.0)
        assert recovered.executed.price == pytest.approx(110.0)
        assert recovered.executed.comm == pytest.approx(0.11)
        assert [bit.price for bit in recovered.executed.exbits] == pytest.approx([100.0, 120.0])
        assert [bit.comm for bit in recovered.executed.exbits] == pytest.approx([0.05, 0.06])
        assert len(recovered.executed.exbits) == 2
        assert second_provider.submitted_orders == []
        assert (
            restarted_bridge._framework_projection_journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 3
        )
    finally:
        restarted_broker.stop()
        restarted_bridge.close()


def test_unmaterialized_earlier_intent_holds_scope_cursor_and_later_fill(tmp_path) -> None:
    runtime, provider, _store, data, broker, order_b = _make_provider_event_stack(
        tmp_path,
        intent_id="intent.b",
        responses=[
            {"status": "accepted", "id": "provider.order.b"},
            {"status": "accepted", "id": "provider.order.a"},
        ],
    )
    try:
        runtime._record_provider_event(
            _CumulativeProviderObservation(
                intent_id="intent.a",
                state=_ExecutionState.PARTIALLY_FILLED,
                provider_order_id="provider.order.a",
                filled_quantity=Decimal("1"),
                average_price=Decimal("100"),
                cumulative_commission=Decimal("0.05"),
            )
        )
        runtime._record_provider_event(
            _CumulativeProviderObservation(
                intent_id="intent.b",
                state=_ExecutionState.PARTIALLY_FILLED,
                provider_order_id="provider.order.b",
                filled_quantity=Decimal("1"),
                average_price=Decimal("101"),
                cumulative_commission=Decimal("0.06"),
            )
        )
        journal = broker.store._managed_execution_adapter._framework_projection_journal
        assert (
            journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 0
        )

        # The first durable event belongs to an order not yet materialized in
        # this Broker. B cannot jump the global stream cursor and book its later
        # event out of order.
        broker._drain_store_updates()
        assert order_b.executed.size == pytest.approx(0.0)
        assert (
            journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 0
        )

        order_a = _submit(broker, data, "intent.a")
        broker._drain_store_updates()
        assert order_a.executed.size == pytest.approx(1.0)
        assert order_b.executed.size == pytest.approx(1.0)
        assert (
            journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 2
        )
        assert len(provider.submitted_orders) == 2
    finally:
        broker.stop()


def test_outbox_recovery_consumes_lifecycle_rows_then_recovers_after_raw_queue_loss(
    tmp_path,
) -> None:
    runtime, _provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    try:
        runtime._source_sequence = 1
        runtime._outbox.append(
            SimpleNamespace(
                sequence=1,
                event_id="event.intent-recorded",
                intent_id="intent.provider-events",
                scope_key=runtime.scope.key,
                event_type="intent_recorded",
                state="PENDING_ADMISSION",
                created_at_ns=1_900_000_000_000_000_001,
                journal_incarnation_id=runtime.journal_generation,
                payload={"payload_sha256": "c" * 64},
            )
        )
        runtime._record_provider_event(
            _CumulativeProviderObservation(
                intent_id="intent.provider-events",
                state=_ExecutionState.PARTIALLY_FILLED,
                provider_order_id="provider.event-fixture",
                filled_quantity=Decimal("1"),
                average_price=Decimal("100"),
                cumulative_commission=Decimal("0.05"),
            )
        )

        # No raw callback remains in the bounded Store queue. Recovery comes
        # only from the immutable scoped SQLite outbox.
        broker._drain_store_updates()

        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.price == pytest.approx(100.0)
        assert order.executed.comm == pytest.approx(0.05)
        assert (
            broker.store._managed_execution_adapter._framework_projection_journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 2
        )
    finally:
        broker.stop()


def test_no_fill_admission_and_dispatch_events_advance_before_next_fill(tmp_path) -> None:
    runtime, provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    try:
        for sequence, intent_id, event_type, state, payload in (
            (
                1,
                "intent.risk-rejected",
                "intent_rejected",
                "REJECTED",
                {"reason_code": "risk_denied"},
            ),
            (
                2,
                "intent.risk-blocked",
                "intent_blocked",
                "BLOCKED",
                {"reason_code": "risk_blocked"},
            ),
            (
                3,
                "intent.guard-blocked",
                "dispatch_claimed",
                "DISPATCHING",
                {"dispatch_attempt": 1},
            ),
            (
                4,
                "intent.guard-blocked",
                "dispatch_blocked",
                "BLOCKED",
                {"reason_code": "guard_blocked"},
            ),
        ):
            runtime._outbox.append(
                SimpleNamespace(
                    sequence=sequence,
                    event_id="event." + str(sequence),
                    intent_id=intent_id,
                    scope_key=runtime.scope.key,
                    event_type=event_type,
                    state=state,
                    created_at_ns=1_900_000_000_000_000_000 + sequence,
                    journal_incarnation_id=runtime.journal_generation,
                    payload=payload,
                )
            )
        runtime._source_sequence = 4
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )

        broker._drain_store_updates()

        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.comm == pytest.approx(0.05)
        assert (
            bridge._framework_projection_journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 5
        )
        assert bridge._source_projection_blocked is False
    finally:
        broker.stop()


def test_no_fill_lifecycle_event_with_economic_payload_fails_closed(tmp_path) -> None:
    runtime, _provider, _store, _data, broker, _order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    runtime._outbox.append(
        SimpleNamespace(
            sequence=1,
            event_id="event.intent-rejected-with-fill",
            intent_id="intent.risk-rejected",
            scope_key=runtime.scope.key,
            event_type="intent_rejected",
            state="REJECTED",
            created_at_ns=1_900_000_000_000_000_001,
            journal_incarnation_id=runtime.journal_generation,
            payload={"reason_code": "risk_denied", "filled_quantity": "1"},
        )
    )
    try:
        with pytest.raises(ManagedExecutionBindingError, match="unexpected payload facts"):
            bridge.poll_managed_provider_outbox_update()
        assert bridge._source_projection_blocked is True
    finally:
        broker.stop()


def test_real_facade_pre_dispatch_guard_emits_blocked_no_fill_event(tmp_path) -> None:
    execution = pytest.importorskip("bt_api_execution")
    scope = execution.ExecutionScope(
        "fixture", "offline", "account.facade-guard", "strategy.facade-guard", "20260926"
    )
    execution_store = execution.SqliteExecutionStore(tmp_path / "execution.sqlite3")
    provider = _ResponseProvider([])

    def guard(_intent) -> None:
        raise RuntimeError("fixture pre-dispatch guard deny")

    facade = execution.ManagedExecutionFacade(
        execution_store,
        scope,
        writer_id="fixture.pre-dispatch-guard",
        allow_unprotected=True,
        pre_dispatch_guard=guard,
    )
    runtime = SimpleNamespace(
        execution=execution,
        scope=scope,
        state_directory=tmp_path,
        framework_projection_session_id=uuid.uuid4().hex,
        execution_store=execution_store,
        facade=facade,
        submit=lambda intent, dispatcher: facade.submit(intent, dispatcher),
    )
    bridge = ManagedExecutionBridge(
        runtime,
        provider_observation_from_update=_cumulative_provider_observation,
    )
    _store, data, broker = _make_started_stack(runtime, provider, managed_execution_adapter=bridge)
    try:
        order = _submit(broker, data, "intent.facade-guard")

        assert order.status == bt.Order.Rejected
        assert order.executed.size == pytest.approx(0.0)
        assert provider.submitted_orders == []
        record = execution_store.get("intent.facade-guard", scope=scope)
        assert record.state is execution.ExecutionState.BLOCKED

        events = execution_store.read_outbox(scope=scope)
        blocked = [event for event in events if event.event_type == "dispatch_blocked"]
        assert len(blocked) == 1
        assert blocked[0].state is execution.ExecutionState.BLOCKED
        assert blocked[0].payload == {"reason_code": "pre_dispatch_guard_failed"}

        # The real source rows are consumed as an exact no-fill lifecycle
        # prefix, leaving the scoped source cursor ready for later events.
        assert bridge.poll_managed_provider_outbox_update() is None
        identity = execution_store.journal_source_identity()
        assert (
            bridge._framework_projection_journal.source_high_water(
                scope_key=scope.key,
                journal_incarnation_id=identity["generation"],
                session_id=runtime.framework_projection_session_id,
            )
            == events[-1].sequence
        )
        assert bridge._source_projection_blocked is False
    finally:
        broker.stop()
        bridge.close()
        facade.close()
        execution_store.close()


def test_cancel_snapshot_replays_before_next_intent_event(tmp_path) -> None:
    runtime, provider, _store, data, broker, order = _make_provider_event_stack(
        tmp_path,
        responses=[
            {"status": "accepted", "id": "provider.event-fixture"},
            {"status": "accepted", "id": "provider.next-fixture"},
        ],
    )
    bridge = broker.store._managed_execution_adapter
    try:
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()
        assert order.executed.size == pytest.approx(1.0)
        assert order.status == bt.Order.Partial

        # The cancellation event captures the exact cumulative target facts
        # inside the execution store transaction. The main reader does not
        # look at a latest ExecutionRecord to reconstruct these values.
        runtime._source_sequence += 1
        runtime._outbox.append(
            SimpleNamespace(
                sequence=runtime._source_sequence,
                event_id="source-event.cancelled",
                intent_id="intent.provider-events",
                scope_key=runtime.scope.key,
                event_type="cancelled_by_cancel_intent",
                state=_ExecutionState.CANCELLED,
                created_at_ns=1_900_000_000_000_000_000 + runtime._source_sequence,
                journal_incarnation_id=runtime.journal_generation,
                payload={
                    "cancel_id": "cancel.fixture",
                    "provider_order_id": "provider.event-fixture",
                    "source": "provider",
                    "filled_quantity": "1",
                    "average_price": "100",
                    "cumulative_commission": "0.05",
                },
            )
        )
        broker._drain_store_updates()
        assert (
            bridge._framework_projection_journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 2
        )
        assert order.status == bt.Order.Canceled
        assert order.executed.size == pytest.approx(1.0)
        assert order.executed.comm == pytest.approx(0.05)

        next_order = _submit(broker, data, "intent.next")
        runtime._record_provider_event(
            _CumulativeProviderObservation(
                intent_id="intent.next",
                state=_ExecutionState.ACKED,
                provider_order_id="provider.next-fixture",
                filled_quantity=Decimal("0"),
                average_price=None,
                cumulative_commission=Decimal("0"),
            )
        )
        broker._drain_store_updates()

        assert next_order.status == bt.Order.Accepted
        assert next_order.executed.size == pytest.approx(0.0)
        assert (
            bridge._framework_projection_journal.source_high_water(
                scope_key=runtime.scope.key,
                journal_incarnation_id=runtime.journal_generation,
                session_id=runtime.framework_projection_session_id,
            )
            == 3
        )
    finally:
        broker.stop()


def test_missing_fee_growth_and_cancel_wait_for_event_time_fee_evidence(tmp_path) -> None:
    runtime, _provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    bridge = broker.store._managed_execution_adapter
    journal = bridge._framework_projection_journal

    def high_water() -> int:
        return journal.source_high_water(
            scope_key=runtime.scope.key,
            journal_incarnation_id=runtime.journal_generation,
            session_id=runtime.framework_projection_session_id,
        )

    try:
        first = runtime._record_provider_event(
            _CumulativeProviderObservation(
                intent_id="intent.provider-events",
                state=_ExecutionState.PARTIALLY_FILLED,
                provider_order_id="provider.event-fixture",
                filled_quantity=Decimal("0.75"),
                average_price=Decimal("50001.25"),
                cumulative_commission=Decimal("-0.125"),
            )
        )
        broker._drain_store_updates()
        assert first.sequence == 1
        assert order.executed.size == pytest.approx(0.75)
        assert order.executed.comm == pytest.approx(-0.125)
        assert high_water() == 1

        # Growing cumulative quantity with an unknown fee must clear the
        # prior known fee. The immutable cancellation snapshot must preserve
        # that unknown, rather than copying the stale fee from an old row.
        second = runtime._record_provider_event(
            _CumulativeProviderObservation(
                intent_id="intent.provider-events",
                state=_ExecutionState.PARTIALLY_FILLED,
                provider_order_id="provider.event-fixture",
                filled_quantity=Decimal("1.25"),
                average_price=Decimal("50002.50"),
                cumulative_commission=None,
            )
        )
        cancellation = SimpleNamespace(
            sequence=3,
            event_id="source-event.cancelled-with-unknown-fee",
            intent_id="intent.provider-events",
            scope_key=runtime.scope.key,
            event_type="cancelled_by_cancel_intent",
            state=_ExecutionState.CANCELLED,
            created_at_ns=1_900_000_000_000_000_003,
            journal_incarnation_id=runtime.journal_generation,
            payload={
                "cancel_id": "cancel.fixture",
                "provider_order_id": "provider.event-fixture",
                "source": "provider",
                "filled_quantity": "1.25",
                "average_price": "50002.50",
                "cumulative_commission": None,
            },
        )
        runtime._source_sequence = cancellation.sequence
        runtime._outbox.append(cancellation)
        broker._drain_store_updates()

        assert second.sequence == 2
        assert second.payload["cumulative_commission"] is None
        assert cancellation.payload["cumulative_commission"] is None
        assert order.executed.size == pytest.approx(0.75)
        assert order.executed.comm == pytest.approx(-0.125)
        assert order.status == bt.Order.Partial
        assert high_water() == 1

        fee_evidence = runtime._record_provider_event(
            _CumulativeProviderObservation(
                intent_id="intent.provider-events",
                state=_ExecutionState.CANCELLED,
                provider_order_id="provider.event-fixture",
                filled_quantity=Decimal("1.25"),
                average_price=Decimal("50002.50"),
                cumulative_commission=Decimal("-0.185"),
            )
        )
        broker._drain_store_updates()

        assert fee_evidence.event_type == "provider_commission_evidence"
        assert fee_evidence.sequence == 4
        assert order.status == bt.Order.Canceled
        assert order.executed.size == pytest.approx(1.25)
        assert order.executed.price == pytest.approx(50002.50)
        assert order.executed.comm == pytest.approx(-0.185)
        assert [bit.price for bit in order.executed.exbits] == pytest.approx([50001.25, 50004.375])
        assert [bit.comm for bit in order.executed.exbits] == pytest.approx([-0.125, -0.06])
        assert high_water() == 4
        assert bridge._source_projection_blocked is False
    finally:
        broker.stop()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("avg_price", "999"),
        ("price", 999.0),
        ("commission", 9.0),
        ("managed_source_average_price", "999"),
    ),
)
def test_mutated_prepared_economic_update_is_rejected_before_booking(
    tmp_path, field, value
) -> None:
    _runtime, provider, store, _data, broker, order = _make_provider_event_stack(tmp_path)
    original_validate = store.validate_managed_provider_projection

    def mutate_then_validate(update, current_order):
        update[field] = value
        return original_validate(update, current_order)

    store.validate_managed_provider_projection = mutate_then_validate
    try:
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()
        assert order.executed.size == pytest.approx(0.0)
        assert order.info["execution_unknown"] is True
        assert order.info.get("ledger_mismatch") is True
        assert broker._managed_provider_projection_failed is True
    finally:
        broker.stop()


def test_silent_broker_apply_noop_fails_actual_execution_receipt_check(tmp_path) -> None:
    _runtime, provider, _store, _data, broker, order = _make_provider_event_stack(tmp_path)
    broker._apply_order_update = lambda *_args, **_kwargs: None
    try:
        _push_cumulative_update(
            provider,
            order,
            quantity="1",
            average="100",
            commission="0.05",
        )
        broker._drain_store_updates()
        assert order.executed.size == pytest.approx(0.0)
        assert order.info["execution_unknown"] is True
        assert order.info.get("ledger_mismatch") is True
        assert broker._managed_provider_projection_failed is True
    finally:
        broker.stop()
