"""Local validation consumes the public SDK's native quantity/price rules."""

import backtrader as bt
import pytest

from tests.fixtures.fake_btapi import FakeBtApiClient, make_bar, make_store


@pytest.mark.parametrize("position_mode", ["net", "dual_side"])
@pytest.mark.parametrize(
    "size,price,error_code",
    [
        (0.11, 80017.51, None),
        (0.115, 80017.51, "invalid_order_size_step"),
        (0.11, 80017.515, "invalid_price_tick"),
    ],
)
def test_normalized_native_lot_and_tick_rules_before_submission(
    position_mode, size, price, error_code
):
    symbol = "BTC-USDT-SWAP"
    client = FakeBtApiClient(
        balance={"cash": 5000.0, "value": 5000.0},
        history={symbol: [make_bar(0, 80000, 80020, 79950, 80000)]},
    )
    store = make_store(
        api=client,
        config={"supports_dual_side": True},
        contract_metadata={
            symbol: {
                "symbol": symbol,
                "asset_type": "swap",
                "quantity_unit": "contracts",
                "multiplier": 0.01,
                "lot_size": 0.01,
                "min_size": 0.01,
                "max_size": 1000000,
                "tick_size": 0.01,
                "settlement_currency": "USDT",
                "linear": True,
            }
        },
    )
    data = store.getdata(dataname=symbol)
    broker = store.getbroker(position_mode=position_mode, force_refresh_queries=False)
    broker.addcommissioninfo(
        bt.ComminfoFuturesPercent(commission=0.0005, mult=0.01, margin=1), name=symbol
    )
    data._start()
    assert data.load()
    broker.start()
    try:
        order = broker.buy(
            None,
            data,
            size=size,
            price=price,
            exectype=bt.Order.Limit,
            time_in_force="IOC",
            position_side="long",
            offset="open",
            reduce_only=False,
        )
        if error_code:
            assert order.status == bt.Order.Rejected
            assert order.info["error_code"] == error_code
            assert not client.submitted_orders
        else:
            assert order.status == bt.Order.Accepted
            assert len(client.submitted_orders) == 1
    finally:
        broker.stop()
