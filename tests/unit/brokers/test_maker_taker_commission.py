import pytest

from backtrader.comminfo import CommissionInfo
from backtrader.brokers.hft import QueueExchangeModel
from backtrader.brokers.tickbroker import TickBroker
from backtrader.events import OrderBookSnapshot, TickEvent
from backtrader.order import Order


class DummyData:
    def __init__(self, name="BTC/USDT"):
        self._name = name
        self.name = name
        self.symbol = name


class LegacyCommissionInfo(CommissionInfo):
    def _getcommission(self, size, price, pseudoexec):
        return abs(size) * price * self.p.commission


def test_comminfo_uses_role_specific_commission_rates_with_fallback():
    comminfo = CommissionInfo(
        commission=0.001,
        maker_commission=-0.0005,
        taker_commission=0.002,
    )

    assert comminfo.getcommission(1.0, 100.0, role="maker") == pytest.approx(-0.05)
    assert comminfo.getcommission(1.0, 100.0, role="taker") == pytest.approx(0.2)
    assert comminfo.getcommission(1.0, 100.0, role="unknown") == pytest.approx(0.1)


def test_comminfo_supports_legacy_getcommission_override_without_role():
    comminfo = LegacyCommissionInfo(commission=0.001)

    assert comminfo.getcommission(2.0, 100.0, role="maker") == pytest.approx(0.2)
    assert comminfo.confirmexec(3.0, 100.0, role="taker") == pytest.approx(0.3)


def test_broker_setcommission_supports_role_specific_rates():
    data = DummyData()
    broker = TickBroker(cash=1000.0)
    broker.setcommission(
        commission=0.001,
        maker_commission=-0.0005,
        taker_commission=0.002,
        name=data.name,
    )

    comminfo = broker.getcommissioninfo(data)

    assert comminfo.getcommission(1.0, 100.0, role="maker") == pytest.approx(-0.05)
    assert comminfo.getcommission(1.0, 100.0, role="taker") == pytest.approx(0.2)


def test_tickbroker_applies_maker_and_taker_commission_roles():
    data = DummyData()
    broker = TickBroker(cash=1000.0, exchange_model=QueueExchangeModel())
    broker.setcommission(
        commission=0.0,
        maker_commission=-0.001,
        taker_commission=0.002,
        name=data.name,
    )

    maker_order = broker.buy(owner=None, data=data, size=1, price=100.0, exectype=Order.Limit)

    broker.process_orderbook(
        OrderBookSnapshot(
            timestamp=1.0,
            symbol=data._name,
            bids=[(100.0, 1.0)],
            asks=[(101.0, 5.0)],
        )
    )
    broker.process_tick(TickEvent(timestamp=2.0, symbol=data._name, price=100.0, volume=2.0))

    taker_order = broker.sell(owner=None, data=data, size=1, price=101.0, exectype=Order.Market)
    broker.process_tick(TickEvent(timestamp=3.0, symbol=data._name, price=101.0, volume=2.0))

    assert maker_order.status == Order.Completed
    assert taker_order.status == Order.Completed
    assert broker.order_history[-2]["role"] == "maker"
    assert broker.order_history[-2]["commission"] == pytest.approx(-0.1)
    assert broker.order_history[-1]["role"] == "taker"
    assert broker.order_history[-1]["commission"] == pytest.approx(0.202)
    assert broker.getcash() == pytest.approx(1000.898)
