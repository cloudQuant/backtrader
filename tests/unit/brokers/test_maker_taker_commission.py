"""Tests for maker/taker commission model."""
import pytest

from backtrader.comminfo import (
    CommInfoBase,
    CommissionInfo,
    ComminfoFuturesInverse,
    ComminfoFuturesMixed,
    ComminfoFuturesPercent,
)
from backtrader.brokers.hft import QueueExchangeModel
from backtrader.brokers.tickbroker import TickBroker
from backtrader.events import OrderBookSnapshot, TickEvent
from backtrader.order import Order


class DummyData:
    """Dummy data source for testing."""

    def __init__(self, name="BTC/USDT"):
        """Initialize dummy data."""
        self._name = name
        self.name = name
        self.symbol = name


class LegacyCommissionInfo(CommissionInfo):
    """Legacy commission info with _getcommission override."""

    def _getcommission(self, size, price, pseudoexec):
        """Calculate commission using legacy method."""
        return abs(size) * price * self.p.commission


def test_comminfo_uses_role_specific_commission_rates_with_fallback():
    """Test CommissionInfo uses role-specific rates with fallback."""
    comminfo = CommissionInfo(
        commission=0.001,
        maker_commission=-0.0005,
        taker_commission=0.002,
    )

    assert comminfo.getcommission(1.0, 100.0, role="maker") == pytest.approx(-0.05)
    assert comminfo.getcommission(1.0, 100.0, role="taker") == pytest.approx(0.2)
    assert comminfo.getcommission(1.0, 100.0, role="unknown") == pytest.approx(0.1)


def test_comminfo_converts_role_specific_percentages_when_percabs_false():
    """Role-specific percentage rates must follow base commission conversion."""
    comminfo = CommInfoBase(
        commission=0.1,
        maker_commission=-0.02,
        taker_commission=0.05,
        open_commission=0.1,
        close_commission=0.2,
        close_today_commission=1.5,
        commtype=CommInfoBase.COMM_PERC,
        percabs=False,
        stocklike=True,
    )

    assert comminfo.get_param("commission") == pytest.approx(0.001)
    assert comminfo.getcommission(1.0, 100.0, role="maker") == pytest.approx(-0.02)
    assert comminfo.getcommission(1.0, 100.0, role="taker") == pytest.approx(0.05)
    assert comminfo.getcommission(1.0, 100.0, role="open") == pytest.approx(0.1)
    assert comminfo.getcommission(1.0, 100.0, role="close") == pytest.approx(0.2)
    assert comminfo.getcommission(1.0, 100.0, role="close_today") == pytest.approx(1.5)


def test_futures_comminfo_uses_offset_specific_commission_rates():
    """Futures schemes must distinguish open, close and close-today fees."""
    comminfo = ComminfoFuturesPercent(
        commission=0.0001,
        open_commission=0.000023,
        close_commission=0.00003,
        close_today_commission=0.000345,
        margin=0.12,
        mult=300,
    )

    assert comminfo.getcommission(1.0, 4000.0, role="open") == pytest.approx(27.6)
    assert comminfo.getcommission(1.0, 4000.0, role="close") == pytest.approx(36.0)
    assert comminfo.getcommission(1.0, 4000.0, role="close_today") == pytest.approx(414.0)
    assert comminfo.getcommission(1.0, 4000.0, role="close_yesterday") == pytest.approx(36.0)


def test_futures_mixed_comminfo_combines_percent_and_per_lot_fees():
    """CTP can report both amount-by-money and amount-by-volume fees."""
    comminfo = ComminfoFuturesMixed(
        commission=0.000023,
        open_commission=0.000023,
        close_commission=0.00003,
        close_today_commission=0.000345,
        commission_amount=1.2,
        open_commission_amount=1.2,
        close_commission_amount=2.0,
        close_today_commission_amount=4.5,
        margin=0.12,
        mult=300,
    )

    assert comminfo.getcommission(1.0, 4000.0, role="open") == pytest.approx(28.8)
    assert comminfo.getcommission(1.0, 4000.0, role="close") == pytest.approx(38.0)
    assert comminfo.getcommission(1.0, 4000.0, role="close_today") == pytest.approx(418.5)
    assert comminfo.getcommission(1.0, 4000.0, role="close_yesterday") == pytest.approx(38.0)


def test_inverse_futures_comminfo_uses_fixed_contract_value():
    """Inverse futures must not multiply fees, margin or PnL linearly by price."""
    comminfo = ComminfoFuturesInverse(
        commission=0.0005,
        maker_commission=-0.0001,
        margin=0.1,
        mult=100.0,
    )

    assert comminfo.getcommission(100, 50000.0) == pytest.approx(5.0)
    assert comminfo.getcommission(100, 50000.0, role="maker") == pytest.approx(-1.0)
    assert comminfo.get_margin(50000.0) == pytest.approx(10.0)
    assert comminfo.getoperationcost(100, 50000.0) == pytest.approx(1000.0)
    assert comminfo.profitandloss(100, 50000.0, 55000.0) == pytest.approx(1000.0)
    assert comminfo.profitandloss(-100, 50000.0, 45000.0) == pytest.approx(1000.0)


def test_comminfo_supports_legacy_getcommission_override_without_role():
    """Test legacy CommissionInfo with _getcommission override."""
    comminfo = LegacyCommissionInfo(commission=0.001)

    assert comminfo.getcommission(2.0, 100.0, role="maker") == pytest.approx(0.2)
    assert comminfo.confirmexec(3.0, 100.0, role="taker") == pytest.approx(0.3)


def test_broker_setcommission_supports_role_specific_rates():
    """Test broker setcommission supports role-specific rates."""
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


def test_broker_setcommission_supports_offset_specific_rates():
    """setcommission must expose futures open/close/close-today fee roles."""
    data = DummyData("IF2609")
    broker = TickBroker(cash=1000000.0)
    broker.setcommission(
        commission=0.01,
        open_commission=0.1,
        close_commission=0.2,
        close_today_commission=1.5,
        commtype=CommInfoBase.COMM_PERC,
        percabs=False,
        stocklike=True,
        name=data.name,
    )

    comminfo = broker.getcommissioninfo(data)

    assert comminfo.getcommission(1.0, 100.0, role="open") == pytest.approx(0.1)
    assert comminfo.getcommission(1.0, 100.0, role="close") == pytest.approx(0.2)
    assert comminfo.getcommission(1.0, 100.0, role="close_today") == pytest.approx(1.5)


def test_tickbroker_applies_maker_and_taker_commission_roles():
    """Test TickBroker applies maker and taker commission roles."""
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
