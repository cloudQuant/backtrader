"""Native futures IOC reconciliation, including ambiguous submissions."""

import asyncio
import datetime as dt
import time

import backtrader as bt
import pytest

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


@pytest.fixture
def stack():
    client = FakeBtApiClient(history={DEFAULT_SYMBOL: [make_bar(0, 100, 101, 99, 100)]})
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(
        validation_enabled=False,
        force_refresh_queries=False,
        account_refresh_interval=3600,
        positions_refresh_interval=3600,
        open_orders_refresh_interval=3600,
        cancel_wait_remote=True,
    )
    data._start()
    assert data.load()
    broker.start()
    yield client, store, data, broker
    broker.stop()


def submit(stack, **kwargs):
    return stack[3].buy(None, stack[2], size=2, price=120, exectype=bt.Order.Limit, **kwargs)


def update(stack, order, **fields):
    stack[0].broker_updates.append({"kind": "order", "bt_order_ref": order.ref, **fields})
    stack[3].next()


def leased_stack(expires_at, maximum_orders):
    client = FakeBtApiClient(history={DEFAULT_SYMBOL: [make_bar(0, 100, 101, 99, 100)]})
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(
        validation_enabled=False,
        force_refresh_queries=False,
        account_refresh_interval=3600,
        positions_refresh_interval=3600,
        open_orders_refresh_interval=3600,
        approval_expires_at_utc=expires_at,
        approval_max_order_count=maximum_orders,
    )
    data._start()
    assert data.load()
    broker.start()
    return client, store, data, broker


class ClassifiedRemoteError(RuntimeError):
    def __init__(self, code, *, execution_unknown=False, definite_reject=False):
        super().__init__("credential=must-not-enter-order-info")
        self.code = code
        self.execution_unknown = execution_unknown
        self.definite_reject = definite_reject


def test_unknown_submission_stays_live_until_confirmed_terminal_fill(stack):
    client, store, data, broker = stack
    client.submit_order = lambda payload: {
        "status": "submitted",
        "execution_unknown": True,
        "client_order_id": "arb-unknown",
        "bt_order_ref": payload["bt_order_ref"],
    }
    order = submit(stack, client_order_id="arb-unknown", time_in_force="IOC", reduce_only=True)
    assert order.status == bt.Order.Accepted
    assert order.info.execution_unknown is True
    assert order.info.time_in_force == "IOC"
    assert order.info.reduce_only is True
    assert broker._orders_by_client_ref["arb-unknown"] is order
    update(stack, order, status="submitted", execution_unknown=True)
    assert order.alive()
    update(stack, order, status="canceled", filled=0.5, avg_price=105, cumulative_commission=0.02)
    assert order.status == bt.Order.Canceled
    assert order.info.execution_unknown is False
    assert order.executed.size == pytest.approx(0.5)
    assert order.executed.price == pytest.approx(105)
    assert order.executed.comm == pytest.approx(0.02)
    assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(0.5)


def test_timeout_is_not_reported_as_rejection_or_retried(stack):
    attempts = []

    def timed_out(payload):
        attempts.append(payload)
        raise TimeoutError("response timed out")

    stack[0].submit_order = timed_out
    order = submit(stack, client_order_id="arb-timeout")
    assert order.status == bt.Order.Accepted
    assert order.info.execution_unknown is True
    assert stack[3]._orders_by_client_ref["arb-timeout"] is order
    stack[3].next()
    assert len(attempts) == 1


def test_normalized_unknown_exception_keeps_original_client_identity_live(stack):
    attempts = []

    def unknown(payload):
        attempts.append(payload)
        raise ClassifiedRemoteError("transport_timeout", execution_unknown=True)

    stack[0].submit_order = unknown
    order = submit(stack, client_order_id="arb-classified-unknown")

    assert order.status == bt.Order.Accepted
    assert order.info.execution_unknown is True
    assert order.info.remote_error_code == "transport_timeout"
    assert "must-not-enter-order-info" not in order.info.error_msg
    assert stack[3]._orders_by_client_ref["arb-classified-unknown"] is order
    stack[3].next()
    assert len(attempts) == 1


def test_unclassified_sdk_submit_exception_is_unknown_not_rejected(stack):
    def unclassified(_payload):
        raise ConnectionError("connection reset after possible write")

    stack[1]._sdk_mode = True
    stack[3]._uses_async_commands = lambda: False
    stack[3]._validate_order = lambda _order: None
    stack[3]._ensure_required_net_offset = lambda _order: None
    stack[1].submit_order = unclassified
    try:
        order = submit(stack, client_order_id="arb-unclassified")

        assert order.status == bt.Order.Accepted
        assert order.info.execution_unknown is True
        assert any(mapped is order for mapped in stack[3]._orders_by_client_ref.values())
    finally:
        stack[1]._sdk_mode = False


def test_sdk_opening_is_locked_until_startup_evidence_is_complete(stack):
    calls = []
    stack[1]._sdk_mode = True
    stack[3]._startup_ready = False
    stack[1].submit_order = lambda order: calls.append(order)
    try:
        order = submit(stack, client_order_id="startup-not-ready")

        assert order.status == bt.Order.Rejected
        assert order.info.error_code == "startup_preflight_incomplete"
        assert calls == []
    finally:
        stack[1]._sdk_mode = False


def test_sdk_startup_with_remote_open_orders_stays_locked():
    class StartupStore:
        _sdk_mode = True
        uses_async_commands = True
        requires_account_risk = False
        contract_metadata = {}

        def __init__(self):
            self.is_connected = False

        def start(self, broker=None):
            self.is_connected = True

        def get_balance(self, **_kwargs):
            return {"cash": 1000, "value": 1000}

        def get_positions(self, **_kwargs):
            return []

        def fetch_open_orders(self, **_kwargs):
            return [{"id": "pre-existing-order"}]

        def emit_runtime_event(self, *_args, **_kwargs):
            return None

        def stop(self, **_kwargs):
            self.is_connected = False

    store = StartupStore()
    broker = bt.brokers.BtApiBroker(
        store=store,
        sdk_preflight=False,
        validation_enabled=False,
        force_refresh_queries=False,
    )

    with pytest.raises(ValueError, match="empty remote open-order set"):
        broker.start()

    assert broker._live_started is False
    assert broker._startup_ready is False
    assert broker._trading_enabled is False
    broker.stop()


def test_sdk_startup_requires_clean_fenced_execution_summary(stack):
    broker = stack[3]
    now_ns = time.monotonic_ns()
    identity_hash = "a" * 64
    snapshot = {
        "positions": [],
        "open_orders": [],
        "configured_venues": ["okx"],
        "reconciled_venues": ["okx"],
        "unknown_ids": [],
        "trading_blocked": False,
        "generation": 3,
        "session_generation": 3,
        "fencing_epoch": 7,
        "as_of_monotonic_ns": now_ns,
        "identity_binding_sha256": identity_hash,
        "evidence_complete": True,
        "evidence_errors": [],
        "execution_summary": {
            "session_enabled": True,
            "active_orders": 0,
            "unknown_ids": [],
            "fee_unresolved_orders": [],
            "funding_unresolved_orders": [],
            "reconciliation_errors": {},
            "trading_blocked": False,
            "generation": 3,
            "session_generation": 3,
            "fencing_epoch": 7,
            "as_of_monotonic_ns": now_ns,
            "identity_binding_sha256": identity_hash,
            "evidence_complete": True,
            "evidence_errors": [],
        },
    }

    assert broker._reconcile_proves_clean_execution(snapshot) is True
    snapshot["execution_summary"]["active_orders"] = 1
    assert broker._reconcile_proves_clean_execution(snapshot) is False


@pytest.mark.parametrize("remote_side", ["sell", "unrecognized-side"])
def test_trade_side_conflict_is_not_booked_and_blocks_openings(stack, remote_side):
    client, store, data, broker = stack
    order = submit(stack)
    before_position = broker.positions[DEFAULT_SYMBOL].size

    client.push_broker_update(
        {
            "kind": "trade",
            "bt_order_ref": order.ref,
            "trade_id": f"wrong-side-{remote_side}",
            "data_name": DEFAULT_SYMBOL,
            "side": remote_side,
            "offset": "open",
            "size": 1,
            "price": 101,
        }
    )
    broker.next()

    expected_code = "trade_side_mismatch" if remote_side == "sell" else "trade_side_unrecognized"
    assert order.executed.size == 0
    assert broker.positions[DEFAULT_SYMBOL].size == before_position
    assert order.info.execution_unknown is True
    assert order.info.ledger_mismatch is True
    assert order.info.error_code == expected_code
    assert broker._position_audit_blocked is True

    blocked = broker.buy(
        None,
        data,
        size=1,
        price=120,
        exectype=bt.Order.Limit,
        offset="open",
    )
    assert blocked.status == bt.Order.Rejected
    assert blocked.info.error_code == "position_audit_blocked"

    events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    mismatch = [
        event for event in events if event["event_type"] == "trade_update_identity_mismatch"
    ]
    assert mismatch and mismatch[-1]["error_code"] == expected_code


@pytest.mark.parametrize(
    ("local_meta", "remote_meta", "expected_code"),
    [
        (
            {"position_side": "long", "offset": "open"},
            {"position_side": "short"},
            "trade_position_side_mismatch",
        ),
        (
            {"position_side": "long", "offset": "open"},
            {"offset": "close"},
            "trade_offset_mismatch",
        ),
        (
            {"position_side": "long", "offset": "open"},
            {"position_mode": "dual_side"},
            "trade_position_mode_mismatch",
        ),
        (
            {
                "position_side": "long",
                "offset": "open",
                "quantity_unit": "contracts",
            },
            {"quantity_unit": "base_asset"},
            "trade_quantity_unit_mismatch",
        ),
    ],
)
def test_trade_position_identity_conflict_is_not_booked(
    stack, local_meta, remote_meta, expected_code
):
    client, _store, _data, broker = stack
    order = submit(stack, **local_meta)
    before_position = broker.positions[DEFAULT_SYMBOL].size

    client.push_broker_update(
        {
            "kind": "trade",
            "bt_order_ref": order.ref,
            "trade_id": f"identity-{expected_code}",
            "data_name": DEFAULT_SYMBOL,
            "side": "buy",
            "size": 1,
            "price": 101,
            **remote_meta,
        }
    )
    broker.next()

    assert order.executed.size == 0
    assert broker.positions[DEFAULT_SYMBOL].size == before_position
    assert order.info.execution_unknown is True
    assert order.info.ledger_mismatch is True
    assert order.info.error_code == expected_code
    assert broker._position_audit_blocked is True


@pytest.mark.parametrize(
    ("local_meta", "remote_key", "remote_value", "expected_code", "canonical_key"),
    [
        (
            {"position_side": "long", "offset": "open"},
            "posSide",
            "short",
            "trade_position_side_mismatch",
            "position_side",
        ),
        (
            {"position_side": "long", "offset": "open"},
            "positionEffect",
            "close",
            "trade_offset_mismatch",
            "offset",
        ),
        (
            {"position_side": "long", "offset": "open"},
            "posMode",
            "dual_side",
            "trade_position_mode_mismatch",
            "position_mode",
        ),
        (
            {
                "position_side": "long",
                "offset": "open",
                "quantity_unit": "contracts",
            },
            "qtyUnit",
            "base_asset",
            "trade_quantity_unit_mismatch",
            "quantity_unit",
        ),
    ],
)
def test_nested_trade_identity_mismatch_preserves_evidence_and_requests_both_reconciles(
    stack,
    monkeypatch,
    local_meta,
    remote_key,
    remote_value,
    expected_code,
    canonical_key,
):
    client, store, _data, broker = stack
    order = submit(stack, **local_meta)
    order.addinfo(
        reconcile_requested=False,
        reconcile_next_monotonic_ns=None,
        reconcile_attempts=0,
    )
    calls = []
    monkeypatch.setattr(
        store,
        "enqueue_query",
        lambda order_ref, dataname=None: calls.append(("query", order_ref))
        or {"queued": True, "status": "submitted"},
    )
    monkeypatch.setattr(
        store,
        "enqueue_reconcile",
        lambda: calls.append(("reconcile", None)) or {"queued": True, "status": "submitted"},
    )
    before = store.get_command_health()

    client.push_broker_update(
        {
            "kind": "trade",
            "bt_order_ref": order.ref,
            "trade_id": f"nested-{expected_code}",
            "data_name": DEFAULT_SYMBOL,
            "size": 1,
            "price": 101,
            "details": {"side": "buy", remote_key: remote_value},
        }
    )
    broker.next()

    assert order.executed.size == 0
    assert broker.positions[DEFAULT_SYMBOL].size == 0
    assert order.info.error_code == expected_code
    after = store.get_command_health()
    assert after["risk_incident_epoch"] == before["risk_incident_epoch"] + 1
    assert after["risk_state_latched"] is True
    assert after["accepting_openings"] is False
    assert calls == [("query", order.ref), ("reconcile", None)]

    events = [kwargs["event"] for _msg, _args, kwargs in store.get_notifications()]
    mismatch = [
        event for event in events if event["event_type"] == "trade_update_identity_mismatch"
    ]
    details = mismatch[-1]["details"]
    assert details[remote_key] == remote_value
    assert details["actual_remote_identity"][canonical_key] == remote_value
    expected = details["expected_execution_contract"]
    assert expected[canonical_key] != remote_value
    assert expected["source"] in {"broker_intent", "sdk_request"}


def test_identity_mismatch_quarantines_later_cumulative_order_fill(stack):
    client, _store, _data, broker = stack
    order = submit(stack, position_side="long", offset="open")

    client.push_broker_update(
        {
            "kind": "trade",
            "bt_order_ref": order.ref,
            "trade_id": "conflicting-trade",
            "data_name": DEFAULT_SYMBOL,
            "side": "buy",
            "position_side": "short",
            "offset": "open",
            "size": 1,
            "price": 101,
        }
    )
    broker.next()
    assert order.executed.size == 0

    client.push_broker_update(
        {
            "kind": "order",
            "bt_order_ref": order.ref,
            "data_name": DEFAULT_SYMBOL,
            "status": "completed",
            "filled": 1,
            "avg_price": 101,
        }
    )
    broker.next()

    assert order.executed.size == 0
    assert broker.positions[DEFAULT_SYMBOL].size == 0
    assert order.info.ledger_mismatch is True


def test_execution_contract_is_immutable_after_submission(stack):
    client, _store, _data, broker = stack
    order = submit(
        stack,
        position_side="long",
        offset="open",
        quantity_unit="contracts",
    )
    order.info.position_side = "short"
    order.info.offset = "close"
    order.info.quantity_unit = "base_asset"

    client.push_broker_update(
        {
            "kind": "trade",
            "bt_order_ref": order.ref,
            "trade_id": "immutable-contract-fill",
            "data_name": DEFAULT_SYMBOL,
            "side": "buy",
            "position_side": "long",
            "offset": "open",
            "position_mode": "net",
            "quantity_unit": "contracts",
            "size": 1,
            "price": 101,
        }
    )
    broker.next()

    assert order.executed.size == pytest.approx(1)
    assert broker.positions[DEFAULT_SYMBOL].size == pytest.approx(1)


def test_normalized_definite_reject_returns_rejected_order_without_raising(stack):
    def rejected(_payload):
        raise ClassifiedRemoteError("50123", definite_reject=True)

    stack[0].submit_order = rejected
    order = submit(stack, client_order_id="arb-definite-reject")

    assert order.status == bt.Order.Rejected
    assert order.info.error_code == "remote_submit_rejected"
    assert order.info.remote_error_code == "50123"
    assert "must-not-enter-order-info" not in order.info.error_msg


@pytest.mark.parametrize("wrapped", [False, True])
def test_normalized_submit_rejection_preserves_specific_remote_code(stack, wrapped):
    response = {
        "kind": "order",
        "status": "rejected",
        "execution_unknown": False,
        "terminal_confirmed": True,
        "error_code": "50123",
    }
    stack[0].submit_order = lambda payload: (
        {"status": "ok", "data": response} if wrapped else response
    )
    order = submit(stack)
    assert order.status == bt.Order.Rejected
    assert order.info.error_code == "remote_submit_rejected"
    assert order.info.remote_error_code == "50123"


@pytest.mark.parametrize("status_msg", [None, "rejected"])
def test_normalized_later_rejection_preserves_specific_remote_code(stack, status_msg):
    order = submit(stack)
    update(stack, order, status="rejected", error_code=50123, status_msg=status_msg)
    assert order.status == bt.Order.Rejected
    assert order.info.error_code == "remote_reject"
    assert order.info.remote_error_code == "50123"


@pytest.mark.parametrize("terminal", ["canceled", "expired", "EXPIRED_IN_MATCH"])
@pytest.mark.parametrize("filled", [0.0, 0.5])
def test_confirmed_ioc_terminal_status_keeps_partial_fill_without_local_deadline(
    stack, terminal, filled
):
    order = submit(stack)
    update(stack, order, status=terminal, filled=filled, avg_price=105)
    expected = bt.Order.Canceled if terminal == "canceled" else bt.Order.Expired
    assert order.status == expected
    assert not order.alive()
    assert order.executed.size == pytest.approx(filled)
    assert stack[3].positions[DEFAULT_SYMBOL].size == pytest.approx(filled)


@pytest.mark.parametrize("terminal", ["canceled", "expired"])
def test_immediate_terminal_submit_response_records_partial_execution(stack, terminal):
    stack[0].submit_order = lambda payload: {
        "status": terminal,
        "order_id": "ioc-immediate",
        "filled": 0.5,
        "avg_price": 105,
        "cumulative_commission": 0.02,
    }
    order = submit(stack)
    assert order.status == (bt.Order.Canceled if terminal == "canceled" else bt.Order.Expired)
    assert order.executed.size == pytest.approx(0.5)
    assert order.executed.comm == pytest.approx(0.02)


def test_cumulative_average_and_fees_are_converted_to_incremental_fills(stack):
    order = submit(stack)
    update(stack, order, status="partial", filled=1, avg_price=100, cumulative_commission=0.05)
    update(stack, order, status="completed", filled=2, avg_price=110, cumulative_commission=0.11)
    assert order.executed.price == pytest.approx(110)
    assert [part.price for part in order.executed.exbits] == pytest.approx([100, 120])
    assert order.executed.comm == pytest.approx(0.11)
    assert stack[3].positions[DEFAULT_SYMBOL].price == pytest.approx(110)


def test_confirmed_live_status_clears_unknown_and_emits_notification(stack):
    stack[0].submit_order = lambda payload: {
        "execution_unknown": True,
        "client_order_id": "arb-pending",
    }
    order = submit(stack)
    stack[3].notifs.clear()
    update(stack, order, status="accepted")
    assert order.alive()
    assert order.info.execution_unknown is False
    notification = stack[3].get_notification()
    assert notification.status == bt.Order.Accepted
    assert notification.info.execution_unknown is False


def test_approval_operation_budget_blocks_new_exposure_but_never_traps_a_close():
    expires_at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    current = leased_stack(expires_at, 2)
    try:
        opening = submit(current)
        closing = submit(current, offset="close", reduce_only=True)
        blocked = submit(current)

        assert opening.status != bt.Order.Rejected
        assert opening.info.approval_operation_count == 1
        assert closing.status != bt.Order.Rejected
        assert closing.info.approval_operation_count == 2
        assert closing.info.approval_risk_reducing is True
        assert blocked.status == bt.Order.Rejected
        assert blocked.info.error_code == "demo_approval_order_limit"
        assert current[3]._approval_operation_count == 2
        assert current[3].get_approval_lease_status() == {
            "enabled": True,
            "expires_at_utc": expires_at,
            "maximum_order_count": 2,
            "operation_count": 2,
        }
    finally:
        current[3].stop()


def test_expired_approval_blocks_opening_but_allows_risk_reduction():
    expires_at = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    current = leased_stack(expires_at, 1)
    try:
        opening = submit(current)
        closing = submit(current, offset="close", reduce_only=True)

        assert opening.status == bt.Order.Rejected
        assert opening.info.error_code == "demo_approval_expired"
        assert closing.status != bt.Order.Rejected
        assert closing.info.approval_operation_count == 1
        assert closing.info.approval_risk_reducing is True
    finally:
        current[3].stop()


def test_cancel_operation_consumes_the_signed_operation_budget():
    expires_at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    current = leased_stack(expires_at, 2)
    try:
        opening = submit(current)
        current[3].cancel(opening)
        blocked = submit(current)

        assert opening.info.approval_operation == "cancel"
        assert opening.info.approval_operation_count == 2
        assert blocked.status == bt.Order.Rejected
        assert blocked.info.error_code == "demo_approval_order_limit"
    finally:
        current[3].stop()


def test_store_rechecks_approval_immediately_before_async_sdk_write():
    class LeaseSdk:
        def __init__(self):
            self.calls = []

        async def async_make_order(self, venue, request, normalized=False):
            self.calls.append((venue, request, normalized))
            return {"status": "submitted"}

    api = LeaseSdk()
    store = object.__new__(BtApiStore)
    store._api = api
    expired = {
        "approval_expires_at_utc": "2000-01-01T00:00:00Z",
        "approval_operation_count": 1,
        "approval_max_order_count": 2,
        "approval_risk_reducing": False,
        "venue": "OKX___SWAP",
        "request": object(),
    }

    with pytest.raises(BtApiStoreError, match="demo_approval_expired"):
        asyncio.run(store._invoke_sdk_command("submit", expired))
    assert api.calls == []

    reducing = dict(expired, approval_operation_count=3, approval_risk_reducing=True)
    result = asyncio.run(store._invoke_sdk_command("submit", reducing))
    assert result == {"status": "submitted"}
    assert len(api.calls) == 1
