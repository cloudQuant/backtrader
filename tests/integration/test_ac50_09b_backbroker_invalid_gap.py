"""Ordinary Cerebro must leave pending orders untouched on an invalid bar."""

from datetime import date, datetime

import backtrader as bt
import pandas as pd
import pytest


class _PendingMarketAndLimit(bt.Strategy):
    params = (("initial_cash", 10_000.0),)

    def __init__(self):
        self.orders = []
        self.bar_states = []

    def next(self):
        self.bar_states.append(
            {
                "date": self.data.datetime.date(0),
                "cash": self.broker.getcash(),
                "position": self.getposition(self.data).size,
                "orders": tuple(
                    (
                        order.getstatusname(),
                        order.executed.size,
                        order.executed.price,
                        order.executed.dt,
                    )
                    for order in self.orders
                ),
            }
        )
        if not self.orders:
            self.orders.extend(
                (
                    self.buy(size=1, exectype=bt.Order.Market),
                    self.buy(size=1, exectype=bt.Order.Limit, price=9.0),
                )
            )


class _CapturePosition(bt.Strategy):
    def __init__(self):
        self.position_sizes = []
        self.completed_orders = []

    def next(self):
        self.position_sizes.append(self.getposition(self.data).size)

    def notify_order(self, order):
        if order.status == order.Completed:
            self.completed_orders.append(order)


@pytest.mark.parametrize("invalid_field", ("open", "high", "low", "close"))
def test_existing_market_and_limit_wait_through_nan_bar_then_fill_next_valid_bar(
    invalid_field,
):
    """A bad price cannot fill an order or contaminate BackBroker accounting."""
    frame = pd.DataFrame(
        {
            "open": (10.0, 10.0, 8.0),
            "high": (11.0, 11.0, 10.0),
            "low": (9.0, 9.0, 7.0),
            "close": (10.5, 10.5, 9.5),
            "volume": (1.0, 1.0, 1.0),
            "openinterest": (0.0, 0.0, 0.0),
        },
        index=pd.date_range("2025-01-01", periods=3, freq="D"),
    )
    frame.loc[frame.index[1], invalid_field] = float("nan")

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(10_000.0)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(_PendingMarketAndLimit)

    strategy = cerebro.run()[0]

    assert len(strategy.bar_states) == 3
    invalid_bar, valid_bar = strategy.bar_states[1:]
    assert invalid_bar["date"] == date(2025, 1, 2)
    assert invalid_bar["cash"] == 10_000.0
    assert invalid_bar["position"] == 0
    assert all(order[0] in ("Submitted", "Accepted") for order in invalid_bar["orders"])
    assert all(order[1] == 0 for order in invalid_bar["orders"])

    assert valid_bar["date"] == date(2025, 1, 3)
    assert valid_bar["position"] == 2
    assert [order.getstatusname() for order in strategy.orders] == ["Completed", "Completed"]
    assert [order.executed.price for order in strategy.orders] == [8.0, 8.0]
    assert all(
        bt.num2date(order.executed.dt).date() == date(2025, 1, 3) for order in strategy.orders
    )


def test_historical_order_keeps_its_explicit_price_on_nan_current_bar():
    """Historical orders use their declared price, not the current OHLC bar."""
    frame = pd.DataFrame(
        {
            "open": (10.0, float("nan"), 8.0),
            "high": (11.0, float("nan"), 10.0),
            "low": (9.0, float("nan"), 7.0),
            "close": (10.5, float("nan"), 9.5),
            "volume": (1.0, 0.0, 1.0),
            "openinterest": (0.0, 0.0, 0.0),
        },
        index=pd.date_range("2025-01-01", periods=3, freq="D"),
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(10_000.0)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(_CapturePosition)
    cerebro.broker.add_order_history(((datetime(2025, 1, 2), 1, 5.0),))

    strategy = cerebro.run()[0]

    assert strategy.position_sizes == [0, 1, 1]
    assert len(strategy.completed_orders) == 1
    historical = strategy.completed_orders[0]
    assert historical.getstatusname() == "Completed"
    assert historical.executed.price == 5.0
    assert bt.num2date(historical.executed.dt).date() == date(2025, 1, 2)
