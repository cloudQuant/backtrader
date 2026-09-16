"""Explicit startup position baselines cannot overlap later execution callbacks."""

import backtrader as bt
import pytest

from types import SimpleNamespace
import collections

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.position import Position
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


def setup_stack(mode="dual_side", policy="startup", initial=0, start_feed=True, audit_interval=0.0):
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
    return (
        broker.getposition(data, side=side)
        if broker.p.position_mode == "dual_side"
        else broker.getposition(data)
    )


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
