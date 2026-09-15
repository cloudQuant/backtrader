"""Tests for dual-side BtApiBroker functionality."""

import pytest

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.position import Position
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


def test_btapibroker_dual_side_getposition_keeps_clone_compatibility_before_start():
    """Test BtApiBroker dual side getposition keeps clone compatibility before start."""
    broker = BtApiBroker(store=None, position_mode="dual_side")
    data = type("SeededData", (), {"_name": DEFAULT_SYMBOL})()

    broker.long_positions[DEFAULT_SYMBOL] = Position(size=2.0, price=100.0)
    broker.short_positions[DEFAULT_SYMBOL] = Position(size=1.0, price=101.0)
    broker._sync_net_position(data)

    net_position = broker.getposition(data)
    cached_long = broker.getposition(data, clone=False, side="long")
    cached_short = broker.getposition(data, clone=False, side="short")

    assert net_position.size == pytest.approx(1.0)
    assert net_position is not broker.positions[DEFAULT_SYMBOL]
    assert cached_long is broker.long_positions[DEFAULT_SYMBOL]
    assert cached_short is broker.short_positions[DEFAULT_SYMBOL]
    assert cached_long.size == pytest.approx(2.0)
    assert cached_short.size == pytest.approx(1.0)

    report_state = broker.get_cached_report_state()
    report_legs = report_state["position_legs"][DEFAULT_SYMBOL]
    assert report_state["positions"][DEFAULT_SYMBOL].size == pytest.approx(1.0)
    assert report_legs["long"] is cached_long
    assert report_legs["short"] is cached_short


def test_btapibroker_dual_side_start_requires_provider_capability():
    """Test BtApiBroker dual side start requires provider capability."""
    client = FakeBtApiClient(
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2, "direction": "long"}]
    )
    store = make_store(api=client)
    broker = store.getbroker(position_mode="dual_side")

    with pytest.raises(ValueError, match="does not advertise support"):
        broker.start()


def test_btapibroker_dual_side_start_splits_provider_positions_when_capability_is_enabled():
    """Test BtApiBroker dual side start splits provider positions when capability is enabled."""
    client = FakeBtApiClient(
        positions=[
            {"instrument": DEFAULT_SYMBOL, "volume": 2, "direction": "long", "price": 100.0},
            {"instrument": DEFAULT_SYMBOL, "volume": 1, "direction": "short", "price": 101.0},
        ]
    )
    store = make_store(api=client, supports_dual_side=True)
    broker = store.getbroker(position_mode="dual_side")
    data = type("LiveData", (), {"_name": DEFAULT_SYMBOL})()

    broker.start()
    try:
        assert broker.getposition(data).size == pytest.approx(1.0)
        assert broker.getposition(data, clone=False, side="long").size == pytest.approx(2.0)
        assert broker.getposition(data, clone=False, side="short").size == pytest.approx(1.0)
    finally:
        broker.stop()


def test_btapibroker_dual_side_remote_trade_updates_keep_legs_separate():
    """Test BtApiBroker dual side remote trade updates keep legs separate."""
    client = FakeBtApiClient(
        positions=[],
        history={DEFAULT_SYMBOL: [make_bar(0, 100.0, 101.0, 99.0, 100.5)]},
    )
    store = make_store(api=client, supports_dual_side=True)
    broker = store.getbroker(position_mode="dual_side")
    data = store.getdata(dataname=DEFAULT_SYMBOL)

    data._start()
    assert data.load() is True
    broker.start()
    try:
        order = broker.buy(
            owner=None,
            data=data,
            size=1,
            price=101.0,
            exectype=bt.Order.Limit,
            position_side="long",
            offset="open",
        )

        client.push_broker_update(
            {
                "kind": "trade",
                "external_order_id": "btapi-1",
                "order_ref": "btapi-1",
                "trade_id": "dual-trade-1",
                "data_name": DEFAULT_SYMBOL,
                "side": "buy",
                "offset": "open",
                "size": 1,
                "price": 101.0,
                "timestamp": "09:30:00",
            }
        )
        client.positions = [
            {"instrument": DEFAULT_SYMBOL, "volume": 1, "direction": "long", "price": 101.0}
        ]

        broker.next()

        assert order.status == bt.Order.Completed
        assert broker.getposition(data).size == pytest.approx(1.0)
        assert broker.getposition(data, clone=False, side="long").size == pytest.approx(1.0)
        assert broker.getposition(data, clone=False, side="short").size == pytest.approx(0.0)
    finally:
        broker.stop()


def test_dual_side_sync_aggregates_distinct_position_rows_without_losing_gross():
    # CTP may split today/yesterday; MT5 may have multiple position tickets.
    client = FakeBtApiClient(
        positions=[
            {
                "instrument": DEFAULT_SYMBOL,
                "volume": 2,
                "direction": "long",
                "price": 100,
                "position_id": "a",
            },
            {
                "instrument": DEFAULT_SYMBOL,
                "volume": 1,
                "direction": "long",
                "price": 106,
                "position_id": "b",
            },
            {
                "instrument": DEFAULT_SYMBOL,
                "volume": 3,
                "direction": "short",
                "price": 110,
                "position_id": "c",
            },
        ]
    )
    store = make_store(api=client, supports_dual_side=True)
    broker = store.getbroker(position_mode="dual_side")
    data = type("LiveData", (), {"_name": DEFAULT_SYMBOL})()
    broker.start()
    try:
        assert broker.getposition(data, side="long").size == 3
        assert broker.getposition(data, side="long").price == pytest.approx(102)
        assert broker.getposition(data, side="short").size == 3
        assert broker.getposition(data, side="short").price == 110
        assert broker.getposition(data).size == 0
    finally:
        broker.stop()


@pytest.mark.parametrize("offset", ["close_today", "close_yesterday"])
@pytest.mark.parametrize("side", ["long", "short"])
def test_dated_dual_side_closes_preserve_offset_and_cannot_exceed_leg(offset, side):
    client = FakeBtApiClient(
        positions=[{"instrument": DEFAULT_SYMBOL, "volume": 1, "direction": side, "price": 100}],
        history={DEFAULT_SYMBOL: [make_bar(0, 100, 101, 99, 100)]},
    )
    store = make_store(api=client, supports_dual_side=True)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    data._start()
    assert data.load()
    broker = store.getbroker(position_mode="dual_side")
    broker.start()
    try:
        method = broker.sell if side == "long" else broker.buy
        order = method(
            owner=None,
            data=data,
            size=2,
            price=100,
            exectype=bt.Order.Limit,
            position_side=side,
            offset=offset,
        )
        assert order.info["offset"] == offset
        assert order.status == bt.Order.Rejected
        assert not client.submitted_orders
    finally:
        broker.stop()
        data.stop()
