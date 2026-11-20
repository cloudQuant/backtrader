"""Credit interest is a cost for a short digital-currency position."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backtrader.comminfo import ComminfoDC
from backtrader.brokers import BackBroker
from backtrader.position import Position


def test_short_interest_is_positive_cost_with_multiplier():
    commission = ComminfoDC(interest=0.365, mult=2.0)
    opened = datetime(2025, 1, 1)
    position = SimpleNamespace(size=-3, price=100.0, datetime=opened)

    credit = commission.get_credit_interest(None, position, opened + timedelta(days=2))

    assert credit == pytest.approx(2 * (0.365 / 365) * 3 * 100 * 2)


def test_broker_deducts_short_interest_from_cash():
    broker = BackBroker(cash=1000)
    broker.addcommissioninfo(ComminfoDC(interest=0.365, mult=2.0))
    broker.start()
    opened = datetime(2025, 1, 1)
    data = MagicMock()
    data.datetime.datetime.return_value = opened + timedelta(days=2)
    data.close.__getitem__.return_value = 100
    position = Position(size=-3, price=100)
    position.datetime = opened
    position.adjbase = 100
    broker.positions[data] = position
    broker._no_open_positions = False

    broker.next()

    assert broker.getcash() == pytest.approx(1000 - 1.2)
