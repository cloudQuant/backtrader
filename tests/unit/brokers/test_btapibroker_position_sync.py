"""Explicit startup position baselines cannot overlap later execution callbacks."""

import collections
from decimal import Decimal
from types import SimpleNamespace

import backtrader as bt
import pytest

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.position import Position
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


def setup_stack(mode="dual_side", policy="startup", initial=0, start_feed=True, audit_interval=0.0):
    """Start a position-sync broker stack; returns (client, data, broker)."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100, 102, 98, 100)]},
        positions=[{"symbol": DEFAULT_SYMBOL, "size": initial, "price": 100, "direction": "long"}],
    )
    client.position_queries = 0
    original = client.get_positions

    def positions():
        client.position_queries += 1
        return original()

    client.get_positions = positions
    store = make_store(api=client, config={"supports_dual_side": True})
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker(
        position_mode=mode,
        position_sync_policy=policy,
        validation_enabled=False,
        force_refresh_queries=True,
        positions_refresh_interval=0,
        account_refresh_interval=3600,
        open_orders_refresh_interval=3600,
        position_audit_interval=audit_interval,
    )
    if start_feed:
        data._start()
        assert data.load()
    broker.start()
    return client, data, broker


def position(broker, data, side):
    """Return the broker's position for data on the given side."""
    return (
        broker.getposition(data, side=side)
        if broker.p.position_mode == "dual_side"
        else broker.getposition(data)
    )


def make_position_sync_broker(data_feeds, rows, *, subscribed=(), contract_metadata=None):
    store = SimpleNamespace(
        is_connected=True,
        _service_read_only=False,
        _data_feeds=list(data_feeds),
        _subscribed_datanames=set(subscribed),
        contract_metadata=dict(contract_metadata or {}),
        get_positions=lambda **kwargs: list(rows),
    )
    broker = BtApiBroker(
        store=store,
        position_sync_policy="periodic",
        force_refresh_queries=False,
        validation_enabled=False,
        contract_metadata=contract_metadata,
    )
    broker._live_started = True
    return broker


def test_net_snapshot_aggregates_multiple_same_side_rows_with_weighted_price():
    broker = BtApiBroker(position_mode="net")
    synced = collections.defaultdict(Position)
    long_synced = collections.defaultdict(Position)
    short_synced = collections.defaultdict(Position)

    for row in (
        {"symbol": DEFAULT_SYMBOL, "size": 2, "price": 100, "direction": "long"},
        {"symbol": DEFAULT_SYMBOL, "size": 1, "price": 110, "direction": "long"},
    ):
        broker._sync_one_position(
            row,
            synced,
            long_synced,
            short_synced,
            key=DEFAULT_SYMBOL,
        )

    assert synced[DEFAULT_SYMBOL].size == 3
    assert synced[DEFAULT_SYMBOL].price == pytest.approx(310 / 3)


def test_net_snapshot_rejects_opposing_rows_as_account_mode_mismatch():
    broker = BtApiBroker(position_mode="net")
    synced = collections.defaultdict(Position)
    long_synced = collections.defaultdict(Position)
    short_synced = collections.defaultdict(Position)
    broker._sync_one_position(
        {"symbol": DEFAULT_SYMBOL, "size": 1, "price": 100, "direction": "long"},
        synced,
        long_synced,
        short_synced,
        key=DEFAULT_SYMBOL,
    )

    with pytest.raises(ValueError, match="opposing position rows"):
        broker._sync_one_position(
            {"symbol": DEFAULT_SYMBOL, "size": 1, "price": 101, "direction": "short"},
            synced,
            long_synced,
            short_synced,
            key=DEFAULT_SYMBOL,
        )


@pytest.mark.parametrize(
    "mode,side", [("net", "long"), ("dual_side", "long"), ("dual_side", "short")]
)
@pytest.mark.parametrize("snapshot_first", [False, True])
@pytest.mark.parametrize("source", ["cumulative", "trades"])
def test_startup_snapshot_never_double_counts_or_erases_open_and_close_fills(
    mode, side, snapshot_first, source
):
    client, data, broker = setup_stack(mode)
    try:

        def refresh(remote_size):
            client.positions = [
                {"symbol": DEFAULT_SYMBOL, "size": remote_size, "price": 101, "direction": side}
            ]
            broker._sync_positions(force=True, raise_errors=True)
            return abs(position(broker, data, side).size)

        def execute(order, price):
            identity = {
                "bt_order_ref": order.ref,
                "data_name": DEFAULT_SYMBOL,
                "side": "buy" if order.isbuy() else "sell",
            }
            if source == "cumulative":
                client.push_broker_update(
                    {
                        **identity,
                        "kind": "order",
                        "status": "completed",
                        "filled": 2,
                        "avg_price": price,
                        "execution_source": source,
                    }
                )
            else:
                client.push_broker_update(
                    {
                        **identity,
                        "kind": "order",
                        "status": "completed",
                        "filled": 2,
                        "execution_source": source,
                    }
                )
                for index, fill_price in enumerate((price - 1, price + 1)):
                    client.push_broker_update(
                        {
                            **identity,
                            "kind": "trade",
                            "trade_id": f"{order.ref}-{index}",
                            "size": 1,
                            "price": fill_price,
                        }
                    )
            broker.next()
            assert abs(order.executed.size) == 2
            assert order.status == bt.Order.Completed

        opening = broker.buy if side == "long" else broker.sell
        order = opening(
            None,
            data,
            size=2,
            price=101,
            exectype=bt.Order.Limit,
            position_side=side,
            offset="open",
        )
        if snapshot_first:
            assert refresh(2) == 0
        execute(order, 101)
        assert refresh(2 if snapshot_first else 0) == 2
        assert position(broker, data, side).price == 101
        closing = broker.sell if side == "long" else broker.buy
        close = closing(
            None,
            data,
            size=2,
            price=99,
            exectype=bt.Order.Limit,
            position_side=side,
            offset="close",
            reduce_only=True,
        )
        if snapshot_first:
            assert refresh(0) == 2
        execute(close, 99)
        assert refresh(0 if snapshot_first else 2) == 0
        assert client.position_queries == 1
    finally:
        broker.stop()


def test_startup_hydrates_registered_feed_before_it_starts_and_never_reimports_on_restart():
    client, data, broker = setup_stack(initial=3, start_feed=False)
    try:
        data._start()
        assert data.load()
        assert broker.getposition(data, side="long").size == 3
        client.positions = []
        broker.stop()
        broker.start()
        assert broker.getposition(data, side="long").size == 3
        assert client.position_queries == 1
        with pytest.raises(ValueError, match="frozen"):
            broker.set_param("position_sync_policy", "periodic")
    finally:
        broker.stop()


def test_periodic_policy_preserves_existing_forced_remote_refresh():
    client, data, broker = setup_stack(policy="periodic", initial=2)
    try:
        client.positions = [
            {"symbol": DEFAULT_SYMBOL, "size": 3, "price": 101, "direction": "long"}
        ]
        assert broker.getposition(data, side="long").size == 3
        assert client.position_queries == 2
    finally:
        broker.stop()


def test_periodic_refresh_keeps_current_contract_position_bound_to_named_feed():
    """A contract-keyed position row must resolve to the feed's execution key."""
    data = SimpleNamespace(
        _name="DCE.M",
        _dataname="M2612",
        p=SimpleNamespace(dataname="M2612"),
    )
    store = SimpleNamespace(
        is_connected=True,
        _service_read_only=False,
        _data_feeds=[data],
        _subscribed_datanames={"M2612"},
        get_positions=lambda **kwargs: [
            {
                "symbol": "M2612",
                "instrument": "M2612",
                "exchange_id": "DCE",
                "direction": "long",
                "volume": 1,
                "price": 100,
            }
        ],
    )
    broker = BtApiBroker(
        store=store,
        position_sync_policy="periodic",
        force_refresh_queries=False,
        validation_enabled=False,
        contract_metadata={"DCE.M": {"instrument_id": "M2612", "exchange_id": "DCE"}},
    )
    broker._live_started = True
    broker.positions["DCE.M"].update(1, 100)

    before_refresh = broker.execution_position_snapshot(data)
    assert before_refresh.data_name == "DCE.M"
    assert before_refresh.instrument_id == "M2612"
    assert before_refresh.exchange_id == "DCE"
    assert before_refresh.quantity == Decimal("1")

    broker._sync_positions(force=True, raise_errors=True)

    after_refresh = broker.execution_position_snapshot(data)
    assert after_refresh.quantity == Decimal("1")


def test_periodic_refresh_routes_same_instrument_by_exchange_without_merging():
    dce_data = SimpleNamespace(
        _name="DCE.M",
        _dataname="M2612",
        p=SimpleNamespace(dataname="M2612"),
    )
    shfe_data = SimpleNamespace(
        _name="SHFE.M",
        _dataname="M2612",
        p=SimpleNamespace(dataname="M2612"),
    )
    metadata = {
        "DCE.M": {"instrument_id": "M2612", "exchange_id": "DCE"},
        "SHFE.M": {"instrument_id": "M2612", "exchange_id": "SHFE"},
    }
    rows = [
        {
            "symbol": "M2612",
            "instrument_id": "M2612",
            "exchange_id": "DCE",
            "direction": "long",
            "volume": 1,
            "price": 100,
        },
        {
            "symbol": "M2612",
            "instrument_id": "M2612",
            "exchange_id": "SHFE",
            "direction": "long",
            "volume": 2,
            "price": 101,
        },
    ]
    broker = make_position_sync_broker(
        [dce_data, shfe_data],
        rows,
        subscribed={"M2612"},
        contract_metadata=metadata,
    )

    broker._sync_positions(force=True, raise_errors=True)

    assert broker.execution_position_snapshot(dce_data).quantity == Decimal("1")
    assert broker.execution_position_snapshot(shfe_data).quantity == Decimal("2")
    assert set(broker.positions) == {"DCE.M", "SHFE.M"}


def test_ambiguous_position_route_keeps_existing_cache_and_raises():
    dce_data = SimpleNamespace(
        _name="DCE.M",
        _dataname="M2612",
        p=SimpleNamespace(dataname="M2612"),
    )
    shfe_data = SimpleNamespace(
        _name="SHFE.M",
        _dataname="M2612",
        p=SimpleNamespace(dataname="M2612"),
    )
    metadata = {
        "DCE.M": {"instrument_id": "M2612", "exchange_id": "DCE"},
        "SHFE.M": {"instrument_id": "M2612", "exchange_id": "SHFE"},
    }
    broker = make_position_sync_broker(
        [dce_data, shfe_data],
        [{"symbol": "M2612", "volume": 1, "price": 100, "direction": "long"}],
        subscribed={"M2612"},
        contract_metadata=metadata,
    )
    broker.positions["DCE.M"].update(3, 100)
    broker.positions["SHFE.M"].update(4, 101)

    with pytest.raises(ValueError, match="matches multiple tracked routes"):
        broker._sync_positions(force=True, raise_errors=True)

    assert broker.positions["DCE.M"].size == 3
    assert broker.positions["SHFE.M"].size == 4


def test_position_exchange_mismatch_does_not_replace_tracked_cache():
    data = SimpleNamespace(
        _name="DCE.M",
        _dataname="M2612",
        p=SimpleNamespace(dataname="M2612"),
    )
    broker = make_position_sync_broker(
        [data],
        [
            {
                "symbol": "M2612",
                "instrument_id": "M2612",
                "exchange_id": "SHFE",
                "volume": 1,
                "price": 100,
                "direction": "long",
            }
        ],
        subscribed={"M2612"},
        contract_metadata={"DCE.M": {"instrument_id": "M2612", "exchange_id": "DCE"}},
    )
    broker.positions["DCE.M"].update(3, 100)

    with pytest.raises(ValueError, match="identity conflicts with tracked route"):
        broker._sync_positions(force=True, raise_errors=True)

    assert broker.positions["DCE.M"].size == 3


def test_position_identity_cannot_override_contradictory_symbol_route():
    matching_data = SimpleNamespace(
        _name="DCE.M",
        _dataname="M2612",
        p=SimpleNamespace(dataname="M2612"),
    )
    conflicting_data = SimpleNamespace(
        _name="DCE.B",
        _dataname="B",
        p=SimpleNamespace(dataname="B"),
    )
    broker = make_position_sync_broker(
        [matching_data, conflicting_data],
        [
            {
                "symbol": "DCE.B",
                "instrument_id": "M2612",
                "exchange_id": "DCE",
                "volume": 1,
                "price": 100,
                "direction": "long",
            }
        ],
        contract_metadata={
            "DCE.M": {"instrument_id": "M2612", "exchange_id": "DCE"},
            "DCE.B": {"instrument_id": "B", "exchange_id": "DCE"},
        },
    )
    broker.positions["DCE.M"].update(3, 100)
    broker.positions["DCE.B"].update(4, 101)

    with pytest.raises(ValueError, match="symbol conflicts with provider identity route"):
        broker._sync_positions(force=True, raise_errors=True)

    assert broker.positions["DCE.M"].size == 3
    assert broker.positions["DCE.B"].size == 4


def test_unnamed_feed_keeps_its_original_position_key():
    data = SimpleNamespace(
        _name=None,
        _dataname="M2612",
        p=SimpleNamespace(dataname="M2612"),
    )
    broker = make_position_sync_broker(
        [data],
        [
            {"symbol": "M2612", "volume": 2, "price": 100, "direction": "long"},
            {"symbol": "UNTRACKED", "volume": 9, "price": 100, "direction": "long"},
        ],
        subscribed={"M2612"},
    )

    broker._sync_positions(force=True, raise_errors=True)

    assert broker.positions["M2612"].size == 2
    assert "UNTRACKED" not in broker.positions


def test_tracked_order_data_binds_native_instrument_to_feed_position_key():
    data = SimpleNamespace(
        _name="DCE.M",
        _dataname="M2612",
        p=SimpleNamespace(dataname="M2612"),
    )
    broker = make_position_sync_broker(
        [],
        [
            {
                "symbol": "M2612",
                "instrument_id": "M2612",
                "exchange_id": "DCE",
                "volume": 1,
                "price": 100,
                "direction": "long",
            }
        ],
        contract_metadata={"DCE.M": {"instrument_id": "M2612", "exchange_id": "DCE"}},
    )
    broker.orders[101] = SimpleNamespace(data=data, info={})

    broker._sync_positions(force=True, raise_errors=True)

    assert broker.positions["DCE.M"].size == 1
    assert "M2612" not in broker.positions


def test_sdk_startup_reconcile_uses_position_audit_interval_only():
    class ReconcileStore:
        def __init__(self):
            self.reconcile_calls = 0

        def enqueue_reconcile(self):
            self.reconcile_calls += 1
            return {"queued": True}

    store = ReconcileStore()
    startup = BtApiBroker(
        position_sync_policy="startup",
        position_audit_interval=10.0,
        account_refresh_interval=1.0,
        positions_refresh_interval=1.0,
        open_orders_refresh_interval=1.0,
    )
    startup.store = store
    startup._live_started = True

    startup._schedule_sdk_reconcile()
    scheduled_at = startup._last_position_audit
    assert store.reconcile_calls == 1
    assert scheduled_at > 0

    startup._periodic_reconcile_pending = False
    startup._schedule_sdk_reconcile()
    assert store.reconcile_calls == 1
    assert startup._last_position_audit == scheduled_at

    startup._last_position_audit = 0.0
    startup.orders[1] = SimpleNamespace(alive=lambda: True)
    startup._schedule_sdk_reconcile()
    assert store.reconcile_calls == 1

    startup.orders.clear()
    startup._pending_trade_updates.append({"client_order_id": "pending-trade"})
    startup._schedule_sdk_reconcile()
    assert store.reconcile_calls == 1
    startup._pending_trade_updates.clear()

    startup._periodic_reconcile_pending = False
    startup.p.position_audit_interval = 0.0
    startup._schedule_sdk_reconcile()
    assert store.reconcile_calls == 1
    assert startup.request_reconcile() == {"queued": True}
    assert store.reconcile_calls == 2

    periodic_store = ReconcileStore()
    periodic = BtApiBroker(
        position_sync_policy="periodic",
        position_audit_interval=0.0,
        account_refresh_interval=10.0,
        positions_refresh_interval=10.0,
        open_orders_refresh_interval=10.0,
    )
    periodic.store = periodic_store
    periodic._live_started = True
    periodic._last_account_refresh = float("inf")
    periodic._last_positions_refresh = float("inf")
    periodic._last_open_orders_refresh = float("inf")

    periodic._schedule_sdk_reconcile()
    assert periodic_store.reconcile_calls == 0
    periodic._last_positions_refresh = 0.0
    periodic._schedule_sdk_reconcile()
    assert periodic_store.reconcile_calls == 1


def test_unknown_position_sync_policy_is_rejected():
    with pytest.raises(ValueError, match="position_sync_policy"):
        setup_stack(policy="guess")


def test_startup_audit_reports_remote_drift_without_replacing_local_ledger(monkeypatch):
    """Startup policy must never re-import positions, but silent ledger drift
    (e.g. a lost WSS fill) has to surface as an audit event."""
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100, 102, 98, 100)]},
        positions=[{"symbol": DEFAULT_SYMBOL, "size": 0, "price": 0, "direction": "long"}],
    )
    store = make_store(api=client, config={"supports_dual_side": True})
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    data._start()
    assert data.load()
    broker = store.getbroker(
        position_mode="dual_side",
        position_sync_policy="startup",
        validation_enabled=False,
        force_refresh_queries=False,
        positions_refresh_interval=0,
        account_refresh_interval=3600,
        open_orders_refresh_interval=3600,
        position_audit_interval=0.001,
    )
    broker.start()
    try:
        order = broker.buy(
            None,
            data,
            size=2,
            price=101,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
        )
        client.push_broker_update(
            {
                "kind": "order",
                "bt_order_ref": order.ref,
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "status": "completed",
                "filled": 2,
                "avg_price": 100,
                "execution_source": "cumulative",
            }
        )
        broker._drain_store_updates()
        assert broker.getposition(data, side="long").size == 2

        client.positions = [
            {"symbol": DEFAULT_SYMBOL, "size": 5, "price": 100, "direction": "long"}
        ]
        emitted = []
        monkeypatch.setattr(broker, "_emit_runtime_event", lambda *a, **k: emitted.append((a, k)))
        broker.next()

        assert [a[0] for a, _ in emitted] == ["position_audit_mismatch"]
        mismatch = emitted[0][1]["mismatches"][0]
        assert mismatch["local_size"] == 2 and mismatch["remote_size"] == 5
        # Audit never overwrites the local ledger.
        assert broker.getposition(data, side="long").size == 2
    finally:
        broker.stop()


def test_startup_audit_skips_when_orders_are_in_flight(monkeypatch):
    client = FakeBtApiClient(
        history={DEFAULT_SYMBOL: [make_bar(0, 100, 102, 98, 100)]},
        positions=[{"symbol": DEFAULT_SYMBOL, "size": 0, "price": 0, "direction": "long"}],
    )
    store = make_store(api=client, config={"supports_dual_side": True})
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    data._start()
    assert data.load()
    broker = store.getbroker(
        position_mode="dual_side",
        position_sync_policy="startup",
        validation_enabled=False,
        force_refresh_queries=False,
        positions_refresh_interval=0,
        account_refresh_interval=3600,
        open_orders_refresh_interval=3600,
        position_audit_interval=0.001,
    )
    broker.start()
    try:
        client.positions = [
            {"symbol": DEFAULT_SYMBOL, "size": 5, "price": 100, "direction": "long"}
        ]
        emitted = []
        monkeypatch.setattr(broker, "_emit_runtime_event", lambda *a, **k: emitted.append((a, k)))
        alive = SimpleNamespace(alive=lambda: True)
        broker.orders[1] = alive
        broker.next()

        assert emitted == []
        assert broker.getposition(data, side="long").size == 0
    finally:
        broker.stop()


def test_position_audit_mismatch_blocks_opening_until_a_matching_audit_recovers():
    client, data, broker = setup_stack(initial=2, audit_interval=0.001)
    try:
        client.positions = [
            {"symbol": DEFAULT_SYMBOL, "size": 5, "price": 100, "direction": "long"}
        ]
        broker._last_position_audit = 0.0
        broker._maybe_audit_positions()

        assert broker._position_audit_blocked is True
        assert broker._position_audit_mismatch[0]["local_size"] == 2
        blocked = broker.buy(
            None,
            data,
            size=1,
            price=101,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
        )
        assert blocked.status == bt.Order.Rejected
        assert blocked.info["error_code"] == "position_audit_blocked"
        assert client.submitted_orders == []

        client.positions = [
            {"symbol": DEFAULT_SYMBOL, "size": 2, "price": 100, "direction": "long"}
        ]
        broker._last_position_audit = 0.0
        broker._maybe_audit_positions()

        assert broker._position_audit_blocked is False
        assert broker._position_audit_mismatch is None
        recovered = broker.buy(
            None,
            data,
            size=1,
            price=101,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
        )
        assert recovered.status == bt.Order.Accepted
        assert len(client.submitted_orders) == 1
    finally:
        broker.stop()


def test_position_audit_query_failure_blocks_opening_but_allows_bounded_close():
    client, data, broker = setup_stack(initial=2, audit_interval=0.001)
    healthy_get_positions = client.get_positions

    def failed_get_positions():
        raise RuntimeError("position service unavailable")

    client.get_positions = failed_get_positions
    try:
        broker._last_position_audit = 0.0
        broker._maybe_audit_positions()

        assert broker._position_audit_blocked is True
        assert broker._position_audit_error == "position service unavailable"
        opening = broker.buy(
            None,
            data,
            size=1,
            price=101,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
        )
        assert opening.status == bt.Order.Rejected
        assert opening.info["error_code"] == "position_audit_blocked"

        oversized_close = broker.sell(
            None,
            data,
            size=3,
            price=99,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="close_today",
            reduce_only=True,
        )
        assert oversized_close.status == bt.Order.Rejected
        assert oversized_close.info["error_code"] == "position_audit_close_not_reducing"

        close = broker.sell(
            None,
            data,
            size=1,
            price=99,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="close_yesterday",
            reduce_only=True,
        )
        assert close.status == bt.Order.Accepted
        assert len(client.submitted_orders) == 1
        assert client.submitted_orders[0]["offset"] == "close_yesterday"
    finally:
        client.get_positions = healthy_get_positions
        broker.stop()
