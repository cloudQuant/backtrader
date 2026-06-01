import pytest

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.position import Position
from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


def test_btapibroker_dual_side_getposition_keeps_clone_compatibility_before_start():
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


def test_btapibroker_dual_side_start_requires_provider_capability():
    client = FakeBtApiClient(positions=[{"instrument": DEFAULT_SYMBOL, "volume": 2, "direction": "long"}])
    store = make_store(api=client)
    broker = store.getbroker(position_mode="dual_side")

    with pytest.raises(ValueError, match="does not advertise support"):
        broker.start()


def test_btapibroker_dual_side_start_splits_provider_positions_when_capability_is_enabled():
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
