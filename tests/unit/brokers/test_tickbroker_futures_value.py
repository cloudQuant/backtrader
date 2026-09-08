"""Independent cash/PnL oracles for native futures quantities on book feeds."""

from types import SimpleNamespace

import pytest

from backtrader.brokers.mixbroker import MixBroker
from backtrader.comminfo import ComminfoFuturesPercent
from backtrader.events import OrderBookSnapshot, TickEvent
from backtrader.order import Order


def book(price, timestamp):
    return OrderBookSnapshot(
        symbol="BTC-USDT-SWAP",
        timestamp=timestamp,
        local_time=timestamp,
        bids=[(price, 100)],
        asks=[(price, 100)],
        asset_type="swap",
    )


def configured_broker(commission=0, **kwargs):
    broker = MixBroker(cash=2000, **kwargs)
    broker.addcommissioninfo(
        ComminfoFuturesPercent(commission=commission, mult=0.01, margin=1),
        name="BTC-USDT-SWAP",
    )
    return broker, SimpleNamespace(_name="BTC-USDT-SWAP")


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_book_only_futures_value_matches_round_trip_cash(side):
    broker, data = configured_broker(commission=0.0005)
    opening = getattr(broker, side)(None, data, size=0.2, exectype=Order.Market)
    broker.process_orderbook(book(60000, 1), data)
    assert opening.status == Order.Completed
    assert broker.getcash() == pytest.approx(2000 - 120 - 0.06)
    assert broker.getvalue() == pytest.approx(2000 - 0.06)
    broker.process_orderbook(book(61000, 2), data)
    pnl = 2 if side == "buy" else -2
    assert broker.getvalue() == pytest.approx(2000 - 0.06 + pnl)
    # Valuation reads must not accumulate cash adjustments.
    assert broker.getvalue() == pytest.approx(2000 - 0.06 + pnl)
    closing = getattr(broker, "sell" if side == "buy" else "buy")(
        None, data, size=0.2, exectype=Order.Market
    )
    broker.process_orderbook(book(61000, 3), data)
    assert closing.status == Order.Completed
    assert broker.getposition(data).size == pytest.approx(0)
    assert broker.getcash() == pytest.approx(2000 + pnl - 0.06 - 0.061)
    assert broker.getvalue() == pytest.approx(broker.getcash())


def test_scaled_futures_position_does_not_double_count_settled_pnl():
    broker, data = configured_broker()
    broker.buy(None, data, size=0.2, exectype=Order.Market)
    broker.process_orderbook(book(60000, 1), data)
    broker.buy(None, data, size=0.1, exectype=Order.Market)
    broker.process_orderbook(book(61000, 2), data)
    assert broker.getvalue() == pytest.approx(2002)
    broker.sell(None, data, size=0.15, exectype=Order.Market)
    broker.process_orderbook(book(62000, 3), data)
    assert broker.getvalue() == pytest.approx(2005)
    broker.sell(None, data, size=0.15, exectype=Order.Market)
    broker.process_orderbook(book(62000, 4), data)
    assert broker.getcash() == pytest.approx(2005)


def test_futures_mark_uses_newest_market_event():
    broker, data = configured_broker()
    broker.buy(None, data, size=0.2, exectype=Order.Market)
    broker.process_tick(TickEvent(symbol=data._name, timestamp=1, price=60000, volume=1))
    broker.process_orderbook(book(61000, 2), data)
    assert broker.getvalue() == pytest.approx(2002)
    broker.process_tick(TickEvent(symbol=data._name, timestamp=3, price=62000, volume=1))
    assert broker.getvalue() == pytest.approx(2004)


def test_hedge_mode_values_native_futures_legs_separately():
    broker, data = configured_broker(position_mode="dual_side")
    broker.buy(None, data, size=0.2, exectype=Order.Market, position_side="long", offset="open")
    broker.sell(None, data, size=0.1, exectype=Order.Market, position_side="short", offset="open")
    broker.process_orderbook(book(60000, 1), data)
    assert broker.getvalue() == pytest.approx(2000)
    broker.process_orderbook(book(61000, 2), data)
    assert broker.getvalue() == pytest.approx(2001)
